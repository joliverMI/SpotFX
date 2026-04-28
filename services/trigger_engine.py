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
from dataclasses import dataclass, field as dc_field
from typing import Optional

from config import settings
from models.state import state
from models.song_profile import SongProfile, MusicTrigger
from models.music_event import MusicEvent, Action
from services.profile_manager import get_event
from services.audio_analyzer import load_audio_shape_meta, load_beats_for_uri, load_tempo_for_uri
from services.device_category_service import get_virtuals_for_role
from services.effect_params import get_all_virtual_ids
from services.websocket_manager import ws_manager
from api import ledfx_client

logger = logging.getLogger(__name__)

TICK_MS = 50  # engine resolution — 50 ms tick
STALE_FIRE_MS = 2000  # any trigger whose anchor is more than this far behind song position is silently marked fired (covers startup/long seek, leaves room for normal playback jitter)


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
    is_root: bool = False                         # True only for the root entry of a trigger's plan
    planned_descendant_ids: set[str] = dc_field(default_factory=set)
    preselected_action: Optional[Action] = None   # for "single" events — action chosen at plan time
    preselected_steps: Optional[list] = None      # for "sequence" events — per-step action pre-selection
    snapshot_task: Optional[asyncio.Task] = None  # pre-fire snapshot of the LedFX state this event will change
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
            return base + trim, quality, f"setlist:{sl_id}"
        # No entry yet — bias the default by the Set List's recent deltas.
        bias = _setlist_delta_bias(sl_id)
        if bias != 0:
            base = int(meta.timestamp_offset_ms or 0) + bias
            quality = float(meta.offset_quality or 0.0)
            trim = int(getattr(meta, "perception_trim_ms", 0) or 0)
            return base + trim, quality, f"default+setlist_bias:{bias:+d}"
    base = int(meta.timestamp_offset_ms or 0)
    quality = float(meta.offset_quality or 0.0)
    trim = int(getattr(meta, "perception_trim_ms", 0) or 0)
    return base + trim, quality, "default"


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
        self._pre_fired: set[str] = set()      # trigger ids whose pre-commands have fired
        self._pre_ramp_fired: set[str] = set() # trigger ids whose brightness ramp has started
        self._last_uri: str = ""
        self._last_progress_ms: int = 0
        # Track last called action per event id to avoid immediate repeat
        self._last_action: dict[str, str] = {}  # event_id -> action index/key
        self._shape_offset_ms: int = 0       # cached from AudioShapeMeta.timestamp_offset_ms
        self._shape_offset_quality: float = 0.0  # cached quality score (r × difficulty)
        # Highest match-quality observed during the current play. Reset on URI
        # change. Anchor and sweep saves only override the engine's live offset
        # when their quality strictly beats this — gives priority to confident
        # matches mid-play while still letting median (loaded at song start)
        # be the floor when no match clears it.
        self._play_best_quality: float = 0.0
        # Per-song librosa cache — avoids re-reading the JSON every beat-sequence fire.
        self._beats_cache: Optional[list] = None
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
        # Tracks the look-ahead _fire_pre_commands task per trigger, so when
        # _execute_plan_entry runs with skip_pre_commands=True it can AWAIT
        # the task before step 0 — guaranteeing the transition PUT reaches
        # LedFX before the effect PUT (otherwise the httpx pool may dispatch
        # them out of order and the transition won't apply to the change).
        self._pre_cmd_tasks: dict[str, asyncio.Task] = {}

    def _spawn_ramp(self, coro) -> asyncio.Task:
        """Create a tracked ramp task. All ramp tasks should use this instead of create_task."""
        task = asyncio.create_task(coro)
        self._ramp_tasks.add(task)
        task.add_done_callback(self._ramp_tasks.discard)
        return task

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
            self._pre_ramp_fired.clear()
            self._pre_cmd_tasks.clear()
            self._last_action.clear()
            self._preselected.clear()
            self._preselected_steps.clear()
            self._plan.clear()
            self._plan_desc.clear()
            self._last_preview_id = None
            self._last_uri = profile.spotify_uri
            # New song — clear the play-best floor so any anchor or sweep
            # save this play can override the median-derived starting baseline.
            self._play_best_quality = 0.0
            meta = load_audio_shape_meta(profile.spotify_uri)
            # Resolve the offset from whichever slot fits the current context
            # (Set List override or default), then layer the user's perception
            # trim on top so subjective alignment persists across plays.
            self._shape_offset_ms, self._shape_offset_quality, sl_source = _resolve_shape_offset(meta)
            logger.info(
                "load_profile: shape_offset_ms=%+d Q=%.2f source=%s",
                self._shape_offset_ms, self._shape_offset_quality, sl_source,
            )
            # Pre-load librosa beats/tempo once so beat-sequence fires don't
            # each re-parse the JSON file from disk.
            self._beats_cache = load_beats_for_uri(profile.spotify_uri)
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
                self._fired.add(start_trig.id)
                self._pre_fired.add(start_trig.id)
                self._pre_ramp_fired.add(start_trig.id)
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
        self._pre_ramp_fired.update(ids)
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
        self._pre_ramp_fired.update(newly_suppressed)
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
                self._pre_ramp_fired = {tid for tid in self._pre_ramp_fired if not tid.startswith("tl_")}
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
                    self._pre_ramp_fired.add(start_trig.id)
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
                self._pre_ramp_fired.update(skip_ids)
                self._fired.add(song_start.id)
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
            genres = getattr(self._profile, "genres", []) or []
        tp_data = _find_profile_for_genres(genres)
        if not tp_data:
            logger.info("Analyzed triggers: no matching training profile for genres %s", genres)
            return None
        tp = TrainingProfile(**tp_data)

        track_id = spotify_uri.split(":")[-1]
        cached = analyzed_trigger_store.load(track_id)
        if cached and analyzed_trigger_store.is_valid(cached, tp):
            logger.info(
                "Analyzed triggers: loaded %d cached for %s (profile: %s)",
                len(cached.triggers), spotify_uri, tp.name,
            )
            return [
                MusicTrigger(
                    id=t.id, timestamp_ms=t.timestamp_ms,
                    event_id=t.event_id, labels=list(t.labels or []),
                )
                for t in cached.triggers
            ]

        generated = analyzed_trigger_store.generate_for_uri(spotify_uri, save_cache=True)
        if not generated:
            return None
        return [
            MusicTrigger(
                id=t.id, timestamp_ms=t.timestamp_ms,
                event_id=t.event_id, labels=list(t.labels or []),
            )
            for t in generated
        ]

    # ── Triggerless play helpers ────────────────────────────────────────────

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
                    ))
                t += flare_interval_ms

        # 4. End event
        if end_eid and duration_ms > end_pre:
            triggers.append(MusicTrigger(
                id=f"tl_end_{end_cutoff}", timestamp_ms=end_cutoff,
                event_id=end_eid, labels=["triggerless", "end"],
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

    def apply_save(self, uri: str, raw_offset_ms: int, quality: float, source: str = "sweep") -> bool:
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
        logger.info(
            "Engine: snap %+dms → %+dms (Q %.2f → %.2f, source=%s, trim=%+d) for %s",
            self._shape_offset_ms, new_effective,
            self._play_best_quality, quality, source, trim, uri,
        )
        self._shape_offset_ms = new_effective
        self._shape_offset_quality = quality
        self._play_best_quality = quality
        return True

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
    ) -> tuple[list[_PlanEntry], str]:
        """
        Walk the resolved event tree and produce a flat list of _PlanEntry
        with absolute song-ms fire times. Offsets (event_offset_ms,
        sequence step.delay_ms, and beat-sequence step spacing) compound
        through the walk. Also returns a drill-down preview string.

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
                    step_time += step.delay_ms
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
                    is_root=(event.id == root_event.id),
                    planned_descendant_ids=child_ids,
                ))
                return " > ".join(parts) if parts else event.name

            return event.name

        description = walk(root_event, trigger.timestamp_ms, list(labels))
        entries.sort(key=lambda e: e.fire_at_ms)
        return entries, description

    @staticmethod
    def _resolve_step_actions(step) -> list:
        """Return the effective action list for a step (multi-action or single)."""
        if step.actions:
            return list(step.actions)
        if step.action is not None:
            return [step.action]
        return []

    def _select_action(self, event: MusicEvent, labels: list[str]) -> Optional[Action]:
        """
        Pick an action from event.actions respecting label filters and weights.
        De-weights the last-used action to avoid consecutive repeats.
        """
        if not event.actions:
            return None

        pos_labels = [l.lower() for l in labels if not l.startswith("-")]
        neg_labels = [l[1:].lower() for l in labels if l.startswith("-")]

        # Candidates are (original_index, action) pairs so identical actions are distinct
        candidates: list[tuple[int, Action]] = []
        for i, action in enumerate(event.actions):
            action_labels_lower = [l.lower() for l in action.labels]
            # Positive filter: if any pos labels given, action must match at least one
            if pos_labels and not any(pl in action_labels_lower for pl in pos_labels):
                continue
            # Negative filter
            if any(nl in action_labels_lower for nl in neg_labels):
                continue
            # Weight-0 actions are label-only: skip them unless a positive label matched
            if action.weight == 0 and not pos_labels:
                continue
            candidates.append((i, action))

        if not candidates:
            # Fall back to all actions (ignore labels) and log low-level alert
            logger.info("No actions matched labels %s for event '%s'; ignoring filter.", labels, event.name)
            candidates = list(enumerate(event.actions))

        if not candidates:
            return None

        # Zero out the weight of the last-fired action (by index) to avoid consecutive repeats
        last_idx = self._last_action.get(event.id)  # int index or None
        weights = [0.0 if i == last_idx else a.weight for i, a in candidates]

        # If all weights are 0 (last-action de-weight or weight-0 label-only actions), allow repeat
        if sum(weights) == 0:
            weights = [a.weight for _, a in candidates]
        # Still zero (all candidates are weight-0 label-only) — use uniform weights
        if sum(weights) == 0:
            weights = [1.0] * len(candidates)

        chosen_i, selected = random.choices(candidates, weights=weights, k=1)[0]
        self._last_action[event.id] = chosen_i
        return selected

    def _describe_action(self, action: Action, _depth: int = 0) -> str:
        """Return a short human-readable label for a pre-selected action."""
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
        elif action.type == "ledfx_global_brightness":
            return f"Brightness {int(action.brightness * 100)}%"
        elif action.type == "ledfx_global_transition":
            return f"Transition {action.transition_time}s"
        elif action.type == "ledfx_effect_param":
            scope = action.virtual_id or action.category or "all"
            names = [p.param_label for p in action.params if p.param_label]
            body = ", ".join(names) if names else "params"
            return f"{body} ({scope})"
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
        return action.type

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

        For single events: applies pre-brightness (ramp awaited) and pre-transition,
        waits the configured lead time, then fires the main action.
        """
        event = get_event(event_id)
        if event is None:
            logger.warning("fire_event_now: unknown event %s", event_id)
            return False
        if event.event_type == "single":
            await self._apply_pre_commands(event, list(labels or []))
            lead_ms = max(
                settings.pre_brightness_lead_ms if event.pre_brightness_enabled else 0,
                settings.pre_transition_lead_ms if event.pre_transition_enabled else 0,
            )
            if lead_ms > 0:
                await asyncio.sleep(lead_ms / 1000)
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

        event = get_event(trigger.event_id)
        if event is None:
            logger.warning("Trigger %s references unknown event %s.", trigger.id, trigger.event_id)
            return

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

        asyncio.create_task(
            ws_manager.broadcast_trigger_fired(
                trigger.id, event.name, event.color,
                scheduled_ms=trigger.timestamp_ms,
                fired_at_ms=fired_at_ms,
                effective_offset_ms=effective_offset_ms,
            )
        )

    async def _fire_pre_commands(self, event: MusicEvent, trigger_id: str, labels: list[str] | None = None) -> None:
        """Fire global brightness/transition ahead of a single event's main action."""
        ov = self._parse_label_overrides(labels or [])
        if not ov.get("skip_brightness") and event.pre_brightness_enabled and trigger_id not in self._pre_ramp_fired:
            value = ov.get("brightness_value", event.pre_brightness_value)
            await ledfx_client.set_config({"global_brightness": value})
        if not ov.get("skip_transition") and event.pre_transition_enabled:
            value = ov.get("transition_value", event.pre_transition_value)
            cfg = {"transition_time": value}
            vids = get_all_virtual_ids()
            logger.info("Pre-transition (look-ahead) '%s': set transition_time=%s on %d virtuals", event.name, value, len(vids))
            if vids:
                await asyncio.gather(
                    *(ledfx_client.set_virtual_config(vid, cfg) for vid in vids),
                    return_exceptions=True,
                )

    async def _execute_action(
        self, action: Action, labels: list[str] | None = None,
        await_ramps: bool = False, skip_event_ids: set[str] | None = None,
    ) -> None:
        """Dispatch a single action."""
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
            else:
                sub_action = self._select_action(sub, labels or [])
                if sub_action:
                    await self._execute_action(sub_action, labels, await_ramps=await_ramps, skip_event_ids=skip_event_ids)
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

        elif action.type == "ledfx_global_brightness":
            ramp_ms = action.ramp_ms if action.ramp_ms is not None else settings.smooth_ramp_ms
            if ramp_ms > 0:
                if await_ramps:
                    await ledfx_client.ramp_brightness(action.brightness, ramp_ms)
                else:
                    self._spawn_ramp(ledfx_client.ramp_brightness(action.brightness, ramp_ms))
            else:
                await ledfx_client.set_config({"global_brightness": action.brightness})

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
            from services.effect_params import get_virtuals_for_category, resolve_params, get_param_meta
            if action.virtual_id:
                virtuals = [action.virtual_id]
            elif action.category:
                virtuals = get_virtuals_for_category(action.category)
            else:
                virtuals = get_all_virtual_ids()
            ramp_ms = action.ramp_ms if action.ramp_ms is not None else settings.smooth_ramp_ms
            instant_coros = []
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
                        elif meta and meta.get("type") in ("color", "gradient"):
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
                        if await_ramps:
                            await ledfx_client.ramp_effect_params(vid, effect_type, num_patch, ramp_ms)
                            # Update cache AFTER the ramp so the next step's ramp_effect_params
                            # reads the correct post-ramp start value (not the pre-ramp value).
                            # Revert snapshot was taken before the sequence, so it's unaffected.
                            effect_cfg.update(num_patch)
                        else:
                            self._spawn_ramp(
                                ledfx_client.ramp_effect_params(vid, effect_type, num_patch, ramp_ms)
                            )
                    else:
                        instant_coros.append(ledfx_client.set_virtual_effect(vid, effect_type, num_patch))
                        effect_cfg.update(num_patch)
                if ramp_str:
                    if await_ramps:
                        await ledfx_client.ramp_gradient_params(vid, effect_type, ramp_str, ramp_ms)
                    else:
                        self._spawn_ramp(
                            ledfx_client.ramp_gradient_params(vid, effect_type, ramp_str, ramp_ms)
                        )
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
                            await coro
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

        else:
            logger.warning("Unknown action type: %s", action.type)

    async def _snapshot_for_revert(self, event: MusicEvent) -> dict:
        """
        Snapshot only the specific LedFX param values this sequence will change.

        Snapshot format:
          {
            "global_brightness": float,
            "virtual_effects":  {vid: {"type": str, "params": {pname: value}}},
            "virtual_configs":  {vid: {key: value}},
          }
        """
        from api import ledfx_client as _lc
        from services.effect_params import resolve_params, get_param_meta, get_virtuals_for_category

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

        # Gather every vid this event will touch so we can warm them concurrently.
        target_vids: set[str] = set()
        for _step in (event.beat_sequence_steps if event.event_type == "beat_sequence" else event.sequence_steps):
            if _step.step_type != "action":
                continue
            for _a in self._resolve_step_actions(_step):
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
        if target_vids:
            await _warm(list(target_vids))

        steps_to_check = (
            event.beat_sequence_steps if event.event_type == "beat_sequence"
            else event.sequence_steps
        )
        for step in steps_to_check:
            if step.step_type != "action":
                continue
            all_actions = self._resolve_step_actions(step)
            if not all_actions:
                continue
            for action in all_actions:
                if action.type == "ledfx_global_brightness":
                    snapshot.setdefault("global_brightness", _lc._current_brightness)

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

        if "global_brightness" in snapshot:
            target = snapshot["global_brightness"]
            if t_ms > 0:
                self._spawn_ramp(_lc.ramp_brightness(target, t_ms))
            else:
                await _lc.set_config({"global_brightness": target})

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

    @staticmethod
    def _parse_label_overrides(labels: list[str]) -> dict:
        """Extract special label overrides from the labels list."""
        ov: dict = {}
        for l in labels:
            if l == "-brightness":
                ov["skip_brightness"] = True
            elif l == "-transition":
                ov["skip_transition"] = True
            elif l.startswith("=brightness:"):
                try: ov["brightness_value"] = float(l.split(":", 1)[1])
                except ValueError: pass
            elif l.startswith("=transition:"):
                try: ov["transition_value"] = float(l.split(":", 1)[1])
                except ValueError: pass
            elif l.startswith("=ramp:"):
                try: ov["ramp_ms"] = int(l.split(":", 1)[1])
                except ValueError: pass
        return ov

    async def _apply_pre_commands(self, event: MusicEvent, labels: list[str] | None = None) -> None:
        """Apply pre-brightness and pre-transition before a sequence or single event fires.
        Special labels: -brightness/-transition skip; =brightness:/=transition:/=ramp: override.
        = overrides are consumed (removed from labels) after use so nested events use their own values.
        """
        ov = self._parse_label_overrides(labels or [])
        if not ov.get("skip_brightness") and event.pre_brightness_enabled:
            value = ov.get("brightness_value", event.pre_brightness_value)
            ramp_ms = ov.get("ramp_ms",
                             event.pre_brightness_ramp_ms if event.pre_brightness_ramp_ms is not None
                             else settings.smooth_ramp_ms)
            if ramp_ms > 0:
                await ledfx_client.ramp_brightness(value, ramp_ms)
            else:
                await ledfx_client.set_config({"global_brightness": value})
            # Consume = overrides so they don't fire again in nested events
            if labels:
                labels[:] = [l for l in labels
                             if not l.startswith("=brightness:") and not l.startswith("=ramp:")]
        if not ov.get("skip_transition") and event.pre_transition_enabled:
            value = ov.get("transition_value", event.pre_transition_value)
            cfg = {"transition_time": value}
            vids = get_all_virtual_ids()
            logger.info("Pre-transition (inline) '%s': set transition_time=%s on %d virtuals", event.name, value, len(vids))
            if vids:
                await asyncio.gather(
                    *(ledfx_client.set_virtual_config(vid, cfg) for vid in vids),
                    return_exceptions=True,
                )
            if labels:
                labels[:] = [l for l in labels if not l.startswith("=transition:")]

    def _event_touches_ambient(self, event: MusicEvent) -> list[str]:
        """Return the list of ambient virtual ids this event will modify, or []
        if it doesn't touch the ambient role. Used by the steal-snapshot path."""
        steps = event.beat_sequence_steps if event.event_type == "beat_sequence" else event.sequence_steps
        for step in steps:
            if step.step_type != "action":
                continue
            for a in self._resolve_step_actions(step):
                if a.type in ("ledfx_ambient", "ledfx_ambient_color"):
                    return list(get_virtuals_for_role("ambient"))
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
            if "global_brightness" in prev_snap and "global_brightness" not in stolen:
                stolen["global_brightness"] = prev_snap["global_brightness"]
        return stolen or None

    async def _schedule_ambient_revert(
        self, event: MusicEvent, snapshot: dict, revert_cfg, vids: list[str],
    ) -> None:
        """Fire revert as a cancellable task registered under each target vid.
        An overlapping flip can cancel this task mid-sleep via the steal path."""
        async def _revert_runner():
            try:
                logger.info(
                    "Revert firing for '%s' (delay=%dms, transition=%dms)",
                    event.name, revert_cfg.delay_ms, revert_cfg.transition_ms,
                )
                if revert_cfg.delay_ms > 0:
                    await asyncio.sleep(revert_cfg.delay_ms / 1000)
                await self._restore_from_snapshot(snapshot, revert_cfg)
            except asyncio.CancelledError:
                logger.info("Revert cancelled for '%s' — snapshot stolen by overlapping flip", event.name)
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
        skip_pre_commands: bool = False,
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
        if not skip_pre_commands:
            await self._apply_pre_commands(event, labels)

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
                await self._schedule_ambient_revert(event, snapshot, revert, ambient_vids)
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

    async def _execute_plan_entry(self, entry: _PlanEntry) -> None:
        """Execute one plan entry at its scheduled time."""
        if state.paused:
            return
        evt = entry.event
        skip_ids = entry.planned_descendant_ids or None
        # If this is the root entry and pre-commands were fired by the
        # look-ahead path (_pre_fired set), skip them inside the sequence
        # so step 0 fires immediately instead of awaiting brightness ramps.
        skip_pc = entry.is_root and entry.trigger_id in self._pre_fired
        # Await the look-ahead pre-commands task if one is still running for
        # this trigger. Without this await, the sequence's first effect PUT
        # can reach LedFX before the transition PUT (both go through the same
        # httpx pool concurrently), making the transition silently not apply.
        if skip_pc:
            _pc_task = self._pre_cmd_tasks.pop(entry.trigger_id, None)
            if _pc_task is not None and not _pc_task.done():
                try:
                    await _pc_task
                except Exception:
                    pass
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
                skip_pre_commands=skip_pc,
                precomputed_snapshot=snap,
            )
        elif evt.event_type == "beat_sequence":
            # fire_at_ms is already the anchor, computed with compounded offsets.
            await self._execute_beat_sequence(
                evt, entry.fire_at_ms, entry.labels,
                skip_event_ids=skip_ids,
                anchor_override_ms=entry.fire_at_ms,
                skip_pre_commands=skip_pc,
                precomputed_snapshot=snap,
            )

    async def _execute_beat_sequence(
        self,
        event: MusicEvent,
        trigger_ms: int,
        labels: list[str],
        step1_prefired: bool = False,
        skip_event_ids: set[str] | None = None,
        anchor_override_ms: int | None = None,
        skip_pre_commands: bool = False,
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
            ramp_ms = 0
            if resolved:
                # Respect ramp_ms=0 (instant) — only fall back to smooth_ramp_ms
                # when the field is None. The previous `or` coerced 0 to the
                # fallback, inflating the inter-step safety pad by ~500ms.
                ramp_ms = max(
                    (a.ramp_ms if getattr(a, "ramp_ms", None) is not None else settings.smooth_ramp_ms)
                    for a in resolved
                )

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

        # Snapshot BEFORE pre-commands so revert restores the true pre-event state.
        # _snapshot_for_revert itself warms any missing target-virtual cache entries
        # concurrently, so no separate sequential refresh is needed.
        snapshot: dict = {}
        if revert and revert.enabled:
            if precomputed_snapshot is not None:
                snapshot = precomputed_snapshot
            else:
                snapshot = await self._snapshot_for_revert(event)
        if not skip_pre_commands:
            await self._apply_pre_commands(event, labels)

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
                    self._pre_ramp_fired -= re_enabled
                    for tid in re_enabled:
                        self._preselected.pop(tid, None)
                        self._preselected_steps.pop(tid, None)
                        for _e in self._plan.get(tid, []):
                            if _e.snapshot_task and not _e.snapshot_task.done():
                                _e.snapshot_task.cancel()
                        self._plan.pop(tid, None)
                        self._plan_desc.pop(tid, None)
                        self._pre_cmd_tasks.pop(tid, None)
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
                    self._pre_cmd_tasks.pop(_t.id, None)
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
                        plan, desc = self._plan_timeline(event, next_t, list(next_t.labels))
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
                            "locked":       False,
                        }))

            # ─────────────────────────────────────────────────────────────────

            if not state.paused:
                # Brightness ramp look-ahead — starts ramp at T - lead_ms - ramp_ms
                # Skip in dinner party mode (DP scenes handle their own brightness)
                if not state.dinner_party_mode:
                    for trigger in self._get_active_triggers():
                        if not trigger.enabled or trigger.id in self._fired or trigger.id in self._pre_ramp_fired:
                            continue
                        event = get_event(trigger.event_id)
                        if not event or event.event_type != "single" or not event.pre_brightness_enabled:
                            continue
                        ramp_ms = event.pre_brightness_ramp_ms if event.pre_brightness_ramp_ms is not None \
                                  else settings.smooth_ramp_ms
                        if ramp_ms <= 0:
                            continue
                        lead_ms = settings.pre_brightness_lead_ms
                        if trigger.timestamp_ms - lead_ms - ramp_ms <= effective_now:
                            self._pre_ramp_fired.add(trigger.id)
                            self._spawn_ramp(ledfx_client.ramp_brightness(event.pre_brightness_value, ramp_ms))

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

                    # Pre-command look-ahead: fire brightness/transition lead_ms before main trigger.
                    # Now applies to all event types — for sequence/beat_sequence we use the
                    # plan's root fire_at_ms (which already accounts for cumulative offsets) so
                    # pre-commands finish before step 0 and don't block its fire.
                    for trigger in self._get_active_triggers():
                        if not trigger.enabled or trigger.id in self._fired or trigger.id in self._pre_fired:
                            continue
                        event = get_event(trigger.event_id)
                        if not event:
                            continue
                        lead_ms = max(
                            settings.pre_brightness_lead_ms if event.pre_brightness_enabled else 0,
                            settings.pre_transition_lead_ms if event.pre_transition_enabled else 0,
                        )
                        if lead_ms <= 0:
                            continue
                        # For sequence/beat_sequence prefer the plan's root fire_at_ms so
                        # pre-commands land relative to the actual (offset-adjusted) start.
                        anchor_ms = trigger.timestamp_ms
                        _plan_entries = self._plan.get(trigger.id) or []
                        for _e in _plan_entries:
                            if _e.event.id == trigger.event_id:
                                anchor_ms = _e.fire_at_ms
                                break
                        _delta = anchor_ms - lead_ms - effective_now
                        if _delta <= 0:
                            logger.info(
                                "Pre-cmd look-ahead: trigger=%s event='%s' type=%s pt_en=%s pb_en=%s lead=%d anchor=%d eff_now=%d delta=%d",
                                trigger.id, event.name, event.event_type,
                                event.pre_transition_enabled, event.pre_brightness_enabled,
                                lead_ms, anchor_ms, effective_now, _delta,
                            )
                            self._pre_fired.add(trigger.id)
                            _pc_task = asyncio.create_task(
                                self._fire_pre_commands(event, trigger.id, trigger.labels)
                            )
                            self._pre_cmd_tasks[trigger.id] = _pc_task

                # ── Fire plan entries whose time has come ─────────────────
                # Each entry is an atomic fire computed by _plan_timeline with
                # compounded event_offset_ms. The root entry of each trigger
                # also emits the trigger_fired WS broadcast so the UI clears
                # the preview and shows the flash animation.
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
                        if _entry.fire_at_ms <= effective_now:
                            _entry.fired = True
                            _is_root = (_entry.event.id == _trigger.event_id)
                            logger.info(
                                "Plan fire: %s at ~%dms (trigger=%s, %s, plan_offset=%+dms)",
                                _entry.event.name, now_ms, _tid,
                                "root" if _is_root else "child",
                                _entry.fire_at_ms - _trigger.timestamp_ms,
                            )
                            asyncio.create_task(self._execute_plan_entry(_entry))
                            if _is_root:
                                asyncio.create_task(
                                    ws_manager.broadcast_trigger_fired(
                                        _tid, _entry.event.name, _entry.event.color,
                                        scheduled_ms=_trigger.timestamp_ms,
                                        fired_at_ms=now_ms,
                                        effective_offset_ms=offset,
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
                    if trigger.timestamp_ms <= effective_now:
                        self._fired.add(trigger.id)
                        logger.info(
                            "Firing unplanned trigger %s at ~%dms (event=%s)",
                            trigger.id, now_ms, trigger.event_id,
                        )
                        asyncio.create_task(self._fire_trigger(
                            trigger, fired_at_ms=now_ms, effective_offset_ms=offset
                        ))

