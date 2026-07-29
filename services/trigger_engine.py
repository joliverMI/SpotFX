"""
SpotFX — Music Event Trigger Engine.

Watches the interpolated playback position and fires MusicTriggers at the
right moment, accounting for:
  - audio_latency_ms  (external, configured in settings)
  - ledfx_trigger_buffer_ms  (user buffer; positive = fire earlier)
  - state.ledfx_rtt_ms  (measured LedFX round-trip time)
  - AudioShapeMeta.timestamp_offset_ms  (capture timing correction; cached per song)

Algorithm:
  Every TICK_MS, compute the "effective now" in song-ms, then check whether
  any trigger's timestamp_ms falls in the window [last_tick, now).
  Each trigger is fired at most once per playback of that song.
"""
from __future__ import annotations
import asyncio
import colorsys
import logging
import random
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field as dc_field
from typing import NamedTuple, Optional

from config import settings
from models.state import state
from models.song_profile import SongProfile, MusicTrigger
from models.music_event import MusicEvent, Action
from services.profile_manager import get_event
from services.audio_analyzer import load_audio_shape_meta, load_beats_for_uri, load_tempo_for_uri
from services.device_category_service import get_virtuals_for_role
from services.signal_resolver import resolve_action_bindings, resolve_signal, static_ramp_ms

# Per-fire trigger intensity for the "trigger_intensity" binding signal.
# Both fire paths run in their own asyncio task (copied Context), so setting
# this at fire entry can't leak across overlapping fires. Manual event fires
# never set it → bindings resolve to their fallback.
_FIRE_INTENSITY: ContextVar[float | None] = ContextVar("spotfx_fire_intensity", default=None)
# Per-fire scene-group color override (MusicTrigger.color_group_override): a
# ColorSetCard group id that replaces the scene group's designated Color Group
# whenever this fire resolves the "__scene_group__" sentinel. Same task-scoped
# lifetime as _FIRE_INTENSITY; unset/None = normal resolution.
_FIRE_COLOR_GROUP: ContextVar[str | None] = ContextVar("spotfx_fire_color_group", default=None)
from services.effect_params import get_all_virtual_ids
from services.websocket_manager import ws_manager
from api import ledfx_client

logger = logging.getLogger(__name__)

TICK_MS = 50  # engine resolution — 50 ms tick
STALE_FIRE_MS = 2000  # any trigger whose anchor is more than this far behind song position is silently marked fired (covers startup/long seek, leaves room for normal playback jitter)

# Scene events: the user-created scene_update (lanes below) plus the fixed
# built-ins that re-run one or more of its lanes against the last fired
# scene_update. Indices into a scene_update's morph_lanes.
SCENE_LANE_NAMES = ["First", "Rest", "Shape", "Color"]
SCENE_EVENT_TYPES = (
    "scene_update", "update_scene", "reset_scene",
    "shape_flare", "color_flare", "combo_flare",
    "scene_group",
)
# Params whose value change makes LedFX re-instantiate (reset) the effect.
# These must be written instantly (ramping them flickers/restarts the effect),
# and Set Color's "preserve effect" mode skips them entirely. The canonical
# set covers unmodeled effects; effect_params may also flag `resets_effect`.
# Empty since the 2026-07-10 ledfx-src patch: virtual_effects.py excludes
# background_* keys from the color-recreation branch, so background_color
# (the only former member) now updates in place like gradient.
RESET_EFFECT_PARAMS: set[str] = set()


def _param_resets_effect(effect_type: str, param: str) -> bool:
    if param in RESET_EFFECT_PARAMS:
        return True
    from services.effect_params import get_param_meta
    meta = get_param_meta(effect_type, param) or {}
    return bool(meta.get("resets_effect"))


# fixed-event type → lane indices to run against the last scene_update.
_FLARE_LANES = {
    "update_scene": [1],     # Rest
    "reset_scene":  [0],     # First
    "shape_flare":  [2],     # Shape
    "color_flare":  [3],     # Color
    "combo_flare":  [2, 3],  # Shape + Color in parallel
}


class MorphPick(NamedTuple):
    """One lane's resolved pick for a morph_set fire: the picked Action plus the
    lane's timing offset (ms; negative = earlier, positive = later). Carrying
    `offset_ms` per pick lets the dispatch stagger lanes relative to the trigger
    point. `offset_ms` is a property of the LANE, not the picked alternative, so
    it's stable across re-rolls of which alternative a lane chooses."""
    lane_name: str
    action: Action
    offset_ms: int = 0


@dataclass
class _PlanEntry:
    """
    One atomic fire in the planned trigger timeline.

    The planner walks the resolved event tree from a trigger, compounds
    `event_offset_ms` down the chain, turns sequence `step.delay_ms` and
    beat-sequence step spacing into absolute song-ms, and emits one entry
    per event body (not per event_ref — singles with event_ref are transparent).

    Each entry's execution skips its `planned_descendant_ids` — those sub-events
    already have their own entries so we don't double-fire them.
    """
    fire_at_ms: int                               # absolute song-ms to fire this event
    event: MusicEvent                             # event whose body executes
    labels: list[str] = dc_field(default_factory=list)
    trigger_ms: int = 0                           # root trigger timestamp (for logs)
    trigger_id: str = ""                          # root trigger id (to check _pre_fired at exec time)
    trigger_intensity: float = 0.5                # firing trigger's intensity (0-1, scaler applied at plan time)
    trigger_color_group: Optional[str] = None     # firing trigger's scene-group color override (card id)
    is_root: bool = False                         # True only for the root entry of a trigger's plan
    planned_descendant_ids: set[str] = dc_field(default_factory=set)
    preselected_action: Optional[Action] = None   # for "single" events — action chosen at plan time
    preselected_steps: Optional[list] = None      # for "sequence" events — per-step action pre-selection
    preselected_morph_picks: Optional[list] = None  # for "morph_set" events — per-lane pre-picks (list[MorphPick])
    morph_anchor_offset_ms: int = 0               # earliest lane offset; fire_at_ms is start_at + this (lanes sleep offset - anchor)
    # For "composite" events — plan-time resolution of every random_group in the
    # tree (group.id → RandomOption.id) so previews match fires and scene-override
    # can pre-stage. Fire-time falls back to fresh picks when None.
    resolved_picks: Optional[dict] = None
    # For scene-family events — lane picks locked at plan time (list of
    # (lane_index, Action)) so the Now Playing preview shows exactly what will
    # change. `scene_picks_sid` is the _last_scene_update_id the picks were
    # rolled against; fire-time re-rolls when it no longer matches (a Scene
    # Update fired in between), so a stale preview never fires stale lanes.
    preselected_scene_picks: Optional[list] = None
    scene_picks_sid: Optional[str] = None
    # Event the scene picks were rolled against (the Force Scene target when
    # active, else the entry's own event / last Scene Update for flares).
    scene_picks_event_id: Optional[str] = None
    snapshot_task: Optional[asyncio.Task] = None  # pre-fire snapshot of the LedFX state this event will change
    # Scene-override lookahead: planner pre-stages the temp scene + transition_times
    # ahead of fire_at_ms; fire-time just activates the prepared scene.
    scene_override_prepared: bool = False
    scene_override_payload: Optional[dict] = None
    fired: bool = False


def _resolve_shape_offset(meta) -> tuple[int, float, str]:
    """Pick the right offset slot for the current Set List context, then
    layer the user's perception trim on top. Uses the median of recent
    saved locks (when present) instead of the latest one alone — keeps a
    single noisy save from displacing a stable baseline.

    When no per-(track, Set List) entry exists yet, fall back to the
    track's default offset PLUS the active Set List's recent-deltas bias
    (median of the last few "lock − baseline" deltas observed in this
    Set List), so the first play of an unseen track in a mix-warped
    Set List doesn't start cold.

    Returns (effective_offset_ms, quality, source_label).
    """
    if meta is None:
        return 0, 0.0, "default"
    sl_id = state.active_setlist_id
    if sl_id:
        sl_entry = (meta.setlist_offsets or {}).get(sl_id)
        if sl_entry:
            history = sl_entry.get("history") or []
            base = _median_offset_local(history)
            if base is None:
                base = int(sl_entry.get("timestamp_offset_ms", 0))
            quality = float(sl_entry.get("offset_quality", 0.0))
            trim = int(sl_entry.get("perception_trim_ms", 0))
            return _layer_systemic(base + trim, quality, f"setlist:{sl_id}")
        # No entry yet — bias the default by the Set List's recent deltas.
        bias = _setlist_delta_bias(sl_id)
        if bias != 0:
            base = int(meta.timestamp_offset_ms or 0) + bias
            quality = float(meta.offset_quality or 0.0)
            trim = int(getattr(meta, "perception_trim_ms", 0) or 0)
            return _layer_systemic(base + trim, quality,
                                   f"default+setlist_bias:{bias:+d}")
    base = int(meta.timestamp_offset_ms or 0)
    quality = float(meta.offset_quality or 0.0)
    trim = int(getattr(meta, "perception_trim_ms", 0) or 0)
    return _layer_systemic(base + trim, quality, "default")


def _layer_systemic(offset_ms: int, quality: float, source: str) -> tuple[int, float, str]:
    """Add the systemic starting-offset bias, then the active timing device's
    offset, on top of the per-song / per-Set-List resolution. The systemic
    layer is a cold-start aid only — this play's own xcorr re-lock overrides
    it via apply_save; inert unless the learner is enabled and confident
    (see services/systemic_offset.py). The device layer is the manual trim
    for the active snapcast client (settings.timing_device_offsets keyed by
    settings.active_timing_device) and applies unconditionally."""
    try:
        from services import systemic_offset
        pred = systemic_offset.predict()
        if pred.bias_ms != 0:
            offset_ms += pred.bias_ms
            source = f"{source}+systemic:{pred.bias_ms:+d}@{pred.confidence:.2f}"
    except Exception:
        pass
    dev_ms, dev_name = _device_offset()
    if dev_ms != 0:
        offset_ms += dev_ms
        source = f"{source}+dev:{dev_name}:{dev_ms:+d}"
    return offset_ms, quality, source


def _device_offset() -> tuple[int, str]:
    """(offset_ms, name) for the active timing device — 0 when unset."""
    name = str(getattr(settings, "active_timing_device", "default") or "default")
    offsets = getattr(settings, "timing_device_offsets", {}) or {}
    try:
        return int(offsets.get(name, 0) or 0), name
    except (TypeError, ValueError):
        return 0, name


def _perception_trim_for(meta) -> int:
    """Return the perception trim that applies for the current Set List context."""
    if meta is None:
        return 0
    sl_id = state.active_setlist_id
    if sl_id:
        sl_entry = (meta.setlist_offsets or {}).get(sl_id) or {}
        return int(sl_entry.get("perception_trim_ms", 0))
    return int(getattr(meta, "perception_trim_ms", 0) or 0)


def _median_offset_local(history: list) -> int | None:
    vals = sorted(int(h.get("offset_ms", 0)) for h in (history or []) if h)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) // 2


def _setlist_delta_bias(setlist_id: str) -> int:
    """Median of recent (lock - baseline) deltas observed while this Set
    List was active. Used as a starting bias for tracks the Set List
    hasn't seen yet. Returns 0 when there's not enough history."""
    try:
        from services import setlist_store
        sl = setlist_store.get_by_id(setlist_id)
    except Exception:
        return 0
    if not sl or not sl.recent_offset_deltas or len(sl.recent_offset_deltas) < 2:
        return 0
    vals = sorted(int(d) for d in sl.recent_offset_deltas)
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) // 2


class TriggerEngine:
    """
    Runs a loop that fires triggers against the current song profile.
    Instantiate one and call run().
    """

    def __init__(self):
        self._profile: Optional[SongProfile] = None
        self._fired: set[str] = set()          # trigger ids fired this playback
        self._pre_fired: set[str] = set()      # trigger ids whose step-1 pre-ramp has fired
        self._last_uri: str = ""
        self._last_progress_ms: int = 0
        # Track last called action per event id to avoid immediate repeat
        self._last_action: dict[str, str] = {}  # event_id -> action index/key
        # Color Group selection state (in-memory, reset on track change like
        # _last_action). Cursor = last index served per group; dir = +1/-1 for
        # bounce traversal.
        self._color_cursor: dict[str, int] = {}
        self._color_cursor_dir: dict[str, int] = {}
        # Index served two fires ago per group — used to break a bounce ping-pong
        # when advance > 1 (e.g. n=3 advance=2 would otherwise loop 0,2,0,2).
        self._color_cursor_prev: dict[str, int] = {}
        # Palette Sync: room-wide hue (0..360) of the last set applied via a
        # palette_sync group. Unlike the cursors this survives track changes —
        # it mirrors what's physically showing on the lights, so the next song
        # (or another synced group) continues from the room's actual palette.
        self._palette_hue: Optional[float] = None
        # Last fired Color Set's 3rd (accent) color per virtual, recorded as a
        # Color Set is applied. value may be None when that set's entry left the
        # accent undefined. On an effect switch to an accent-capable effect
        # (power/eq2d) the new effect's accent is sourced from here, else black.
        # Persists across songs (intentionally NOT cleared on track change) —
        # it tracks the most recent Color Set fired, not per-track selection.
        self._last_accent_by_vid: dict[str, Optional[str]] = {}
        # Shape-nudge bounce direction per "{virtual_id}::{param}" (in-memory,
        # reset on track change). Used when a Shape sub-field nudge has wrap=True.
        self._nudge_dir: dict[str, int] = {}
        # Id of the last fired scene_update event. Decides First vs Rest and is the
        # target for the fixed Update/Reset Scene events. Persists across songs
        # (intentionally NOT cleared on track change).
        self._last_scene_update_id: Optional[str] = None
        # Scene Group selection state (mirrors the _color_cursor trio above,
        # keyed by the scene_group EVENT id). Unlike color cursors these are
        # intentionally NOT cleared on track change — like _last_scene_update_id
        # they track room continuity: a forced group rotating across a set
        # keeps rotating rather than restarting at member 0 each song.
        self._scene_cursor: dict[str, int] = {}
        self._scene_cursor_dir: dict[str, int] = {}
        self._scene_cursor_prev: dict[str, int] = {}
        # Id of the scene_group event currently driving the scene (set when a
        # group fires or Scene Morph steps it; cleared when a plain
        # scene_update is picked directly). Scene Morph acts on this group.
        self._active_scene_group_id: Optional[str] = None
        # Genre intensity-scale fallback, cached per uri (recomputed on track
        # change; the song's own intensity_scale bypasses this entirely).
        self._genre_scale_uri: Optional[str] = None
        self._genre_scale_cache: float = 1.0
        # Scene-family fire counter + condition for sequence "updates" waits:
        # bumped on EVERY scene-family fire (scene picks, Update/Reset Scene,
        # flares — including no-op flares — and Scene Morph). Waiters compare
        # against an absolute target so wakeups can't be lost.
        self._scene_fire_seq: int = 0
        self._scene_fire_cond: asyncio.Condition = asyncio.Condition()
        self._shape_offset_ms: int = 0       # cached from AudioShapeMeta.timestamp_offset_ms
        self._shape_offset_quality: float = 0.0  # cached quality score (r × difficulty)
        # Highest match-quality observed during the current play. Reset on URI
        # change. Anchor and sweep saves only override the engine's live offset
        # when their quality strictly beats this — gives priority to confident
        # matches mid-play while still letting median (loaded at song start)
        # be the floor when no match clears it.
        self._play_best_quality: float = 0.0
        # Loaded offset at song start (median + trim). Used as the reference
        # for the in-song drift cap: mid-play saves more than
        # `engine_in_song_drift_cap_ms` away from this are rejected as
        # likely beat-tile false matches.
        self._loaded_offset_ms: int = 0
        # Per-song librosa cache — avoids re-reading the JSON every beat-sequence fire.
        self._beats_cache: Optional[list] = None
        self._sections_cache: Optional[list] = None  # librosa sections for value bindings
        self._tempo_cache: Optional[float] = None
        # Pre-selection state for trigger preview
        self._preselected: dict[str, Action] = {}           # trigger_id → pre-selected action (single events)
        self._preselected_steps: dict[str, list] = {}       # trigger_id → [Optional[Action], ...] (sequence steps)
        self._last_preview_id: Optional[str] = None         # id of last previewed trigger (dedup guard)
        # Planned timeline for upcoming trigger — flat list of atomic fires
        self._plan: dict[str, list[_PlanEntry]] = {}  # trigger_id → entries (absolute song-ms)
        self._plan_desc: dict[str, str] = {}          # trigger_id → drill-down preview label
        # AI suggestion set triggers (cached per song, used when use_unreviewed_ai_triggers is on)
        self._ai_triggers: Optional[list[MusicTrigger]] = None
        # Analyzed triggers: generated by embedded pipeline from librosa data
        self._analyzed_triggers: Optional[list[MusicTrigger]] = None
        # Triggerless play: synthetic triggers generated at song load
        self._triggerless_triggers: Optional[list[MusicTrigger]] = None
        # Ramp task registry — tracked so they can be cancelled on song change
        self._ramp_tasks: set[asyncio.Task] = set()
        # Pending revert state per target virtual — lets an overlapping flip
        # steal the prior snapshot and cancel its revert, so the final revert
        # always restores to the truly-clean pre-first-flip color regardless
        # of how many flips interleave. See plan section "added, 4".
        # {vid: (snapshot, revert_cfg, revert_task)}
        self._pending_ambient_revert: dict[str, tuple[dict, object, asyncio.Task]] = {}

    def _spawn_ramp(self, coro) -> asyncio.Task:
        """Create a tracked ramp task. All ramp tasks should use this instead of create_task."""
        task = asyncio.create_task(coro)
        self._ramp_tasks.add(task)
        task.add_done_callback(self._ramp_tasks.discard)
        return task

    @staticmethod
    async def _await_ramps_parallel(jobs: list) -> None:
        """Await one step's collected per-device ramps CONCURRENTLY: every
        device starts its ramp together and the step completes with the
        slowest. (Awaiting them inline chained device after device — with
        server-side tween each call holds for its full ramp_ms, so an N-device
        Set Color visibly cascaded for N x ramp_ms instead of changing as one.)

        jobs: (coro, cfg_or_None, patch_or_None); each cache patch is applied
        after the gather so a following sequence step reads post-ramp values.
        One device's ramp failure doesn't abort its siblings'."""
        if not jobs:
            return
        await asyncio.gather(*(c for c, _, _ in jobs), return_exceptions=True)
        for _, cfg, patch in jobs:
            if cfg is not None and patch:
                cfg.update(patch)

    def load_profile(self, profile: SongProfile) -> None:
        self._profile = profile
        logger.info(
            "load_profile: uri=%s last_uri=%s (change=%s)",
            profile.spotify_uri, self._last_uri,
            profile.spotify_uri != self._last_uri,
        )
        if profile.spotify_uri != self._last_uri:
            for task in list(self._ramp_tasks):
                task.cancel()
            self._ramp_tasks.clear()
            self._fired.clear()
            self._pre_fired.clear()
            self._last_action.clear()
            self._color_cursor.clear()
            self._color_cursor_dir.clear()
            self._color_cursor_prev.clear()
            self._nudge_dir.clear()
            self._preselected.clear()
            self._preselected_steps.clear()
            self._plan.clear()
            self._plan_desc.clear()
            self._last_preview_id = None
            self._last_uri = profile.spotify_uri
            # Scene cursors / active group intentionally NOT cleared (room
            # continuity — see __init__). But wake any sequence "updates"
            # waiters so an updates-only wait (delay_ms=0) releases via its
            # track-change predicate instead of spanning songs.
            try:
                asyncio.get_running_loop().create_task(self._wake_scene_waiters())
            except RuntimeError:
                pass  # no running loop (offline scripts) — nothing can be waiting
            # Auto intensity scale: songs with no scaler yet get the library-
            # ranked starting value stamped (source="auto"). Runs off-loop —
            # the first call sweeps the whole library feature cache.
            try:
                asyncio.get_running_loop().create_task(self._auto_intensity_scale(profile))
            except RuntimeError:
                pass
            # New song — clear the play-best floor so any anchor or sweep
            # save this play can override the median-derived starting baseline.
            self._play_best_quality = 0.0
            meta = load_audio_shape_meta(profile.spotify_uri)
            # Resolve the offset from whichever slot fits the current context
            # (Set List override or default), then layer the user's perception
            # trim on top so subjective alignment persists across plays.
            self._shape_offset_ms, self._shape_offset_quality, sl_source = _resolve_shape_offset(meta)
            self._loaded_offset_ms = self._shape_offset_ms
            logger.info(
                "load_profile: shape_offset_ms=%+d Q=%.2f source=%s",
                self._shape_offset_ms, self._shape_offset_quality, sl_source,
            )
            # Pre-load librosa beats/tempo once so beat-sequence fires don't
            # each re-parse the JSON file from disk.
            self._beats_cache = load_beats_for_uri(profile.spotify_uri)
            from services.audio_analyzer import load_sections_for_uri
            self._sections_cache = load_sections_for_uri(profile.spotify_uri)
            self._tempo_cache = load_tempo_for_uri(profile.spotify_uri)
            # Cache AI suggestion set as MusicTrigger list for this song
            from services.suggestion_store import load_suggestion_set
            track_id = profile.spotify_uri.split(":")[-1]
            sug_set = load_suggestion_set(track_id)
            if sug_set and sug_set.suggestions:
                self._ai_triggers = [
                    MusicTrigger(
                        id=f"ai_{s.event_id}_{s.timestamp_ms}",
                        timestamp_ms=s.timestamp_ms,
                        event_id=s.event_id,
                        labels=s.labels,
                    )
                    for s in sug_set.suggestions
                ]
            else:
                self._ai_triggers = None
            # Generate analyzed triggers from embedded pipeline (if librosa data exists)
            self._analyzed_triggers = self._generate_analyzed_triggers(profile.spotify_uri)
            # Generate synthetic triggerless triggers if needed.
            # Dinner Party mode always wins — its synthetic triggers come from the
            # "Dinner Party" profile regardless of whether analyzed triggers exist.
            if self._should_use_triggerless():
                if state.dinner_party_mode:
                    tp = self._resolve_triggerless_profile()
                    if tp:
                        self._triggerless_triggers = self._generate_triggerless_triggers(
                            tp, profile.duration_ms
                        )
                        logger.info("Triggerless: generated %d synthetic triggers from '%s' (dinner party)",
                                    len(self._triggerless_triggers), tp.name)
                    else:
                        self._triggerless_triggers = None
                elif state.use_analyzed_triggerless and self._analyzed_triggers:
                    self._triggerless_triggers = None
                    logger.info("Using analyzed triggers (%d) instead of synthetic triggerless",
                                len(self._analyzed_triggers))
                else:
                    tp = self._resolve_triggerless_profile()
                    if tp:
                        self._triggerless_triggers = self._generate_triggerless_triggers(
                            tp, profile.duration_ms
                        )
                        logger.info("Triggerless: generated %d synthetic triggers from '%s'",
                                    len(self._triggerless_triggers), tp.name)
                    else:
                        self._triggerless_triggers = None
            else:
                self._triggerless_triggers = None

            # Genre Blending: if the previous song ended naturally and shares a
            # genre with the incoming song, pre-mark any "start" triggers as
            # fired so they won't fire on the first tick.
            self._apply_genre_blend_on_load()

            # Fire any near-start trigger immediately if the song is already
            # past it. Covers mid-song skips: Spotify reports a non-zero
            # position on skip, and by the time the main loop ticks, triggers
            # at small timestamps (e.g. 0, 350ms) land past STALE_FIRE_MS and
            # get silently suppressed. Users often anchor Song Start slightly
            # off zero, so we can't rely on `== 0`. The `< now_ms` guard
            # keeps fresh plays flowing through the main loop at the right
            # moment instead of pre-firing here.
            _now_ms = state.current_track.interpolated_progress_ms() if state.current_track else 0
            start_trig = next(
                (
                    t for t in self._get_active_triggers()
                    if t.enabled
                    and t.timestamp_ms <= STALE_FIRE_MS
                    and t.timestamp_ms < _now_ms
                    and t.id not in self._fired
                ),
                None,
            )
            if start_trig:
                # Mark fired so the main loop doesn't try again; but only
                # actually fire when the service is active. The main per-tick
                # firing path also respects state.paused — this branch was
                # bypassing it and firing Song Start regardless.
                self._fired.add(start_trig.id)
                self._pre_fired.add(start_trig.id)
                if state.paused:
                    logger.info(
                        "load_profile: skipping Song Start trigger %s — service paused",
                        start_trig.id,
                    )
                else:
                    asyncio.create_task(
                        self.fire_event_now(start_trig.event_id, start_trig.labels)
                    )
                    logger.info(
                        "load_profile: firing Song Start trigger %s immediately (event=%s)",
                        start_trig.id, start_trig.event_id,
                    )

    def _start_trigger_ids(self) -> list[str]:
        """IDs of triggers whose resolved event name contains 'start' (case-insensitive).

        Only considers the currently-active trigger source (user / analyzed /
        triggerless / ai) so we don't suppress triggers that won't fire anyway.
        """
        ids: list[str] = []
        for trig in self._get_active_triggers():
            if not trig.enabled:
                continue
            ev = get_event(trig.event_id)
            if ev and "start" in (ev.name or "").lower():
                ids.append(trig.id)
        return ids

    def _genre_blend_should_suppress(self) -> tuple[bool, str]:
        """Decide whether to suppress start triggers for the current song.

        Returns (should_suppress, reason_for_log). The reason is always
        populated so diagnostics are useful regardless of the outcome.
        """
        if not settings.genre_blending_enabled:
            return False, "disabled"
        prev = state.last_ended_track
        if prev is None:
            return False, "no prev track"
        if prev.duration_ms <= 0:
            return False, "prev duration unknown"
        remaining = prev.duration_ms - prev.last_known_progress_ms
        if remaining > 3000:
            return False, f"skip (prev ended {remaining}ms early)"
        new_genres = []
        if state.current_track and state.current_track.genres:
            new_genres = state.current_track.genres
        a = {g.strip().lower() for g in (prev.genres or []) if g}
        b = {g.strip().lower() for g in (new_genres or []) if g}
        if not a or not b:
            return False, f"genres missing (prev={sorted(a)}, new={sorted(b)})"
        overlap = a & b
        if not overlap:
            return False, f"no genre overlap (prev={sorted(a)}, new={sorted(b)})"
        return True, f"match={sorted(overlap)} (prev={sorted(a)}, new={sorted(b)})"

    def _apply_genre_blend_on_load(self) -> None:
        if state.dinner_party_mode:
            logger.debug("Genre Blending: skipped (dinner party mode — Song Start always fires)")
            return
        suppress, reason = self._genre_blend_should_suppress()
        if not suppress:
            logger.debug("Genre Blending: no-op on load (%s)", reason)
            return
        ids = self._start_trigger_ids()
        if not ids:
            logger.debug("Genre Blending: %s but no start triggers in active source", reason)
            return
        self._fired.update(ids)
        self._pre_fired.update(ids)
        logger.info("Genre Blending: suppressing start trigger(s) %s — %s", ids, reason)

    def reconsider_genre_blend(self) -> None:
        """Re-evaluate genre blending after genres arrive asynchronously.

        Used by the LedFX pipeline, which broadcasts a new track with empty
        genres and then fills them in from Last.fm. If the blend now applies
        and the start trigger hasn't fired yet, suppress it. If it already
        fired, we accept the race.
        """
        if state.dinner_party_mode:
            return
        suppress, reason = self._genre_blend_should_suppress()
        if not suppress:
            return
        ids = self._start_trigger_ids()
        newly_suppressed = [i for i in ids if i not in self._fired]
        if not newly_suppressed:
            return
        self._fired.update(newly_suppressed)
        self._pre_fired.update(newly_suppressed)
        logger.info(
            "Genre Blending (late): suppressing start trigger(s) %s — %s",
            newly_suppressed, reason,
        )

    def refresh_triggerless(self) -> None:
        """Re-evaluate triggerless state for the current song (e.g. after dinner party toggle)."""
        if not self._profile:
            return

        if state.dinner_party_mode:
            # Turning ON: regenerate synthetic triggers from the Dinner Party profile
            # (even if triggerless triggers were already active from a genre-matched
            # profile) and fire Song Start immediately.
            tp = self._resolve_triggerless_profile()
            if tp:
                self._triggerless_triggers = self._generate_triggerless_triggers(
                    tp, self._profile.duration_ms
                )
                self._fired = {tid for tid in self._fired if not tid.startswith("tl_")}
                self._pre_fired = {tid for tid in self._pre_fired if not tid.startswith("tl_")}
                logger.info("Triggerless: refreshed %d synthetic triggers from '%s'",
                            len(self._triggerless_triggers), tp.name)
                # Fire the Song Start event now. The tl_start_0 trigger is at 0ms,
                # so mid-song the stale-fire suppression would mark it fired
                # without actually running it — call the event directly instead.
                start_trig = next(
                    (t for t in self._triggerless_triggers if "start" in t.labels),
                    None,
                )
                if start_trig:
                    self._fired.add(start_trig.id)
                    self._pre_fired.add(start_trig.id)
                    if state.paused:
                        logger.info(
                            "Dinner Party on: skipping Song Start event %s — service paused",
                            start_trig.event_id,
                        )
                    else:
                        import asyncio as _asyncio
                        _asyncio.create_task(
                            self.fire_event_now(start_trig.event_id, start_trig.labels)
                        )
                        logger.info(
                            "Dinner Party on: firing Song Start event %s immediately",
                            start_trig.event_id,
                        )
            else:
                self._triggerless_triggers = None
        else:
            # Turning OFF
            enabled_triggers = sorted(
                [t for t in self._profile.triggers if t.enabled],
                key=lambda t: t.timestamp_ms,
            )
            if enabled_triggers:
                # Song has real triggers: switch to normal mode and fire Song Start immediately.
                # Pre-mark every trigger in the past + next 10 song-seconds as fired so
                # the main loop doesn't fire them all at once.
                self._triggerless_triggers = None
                song_start = enabled_triggers[0]
                now_ms = state.current_track.interpolated_progress_ms() if state.current_track else 0
                cutoff_ms = now_ms + 10_000
                skip_ids = {
                    t.id for t in self._profile.triggers
                    if t.id != song_start.id and t.timestamp_ms <= cutoff_ms
                }
                self._fired.update(skip_ids)
                self._pre_fired.update(skip_ids)
                self._fired.add(song_start.id)
                if state.paused:
                    logger.info(
                        "Dinner Party off: skipping Song Start trigger %s (suppressing %d triggers in 10s window) — service paused",
                        song_start.id, len(skip_ids),
                    )
                else:
                    logger.info(
                        "Dinner Party off: firing Song Start trigger %s; suppressing %d triggers within 10s window",
                        song_start.id, len(skip_ids),
                    )
                    import asyncio as _asyncio
                    _asyncio.create_task(self.fire_event_now(song_start.event_id, song_start.labels))
            else:
                # No real triggers: let Dinner Party synthetic triggers finish this song
                logger.info(
                    "Dinner Party off: no profile triggers — completing song with existing synthetic triggers"
                )
                # _triggerless_triggers unchanged; next song won't use Dinner Party
                # because state.dinner_party_mode is already False

    def _user_triggers(self) -> list[MusicTrigger]:
        """User-defined triggers, picking the active Set List override if any."""
        if not self._profile:
            return []
        sl_id = state.active_setlist_id
        if sl_id and self._profile.setlist_triggers.get(sl_id):
            return self._profile.setlist_triggers[sl_id]
        return self._profile.triggers

    def _get_active_triggers(self) -> list[MusicTrigger]:
        """Return the trigger list to use, in priority order."""
        # 1. Dinner party / explicit triggerless (synthetic)
        if self._triggerless_triggers is not None:
            return self._triggerless_triggers
        # 2. Debug override: analyzed triggers replace user triggers
        if state.analyzed_trigger_override and self._analyzed_triggers:
            return self._analyzed_triggers
        # 3. User-defined triggers (if any are enabled), honouring active Set List override
        user = self._user_triggers()
        if user and any(t.enabled for t in user):
            return user
        # 4. Analyzed triggerless (embedded pipeline output)
        if state.use_analyzed_triggerless and self._analyzed_triggers:
            return self._analyzed_triggers
        # 5. AI suggestion set (legacy)
        if state.use_unreviewed_ai_triggers and self._ai_triggers:
            return self._ai_triggers
        return self._user_triggers()

    # ── Analyzed trigger generation ──────────────────────────────────────────

    def _generate_analyzed_triggers(self, spotify_uri: str) -> Optional[list[MusicTrigger]]:
        """Return analyzed triggers for this URI, using the on-disk cache when
        valid and regenerating + persisting only when the training profile
        match or its content has changed. Skips entirely when analyzed mode
        is not active — no point paying the cost if nothing will consume them.
        """
        from services import analyzed_trigger_store
        from services.librosa_service import get_analysis_by_uri
        from services.audio_shape_service import _find_profile_for_genres
        from services.training_profile_manager import TrainingProfile

        if not state.use_analyzed_triggerless and not state.analyzed_trigger_override:
            return None

        # Cheap pre-checks: bail early if librosa data or profile match is missing.
        la = get_analysis_by_uri(spotify_uri)
        if not la or not la.beats:
            return None

        genres = state.current_track.genres if state.current_track else []
        if not genres and self._profile:
            genres = self._profile.artist_genre or []
        tp_data = _find_profile_for_genres(genres)
        if not tp_data:
            logger.info("Analyzed triggers: no matching training profile for genres %s", genres)
            return None
        tp = TrainingProfile(**tp_data)

        def _mk(t) -> MusicTrigger:
            # Honor a per-record intensity if the analyzed pipeline ever
            # provides one; otherwise default to the section energy level.
            iv = getattr(t, "intensity", None)
            return MusicTrigger(
                id=t.id, timestamp_ms=t.timestamp_ms,
                event_id=t.event_id, labels=list(t.labels or []),
                intensity=iv if iv is not None else self._section_intensity(t.timestamp_ms),
            )

        track_id = spotify_uri.split(":")[-1]
        cached = analyzed_trigger_store.load(track_id)
        if cached and analyzed_trigger_store.is_valid(cached, tp):
            logger.info(
                "Analyzed triggers: loaded %d cached for %s (profile: %s)",
                len(cached.triggers), spotify_uri, tp.name,
            )
            return [_mk(t) for t in cached.triggers]

        generated = analyzed_trigger_store.generate_for_uri(spotify_uri, save_cache=True)
        if not generated:
            return None
        return [_mk(t) for t in generated]

    # ── Triggerless play helpers ────────────────────────────────────────────

    def _section_intensity(self, ms: int) -> float:
        """Default intensity for machine-generated (triggerless/analyzed)
        triggers: the librosa section energy at that moment — the same lookup
        the section_energy binding signal uses. Mid (0.5) without data."""
        from services.signal_resolver import _section_energy
        if self._sections_cache is None and self._profile:
            from services.audio_analyzer import load_sections_for_uri
            self._sections_cache = load_sections_for_uri(self._profile.spotify_uri)
        v = _section_energy(self._sections_cache, ms)
        return 0.5 if v is None else v

    def _should_use_triggerless(self) -> bool:
        """Check if triggerless mode should be active for the current song."""
        if state.dinner_party_mode:
            return True
        # Profile with zero enabled triggers
        triggers = self._get_active_triggers()
        return len([t for t in triggers if t.enabled]) == 0

    def _resolve_triggerless_profile(self):
        """Find the right unified profile for triggerless/analyzed mode.
        Returns a TrainingProfile (unified model) or None."""
        from services.training_profile_manager import TrainingProfile, TRAINING_PROFILES_FILE
        import json

        raw = {}
        if TRAINING_PROFILES_FILE.exists():
            try:
                raw = json.loads(TRAINING_PROFILES_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        profiles = [TrainingProfile(**v) for v in raw.values()]

        if state.dinner_party_mode:
            for p in profiles:
                if p.name.lower().strip() == "dinner party":
                    logger.info("Triggerless: resolved Dinner Party profile '%s'", p.name)
                    return p
            logger.warning("Triggerless: Dinner Party mode ON but no profile named 'Dinner Party' found")
            return None

        genres = []
        if state.current_track:
            genres = state.current_track.genres or []
        if not genres and self._profile:
            genres = getattr(self._profile, "genres", []) or []

        # Genre matching: find profile whose genres overlap with the song's genres
        song_genres_lower = {g.lower() for g in genres}
        for p in profiles:
            profile_genres = {g.lower() for g in p.genres}
            if song_genres_lower & profile_genres:
                logger.info("Triggerless: resolved genre profile '%s' for genres %s", p.name, genres)
                return p

        # Fallback to default
        for p in profiles:
            if p.is_default:
                logger.info("Triggerless: using default profile '%s' (no genre match for %s)", p.name, genres)
                return p

        logger.info("Triggerless: no profile found for genres %s", genres)
        return None

    def _generate_triggerless_triggers(self, tp, duration_ms: int) -> list[MusicTrigger]:
        """Generate synthetic interval-based triggers from a unified TrainingProfile (Simple mode)."""
        triggers: list[MusicTrigger] = []
        end_pre = getattr(tp, "end_pre_fire_ms", 5000)
        end_eid = getattr(tp, "song_end_event_id", "") or ""
        start_eid = getattr(tp, "song_start_event_id", "") or ""
        scene_eid = getattr(tp, "scene_fill_event_id", "") or ""
        flare_eid = getattr(tp, "flare_event_id", "") or ""
        scene_interval = getattr(tp, "scene_change_interval_s", 30)
        flare_interval = getattr(tp, "flare_interval_s", 15)

        end_cutoff = duration_ms - end_pre if end_eid else duration_ms

        # 1. Start event at 0ms
        if start_eid:
            triggers.append(MusicTrigger(
                id="tl_start_0", timestamp_ms=0,
                event_id=start_eid, labels=["triggerless", "start"],
                intensity=self._section_intensity(0),
            ))

        # 2. Scene events at regular intervals
        scene_timestamps: set[int] = set()
        if scene_eid and scene_interval > 0:
            interval_ms = scene_interval * 1000
            t = interval_ms
            while t < end_cutoff:
                scene_timestamps.add(t)
                triggers.append(MusicTrigger(
                    id=f"tl_scene_{t}", timestamp_ms=t,
                    event_id=scene_eid, labels=["triggerless", "scene"],
                    intensity=self._section_intensity(t),
                ))
                t += interval_ms

        # 3. Flare events (skip timestamps that coincide with scene events)
        if flare_eid and flare_interval > 0:
            flare_interval_ms = flare_interval * 1000
            t = flare_interval_ms
            while t < end_cutoff:
                if t not in scene_timestamps:
                    triggers.append(MusicTrigger(
                        id=f"tl_flare_{t}", timestamp_ms=t,
                        event_id=flare_eid, labels=["triggerless", "flare"],
                        intensity=self._section_intensity(t),
                    ))
                t += flare_interval_ms

        # 4. End event
        if end_eid and duration_ms > end_pre:
            triggers.append(MusicTrigger(
                id=f"tl_end_{end_cutoff}", timestamp_ms=end_cutoff,
                event_id=end_eid, labels=["triggerless", "end"],
                intensity=self._section_intensity(end_cutoff),
            ))

        triggers.sort(key=lambda t: t.timestamp_ms)
        return triggers

    # ── Shape offset ─────────────────────────────────────────────────────────

    def reload_shape_offset(self, uri: str) -> None:
        """Re-derive the engine offset from disk (median + trim). Used for
        perception-trim updates and other context changes where we want to
        force a re-resolve rather than apply a single new save."""
        if self._last_uri == uri:
            meta = load_audio_shape_meta(uri)
            self._shape_offset_ms, self._shape_offset_quality, src = _resolve_shape_offset(meta)
            logger.info(
                "Shape offset reloaded: %+dms Q=%.2f source=%s for %s",
                self._shape_offset_ms, self._shape_offset_quality, src, uri,
            )

    def apply_save(self, uri: str, raw_offset_ms: int, quality: float,
                   source: str = "sweep", bypass_drift_cap: bool = False) -> bool:
        """Apply a fresh save to the live engine if its quality beats the
        best seen this play. Layers the current perception trim on top.

        The disk write is handled separately by _save_offset; this only
        updates the in-memory offset for the rest of the current play. At
        song start, _play_best_quality is reset to 0 so the first save with
        any quality wins. Subsequent saves must strictly improve to override.

        Returns True if applied. False = ignored (lower quality than current).
        """
        if uri != self._last_uri:
            return False
        if quality <= self._play_best_quality:
            logger.info(
                "Engine: skip snap — %+dms Q=%.2f source=%s ≤ play-best Q=%.2f (current=%+d)",
                raw_offset_ms, quality, source, self._play_best_quality, self._shape_offset_ms,
            )
            return False
        meta = load_audio_shape_meta(uri)
        trim = _perception_trim_for(meta)
        new_effective = int(raw_offset_ms) + int(trim)
        # In-song drift cap: once we have a loaded baseline, big mid-play
        # jumps are almost always beat-tile false matches (observed: anchor
        # locks at +5000ms then later corrects back). Reject saves that
        # diverge more than `engine_in_song_drift_cap_ms` from the offset
        # loaded at song start. The disk-write path is unaffected — large
        # corrections still accumulate in history and influence next play's
        # median.
        # Drift cap: low-confidence mid-play snaps that diverge from the loaded
        # baseline by more than `engine_in_song_drift_cap_ms` are rejected as
        # likely beat-tile false matches. The beat-twin gates upstream already
        # reject most such matches, so we let high-Q measurements bypass the cap
        # — the loaded baseline is just a previous play's median, not ground
        # truth, and a confident new measurement should be allowed to correct it.
        drift_cap = int(getattr(settings, "engine_in_song_drift_cap_ms", 2000))
        bypass_q = float(getattr(settings, "engine_drift_bypass_q", 0.70))
        # Round 8: anti-correlated baseline relaxation no longer waives the cap
        # for low-Q saves. Multiple plays showed Q=0.55-0.79 anti-corr-bypass
        # snaps overriding correct locks (Pepas +5200, Contra -2275). Now the
        # bypass requires Q ≥ engine_anti_corr_bypass_q (0.85 default) — i.e.
        # only really-confident measurements are trusted to far-jump even
        # when the loaded baseline appears anti-correlated.
        anti_corr_bypass_q = float(getattr(settings, "engine_anti_corr_bypass_q", 0.85))
        effective_bypass = bypass_drift_cap and quality >= anti_corr_bypass_q
        # Cold-start progressive exception: before anything has locked this
        # play (_play_best_quality == 0), a progressive early match is the
        # best information available — on blended cut-ins the loaded baseline
        # is exactly what's wrong, and progressive Q is structurally low
        # early (r × span/8s). Its strict gates (r/dominance/comb) carry the
        # false-match defense. Mid-play snaps keep the cap unchanged.
        if source == "progressive" and self._play_best_quality == 0.0:
            effective_bypass = True
        if drift_cap > 0 and quality < bypass_q and not effective_bypass:
            drift = abs(new_effective - self._loaded_offset_ms)
            if drift > drift_cap:
                logger.info(
                    "Engine: reject snap — %+dms is %+dms from loaded %+dms (cap=%dms, source=%s, Q=%.2f<%.2f)",
                    new_effective, new_effective - self._loaded_offset_ms,
                    self._loaded_offset_ms, drift_cap, source, quality, bypass_q,
                )
                return False
        logger.info(
            "Engine: snap %+dms → %+dms (Q %.2f → %.2f, source=%s, trim=%+d) for %s",
            self._shape_offset_ms, new_effective,
            self._play_best_quality, quality, source, trim, uri,
        )
        self._shape_offset_ms = new_effective
        self._shape_offset_quality = quality
        self._play_best_quality = quality
        return True

    def systemic_residual_for(self, uri: str, raw_offset_ms: int) -> Optional[int]:
        """Residual of a confirmed save vs the offset loaded at song start, in
        the engine's effective-offset frame (trim included on both sides, so it
        cancels). Feeds the systemic-offset learner. None when this isn't the
        current song (the loaded baseline wouldn't correspond)."""
        if uri != self._last_uri:
            return None
        meta = load_audio_shape_meta(uri)
        trim = _perception_trim_for(meta)
        return int(raw_offset_ms) + int(trim) - int(self._loaded_offset_ms)

    def demote_play_best(self, uri: str, ceiling: float,
                         reason: str = "monitor") -> None:
        """Phase 5: lower _play_best_quality to `ceiling` (never raise) so a
        fresh corrective save can win the quality-wins gate after a confirmed
        live mismatch. The offset itself is untouched — this only re-opens
        the gate; an actual better measurement must still arrive and clear
        every other gate (incl. the drift cap)."""
        if uri == self._last_uri and self._play_best_quality > ceiling:
            logger.info(
                "Engine: play-best demoted %.2f → %.2f (%s) for %s",
                self._play_best_quality, ceiling, reason, uri,
            )
            self._play_best_quality = float(ceiling)

    def _effective_offset_ms(self) -> int:
        """
        Total ms to subtract from the song timestamp when deciding to fire.
        Positive result means we fire triggers earlier.
        """
        return (
            settings.ledfx_trigger_buffer_ms
            + int(state.ledfx_rtt_ms)
            + self._shape_offset_ms
        )

    # ── Plan-timeline builder ──────────────────────────────────────────────

    def _local_beat_interval_ms(self, at_ms: int) -> int:
        """
        Beat-to-beat interval at the given song position. Used to convert
        `delay_beats` into ms without snapping steps to the grid.

        Picks the two beats bracketing at_ms. Falls back to 60000/tempo_bpm
        when we don't have librosa data yet, then to 500 (120 BPM).
        """
        beats = self._beats_cache
        tempo = self._tempo_cache
        fallback = int(round(60000 / tempo)) if tempo else 500
        if not beats or len(beats) < 2:
            return fallback
        # Nearest beat index to at_ms
        nearest = min(range(len(beats)), key=lambda i: abs(beats[i]["ms"] - at_ms))
        if nearest + 1 < len(beats):
            return max(1, int(beats[nearest + 1]["ms"] - beats[nearest]["ms"]))
        return max(1, int(beats[nearest]["ms"] - beats[nearest - 1]["ms"]))

    def _plan_timeline(
        self,
        root_event: MusicEvent,
        trigger: MusicTrigger,
        labels: list[str],
        time_scale: float = 1.0,
    ) -> tuple[list[_PlanEntry], str]:
        """
        Walk the resolved event tree and produce a flat list of _PlanEntry
        with absolute song-ms fire times. Offsets (event_offset_ms,
        sequence step.delay_ms, and beat-sequence step spacing) compound
        through the walk. Also returns a drill-down preview string.

        `time_scale` (Override Blend) stretches the plan's ms spacing —
        sequence step delays and parallel/morph lane offsets — by that
        factor. event_offset_ms (a latency trim, not ramping) and
        beat-anchored spacing stay unscaled; the fire-time counterpart
        (event-body sleeps + ramps) is scaled by _blend_scale_plan.

        Offset semantics:
          - Every event has `event_offset_ms`: shifts this event's own start
            relative to the time its parent would invoke it. Negative = earlier.
          - `sequence_steps[i].delay_ms`: start this step this many ms after
            the previous step's nominal start.
          - `beat_sequence_steps[i].delay_beats`: start this step this many
            +1 beat-intervals after the previous step's nominal start.
          - `beat_sequence_start_offset_beats`: shift whole beat sequence.
          - Singles with an event_ref action are transparent: the child takes
            their place in the plan; no entry is emitted for the single itself.
        """
        entries: list[_PlanEntry] = []

        def _walk_step_body(
            step, step_time: int, merged: list[str], depth: int, visited_next: frozenset,
        ) -> tuple[str, set[str]]:
            """
            Expand one sequence/beat_sequence step into plan entries for any
            event_ref sub-events it contains and return a description + the set
            of sub-event ids the plan covers (so the parent can skip them).

            An action-type step may contain event_ref actions (that's how
            "Flare - EDM" points at "Flare - EDM - Flash"). Those must be
            planned with offset compounding too, not just event-type steps.
            """
            sub_ids: set[str] = set()
            labels_here: list[str] = []
            if step.step_type == "event" and step.event_id:
                child = get_event(step.event_id)
                if child and child.id not in visited_next:
                    label = walk(child, step_time, merged, depth + 1, visited_next)
                    sub_ids.add(child.id)
                    return label, sub_ids
                if child:
                    return child.name, sub_ids
                return "", sub_ids
            if step.step_type == "action":
                resolved = self._resolve_step_actions(step)
                ref_labels: list[str] = []
                raw_labels: list[str] = []
                for a in resolved:
                    if a.type == "event_ref" and a.event_id:
                        child = get_event(a.event_id)
                        if child and child.id not in visited_next:
                            a_merged = merged + list(a.labels or [])
                            lbl = walk(child, step_time, a_merged, depth + 1, visited_next)
                            ref_labels.append(lbl)
                            sub_ids.add(child.id)
                        elif child:
                            ref_labels.append(child.name)
                    else:
                        raw_labels.append(self._describe_action(a))
                parts = ref_labels + raw_labels
                return (", ".join(parts) if parts else ""), sub_ids
            return "", sub_ids

        def walk(
            event: MusicEvent,
            invoke_at_ms: int,
            lbls: list[str],
            depth: int = 0,
            visited: frozenset = frozenset(),
        ) -> str:
            """Recurse; return a drill-down description string for this node."""
            if depth > 5:
                return "…"
            if event.id in visited:
                return event.name  # cycle guard
            visited_next = visited | {event.id}

            start_at = invoke_at_ms + event.event_offset_ms

            if event.event_type == "single":
                action = self._select_action(event, lbls)
                if action and action.type == "event_ref" and action.event_id:
                    child = get_event(action.event_id)
                    if child and child.id not in visited_next:
                        merged = lbls + list(action.labels or [])
                        return walk(child, start_at, merged, depth + 1, visited_next)
                    # cycle / missing → fall through to emit entry
                # Leaf single: emit entry with the pre-selected action
                entries.append(_PlanEntry(
                    fire_at_ms=start_at, event=event, labels=list(lbls),
                    trigger_ms=trigger.timestamp_ms,
                    trigger_id=trigger.id,
                    trigger_intensity=self._scaled_intensity(getattr(trigger, "intensity", 0.5)),
                    trigger_color_group=getattr(trigger, "color_group_override", None),
                    is_root=(event.id == root_event.id),
                    preselected_action=action,
                ))
                return self._describe_action(action) if action else event.name

            if event.event_type == "sequence":
                step_time = start_at
                child_ids: set[str] = set()
                preselected_steps: list = []
                parts: list[str] = []
                for step in event.sequence_steps:
                    step_time += round(step.delay_ms * time_scale)
                    merged = lbls + list(step.labels or [])
                    label, step_child_ids = _walk_step_body(
                        step, step_time, merged, depth, visited_next,
                    )
                    if label:
                        parts.append(label)
                    child_ids |= step_child_ids
                    preselected_steps.append(None)
                entries.append(_PlanEntry(
                    fire_at_ms=start_at, event=event, labels=list(lbls),
                    trigger_ms=trigger.timestamp_ms,
                    trigger_id=trigger.id,
                    trigger_intensity=self._scaled_intensity(getattr(trigger, "intensity", 0.5)),
                    trigger_color_group=getattr(trigger, "color_group_override", None),
                    is_root=(event.id == root_event.id),
                    planned_descendant_ids=child_ids,
                    preselected_steps=preselected_steps,
                ))
                return ", ".join(parts) if parts else event.name

            if event.event_type == "beat_sequence":
                # Use the local beat interval at the sequence's actual start time,
                # so tempo changes within a song scale the spacing appropriately.
                interval = self._local_beat_interval_ms(start_at)
                anchor = start_at + event.beat_sequence_start_offset_beats * interval
                step_time = anchor
                child_ids = set()
                parts = []
                for i, step in enumerate(event.beat_sequence_steps):
                    if i > 0:
                        step_time += (1 + step.delay_beats) * interval
                    merged = lbls + list(step.labels or [])
                    label, step_child_ids = _walk_step_body(
                        step, step_time, merged, depth, visited_next,
                    )
                    if label:
                        parts.append(label)
                    child_ids |= step_child_ids
                entries.append(_PlanEntry(
                    fire_at_ms=anchor, event=event, labels=list(lbls),
                    trigger_ms=trigger.timestamp_ms,
                    trigger_id=trigger.id,
                    trigger_intensity=self._scaled_intensity(getattr(trigger, "intensity", 0.5)),
                    trigger_color_group=getattr(trigger, "color_group_override", None),
                    is_root=(event.id == root_event.id),
                    planned_descendant_ids=child_ids,
                ))
                return " > ".join(parts) if parts else event.name

            if event.event_type == "morph_set":
                # Pre-pick one alternative per lane so the plan has a Now Playing
                # summary; the color-group cycle cursor still advances at fire
                # time (inside _execute_set_color), not here.
                picks = self._pick_morph_lanes(event, lbls)
                # Anchor the entry at the EARLIEST lane: fire_at = start_at +
                # min(offset). Each lane then sleeps (offset - anchor) >= 0 at
                # dispatch. All-equal offsets (incl. all-zero) → anchor == that
                # value, no relative sleeps. Offsets live on the lane, so the
                # anchor is stable across the fire-time re-roll of alternatives.
                morph_anchor = round(min((p.offset_ms for p in picks), default=0) * time_scale)
                entries.append(_PlanEntry(
                    fire_at_ms=start_at + morph_anchor, event=event, labels=list(lbls),
                    trigger_ms=trigger.timestamp_ms,
                    trigger_id=trigger.id,
                    trigger_intensity=self._scaled_intensity(getattr(trigger, "intensity", 0.5)),
                    trigger_color_group=getattr(trigger, "color_group_override", None),
                    is_root=(event.id == root_event.id),
                    preselected_morph_picks=picks,
                    morph_anchor_offset_ms=morph_anchor,
                ))
                return self._morph_picks_summary(picks) if picks else event.name

            if event.event_type == "composite":
                root = event.root
                resolved = (
                    self._resolve_random_picks(
                        root, list(lbls), energy=self._scaled_intensity(getattr(trigger, "intensity", None)))
                    if root is not None else {}
                )
                # Anchor mirrors legacy: beats root shifts by start_offset_beats;
                # parallel root shifts by min(child offset) (children then sleep
                # offset - anchor at fire time).
                fire_at = start_at
                anchor_off = 0
                if root is not None and root.type == "sequence_group" and root.timing == "beats":
                    interval = self._local_beat_interval_ms(start_at)
                    fire_at = start_at + root.start_offset_beats * interval
                elif root is not None and root.type == "parallel_group" and root.children:
                    anchor_off = round(min(int(c.offset_ms or 0) for c in root.children) * time_scale)
                    fire_at = start_at + anchor_off

                # Plan event_ref children on RESOLVED branches with compounded
                # timing, so their event_offset_ms lands correctly (the inline
                # fallback in _execute_action stays for unresolved branches).
                child_ids: set[str] = set()

                def _plan_refs(action, base_ms: float, merged: list[str], d: int) -> None:
                    if action is None or d > 5:
                        return
                    t = getattr(action, "type", "")
                    if t == "event_ref" and action.event_id:
                        child = get_event(action.event_id)
                        if child and child.id not in visited_next:
                            walk(child, int(base_ms), merged + list(action.labels or []),
                                 depth + 1, visited_next)
                            child_ids.add(child.id)
                        return
                    if t == "random_group":
                        opt_id = resolved.get(action.id)
                        opt = next((o for o in action.options if o.id == opt_id), None)
                        if opt is not None:
                            for a in opt.actions:
                                _plan_refs(a, base_ms, merged + list(opt.labels or []), d + 1)
                        return
                    if t == "intensity_chooser":
                        lane_id = resolved.get(action.id)
                        lane = next((l for l in action.lanes if l.id == lane_id), None)
                        if lane is not None:
                            for a in lane.actions:
                                _plan_refs(a, base_ms, merged + list(lane.labels or []), d + 1)
                        return
                    if t == "sequence_group":
                        tmg = action.timing
                        interval = self._local_beat_interval_ms(int(base_ms)) if tmg == "beats" else 0
                        tcur = base_ms + (action.start_offset_beats * interval if tmg == "beats" else 0)
                        for i, c in enumerate(action.children):
                            if tmg == "beats":
                                if i > 0:
                                    tcur += (1 + c.delay_beats) * interval
                            else:
                                tcur += c.delay_ms * time_scale
                            for a in c.actions:
                                _plan_refs(a, tcur, merged + list(c.labels or []), d + 1)
                        return
                    if t == "parallel_group":
                        for c in action.children:
                            for a in c.actions:
                                _plan_refs(a, base_ms + int(c.offset_ms or 0) * time_scale,
                                           merged + list(c.labels or []), d + 1)
                        return

                if root is not None:
                    _plan_refs(root, float(start_at), list(lbls), 0)

                entries.append(_PlanEntry(
                    fire_at_ms=int(fire_at), event=event, labels=list(lbls),
                    trigger_ms=trigger.timestamp_ms,
                    trigger_id=trigger.id,
                    trigger_intensity=self._scaled_intensity(getattr(trigger, "intensity", 0.5)),
                    trigger_color_group=getattr(trigger, "color_group_override", None),
                    is_root=(event.id == root_event.id),
                    planned_descendant_ids=child_ids,
                    resolved_picks=resolved,
                    morph_anchor_offset_ms=anchor_off,
                ))
                return (self._describe_action(root, resolved=resolved)
                        if root is not None else event.name)

            if event.event_type in SCENE_EVENT_TYPES:
                # Lock the lane picks in NOW so the preview can say exactly
                # what will change — including every random branch inside
                # referenced composites (deep resolution). _execute_plan_entry
                # re-rolls only if the active Scene Update changes between
                # plan and fire (the scene_picks_sid guard).
                scene_sid = self._last_scene_update_id
                if event.event_type in ("scene_update", "scene_group"):
                    # Scene Groups get no plan-time picks (member resolves at
                    # fire time), but picks_src still records the redirect
                    # target so the staleness guard compares like-for-like.
                    picks_src = (self._forced_scene_event() or event).id
                else:
                    picks_src = scene_sid  # flares roll against the last scene
                scene_picks = self._pick_scene_lanes(event, lbls)
                scene_resolved: dict = {}
                for _i, _a in scene_picks:
                    self._resolve_random_picks_deep(
                        _a, list(lbls), scene_resolved,
                        energy=self._scaled_intensity(getattr(trigger, "intensity", None)))
                parts = []
                for i, a in scene_picks:
                    nm = SCENE_LANE_NAMES[i] if 0 <= i < len(SCENE_LANE_NAMES) else str(i)
                    leaves = self._collect_leaves(a, scene_resolved, tag=nm)
                    if leaves:
                        t0 = self._describe_action_detail(leaves[0][2], inherited_scope=leaves[0][1])[0]
                        more = f" +{len(leaves) - 1}" if len(leaves) > 1 else ""
                        parts.append(f"{nm}: {t0}{more}")
                entries.append(_PlanEntry(
                    fire_at_ms=start_at, event=event, labels=list(lbls),
                    trigger_ms=trigger.timestamp_ms,
                    trigger_id=trigger.id,
                    trigger_intensity=self._scaled_intensity(getattr(trigger, "intensity", 0.5)),
                    trigger_color_group=getattr(trigger, "color_group_override", None),
                    is_root=(event.id == root_event.id),
                    preselected_scene_picks=scene_picks or None,
                    scene_picks_sid=scene_sid,
                    scene_picks_event_id=picks_src,
                    resolved_picks=scene_resolved or None,
                ))
                return f"{event.name}: {' · '.join(parts)}" if parts else event.name

            if event.event_type == "device_settings":
                entries.append(_PlanEntry(
                    fire_at_ms=start_at, event=event, labels=list(lbls),
                    trigger_ms=trigger.timestamp_ms,
                    trigger_id=trigger.id,
                    trigger_intensity=self._scaled_intensity(getattr(trigger, "intensity", 0.5)),
                    trigger_color_group=getattr(trigger, "color_group_override", None),
                    is_root=(event.id == root_event.id),
                ))
                return f"Device settings ({len(event.device_targets)}×)"

            return event.name

        description = walk(root_event, trigger.timestamp_ms, list(labels))
        entries.sort(key=lambda e: e.fire_at_ms)
        return entries, description

    # ── Override Blend ───────────────────────────────────────────────────────
    # A trigger with override_blend=True stretches (or compresses) its event's
    # ms timing so the last ramp completes exactly at the NEXT enabled trigger
    # (or song end). Ramps and ms delays/offsets scale proportionally;
    # event_offset_ms (latency trim) and beat-anchored spacing stay unscaled —
    # for beat-timed bodies only the ramps scale, so completion is exact only
    # for ms-timed trees. Scene-family fires scale via their plan-time lane
    # picks; a stale-scene re-roll at fire time falls back to natural speed.

    def _blend_ramp_of(self, action) -> int:
        """Effective ramp of one leaf action (None / unresolvable binding →
        the settings.smooth_ramp_ms default the executors would use)."""
        r = static_ramp_ms(getattr(action, "ramp_ms", None), self._signal_now)
        return r if r is not None else settings.smooth_ramp_ms

    def _blend_action_tail_ms(
        self, action, at_ms: int, depth: int = 0, visited: frozenset = frozenset(),
    ) -> float:
        """Ms from an action's invoke moment until its last ramp completes.
        Pick-independent: random groups use the slowest option (upper bound —
        a shorter pick just finishes early). `at_ms` anchors beat intervals."""
        if action is None or depth > 6:
            return 0.0
        t = getattr(action, "type", "")
        if t == "morph_step":
            base = self._blend_ramp_of(action)
            per: list[float] = []
            for tg in action.targets:
                if tg.ramp_ms is not None:
                    r = static_ramp_ms(tg.ramp_ms, self._signal_now)
                    per.append(float(r if r is not None else base))
                else:
                    per.append(float(base))
            return max(per) if per else float(base)
        if t in ("set_color", "morph_color", "ledfx_effect_param"):
            return float(self._blend_ramp_of(action))
        if t == "event_ref" and action.event_id:
            child = get_event(action.event_id)
            if child and child.id not in visited:
                return child.event_offset_ms + self._blend_event_tail_ms(
                    child, at_ms, depth + 1, visited | {child.id})
            return 0.0
        if t == "random_group":
            return max(
                (max((self._blend_action_tail_ms(a, at_ms, depth + 1, visited)
                      for a in opt.actions), default=0.0)
                 for opt in action.options),
                default=0.0,
            )
        if t == "intensity_chooser":
            return max(
                (max((self._blend_action_tail_ms(a, at_ms, depth + 1, visited)
                      for a in lane.actions), default=0.0)
                 for lane in action.lanes),
                default=0.0,
            )
        if t == "sequence_group":
            if action.timing == "beats":
                interval = self._local_beat_interval_ms(at_ms)
                tcur = float(action.start_offset_beats * interval)
                end = 0.0
                for i, c in enumerate(action.children):
                    if i > 0:
                        tcur += (1 + c.delay_beats) * interval
                    tail = max((self._blend_action_tail_ms(a, at_ms, depth + 1, visited)
                                for a in c.actions), default=0.0)
                    # pre_ramp completes ON the beat; otherwise the ramp runs past it
                    end = max(end, tcur + (0.0 if c.pre_ramp else tail))
                if action.revert and action.revert.enabled:
                    end += action.revert.delay_beats * interval
                    if not action.revert.pre_ramp:
                        end += action.revert.transition_ms
                return end
            # ms mode is sequential INCLUDING ramps (children await ramps).
            # delay_ms stays the upper bound when delay_updates is set — an
            # updates wait can only fire the child EARLIER than its delay.
            tcur = 0.0
            for c in action.children:
                tcur += c.delay_ms
                tcur += max((self._blend_action_tail_ms(a, at_ms, depth + 1, visited)
                             for a in c.actions), default=0.0)
            if action.revert and action.revert.enabled:
                tcur += action.revert.delay_ms + action.revert.transition_ms
            return tcur
        if t == "parallel_group":
            offs = [int(c.offset_ms or 0) for c in action.children if c.actions]
            anchor = min(offs, default=0)
            end = 0.0
            for c in action.children:
                if not c.actions:
                    continue
                rel = int(c.offset_ms or 0) - anchor
                end = max(end, rel + max((self._blend_action_tail_ms(a, at_ms, depth + 1, visited)
                                          for a in c.actions), default=0.0))
            return end
        return 0.0  # scene/ambient/global-transition/device leaves are instant

    def _blend_event_tail_ms(
        self, event: MusicEvent, at_ms: int, depth: int = 0, visited: frozenset = frozenset(),
    ) -> float:
        """Ms from an event's invoke moment until its last ramp completes."""
        if event is None or depth > 5 or event.id in visited:
            return 0.0
        visited = visited | {event.id}
        et = event.event_type
        if et == "single":
            return max((self._blend_action_tail_ms(a, at_ms, depth, visited)
                        for a in event.actions), default=0.0)
        if et == "sequence":
            tcur = 0.0
            for step in event.sequence_steps:
                tcur += step.delay_ms
                if step.step_type == "event" and step.event_id:
                    child = get_event(step.event_id)
                    if child:
                        tcur += self._blend_event_tail_ms(child, at_ms, depth + 1, visited)
                else:
                    tcur += max((self._blend_action_tail_ms(a, at_ms, depth, visited)
                                 for a in self._resolve_step_actions(step)), default=0.0)
            if event.revert and event.revert.enabled:
                tcur += event.revert.delay_ms + event.revert.transition_ms
            return tcur
        if et == "beat_sequence":
            interval = self._local_beat_interval_ms(at_ms)
            tcur = float(event.beat_sequence_start_offset_beats * interval)
            end = 0.0
            for i, step in enumerate(event.beat_sequence_steps):
                if i > 0:
                    tcur += (1 + step.delay_beats) * interval
                tail = max((self._blend_action_tail_ms(a, at_ms, depth, visited)
                            for a in self._resolve_step_actions(step)), default=0.0)
                end = max(end, tcur + (0.0 if step.pre_ramp else tail))
            if event.beat_revert and event.beat_revert.enabled:
                end += event.beat_revert.delay_beats * interval
                if not event.beat_revert.pre_ramp:
                    end += event.beat_revert.transition_ms
            return end
        if et == "morph_set":
            offs = [int(l.offset_ms or 0) for l in event.morph_lanes if l.alternatives]
            anchor = min(offs, default=0)
            end = 0.0
            for lane in event.morph_lanes:
                if not lane.alternatives:
                    continue
                tail = max((self._blend_action_tail_ms(a, at_ms, depth, visited)
                            for a in lane.alternatives), default=0.0)
                end = max(end, int(lane.offset_ms or 0) - anchor + tail)
            return end
        if et == "composite":
            return self._blend_action_tail_ms(event.root, at_ms, depth, visited)
        if et in SCENE_EVENT_TYPES:
            if et == "scene_update":
                forced = self._forced_scene_event()
                if forced is not None:
                    event = forced  # Force Scene: reassert with normal First/Rest
                lane_index = 1 if self._last_scene_update_id == event.id else 0
                lanes = event.morph_lanes or []
                if 0 <= lane_index < len(lanes):
                    return max((self._blend_action_tail_ms(a, at_ms, depth, visited)
                                for a in lanes[lane_index].alternatives), default=0.0)
                return 0.0
            last = get_event(self._last_scene_update_id) if self._last_scene_update_id else None
            if last is None or last.event_type != "scene_update":
                return 0.0
            lanes = last.morph_lanes or []
            end = 0.0
            for i in self._scene_lane_indices(event):
                if 0 <= i < len(lanes):
                    end = max(end, max((self._blend_action_tail_ms(a, at_ms, depth, visited)
                                        for a in lanes[i].alternatives), default=0.0))
            return end
        return 0.0  # device_settings and friends are instant

    def _blend_factor_for(self, trigger: MusicTrigger, event: MusicEvent) -> Optional[float]:
        """Override Blend scale factor for this trigger: gap to the next
        enabled trigger (or song end) ÷ the event's natural tail.
        None = leave the plan at natural speed."""
        if self._profile is None:
            return None
        nxt = min(
            (t.timestamp_ms for t in self._get_active_triggers()
             if t.enabled and t.id != trigger.id and t.timestamp_ms > trigger.timestamp_ms),
            default=None,
        )
        end_ms = nxt if nxt is not None else int(self._profile.duration_ms or 0)
        gap = end_ms - trigger.timestamp_ms
        if gap <= 0:
            return None
        tail = self._blend_event_tail_ms(event, trigger.timestamp_ms)
        if tail <= 0:
            return None
        factor = gap / tail
        if abs(factor - 1.0) < 0.01:
            return None
        return factor

    def _blend_scale_ramp(self, value, factor: float, default_ms: Optional[int] = None):
        """Scale one ramp_ms field. None → materialize the default it would
        have used (when given); ValueBindings resolve to a static int first
        so the scaled plan is deterministic."""
        if value is None:
            return None if default_ms is None else max(0, round(default_ms * factor))
        r = static_ramp_ms(value, self._signal_now)
        if r is None:
            r = settings.smooth_ramp_ms
        return max(0, round(r * factor))

    def _blend_scale_action(self, action, factor: float) -> None:
        """Scale ms timing in place on a deep-COPIED Action tree: ramps
        (explicit or defaulted), ms delays/offsets, reverts. Beat-anchored
        spacing (delay_beats) stays musical."""
        if action is None:
            return
        t = getattr(action, "type", "")
        if t == "morph_step":
            for tg in action.targets:
                if tg.ramp_ms is not None:
                    tg.ramp_ms = self._blend_scale_ramp(tg.ramp_ms, factor)
            action.ramp_ms = self._blend_scale_ramp(action.ramp_ms, factor, settings.smooth_ramp_ms)
            return
        if t in ("set_color", "morph_color", "ledfx_effect_param"):
            action.ramp_ms = self._blend_scale_ramp(action.ramp_ms, factor, settings.smooth_ramp_ms)
            if t == "set_color":
                # Color Set entries may override ramp_ms per entry (card data,
                # not on the action) — the executor multiplies those by this.
                action.ramp_scale = factor
            return
        if t == "random_group":
            for opt in action.options:
                for a in opt.actions:
                    self._blend_scale_action(a, factor)
            return
        if t == "intensity_chooser":
            for lane in action.lanes:
                for a in lane.actions:
                    self._blend_scale_action(a, factor)
            return
        if t == "sequence_group":
            for c in action.children:
                if action.timing == "ms":
                    c.delay_ms = round(c.delay_ms * factor)
                for a in c.actions:
                    self._blend_scale_action(a, factor)
            if action.revert:
                action.revert.delay_ms = round(action.revert.delay_ms * factor)
                action.revert.transition_ms = round(action.revert.transition_ms * factor)
            return
        if t == "parallel_group":
            for c in action.children:
                c.offset_ms = round(int(c.offset_ms or 0) * factor)
                for a in c.actions:
                    self._blend_scale_action(a, factor)
            return
        # event_ref children get their own (scaled) plan entries; ramp-less
        # leaves (scene/ambient/device) have nothing to scale.

    def _blend_scale_event(self, event: MusicEvent, factor: float) -> MusicEvent:
        """Deep-copied event with all ms timing scaled. event_offset_ms is a
        latency trim, not ramping — intentionally left alone."""
        ev = event.model_copy(deep=True)
        for step in ev.sequence_steps:
            step.delay_ms = round(step.delay_ms * factor)
            for a in self._resolve_step_actions(step):
                self._blend_scale_action(a, factor)
        if ev.revert:
            ev.revert.delay_ms = round(ev.revert.delay_ms * factor)
            ev.revert.transition_ms = round(ev.revert.transition_ms * factor)
        for step in ev.beat_sequence_steps:
            for a in self._resolve_step_actions(step):
                self._blend_scale_action(a, factor)
        if ev.beat_revert:
            ev.beat_revert.transition_ms = round(ev.beat_revert.transition_ms * factor)
        for lane in ev.morph_lanes:
            lane.offset_ms = round(int(lane.offset_ms or 0) * factor)
            for a in lane.alternatives:
                self._blend_scale_action(a, factor)
        for a in ev.actions:
            self._blend_scale_action(a, factor)
        if ev.root is not None:
            self._blend_scale_action(ev.root, factor)
        return ev

    def _blend_scale_plan(self, plan: list[_PlanEntry], factor: float) -> None:
        """Apply Override Blend to a built plan: swap each entry's event and
        its plan-time picks for time-scaled copies. The plan's fire_at_ms
        spacing was already scaled by _plan_timeline(time_scale=...)."""
        for entry in plan:
            entry.event = self._blend_scale_event(entry.event, factor)
            if entry.preselected_action is not None:
                a = entry.preselected_action.model_copy(deep=True)
                self._blend_scale_action(a, factor)
                entry.preselected_action = a
            if entry.preselected_morph_picks:
                entry.preselected_morph_picks = [
                    MorphPick(p.lane_name,
                              self._blend_scaled_copy(p.action, factor),
                              round(p.offset_ms * factor))
                    for p in entry.preselected_morph_picks
                ]
            if entry.preselected_scene_picks:
                entry.preselected_scene_picks = [
                    (i, self._blend_scaled_copy(a, factor))
                    for i, a in entry.preselected_scene_picks
                ]

    def _blend_scaled_copy(self, action, factor: float):
        c = action.model_copy(deep=True)
        self._blend_scale_action(c, factor)
        return c

    @staticmethod
    def _resolve_step_actions(step) -> list:
        """Return the effective action list for a step (multi-action or single)."""
        if step.actions:
            return list(step.actions)
        if step.action is not None:
            return [step.action]
        return []

    CONTAINER_ACTION_TYPES = ("random_group", "sequence_group", "parallel_group",
                              "intensity_chooser")

    @staticmethod
    def _scope_is_empty(scope) -> bool:
        return scope is None or (
            not scope.virtual_ids and not scope.categories and not scope.roles
        )

    def _effective_scope(self, own, inherited):
        """Child override wins; else inherit. None = nothing set anywhere."""
        return own if not self._scope_is_empty(own) else inherited

    def _apply_inherited_scope(self, action, scope):
        """Return `action` with EMPTY leaf scopes replaced by the inherited
        group/lane scope (set in the editor's Target field). Same object when
        nothing applies. Leaves with their own scope always win. Does not
        cross event_ref boundaries — referenced events keep their own scoping."""
        if self._scope_is_empty(scope):
            return action
        if action.type == "morph_step":
            if not any(self._scope_is_empty(t.scope) for t in action.targets):
                return action
            new = action.model_copy(deep=True)
            for t in new.targets:
                if self._scope_is_empty(t.scope):
                    t.scope = scope.model_copy(deep=True)
            return new
        if action.type == "ledfx_effect_param":
            if action.virtual_id or action.category:
                return action
            if scope.virtual_ids:
                return action.model_copy(update={"virtual_id": scope.virtual_ids[0]})
            if scope.categories:
                return action.model_copy(update={"category": scope.categories[0]})
            return action  # roles-only scope has no effect_param mapping
        if action.type == "device_settings":
            if not any(self._scope_is_empty(t.scope) for t in action.targets):
                return action
            new = action.model_copy(deep=True)
            for t in new.targets:
                if self._scope_is_empty(t.scope):
                    t.scope = scope.model_copy(deep=True)
            return new
        if action.type == "morph_color":
            if not self._scope_is_empty(action.scope):
                return action
            return action.model_copy(update={"scope": scope.model_copy(deep=True)})
        return action

    def _iter_leaf_actions(self, actions, resolved_picks: dict | None = None,
                           _depth: int = 0, inherited_scope=None):
        """Yield leaf (non-container) actions from a list, descending containers.
        For random_group: descend only the resolved option when the pick is
        known, else ALL options — a conservative superset, which is correct for
        snapshot/ambient collection (over-capturing is safe). Group/lane Target
        scopes are applied so snapshots stay as narrow as the actual writes."""
        if _depth > 6 or not actions:
            return
        for a in actions:
            t = getattr(a, "type", "")
            if t == "random_group":
                eff = self._effective_scope(a.scope, inherited_scope)
                opts = a.options
                if resolved_picks and a.id in resolved_picks:
                    opts = [o for o in a.options if o.id == resolved_picks[a.id]]
                for o in opts:
                    o_eff = self._effective_scope(o.scope, eff)
                    yield from self._iter_leaf_actions(o.actions, resolved_picks, _depth + 1, o_eff)
            elif t == "intensity_chooser":
                eff = self._effective_scope(a.scope, inherited_scope)
                lanes = a.lanes
                if resolved_picks and a.id in resolved_picks:
                    lanes = [l for l in a.lanes if l.id == resolved_picks[a.id]]
                for l in lanes:
                    l_eff = self._effective_scope(l.scope, eff)
                    yield from self._iter_leaf_actions(l.actions, resolved_picks, _depth + 1, l_eff)
            elif t in ("sequence_group", "parallel_group"):
                g_eff = self._effective_scope(getattr(a, "scope", None), inherited_scope)
                for c in a.children:
                    c_eff = self._effective_scope(c.scope, g_eff)
                    yield from self._iter_leaf_actions(c.actions, resolved_picks, _depth + 1, c_eff)
            else:
                yield self._apply_inherited_scope(a, inherited_scope) if inherited_scope is not None else a

    def _event_leaf_actions(self, event: MusicEvent, resolved_picks: dict | None = None) -> list:
        """Flat leaf-action list for any event shape (legacy steps or composite root)."""
        if event.event_type == "composite":
            return list(self._iter_leaf_actions([event.root] if event.root else [], resolved_picks))
        if event.event_type in ("sequence", "beat_sequence"):
            steps = event.beat_sequence_steps if event.event_type == "beat_sequence" else event.sequence_steps
            flat: list = []
            for step in steps:
                if step.step_type == "action":
                    flat.extend(self._resolve_step_actions(step))
            return list(self._iter_leaf_actions(flat, resolved_picks))
        return list(self._iter_leaf_actions(list(event.actions or []), resolved_picks))

    def _resolve_random_picks(
        self, action, labels: list[str], out: dict | None = None, _depth: int = 0,
        energy: float | None = None,
    ) -> dict:
        """Plan-time resolution of every random_group in an action tree:
        {group.id: RandomOption.id}. Picking here advances the _last_action
        dedupe memory — same precedent as plan-time _select_action for singles.
        Recurses only into the PICKED option of each group; sequence/parallel
        children are all walked (merging child labels like lane picks do).
        `energy` = the firing trigger's intensity, for option energy gates."""
        if out is None:
            out = {}
        if action is None or _depth > 6:
            return out
        t = getattr(action, "type", "")
        if t == "random_group":
            if not action.dedupe:
                self._last_action.pop(action.id, None)
            opt = self._pick_from_actions(action.options, labels, dedupe_key=action.id,
                                          desc="random group (plan)", energy=energy)
            if opt is not None:
                out[action.id] = opt.id
                for a in opt.actions:
                    self._resolve_random_picks(a, labels + list(opt.labels or []), out, _depth + 1, energy)
        elif t == "intensity_chooser":
            lane = self._pick_intensity_lane(action, energy)
            if lane is not None:
                out[action.id] = lane.id
                for a in lane.actions:
                    self._resolve_random_picks(a, labels + list(lane.labels or []), out, _depth + 1, energy)
        elif t in ("sequence_group", "parallel_group"):
            for c in action.children:
                merged = labels + list(c.labels or [])
                for a in c.actions:
                    self._resolve_random_picks(a, merged, out, _depth + 1, energy)
        return out

    def _resolve_random_picks_deep(
        self, action, labels: list[str], out: dict | None = None, _depth: int = 0,
        energy: float | None = None,
    ) -> dict:
        """_resolve_random_picks plus event_ref drilling: referenced composite
        events get their random_groups resolved into the same map, so a locked
        scene-lane pick pins the ENTIRE subtree it will fire (group ids are
        uuids, so maps can't collide across events). Used for scene-family
        plan entries, whose picks execute inline via _execute_action instead
        of being planned as child entries."""
        if out is None:
            out = {}
        if action is None or _depth > 6:
            return out
        t = getattr(action, "type", "")
        if t == "event_ref" and action.event_id:
            sub = get_event(action.event_id)
            if sub is not None and sub.event_type == "composite" and sub.root is not None:
                self._resolve_random_picks_deep(
                    sub.root, labels + list(action.labels or []), out, _depth + 1, energy)
            return out
        if t == "random_group":
            if not action.dedupe:
                self._last_action.pop(action.id, None)
            opt = self._pick_from_actions(action.options, labels, dedupe_key=action.id,
                                          desc="random group (plan)", energy=energy)
            if opt is not None:
                out[action.id] = opt.id
                for a in opt.actions:
                    self._resolve_random_picks_deep(a, labels + list(opt.labels or []), out, _depth + 1, energy)
        elif t == "intensity_chooser":
            lane = self._pick_intensity_lane(action, energy)
            if lane is not None:
                out[action.id] = lane.id
                for a in lane.actions:
                    self._resolve_random_picks_deep(a, labels + list(lane.labels or []), out, _depth + 1, energy)
        elif t in ("sequence_group", "parallel_group"):
            for c in action.children:
                merged = labels + list(c.labels or [])
                for a in c.actions:
                    self._resolve_random_picks_deep(a, merged, out, _depth + 1, energy)
        return out

    def _composite_scene_picks(self, event, resolved_picks: dict | None):
        """Flatten a RESOLVED composite tree into MorphPick-shaped lanes for the
        scene-override machinery. Returns None when the tree can't be expressed
        as one atomic activate: root missing, an unresolved random_group, or any
        sequence_group (an atomic activate can't stagger steps in time)."""
        root = event.root if event.event_type == "composite" else None
        if root is None:
            return None

        def flatten(action, offset: int, name: str, depth: int = 0, scope=None):
            if depth > 6:
                return None
            t = getattr(action, "type", "")
            if t == "sequence_group":
                return None
            if t == "random_group":
                eff = self._effective_scope(action.scope, scope)
                opt = None
                if resolved_picks and action.id in resolved_picks:
                    opt = next((o for o in action.options if o.id == resolved_picks[action.id]), None)
                elif len(action.options) == 1:
                    opt = action.options[0]
                if opt is None:
                    return None
                o_eff = self._effective_scope(opt.scope, eff)
                picks: list = []
                for a in opt.actions:
                    sub = flatten(a, offset, name, depth + 1, o_eff)
                    if sub is None:
                        return None
                    picks.extend(sub)
                return picks
            if t == "intensity_chooser":
                eff = self._effective_scope(action.scope, scope)
                lane = None
                if resolved_picks and action.id in resolved_picks:
                    lane = next((l for l in action.lanes if l.id == resolved_picks[action.id]), None)
                elif len(action.lanes) == 1:
                    lane = action.lanes[0]
                if lane is None:
                    return None
                l_eff = self._effective_scope(lane.scope, eff)
                picks = []
                for a in lane.actions:
                    sub = flatten(a, offset, lane.name or name, depth + 1, l_eff)
                    if sub is None:
                        return None
                    picks.extend(sub)
                return picks
            if t == "parallel_group":
                picks = []
                for c in action.children:
                    c_eff = self._effective_scope(c.scope, scope)
                    for a in c.actions:
                        sub = flatten(a, offset + int(c.offset_ms or 0), c.name or name, depth + 1, c_eff)
                        if sub is None:
                            return None
                        picks.extend(sub)
                return picks
            if scope is not None:
                action = self._apply_inherited_scope(action, scope)
            return [MorphPick(name, action, offset)]

        return flatten(root, 0, "")

    def _select_action(self, event: MusicEvent, labels: list[str]) -> Optional[Action]:
        """Pick an action from event.actions (delegates to _pick_from_actions).
        Kept as a thin wrapper for the existing `event.actions` call sites."""
        return self._pick_from_actions(
            event.actions, labels, dedupe_key=event.id, desc=f"event '{event.name}'"
        )

    def _pick_from_actions(
        self,
        actions: list[Action],
        labels: list[str],
        dedupe_key: str,
        desc: str = "",
        energy: float | None = None,
    ) -> Optional[Action]:
        """Weighted random pick from a list of Actions, honoring positive/
        negative label filters and de-weighting whatever was picked last under
        the same `dedupe_key`. Used by both `_select_action` (single-event
        action pool) and `_execute_morph_set` (per-lane alternatives pool).

        `energy` (trigger intensity 0-1) drives the RandomOption energy gate:
        options with a floor/ceiling outside it are excluded outright (all
        gated out = fire nothing), and energy_scale tilts surviving weights
        across the window. Plan-time callers pass it explicitly; fire-time
        callers inherit the per-task _FIRE_INTENSITY. None = gate off.
        """
        if not actions:
            return None

        pos_labels = [l.lower() for l in labels if not l.startswith("-")]
        neg_labels = [l[1:].lower() for l in labels if l.startswith("-")]

        candidates: list[tuple[int, Action]] = []
        for i, action in enumerate(actions):
            action_labels_lower = [l.lower() for l in action.labels]
            if pos_labels and not any(pl in action_labels_lower for pl in pos_labels):
                continue
            if any(nl in action_labels_lower for nl in neg_labels):
                continue
            if action.weight == 0 and not pos_labels:
                continue
            candidates.append((i, action))

        if not candidates:
            logger.info("No actions matched labels %s for %s; ignoring filter.", labels, desc or dedupe_key)
            candidates = list(enumerate(actions))

        if not candidates:
            return None

        if energy is None:
            energy = _FIRE_INTENSITY.get()
        energy_mult: dict[int, float] = {}
        if energy is not None:
            gated: list[tuple[int, Action]] = []
            for i, a in candidates:
                lo = getattr(a, "energy_floor", None)
                hi = getattr(a, "energy_ceiling", None)
                if lo is not None and energy < lo:
                    continue
                if hi is not None and energy > hi:
                    continue
                scale = getattr(a, "energy_scale", 0.0) or 0.0
                if scale:
                    w_lo = lo if lo is not None else 0.0
                    w_hi = hi if hi is not None else 1.0
                    t = 0.5 if w_hi <= w_lo else min(1.0, max(0.0, (energy - w_lo) / (w_hi - w_lo)))
                    energy_mult[i] = max(0.0, 1.0 + scale * (2.0 * t - 1.0))
                gated.append((i, a))
            if not gated:
                logger.info(
                    "Every option energy-gated out (energy=%.2f) for %s; firing nothing.",
                    energy, desc or dedupe_key,
                )
                return None
            candidates = gated

        last_idx = self._last_action.get(dedupe_key)
        weights = [0.0 if i == last_idx else a.weight * energy_mult.get(i, 1.0) for i, a in candidates]
        if sum(weights) == 0:
            weights = [a.weight * energy_mult.get(i, 1.0) for i, a in candidates]
        if sum(weights) == 0:
            weights = [1.0] * len(candidates)

        chosen_i, selected = random.choices(candidates, weights=weights, k=1)[0]
        self._last_action[dedupe_key] = chosen_i
        return selected

    def _describe_action(self, action: Action, _depth: int = 0,
                         resolved: dict | None = None) -> str:
        """Return a short human-readable label for a pre-selected action.
        `resolved` (random_group.id → option.id) drills into the picked branch
        so plan-time previews match what actually fires."""
        if action.type == "ledfx_scene":
            return action.scene_id
        elif action.type == "ledfx_ambient":
            parts = [action.color] if action.color else []
            if action.brightness is not None:
                parts.append(f"{int(action.brightness * 100)}% bright")
            return "Ambient " + (", ".join(parts) if parts else "–")
        elif action.type == "ledfx_ambient_color":
            return "Complementary color"
        elif action.type == "ledfx_reverse":
            return "Reverse"
        elif action.type == "ledfx_global_transition":
            return f"Transition {action.transition_time}s"
        elif action.type == "ledfx_effect_param":
            scope = action.virtual_id or action.category or "all"
            names = [p.param_label for p in action.params if p.param_label]
            body = ", ".join(names) if names else "params"
            return f"{body} ({scope})"
        elif action.type == "morph_step":
            n = len(action.targets)
            aspects = sorted({t.aspect for t in action.targets})
            body = ", ".join(aspects) if aspects else "no targets"
            name = getattr(action, "name", "") or ""
            if name:
                return f"Morph “{name}” ({body})"
            return f"Morph {n}× ({body})"
        elif action.type == "set_color":
            from models.music_event import SCENE_GROUP_COLOR_REF, CURRENT_COLOR_GROUP_REF
            from services import color_set_store
            if action.ref_id == SCENE_GROUP_COLOR_REF:
                return "Color → Scene Group's colors"
            if action.ref_id == CURRENT_COLOR_GROUP_REF:
                return "Color → current group"
            card = color_set_store.get_by_id(action.ref_id)
            name = card.name if card else "?"
            return f"Color → {name}"
        elif action.type == "morph_color":
            sign = "-" if action.direction == "backward" else "+"
            scope_bits = list(action.scope.categories) + list(action.scope.virtual_ids) + list(action.scope.roles)
            where = f" ({', '.join(scope_bits)})" if scope_bits else ""
            return f"Rotate {sign}{action.degrees:g}°{where}"
        elif action.type == "scene_morph":
            sign = "-" if action.direction == "backward" else "+"
            return f"Scene morph {sign}{action.advance}"
        elif action.type == "device_settings":
            return f"Device settings ({len(action.targets)}×)"
        elif action.type == "event_ref":
            if _depth < 3:
                sub = get_event(action.event_id)
                if sub and sub.event_type == "single":
                    resolved = self._select_action(sub, [])
                    if resolved:
                        return f"→ {self._describe_action(resolved, _depth + 1)}"
                elif sub:
                    return f"→ {sub.name}"
            return "→ (event ref)"
        elif action.type == "random_group":
            if resolved and action.id in resolved and _depth < 4:
                opt = next((o for o in action.options if o.id == resolved[action.id]), None)
                if opt is not None:
                    inner = ", ".join(
                        self._describe_action(a, _depth + 1, resolved) for a in opt.actions
                    )
                    return f"🎲 {opt.name or inner or '—'}" if not opt.name else f"🎲 {opt.name}: {inner}"
            return f"🎲 1 of {len(action.options)}"
        elif action.type == "intensity_chooser":
            if resolved and action.id in resolved and _depth < 4:
                lane = next((l for l in action.lanes if l.id == resolved[action.id]), None)
                if lane is not None:
                    idx = action.lanes.index(lane)
                    label = lane.name or ("default" if idx == 0 else f"lane {idx}")
                    inner = ", ".join(
                        self._describe_action(a, _depth + 1, resolved) for a in lane.actions
                    )
                    return f"⚡ {label}: {inner}" if inner else f"⚡ {label}"
            return f"⚡ 1 of {len(action.lanes)} lanes"
        elif action.type == "sequence_group":
            if _depth >= 3:
                return f"Seq · {len(action.children)} steps"
            parts = [
                ", ".join(self._describe_action(a, _depth + 1, resolved) for a in c.actions) or "—"
                for c in action.children
            ]
            return " > ".join(parts) if parts else "Seq (empty)"
        elif action.type == "parallel_group":
            if _depth >= 3:
                return f"⫴ {len(action.children)} lanes"
            parts = []
            for c in action.children:
                desc = ", ".join(self._describe_action(a, _depth + 1, resolved) for a in c.actions) or "—"
                if c.offset_ms:
                    desc = f"{desc} ({c.offset_ms:+d}ms)"
                parts.append(f"{c.name}: {desc}" if c.name else desc)
            return " · ".join(parts) if parts else "Parallel (empty)"
        return action.type

    _SIGNAL_SHORT = {
        "rms_total": "rms", "rms_bass": "bass", "onset_score": "onset",
        "section_energy": "energy", "trigger_intensity": "intensity",
    }

    @classmethod
    def _fmt_val(cls, v) -> str:
        """Short display value for the preview board: numbers trimmed,
        signal bindings shown as live·<signal>, tri-states as on/off/toggle."""
        from models.value_binding import ValueBinding
        if v is None:
            return "?"
        if isinstance(v, ValueBinding):
            return f"live·{cls._SIGNAL_SHORT.get(v.signal, v.signal)}"
        if isinstance(v, bool):
            return "on" if v else "off"
        if isinstance(v, str):
            return v
        return f"{float(v):g}"

    @staticmethod
    def _fmt_ramp(v) -> str:
        from models.value_binding import ValueBinding
        if isinstance(v, ValueBinding):
            return "live ramp"
        return "instant" if int(v) == 0 else f"{int(v) / 1000:g}s"

    @staticmethod
    def _scope_to_str(scope) -> str:
        if scope is None:
            return ""
        return ", ".join(
            list(scope.categories) + list(scope.roles) + list(scope.virtual_ids))

    def _collect_leaves(
        self, action, resolved: dict | None = None, tag: str = "",
        scope=None, skip_ids: set | None = None, _depth: int = 0,
        out: list | None = None,
    ) -> list[tuple[str, object, Action]]:
        """Flatten an action tree to the LEAF actions the fire will execute,
        following the same branches the executor takes: resolved random picks,
        event_ref → referenced composite roots, container scope inheritance.
        Returns [(tag, inherited_scope, action)] where `tag` is the deepest
        named container along the path (lane / child / option name) —
        intermediate event names are dropped (preview shows leaves, not the
        route). `skip_ids` mirrors the executor's skip_event_ids: event_refs
        planned as their own entries are excluded so rows aren't duplicated."""
        if out is None:
            out = []
        if action is None or _depth > 6:
            return out
        t = getattr(action, "type", "")
        if t == "random_group":
            eff = self._effective_scope(getattr(action, "scope", None), scope)
            opt = None
            if resolved and action.id in resolved:
                opt = next((o for o in action.options if o.id == resolved[action.id]), None)
            if opt is None and len(action.options) == 1:
                opt = action.options[0]
            if opt is None:
                out.append((tag, eff, action))  # unresolved 🎲 — described as-is
                return out
            opt_scope = self._effective_scope(opt.scope, eff)
            for a in opt.actions:
                self._collect_leaves(a, resolved, opt.name or tag, opt_scope,
                                     skip_ids, _depth + 1, out)
            return out
        if t == "intensity_chooser":
            eff = self._effective_scope(getattr(action, "scope", None), scope)
            lane = None
            if resolved and action.id in resolved:
                lane = next((l for l in action.lanes if l.id == resolved[action.id]), None)
            if lane is None and len(action.lanes) == 1:
                lane = action.lanes[0]
            if lane is None:
                out.append((tag, eff, action))  # unresolved ⚡ — described as-is
                return out
            lane_scope = self._effective_scope(lane.scope, eff)
            for a in lane.actions:
                self._collect_leaves(a, resolved, lane.name or tag, lane_scope,
                                     skip_ids, _depth + 1, out)
            return out
        if t in ("sequence_group", "parallel_group"):
            eff = self._effective_scope(getattr(action, "scope", None), scope)
            for c in action.children:
                c_scope = self._effective_scope(getattr(c, "scope", None), eff)
                for a in c.actions:
                    self._collect_leaves(a, resolved, c.name or tag, c_scope,
                                         skip_ids, _depth + 1, out)
            return out
        if t == "event_ref" and action.event_id:
            if skip_ids and action.event_id in skip_ids:
                return out  # planned as its own entry — that entry makes the rows
            sub = get_event(action.event_id)
            if sub is None:
                return out
            if sub.event_type == "composite" and sub.root is not None:
                # Referenced events keep their own scoping — don't inherit.
                return self._collect_leaves(sub.root, resolved, tag, None,
                                            skip_ids, _depth + 1, out)
            if sub.event_type == "single" and len(sub.actions) == 1:
                return self._collect_leaves(sub.actions[0], resolved, tag, None,
                                            skip_ids, _depth + 1, out)
            out.append((tag, scope, action))  # scene events / multi-pick singles
            return out
        out.append((tag, scope, action))
        return out

    def _describe_action_detail(
        self, action: Action, inherited_scope=None,
    ) -> tuple[str, list[str], str, str]:
        """Rich description of one pre-picked action for the Now Playing
        "next changes" board: WHAT parameters change and TO WHAT. Returns
        (text, swatch_colors, scope, full_text) — `text` is capped for the
        board row, `full_text` is the uncapped version for a tooltip. Color
        Group cycles deliberately show only the step count (the destination
        set stays a surprise); action types without a richer story fall back
        to _describe_action."""
        hexes: list[str] = []

        def _grab_hex(val: str | None) -> list[str]:
            # Gradients store rgb(r,g,b) stops; solids/BGs store #rrggbb.
            found = re.findall(r"#[0-9a-fA-F]{6}", val or "")
            for r, g, b in re.findall(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", val or ""):
                found.append(f"#{int(r):02x}{int(g):02x}{int(b):02x}")
            hexes.extend(found)
            return found

        _scope_str = self._scope_to_str

        def _cap(parts: list[str], scope: str = "", name: str = "",
                 suffix: str = "") -> tuple[str, list[str], str, str]:
            full = ", ".join(parts)
            text = full if len(parts) <= 4 else ", ".join(parts[:3]) + f", +{len(parts) - 3} more"
            if name:  # named morph step: lead with the name the user gave it
                full = f"“{name}” — {full}"
                text = f"“{name}” — {text}"
            return text + suffix, hexes[:6], scope, full + suffix

        if action.type == "morph_step":

            def _target_parts(t) -> list[str]:
                av = t.absolute_value
                a = t.aspect
                if a in ("brightness", "reactivity", "blur"):
                    parts: list[str] = []
                    if t.mode == "nudge":
                        if t.nudge_amount:
                            parts.append(f"{a} {t.nudge_amount:+g}")
                    elif av.number is not None:
                        parts.append(f"{a} → {self._fmt_val(av.number)}")
                    if a == "reactivity":
                        for pname, v in (av.reactivity_values or {}).items():
                            parts.append(f"{pname} → {self._fmt_val(v)}")
                        if t.mode == "nudge":
                            for pname, sp in (av.reactivity_nudges or {}).items():
                                if sp is not None and sp.amount:
                                    parts.append(f"{pname} {sp.amount:+g}")
                    return parts or [a]
                if a == "shape":
                    parts = []
                    for name in ("star", "edges", "twist", "x_offset", "y_offset",
                                 "swirl", "horizon_scale"):
                        if t.mode == "nudge":
                            sp = getattr(av, f"{name}_nudge", None)
                            if sp is not None and sp.amount:
                                parts.append(f"{name} {sp.amount:+g}")
                        else:
                            v = getattr(av, name)
                            if v is not None:
                                parts.append(f"{name} → {self._fmt_val(v)}")
                    for name in ("polygon", "flip", "reverse"):
                        v = getattr(av, name)
                        if v is not None:
                            parts.append(f"{name} {'toggle' if v == 'toggle' else self._fmt_val(v)}")
                    return parts or ["shape"]
                if a == "color":
                    found = _grab_hex(av.color_value)
                    if av.color_kind == "solid" and found:
                        return [f"color → {found[0]}"]
                    return [f"color → {'gradient' if av.color_kind == 'gradient' else (av.color_value or '?')}"]
                if a == "bg_color":
                    found = _grab_hex(av.bg_color)
                    return [f"bg → {found[0] if found else (av.bg_color or '?')}"]
                if a == "effect":
                    return [f"effect → {av.effect_type or '?'}"]
                return [a]

            name = getattr(action, "name", "") or ""
            ramp = f" ({self._fmt_ramp(action.ramp_ms)})" if action.ramp_ms is not None else ""
            eff = [self._effective_scope(t.scope, inherited_scope) for t in action.targets]
            scopes = {_scope_str(s) for s in eff}
            if len(scopes) <= 1:
                parts = [p for t in action.targets for p in _target_parts(t)]
                return _cap(parts, next(iter(scopes), ""), name, ramp)
            parts = [
                f"{_scope_str(s) or 'all'}: {p}"
                for t, s in zip(action.targets, eff) for p in _target_parts(t)
            ]
            return _cap(parts, "", name, ramp)

        if action.type == "set_color":
            from models.music_event import SCENE_GROUP_COLOR_REF, CURRENT_COLOR_GROUP_REF
            from services import color_set_store
            ramp = f" ({self._fmt_ramp(action.ramp_ms)})" if action.ramp_ms is not None else ""
            # Sentinel refs describe as whatever they resolve to RIGHT NOW so
            # preview rows show the actual group; fall back to a symbolic label.
            card = color_set_store.get_by_id(self._resolve_color_ref(action.ref_id))
            if card is None:
                sym = ("Scene Group's colors" if action.ref_id == SCENE_GROUP_COLOR_REF
                       else "current group" if action.ref_id == CURRENT_COLOR_GROUP_REF
                       else "?")
                return f"Color → {sym}", [], "", f"Color → {sym}"
            if card.kind == "group":
                mode = card.mode if action.pick_mode == "default" else action.pick_mode
                n = len(card.members or [])
                if mode == "cycle":
                    adv = self._fmt_val(action.advance)
                    sign = "-" if action.direction == "backward" else "+"
                    text = f"{sign}{adv} step{'' if adv == '1' else 's'} in “{card.name}” ({n} sets){ramp}"
                else:
                    text = f"random set from “{card.name}” ({n} sets){ramp}"
                return text, [], "", text
            for e in card.entries or []:
                for f in ("color_value", "bg_color", "accent_color"):
                    _grab_hex(getattr(e, f, None))
            seen: set[str] = set()
            swatches = [h for h in hexes if not (h.lower() in seen or seen.add(h.lower()))]
            text = f"Color Set “{card.name}”{ramp}"
            return text, swatches[:6], "", text

        if action.type == "morph_color":
            sign = "-" if action.direction == "backward" else "+"
            ramp = f" ({self._fmt_ramp(action.ramp_ms)})" if action.ramp_ms is not None else ""
            text = f"rotate hue {sign}{action.degrees:g}°{ramp}"
            scope = self._effective_scope(action.scope, inherited_scope)
            return text, [], _scope_str(scope), text

        if action.type == "ledfx_scene":
            text = f"Scene {action.scene_id}"
            return text, [], "", text

        text = self._describe_action(action)
        return text, [], "", text

    def _preview_rows(self, root_event: MusicEvent, plan: list[_PlanEntry]) -> list[dict]:
        """Structured rows for the Now Playing "next changes" board. Every plan
        entry is flattened to its LEAF actions (following locked random picks
        and event_ref chains — see _collect_leaves), each described in detail
        (params → values + ramp), then rows with identical change text are
        merged with combined tags/scopes. Each row: {tag, scope, text, full,
        colors, at_ms}; `at_ms` is the fire offset from the trigger point.
        JSON-safe."""
        rows: list[dict] = []
        trigger_ms = plan[0].trigger_ms if plan else 0

        def _add_leaves(entry: _PlanEntry, leaves: list, default_tag: str = "") -> None:
            for tag, l_scope, act in leaves:
                text, colors, scope, full = self._describe_action_detail(act, inherited_scope=l_scope)
                if not scope:
                    scope = self._scope_to_str(l_scope)
                rows.append({
                    "tag": tag or default_tag, "scope": scope, "text": text,
                    "full": full if full != text else "",
                    "colors": colors,
                    "at_ms": int(entry.fire_at_ms - trigger_ms),
                })

        for entry in plan:
            evt = entry.event
            et = evt.event_type
            child_tag = evt.name if evt.id != root_event.id else ""
            skip = entry.planned_descendant_ids or None
            if et in SCENE_EVENT_TYPES:
                if entry.preselected_scene_picks:
                    for i, act in entry.preselected_scene_picks:
                        nm = SCENE_LANE_NAMES[i] if 0 <= i < len(SCENE_LANE_NAMES) else str(i)
                        _add_leaves(entry, self._collect_leaves(
                            act, entry.resolved_picks, tag=nm, skip_ids=skip))
                else:
                    group_like = (et == "scene_group"
                                  or (fs := self._forced_scene_event()) is not None
                                  and fs.event_type == "scene_group")
                    rows.append({
                        "tag": child_tag or evt.name, "scope": "",
                        "text": ("next group scene picked at fire time"
                                 if group_like else
                                 "resolved at fire time (no active scene yet)"),
                        "full": "", "colors": [],
                        "at_ms": int(entry.fire_at_ms - trigger_ms),
                    })
            elif et == "morph_set" and entry.preselected_morph_picks:
                for p in entry.preselected_morph_picks:
                    _add_leaves(entry, self._collect_leaves(
                        p.action, entry.resolved_picks, tag=p.lane_name, skip_ids=skip))
            elif et == "single" and entry.preselected_action is not None:
                _add_leaves(entry, self._collect_leaves(
                    entry.preselected_action, entry.resolved_picks,
                    tag=child_tag, skip_ids=skip))
            elif et == "composite" and evt.root is not None:
                _add_leaves(entry, self._collect_leaves(
                    evt.root, entry.resolved_picks, tag=child_tag, skip_ids=skip))
            elif et in ("sequence", "beat_sequence"):
                for step in (evt.sequence_steps if et == "sequence" else evt.beat_sequence_steps):
                    if step.step_type != "action":
                        continue
                    for a in self._resolve_step_actions(step):
                        if a.type == "event_ref":
                            continue  # referenced events plan their own entries
                        _add_leaves(entry, self._collect_leaves(
                            a, entry.resolved_picks, tag=child_tag, skip_ids=skip))
            elif et == "device_settings":
                rows.append({
                    "tag": child_tag, "scope": "",
                    "text": f"Device settings ({len(evt.device_targets)}×)",
                    "full": "", "colors": [],
                    "at_ms": int(entry.fire_at_ms - trigger_ms),
                })

        # ── Merge rows whose change text is identical (per-device children
        # firing the same morph collapse into one row with combined scope). ──
        merged: list[dict] = []
        by_text: dict[str, dict] = {}
        for r in rows:
            m = by_text.get(r["text"])
            if m is None:
                by_text[r["text"]] = r
                merged.append(r)
                continue
            for f in ("tag", "scope"):
                if r[f] and r[f] not in (m[f].split(", ") if m[f] else []):
                    m[f] = f"{m[f]}, {r[f]}" if m[f] else r[f]
            for c in r["colors"]:
                if c not in m["colors"]:
                    m["colors"].append(c)
            m["at_ms"] = min(m["at_ms"], r["at_ms"])
        return merged

    def _preselect_sequence_steps(
        self, event: MusicEvent, trigger_labels: list[str]
    ) -> tuple[list, str]:
        """
        For a sequence event, pre-select one action per event-type step.
        Returns (step_actions_list, action_label_string).
        step_actions_list[i] is the pre-selected Action for step i (None if not applicable).
        """
        step_actions: list = []
        label_parts: list[str] = []
        for step in event.sequence_steps:
            if step.step_type == "event" and step.event_id:
                sub_event = get_event(step.event_id)
                if sub_event and sub_event.event_type == "single":
                    merged = trigger_labels + (step.labels or [])
                    action = self._select_action(sub_event, merged)
                    step_actions.append(action)
                    label_parts.append(self._describe_action(action) if action else "?")
                else:
                    step_actions.append(None)
                    if sub_event:
                        label_parts.append(sub_event.name)
            elif step.step_type == "action" and step.action:
                step_actions.append(None)  # deterministic, no need to store
                label_parts.append(self._describe_action(step.action))
            else:
                step_actions.append(None)
        return step_actions, " → ".join(label_parts)

    async def fire_event_now(self, event_id: str, labels: list[str] | None = None) -> bool:
        """
        Directly fire a MusicEvent by id, bypassing song-position checks.
        Used by the test/fire endpoint in the UI. Returns True on success.

        Wraps the whole body in `ledfx_client.force_allow()` so the user's
        explicit fire always reaches LedFX even mid-capture (when the audio-
        shape gate would otherwise mute writes). Pause is not consulted —
        manual fires intentionally work regardless of `state.paused`.

        When `event.scene_override == True` and the event has morph_step actions,
        skips the per-virtual write path entirely: builds the post-morph scene,
        pushes it + per-virtual transition_time to LedFX, then activates the
        shared `spotfx-morph-temp` scene so every device changes atomically.
        """
        event = get_event(event_id)
        if event is None:
            logger.warning("fire_event_now: unknown event %s", event_id)
            return False
        return await self.fire_event_object_now(event, labels)

    async def fire_event_object_now(
        self, event: MusicEvent, labels: list[str] | None = None
    ) -> bool:
        """Fire an in-memory MusicEvent that need not be saved — the body of
        fire_event_now, used by the editor's per-level Preview (an ad-hoc
        composite wrapping the previewed subtree)."""
        with ledfx_client.force_allow():
            # Composite: resolve random picks ONCE so the scene-override attempt
            # and the fallback bus dispatch fire the same branches.
            _rp: dict | None = None
            _so_picks = None
            if event.event_type == "composite" and event.root is not None:
                _rp = self._resolve_random_picks(event.root, list(labels or []))
                _so_picks = self._composite_scene_picks(event, _rp)

            # ── Scene-override fast path (manual fire = prepare inline + fire) ──
            if await self._maybe_fire_scene_override(event, labels=labels, picks=_so_picks):
                await ledfx_client.drain_bus()
                return True

            if event.event_type == "composite":
                await self._execute_composite(
                    event, list(labels or []), resolved_picks=_rp,
                )
            elif event.event_type == "single":
                action = self._select_action(event, labels or [])
                if action is None:
                    return False
                await self._execute_action(action, labels or [])
            elif event.event_type == "sequence":
                await self._execute_sequence(event, labels or [])
            elif event.event_type == "beat_sequence":
                # Test fire: use current song position or 0; fallback beats used if no librosa data
                trigger_ms = state.current_track.interpolated_progress_ms() if state.current_track else 0
                await self._execute_beat_sequence(event, trigger_ms, labels or [], step1_prefired=False)
            elif event.event_type == "morph_set":
                await self._execute_morph_set(event, labels or [])
            elif event.event_type == "device_settings":
                await self._apply_device_targets(event.device_targets)
            elif event.event_type in SCENE_EVENT_TYPES:
                await self._execute_scene_event(event, labels or [])
            # Wait for any pending coalesce-bus flush so the writes land before
            # we exit force_allow and the capture gate closes again.
            await ledfx_client.drain_bus()
        return True

    # ── Scene-override helpers ──────────────────────────────────────────────
    SCENE_OVERRIDE_TEMP_ID = "spotfx-morph-temp"

    def _event_eligible_for_scene_override(self, event, picks=None) -> bool:
        """Phase 1 scope: honor scene_override only for `single` and `morph_set`.
        For sequence / beat_sequence the flag is parsed and saved but ignored
        at fire time (per-step lookahead not implemented yet).

        A morph_set with MIXED per-lane offsets is NOT eligible: a single atomic
        scene activate fires all virtuals at once and can't stagger lanes in
        time, so we fall back to bus dispatch (which honors each lane's offset).
        Uniform offsets stay eligible — the whole activate just shifts, since
        the entry's fire_at_ms was already moved by that shared offset. When
        `picks` are known we check the picked lanes; otherwise we check the
        lanes directly (a conservative superset — mixed lanes always fall back)."""
        if not getattr(event, "scene_override", False):
            return False
        # random_group resolves at fire time, so the morph payload can't be
        # pre-staged into a scene — fall back to per-virtual bus dispatch.
        def _has_random_group(actions) -> bool:
            return any(getattr(a, "type", "") == "random_group" for a in (actions or []))
        if event.event_type == "single":
            if _has_random_group(event.actions):
                logger.info(
                    "Event '%s' contains a random_group — scene-override not honored "
                    "(picks resolve at fire time); using bus dispatch.", event.name,
                )
                return False
            return True
        if event.event_type == "morph_set":
            if picks is not None:
                if _has_random_group([p.action for p in picks]):
                    logger.info(
                        "Event '%s' picked a random_group lane — scene-override not "
                        "honored; using bus dispatch.", event.name,
                    )
                    return False
                offsets = {p.offset_ms for p in picks}
            else:
                if any(_has_random_group(l.alternatives) for l in (event.morph_lanes or [])):
                    logger.info(
                        "Event '%s' has random_group lane alternatives — scene-override "
                        "not honored; using bus dispatch.", event.name,
                    )
                    return False
                offsets = {int(l.offset_ms or 0) for l in (event.morph_lanes or [])}
            if len(offsets) > 1:
                logger.info(
                    "Event '%s' has mixed per-lane offsets %s — bus dispatch "
                    "(scene-override can't stagger an atomic activate).",
                    event.name, sorted(offsets),
                )
                return False
            return True
        if event.event_type == "composite":
            # Callers pass picks from _composite_scene_picks (resolved + flattened).
            # None = tree can't be one atomic activate (unresolved random, any
            # sequence_group, or empty root) — bus dispatch.
            if picks is None:
                logger.info(
                    "Event '%s' (composite) not flattenable for scene-override "
                    "(unresolved random / sequence group) — bus dispatch.", event.name,
                )
                return False
            offsets = {p.offset_ms for p in picks}
            if len(offsets) > 1:
                logger.info(
                    "Event '%s' (composite) has mixed offsets %s — bus dispatch.",
                    event.name, sorted(offsets),
                )
                return False
            return True
        logger.warning(
            "Event '%s' has scene_override=True but event_type=%s — not honored in Phase 1; "
            "falling back to the bus dispatch.",
            event.name, event.event_type,
        )
        return False

    def _collect_morph_actions_for_event(self, event, labels: list[str] | None = None) -> list:
        """For scene-override fires: gather the MorphStepActions that would land.
        For morph_set events, pre-picks lanes via the existing `_pick_morph_lanes`
        so the scene reflects the chosen picks."""
        from models.music_event import MorphStepAction
        if event.event_type == "single":
            return [a for a in (event.actions or []) if isinstance(a, MorphStepAction)]
        if event.event_type == "morph_set":
            picks = self._pick_morph_lanes(event, labels or [])
            return [p.action for p in picks if isinstance(p.action, MorphStepAction)]
        return []

    def _collect_device_settings_for_event(self, event, labels: list[str] | None = None,
                                           picks: list | None = None) -> list:
        """Scene-override fires: gather DeviceSettingTargets embedded in the prep
        event. The temp scene can't store virtual config (max_brightness /
        frequency band), so these are applied directly at activation. When the
        morph_set lane picks are already known, pass them so the device settings
        match the chosen picks."""
        from models.music_event import DeviceSettingsAction
        actions: list = []
        if picks is not None:
            actions = [p.action for p in picks if isinstance(p.action, DeviceSettingsAction)]
        elif event.event_type == "single":
            actions = [a for a in (event.actions or []) if isinstance(a, DeviceSettingsAction)]
        elif event.event_type == "morph_set":
            picks = self._pick_morph_lanes(event, labels or [])
            actions = [p.action for p in picks if isinstance(p.action, DeviceSettingsAction)]
        out: list = []
        for a in actions:
            out.extend(a.targets or [])
        return out

    def _build_scene_payload(self, morph_actions: list) -> Optional[dict]:
        """Wrap `morph_scene.build_scene_state` with a cache copy + an
        intensity resolver tied to `self._beat_intensity_now`. Returns None
        if the morph produced no touched virtuals (scene-override pointless)."""
        if not morph_actions:
            return None
        # Resolve value bindings now so the prestaged scene carries concrete
        # values (same ≤500ms-early drift as the nudge intensity_resolver).
        morph_actions = [resolve_action_bindings(a, self._signal_now) for a in morph_actions]
        import copy
        from services.morph_scene import build_scene_state
        working_cache = copy.deepcopy(dict(state.ledfx_virtual_cache))
        payload = build_scene_state(
            morph_actions,
            virtual_cache=working_cache,
            intensity_resolver=lambda src: self._beat_intensity_now(src),
            accent_per_vid=self._last_accent_by_vid,
        )
        if not payload.get("touched_virtuals"):
            return None
        return payload

    async def _push_scene_override_prep(self, payload: dict) -> bool:
        """POST the temp scene's virtuals + set per-virtual transition_time.
        Wrapped in force_allow by the caller; returns True if both succeeded."""
        scene_id = self.SCENE_OVERRIDE_TEMP_ID
        scene_virtuals = payload["scene_virtuals"]
        transition_times_ms = payload["transition_times_ms"]

        scene_ok = await ledfx_client.update_scene_virtuals(scene_id, scene_virtuals)
        if not scene_ok:
            return False

        # Set transition_time on every touched virtual concurrently. LedFX uses
        # this as the cross-fade duration during the upcoming scene activate.
        cfg_coros = [
            ledfx_client.set_virtual_config(vid, {"transition_time": (ms or 0) / 1000})
            for vid, ms in transition_times_ms.items()
        ]
        if cfg_coros:
            await asyncio.gather(*cfg_coros, return_exceptions=True)
        return True

    async def _fire_scene_override(self, payload: dict, event) -> None:
        """Activate the temp scene, update cache, persist post-state, broadcast."""
        scene_id = self.SCENE_OVERRIDE_TEMP_ID
        # Device settings (virtual config) can't ride in the scene — apply them
        # directly at activation so the prep event's settings land.
        dev_targets = payload.get("device_targets")
        if dev_targets:
            await self._apply_device_targets(dev_targets)
        await ledfx_client.trigger_scene(scene_id)

        # Update the local cache so subsequent compiles see the new state.
        from services import morph_effect_state
        updates = []
        for vid, post in payload["post_state_per_vid"].items():
            entry = state.ledfx_virtual_cache.setdefault(vid, {})
            entry["effect"] = {"type": post["type"], "config": dict(post["config"])}
            updates.append((vid, post["type"], dict(post["config"])))
        if updates:
            morph_effect_state.save_many(updates)

    async def _fire_color_lanes_alongside(
        self,
        picks,
        labels,
        anchor_offset_ms: int = 0,
        skip_event_ids: Optional[set] = None,
    ) -> None:
        """Fire only the Set Color / Morph Color picks from a morph_set's lanes.

        The scene-override payload is built from MorphStepActions only (see
        `build_scene_state` / `_collect_morph_actions_for_event`), so a Color Set
        lane would otherwise be silently dropped when the event uses
        scene-override. We run those color lanes through the normal bus path
        right alongside the atomic scene activate. The event is only on this
        path when its lane offsets are uniform, so the color picks share the
        same offset as the activate and fire with it (rel == 0)."""
        if not picks:
            return
        from models.music_event import MorphColorAction, SetColorAction
        color_picks = [p for p in picks if isinstance(p.action, (SetColorAction, MorphColorAction))]
        if color_picks:
            await self._fire_morph_picks(
                color_picks, labels or [], skip_event_ids=skip_event_ids,
                anchor_offset_ms=anchor_offset_ms,
            )

    async def _maybe_fire_scene_override(self, event, labels=None, picks=None) -> bool:
        """Combined prepare + fire for the manual / fallback path. Returns True
        iff scene-override was eligible AND actually completed (so the caller
        skips the regular dispatch). False if not eligible, no morph actions
        produced writes, or the LedFX prep call failed (caller falls back)."""
        if not self._event_eligible_for_scene_override(event, picks=picks):
            return False
        if picks is not None:
            from models.music_event import MorphStepAction
            morph_actions = [p.action for p in picks if isinstance(p.action, MorphStepAction)]
        else:
            morph_actions = self._collect_morph_actions_for_event(event, labels)
        payload = self._build_scene_payload(morph_actions)
        if payload is None:
            return False
        payload["device_targets"] = self._collect_device_settings_for_event(event, labels, picks=picks)
        if not await self._push_scene_override_prep(payload):
            logger.warning(
                "scene-override prep failed for event '%s' — falling back to bus dispatch",
                event.name,
            )
            return False
        await self._fire_scene_override(payload, event)
        # Color Set lanes aren't in the step-only scene payload — fire them too.
        if picks is not None:
            await self._fire_color_lanes_alongside(picks, labels)
        logger.info(
            "scene-override fired '%s' atomically (touched=%s)",
            event.name, payload["touched_virtuals"],
        )
        return True

    async def _fire_trigger(
        self, trigger: MusicTrigger, fired_at_ms: int = 0, effective_offset_ms: int = 0
    ) -> None:
        """
        Fallback trigger execution for triggers that weren't planned
        (e.g. fired before their preview tick ran). Plan-based firing is
        preferred — see `_execute_plan_entry` above.
        """
        if state.paused:
            logger.debug("Trigger %s skipped (service paused).", trigger.id)
            return
        _FIRE_INTENSITY.set(self._scaled_intensity(getattr(trigger, "intensity", 0.5)))
        _FIRE_COLOR_GROUP.set(getattr(trigger, "color_group_override", None))

        event = get_event(trigger.event_id)
        if event is None:
            logger.warning("Trigger %s references unknown event %s.", trigger.id, trigger.event_id)
            return

        morph_summary = ""
        if event.event_type == "single":
            action = self._preselected.pop(trigger.id, None) or self._select_action(event, trigger.labels)
            if action is None:
                return
            await self._execute_action(action, trigger.labels)
        elif event.event_type == "sequence":
            pre_steps = self._preselected_steps.pop(trigger.id, None)
            await self._execute_sequence(event, trigger.labels, pre_steps=pre_steps)
        elif event.event_type == "beat_sequence":
            step1_prefired = trigger.id in self._pre_fired
            asyncio.create_task(
                self._execute_beat_sequence(event, trigger.timestamp_ms, trigger.labels, step1_prefired)
            )
        elif event.event_type == "morph_set":
            # Pick synchronously so we can include the lane outcomes in the
            # trigger_fired broadcast, then fire the picks asynchronously.
            morph_picks = self._pick_morph_lanes(event, trigger.labels)
            asyncio.create_task(self._fire_morph_picks(morph_picks, trigger.labels))
            morph_summary = self._morph_picks_summary(morph_picks)
        elif event.event_type == "device_settings":
            asyncio.create_task(self._apply_device_targets(event.device_targets))
        elif event.event_type == "composite":
            # Resolve picks synchronously so the broadcast summary matches the fire.
            rp = self._resolve_random_picks(event.root, list(trigger.labels)) if event.root else {}
            if event.root is not None:
                morph_summary = self._describe_action(event.root, resolved=rp)
            asyncio.create_task(
                self._execute_composite(event, list(trigger.labels), resolved_picks=rp)
            )
        elif event.event_type in SCENE_EVENT_TYPES:
            # Lane choice depends on live scene state; resolve + fire async.
            asyncio.create_task(self._execute_scene_event(event, trigger.labels))

        asyncio.create_task(
            ws_manager.broadcast_trigger_fired(
                trigger.id, event.name, event.color,
                scheduled_ms=trigger.timestamp_ms,
                fired_at_ms=fired_at_ms,
                effective_offset_ms=effective_offset_ms,
                event_type=event.event_type,
                summary=morph_summary,
                intensity=self._scaled_intensity(getattr(trigger, "intensity", 0.5)),
            )
        )

    async def _auto_intensity_scale(self, profile: SongProfile) -> None:
        """Stamp a library-ranked starting intensity_scale (source="auto") on a
        song that has none. User-set values are never touched; songs that
        can't be ranked stay unset and fall through to genre/100%."""
        if profile.intensity_scale is not None:
            return
        try:
            from services.intensity_scale_service import compute_auto_scale
            scale = await asyncio.get_running_loop().run_in_executor(
                None, compute_auto_scale, profile.spotify_uri,
                list(profile.artist_genre or []) or None)
        except Exception:
            logger.warning("auto intensity-scale failed", exc_info=True)
            return
        if scale is None:
            return
        # Re-check on the loop: the user may have set the slider meanwhile.
        live = self._profile if (self._profile and
                                 self._profile.spotify_uri == profile.spotify_uri) else profile
        if live.intensity_scale is not None:
            return
        live.intensity_scale = scale
        live.intensity_scale_source = "auto"
        try:
            from services.profile_manager import save_profile
            save_profile(live)
            logger.info("auto intensity scale %.0f%% stamped on %s",
                        scale * 100, live.spotify_uri)
        except Exception:
            logger.warning("auto intensity-scale save failed", exc_info=True)

    def _intensity_scale_now(self) -> float:
        """Resolve the current song's intensity-scale multiplier (0-2 = 0-200%).
        Resolution order: SongProfile.intensity_scale if set (user slider /
        auto-computed), else the matching genre training profile's
        default_intensity_scale (cached per uri), else 1.0."""
        prof = self._profile
        if prof is None:
            return 1.0
        if prof.intensity_scale is not None:
            return max(0.0, min(2.0, float(prof.intensity_scale)))
        uri = prof.spotify_uri
        if self._genre_scale_uri != uri:
            from services.intensity_scale_service import resolve_genre_scale
            genres = state.current_track.genres if state.current_track else []
            if not genres:
                genres = prof.artist_genre or []
            self._genre_scale_uri = uri
            self._genre_scale_cache = resolve_genre_scale(genres)
        return self._genre_scale_cache

    def _scaled_intensity(self, raw: float | None) -> float | None:
        """Apply the song/genre intensity scaler to a raw trigger intensity,
        clamped back to 0-1. Applied at every point the intensity signal
        originates (plan-time gates/picks and the fire-time ContextVar), so
        gates, chooser lanes, bindings and the ⚡ broadcast all agree.
        None (no intensity context) passes through untouched."""
        if raw is None:
            return None
        return max(0.0, min(1.0, float(raw) * self._intensity_scale_now()))

    @staticmethod
    def _pick_intensity_lane(action, intensity: float | None):
        """Pick the IntensityLane for `intensity`. lanes[0] is the default
        lane; among lanes[1:] the highest threshold <= intensity wins, with
        equal thresholds resolved to the later lane. No intensity context
        (manual test fires) → default lane."""
        lanes = action.lanes
        if not lanes:
            return None
        if intensity is None:
            return lanes[0]
        best, best_thr = lanes[0], -1.0
        for lane in lanes[1:]:
            if lane.threshold <= intensity and lane.threshold >= best_thr:
                best, best_thr = lane, lane.threshold
        return best

    async def _execute_action(
        self, action: Action, labels: list[str] | None = None,
        await_ramps: bool = False, skip_event_ids: set[str] | None = None,
        _depth: int = 0, resolved_picks: dict | None = None,
        inherited_scope=None,
    ) -> None:
        """Dispatch a single action. `resolved_picks` (random_group.id →
        RandomOption.id) pins random branches to the plan-time resolution so
        fires match previews; absent entries fall back to fresh picks.
        `inherited_scope` is the nearest group/lane Target — leaves with empty
        scopes adopt it (see _apply_inherited_scope)."""
        if action.type in self.CONTAINER_ACTION_TYPES and _depth > 5:
            logger.warning("%s depth cap (5) hit — skipping nested group", action.type)
            return
        if action.type == "random_group":
            eff_scope = self._effective_scope(action.scope, inherited_scope)
            opt = None
            if resolved_picks and action.id in resolved_picks:
                opt = next((o for o in action.options if o.id == resolved_picks[action.id]), None)
            if opt is None:
                if not action.dedupe:
                    self._last_action.pop(action.id, None)  # forget last pick → no de-weighting
                opt = self._pick_from_actions(
                    action.options, labels or [], dedupe_key=action.id, desc="random group",
                )
            if opt and opt.actions:
                merged = (labels or []) + [l for l in opt.labels if l not in (labels or [])]
                opt_scope = self._effective_scope(opt.scope, eff_scope)
                await asyncio.gather(*(
                    self._execute_action(
                        a, merged, await_ramps=await_ramps,
                        skip_event_ids=skip_event_ids, _depth=_depth + 1,
                        resolved_picks=resolved_picks, inherited_scope=opt_scope,
                    )
                    for a in opt.actions
                ))
            return
        if action.type == "sequence_group":
            await self._execute_sequence_group(
                action, labels or [], skip_event_ids=skip_event_ids,
                resolved_picks=resolved_picks, _depth=_depth,
                inherited_scope=inherited_scope,
            )
            return
        if action.type == "parallel_group":
            await self._execute_parallel_group(
                action, labels or [], await_ramps=await_ramps,
                skip_event_ids=skip_event_ids,
                resolved_picks=resolved_picks, _depth=_depth,
                inherited_scope=inherited_scope,
            )
            return
        if action.type == "intensity_chooser":
            lane = None
            if resolved_picks and action.id in resolved_picks:
                lane = next((l for l in action.lanes if l.id == resolved_picks[action.id]), None)
            if lane is None:
                lane = self._pick_intensity_lane(action, _FIRE_INTENSITY.get())
            if lane and lane.actions:
                eff_scope = self._effective_scope(action.scope, inherited_scope)
                lane_scope = self._effective_scope(lane.scope, eff_scope)
                merged = (labels or []) + [l for l in lane.labels if l not in (labels or [])]
                await asyncio.gather(*(
                    self._execute_action(
                        a, merged, await_ramps=await_ramps,
                        skip_event_ids=skip_event_ids, _depth=_depth + 1,
                        resolved_picks=resolved_picks, inherited_scope=lane_scope,
                    )
                    for a in lane.actions
                ))
            return
        if inherited_scope is not None and action.type not in ("event_ref",):
            # Leaf: adopt the nearest Target where the leaf's own scope is empty.
            # event_refs are excluded — referenced events keep their own scoping.
            action = self._apply_inherited_scope(action, inherited_scope)
        if action.type == "event_ref":
            sub = get_event(action.event_id)
            if sub is None:
                logger.warning("event_ref: unknown event %s", action.event_id)
                return
            # Skip if this event_ref's target was planned separately — the plan
            # handles its offset-adjusted fire time, so we must not also fire it here.
            if skip_event_ids and sub.id in skip_event_ids:
                return
            # Fallback path (reached only for sub-events the planner didn't cover —
            # depth > 5, cycles, or new event_refs introduced after planning). In that
            # case sub.event_offset_ms is applied inline as a best-effort shift.
            if sub.event_offset_ms:
                if sub.event_offset_ms > 0:
                    await asyncio.sleep(sub.event_offset_ms / 1000)
                # Negative offsets in the fallback path have already "passed" — fire immediately.
            if sub.event_type == "sequence":
                await self._execute_sequence(sub, labels or [], skip_event_ids=skip_event_ids)
            elif sub.event_type == "beat_sequence":
                trigger_ms = state.current_track.interpolated_progress_ms() if state.current_track else 0
                await self._execute_beat_sequence(
                    sub, trigger_ms, labels or [],
                    skip_event_ids=skip_event_ids,
                )
            elif sub.event_type == "morph_set":
                await self._execute_morph_set(sub, labels or [], skip_event_ids=skip_event_ids)
            elif sub.event_type == "composite":
                # Honor scene_override on referenced setters (scene First
                # lanes fire them via event_ref): the atomic activate switches
                # every device FIRST and asserts the Color Set picks AFTER, so
                # a concurrent set_color can never address the pre-switch
                # effect and flip a device back to it (radial→orbits→radial
                # flicker). Bus dispatch remains the fallback.
                if getattr(sub, "scene_override", False):
                    _rp = resolved_picks
                    if _rp is None and sub.root is not None:
                        _rp = self._resolve_random_picks(sub.root, list(labels or []))
                    _sp = self._composite_scene_picks(sub, _rp)
                    if self._event_eligible_for_scene_override(sub, picks=_sp):
                        with ledfx_client.force_allow():
                            fired = await self._maybe_fire_scene_override(
                                sub, labels=labels, picks=_sp)
                            if fired:
                                await ledfx_client.drain_bus()
                                return
                # Forward the resolved map: group ids are uuids, so entries can
                # only match this sub-tree's own groups (deep plan-time locks —
                # e.g. scene-lane picks — resolve into the same map). Groups
                # not in the map still roll fresh.
                await self._execute_composite(sub, labels or [], skip_event_ids=skip_event_ids,
                                              resolved_picks=resolved_picks)
            elif sub.event_type in SCENE_EVENT_TYPES:
                await self._execute_scene_event(sub, labels or [], skip_event_ids=skip_event_ids)
            else:
                sub_action = self._select_action(sub, labels or [])
                if sub_action:
                    await self._execute_action(
                        sub_action, labels, await_ramps=await_ramps,
                        skip_event_ids=skip_event_ids, _depth=_depth + 1,
                        resolved_picks=resolved_picks,
                    )
            return

        if action.type == "ledfx_scene":
            await ledfx_client.trigger_scene(action.scene_id)

        elif action.type == "ledfx_ambient":
            # Build effect config patch from non-None fields
            patch: dict = {}
            if action.color:
                patch["gradient"] = action.color
                patch["background_color"] = action.color
                patch["sparks_color"] = action.color
            if action.brightness is not None:
                patch["brightness"] = action.brightness
            if action.blur is not None:
                patch["blur"] = action.blur
            if action.bass_decay_rate is not None:
                patch["bass_decay_rate"] = action.bass_decay_rate
            if action.background_brightness is not None:
                patch["background_brightness"] = action.background_brightness
            if patch:
                for vid in get_virtuals_for_role("ambient"):
                    await ledfx_client.set_virtual_effect(vid, "power", patch)
            if action.max_brightness is not None:
                for vid in get_virtuals_for_role("ambient"):
                    await ledfx_client.set_virtual_config(
                        vid, {"max_brightness": action.max_brightness}
                    )

        elif action.type == "ledfx_ambient_color":
            amb_vids = get_virtuals_for_role("ambient")
            if not amb_vids:
                return
            # Read cached color from first ambient virtual — fall back to live GET
            primary = amb_vids[0]
            virtual = state.ledfx_virtual_cache.get(primary, {})
            if not virtual:
                live = await ledfx_client.get_virtual(primary)
                if live:
                    virtual = live.get(primary, live)
                    state.ledfx_virtual_cache[primary] = virtual
                    logger.info("ledfx_ambient_color: cache was empty, fetched live virtual state")
            effect_type = virtual.get("effect", {}).get("type", "")
            if effect_type.lower() != "power":
                logger.warning(
                    "ledfx_ambient_color skipped — %s is running '%s', not 'power'",
                    primary, effect_type,
                )
                return
            effect_cfg = virtual.get("effect", {}).get("config", {})
            raw = effect_cfg.get("gradient") or effect_cfg.get("background_color", "#ffffff")
            m = re.search(r'#([0-9a-fA-F]{6})', raw)
            if not m:
                logger.warning("ledfx_ambient_color: no hex color in cached value '%s'", raw)
                return
            h = m.group(0)
            r, g, b = int(h[1:3], 16) / 255, int(h[3:5], 16) / 255, int(h[5:7], 16) / 255
            hue, s, v = colorsys.rgb_to_hsv(r, g, b)
            r2, g2, b2 = colorsys.hsv_to_rgb((hue + 0.5) % 1.0, s, v)
            comp = f"#{int(r2 * 255):02x}{int(g2 * 255):02x}{int(b2 * 255):02x}"
            color_patch = {"gradient": comp, "background_color": comp, "sparks_color": comp}
            for vid in amb_vids:
                await ledfx_client.set_virtual_effect(vid, "power", color_patch)
                # Update cache immediately so a back-to-back firing reads the new color
                cached = state.ledfx_virtual_cache.get(vid, {})
                cfg = cached.get("effect", {}).get("config")
                if cfg is not None:
                    cfg["gradient"] = comp
                    cfg["background_color"] = comp
                    cfg["sparks_color"] = comp

        elif action.type == "ledfx_global_transition":
            cfg: dict = {"transition_time": action.transition_time}
            if action.transition_mode:
                cfg["transition_mode"] = action.transition_mode
            vids = get_all_virtual_ids()
            if vids:
                await asyncio.gather(
                    *(ledfx_client.set_virtual_config(vid, cfg) for vid in vids),
                    return_exceptions=True,
                )

        elif action.type == "ledfx_effect_param":
            action = resolve_action_bindings(action, self._signal_now)
            from services.effect_params import get_virtuals_for_category, resolve_params, get_param_meta
            if action.virtual_id:
                virtuals = [action.virtual_id]
            elif action.category:
                virtuals = get_virtuals_for_category(action.category)
            else:
                virtuals = get_all_virtual_ids()
            ramp_ms = action.ramp_ms if action.ramp_ms is not None else settings.smooth_ramp_ms
            instant_coros = []
            ramp_jobs: list = []
            polar_changes: dict = {}  # vid → (angle, radius, effect_type)
            for vid in virtuals:
                cached = ledfx_client.get_virtual_cache(vid)
                if not cached:
                    # Live fallback when cache is empty (e.g. first fire after startup)
                    live_data = await ledfx_client.get_virtual(vid)
                    if live_data:
                        cached = live_data.get(vid, live_data)
                        state.ledfx_virtual_cache[vid] = cached
                if not cached:
                    continue
                effect_type = cached.get("effect", {}).get("type")
                if not effect_type:
                    continue
                effect_cfg = cached.get("effect", {}).get("config", {})
                patch: dict = {}
                for change in action.params:
                    for pname in resolve_params(effect_type, change.param_label):
                        meta = get_param_meta(effect_type, pname)
                        if meta and meta.get("type") == "polar":
                            # Defer to polar ramp; store per-virtual, don't add to patch
                            if change.polar_angle is not None and change.polar_radius is not None:
                                polar_changes[vid] = (change.polar_angle, change.polar_radius, effect_type)
                            continue
                        elif meta and meta.get("type") in ("color", "gradient", "string"):
                            if change.string_value is not None:
                                patch[pname] = change.string_value
                        elif meta and meta.get("sign_control"):
                            # Virtual param: maps_to holds the real LedFX param; control sign only
                            actual_pname = meta["maps_to"]
                            current = ledfx_client.get_cached_param(vid, actual_pname) or 0.0
                            ta = change.toggle_action
                            if ta == "on":
                                new_val = abs(current)
                            elif ta == "off":
                                new_val = -abs(current)
                            else:  # "toggle" or None
                                new_val = -current
                            patch[actual_pname] = round(new_val, 4)
                        elif meta and meta.get("type") == "toggle":
                            ta = change.toggle_action
                            if ta == "on":
                                patch[pname] = True
                            elif ta == "off":
                                patch[pname] = False
                            else:  # "toggle" or None
                                patch[pname] = not effect_cfg.get(pname, False)
                        elif meta and meta.get("magnitude_only"):
                            # Preserve sign of current value, only change magnitude
                            current = ledfx_client.get_cached_param(vid, pname) or 0.0
                            sign = -1 if current < 0 else 1
                            patch[pname] = round(sign * abs(change.target_value), 4)
                        elif meta and meta.get("scale_offset") and change.flip_sign:
                            # X/Y offset flip: work in frontend -1..1 space, then convert to LedFX 0..1
                            _cl = ledfx_client.get_cached_param(vid, pname)
                            cur_l = _cl if _cl is not None else 0.5
                            cur_f = (cur_l - 0.5) * 2  # → frontend -1..1
                            new_sign = 1 if cur_f < 0 else -1
                            mag = abs(change.target_value) if change.target_value != 0 else abs(cur_f)
                            patch[pname] = round((new_sign * mag) / 2 + 0.5, 4)
                        elif meta and meta.get("scale_offset"):
                            # X/Y offset normal: target_value is in frontend -1..1, convert to LedFX 0..1
                            patch[pname] = round(change.target_value / 2 + 0.5, 4)
                        elif meta and meta.get("flip_sign") and change.flip_sign:
                            # twist/star etc.: flip sign in native LedFX space
                            current = ledfx_client.get_cached_param(vid, pname) or 0.0
                            new_sign = 1 if current < 0 else -1
                            mag = abs(change.target_value) if change.target_value != 0 else abs(current)
                            patch[pname] = round(new_sign * mag, 4)
                        elif meta and meta.get("type") == "move_xy":
                            # Relative move in XY: add delta to current position, clamp -1..1
                            dx = change.move_x or 0.0
                            dy = change.move_y or 0.0
                            _cxl = ledfx_client.get_cached_param(vid, "x_offset")
                            _cyl = ledfx_client.get_cached_param(vid, "y_offset")
                            cur_xl = _cxl if _cxl is not None else 0.5
                            cur_yl = _cyl if _cyl is not None else 0.5
                            new_xf = max(-1, min(1, (cur_xl - 0.5) * 2 + dx))
                            new_yf = max(-1, min(1, (cur_yl - 0.5) * 2 + dy))
                            patch["x_offset"] = round(new_xf / 2 + 0.5, 4)
                            patch["y_offset"] = round(new_yf / 2 + 0.5, 4)
                        elif meta and meta.get("type") == "move_polar":
                            # Relative move in polar: add deltas to current angle/radius
                            import math as _math
                            da = change.move_angle or 0.0
                            dr = change.move_radius or 0.0
                            _cxl = ledfx_client.get_cached_param(vid, "x_offset")
                            _cyl = ledfx_client.get_cached_param(vid, "y_offset")
                            cur_xl = _cxl if _cxl is not None else 0.5
                            cur_yl = _cyl if _cyl is not None else 0.5
                            cx = (cur_xl - 0.5) * 2
                            cy = (cur_yl - 0.5) * 2
                            cur_r = _math.sqrt(cx ** 2 + cy ** 2)
                            cur_a = _math.degrees(_math.atan2(cx, cy))
                            polar_changes[vid] = (cur_a + da, max(0, min(1, cur_r + dr)), effect_type)
                            continue
                        else:
                            patch[pname] = change.target_value
                if not patch:
                    continue
                if action.fallback_s is not None:
                    # Flare-style burst: POST the full merged config with LedFX's
                    # server-side fallback so the prior effect auto-restores after
                    # fallback_s seconds. Cache is left untouched — it keeps the
                    # canonical (restored-to) state.
                    merged = {**effect_cfg, **patch}
                    instant_coros.append(
                        ledfx_client.set_virtual_effect_fallback(
                            vid, effect_type, merged, action.fallback_s
                        )
                    )
                    continue
                # Booleans fire instantly; strings split into instant vs ramp by smooth flag; numerics can ramp
                bool_patch = {k: v for k, v in patch.items() if isinstance(v, bool)}
                str_patch  = {k: v for k, v in patch.items() if isinstance(v, str)}
                num_patch  = {k: v for k, v in patch.items() if not isinstance(v, (bool, str))}
                # Split strings: smooth=True + ramp_ms>0 → gradient ramp; else instant
                instant_str: dict = {}
                ramp_str: dict = {}
                for k, v in str_patch.items():
                    pmeta = get_param_meta(effect_type, k)
                    if pmeta and pmeta.get("smooth") and ramp_ms > 0:
                        ramp_str[k] = v
                    else:
                        instant_str[k] = v
                if bool_patch or instant_str:
                    instant_coros.append(ledfx_client.set_virtual_effect(vid, effect_type, {**bool_patch, **instant_str}))
                    # Update cache immediately — instant, so no ramp reads these before they land
                    effect_cfg.update({**bool_patch, **instant_str})
                if num_patch:
                    if ramp_ms > 0:
                        coro = ledfx_client.ramp_effect_params(vid, effect_type, num_patch, ramp_ms)
                        if await_ramps:
                            # Cache patch lands AFTER the gather so the next step's
                            # ramp_effect_params reads the correct post-ramp start value
                            # (not the pre-ramp value). Revert snapshot was taken before
                            # the sequence, so it's unaffected.
                            ramp_jobs.append((coro, effect_cfg, num_patch))
                        else:
                            self._spawn_ramp(coro)
                    else:
                        instant_coros.append(ledfx_client.set_virtual_effect(vid, effect_type, num_patch))
                        effect_cfg.update(num_patch)
                if ramp_str:
                    coro = ledfx_client.ramp_gradient_params(vid, effect_type, ramp_str, ramp_ms)
                    if await_ramps:
                        ramp_jobs.append((coro, None, None))
                    else:
                        self._spawn_ramp(coro)
            if instant_coros:
                await asyncio.gather(*instant_coros)
            # Dispatch polar offset ramps (x_offset + y_offset interpolated in polar space)
            if polar_changes:
                import math as _math
                polar_instant_coros = []
                for _vid, (_angle, _radius, _etype) in polar_changes.items():
                    if ramp_ms > 0:
                        coro = ledfx_client.ramp_polar_offset(_vid, _etype, _angle, _radius, ramp_ms)
                        if await_ramps:
                            ramp_jobs.append((coro, None, None))
                        else:
                            self._spawn_ramp(coro)
                    else:
                        _ar = _math.radians(_angle)
                        _xl = round(_math.sin(_ar) * _radius / 2 + 0.5, 4)
                        _yl = round(_math.cos(_ar) * _radius / 2 + 0.5, 4)
                        polar_instant_coros.append(
                            ledfx_client.set_virtual_effect(_vid, _etype, {"x_offset": _xl, "y_offset": _yl})
                        )
                if polar_instant_coros:
                    await asyncio.gather(*polar_instant_coros)
            await self._await_ramps_parallel(ramp_jobs)

        elif action.type == "morph_step":
            await self._execute_morph_step(action, await_ramps=await_ramps)

        elif action.type == "set_color":
            await self._execute_set_color(action, await_ramps=await_ramps)

        elif action.type == "morph_color":
            await self._execute_morph_color(action, await_ramps=await_ramps)

        elif action.type == "scene_morph":
            await self._execute_scene_morph(action, labels or [],
                                            skip_event_ids=skip_event_ids)

        elif action.type == "device_settings":
            await self._apply_device_targets(action.targets)

        else:
            logger.warning("Unknown action type: %s", action.type)

    async def _apply_device_targets(self, targets: list) -> None:
        """Apply Device Settings (virtual-config: max_brightness / frequency band)
        to every scoped virtual. Each target field is optional — only set fields
        are written. Instant (set_virtual_config); also mirrored into the cache."""
        from services.morph_compiler import resolve_scope
        coros = []
        for t in (targets or []):
            cfg: dict = {}
            if t.max_brightness is not None:
                cfg["max_brightness"] = t.max_brightness
            if t.frequency_min is not None:
                cfg["frequency_min"] = int(t.frequency_min)
            if t.frequency_max is not None:
                cfg["frequency_max"] = int(t.frequency_max)
            if not cfg:
                continue
            for vid in resolve_scope(t.scope):
                coros.append(ledfx_client.set_virtual_config(vid, dict(cfg)))
                vc = state.ledfx_virtual_cache.setdefault(vid, {}).setdefault("config", {})
                vc.update(cfg)
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    async def _execute_morph_step(self, action, await_ramps: bool = False) -> None:
        """Dispatch a MorphStepAction in two compile passes so an in-step effect
        switch is visible to subsequent param targets on the same virtual.

        Pass 1: compile effect-switch targets against the current cache. Fire
        switches (instant). Snapshot each virtual's pre-switch (effect, config)
        to persisted morph_effect_state so a later switch-back can resume it.
        Mutate the cache to reflect the new effect + its starter config.

        Pass 2: compile non-effect targets against the now-updated cache. Patch
        params using the same instant/string-ramp/numeric-ramp split as
        `ledfx_effect_param`.

        Finally, persist the post-action (effect, config) for every touched
        virtual so future switch-backs resume the right state.
        """
        action = resolve_action_bindings(action, self._signal_now)
        from services.morph_compiler import compile_target, resolve_scope
        from services.effect_params import get_param_meta
        from services import morph_effect_state

        # Refresh each scoped virtual's LIVE effect type so param patches address
        # the device's current effect (not a stale cached one, which would make
        # the write switch the effect). Explicit aspect=effect targets still
        # switch as intended.
        await self._refresh_effect_types(
            [vid for t in action.targets for vid in resolve_scope(t.scope)]
        )

        # ── Pass 1: effect-switch targets (no nudge — effect switches are absolute) ─
        # Effect-switch writes source the new effect's accent / third color from
        # the last fired Color Set's 3rd color per virtual (else black). An
        # effect target on a device ALREADY running that effect emits a patch
        # (kind="patch") that re-asserts the accent — keeps it in sync with a
        # sibling that switched — rather than a switch; route those to Pass 2.
        switch_writes = []
        accent_sync_writes = []
        for target in action.targets:
            if target.aspect != "effect":
                continue
            for w in compile_target(target, state.ledfx_virtual_cache, default_ramp_ms=action.ramp_ms,
                                    accent_per_vid=self._last_accent_by_vid):
                (switch_writes if w.kind == "switch" else accent_sync_writes).append(w)

        # Non-ramping values we intend this step, accumulated per virtual so we
        # can read them back and re-issue any that didn't land (effect type,
        # colors incl. the third/accent sparks_color, bools, instant numerics).
        # Ramped params are deliberately excluded — they may be mid-flight.
        verify_targets: dict[str, dict] = {}
        def _vt(vid: str) -> dict:
            return verify_targets.setdefault(vid, {"type": None, "config": {}})

        switch_coros = []
        for w in switch_writes:
            # Snapshot the pre-switch (effect, config) before we lose it, so
            # future switch-backs to that effect resume the user's prior state.
            pre = state.ledfx_virtual_cache.get(w.virtual_id) or {}
            pre_eff = (pre.get("effect") or {})
            if pre_eff.get("type") and pre_eff.get("type") != w.new_effect_type:
                morph_effect_state.save(w.virtual_id, pre_eff["type"], dict(pre_eff.get("config") or {}))

            starter = w.starter_config or {}
            switch_coros.append(
                ledfx_client.set_virtual_effect(
                    w.virtual_id, w.new_effect_type, starter, is_switch=True
                )
            )
            # Mirror the switch into the cache so Pass 2 sees the new effect.
            state.ledfx_virtual_cache.setdefault(w.virtual_id, {})["effect"] = {
                "type": w.new_effect_type,
                "config": dict(starter),
            }
            # Verify the type + the discrete (colour/toggle) starter fields.
            # On a switch between particle-handoff siblings, the incoming
            # effect intentionally adopts the predecessor's gradient and spin
            # direction at first draw — verifying those would "correct" the
            # handoff and visibly snap color/direction mid-crossfade.
            _HANDOFF_FAMILY = {
                "orbits", "blackhole", "radial", "fireworks",
                "orbits1d", "blackhole1d", "fireworks1d",
            }
            handoff_pair = (
                pre_eff.get("type") in _HANDOFF_FAMILY
                and w.new_effect_type in _HANDOFF_FAMILY
            )
            vt = _vt(w.virtual_id)
            vt["type"] = w.new_effect_type
            vt["config"].update(
                {
                    k: v
                    for k, v in starter.items()
                    if isinstance(v, (str, bool))
                    and not (handoff_pair and k in ("gradient", "reverse"))
                }
            )
        if switch_coros:
            await asyncio.gather(*switch_coros, return_exceptions=True)

        # ── Pass 2: non-effect targets, compiled against the post-switch cache ─
        # Resolve beat intensity once per step (action.intensity_source). Every
        # nudge target — and every per-Shape-sub-field nudge spec — reads the
        # same value, keeping the step's audio response coherent.
        patch_writes = list(accent_sync_writes)
        step_source = getattr(action, "intensity_source", None) or "rms_total"
        any_nudge = any(t.mode == "nudge" and t.aspect != "effect" for t in action.targets)
        intensity = self._beat_intensity_now(step_source) if any_nudge else None
        for target in action.targets:
            if target.aspect == "effect":
                continue
            patch_writes.extend(
                compile_target(
                    target, state.ledfx_virtual_cache,
                    default_ramp_ms=action.ramp_ms,
                    intensity=intensity if target.mode == "nudge" else None,
                    nudge_dir=self._nudge_dir,
                )
            )

        default_ramp_ms = action.ramp_ms if action.ramp_ms is not None else settings.smooth_ramp_ms
        touched: set[str] = {w.virtual_id for w in switch_writes}
        instant_coros: list = []
        ramp_jobs: list = []

        for w in patch_writes:
            ramp_ms = w.ramp_ms if w.ramp_ms is not None else default_ramp_ms
            patch = dict(w.patch or {})
            if not patch:
                continue
            touched.add(w.virtual_id)

            bool_patch = {k: v for k, v in patch.items() if isinstance(v, bool)}
            str_patch  = {k: v for k, v in patch.items() if isinstance(v, str)}
            num_patch  = {k: v for k, v in patch.items() if not isinstance(v, (bool, str))}

            instant_str: dict = {}
            ramp_str: dict = {}
            # Server-side tweens bypass LedFX's color-recreation path, so
            # effect-resetting colour params (any flagged `resets_effect`) CAN
            # be tweened smoothly there. On the legacy client loop they must
            # stay instant — ramming them through 40 frames restarts the effect.
            _allow_reset_ramp = ledfx_client.server_tween_enabled()
            for k, v in str_patch.items():
                pmeta = get_param_meta(w.effect_type, k)
                if (
                    pmeta and pmeta.get("smooth") and ramp_ms > 0
                    and (_allow_reset_ramp or not _param_resets_effect(w.effect_type, k))
                ):
                    ramp_str[k] = v
                else:
                    instant_str[k] = v

            effect_cfg = state.ledfx_virtual_cache.setdefault(w.virtual_id, {}).setdefault("effect", {}).setdefault("config", {})

            if bool_patch or instant_str:
                instant_coros.append(
                    ledfx_client.set_virtual_effect(w.virtual_id, w.effect_type, {**bool_patch, **instant_str})
                )
                effect_cfg.update({**bool_patch, **instant_str})
                _vt(w.virtual_id)["config"].update({**bool_patch, **instant_str})

            if num_patch:
                if ramp_ms > 0:
                    coro = ledfx_client.ramp_effect_params(w.virtual_id, w.effect_type, num_patch, ramp_ms)
                    if await_ramps:
                        # Cache patch lands post-gather so the next step's
                        # ramp_effect_params reads the post-ramp start value.
                        ramp_jobs.append((coro, effect_cfg, num_patch))
                    else:
                        self._spawn_ramp(coro)
                else:
                    instant_coros.append(
                        ledfx_client.set_virtual_effect(w.virtual_id, w.effect_type, num_patch)
                    )
                    effect_cfg.update(num_patch)
                    _vt(w.virtual_id)["config"].update(num_patch)

            if ramp_str:
                coro = ledfx_client.ramp_gradient_params(w.virtual_id, w.effect_type, ramp_str, ramp_ms)
                if await_ramps:
                    ramp_jobs.append((coro, None, None))
                else:
                    self._spawn_ramp(coro)

        if instant_coros:
            await asyncio.gather(*instant_coros, return_exceptions=True)
        await self._await_ramps_parallel(ramp_jobs)

        # ── Verify non-ramping writes landed; re-issue any that didn't ─────────
        # Sparks-when-power guarantee: for any verified virtual now on the
        # `power` effect, make sure the sparks params are checked even if this
        # step didn't explicitly touch them (LedFX re-fills sparks_color white on
        # a switch). Source the intended values from the post-write cache.
        if verify_targets and settings.verify_nonramping_writes:
            for vid, spec in verify_targets.items():
                eff = (state.ledfx_virtual_cache.get(vid) or {}).get("effect") or {}
                if (spec.get("type") or eff.get("type")) == "power":
                    cfg = eff.get("config") or {}
                    for sp in ("sparks_color", "sparks_decay_rate"):
                        if sp not in spec["config"] and sp in cfg:
                            spec["config"][sp] = cfg[sp]
            corrected = await ledfx_client.verify_and_correct(
                verify_targets,
                settle_ms=settings.verify_settle_ms,
                timeout_ms=settings.verify_timeout_ms,
            )
            if corrected:
                logger.warning("morph verify corrected non-ramping writes: %s", corrected)

        # ── Persist post-action state for every touched virtual ───────────────
        if touched:
            updates = []
            for vid in touched:
                entry = state.ledfx_virtual_cache.get(vid) or {}
                eff = entry.get("effect") or {}
                etype = eff.get("type")
                cfg = eff.get("config") or {}
                if etype and cfg:
                    updates.append((vid, etype, dict(cfg)))
            if updates:
                morph_effect_state.save_many(updates)

    def _select_color_set_member(
        self, group, pick_mode: str, advance: int = 1, direction: str = "forward"
    ) -> Optional[str]:
        """Pick one member Color Set id from a Group, updating in-memory cursor
        state. `pick_mode` ("default"|"cycle"|"weighted") overrides the group's
        own `mode` unless "default". For cycle mode, `advance` is how many
        members to move per fire (1 = next, 3 = skip 2) and `direction`
        ("forward"|"backward") sets travel: absolute index direction for wrap,
        and relative to the current bounce direction for bounce ("backward"
        reverses it). A move never settles on the set currently showing —
        except advance=0, which deliberately stays put (repaint/align); in
        bounce with advance > 1 it also avoids the set from two fires ago, so an
        even advance can't ping-pong between two endpoints (e.g. n=3 advance=2).

        Palette Sync (group.palette_sync): instead of this group's private
        cursor, the move starts from the member matching the room's CURRENT
        palette — the exact last-applied set when it's a member here, else the
        member nearest the shared palette hue — and the pick's hue is published
        back. Synced groups therefore walk one shared palette position instead
        of each jumping to wherever its own cursor last sat.
        Returns the color_set_id."""
        members = group.members or []
        if not members:
            return None
        n = len(members)
        mode = group.mode if pick_mode == "default" else pick_mode
        cur = self._color_cursor.get(group.id)
        prev = self._color_cursor_prev.get(group.id)
        adv = max(0, int(advance))
        back = direction == "backward"

        sync = bool(getattr(group, "palette_sync", False))
        member_hues: list[Optional[float]] = []
        if sync:
            member_hues = self._member_palette_hues(members)
            anchor = self._palette_sync_anchor(members, member_hues)
            if anchor is not None and anchor != cur:
                # Re-anchored to the room's palette: the private bounce
                # history no longer applies.
                cur, prev = anchor, None

        if mode == "cycle":
            if cur is None:
                idx = 0
                self._color_cursor_dir[group.id] = -1 if back else 1
            elif adv == 0:
                # advance 0 = stay: re-apply the current member (for a Palette
                # Sync group, `cur` was just re-anchored to the room's palette,
                # so this repaints the scoped devices in the current family).
                idx = cur
            elif group.cycle_behavior == "bounce" and n > 1:
                d = self._color_cursor_dir.get(group.id, 1)
                if back:
                    d = -d  # "backward" reverses the current bounce direction

                def _bounce_step(i, dd):
                    nxt = i + dd
                    if nxt >= n:
                        dd, nxt = -1, i - 1
                    elif nxt < 0:
                        dd, nxt = 1, i + 1
                    return nxt, dd

                idx = cur
                for _ in range(adv):
                    idx, d = _bounce_step(idx, d)
                # Never settle on the set already showing; for advance > 1 also
                # avoid the set from two fires ago so an even stride can't get
                # stuck ping-ponging between two endpoints. Step one further
                # (reflecting) until clear; bounded by n since single steps visit
                # every index.
                forbidden = {cur}
                if adv > 1 and n > 2 and prev is not None:
                    forbidden.add(prev)
                guard = 0
                while idx in forbidden and guard < n:
                    idx, d = _bounce_step(idx, d)
                    guard += 1
                self._color_cursor_dir[group.id] = d
            else:  # wrap (or single-member bounce)
                idx = (cur + (-adv if back else adv)) % n
                if idx == cur and n > 1:
                    idx = (idx + (-1 if back else 1)) % n
        else:  # weighted
            last_idx = cur if group.exclude_current else None
            weights = [0.0 if i == last_idx else m.weight for i, m in enumerate(members)]
            if sum(weights) == 0:
                weights = [m.weight for m in members]
            if sum(weights) == 0:
                weights = [1.0] * n
            idx = random.choices(range(n), weights=weights, k=1)[0]

        self._color_cursor_prev[group.id] = cur  # what this fire's cursor was
        self._color_cursor[group.id] = idx
        return members[idx].color_set_id

    def _select_scene_group_member(
        self,
        group: MusicEvent,
        advance: int = 1,
        direction: str = "forward",
        pick_mode: str = "default",
    ) -> Optional[MusicEvent]:
        """Advance a scene_group's cursor and return the picked member
        scene_update EVENT (None when no valid member exists). Deliberate
        near-duplicate of _select_color_set_member's cycle/bounce/weighted
        math (kept separate: that method's Palette Sync anchoring makes a
        shared abstraction riskier than the duplication) — semantics of
        advance/direction/bounce/exclude_current match it exactly. Members
        whose event is missing or no longer a scene_update are skipped by
        stepping once more (bounded by n). The cursor is committed only for
        the finally-returned index; cursors persist across track changes."""
        members = group.scene_group_members or []
        if not members:
            return None
        n = len(members)
        mode = group.scene_group_mode if pick_mode == "default" else pick_mode
        cur = self._scene_cursor.get(group.id)
        prev = self._scene_cursor_prev.get(group.id)
        adv = max(0, int(advance))
        back = direction == "backward"
        bounce = group.scene_group_cycle_behavior == "bounce"

        def _bounce_step(i, dd):
            nxt = i + dd
            if nxt >= n:
                dd, nxt = -1, i - 1
            elif nxt < 0:
                dd, nxt = 1, i + 1
            return nxt, dd

        d = self._scene_cursor_dir.get(group.id, 1)
        if mode == "cycle":
            if cur is None:
                idx = 0
                d = -1 if back else 1
            elif adv == 0:
                idx = cur  # stay: re-fire the current member (its Rest lane)
            elif bounce and n > 1:
                if back:
                    d = -d  # "backward" reverses the current bounce travel
                idx = cur
                for _ in range(adv):
                    idx, d = _bounce_step(idx, d)
                # Never settle on the scene already showing; for advance > 1
                # also avoid the one from two fires ago so an even stride
                # can't ping-pong between two endpoints.
                forbidden = {cur}
                if adv > 1 and n > 2 and prev is not None:
                    forbidden.add(prev)
                guard = 0
                while idx in forbidden and guard < n:
                    idx, d = _bounce_step(idx, d)
                    guard += 1
            else:  # wrap (or single-member bounce)
                idx = (cur + (-adv if back else adv)) % n
                if idx == cur and n > 1:
                    idx = (idx + (-1 if back else 1)) % n
        else:  # weighted
            last_idx = cur if group.scene_group_exclude_current else None
            weights = [0.0 if i == last_idx else m.weight for i, m in enumerate(members)]
            if sum(weights) == 0:
                weights = [m.weight for m in members]
            if sum(weights) == 0:
                weights = [1.0] * n
            idx = random.choices(range(n), weights=weights, k=1)[0]

        # Skip deleted / non-scene members by stepping once more, bounded by n.
        member_ev: Optional[MusicEvent] = None
        step_dir = -1 if back else 1
        for _ in range(n):
            ev = get_event(members[idx].event_id)
            if ev is not None and ev.event_type == "scene_update":
                member_ev = ev
                break
            logger.warning(
                "scene_group '%s': member %s missing or not a scene_update — skipping",
                group.name, members[idx].event_id)
            if bounce and mode == "cycle" and n > 1:
                idx, d = _bounce_step(idx, d)
            else:
                idx = (idx + step_dir) % n
        if member_ev is None:
            return None

        self._scene_cursor_prev[group.id] = cur
        self._scene_cursor[group.id] = idx
        self._scene_cursor_dir[group.id] = d
        return member_ev

    def _member_palette_hues(self, members) -> list[Optional[float]]:
        """Representative hue per group member (None when underivable) —
        derived from the member card's swatch color first, then its entries'
        FG values. One store read for the whole member list."""
        from services import color_set_store
        from services.gradient_interpolation import representative_hue
        cards = {c.id: c for c in color_set_store.list_all()}
        hues: list[Optional[float]] = []
        for m in members:
            card = cards.get(m.color_set_id)
            if card is None:
                hues.append(None)
                continue
            candidates = [card.color] + [e.color_value for e in card.entries]
            hues.append(representative_hue(candidates))
        return hues

    def _palette_sync_anchor(
        self, members, member_hues: list[Optional[float]]
    ) -> Optional[int]:
        """Index of the member representing the room's current palette: the
        exact last-applied Color Set when it's a member of this group, else
        the member with the smallest hue distance to the shared palette hue.
        None when neither anchor resolves (fall back to the private cursor)."""
        from services.gradient_interpolation import hue_distance
        last_id = state.last_color_set_id
        if last_id:
            for i, m in enumerate(members):
                if m.color_set_id == last_id:
                    return i
        if self._palette_hue is None:
            return None
        best: Optional[int] = None
        best_d = 1e9
        for i, h in enumerate(member_hues):
            if h is None:
                continue
            d = hue_distance(h, self._palette_hue)
            if d < best_d:
                best, best_d = i, d
        return best

    @staticmethod
    def _color_param_for(etype: str, aspect: str, fallback: str, cfg: dict) -> Optional[str]:
        """Raw param name to write for a Color Set aspect on `etype`. Uses the
        effect's mapped aspect param when SpotFX models it, else falls back to
        LedFX's canonical key (`gradient` / `background_color`) when the live
        effect actually exposes it — so unmodeled effects (e.g. crawler) still
        receive colors. Effects flagged `no_background_color` in the registry
        (radial) never receive bg writes, not even via the fallback."""
        from services import morph_aspects
        from services.effect_params import bg_color_blocked, get_param_meta
        if aspect == "bg_color" and bg_color_blocked(etype):
            return None
        params = morph_aspects.params_for_aspect(etype, aspect)
        if params:
            return params[0]
        if get_param_meta(etype, fallback) is not None or fallback in cfg:
            return fallback
        return None

    def _resolve_color_ref(self, ref_id: str) -> str:
        """Resolve a SetColorAction ref to a real ColorSetCard id. The
        SCENE_GROUP_COLOR_REF sentinel follows the Color Group designated by
        the active scene_group, falling back to the current group when none is
        active (or the active one designates nothing); CURRENT_COLOR_GROUP_REF
        re-uses the last group any set_color fire drew from. Real ids pass
        through untouched; "" = nothing resolves."""
        from models.music_event import SCENE_GROUP_COLOR_REF, CURRENT_COLOR_GROUP_REF
        if ref_id == SCENE_GROUP_COLOR_REF:
            override = _FIRE_COLOR_GROUP.get()
            if override:
                from services import color_set_store
                card = color_set_store.get_by_id(override)
                if card is not None and getattr(card, "kind", "") == "group":
                    return override
                # Deleted / non-group card → ignore, use normal resolution.
                logger.warning("color_group_override %s not a group card — ignored", override)
            gid = self._active_scene_group_id or state.active_scene_group_id
            grp = get_event(gid) if gid else None
            designated = (grp.scene_group_color_ref_id
                          if grp is not None and grp.event_type == "scene_group"
                          else "")
            return designated or state.last_color_group_id
        if ref_id == CURRENT_COLOR_GROUP_REF:
            return state.last_color_group_id
        return ref_id

    async def _execute_set_color(self, action, await_ramps: bool = False) -> None:
        """Apply a Color Set (or a Group's currently-selected Color Set) across
        every scoped device. Writes FG color, BG color, and background mode
        directly per virtual — resolving each param against the device's CURRENT
        effect with a canonical-key fallback — so it works regardless of which
        effect a device is running (modeled or not). Color/BG strings ramp via
        gradient interpolation; background mode is instant.

        A Group's own `entries` act as a field-level override layer on top of
        whichever member Set gets picked — see the merge step below."""
        action = resolve_action_bindings(action, self._signal_now)
        from models.color_set import ColorSetEntry
        from services import color_set_store
        from services import morph_aspects
        from services import morph_effect_state
        from services.morph_compiler import resolve_scope
        from services.effect_params import get_param_meta

        ref_id = self._resolve_color_ref(action.ref_id)
        if not ref_id:
            logger.info("set_color: '%s' resolves to no Color Group yet — no-op",
                        action.ref_id)
            return

        card = color_set_store.get_by_id(ref_id)
        if card is None:
            logger.warning("set_color: unknown Color Set ref %s", ref_id)
            return

        overrides: list = []
        if card.kind == "group":
            state.last_color_group_id = card.id
            overrides = list(card.entries or [])
            chosen_id = self._select_color_set_member(
                card, action.pick_mode, action.advance, action.direction
            )
            if not chosen_id:
                logger.info("set_color: group '%s' has no members", card.name)
                return
            card = color_set_store.get_by_id(chosen_id)
            if card is None or card.kind != "set":
                logger.warning("set_color: group member %s missing or not a set", chosen_id)
                return

        if not card.entries and not overrides:
            return

        state.last_color_set_id = card.id  # mirror for the Now Playing indicator

        # Publish the room's palette hue for Palette Sync groups. Every
        # color-carrying Set application updates it (group pick or direct
        # fire) so the shared hue tracks what's physically showing; sets with
        # no derivable hue (brightness-only, rainbows) leave it untouched.
        from services.gradient_interpolation import representative_hue
        applied_hue = representative_hue(
            [card.color] + [e.color_value for e in card.entries]
        )
        if applied_hue is not None:
            self._palette_hue = applied_hue

        # ── Merge layers into one effective entry per virtual ────────────────
        # Base layer: the Set's entries in order (on overlap, later entries win
        # per field). Override layer: the Group's entries — every field they
        # define replaces the base value for each virtual their scope resolves
        # to. Because merging happens per VIRTUAL, a Group override scoped to a
        # sub-category (or single device) inside a Set entry's scope only
        # affects those nested devices — the Set keeps applying to the rest —
        # while an override scope covering everything the Set touches simply
        # wins everywhere. Group overrides also apply (explicit fields only) to
        # virtuals the chosen Set doesn't cover, so a Group-level clamp behaves
        # the same no matter which member gets picked.
        merge_fields = (
            "color_kind", "color_value", "bg_color", "bg_mode", "brightness",
            "background_brightness", "accent_color", "ramp_ms",
        )
        merged: dict[str, ColorSetEntry] = {}

        def _overlay(entries: list) -> set[str]:
            covered: set[str] = set()
            for entry in entries:
                for vid in resolve_scope(entry.scope):
                    covered.add(vid)
                    tgt = merged.get(vid)
                    if tgt is None:
                        merged[vid] = tgt = ColorSetEntry()
                    for f in merge_fields:
                        v = getattr(entry, f)
                        if v is not None:
                            setattr(tgt, f, v)
            return covered

        base_vids = _overlay(card.entries)
        _overlay(overrides)
        if not merged:
            logger.info("set_color '%s': no virtuals resolved from entry scopes — nothing to do", card.name)
            return

        # Address each device by its LIVE active effect (not a stale cached one)
        # so these color writes update config in place instead of switching the
        # effect back to whatever was last polled.
        await self._refresh_effect_types(list(merged))

        default_ramp_ms = action.ramp_ms if action.ramp_ms is not None else settings.smooth_ramp_ms
        instant_coros: list = []
        ramp_jobs: list = []   # awaited ramps, gathered in parallel after the loop
        touched: set[str] = set()

        ramp_scale = float(getattr(action, "ramp_scale", 1.0) or 1.0)
        for vid, entry in merged.items():
            # Per-entry card ramps bypass action.ramp_ms, so Override Blend's
            # scaled copies carry ramp_scale to stretch them here.
            ramp_ms = (max(0, round(entry.ramp_ms * ramp_scale))
                       if entry.ramp_ms is not None else default_ramp_ms)
            # Remember this set's 3rd color for the vid so a later effect
            # switch can source the new effect's accent from it (None →
            # black). Recorded for every base-covered vid even if its current
            # effect has no accent slot to write right now. Override-only vids
            # (Group scope beyond the Set's coverage) record only an EXPLICIT
            # accent — a Group that doesn't set one leaves the device's accent
            # state alone.
            if vid in base_vids or entry.accent_color is not None:
                self._last_accent_by_vid[vid] = entry.accent_color
            eff = (state.ledfx_virtual_cache.get(vid) or {}).get("effect") or {}
            etype = eff.get("type")
            if not etype:
                logger.debug("set_color '%s': %s has no cached effect type — skipped", card.name, vid)
                continue
            cfg = eff.setdefault("config", {})

            instant: dict = {}
            ramp_str: dict = {}
            ramp_num: dict = {}

            def _unchanged(param: str, value) -> bool:
                # Skip params already at the target value. Critical for
                # non-pixels effects (melt/power/…): they have no color_blend
                # option, so LedFX RECREATES (restarts + transition) the
                # effect whenever a "color"-named key is in the PUT — even if
                # the value didn't change. Dropping an unchanged
                # background_color keeps a gradient-only change in-place.
                cur = cfg.get(param)
                if cur is None:
                    return False
                if isinstance(value, (int, float)) and isinstance(cur, (int, float)):
                    return abs(float(cur) - float(value)) < 1e-4
                return str(cur).strip().lower() == str(value).strip().lower()

            def _place(param: str, value: str):
                if _unchanged(param, value):
                    return
                meta = get_param_meta(etype, param) or {}
                # gradients/colors are smooth by default; only skip the ramp
                # when explicitly marked non-smooth or no ramp requested.
                smooth = meta.get("smooth", True) and ramp_ms > 0
                # Effect-resetting params (flagged `resets_effect`): with
                # preserve_effect (default) skip them entirely to keep the
                # running effect. When the user wants them applied
                # (preserve_effect=False), a server-side tween can ramp them
                # smoothly (its PUT bypasses LedFX's effect-recreation); the
                # legacy path must be instant (ramping would restart it).
                if _param_resets_effect(etype, param):
                    if getattr(action, "preserve_effect", True):
                        return
                    if smooth and ledfx_client.server_tween_enabled():
                        ramp_str[param] = value
                    else:
                        instant[param] = value
                    return
                if smooth:
                    ramp_str[param] = value
                else:
                    instant[param] = value

            def _place_num(param: str, value: float):
                if _unchanged(param, value):
                    return
                meta = get_param_meta(etype, param) or {}
                if meta.get("smooth", True) and ramp_ms > 0:
                    ramp_num[param] = value
                else:
                    instant[param] = value

            def _has(param: str) -> bool:
                return get_param_meta(etype, param) is not None or param in cfg

            if entry.color_value:
                pc = self._color_param_for(etype, "color", "gradient", cfg)
                if pc:
                    _place(pc, entry.color_value)
            if entry.bg_color:
                pb = self._color_param_for(etype, "bg_color", "background_color", cfg)
                if pb:
                    _place(pb, entry.bg_color)
            # 3rd / accent color (sparks_color on power, peak_color on
            # eq2d): write the set's 3rd color, or black when the set
            # leaves it undefined — so an accent-capable effect never keeps
            # a stale accent from a prior set. Effects without an accent
            # param (melt, radial) silently skip; so do override-only vids
            # with no explicit Group accent.
            ap = morph_aspects.accent_param_for(etype)
            if ap and (vid in base_vids or entry.accent_color is not None):
                _place(ap, entry.accent_color or "#000000")
            if entry.brightness is not None and _has("brightness"):
                _place_num("brightness", entry.brightness)
            if entry.background_brightness is not None and _has("background_brightness"):
                _place_num("background_brightness", entry.background_brightness)
            if entry.bg_mode and _has("background_mode") and not _unchanged("background_mode", entry.bg_mode):
                instant["background_mode"] = entry.bg_mode

            if not instant and not ramp_str and not ramp_num:
                logger.debug(
                    "set_color '%s': %s/%s nothing to write (no fields for this vid, or all already at target)",
                    card.name, vid, etype,
                )
                continue
            touched.add(vid)
            logger.info(
                "set_color '%s': %s/%s instant=%s ramp_str=%s ramp_num=%s ramp_ms=%s",
                card.name, vid, etype, instant, ramp_str, ramp_num, ramp_ms,
            )

            if instant:
                instant_coros.append(ledfx_client.set_virtual_effect(vid, etype, instant))
                cfg.update(instant)
            if ramp_str:
                coro = ledfx_client.ramp_gradient_params(vid, etype, ramp_str, ramp_ms)
                if await_ramps:
                    ramp_jobs.append((coro, cfg, ramp_str))
                else:
                    self._spawn_ramp(coro)
            if ramp_num:
                coro = ledfx_client.ramp_effect_params(vid, etype, ramp_num, ramp_ms)
                if await_ramps:
                    ramp_jobs.append((coro, cfg, ramp_num))
                else:
                    self._spawn_ramp(coro)

        if instant_coros:
            await asyncio.gather(*instant_coros, return_exceptions=True)
        await self._await_ramps_parallel(ramp_jobs)

        # Persist post-action state so a later effect switch-back resumes colors.
        if touched:
            updates = []
            for vid in touched:
                eff = (state.ledfx_virtual_cache.get(vid) or {}).get("effect") or {}
                et, c = eff.get("type"), eff.get("config") or {}
                if et and c:
                    updates.append((vid, et, dict(c)))
            if updates:
                morph_effect_state.save_many(updates)

    async def _execute_morph_color(self, action, await_ramps: bool = False) -> None:
        """Morph the colors ALREADY showing on the scoped devices by rotating
        every color param (FG gradient/color, BG color, accent) around the hue
        wheel by `action.degrees` (backward = negative). Beat intensity can
        modulate the rotation via `intensity_scale` (same factor math as morph
        nudges). BG on melt effects is skipped when `preserve_melt_bg` is set;
        power effects always get their BG rotated. Rotated strings ramp via
        gradient interpolation; effect-resetting params follow the same
        instant/server-tween rules as Set Color."""
        action = resolve_action_bindings(action, self._signal_now)
        from services import morph_aspects
        from services import morph_effect_state
        from services.gradient_interpolation import rotate_color_string
        from services.morph_compiler import resolve_scope
        from services.effect_params import get_param_meta

        vids = resolve_scope(action.scope)
        if not vids:
            return
        await self._refresh_effect_types(vids)

        # Effective rotation: direction sets the sign, beat intensity scales the
        # sweep (neutral 0.5 when no beat data — factor 1.0, the raw degrees).
        degrees = float(action.degrees or 0.0)
        if action.intensity_scale:
            intensity = self._beat_intensity_now(action.intensity_source or "rms_total")
            eff_intensity = intensity if intensity is not None else 0.5
            degrees *= 1.0 + (eff_intensity - 0.5) * float(action.intensity_scale)
        if action.direction == "backward":
            degrees = -degrees
        if not degrees:
            return

        ramp_ms = action.ramp_ms if action.ramp_ms is not None else settings.smooth_ramp_ms
        instant_coros: list = []
        ramp_jobs: list = []
        touched: set[str] = set()

        for vid in vids:
            eff = (state.ledfx_virtual_cache.get(vid) or {}).get("effect") or {}
            etype = eff.get("type")
            if not etype:
                continue
            cfg = eff.setdefault("config", {})

            instant: dict = {}
            ramp_str: dict = {}

            def _rotate_param(param: str) -> None:
                cur = cfg.get(param)
                if not isinstance(cur, str) or not cur.strip():
                    return
                rotated = rotate_color_string(cur, degrees)
                if rotated is None or rotated.strip().lower() == cur.strip().lower():
                    return
                meta = get_param_meta(etype, param) or {}
                smooth = meta.get("smooth", True) and ramp_ms > 0
                if _param_resets_effect(etype, param):
                    # Same rule as Set Color with preserve_effect off: a server-
                    # side tween can ramp reset params smoothly; the legacy
                    # client loop must write them instantly.
                    if smooth and ledfx_client.server_tween_enabled():
                        ramp_str[param] = rotated
                    else:
                        instant[param] = rotated
                elif smooth:
                    ramp_str[param] = rotated
                else:
                    instant[param] = rotated

            pc = self._color_param_for(etype, "color", "gradient", cfg)
            if pc:
                _rotate_param(pc)

            # BG: melt keeps its background when preserve_melt_bg is set;
            # power is exempt from that guard and always rotates.
            if not (action.preserve_melt_bg and etype == "melt"):
                pb = self._color_param_for(etype, "bg_color", "background_color", cfg)
                if pb:
                    _rotate_param(pb)

            ap = morph_aspects.accent_param_for(etype)
            if ap:
                _rotate_param(ap)
                # Keep the per-vid accent memory in sync so a later effect
                # switch carries the rotated accent, not the pre-rotation one.
                new_accent = ramp_str.get(ap) or instant.get(ap)
                if new_accent and vid in self._last_accent_by_vid:
                    self._last_accent_by_vid[vid] = new_accent

            if not instant and not ramp_str:
                continue
            touched.add(vid)

            if instant:
                instant_coros.append(ledfx_client.set_virtual_effect(vid, etype, instant))
                cfg.update(instant)
            if ramp_str:
                coro = ledfx_client.ramp_gradient_params(vid, etype, ramp_str, ramp_ms)
                if await_ramps:
                    ramp_jobs.append((coro, cfg, ramp_str))
                else:
                    self._spawn_ramp(coro)
                    # Optimistically mirror the ramp target so back-to-back
                    # rotations compound instead of re-reading the pre-ramp value.
                    cfg.update(ramp_str)

        if instant_coros:
            await asyncio.gather(*instant_coros, return_exceptions=True)
        await self._await_ramps_parallel(ramp_jobs)

        # Persist post-action state so a later effect switch-back resumes colors.
        if touched:
            updates = []
            for vid in touched:
                eff = (state.ledfx_virtual_cache.get(vid) or {}).get("effect") or {}
                et, c = eff.get("type"), eff.get("config") or {}
                if et and c:
                    updates.append((vid, et, dict(c)))
            if updates:
                morph_effect_state.save_many(updates)

    async def fire_color_set_now(self, card_id: str) -> bool:
        """Preview-fire a Color Set or Group immediately, bypassing the audio-
        capture gate (mirrors fire_event_now's force_allow wrapper)."""
        from models.music_event import SetColorAction
        from services import color_set_store
        card = color_set_store.get_by_id(card_id)
        if card is None:
            logger.warning("fire_color_set_now: unknown card %s", card_id)
            return False
        with ledfx_client.force_allow():
            # Preview shows the full set, so it must NOT honor preserve_effect —
            # otherwise effect-resetting params (e.g. background_color) get
            # silently dropped and the background never fires.
            await self._execute_set_color(
                SetColorAction(ref_id=card_id, pick_mode="default", preserve_effect=False),
                await_ramps=True,
            )
            await ledfx_client.drain_bus()
        return True

    def _pick_morph_lanes(
        self,
        event: MusicEvent,
        labels: list[str],
    ) -> list[MorphPick]:
        """Synchronously pick one Action per lane (weighted random + label
        filter). Returns [MorphPick(lane_name, action, offset_ms), ...].
        Separated from the fire step so callers can build a Now Playing summary
        string without waiting on the actual LedFX writes."""
        out: list[MorphPick] = []
        for li, lane in enumerate(event.morph_lanes):
            merged_labels = list(labels or []) + list(lane.labels or [])
            dedupe_key = f"{event.id}:lane:{li}"
            picked = self._pick_from_actions(
                lane.alternatives, merged_labels,
                dedupe_key=dedupe_key, desc=f"lane '{lane.name or li}' of '{event.name}'",
            )
            if picked is not None:
                out.append(MorphPick(lane.name or f"lane-{li}", picked, int(lane.offset_ms or 0)))
        return out

    async def _fire_morph_picks(
        self,
        picks: list[MorphPick],
        labels: list[str],
        skip_event_ids: Optional[set] = None,
        anchor_offset_ms: Optional[int] = None,
    ) -> None:
        """Fire the picks from `_pick_morph_lanes`, staggering each lane by its
        per-lane offset. Every lane sleeps `offset_ms - anchor` (always >= 0)
        before its dispatch; `anchor` is the earliest lane offset. When the
        planner shifted the entry's fire_at_ms by the same anchor, the earliest
        lane fires on time and the rest sleep forward. All-equal offsets (the
        common all-zero case) yield zero sleeps — identical to firing them
        concurrently. The planner passes its stored anchor so plan-time and
        fire-time agree; ad-hoc callers let it default to the picks' minimum."""
        if not picks:
            return
        anchor = anchor_offset_ms if anchor_offset_ms is not None else min(p.offset_ms for p in picks)

        async def _one(p: MorphPick) -> None:
            rel = p.offset_ms - anchor  # >= 0
            if rel > 0:
                await asyncio.sleep(rel / 1000)
                # A long stagger can outlast a pause/seek — don't fire into stale state.
                if state.paused:
                    return
            await self._execute_action(p.action, labels or [], skip_event_ids=skip_event_ids)

        await asyncio.gather(*(_one(p) for p in picks), return_exceptions=True)

    def _morph_picks_summary(self, picks: list[tuple[str, Action]]) -> str:
        """Build the short Now Playing string for a morph_set fire, e.g.
        'Strips: Morph 1× (brightness) · Matrix: Color: hot'.
        Reuses _describe_action so the format matches the rest of the UI."""
        parts: list[str] = []
        for pick in picks:
            desc = self._describe_action(pick.action)
            if pick.offset_ms:
                desc = f"{desc} ({pick.offset_ms:+d}ms)"
            parts.append(f"{pick.lane_name}: {desc}" if pick.lane_name else desc)
        return " · ".join(parts)

    async def _execute_morph_set(
        self,
        event: MusicEvent,
        labels: list[str],
        skip_event_ids: Optional[set] = None,
    ) -> None:
        """Fire a `morph_set` MusicEvent: for each lane, pick one Action from
        its alternatives (weighted random + label-filtered) and fire all picks
        concurrently. Brightness lives on Morph Step targets and global scene
        transitions are gone."""
        if not event.morph_lanes:
            return
        picks = self._pick_morph_lanes(event, labels)
        await self._fire_morph_picks(picks, labels, skip_event_ids=skip_event_ids)

    # ── Scene events (scene_update / update_scene / reset_scene) ───────────────
    def _pick_lane_action(
        self, event: MusicEvent, lane_index: int, labels: list[str],
    ) -> Optional[Action]:
        """Pick one alternative from `event.morph_lanes[lane_index]` (weighted,
        with the same dedupe key the fire path uses) WITHOUT executing it."""
        lanes = event.morph_lanes or []
        if lane_index < 0 or lane_index >= len(lanes):
            return None
        lane = lanes[lane_index]
        merged = list(labels or []) + list(lane.labels or [])
        return self._pick_from_actions(
            lane.alternatives, merged,
            dedupe_key=f"{event.id}:lane:{lane_index}",
            desc=f"lane '{lane.name or lane_index}' of '{event.name}'",
        )

    def _forced_scene_event(self) -> Optional[MusicEvent]:
        """The Scene Update — or Scene Group — that Force Scene redirects every
        scene pick to, or None when the setting is off / points at a missing or
        non-scene event. A forced group rotates one member per redirected pick."""
        if not settings.force_scene_enabled:
            return None
        eid = settings.force_scene_event_id
        ev = get_event(eid) if eid else None
        if ev is None or ev.event_type not in ("scene_update", "scene_group"):
            return None
        return ev

    def _scene_lane_indices(self, event: MusicEvent) -> list[int]:
        """Lane indices a scene-family event runs against the last Scene
        Update (with Shape Flare's empty-lane fallback to Color)."""
        indices = list(_FLARE_LANES.get(event.event_type) or [])
        if event.event_type == "shape_flare" and self._scene_lane_is_empty(2):
            indices = [3]  # Color
        return indices

    def _pick_scene_lanes(
        self, event: MusicEvent, labels: list[str],
    ) -> list[tuple[int, Action]]:
        """Resolve which lanes a scene-family event would run RIGHT NOW and
        pick one alternative per lane. Used at plan time so the Now Playing
        preview can describe the exact changes; the picks are locked into the
        plan entry and fired as-is (unless the active Scene Update changes).
        Returns [(lane_index, action), ...] — empty when no scene is active.
        Scene Groups (fired directly or forced) never get plan-time picks: the
        cursor advance stays fire-time-only so previews can't move it, and the
        member (hence lane) is unknown until then."""
        if event.event_type == "scene_group":
            return []
        if event.event_type == "scene_update":
            forced = self._forced_scene_event()
            if forced is not None:
                if forced.event_type == "scene_group":
                    return []  # member resolves at fire time
                event = forced  # Force Scene: reassert with normal First/Rest
            lane_index = 1 if self._last_scene_update_id == event.id else 0
            picked = self._pick_lane_action(event, lane_index, labels)
            return [(lane_index, picked)] if picked is not None else []
        last = get_event(self._last_scene_update_id) if self._last_scene_update_id else None
        if last is None or last.event_type != "scene_update":
            return []
        out: list[tuple[int, Action]] = []
        for i in self._scene_lane_indices(event):
            picked = self._pick_lane_action(last, i, labels)
            if picked is not None:
                out.append((i, picked))
        return out

    async def _run_one_lane(
        self,
        event: MusicEvent,
        lane_index: int,
        labels: list[str],
        skip_event_ids: Optional[set] = None,
        preselected: Optional[Action] = None,
        resolved_picks: Optional[dict] = None,
    ) -> Optional[Action]:
        """Fire one alternative from `event.morph_lanes[lane_index]` — the
        plan-time `preselected` pick when given, else a fresh weighted pick.
        `resolved_picks` pins random branches inside the pick's subtree.
        Returns the Action (for the Now-Playing summary) or None."""
        picked = preselected or self._pick_lane_action(event, lane_index, labels)
        if picked is not None:
            await self._execute_action(picked, labels or [],
                                       skip_event_ids=skip_event_ids,
                                       resolved_picks=resolved_picks)
        return picked

    async def _execute_scene_update(
        self, event: MusicEvent, labels: list[str], skip_event_ids: Optional[set] = None,
        preselected: Optional[dict] = None,
        resolved_picks: Optional[dict] = None,
    ) -> str:
        """Run First (lane 0) when this isn't the last Scene Update fired, else
        Rest (lane 1). Becomes the new 'last scene update' BEFORE the lane runs:
        a Rest-lane scene_morph fires another member (which then sets itself as
        last) — stamping afterwards would clobber that back to this event and
        lock the group into a repeat→morph→clobber loop that visually pins one
        member forever."""
        repeat = self._last_scene_update_id == event.id
        lane_index = 1 if repeat else 0
        self._last_scene_update_id = event.id
        state.last_scene_update_id = event.id  # mirror for the Now Playing indicator
        picked = await self._run_one_lane(
            event, lane_index, labels, skip_event_ids,
            preselected=(preselected or {}).get(lane_index),
            resolved_picks=resolved_picks,
        )
        tag = "Rest" if repeat else "First"
        return f"{tag}: {self._describe_action(picked)}" if picked else tag

    async def _execute_scene_group(
        self, event: MusicEvent, labels: list[str], skip_event_ids: Optional[set] = None,
    ) -> str:
        """Advance the group's cursor one step and fire the picked member
        Scene Update (normal First/Rest — a newly rotated-to member runs
        First, a repeat runs Rest). Marks the group as the active one that
        Scene Morph steps. `_last_scene_update_id` ends up pointing at the
        MEMBER, so flares / Update / Reset Scene keep working unchanged."""
        self._active_scene_group_id = event.id
        state.active_scene_group_id = event.id
        member = self._select_scene_group_member(event, advance=1, direction="forward")
        if member is None:
            logger.info("scene_group '%s': no valid members — no-op", event.name)
            return "(empty scene group)"
        tag = await self._execute_scene_update(member, labels, skip_event_ids)
        return f"{event.name} → {member.name} · {tag}"

    async def _execute_scene_morph(
        self, action, labels: list[str], skip_event_ids: Optional[set] = None,
    ) -> None:
        """Scene Morph leaf: step the ACTIVE scene group ±advance members and
        fire the result (normal First/Rest; advance=0 re-fires the current
        member → Rest). The active group is the forced one when Force Scene
        holds a group, else the last group that fired. No-ops (with a log)
        when none is active or Force Scene pins a single scene. Stepping is
        forced ordinal ("cycle") even on weighted groups — ±N is inherently
        an ordered walk; bounce groups honor their bounce travel."""
        forced = self._forced_scene_event()
        if forced is not None and forced.event_type == "scene_update":
            logger.info("scene_morph: Force Scene holds a single scene — no-op")
            return
        gid = forced.id if forced is not None else self._active_scene_group_id
        group = get_event(gid) if gid else None
        if group is None or group.event_type != "scene_group":
            logger.info("scene_morph: no active scene group — no-op")
            return
        self._active_scene_group_id = group.id
        state.active_scene_group_id = group.id
        member = self._select_scene_group_member(
            group, advance=action.advance, direction=action.direction,
            pick_mode="cycle")
        if member is None:
            logger.info("scene_morph: group '%s' has no valid members — no-op",
                        group.name)
            return
        # The one scene fire that bypasses _execute_scene_event — count it
        # for sequence "updates" waiters too.
        await self._notify_scene_fire()
        await self._execute_scene_update(member, labels, skip_event_ids)

    async def _run_last_scene_lanes(
        self, indices: list[int], labels: list[str], skip_event_ids: Optional[set] = None,
        preselected: Optional[dict] = None,
        resolved_picks: Optional[dict] = None,
    ) -> str:
        """Run one or more lanes of the last fired Scene Update — concurrently
        when more than one (e.g. Combo Flare = Shape + Color). No-op when no
        Scene Update has fired yet."""
        last = get_event(self._last_scene_update_id) if self._last_scene_update_id else None
        if last is None or last.event_type != "scene_update":
            logger.info("scene: no active Scene Update to run lanes %s", indices)
            return "(no active scene)"
        picks = await asyncio.gather(
            *(self._run_one_lane(last, i, labels, skip_event_ids,
                                 preselected=(preselected or {}).get(i),
                                 resolved_picks=resolved_picks)
              for i in indices)
        )
        parts: list[str] = []
        for i, p in zip(indices, picks):
            nm = SCENE_LANE_NAMES[i] if 0 <= i < len(SCENE_LANE_NAMES) else str(i)
            if p is not None:
                parts.append(f"{nm}: {self._describe_action(p)}")
        return f"{last.name} → {' · '.join(parts)}" if parts else f"→ {last.name}"

    def _scene_lane_is_empty(self, lane_index: int) -> bool:
        """True when the last fired Scene Update has no alternatives in
        `lane_index` (or there is no active Scene Update / lane)."""
        last = get_event(self._last_scene_update_id) if self._last_scene_update_id else None
        if last is None or last.event_type != "scene_update":
            return True
        lanes = last.morph_lanes or []
        if lane_index < 0 or lane_index >= len(lanes):
            return True
        return not lanes[lane_index].alternatives

    async def _execute_scene_event(
        self, event: MusicEvent, labels: list[str], skip_event_ids: Optional[set] = None,
        preselected: Optional[dict] = None,
        resolved_picks: Optional[dict] = None,
        picks_event_id: Optional[str] = None,
    ) -> str:
        """Dispatch any scene event type. Returns a short summary string for the
        Now-Playing broadcast. `preselected` (lane_index → Action) carries the
        plan-time picks and `resolved_picks` their deep-resolved random
        branches, so the fire matches the Now Playing preview; lanes missing
        from them fall back to fresh picks. `picks_event_id` records which event
        the picks were rolled against — a mismatch with the event that actually
        runs (e.g. Force Scene toggled between plan and fire) drops them.

        Every call bumps the scene-fire counter feeding sequence "updates"
        waits — including flares that end up no-ops (predictable and simple)."""
        await self._notify_scene_fire()
        if event.event_type == "scene_group":
            forced = self._forced_scene_event()
            if forced is not None and forced.id != event.id:
                # Force Scene wins: redirect like any other scene pick.
                if forced.event_type == "scene_group":
                    return await self._execute_scene_group(forced, labels, skip_event_ids)
                self._active_scene_group_id = None
                state.active_scene_group_id = ""
                return await self._execute_scene_update(forced, labels, skip_event_ids)
            return await self._execute_scene_group(event, labels, skip_event_ids)
        if event.event_type == "scene_update":
            forced = self._forced_scene_event()
            if forced is not None and forced.event_type == "scene_group":
                # Forced group: every redirected scene pick rotates it by one.
                # Plan-time picks were rolled against a scene_update — always
                # stale for a group fire, so drop them.
                return await self._execute_scene_group(forced, labels, skip_event_ids)
            target = forced if forced is not None else event
            if picks_event_id is not None and picks_event_id != target.id:
                preselected, resolved_picks = None, None
            # A directly-picked (or forced single) scene means no group drives
            # the room anymore — Scene Morph becomes a no-op until a group fires.
            self._active_scene_group_id = None
            state.active_scene_group_id = ""
            return await self._execute_scene_update(
                target, labels, skip_event_ids, preselected, resolved_picks)
        if event.event_type not in _FLARE_LANES:
            return ""
        # Shape Flare falls back to the Color lane when the Shape lane (2) is
        # empty, so an event with only color alternatives still flares.
        indices = self._scene_lane_indices(event)
        return await self._run_last_scene_lanes(
            indices, labels, skip_event_ids, preselected, resolved_picks)

    async def _notify_scene_fire(self) -> None:
        """Bump the scene-family fire counter and wake sequence "updates"
        waiters. Called from _execute_scene_event (the single choke point for
        all scene-family fires) and _execute_scene_morph (the one path that
        reaches _execute_scene_update without passing through it)."""
        async with self._scene_fire_cond:
            self._scene_fire_seq += 1
            self._scene_fire_cond.notify_all()

    async def _wake_scene_waiters(self) -> None:
        """Wake "updates" waiters WITHOUT counting a fire — used on track
        change so updates-only waits (delay_ms=0) re-check their track-change
        predicate and release instead of leaking into the next song."""
        async with self._scene_fire_cond:
            self._scene_fire_cond.notify_all()

    async def _sleep_child_delay(self, delay_ms: int, delay_updates: Optional[int]) -> None:
        """ms-mode sequence-child gate. Without `delay_updates`: the classic
        sleep. With it: fire after `delay_updates` scene-family fires OR after
        `delay_ms`, whichever comes first (delay_ms == 0 waits on updates
        alone, released by a track change). The wait target is an absolute
        counter value computed before any await, so a fire landing between
        target computation and wait registration still satisfies it."""
        upd = int(delay_updates or 0)
        if upd <= 0:
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
            return
        target = self._scene_fire_seq + upd
        uri0 = self._last_uri

        async def _wait():
            async with self._scene_fire_cond:
                await self._scene_fire_cond.wait_for(
                    lambda: self._scene_fire_seq >= target or self._last_uri != uri0)

        try:
            await asyncio.wait_for(
                _wait(), (delay_ms / 1000) if delay_ms > 0 else None)
        except asyncio.TimeoutError:
            pass  # time delay wins — the child still fires, in the current scene

    def _plan_ramp_ms(self, action) -> int:
        """Effective ramp for beat-timeline math — resolves a bound ramp_ms
        so max() never sees a ValueBinding object."""
        r = static_ramp_ms(getattr(action, "ramp_ms", None), self._signal_now)
        return r if r is not None else settings.smooth_ramp_ms

    def _signal_now(self, binding) -> Optional[float]:
        """Current value of a ValueBinding's signal at the live song position.
        Same track/progress guards as _beat_intensity_now; sections and beats
        come from the runtime caches (lazy-loaded per URI as a fallback)."""
        if binding.signal == "trigger_intensity":
            # Needs no track/beat context — just the per-fire value.
            return resolve_signal(binding, None, None, 0,
                                  trigger_intensity=_FIRE_INTENSITY.get())
        if not state.current_track or not state.current_track.spotify_uri:
            return None
        uri = state.current_track.spotify_uri
        beats = self._beats_cache or load_beats_for_uri(uri)
        sections = self._sections_cache
        if sections is None and binding.signal == "section_energy":
            from services.audio_analyzer import load_sections_for_uri
            sections = self._sections_cache = load_sections_for_uri(uri)
        now_ms = state.current_track.interpolated_progress_ms()
        return resolve_signal(binding, beats, sections, int(now_ms),
                              trigger_intensity=_FIRE_INTENSITY.get())

    def _beat_intensity_now(self, source: str) -> Optional[float]:
        """Resolve the current beat-level intensity for a nudge target.

        Looks up the nearest beat to `state.current_track.interpolated_progress_ms()`
        in the engine's cached `_beats_cache` (or `load_beats_for_uri(uri)` fallback)
        and returns the requested `source` field clamped to [0, 1]. Returns None
        when no track is playing or no beat data is available — the compiler
        falls back to a neutral 0.5 in that case.
        """
        if not state.current_track or not state.current_track.spotify_uri:
            return None
        beats = self._beats_cache or load_beats_for_uri(state.current_track.spotify_uri)
        if not beats:
            return None
        try:
            now_ms = state.current_track.interpolated_progress_ms()
        except Exception:
            return None
        # Beats are ms-sorted; nearest is fine for sub-second granularity needs.
        nearest = min(beats, key=lambda b: abs(int(b.get("ms", 0)) - now_ms))
        val = nearest.get(source)
        if val is None:
            return None
        try:
            return max(0.0, min(1.0, float(val)))
        except (TypeError, ValueError):
            return None

    async def _ensure_virtuals_cached(self, targets: list) -> None:
        """For every virtual reachable from any target's scope, ensure the cache
        has an `effect.type`. Tops up missing entries via a single `get_virtual()` each."""
        from services.morph_compiler import resolve_scope
        needed: set[str] = set()
        for t in targets:
            for vid in resolve_scope(t.scope):
                entry = state.ledfx_virtual_cache.get(vid)
                if not isinstance(entry, dict) or not (entry.get("effect") or {}).get("type"):
                    needed.add(vid)
        for vid in needed:
            live = await ledfx_client.get_virtual(vid)
            if live:
                # ledfx_client.get_virtual returns {vid: {...}} per existing code
                payload = live.get(vid, live)
                state.ledfx_virtual_cache[vid] = payload

    async def _refresh_effect_types(self, vids: list[str]) -> None:
        """Re-fetch the CURRENT effect type + config for each virtual so morph
        writes address the device's *live* active effect, not a possibly stale
        cached one.

        Morph color/param writes are effect-agnostic, but LedFX's effects PUT
        switches the effect whenever the sent `type` differs from the active
        one. If the 5s state poll is behind (or muted during capture), the
        cached type can be wrong and the write flips the device back to it
        (e.g. a user's manual `melt` → last-polled `crawler`). Refreshing here
        keeps writes in-place. Best-effort + time-bounded so a slow/unreachable
        LedFX falls back to the cache instead of stalling the fire."""
        seen: set[str] = set()
        ordered: list[str] = []
        for v in vids:
            if v and v not in seen:
                seen.add(v)
                ordered.append(v)
        if not ordered:
            return

        async def _one(vid: str) -> None:
            live = await ledfx_client.get_virtual(vid)
            if live:
                payload = live.get(vid, live)
                if isinstance(payload, dict) and (payload.get("effect") or {}).get("type"):
                    state.ledfx_virtual_cache[vid] = payload

        try:
            # Tight cap: a healthy localhost read is ~1-5 ms, so 25 ms leaves
            # ample headroom yet stays imperceptible if LedFX is slow/down — we
            # just fall back to the cached effect type rather than stall the fire.
            await asyncio.wait_for(
                asyncio.gather(*(_one(v) for v in ordered), return_exceptions=True),
                timeout=0.025,
            )
        except asyncio.TimeoutError:
            logger.debug("morph: effect-type refresh exceeded 25ms; using cached types")

    async def _snapshot_for_revert(self, event: MusicEvent | None = None,
                                   actions: list | None = None) -> dict:
        """
        Snapshot only the specific LedFX param values this sequence will change.
        Pass `actions` (a flat leaf-action list, e.g. from _iter_leaf_actions)
        to snapshot for a composite group; otherwise the event's steps are used.

        Snapshot format:
          {
            "virtual_effects":  {vid: {"type": str, "params": {pname: value}}},
            "virtual_configs":  {vid: {key: value}},
          }
        """
        from services.effect_params import resolve_params, get_param_meta, get_virtuals_for_category
        from services.morph_compiler import resolve_scope
        from services.morph_aspects import params_for_aspect

        snapshot: dict = {}

        # Collect virtuals that need warming (cache miss → missing effect type)
        # then fetch them all concurrently before snapshotting. This prevents
        # silent revert loss when the 5s poll hasn't populated a virtual yet
        # (the root cause of "Ambient Flip" staying on its flipped color).
        async def _warm(vids: list[str]) -> None:
            missing = [
                v for v in vids
                if not state.ledfx_virtual_cache.get(v, {}).get("effect", {}).get("type")
            ]
            if not missing:
                return
            results = await asyncio.gather(
                *(ledfx_client.get_virtual(v) for v in missing),
                return_exceptions=True,
            )
            for vid, fresh in zip(missing, results):
                if isinstance(fresh, dict) and fresh:
                    state.ledfx_virtual_cache[vid] = fresh.get(vid, fresh)

        def _snap_effect(vid: str, param_names: list[str]) -> None:
            cached = state.ledfx_virtual_cache.get(vid, {})
            etype = cached.get("effect", {}).get("type")
            econfig = cached.get("effect", {}).get("config", {})
            if not etype:
                logger.debug("snapshot: virtual %s has no cached effect; revert for this vid will be a no-op", vid)
                return
            ve = snapshot.setdefault("virtual_effects", {})
            vsnap = ve.setdefault(vid, {"type": etype, "params": {}})
            for p in param_names:
                if p in econfig and p not in vsnap["params"]:
                    vsnap["params"][p] = econfig[p]

        def _snap_vconfig(vid: str, keys: list[str]) -> None:
            vcfg = state.ledfx_virtual_cache.get(vid, {}).get("config", {})
            vc = snapshot.setdefault("virtual_configs", {})
            entry = vc.setdefault(vid, {})
            for k in keys:
                if k in vcfg and k not in entry:
                    entry[k] = vcfg[k]

        leaf_actions = actions if actions is not None else (
            self._event_leaf_actions(event) if event is not None else []
        )

        # Gather every vid this event will touch so we can warm them concurrently.
        target_vids: set[str] = set()
        for _a in leaf_actions:
                if _a.type in ("ledfx_ambient", "ledfx_ambient_color"):
                    target_vids.update(get_virtuals_for_role("ambient"))
                elif _a.type == "ledfx_global_transition":
                    target_vids.update(get_all_virtual_ids())
                elif _a.type == "ledfx_effect_param":
                    from services.effect_params import get_virtuals_for_category as _gfc
                    if _a.virtual_id:
                        target_vids.add(_a.virtual_id)
                    elif _a.category:
                        target_vids.update(_gfc(_a.category))
                    else:
                        target_vids.update(get_all_virtual_ids())
                elif _a.type == "morph_step":
                    for _t in _a.targets:
                        if _t.aspect != "effect":
                            target_vids.update(resolve_scope(_t.scope))
                elif _a.type == "morph_color":
                    target_vids.update(resolve_scope(_a.scope))
        if target_vids:
            await _warm(list(target_vids))

        for action in leaf_actions:
                if action.type == "morph_step":
                    # Snapshot the aspect-mapped params on every scoped virtual so
                    # a revert-enabled group restores what the morph changed.
                    # Effect switches are excluded — they resume via morph state,
                    # not param revert.
                    for t in action.targets:
                        if t.aspect == "effect":
                            continue
                        for vid in resolve_scope(t.scope):
                            cached = state.ledfx_virtual_cache.get(vid, {})
                            etype = cached.get("effect", {}).get("type")
                            if etype:
                                _snap_effect(vid, params_for_aspect(etype, t.aspect))

                elif action.type == "ledfx_ambient":
                    for vid in get_virtuals_for_role("ambient"):
                        if action.color is not None:
                            _snap_effect(vid, ["gradient", "background_color", "sparks_color"])
                        for field, pname in [
                            ("brightness",            "brightness"),
                            ("blur",                  "blur"),
                            ("bass_decay_rate",        "bass_decay_rate"),
                            ("background_brightness",  "background_brightness"),
                        ]:
                            if getattr(action, field) is not None:
                                _snap_effect(vid, [pname])
                        if action.max_brightness is not None:
                            _snap_vconfig(vid, ["max_brightness"])

                elif action.type == "ledfx_ambient_color":
                    for vid in get_virtuals_for_role("ambient"):
                        _snap_effect(vid, ["gradient", "background_color", "sparks_color"])

                elif action.type == "morph_color":
                    # Snapshot the color params the rotation will touch on each
                    # scoped virtual (FG / BG / accent for its current effect).
                    from services.morph_aspects import accent_param_for
                    for vid in resolve_scope(action.scope):
                        cached = state.ledfx_virtual_cache.get(vid, {})
                        etype = cached.get("effect", {}).get("type")
                        if not etype:
                            continue
                        cfg = cached.get("effect", {}).get("config", {})
                        pnames = [
                            self._color_param_for(etype, "color", "gradient", cfg),
                            self._color_param_for(etype, "bg_color", "background_color", cfg),
                            accent_param_for(etype),
                        ]
                        _snap_effect(vid, [p for p in pnames if p])

                elif action.type == "ledfx_global_transition":
                    for vid in get_all_virtual_ids():
                        _snap_vconfig(vid, ["transition_time", "transition_mode"])

                elif action.type == "ledfx_effect_param":
                    if action.virtual_id:
                        virtuals = [action.virtual_id]
                    elif action.category:
                        virtuals = get_virtuals_for_category(action.category)
                    else:
                        virtuals = get_all_virtual_ids()
                    for vid in virtuals:
                        cached = state.ledfx_virtual_cache.get(vid, {})
                        effect_type = cached.get("effect", {}).get("type")
                        if not effect_type:
                            continue
                        pnames: list[str] = []
                        for change in action.params:
                            for pname in resolve_params(effect_type, change.param_label):
                                meta = get_param_meta(effect_type, pname)
                                actual = meta["maps_to"] if (meta and meta.get("sign_control")) else pname
                                pnames.append(actual)
                        if pnames:
                            _snap_effect(vid, pnames)

        return snapshot

    async def _restore_from_snapshot(self, snapshot: dict, revert_cfg) -> None:
        """Restore previously snapshotted LedFX state (targeted params only)."""
        from api import ledfx_client as _lc

        t_ms = revert_cfg.transition_ms

        for vid, vsnap in snapshot.get("virtual_effects", {}).items():
            etype = vsnap["type"]
            params = vsnap["params"]
            if not params:
                continue
            numeric     = {k: v for k, v in params.items() if isinstance(v, (int, float))}
            non_numeric = {k: v for k, v in params.items() if not isinstance(v, (int, float))}
            if non_numeric:
                logger.info("Revert restore: vid=%s etype=%s params=%s", vid, etype, non_numeric)
                await _lc.set_virtual_effect(vid, etype, non_numeric)
                # Update the local cache to reflect the restored values.
                # Without this, the next action that reads cached params
                # (e.g. ledfx_ambient_color computing the complement from
                # the *current* color) would see the pre-revert state and
                # effectively re-flip, making the revert appear to fail.
                cached_cfg = state.ledfx_virtual_cache.get(vid, {}).get("effect", {}).get("config")
                if cached_cfg is not None:
                    cached_cfg.update(non_numeric)
            if numeric and t_ms > 0:
                # Refresh cache so ramp_effect_params starts from the post-sequence values
                fresh = await _lc.get_virtual(vid)
                if fresh:
                    state.ledfx_virtual_cache[vid] = fresh.get(vid, fresh)
                self._spawn_ramp(_lc.ramp_effect_params(vid, etype, numeric, t_ms))
            elif numeric:
                await _lc.set_virtual_effect(vid, etype, numeric)

        for vid, vcfg in snapshot.get("virtual_configs", {}).items():
            if vcfg:
                await _lc.set_virtual_config(vid, vcfg)

        logger.info("Revert applied")

    def _event_touches_ambient(self, event: MusicEvent | None = None,
                               actions: list | None = None) -> list[str]:
        """Return the list of ambient virtual ids this event will modify, or []
        if it doesn't touch the ambient role. Used by the steal-snapshot path.
        Pass `actions` (flat leaf list) for composite groups."""
        leaf = actions if actions is not None else (
            self._event_leaf_actions(event) if event is not None else []
        )
        for a in leaf:
            if a.type in ("ledfx_ambient", "ledfx_ambient_color"):
                return list(get_virtuals_for_role("ambient"))
            if a.type == "morph_color":
                # Scoped rotation (e.g. category "Singles"): counts as an
                # ambient flip for the steal-snapshot path when its scope
                # overlaps the ambient role.
                from services.morph_compiler import resolve_scope as _rs
                hit = set(get_virtuals_for_role("ambient")) & set(_rs(a.scope))
                if hit:
                    return sorted(hit)
        return []

    def _steal_pending_ambient_snapshot(self, vids: list[str]) -> Optional[dict]:
        """If any of `vids` has a pending revert from an earlier flip, pop it,
        cancel its task, and merge its snapshot into a single dict. This
        preserves the TRUE pre-first-flip state across overlapping flips."""
        stolen: dict = {}
        for vid in vids:
            entry = self._pending_ambient_revert.pop(vid, None)
            if entry is None:
                continue
            prev_snap, _prev_cfg, prev_task = entry
            if not prev_task.done():
                prev_task.cancel()
            logger.info("Ambient steal: vid=%s stole pending snapshot", vid)
            # Merge the prior snapshot's virtual_effects / configs into ours.
            for key in ("virtual_effects", "virtual_configs"):
                if key not in prev_snap:
                    continue
                merged = stolen.setdefault(key, {})
                for k, v in prev_snap[key].items():
                    if k not in merged:
                        merged[k] = v
        return stolen or None

    async def _schedule_ambient_revert(
        self, name: str, snapshot: dict, revert_cfg, vids: list[str],
    ) -> None:
        """Fire revert as a cancellable task registered under each target vid.
        An overlapping flip can cancel this task mid-sleep via the steal path."""
        async def _revert_runner():
            try:
                logger.info(
                    "Revert firing for '%s' (delay=%dms, transition=%dms)",
                    name, revert_cfg.delay_ms, revert_cfg.transition_ms,
                )
                if revert_cfg.delay_ms > 0:
                    await asyncio.sleep(revert_cfg.delay_ms / 1000)
                await self._restore_from_snapshot(snapshot, revert_cfg)
            except asyncio.CancelledError:
                logger.info("Revert cancelled for '%s' — snapshot stolen by overlapping flip", name)
                raise
            finally:
                # Clear the pending entry only if it's still pointing at us.
                for vid in vids:
                    current = self._pending_ambient_revert.get(vid)
                    if current and current[2] is task:
                        self._pending_ambient_revert.pop(vid, None)

        task = asyncio.create_task(_revert_runner())
        for vid in vids:
            self._pending_ambient_revert[vid] = (snapshot, revert_cfg, task)

    async def _execute_sequence(
        self, event: MusicEvent, labels: list[str], pre_steps: list | None = None,
        skip_event_ids: set[str] | None = None,
        precomputed_snapshot: Optional[dict] = None,
    ) -> None:
        """Execute a sequence of steps, then optionally revert LedFX state."""
        revert = event.revert
        ambient_vids = self._event_touches_ambient(event) if revert and revert.enabled else []
        snapshot: dict = {}
        if revert and revert.enabled:
            # Overlap handling: if another Ambient Flip is mid-cycle on the same
            # virtual, steal ITS snapshot and cancel its revert. Our revert will
            # restore the truly-clean pre-first-flip state.
            stolen = self._steal_pending_ambient_snapshot(ambient_vids) if ambient_vids else None
            if stolen is not None:
                snapshot = stolen
            elif precomputed_snapshot is not None:
                snapshot = precomputed_snapshot
            else:
                snapshot = await self._snapshot_for_revert(event)
            if not snapshot:
                logger.warning(
                    "Revert skipped for '%s': snapshot is empty (target virtual cache may be missing effect info)",
                    event.name,
                )

        body_error: Optional[BaseException] = None
        try:
            for step_idx, step in enumerate(event.sequence_steps):
                if step.delay_ms > 0:
                    await asyncio.sleep(step.delay_ms / 1000)
                if step.step_type == "action":
                    resolved = self._resolve_step_actions(step)
                    if resolved:
                        await asyncio.gather(*(
                            self._execute_action(a, labels, await_ramps=True, skip_event_ids=skip_event_ids)
                            for a in resolved
                        ))
                elif step.step_type == "event" and step.event_id:
                    sub_event = get_event(step.event_id)
                    if sub_event is None:
                        continue
                    # Skip if already planned separately
                    if skip_event_ids and sub_event.id in skip_event_ids:
                        continue
                    # Apply step-level label filter (merge with caller labels)
                    merged_labels = labels + step.labels
                    if sub_event.event_type == "sequence":
                        await self._execute_sequence(sub_event, merged_labels, skip_event_ids=skip_event_ids)
                    elif sub_event.event_type == "beat_sequence":
                        trigger_ms = state.current_track.interpolated_progress_ms() if state.current_track else 0
                        await self._execute_beat_sequence(
                            sub_event, trigger_ms, merged_labels,
                            skip_event_ids=skip_event_ids,
                        )
                    elif sub_event.event_type == "composite":
                        await self._execute_composite(sub_event, merged_labels, skip_event_ids=skip_event_ids)
                    else:
                        # Use pre-selected action if available (matches what was previewed)
                        pre = pre_steps[step_idx] if pre_steps and step_idx < len(pre_steps) else None
                        action = pre or self._select_action(sub_event, merged_labels)
                        if action:
                            await self._execute_action(action, merged_labels, await_ramps=True, skip_event_ids=skip_event_ids)
        except asyncio.CancelledError:
            logger.warning("Sequence '%s' cancelled; revert will still run if configured", event.name)
            raise
        except Exception as exc:
            body_error = exc
            logger.error("Sequence '%s' body raised: %r; revert will still run if configured", event.name, exc)

        if revert and revert.enabled and snapshot:
            if ambient_vids:
                # Ambient flips: schedule cancellable revert so overlapping flips
                # can steal our snapshot. Returns immediately; revert runs in bg.
                await self._schedule_ambient_revert(event.name, snapshot, revert, ambient_vids)
            else:
                logger.info(
                    "Revert firing for '%s' (delay=%dms, transition=%dms)",
                    event.name, revert.delay_ms, revert.transition_ms,
                )
                if revert.delay_ms > 0:
                    await asyncio.sleep(revert.delay_ms / 1000)
                await self._restore_from_snapshot(snapshot, revert)
        elif revert and revert.enabled:
            logger.warning(
                "Revert NOT firing for '%s': snapshot empty (revert.enabled=%s snapshot=%s)",
                event.name, revert.enabled, bool(snapshot),
            )
        if body_error:
            raise body_error

    # ── Composite (node-tree) executors ─────────────────────────────────────

    async def _execute_parallel_group(
        self, group, labels: list[str], *,
        await_ramps: bool = False,
        skip_event_ids: set[str] | None = None,
        resolved_picks: dict | None = None,
        _depth: int = 0,
        inherited_scope=None,
    ) -> None:
        """Fire every child concurrently, staggered by per-child offset_ms.
        Generalization of _fire_morph_picks: anchor = min(offset); each child
        sleeps (offset - anchor) >= 0; a long stagger re-checks state.paused."""
        children = [c for c in group.children if c.actions]
        if not children:
            return
        anchor = min(int(c.offset_ms or 0) for c in children)

        async def _one(child) -> None:
            rel = int(child.offset_ms or 0) - anchor  # >= 0
            if rel > 0:
                await asyncio.sleep(rel / 1000)
                # A long stagger can outlast a pause/seek — don't fire into stale state.
                if state.paused:
                    return
            merged = labels + list(child.labels or [])
            child_scope = self._effective_scope(child.scope, inherited_scope)
            await asyncio.gather(*(
                self._execute_action(
                    a, merged, await_ramps=await_ramps, skip_event_ids=skip_event_ids,
                    _depth=_depth + 1, resolved_picks=resolved_picks,
                    inherited_scope=child_scope,
                )
                for a in child.actions
            ))

        await asyncio.gather(*(_one(c) for c in children), return_exceptions=True)

    async def _execute_sequence_group(
        self, group, labels: list[str], *,
        name: str = "",
        skip_event_ids: set[str] | None = None,
        resolved_picks: dict | None = None,
        _depth: int = 0,
        anchor_ms: int | None = None,
        step1_prefired: bool = False,
        precomputed_snapshot: Optional[dict] = None,
        inherited_scope=None,
    ) -> None:
        """Run children in order. timing="ms" ports _execute_sequence (per-child
        delay sleeps, revert with ambient-steal, revert-always-runs); timing=
        "beats" ports _execute_beat_sequence (beat interval, pre_ramp shift +
        100ms safety pad + ramp compression, monotonic-clock timeline, revert
        as a synthetic timeline entry)."""
        label = name or f"group:{group.id[:8]}"
        group_scope = self._effective_scope(group.scope, inherited_scope)
        if group.timing == "beats":
            await self._execute_beats_group(
                group, labels, name=label, skip_event_ids=skip_event_ids,
                resolved_picks=resolved_picks, _depth=_depth, anchor_ms=anchor_ms,
                step1_prefired=step1_prefired, precomputed_snapshot=precomputed_snapshot,
                inherited_scope=group_scope,
            )
            return

        revert = group.revert
        leaf = list(self._iter_leaf_actions(
            [a for c in group.children for a in c.actions], resolved_picks,
            inherited_scope=group_scope,
        )) if revert and revert.enabled else []
        ambient_vids = self._event_touches_ambient(actions=leaf) if revert and revert.enabled else []
        snapshot: dict = {}
        if revert and revert.enabled:
            stolen = self._steal_pending_ambient_snapshot(ambient_vids) if ambient_vids else None
            if stolen is not None:
                snapshot = stolen
            elif precomputed_snapshot is not None:
                snapshot = precomputed_snapshot
            else:
                snapshot = await self._snapshot_for_revert(actions=leaf)
            if not snapshot:
                logger.warning(
                    "Revert skipped for '%s': snapshot is empty (target virtual cache may be missing effect info)",
                    label,
                )

        body_error: Optional[BaseException] = None
        try:
            for child in group.children:
                # delay_ms alone = classic sleep; with delay_updates set the
                # child also fires after that many scene-family fires —
                # whichever comes first (see _sleep_child_delay).
                await self._sleep_child_delay(
                    child.delay_ms, getattr(child, "delay_updates", None))
                if not child.actions:
                    continue
                merged = labels + list(child.labels or [])
                child_scope = self._effective_scope(child.scope, group_scope)
                await asyncio.gather(*(
                    self._execute_action(
                        a, merged, await_ramps=True, skip_event_ids=skip_event_ids,
                        _depth=_depth + 1, resolved_picks=resolved_picks,
                        inherited_scope=child_scope,
                    )
                    for a in child.actions
                ))
        except asyncio.CancelledError:
            logger.warning("Sequence group '%s' cancelled; revert will still run if configured", label)
            raise
        except Exception as exc:
            body_error = exc
            logger.error("Sequence group '%s' body raised: %r; revert will still run if configured", label, exc)

        if revert and revert.enabled and snapshot:
            if ambient_vids:
                await self._schedule_ambient_revert(label, snapshot, revert, ambient_vids)
            else:
                logger.info(
                    "Revert firing for '%s' (delay=%dms, transition=%dms)",
                    label, revert.delay_ms, revert.transition_ms,
                )
                if revert.delay_ms > 0:
                    await asyncio.sleep(revert.delay_ms / 1000)
                await self._restore_from_snapshot(snapshot, revert)
        elif revert and revert.enabled:
            logger.warning(
                "Revert NOT firing for '%s': snapshot empty (revert.enabled=%s snapshot=%s)",
                label, revert.enabled, bool(snapshot),
            )
        if body_error:
            raise body_error

    async def _execute_beats_group(
        self, group, labels: list[str], *,
        name: str,
        skip_event_ids: set[str] | None = None,
        resolved_picks: dict | None = None,
        _depth: int = 0,
        anchor_ms: int | None = None,
        step1_prefired: bool = False,
        precomputed_snapshot: Optional[dict] = None,
        inherited_scope=None,
    ) -> None:
        """Beats-mode body of a sequence_group — port of _execute_beat_sequence."""
        have_beats = bool(self._beats_cache)
        if not have_beats and group.beat_fallback == "skip":
            uri = state.current_track.spotify_uri if state.current_track else ""
            logger.warning("Beats group '%s': no beat data for %s — skipping", name, uri)
            return

        if anchor_ms is not None:
            anchor = anchor_ms
            interval_ms = self._local_beat_interval_ms(anchor)
        else:
            song_now = state.current_track.interpolated_progress_ms() if state.current_track else 0
            interval_ms = self._local_beat_interval_ms(song_now)
            anchor = song_now + group.start_offset_beats * interval_ms

        # Build timeline of (child, fire_time, actual_ramp, is_revert).
        timeline: list[tuple] = []
        nominal_time = float(anchor)
        prev_fire_time: float = float("-inf")
        prev_ramp_ms = 0

        for i, child in enumerate(group.children):
            if i > 0:
                nominal_time += (1 + child.delay_beats) * interval_ms
            # Containers resolve at fire time — no ramp contribution.
            ramp_sources = [a for a in child.actions if a.type not in self.CONTAINER_ACTION_TYPES]
            ramp_ms = 0
            if ramp_sources:
                ramp_ms = max(self._plan_ramp_ms(a) for a in ramp_sources)
            raw_fire = (nominal_time - ramp_ms) if (child.pre_ramp and ramp_ms > 0) else nominal_time
            earliest = prev_fire_time + prev_ramp_ms + 100
            if raw_fire < earliest:
                fire_time = earliest
                actual_ramp = max(0, int(nominal_time) - int(earliest))
            else:
                fire_time = raw_fire
                actual_ramp = ramp_ms
            timeline.append((child, fire_time, actual_ramp, False))
            prev_fire_time = fire_time
            prev_ramp_ms = actual_ramp

        revert = group.revert
        if revert and revert.enabled and timeline:
            revert_nominal = nominal_time + (1 + revert.delay_beats) * interval_ms
            raw_fire = (revert_nominal - revert.transition_ms) if (revert.pre_ramp and revert.transition_ms > 0) else revert_nominal
            earliest = prev_fire_time + prev_ramp_ms + 100
            revert_fire_time = max(raw_fire, earliest)
            timeline.append((None, revert_fire_time, revert.transition_ms, True))

        snapshot: dict = {}
        if revert and revert.enabled:
            if precomputed_snapshot is not None:
                snapshot = precomputed_snapshot
            else:
                leaf = list(self._iter_leaf_actions(
                    [a for c in group.children for a in c.actions], resolved_picks,
                    inherited_scope=inherited_scope,
                ))
                snapshot = await self._snapshot_for_revert(actions=leaf)

        import time as _time
        timeline_origin = int(timeline[0][1]) if timeline else 0
        exec_start = _time.monotonic()
        _song_now = state.current_track.interpolated_progress_ms() if state.current_track else 0
        logger.info(
            "beats_group '%s': anchor=%d song_now=%d lag=%+dms interval=%dms steps=%s",
            name, anchor, _song_now, _song_now - int(anchor), interval_ms,
            [int(t[1]) - timeline_origin for t in timeline],
        )

        for i, (child, fire_time, actual_ramp, is_revert) in enumerate(timeline):
            if i == 0 and step1_prefired:
                continue
            step_offset_ms = int(fire_time) - timeline_origin
            elapsed_ms = (_time.monotonic() - exec_start) * 1000
            wait_ms = step_offset_ms - elapsed_ms
            if wait_ms > 0:
                await asyncio.sleep(wait_ms / 1000)
            logger.info(
                "  bg step %d/%d: planned_offset=%dms elapsed=%dms waited=%dms%s",
                i, len(timeline), step_offset_ms, int(elapsed_ms), max(0, int(wait_ms)),
                " [REVERT]" if is_revert else "",
            )
            if is_revert:
                if snapshot:
                    await self._restore_from_snapshot(snapshot, revert)
            elif child is not None and child.actions:
                merged = labels + list(child.labels or [])
                child_scope = self._effective_scope(child.scope, inherited_scope)
                dispatch = []
                for action in child.actions:
                    stored_ramp = getattr(action, "ramp_ms", None)
                    effective_ramp = stored_ramp if stored_ramp is not None else settings.smooth_ramp_ms
                    if (action.type not in self.CONTAINER_ACTION_TYPES
                            and actual_ramp != effective_ramp and hasattr(action, "ramp_ms")):
                        action = action.model_copy(update={"ramp_ms": actual_ramp})
                    dispatch.append(action)
                await asyncio.gather(*(
                    self._execute_action(
                        a, merged, await_ramps=False, skip_event_ids=skip_event_ids,
                        _depth=_depth + 1, resolved_picks=resolved_picks,
                        inherited_scope=child_scope,
                    )
                    for a in dispatch
                ))

    async def _execute_composite(
        self, event: MusicEvent, labels: list[str], *,
        skip_event_ids: set[str] | None = None,
        resolved_picks: dict | None = None,
        anchor_ms: int | None = None,
        step1_prefired: bool = False,
        precomputed_snapshot: Optional[dict] = None,
    ) -> None:
        """Top-level entry for a composite event: snapshot (if the root is a
        revert-enabled sequence group), then the root tree."""
        root = event.root
        if root is None:
            return

        snap = precomputed_snapshot
        if (root.type == "sequence_group" and root.revert and root.revert.enabled
                and snap is None):
            leaf = list(self._iter_leaf_actions(
                [a for c in root.children for a in c.actions], resolved_picks,
            ))
            ambient_vids = self._event_touches_ambient(actions=leaf)
            stolen = self._steal_pending_ambient_snapshot(ambient_vids) if ambient_vids else None
            snap = stolen if stolen is not None else await self._snapshot_for_revert(actions=leaf)

        if root.type == "sequence_group":
            await self._execute_sequence_group(
                root, labels, name=event.name, skip_event_ids=skip_event_ids,
                resolved_picks=resolved_picks, anchor_ms=anchor_ms,
                step1_prefired=step1_prefired, precomputed_snapshot=snap,
            )
        else:
            await self._execute_action(
                root, labels, await_ramps=True, skip_event_ids=skip_event_ids,
                resolved_picks=resolved_picks,
            )

    async def _execute_plan_entry(self, entry: _PlanEntry) -> None:
        """Execute one plan entry at its scheduled time."""
        if state.paused:
            return
        _FIRE_INTENSITY.set(entry.trigger_intensity)  # per-task context — no cross-fire leak
        _FIRE_COLOR_GROUP.set(entry.trigger_color_group)
        evt = entry.event
        skip_ids = entry.planned_descendant_ids or None

        # Scene-override fast path: planner pre-staged the temp scene + per-virtual
        # transition_time. Just activate it — then fire any Color Set lanes, which
        # the step-only scene payload doesn't carry.
        if entry.scene_override_prepared and entry.scene_override_payload:
            await self._fire_scene_override(entry.scene_override_payload, evt)
            entry.scene_override_prepared = False  # consumed
            await self._fire_color_lanes_alongside(
                entry.preselected_morph_picks, entry.labels,
                anchor_offset_ms=entry.morph_anchor_offset_ms, skip_event_ids=skip_ids,
            )
            return

        # Eligible but planner missed the lookahead window — prepare inline
        # (best effort) and fire. Logs a warning.
        _so_picks = entry.preselected_morph_picks if evt.event_type == "morph_set" else None
        if evt.event_type == "composite":
            _so_picks = entry.preselected_morph_picks or self._composite_scene_picks(
                evt, entry.resolved_picks)
        if self._event_eligible_for_scene_override(evt, picks=_so_picks):
            with ledfx_client.force_allow():
                fired = await self._maybe_fire_scene_override(evt, labels=entry.labels, picks=_so_picks)
            if fired:
                logger.warning(
                    "scene-override fell back to inline prep at fire time for '%s' (lookahead missed)",
                    evt.name,
                )
                return
        # If the planner kicked off a pre-fire snapshot task, await it now.
        # Should already be complete (built seconds ago while the loop was idle).
        snap: Optional[dict] = None
        if entry.snapshot_task is not None:
            try:
                snap = await entry.snapshot_task
            except Exception:
                snap = None
        if evt.event_type == "single":
            action = entry.preselected_action or self._select_action(evt, entry.labels)
            if action:
                await self._execute_action(action, entry.labels, skip_event_ids=skip_ids)
        elif evt.event_type == "sequence":
            await self._execute_sequence(
                evt, entry.labels,
                pre_steps=entry.preselected_steps,
                skip_event_ids=skip_ids,
                precomputed_snapshot=snap,
            )
        elif evt.event_type == "beat_sequence":
            # fire_at_ms is already the anchor, computed with compounded offsets.
            await self._execute_beat_sequence(
                evt, entry.fire_at_ms, entry.labels,
                skip_event_ids=skip_ids,
                anchor_override_ms=entry.fire_at_ms,
                precomputed_snapshot=snap,
            )
        elif evt.event_type == "morph_set":
            picks = entry.preselected_morph_picks
            if picks is None:
                picks = self._pick_morph_lanes(evt, entry.labels)
            # Pass the planner's anchor so fire-time sleeps line up with the
            # fire_at_ms shift (the earliest lane fires now, others sleep forward).
            await self._fire_morph_picks(
                picks, entry.labels, skip_event_ids=skip_ids,
                anchor_offset_ms=entry.morph_anchor_offset_ms,
            )
        elif evt.event_type == "device_settings":
            await self._apply_device_targets(evt.device_targets)
        elif evt.event_type == "composite":
            await self._execute_composite(
                evt, entry.labels,
                skip_event_ids=skip_ids,
                resolved_picks=entry.resolved_picks,
                anchor_ms=entry.fire_at_ms,
                precomputed_snapshot=snap,
            )
        elif evt.event_type in SCENE_EVENT_TYPES:
            # Use the plan-time lane picks (and their deep-resolved random
            # branches) only while the Scene Update they were rolled against
            # is still the active one; otherwise re-roll everything so a
            # stale preview can't fire lanes of a replaced scene. Scene Updates
            # roll against their own lanes (the Force Scene target when active),
            # so their picks stay valid regardless of which scene is live —
            # _execute_scene_event drops them if the target event changed.
            picks = None
            resolved = None
            if entry.preselected_scene_picks and (
                    evt.event_type == "scene_update"
                    or entry.scene_picks_sid == self._last_scene_update_id):
                picks = dict(entry.preselected_scene_picks)
                resolved = entry.resolved_picks
            await self._execute_scene_event(
                evt, entry.labels, skip_event_ids=skip_ids,
                preselected=picks, resolved_picks=resolved,
                picks_event_id=entry.scene_picks_event_id)

    async def _execute_beat_sequence(
        self,
        event: MusicEvent,
        trigger_ms: int,
        labels: list[str],
        step1_prefired: bool = False,
        skip_event_ids: set[str] | None = None,
        anchor_override_ms: int | None = None,
        precomputed_snapshot: Optional[dict] = None,
    ) -> None:
        """
        Execute a beat-timed sequence of steps.

        Semantics (not grid-snapped):
          - Step 0 fires at the anchor (= trigger_ms + beat_sequence_start_offset_beats * interval, or an explicit anchor when the planner pre-computed one).
          - Step i fires at step_{i-1}_nominal + (1 + step_i.delay_beats) * interval.
          - `interval` is the local beat-to-beat gap at the anchor, so the same
            sequence on a 60 BPM section spaces 2x longer than on a 120 BPM section
            without needing separate configs.
          - `pre_ramp=True` on an action step shifts the *actual fire* earlier
            by ramp_ms; the next step's spacing is still measured from the
            nominal (non-shifted) time, so pre_ramp doesn't compress the chain.
        """
        have_beats = bool(self._beats_cache)
        if not have_beats and event.beat_sequence_fallback == "skip":
            uri = state.current_track.spotify_uri if state.current_track else ""
            logger.warning("Beat sequence '%s': no beat data for %s — skipping", event.name, uri)
            return

        if anchor_override_ms is not None:
            anchor_ms = anchor_override_ms
            interval_ms = self._local_beat_interval_ms(anchor_ms)
        else:
            interval_ms = self._local_beat_interval_ms(trigger_ms)
            anchor_ms = trigger_ms + event.beat_sequence_start_offset_beats * interval_ms

        # Build timeline of (step, fire_time, actual_ramp, is_revert)
        # where fire_time is the *actual* fire time (possibly pre-ramped earlier)
        # and we track nominal_time separately for spacing.
        timeline: list[tuple] = []
        nominal_time = float(anchor_ms)
        prev_fire_time: float = float("-inf")
        prev_ramp_ms = 0

        for i, step in enumerate(event.beat_sequence_steps):
            if i > 0:
                nominal_time += (1 + step.delay_beats) * interval_ms

            resolved = self._resolve_step_actions(step) if step.step_type == "action" else []
            # random_group resolves at fire time — it carries no ramp, so it
            # contributes no pre-ramp lead (fires on the beat, ramp starts there).
            ramp_sources = [a for a in resolved if a.type != "random_group"]
            ramp_ms = 0
            if ramp_sources:
                # Respect ramp_ms=0 (instant) — only fall back to smooth_ramp_ms
                # when the field is None. Bound ramps resolve via _plan_ramp_ms
                # so max() never sees a ValueBinding.
                ramp_ms = max(self._plan_ramp_ms(a) for a in ramp_sources)

            raw_fire = (nominal_time - ramp_ms) if (step.pre_ramp and ramp_ms > 0) else nominal_time
            # Safety pad: steps can't overlap their predecessor's ramp + 100 ms.
            earliest = prev_fire_time + prev_ramp_ms + 100
            if raw_fire < earliest:
                fire_time = earliest
                actual_ramp = max(0, int(nominal_time) - int(earliest))
            else:
                fire_time = raw_fire
                actual_ramp = ramp_ms

            timeline.append((step, fire_time, actual_ramp, False))
            prev_fire_time = fire_time
            prev_ramp_ms = actual_ramp

        # Revert entry: delay_beats beats after the last nominal step time.
        revert = event.beat_revert
        if revert and revert.enabled and timeline:
            revert_nominal = nominal_time + (1 + revert.delay_beats) * interval_ms
            raw_fire = (revert_nominal - revert.transition_ms) if (revert.pre_ramp and revert.transition_ms > 0) else revert_nominal
            earliest = prev_fire_time + prev_ramp_ms + 100
            revert_fire_time = max(raw_fire, earliest)
            timeline.append((None, revert_fire_time, revert.transition_ms, True))

        # _snapshot_for_revert itself warms any missing target-virtual cache entries
        # concurrently, so no separate sequential refresh is needed.
        snapshot: dict = {}
        if revert and revert.enabled:
            if precomputed_snapshot is not None:
                snapshot = precomputed_snapshot
            else:
                snapshot = await self._snapshot_for_revert(event)

        # Execute timeline — use monotonic clock for relative inter-step delays.
        # This keeps beat spacing correct even when the trigger fires late (e.g. negative
        # trigger_buffer_ms) and all absolute beat positions are already in the past.
        import time as _time
        timeline_origin = int(timeline[0][1]) if timeline else 0  # fire_time of step 0
        exec_start = _time.monotonic()
        # Diagnostics for "delayed / too fast" beat sequences: log planned offsets
        # and the real-time gap between function entry and exec_start.
        _song_now = state.current_track.interpolated_progress_ms() if state.current_track else 0
        logger.info(
            "beat_seq '%s': anchor=%d song_now=%d lag=%+dms interval=%dms steps=%s",
            event.name, anchor_ms, _song_now, _song_now - anchor_ms, interval_ms,
            [int(t[1]) - timeline_origin for t in timeline],
        )

        for i, (step, fire_time, actual_ramp, is_revert) in enumerate(timeline):
            # Step 1 (i==0) may have been pre-fired as a pre-ramp command
            if i == 0 and step1_prefired:
                continue

            # Wait until this step's offset (from step-0's anchor) has elapsed since exec_start
            step_offset_ms = int(fire_time) - timeline_origin
            elapsed_ms = (_time.monotonic() - exec_start) * 1000
            wait_ms = step_offset_ms - elapsed_ms
            if wait_ms > 0:
                await asyncio.sleep(wait_ms / 1000)
            logger.info(
                "  bs step %d/%d: planned_offset=%dms elapsed=%dms waited=%dms%s",
                i, len(timeline), step_offset_ms, int(elapsed_ms), max(0, int(wait_ms)),
                " [REVERT]" if is_revert else "",
            )

            if is_revert:
                if snapshot:
                    await self._restore_from_snapshot(snapshot, revert)
            elif step is not None:
                if step.step_type == "action":
                    resolved = self._resolve_step_actions(step)
                    dispatch = []
                    for action in resolved:
                        # Apply compressed ramp if needed
                        stored_ramp = getattr(action, "ramp_ms", None)
                        effective_ramp = stored_ramp if stored_ramp is not None else settings.smooth_ramp_ms
                        if actual_ramp != effective_ramp and hasattr(action, "ramp_ms"):
                            action = action.model_copy(update={"ramp_ms": actual_ramp})
                        dispatch.append(action)
                    if dispatch:
                        await asyncio.gather(*(
                            self._execute_action(a, labels, await_ramps=False, skip_event_ids=skip_event_ids)
                            for a in dispatch
                        ))
                elif step.step_type == "event" and step.event_id:
                    sub_event = get_event(step.event_id)
                    if sub_event and (not skip_event_ids or sub_event.id not in skip_event_ids):
                        merged_labels = labels + (step.labels or [])
                        if sub_event.event_type == "sequence":
                            await self._execute_sequence(sub_event, merged_labels, skip_event_ids=skip_event_ids)
                        elif sub_event.event_type == "beat_sequence":
                            sub_trigger_ms = int(fire_time)
                            await self._execute_beat_sequence(
                                sub_event, sub_trigger_ms, merged_labels,
                                skip_event_ids=skip_event_ids,
                            )
                        elif sub_event.event_type == "composite":
                            await self._execute_composite(sub_event, merged_labels, skip_event_ids=skip_event_ids)
                        else:
                            sub_action = self._select_action(sub_event, merged_labels)
                            if sub_action:
                                await self._execute_action(sub_action, merged_labels, await_ramps=False, skip_event_ids=skip_event_ids)

    async def run(self) -> None:
        """Main trigger loop — runs forever."""
        logger.info("Trigger engine started (tick=%dms).", TICK_MS)
        _first_tick_logged_uri: str = ""
        while True:
            await asyncio.sleep(TICK_MS / 1000)

            if not state.current_track or not state.current_track.is_playing:
                continue
            if not state.on_target_device:
                continue
            if self._profile is None or self._profile.spotify_uri != state.current_track.spotify_uri:
                continue

            now_ms = state.current_track.interpolated_progress_ms()
            if _first_tick_logged_uri != self._profile.spotify_uri:
                _first_tick_logged_uri = self._profile.spotify_uri
                logger.info(
                    "first tick for %s: now_ms=%d, fired=%d preselected, "
                    "effective_offset=%+dms (buffer=%d, rtt=%d, shape=%+d)",
                    self._profile.spotify_uri, now_ms, len(self._fired),
                    self._effective_offset_ms(),
                    settings.ledfx_trigger_buffer_ms,
                    int(state.ledfx_rtt_ms),
                    self._shape_offset_ms,
                )

            # ── Detect seek-back or song restart ──────────────────────────
            if now_ms < self._last_progress_ms - 10000:
                # Progress jumped backward significantly — re-enable triggers ahead of new position
                re_enabled = {tid for tid in self._fired if any(
                    t.id == tid and t.timestamp_ms > now_ms
                    for t in self._get_active_triggers()
                )}
                if re_enabled:
                    self._fired -= re_enabled
                    self._pre_fired -= re_enabled
                    for tid in re_enabled:
                        self._preselected.pop(tid, None)
                        self._preselected_steps.pop(tid, None)
                        for _e in self._plan.get(tid, []):
                            if _e.snapshot_task and not _e.snapshot_task.done():
                                _e.snapshot_task.cancel()
                        self._plan.pop(tid, None)
                        self._plan_desc.pop(tid, None)
                    logger.info("Seek-back detected (%dms → %dms): re-enabled %d triggers",
                                self._last_progress_ms, now_ms, len(re_enabled))
            self._last_progress_ms = now_ms

            offset = self._effective_offset_ms()
            effective_now = now_ms + offset  # look ahead by offset

            # ── Stale-fire suppression ─────────────────────────────────────
            # Triggers more than STALE_FIRE_MS behind the current song position
            # AND with no in-flight plan execution were already "missed"
            # (service restart mid-song, long forward seek, dinner-party
            # toggle). Firing them now spawns a burst of concurrent
            # beat-sequences that saturates the event loop and delays later,
            # legitimate triggers by seconds. Mark silently-fired here instead.
            #
            # Skip triggers whose plan has any fired entries — a beat sequence
            # with a negative-offset child that already fired is mid-execution,
            # and its root plan entry may still be ahead in time. Killing it
            # here aborts the sequence mid-flight.
            # Compare against effective_now, not raw now_ms: with negative
            # shape_offset_ms the fire window opens later than the song
            # position, so raw-now would mark triggers stale before they
            # could fire.
            _stale = [
                t for t in self._get_active_triggers()
                if t.enabled and t.id not in self._fired
                and effective_now - t.timestamp_ms > STALE_FIRE_MS
                and not any(e.fired for e in self._plan.get(t.id, []))
            ]
            if _stale:
                for _t in _stale:
                    self._fired.add(_t.id)
                    for _e in self._plan.get(_t.id, []):
                        if _e.snapshot_task and not _e.snapshot_task.done():
                            _e.snapshot_task.cancel()
                    self._plan.pop(_t.id, None)
                    self._plan_desc.pop(_t.id, None)
                    self._preselected.pop(_t.id, None)
                    self._preselected_steps.pop(_t.id, None)
                logger.info(
                    "Stale-fire suppression: skipped %d trigger(s) more than %dms behind effective_now=%d (raw song pos=%d, offset=%+d)",
                    len(_stale), STALE_FIRE_MS, effective_now, now_ms, offset,
                )

            # Keep live timing info in shared state for WS broadcast
            state.timing = {
                "effective_offset_ms":   offset,
                "shape_offset_ms":       self._shape_offset_ms,
                "shape_offset_quality":  self._shape_offset_quality,
                "ledfx_rtt_ms":          int(state.ledfx_rtt_ms),
                "buffer_ms":             settings.ledfx_trigger_buffer_ms,
                "shape_offset_source":   "setlist" if state.active_setlist_id else "default",
                "active_setlist_id":     state.active_setlist_id,
            }

            # ── Pre-select next trigger action for preview ────────────────────
            next_t = next(
                (t for t in sorted(self._get_active_triggers(), key=lambda x: x.timestamp_ms)
                 if t.enabled and t.id not in self._fired and t.timestamp_ms > now_ms),
                None,
            )
            if next_t is None:
                if self._last_preview_id is not None:
                    self._last_preview_id = None
                    asyncio.create_task(ws_manager.broadcast({"type": "trigger_preview_clear"}))
            else:
                if next_t.id != self._last_preview_id:
                    self._last_preview_id = next_t.id
                    event = get_event(next_t.event_id)
                    if event:
                        # Build the full execution plan once per "next" trigger.
                        # _plan_timeline also pre-selects actions (for singles it
                        # resolves event_refs), so the preview and the firing use
                        # the same choices.
                        blend = (self._blend_factor_for(next_t, event)
                                 if getattr(next_t, "override_blend", False) else None)
                        plan, desc = self._plan_timeline(
                            event, next_t, list(next_t.labels),
                            time_scale=blend if blend is not None else 1.0,
                        )
                        if blend is not None:
                            self._blend_scale_plan(plan, blend)
                            desc = f"{desc} [blend ×{blend:.2f}]"
                            logger.info(
                                "Override Blend: trigger %s (event '%s') scaled ×%.3f",
                                next_t.id, event.name, blend,
                            )
                        self._plan[next_t.id] = plan
                        self._plan_desc[next_t.id] = desc
                        # Pre-snapshot at plan-time was tried here and REMOVED:
                        # each plan built spawned one get_virtual-gather per
                        # revertable entry, piling concurrent httpx tasks onto
                        # the event loop faster than they drained — lag grew
                        # fire-by-fire (~1s → ~2s → stale burst). The snapshot
                        # stays inline in _execute_{sequence,beat_sequence}.
                        # Legacy preselection caches (kept for _fire_trigger fallback
                        # and any code paths that still read them).
                        for entry in plan:
                            if entry.event.event_type == "single" and entry.preselected_action:
                                self._preselected[entry.event.id] = entry.preselected_action
                        # Remember the root's preselected action / steps for _fire_trigger
                        root_entries = [e for e in plan if e.event.id == event.id]
                        if root_entries:
                            root_entry = root_entries[0]
                            if root_entry.preselected_action:
                                self._preselected[next_t.id] = root_entry.preselected_action
                            if root_entry.preselected_steps:
                                self._preselected_steps[next_t.id] = root_entry.preselected_steps

                        asyncio.create_task(ws_manager.broadcast({
                            "type":         "trigger_preview",
                            "trigger_id":   next_t.id,
                            "event_name":   event.name,
                            "event_color":  event.color,
                            "action_label": desc or None,
                            "rows":         self._preview_rows(event, plan),
                            "locked":       False,
                        }))

            # ─────────────────────────────────────────────────────────────────

            if not state.paused:
                # Skip in dinner party mode (DP scenes handle their own ramps)
                if not state.dinner_party_mode:
                    # Beat sequence Step 1 pre-ramp look-ahead
                    for trigger in self._get_active_triggers():
                        if not trigger.enabled or trigger.id in self._fired or trigger.id in self._pre_fired:
                            continue
                        event = get_event(trigger.event_id)
                        if not event or event.event_type != "beat_sequence":
                            continue
                        steps = event.beat_sequence_steps
                        if not steps:
                            continue
                        step0 = steps[0]
                        if not step0.pre_ramp or step0.step_type != "action" or step0.action is None:
                            continue
                        ramp_ms = getattr(step0.action, "ramp_ms", None)
                        if ramp_ms is None:
                            ramp_ms = settings.smooth_ramp_ms
                        if ramp_ms <= 0:
                            continue
                        if trigger.timestamp_ms - ramp_ms <= effective_now:
                            self._pre_fired.add(trigger.id)
                            asyncio.create_task(self._execute_action(step0.action, trigger.labels, await_ramps=False))

                # ── Scene-override look-ahead ─────────────────────────────
                # For any root entry with event.scene_override eligible, pre-stage
                # the temp scene + per-virtual transition_time some lead_ms before
                # fire_at_ms. At fire time the dispatch is just a single PUT
                # /api/scenes activate. Skipped while paused (no LedFX writes).
                if not state.paused:
                    lead_ms = getattr(settings, "scene_override_lead_ms", 500) or 500
                    for _tid, _entries in list(self._plan.items()):
                        if _tid in self._fired:
                            continue
                        for _entry in _entries:
                            if _entry.fired or _entry.scene_override_prepared:
                                continue
                            if not _entry.is_root:
                                continue
                            _ck_picks = None
                            if _entry.event.event_type == "composite":
                                _ck_picks = (_entry.preselected_morph_picks
                                             or self._composite_scene_picks(
                                                 _entry.event, _entry.resolved_picks))
                            if not self._event_eligible_for_scene_override(_entry.event, picks=_ck_picks):
                                continue
                            if _entry.fire_at_ms - effective_now > lead_ms:
                                continue
                            picks = _entry.preselected_morph_picks
                            if _entry.event.event_type == "morph_set" and picks is None:
                                picks = self._pick_morph_lanes(_entry.event, _entry.labels)
                                _entry.preselected_morph_picks = picks
                            elif _entry.event.event_type == "composite":
                                picks = _ck_picks
                                _entry.preselected_morph_picks = picks
                            from models.music_event import MorphStepAction as _MSA
                            morph_actions = (
                                [p.action for p in (picks or []) if isinstance(p.action, _MSA)]
                                if _entry.event.event_type in ("morph_set", "composite")
                                else self._collect_morph_actions_for_event(_entry.event, _entry.labels)
                            )
                            _fi_tok = _FIRE_INTENSITY.set(_entry.trigger_intensity)
                            _cg_tok = _FIRE_COLOR_GROUP.set(_entry.trigger_color_group)
                            try:
                                payload = self._build_scene_payload(morph_actions)
                            finally:
                                _FIRE_INTENSITY.reset(_fi_tok)
                                _FIRE_COLOR_GROUP.reset(_cg_tok)
                            if payload is None:
                                _entry.scene_override_prepared = True  # nothing to do, skip lookahead retries
                                continue
                            payload["device_targets"] = self._collect_device_settings_for_event(
                                _entry.event, _entry.labels, picks=picks)
                            _entry.scene_override_payload = payload
                            # Push prep async — completion before fire is best-effort;
                            # _execute_plan_entry's "eligible but not prepared" path
                            # provides the inline-prep fallback if prep isn't done.
                            async def _prep_and_mark(entry=_entry, payload=payload):
                                with ledfx_client.force_allow():
                                    ok = await self._push_scene_override_prep(payload)
                                if ok:
                                    entry.scene_override_prepared = True
                                    logger.info(
                                        "scene-override prepared '%s' at T-%dms (touched=%s)",
                                        entry.event.name,
                                        entry.fire_at_ms - effective_now,
                                        payload["touched_virtuals"],
                                    )
                                else:
                                    # Mark as "tried" so we don't retry every tick — fire-time fallback will handle it
                                    logger.warning("scene-override prep failed for '%s'; will retry inline at fire time", entry.event.name)
                            asyncio.create_task(_prep_and_mark())

                # ── Fire plan entries whose time has come ─────────────────
                # Each entry is an atomic fire computed by _plan_timeline with
                # compounded event_offset_ms. The root entry of each trigger
                # also emits the trigger_fired WS broadcast so the UI clears
                # the preview and shows the flash animation.
                # While the capture gate is muting LedFX writes, DON'T fire:
                # _execute_plan_entry's writes would be silently dropped but the
                # entries marked fired, permanently losing every trigger that
                # lands in the capture window. Deferring lets overdue entries
                # fire the moment the capture finishes (a beat late beats never).
                _muting = ledfx_client.capture_muting_active()
                triggers_by_id = {t.id: t for t in self._get_active_triggers()}
                for _tid, _entries in list(self._plan.items()):
                    if _tid in self._fired:
                        continue
                    _trigger = triggers_by_id.get(_tid)
                    if _trigger is None:
                        # Trigger was removed (profile edit) — drop its plan.
                        self._plan.pop(_tid, None)
                        self._plan_desc.pop(_tid, None)
                        continue
                    _all_fired = True
                    for _entry in _entries:
                        if _entry.fired:
                            continue
                        if _entry.fire_at_ms <= effective_now and not _muting:
                            _entry.fired = True
                            _is_root = (_entry.event.id == _trigger.event_id)
                            logger.info(
                                "Plan fire: %s at ~%dms (trigger=%s, %s, plan_offset=%+dms)",
                                _entry.event.name, now_ms, _tid,
                                "root" if _is_root else "child",
                                _entry.fire_at_ms - _trigger.timestamp_ms,
                            )
                            # For morph_set: ensure lanes are picked so the broadcast
                            # carries the per-lane outcome summary. Reuse the planner's
                            # pre-picks when present — re-rolling here would diverge from
                            # the summary already shown in preview and waste a roll (the
                            # anchor offset is the same either way since it's per-lane).
                            _morph_summary = ""
                            if _entry.event.event_type == "morph_set":
                                if _entry.preselected_morph_picks is None:
                                    _entry.preselected_morph_picks = self._pick_morph_lanes(_entry.event, _entry.labels)
                                _morph_summary = self._morph_picks_summary(_entry.preselected_morph_picks)
                            elif (_entry.event.event_type == "composite"
                                  and _entry.event.root is not None
                                  and _entry.event.root.type == "parallel_group"):
                                _morph_summary = self._describe_action(
                                    _entry.event.root, resolved=_entry.resolved_picks)
                            asyncio.create_task(self._execute_plan_entry(_entry))
                            if _is_root:
                                asyncio.create_task(
                                    ws_manager.broadcast_trigger_fired(
                                        _tid, _entry.event.name, _entry.event.color,
                                        scheduled_ms=_trigger.timestamp_ms,
                                        fired_at_ms=now_ms,
                                        effective_offset_ms=offset,
                                        event_type=_entry.event.event_type,
                                        summary=_morph_summary,
                                        intensity=_entry.trigger_intensity,
                                    )
                                )
                            else:
                                # Non-root child fired early: signal UI so the timeline updates
                                asyncio.create_task(ws_manager.broadcast({
                                    "type": "pre_scheduled_fired",
                                    "trigger_id": _tid,
                                    "event_name": _entry.event.name,
                                    "event_color": _entry.event.color,
                                    "fired_at_ms": now_ms,
                                }))
                        else:
                            _all_fired = False
                    if _all_fired:
                        self._fired.add(_tid)

                # Fallback: a trigger that somehow wasn't planned yet (e.g. first
                # tick after seek-back where the preview hasn't re-run) — fire it
                # the legacy way so nothing gets stuck.
                for trigger in self._get_active_triggers():
                    if not trigger.enabled or trigger.id in self._fired:
                        continue
                    if trigger.id in self._plan:
                        continue
                    if trigger.timestamp_ms <= effective_now and not _muting:
                        self._fired.add(trigger.id)
                        logger.info(
                            "Firing unplanned trigger %s at ~%dms (event=%s)",
                            trigger.id, now_ms, trigger.event_id,
                        )
                        asyncio.create_task(self._fire_trigger(
                            trigger, fired_at_ms=now_ms, effective_offset_ms=offset
                        ))

