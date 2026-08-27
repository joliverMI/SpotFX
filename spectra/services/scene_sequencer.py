"""SPECTRA scene sequencer engine — the spot-effects port, semantics
unchanged (decision-complete per the five answered holds), re-homed on
SPECTRA's stores with two deliberate S1 differences:

  1. The wheel position is SHARED ROOM-COLOUR STATE (storage/spectra/
     room_color.json via services/color_journey), no longer sequencer-private
     — creep, jumps, and the selector's travel factor all read one truth
     (a named change in the accepted design).
  2. The music feed IS the S2 read-only bridge (services/bridge): song
     transitions tick on_track_state(), intensity is section energy at the
     playback position (0.5 neutral when the bridge or analysis is absent —
     stated degradation), genre buckets come from the training profiles,
     deferrals from the broadcast flags + the settings poll, and
     trigger-fired scenes are observed via last_scene_id. enabled stays
     False by default regardless (its own dark switch) — feeding the engine
     is not enabling it.

Change moments: SONG TRANSITIONS ONLY (decision 5, binding) — the pluggable
ChangeMomentSource seam ports verbatim; no timer, ever, without the owner's
call. ACCEPTED CONSEQUENCE on record: a long mix holds one scene however
hard it builds; drift (S2) softens that without touching the clock.

Fires resolve bindings at the moment's intensity and go through
scene_compiler.fire_scene(dry_run=False) — scene + colour set in ONE compile.
That fire-time intensity is the RAW kernel-selection value scaled by the
current song's genre+bass factor (spectra/services/intensity_scale.py,
_default_render_intensity) — SELECTION (kernel.select/select_color_set,
above) stays on the raw value so genre isn't double-counted there.

Executable spec: scripts/check_spectra.py (fake clock, injected fire — no
live LedFX, no audio).

MINIMUM DWELL (2026-08-20, data/plan-make-dwell-meaningful-under-the-rea-
4p73/): dwell no longer lives here at all — SelectorEntry.dwell_weight and
this class's own served_songs/dwell_target song-count bookkeeping are
retired. The new per-scene, seconds-not-songs minimum lives in spectra/
services/dwell.py and gates centrally at fire_scene_by_id, below — see
that module's docstring for why (it was built on the wrong reading of
"song transition": between songs, not within a song or a trigger call,
which is the path his real triggers actually use). This class's own
_active_id remains, unchanged in purpose, purely for candidate-building
(prev_id for affinity, the "renewed" comparison in _roll).
"""
from __future__ import annotations

import logging
import time
from random import Random
from typing import Any, Awaitable, Callable, Optional

from spectra.models.sequencer import CurvePoint, SequencerConfig
from spectra.services import selection_kernel as kernel
from spectra.services import sequencer_store

logger = logging.getLogger(__name__)

TRANSITION_SOURCE = "transition"

# Reported in place of a selection_kernel rung when the colour-set pool is
# EMPTY before the kernel is even consulted (every set disabled/gated out).
# The outcome is identical to the kernel's own TERMINAL_KEEP — the room
# keeps its colours — but the CAUSE is different and worth naming.
POOL_EXHAUSTED = "pool_exhausted"

# The colour-pick rung reported when FORCE COLOUR (owner ask 2026-08-27,
# spectra/services/force_color.py) is what stopped the roll — the room's
# colour is pinned, so no selection ran at all. Distinct from
# TERMINAL_KEEP/POOL_EXHAUSTED (which mean "the kernel ran and kept") for
# exactly the reason those two are distinct from each other: same outcome,
# different cause, and the cause is what he needs to see.
FORCED_COLOR = "forced_color"


async def fire_scene_by_id(scene_id: str,
                           color_set_id: Optional[str] = None,
                           intensity: float = 0.5) -> dict:
    """The ONE scene-fire choke point for anything that picks a scene by id
    outside the editor's own test-fire — the sequencer's own rolls and
    SPECTRA-native triggers (spectra.services.trigger_engine) both call
    this, so "fire scene X" means exactly one thing everywhere it happens.

    Force Scene (room_controls.RoomControlState.force_scene_enabled/
    force_scene_scene_id, the legacy Now Playing control ported verbatim)
    redirects scene_id here — the single interception point every automatic
    pick already funnels through. Only the scene is pinned; color_set_id/
    intensity pass through as the caller resolved them, same as legacy's
    "reassert with normal First/Rest." A forced id pointing at a missing
    scene is treated as unset (falls through to the requested scene).

    FORCE COLOUR (owner ask 2026-08-27, spectra/services/force_color.py —
    read that module's docstring for the gates and precedence) is Force
    Scene's twin one axis over, and lands HERE too, on the other half of
    the same call: while a colour pin is enabled, the pinned SET/GROUP
    replaces whatever colour set this caller resolved (a sequencer roll's
    pick, a trigger's authored color_set_id, or nothing at all), and the
    result carries forced_color=<id> so the fire says it wore the pin. The
    two pins are independent: either, both, or neither can be on, and
    neither reads the other's fields.

    Temporary disable (SceneV2.disabled, owner ask 2026-08-18) is gated
    HERE FIRST, ahead of mode availability below — it is the stronger,
    more explicit statement ("don't use this scene, period" vs. "not in
    this room mode"), so a scene that is both disabled and mode-gated
    reports skipped="disabled", not "mode_availability". Same bypass as
    availability: Force Scene pinning it keeps its declared life. But a
    pin that lands on a disabled scene is contradictory input from him —
    honour the pin (he pressed it, he means it) but NAME the override:
    the result carries overrode_disabled=True rather than silently
    proceeding, so room_controls.reconcile_force_scene_if_changed can
    surface it on the Force Scene badge.

    Mode availability (spectra/services/mode_availability.py, owner ask
    2026-08-17) is also gated HERE, once, for both callers: a scene whose
    own display_availability excludes the room's current display_mode is
    skipped (result carries skipped="mode_availability") UNLESS Force Scene
    just pinned it — an explicit pin keeps its declared life, same as it
    already does for pause/dinner_party/ambient. A resolved colour set/
    group member failing its own availability check falls back to the
    room's active set, same as an unresolved/unknown color_set_id already
    does.

    MINIMUM DWELL (2026-08-20, spectra/services/dwell.py — read that
    module's docstring for the full mechanism) is gated HERE, after
    disabled/mode-availability, before the colour set even resolves (a
    deferred request must never advance a Colour Group's own rotation
    cursor for a fire that never happens): if the room's currently-active
    scene hasn't yet cleared its own latched minimum hold, the request is
    deferred — result carries skipped="dwell" plus remaining_dwell_s and
    update_result (what the update-effect seam did, see below) — UNLESS
    Force Scene just pinned this scene, which fires anyway but NAMES the
    override (overrode_dwell=True), same "an explicit pin always wins, but
    say so" pattern as overrode_disabled above. A deferred request calls
    engine.fire_scene_update_event(intensity) — the SAME choke point a
    fire_scene_update trigger action already uses — INSTEAD of compiling
    and firing the requested scene; that seam (scene_response.ResponseEngine.
    on_update, a 2026-08-20 placeholder) fires the current scene's own
    "flare" response at double intensity — degrading to the same "no flare
    response/bands declared" no-op only a scene with no flare material at
    all would hit — recorded (never silent) to fire_history's "deferred"
    bucket rather than the "scenes" bucket below.
    Every real (non-deferred) fire re-latches dwell.note_fired for the
    scene that just started showing — the ONE place dwell's own "current
    scene" state updates, which is what keeps it from going stale the way
    the old sequencer-local dwell bookkeeping did on a trigger fire.

    PREVIEW HOLD (2026-08-21, fm/preview-must-hold-scene-changes) is gated
    FIRST, ahead of every other check including Force Scene — the one gate
    in this function Force Scene does NOT override, matching preview_pause's
    own documented precedence at bridge.py's conductor_deferral/
    sequencer_deferral (preview outranks force_scene there too): a hand-held
    preview is the most explicit, momentary override a room can be under,
    and a Force Scene reassert landing on top of the exact flare he opened
    the preview to judge would defeat the preview's whole purpose. Recorded
    to fire_history's "deferred" bucket like the dwell case, but never fires
    an update effect — dwell's placeholder flare exists to make an
    otherwise-invisible hold visible; a preview's whole point is an
    isolated, motionless room, so adding motion here would fight the thing
    he opened the preview to see."""
    from spectra.services import (color_set_groups, color_sets, dwell,
                                  fire_history, force_color, mode_availability,
                                  preview_pause, scene_compiler, scene_store)
    from spectra.services.room_controls import load_room_controls
    if preview_pause.active():
        scene = scene_store.get_by_id(scene_id)
        scene_name = scene.name if scene is not None else scene_id
        fire_history.record_fire("deferred", scene_id, {
            "scene_name": scene_name,
            "reason": "preview",
        })
        return {"skipped": "preview", "scene_id": scene_id,
               "scene_name": scene_name}
    controls = load_room_controls()
    forced = False
    if controls.force_scene_enabled and controls.force_scene_scene_id:
        if scene_store.get_by_id(controls.force_scene_scene_id) is not None:
            scene_id = controls.force_scene_scene_id
            forced = True
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise ValueError(f"scene {scene_id} not found in spectra scenes")
    overrode_disabled = forced and getattr(scene, "disabled", False)
    if not forced and getattr(scene, "disabled", False):
        return {"skipped": "disabled", "scene_id": scene_id,
               "scene_name": scene.name}
    if not forced and not mode_availability.available_in_room_mode(
            getattr(scene, "display_availability", "default"), controls.display_mode):
        return {"skipped": "mode_availability", "scene_id": scene_id,
               "scene_name": scene.name}
    remaining_dwell = dwell.remaining_s()
    overrode_dwell = forced and remaining_dwell > 0
    if not forced and remaining_dwell > 0:
        from spectra.services.engine import fire_scene_update_event
        update_result = await fire_scene_update_event(intensity)
        fire_history.record_fire("deferred", scene_id, {
            "scene_name": scene.name,
            "remaining_dwell_s": round(remaining_dwell, 1),
            "update_result": (update_result or {}).get("result"),
        })
        return {"skipped": "dwell", "scene_id": scene_id, "scene_name": scene.name,
               "remaining_dwell_s": round(remaining_dwell, 1),
               "update_result": update_result}
    # FORCE COLOUR (owner ask 2026-08-27, spectra/services/force_color.py):
    # the pin replaces whatever colour this caller resolved — a sequencer
    # roll's pick, a trigger's authored color_set_id, or nothing at all.
    # Resolved ONCE here, per fire, which is also what advances a pinned
    # GROUP's own rotation exactly once per fire. A pin that fails to
    # resolve (deleted card, group with no usable member) falls through to
    # the caller's own choice rather than leaving the fire colourless —
    # the same degrade-gracefully posture an unknown color_set_id has.
    forced_color = force_color.pinned_card(controls)
    if forced_color is not None:
        color_set = forced_color
        color_set_id = forced_color.id
    else:
        color_set = color_sets.get_by_id(color_set_id) if color_set_id else None
        if color_set is not None:
            # A Group reference resolves to its picked member here (§10) — a
            # missing/unusable/mode-unavailable one falls back to the room's
            # active set below, same as an unknown plain set id already did.
            color_set = color_set_groups.resolve_for_fire_mode_gated(
                color_set, controls.display_mode)
    result = await scene_compiler.fire_scene(scene, intensity=intensity,
                                             color_set=color_set, dry_run=False)
    if overrode_disabled:
        result["overrode_disabled"] = True
    if overrode_dwell:
        result["overrode_dwell"] = True
    if forced_color is not None:
        # NAMED, not silent: this fire wore the pinned colours, not the
        # ones its caller resolved.
        result["forced_color"] = forced_color.id
    dwell.note_fired(scene, intensity)
    fire_history.record_fire("scenes", scene_id, {
        "scene_name": getattr(scene, "name", scene_id),
        "color_set_id": color_set_id,
        "intensity": intensity,
    })
    return result


class ChangeMomentSource:
    """The pluggable clock seam. A source decides WHEN a change moment
    exists; the engine decides what the moment means. Shipped:
    TransitionSource only — a later owner-approved TimedSource binds the
    same way and needs no engine rework."""

    name = "unset"

    def bind(self, emit: Callable[[str], Awaitable[None]]) -> None:
        self._emit = emit

    async def _fire(self) -> None:
        await self._emit(self.name)


class TransitionSource(ChangeMomentSource):
    """Song transitions: a moment each time the playing URI changes to a new
    one. The first URI seen after startup only ARMS the source — a restart
    mid-song must not change the room mid-song. Stop/None holds the last
    URI, so pause→resume of the same song is not a transition."""

    name = TRANSITION_SOURCE

    def __init__(self) -> None:
        self._last_uri: Optional[str] = None

    async def observe_uri(self, uri: Optional[str]) -> None:
        if uri is None or uri == self._last_uri:
            return
        armed = self._last_uri is not None
        self._last_uri = uri
        if armed:
            await self._fire()


class SceneSequencer:
    """One instance per process (singleton below). Constructor injectables
    exist for the executable spec only — production uses the defaults."""

    def __init__(
        self, *,
        rng: Random | None = None,
        fire: Callable[..., Awaitable[Any]] | None = None,
        intensity: Callable[[], float] | None = None,
        render_intensity: Callable[[float], float] | None = None,
        genre_bucket: Callable[[], Optional[str]] | None = None,
        deferral_fn: Callable[[], Optional[str]] | None = None,
        trigger_scene_id: Callable[[], Optional[str]] | None = None,
        list_scene_ids: Callable[[], set[str]] | None = None,
        scene_name: Callable[[str], str] | None = None,
        broadcast: Callable[[dict], Awaitable[None]] | None = None,
        eligible_sets: Callable[[str], dict[str, Optional[float]]] | None = None,
        color_set_name: Callable[[str], str] | None = None,
        wheel_get: Callable[[], Optional[float]] | None = None,
        wheel_set: Callable[[Optional[float]], None] | None = None,
        scene_mode_available: Callable[[str], bool] | None = None,
        scene_enabled: Callable[[str], bool] | None = None,
        group_ids_by_set: Callable[[], dict[str, list[str]]] | None = None,
    ) -> None:
        self._rng = rng or Random()
        self._fire = fire or self._default_fire
        self._intensity = intensity or self._default_intensity
        self._render_intensity = render_intensity or self._default_render_intensity
        self._genre_bucket = genre_bucket or self._default_genre_bucket
        self._deferral = deferral_fn or self._default_deferral
        self._trigger_scene_id = trigger_scene_id or self._default_trigger_scene_id
        self._list_scene_ids = list_scene_ids or self._default_list_scene_ids
        self._scene_name = scene_name or self._default_scene_name
        self._broadcast = broadcast or self._default_broadcast
        # scene_id → {set_id: wheel position_deg | None} for every existing
        # colour set the scene accepts (two-way filter applied).
        self._eligible_sets = eligible_sets or self._default_eligible_sets
        self._color_set_name = color_set_name or self._default_color_set_name
        # Shared room-colour truth (the design's named change).
        self._wheel_get = wheel_get or self._default_wheel_get
        self._wheel_set = wheel_set or self._default_wheel_set
        self._scene_mode_available = scene_mode_available or self._default_scene_mode_available
        # Temporary disable (owner ask 2026-08-18) — a SEPARATE gate from
        # mode availability above (see SceneV2.disabled's own docstring for
        # why they're kept distinct rather than folded together).
        self._scene_enabled = scene_enabled or self._default_scene_enabled
        # set_id → every Colour Group card id that lists it as a member —
        # the reverse lookup the group-curve multiplicand needs (kernel
        # stays pure; this is the one place colour-set storage is read for it).
        self._group_ids_by_set = group_ids_by_set or self._default_group_ids_by_set

        self.transition_source = TransitionSource()
        self.transition_source.bind(self._on_change_moment)

        # Runtime state — in-memory only, rebuilt from the room after restart.
        # _active_id is this instance's own belief for candidate-building
        # (prev_id for affinity, the "renewed" comparison below) — the
        # MINIMUM DWELL gate itself lives centrally in spectra/services/
        # dwell.py, fed by fire_scene_by_id directly, not this field (see
        # that module's docstring for why: this field only updates from a
        # roll or an observed legacy trigger fire, so a SPECTRA-native
        # trigger fire would go stale here the same way it always did —
        # dwell.py structurally cannot have that problem).
        self._active_id: Optional[str] = None
        self._seen_trigger_scene_id: Optional[str] = None
        self._last_pick: Optional[dict] = None
        self._last_moment: Optional[dict] = None
        self._warned_change_mode: Optional[str] = None
        self._active_color_set_id: Optional[str] = None
        self._last_color_pick: Optional[dict] = None

    # ── feed (the S2 bridge calls this on every state broadcast) ────────────

    async def on_track_state(self, uri: Optional[str]) -> None:
        await self.transition_source.observe_uri(uri)

    # ── the moment ──────────────────────────────────────────────────────────

    async def _on_change_moment(self, source: str) -> None:
        config = sequencer_store.load_config()
        if not config.enabled:
            return
        if config.change_mode != "transition" and \
                self._warned_change_mode != config.change_mode:
            self._warned_change_mode = config.change_mode
            logger.warning(
                "sequencer change_mode=%s stored, but only the transition "
                "clock ships (decision 5) — ticking song transitions only",
                config.change_mode)

        deferral = self._deferral()
        if deferral is not None:
            self._record_moment(source, f"deferred:{deferral}")
            return

        # MINIMUM DWELL (spectra/services/dwell.py) no longer gates here —
        # it gates centrally at fire_scene_by_id, which every real fire
        # below (self._fire) already funnels through, so a roll that picks
        # a different scene too soon is simply converted into an update
        # effect downstream rather than held back from being tried at all.
        self._observe_trigger_fires(config)
        await self._roll(config, source)

    def _observe_trigger_fires(self, config: SequencerConfig) -> bool:
        """Observe (never drive) the legacy engine through the bridge: a new
        trigger-fired scene id since the last enabled moment updates this
        instance's own "current scene" belief (prev_id for affinity). The
        first enabled moment only baselines."""
        seen = self._trigger_scene_id() or None
        if self._seen_trigger_scene_id is None:
            self._seen_trigger_scene_id = seen or ""
            return False
        if seen and seen != self._seen_trigger_scene_id:
            self._seen_trigger_scene_id = seen
            self._adopt(seen)
            logger.info("sequencer: adopted trigger-fired scene %s", seen)
            return True
        return False

    def _adopt(self, scene_id: str) -> None:
        self._active_id = scene_id

    async def _roll(self, config: SequencerConfig, source: str) -> None:
        curves = sequencer_store.load_curves()
        existing = self._list_scene_ids()
        missing = set(config.entries) - existing
        if missing:
            logger.warning("sequencer: %d entr(y/ies) reference no scene "
                           "and are skipped: %s", len(missing), sorted(missing))
        intensity = self._intensity()
        genre_bucket = self._genre_bucket()
        # Mode availability (owner ask 2026-08-17) and temporary disable
        # (owner ask 2026-08-18): a scene marked light/dark-only, or
        # disabled outright, is dropped from the candidate pool, not just
        # vetoed at fire time, so the ladder's fallback rungs see a
        # truthful pool instead of wasting a pick on something
        # fire_scene_by_id would skip anyway.
        available = {sid for sid in existing
                    if self._scene_mode_available(sid) and self._scene_enabled(sid)}
        candidates = kernel.build_scene_candidates(
            config.entries, curves, config.affinity,
            genre_bucket=genre_bucket, prev_id=self._active_id,
            restrict_ids=available)
        pick = kernel.select(candidates, intensity=intensity,
                             rng=self._rng, current_id=self._active_id,
                             terminal=kernel.TERMINAL_STAY)
        self._last_pick = {
            "picked_id": pick.picked_id,
            "picked_name": self._scene_name(pick.picked_id) if pick.picked_id else None,
            "rung": pick.rung,
            "intensity": round(pick.intensity, 4),
            "factors": pick.factors,
            "source": source,
            "at": time.time(),
        }
        if pick.picked_id is None:
            self._record_moment(source, "stay")
            logger.info("sequencer: ladder terminated at STAY (intensity %.2f)",
                        pick.intensity)
            return
        if pick.picked_id == self._active_id:
            # Only reachable via the re-admit/uniform rungs. The room
            # already shows this scene — nothing to fire.
            self._adopt(pick.picked_id)
            self._record_moment(source, "renewed")
            logger.info("sequencer: current scene %s renewed via rung=%s",
                        pick.picked_id, pick.rung)
            return
        color = self._roll_color_set(config, curves, pick.picked_id,
                                     intensity, genre_bucket)
        try:
            # SELECTION (kernel.select/select_color_set above) stayed on the
            # RAW intensity — genre_mult already factors genre into the
            # pick. The FIRE itself gets the current song's genre+bass
            # render scale on top (intensity_scale.py), same split trigger_
            # engine.py's own _fire/_fire_transition make.
            fire_result = await self._fire(pick.picked_id,
                                           color["fire_set_id"] if color else None,
                                           self._render_intensity(intensity))
        except Exception:
            logger.exception("sequencer: firing scene %s failed", pick.picked_id)
            self._record_moment(source, "fire_failed")
            return
        if isinstance(fire_result, dict) and "skipped" in fire_result:
            # MINIMUM DWELL (or any other fire_scene_by_id gate) declined
            # the fire — the room's active scene never changed, so this
            # instance's own "current scene" belief must not move either
            # (adopting the un-fired pick here would desync prev_id/
            # affinity from what's actually showing, the exact staleness
            # dwell.py's own docstring exists to avoid).
            self._record_moment(source, f"skipped:{fire_result['skipped']}")
            logger.info("sequencer: kernel picked %s but fire_scene_by_id "
                        "declined it (%s) — active scene unchanged",
                        pick.picked_id, fire_result["skipped"])
            return
        self._adopt(pick.picked_id)
        if color is not None:
            self._adopt_colors(color)
        self._record_moment(source, "picked")
        logger.info("sequencer: picked %s via rung=%s at intensity %.2f",
                    pick.picked_id, pick.rung, pick.intensity)
        await self._broadcast({
            "type": "sequencer_pick",
            **self._last_pick,
            "color": self._last_color_pick if color is not None else None,
        })

    # ── the colour-set selector (colours change with scenes) ────────────────

    def _roll_color_set(self, config: SequencerConfig, curves: dict,
                        scene_id: str, intensity: float,
                        genre_bucket: Optional[str]) -> Optional[dict]:
        """Roll the colour-set selector for the scene about to fire. None =
        selector unconfigured. A TERMINAL_KEEP pick fires the CURRENT set so
        the new scene keeps the room's palette — never forced to churn."""
        if not config.color_set_entries:
            return None
        from spectra.services import force_color
        # FORCE COLOUR (spectra/services/force_color.py): the pin governs,
        # so rolling here would be pure churn — worse than pointless,
        # since _adopt_colors would move the room's WHEEL POSITION to a
        # set that is never going to be worn, silently re-anchoring the
        # colour journey that resumes when he releases the pin. Reported
        # with its own rung so the status strip's "last colour pick"
        # breakdown says WHY nothing rolled instead of going blank.
        # active() (not pinned_card()) deliberately: this runs on every
        # roll and must never advance a pinned Group's rotation cursor —
        # fire_scene_by_id does that once, at the fire itself.
        if force_color.active():
            return {
                "picked_id": None,
                "fire_set_id": self._active_color_set_id,
                "position_deg": None,
                "record": {
                    "picked_id": None,
                    "picked_name": None,
                    "kept_set_id": self._active_color_set_id,
                    "rung": FORCED_COLOR,
                    "factors": {},
                    "forced_color_id": force_color.pinned_id(),
                },
            }
        eligible = self._eligible_sets(scene_id)
        if not eligible:
            # POOL EXHAUSTED — every set is currently ineligible (disabled,
            # mode-gated, scene-rejected, or rainbow-partitioned out at
            # this intensity). The kernel would reach TERMINAL_KEEP on its
            # own and the room would simply keep its colours, which is the
            # right OUTCOME (a room is never left with nothing) but a
            # silent one: he could disable every rainbow set and never
            # learn why colours stopped rolling above the rainbow limit.
            # So it is named here, on the same status/pick-factors surface
            # every other colour pick reports through.
            diag = self._pool_diagnostic()
            logger.warning(
                "colour-set pool EXHAUSTED at intensity %.2f — nothing "
                "eligible (%d of %d sets disabled); keeping the room's "
                "current colours", intensity, diag["disabled"], diag["sets"])
            return {
                "picked_id": None,
                "fire_set_id": self._active_color_set_id,
                "position_deg": None,
                "record": {
                    "picked_id": None,
                    "picked_name": None,
                    "kept_set_id": self._active_color_set_id,
                    "rung": POOL_EXHAUSTED,
                    "factors": {},
                    "pool_exhausted": True,
                    "pool": diag,
                },
            }
        wheel_profile = (curves.get(config.wheel_travel_curve)
                         if config.wheel_travel_curve else None)
        wheel_points = (wheel_profile.points if wheel_profile
                        else [CurvePoint(x=0.0, y=1.0)])   # no curve ≡ neutral
        candidates = kernel.build_color_set_candidates(
            config.color_set_entries, curves,
            genre_bucket=genre_bucket, room_deg=self._wheel_get(),
            set_positions=eligible, wheel_points=wheel_points,
            group_ids_by_set=self._group_ids_by_set())
        pick = kernel.select_color_set(candidates, intensity=intensity,
                                       rng=self._rng,
                                       current_id=self._active_color_set_id)
        picked = pick.picked_id
        fire_set_id = picked if picked is not None else self._active_color_set_id
        return {
            "picked_id": picked,
            "fire_set_id": fire_set_id,
            "position_deg": eligible.get(picked) if picked is not None else None,
            "record": {
                "picked_id": picked,
                "picked_name": (self._color_set_name(picked)
                                if picked is not None else None),
                "kept_set_id": None if picked is not None else fire_set_id,
                "rung": pick.rung,
                "factors": pick.factors,
            },
        }

    def _pool_diagnostic(self) -> dict:
        """Best-effort counts for an exhausted colour pool: how many "set"
        cards exist and how many of them he has DISABLED — the one cause
        of exhaustion he can act on directly. Never raises: an injected
        fake/absent storage reports zeros rather than breaking a roll."""
        try:
            from spectra.services import color_sets
            cards = [c for c in color_sets.list_all() if c.kind == "set"]
            return {"sets": len(cards),
                    "disabled": sum(1 for c in cards
                                    if getattr(c, "disabled", False)),
                    "eligible": 0}
        except Exception:
            return {"sets": 0, "disabled": 0, "eligible": 0}

    def _adopt_colors(self, color: dict) -> None:
        """Commit colour state AFTER a successful fire. Rainbow/achromatic
        picks (position None) move the active set but leave the room's wheel
        position where the last chromatic set put it — the binding rule."""
        self._last_color_pick = color["record"]
        if color["picked_id"] is not None:
            self._active_color_set_id = color["picked_id"]
            if color["position_deg"] is not None:
                self._wheel_set(color["position_deg"])
        self._last_color_pick["wheel_position_deg"] = self._wheel_get()

    def _record_moment(self, source: str, result: str) -> None:
        self._last_moment = {"source": source, "result": result, "at": time.time()}

    # ── observability (GET /spectra/api/sequencer/status) ───────────────────

    def status(self) -> dict:
        from spectra.services import dwell
        config = sequencer_store.load_config()
        return {
            "enabled": config.enabled,
            "change_mode": config.change_mode,
            "next_change_source": TRANSITION_SOURCE,  # the only shipped clock
            "deferred_by": self._deferral(),
            "bridge_connected": self._bridge_connected(),
            "active_scene_id": self._active_id,
            "active_scene_name": (self._scene_name(self._active_id)
                                  if self._active_id else None),
            # Minimum dwell (spectra/services/dwell.py) is process-global —
            # fed by EVERY real fire (sequencer, trigger, automatic
            # transition), not just this instance's own rolls — so this is
            # the shared gate's own status, not derived from _active_id
            # above (which can legitimately differ, e.g. right after a
            # trigger fired a scene this instance hasn't observed yet).
            "dwell": dwell.status(),
            "last_pick": self._last_pick,
            "last_moment": self._last_moment,
            "color": {
                "active_set_id": self._active_color_set_id,
                "active_set_name": (self._color_set_name(self._active_color_set_id)
                                    if self._active_color_set_id else None),
                "wheel_position_deg": self._wheel_get(),
                "last_pick": self._last_color_pick,
            },
        }

    # ── production defaults (lazy imports; the spec injects fakes) ──────────

    async def _default_fire(self, scene_id: str,
                            color_set_id: Optional[str] = None,
                            intensity: float = 0.5) -> dict:
        return await fire_scene_by_id(scene_id, color_set_id, intensity)

    def _default_eligible_sets(self, scene_id: str) -> dict[str, Optional[float]]:
        from spectra.services import (color_sets, color_wheel,
                                      mode_availability, rainbow_select,
                                      scene_store)
        from spectra.services.room_controls import load_room_controls
        scene = scene_store.get_by_id(scene_id)
        room = load_room_controls()
        room_mode = room.display_mode
        preference = getattr(scene, "preferred_color_set_mode", "default") if scene else "default"
        intensity = self._intensity()
        out: dict[str, Optional[float]] = {}
        for card in color_sets.list_all():
            if card.kind != "set":
                continue
            # DISABLED (owner ask 2026-08-25) — checked first and
            # independent of room mode, the same order fire_scene_by_id
            # applies to a disabled SCENE. A disabled set simply stops
            # being chosen; it is never yanked out of the room mid-paint
            # (scene_compiler.room_active_set, the terminal fallback,
            # deliberately does not check this).
            if getattr(card, "disabled", False):
                continue
            if scene is not None and not scene.accepts_color_set(card):
                continue
            if not mode_availability.available_in_room_mode(
                    card.display_availability, room_mode):
                continue
            if not mode_availability.color_set_preferred(
                    card.display_availability, preference, room_mode):
                continue
            if not rainbow_select.eligible(card.is_rainbow, intensity,
                                           room.rainbow_select_limit):
                continue
            out[card.id] = color_wheel.wheel_position(card).position_deg
        return out

    def _default_group_ids_by_set(self) -> dict[str, list[str]]:
        from spectra.services import color_set_groups
        return color_set_groups.group_ids_by_set()

    def _default_scene_mode_available(self, scene_id: str) -> bool:
        from spectra.services import mode_availability, scene_store
        from spectra.services.room_controls import load_room_controls
        scene = scene_store.get_by_id(scene_id)
        if scene is None:
            return True
        return mode_availability.available_in_room_mode(
            scene.display_availability, load_room_controls().display_mode)

    def _default_scene_enabled(self, scene_id: str) -> bool:
        from spectra.services import scene_store
        scene = scene_store.get_by_id(scene_id)
        if scene is None:
            return True
        return not getattr(scene, "disabled", False)

    def _default_color_set_name(self, set_id: str) -> str:
        from spectra.services import color_sets
        card = color_sets.get_by_id(set_id)
        return card.name if card else set_id

    def _default_intensity(self) -> float:
        # Bridge feed: section energy at position; 0.5 neutral when absent
        # (stated degradation).
        from spectra.services.engine import bridge
        value = bridge.intensity()
        return value if value is not None else 0.5

    def _default_render_intensity(self, raw: float) -> float:
        # See trigger_engine._default_render_intensity's docstring — same
        # seam, same rationale (spectra/services/intensity_scale.py).
        from spectra.services import intensity_scale
        from spectra.services.engine import bridge
        return intensity_scale.combine_measured_and_scale(
            raw, bridge.song_scaling_factor())

    def _default_genre_bucket(self) -> Optional[str]:
        from spectra.services.engine import bridge
        return bridge.genre_bucket()

    def _default_deferral(self) -> Optional[str]:
        # Force Scene / pause / Dinner Party / Ambient, read off the bridge.
        from spectra.services.engine import bridge
        return bridge.sequencer_deferral()

    def _default_trigger_scene_id(self) -> Optional[str]:
        from spectra.services.engine import bridge
        return bridge.trigger_scene_id()

    def _bridge_connected(self) -> bool:
        from spectra.services.engine import bridge
        return bridge.connected

    def _default_list_scene_ids(self) -> set[str]:
        from spectra.services import scene_store
        return {s.id for s in scene_store.list_all()}

    def _default_scene_name(self, scene_id: str) -> str:
        from spectra.services import scene_store
        scene = scene_store.get_by_id(scene_id)
        return scene.name if scene else scene_id

    async def _default_broadcast(self, payload: dict) -> None:
        from spectra.services.ws import ws_manager
        await ws_manager.broadcast(payload)

    def _default_wheel_get(self) -> Optional[float]:
        from spectra.services import color_journey
        return color_journey.load_room().wheel_position_deg

    def _default_wheel_set(self, deg: Optional[float]) -> None:
        # A sequencer colour roll teleports the wheel, invalidating the
        # journey's bearing — clear it so the conductor reselects a
        # destination from the new point next leg.
        from spectra.services import color_journey
        room = color_journey.load_room()
        color_journey.save_room(room.model_copy(
            update={"wheel_position_deg": deg, "destination": None}))


scene_sequencer = SceneSequencer()
