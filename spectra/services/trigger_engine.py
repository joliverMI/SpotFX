"""SPECTRA-native trigger engine — THE KEYSTONE's execution half
(decision-mid-song-model.md, its 2026-08-14 framing correction, and the
settings-model brief, corr=c14a9bcee40e6df9). Fed by the S2 bridge's track
state through two calls (services/engine.py wires both): on_track_state(uri)
on every broadcast (mirrors scene_sequencer.TransitionSource.observe_uri)
and tick(position_ms) every TICK_S from the engine's own poll loop — fed
bridge.effective_position_ms(), the raw bridge position already corrected
by spot-effects' own xcorr shape_offset_ms (bridge.py's module docstring),
so tick() itself stays a plain position-vs-timestamp comparison and never
needs to know the correction exists. Fires
each of the current song's stored triggers (trigger_store) exactly once, the
moment its timestamp is first crossed:

  fire_scene          scene_sequencer.fire_scene_by_id — the SAME choke
                       point the sequencer's own picks use (re-baselines
                       drift via scene_compiler.fire_scene's on_scene_fired).
                       scene_id=None (a GENERATED trigger's own default,
                       front 3 — spectra/services/midsong_generator.py)
                       instead resolves through the sequencer selection
                       kernel AT FIRE TIME (curve × genre × affinity, using
                       the TRIGGER's own intensity) — see
                       _default_select_scene below. scene_pool (models/
                       trigger.py's SCENE POOLS section), when the action
                       also carries one, overrides that with a pure
                       weighted draw over a named subset instead — see
                       _default_select_scene_from_pool.
  fire_response        engine.fire_response_event — the SAME path the
                       bridge's classified trigger_fired events already
                       drive (phase drive, band selection, pulse release).
                       A charge/lull action also carries the real gap to
                       the next trigger this song will fire
                       (_next_trigger_gap_ms) — OVERRIDE BLEND's dynamic
                       ramp stretch (scene_response._phase_ramp_ms), 2026-
                       08-20. A bridge-classified flare carries no such
                       gap; drop is never stretched either way.
  select_color_set      drift_conductor.apply_set_directly — the SAME
                       manual-apply surface POST /api/room-color/apply uses.
  fire_scene_update      engine.fire_scene_update_event — UPDATE (data/
                       spectra-trigger-migration-scoping RULING.md): a
                       major change WITHIN the active scene, not band-
                       gated like fire_response. Reset is the same action
                       as update (his correction — one behaviour).

RENDER-INTENSITY SCALE (2026-08-15, the ported-and-corrected SpotFX v2
per-song/genre intensity scaling — spectra/services/intensity_scale.py):
every trigger's own intensity is a RAW measured value; _default_
render_intensity applies the current song's genre+bass scale to it
(headroom-reserve formula, intensity_scale.py's module docstring) before
it reaches a fire choke point. SELECTION (_select_scene, when a
generated trigger's scene_id is None) deliberately stays on the RAW
value — selection_kernel.py's own genre_mult already factors genre into
which scene/flare/colour-set gets picked, so scaling intensity there too
would double-count genre in the pick, not just in how hard it lands.

THE SETTINGS MODEL (room_controls.RoomControlState.scene_change_mode,
replacing front 3's plain midsong_triggers_enabled bool): four tiers the
owner ticks on the room bar. "transitions"/"analysed"/"full" form the
original additive ladder; "triggers_only" (2026-08-20,
data/spectra-my-triggers-only-mode) does NOT — it is a separate, precise
mode, not another ladder rung. See room_controls.py's own "scene_change_mode"
docstring entry for the full MISLABEL FIX + dual-path reasoning; summary
here:
  "transitions"   — a scene change on every song transition only, nothing
                    else: no stored trigger fires (see _fire_transition
                    below).
  "analysed"      — transitions + GENERATED mid-song triggers (source=
                    "generated" — midsong_generator's analysed section
                    boundaries). Hand-authored triggers still don't fire.
  "triggers_only" — a PER-SONG PREFERENCE WITH A FALLBACK (his 2026-08-20
                    correction, verbatim: "if no triggers exist, use the
                    analyzed triggers" — not the absolute silence-
                    everything design first built). On a song with at
                    least one stored trigger whose source=="authored",
                    ONLY his authored triggers fire — transitions,
                    generated mid-song triggers, and the automatic
                    transition fire are all silenced FOR THAT SONG. On a
                    song with NO stored authored trigger, this tier
                    behaves exactly like "analysed" for that song
                    instead. See _effective_mode_for_song below and
                    room_controls.py's own "scene_change_mode" docstring
                    entry (PER-SONG FALLBACK) for the exact "no triggers
                    exist" rule and the real-data reasoning (313/853
                    songs have any authored trigger; the other 540 need
                    the fallback to behave well, not just exist).
  "full"          — everything: transitions + generated mid-song triggers +
                    the owner's own hand-authored triggers (source=
                    "authored") + response-engine flares (gated at
                    engine.fire_response_event, the same choke point both a
                    bridge-classified flare and a trigger's fire_response
                    action reach). Default.
Checked per-crossing in tick() below (_trigger_allowed, against the PER-SONG
EFFECTIVE mode _effective_mode_for_song resolves) — same seam the old bool
switch used, extended to also cover authored triggers (which previously
always fired regardless of the switch) and, at engine.fire_response_event,
flares (previously always on regardless).

THE AUTOMATIC TRANSITION FIRE (_fire_transition, "transitions"/"analysed"/
"full" always; "triggers_only" only on a song with no authored trigger of
its own — see _effective_mode_for_song): "scene changes ON song
transitions" is the floor those three tiers share — the STANDARD the
binding decision names ("out of the box a song behaves exactly as
transitions-only"). "triggers_only" breaks that floor specifically for a
song he's actually authored (his own ask: "Spectra does not add its own"
when he's already added his own) — the automatic transition fire, like
every generated trigger, defers to his authored material for that song;
an un-authored song keeps the transitions-only floor via the same
"analysed" fallback the stored-trigger gate uses. It is deliberately NOT a stored SpectraTrigger at
timestamp_ms=0: the tick() edge-crossing window rearms at
`position_ms - 1` on a song change (see below), so a trigger sitting
exactly at 0 only fires if the very first tick after the change happens to
land before playback has advanced past it — a real bridge-poll race, not a
reliable mechanism. Firing directly from on_track_state's own transition
detection (mirrors scene_sequencer.TransitionSource's arm/fire semantics:
the first URI seen only arms, a stop/None doesn't count as a transition)
sidesteps that race entirely while still routing through the SAME
selection-kernel + fire_scene_by_id choke point every other scene pick
uses — "one mechanism," in the sense of one execution pathway, even though
this one moment isn't individually retimable/deletable per song the way a
stored trigger is (a deliberate, documented scope call for this settings-
model build, not a rebuild of the full transition-authoring surface).

DEFERS TO scene_sequencer WHEN IT'S THE LIVE TRANSITION AUTHORITY: both
scene_sequencer.on_track_state and this engine's on_track_state are wired
off the SAME URI-change broadcast (services/engine.py's _on_track_uri) — if
the sequencer's own config.enabled is True it ALREADY fires a scene on
every transition through its own TransitionSource, with richer state
(dwell songs served, weighted re-admit/uniform rungs, curve×genre×affinity
carried across songs) than this engine's one-shot kernel draw. Two
mechanisms firing on the same transition would double-fire the room, and
neither would know about the other's pick. Resolution (settings-model
correction, live reality: the sequencer was enabled on the running system
the same day this was built, already observed picking real transitions):
_fire_transition checks sequencer_store.load_config().enabled and is a
no-op whenever it's True — the sequencer remains the sole transition
authority, unconditionally, whether or not the settings model is at its
"transitions" floor; this engine's automatic fire only ever runs when the
sequencer is at ITS shipped default (dark, config.enabled=False). This was
the deliberately smaller, more conservative resolution over formally
superseding/disabling the sequencer: the sequencer's dwell/affinity state
is real, already-verified-working production behaviour as of the
correction, and re-deriving it in this engine (or migrating it away) is a
materially bigger change than this settings-model build's scope. See
_default_sequencer_enabled below and scripts/check_triggers.py's coverage
proving exactly one scene change fires per transition either way.

Two worlds coexist during migration (CLAUDE.md): this engine only ever
reads storage/spectra/triggers.json and the bridge's read-only feed; it
never touches storage/profiles or the legacy trigger_fired path.

AUTO-GENERATION (Admiral ask, order 12 — "they should be auto-generated if
there are none when the song is playing, I shouldn't have to go in and do
that"): maybe_auto_generate(uri), called by services/engine.py's
_on_track_uri on the SAME first-time-seeing-this-URI edge that already
resets _last_track_uri, runs midsong_generator.generate_for_song for a song
with ZERO stored triggers of either source — no timeline visit required.
Fire-and-forget (scheduled via asyncio.create_task, never awaited by the
caller) so a slow or never-analyzed song can never delay the transition
fire or tick work that already ran synchronously before it. Generated
triggers fire immediately at their normal gate (scene_change_mode
"analysed"/"full") — no separate review step; holding them for review
would recreate the exact friction this exists to remove. Never touches a
trigger he has claimed as his own: the empty-store precondition means no
authored trigger can be present when generation starts, and
generate_for_song's own source="generated"-only filtering (front 3) is the
second, independent guard. An unanalyzed song degrades honestly —
generate_for_song already returns a clean zero-moment no-op, never a
fabricated trigger. _generating (per-uri) stops a song from being
re-scheduled while its own generation is still in flight; the module-level
generation lock serializes the actual file-writing bodies of concurrent
generations for DIFFERENT songs, so two songs starting close together can't
interleave their trigger_store read-modify-write cycles.

Edge-triggered: a trigger fires once, on the first tick whose
(last_position, position] window crosses its timestamp — or, since
2026-08-19 (see LEAD-TIME ALIGNMENT below), its timestamp minus a computed
lead. A URI change (a NEW song, or the bridge dropping to None and
reconnecting) rearms: the next tick anchors last_position at position-1, so
a trigger sitting exactly AT that position still fires, while nothing
further back is backfired — a mid-song process restart doesn't replay the
whole song's history. A backward seek (rewind/scrub) rearms the same way,
silently, on the tick it's detected — approaching the same moment again
fires it again.

LEAD-TIME ALIGNMENT (his ask, 2026-08-19 — "this is how it worked in the
old SpotFX, use it as reference," legacy's services/transition_phases.py +
trigger_engine.py's transition_lead_ms/_entry_transition_lead_ms): a scene
transition should LAND on the trigger, not start there — the switch fires
`anchor_frac x crossfade_ms` EARLY. THREE anchors, deliberately different,
settled 2026-08-20 (data/drops-still-fire-early-star-does-not-explode/ —
Black Hole was tried as a "known-good" drop-timing reference, then
withdrawn when he found it early too; the three-anchor split below is his
own resolution, reconfirming the first two and adding the third):
  - a scene transition lands its MID-POINT (0.5 fallback, or a registered
    phased effect's own payoff fraction — services/transition_phases.py)
    on the trigger (_scene_transition_lead_ms) — starts EARLY by design.
  - a momentary flare's FIRST SWITCH lands its END (the full
    DICE_REROLL_GLIDE_MS) on the trigger, so the switch finishes, THEN the
    hold, THEN the flip-back after the trigger mark
    (_response_switch_lead_ms, event_class in charge/lull/flare) — also
    starts EARLY by design.
  - a DROP/explosion anchors its START to the trigger instead — it begins
    ON the mark, never before it (_response_switch_lead_ms,
    event_class=="drop" short-circuits to lead=0 unconditionally, ahead of
    the momentary-glide check the other two classes use). Don't let a
    future drop-band edit reintroduce the momentary rule's early start —
    see that function's own docstring for why the branch has to come
    first, not just happen to evaluate to 0 today.
Both scene-transition and momentary-flare peeks are read-only and
conservative: a fire with nothing to glide yields lead=0. tick()'s
crossing check always ALSO checks the trigger's own unshifted timestamp as
a safety net (fire_at is recomputed from live state every tick, so it
isn't guaranteed monotonic) — a trigger fires by its nominal moment at the
latest either way. Scene-entry crossfade DURATION itself is
intensity-scaled separately (room_controls.scene_transition_ms, consulted
by scene_compiler.fire_scene for every scene fire, not just trigger-driven
ones — his other ask, two Inspector settings scaling transition time by
intensity, linearly).

SCENE-CHANGE TRIGGER OFFSET (his ask, 2026-08-21, models/trigger.py's
SpectraTrigger.trigger_offset_ms — the scene-change equivalent of
FlareKind.trigger_offset_ms, which the flare scrubbing-preview timeline
already honours): a fire_scene trigger's own trigger_offset_ms relocates
the moment tick() targets — HIS sign convention, negative = fire earlier,
positive = fire later, 0 = unchanged — BEFORE the lead-time alignment
above ever runs. The two systems use OPPOSITE senses for "earlier"
(lead_ms: positive = earlier; his offset: negative = earlier) and must
never be combined by naive addition/subtraction of the same sign — see
tick()'s own inline comment for the exact composition
(fire_at = trig.timestamp_ms + trig.trigger_offset_ms - lead_ms) and why
it reduces to today's exact pre-offset behaviour whenever offset is 0
(every one of his real fire_scene triggers, as of this field's
introduction). SINCE 2026-08-27 (fm/flare-preview-offsets-everywhere) the
TRIGGER-level field is honoured on EVERY action kind, not just fire_scene:
an offset only relocates the moment (unlike a lead, which must know what
payoff it is aligning and how long that payoff takes), so it composes with
an instant apply — select_color_set, fire_scene_update — exactly as it does
with a crossfade. Where the fired CONTENT also carries an authored offset
(today: fire_response's flare kind, below), the two ADD — both are OFFSET
family, so summing is ordinary arithmetic, and at the untouched default of
0 on either side the sum degrades to exactly the other one. See tick()'s
own inline comment for why adding (rather than one overriding the other) is
the honest composition of a per-mark correction and a per-scene one.

FLARE-KIND TRIGGER OFFSET (his ask, 2026-08-21 — "make the engine read
the offset and work with the offset like we had in spot FX"): a
fire_response trigger's target is relocated the SAME way, by the SAME
composition, from a different authored source — FlareKind.
trigger_offset_ms (models/scene.py), the number the flare
scrubbing-preview's drag gesture writes (FlarePreviewOverlay.tsx →
flare_preview.trigger_mark_s), read LIVE off the band the ACTIVE scene
would fire for this class at this intensity (scene_response.
band_trigger_offset_ms, via _default_response_offset_ms — the same
active-scene + render-intensity peek _response_switch_lead_ms already
does). Same sign (negative = earlier), same target-then-lead composition
(target_ms = timestamp + kind_offset; fire_at = target_ms - lead_ms),
same offset=0 no-op guarantee (all 61 of his real flare kinds carried 0
when this shipped, re-verified live). Because this source is LIVE (the
active scene changes between ticks), a fire_response target isn't
constant the way a stored fire_scene offset is — tick() carries an
explicit fired-keys memory (exactly-once per approach; also closes a
pre-existing double-fire in the safety-net OR clause, which used to fire
an early-fired trigger AGAIN when its nominal target crossed the window)
and a stranded-target net (a target relocated behind the window uncrossed
fires late-not-never, only while the raw mark is still ahead). Scoped to
stored-trigger fires only, like the lead system: a bridge-classified
legacy flare arrives AT its moment with no forward notice, so there is
nothing to relocate earlier — same reason _fire_transition takes no lead.

Settling the drop anchor does NOT, by itself, prove the VISIBLE explosion
begins on the mark — only that the WRITE does (already true before this
change, for every real scene: scripts/check_triggers.py never found a
drop band anywhere in his data that would have taken the momentary lead
anyway). What each phase-capable effect DOES with phase_progress as it
ramps 0->1 (fx/effects/{radial,blackhole,orbits,squiggles}.py) is a
separate, still-open question — see docs/SPECTRA_SPEC.md's onset-timing
entry and scripts/check_drop_visible_onset.py.

LOOKAHEAD (his ask, 2026-08-19, same day as the alignment above — "his
triggers never name their scene in advance, peek the upcoming trigger
within a bounded horizon, resolve what that fire will actually do, and
move the start moment so the midpoint still lands on the mark"): the
plain rule above yields lead=0 for an unresolved fire_scene (scene_id=
None) — his own words, "no lead rather than a wrong one" — because the
scene isn't chosen until fire time. Correlated against his real data: 0 of
22,013 fire_scene triggers ever carry a resolved scene_id, so that rule
never engaged for him at all — measured live, 100 real fires landed at or
after their stored timestamp, up to 3,144ms late, zero early.
LOOKAHEAD_HORIZON_MS (module-level constant, reusing transition_phases.
MAX_LEAD_MS — see its own docstring for why that's the justified number,
not an arbitrary one) is how far ahead TriggerEngine._pin_for commits to a
real kernel/pool draw for such a trigger. It is NOT a second, independent
prediction sitting alongside the real fire-time decision: it IS the
decision, made once, moved earlier, and reused verbatim — _fire() never
draws again for a trigger it already pinned. The risk his ask names
explicitly — "what happens when what actually fires is not what was
predicted" — can therefore only come from the pinned scene stopping being
legitimate to fire between the pin and the fire (disabled, mode-gated,
Force Scene redirected elsewhere); TriggerEngine._pin_still_valid checks
exactly that, narrowly, and throwing the pin away degrades to today's
exact behaviour: a fresh draw at nominal time, zero lead, late but never
wrong. See _pin_for's own docstring for the full mechanism.

PROVING THIS RATHER THAN ASSERTING IT: the underlying scene-entry ramp
this all rides (scene_compiler.fire_scene's transition_ms write) has no
live instrument today that observes it AT the moment of a real fire —
rendered frame averages sample too coarsely to catch a switching instant,
and executor.recent_writes (fx_executor.py) never records a scene fire's
own writes, only glide/jump calls made directly through it. Everything
above is proven at the unit level (a real scene/room/kernel, no LedFX I/O
— scripts/check_triggers.py) and at the frame level with an INJECTED lead
(tests/test_trigger_engine.py, matching proofs 9/10's own established
convention) — both prove the MECHANISM correctly reuses one committed pick
and degrades correctly when it's invalidated. Neither proves the visual
claim ("the midpoint really lands on the beat") against a live fire,
because nothing in this codebase can observe a live scene-entry ramp yet.
Building that observation would mean extending fire_history.py's already-
hooked choke points (scene_sequencer.fire_scene_by_id) to timestamp the
fx_seam.apply_writes call itself, then correlating that timestamp against
the trigger's own stored timestamp_ms on a real song — a small, bounded
addition (one new timestamped record per scene fire, no new choke point),
named here as a real, uncosted follow-up rather than silently assumed.

Executable spec: scripts/check_triggers.py (fake position feed, injected
fires — no live storage, no LedFX I/O, no audio).
Frame-level proof: tests/test_trigger_engine.py (FacadeExecutor + the
headless dummy device).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from random import Random
from typing import Any, Awaitable, Callable, Optional

from spectra.models.trigger import SpectraTrigger
from spectra.services import transition_phases, trigger_store

logger = logging.getLogger(__name__)

TICK_S = 0.2

# LOOKAHEAD HORIZON (his ask, 2026-08-19 — "peek the upcoming trigger within
# a bounded horizon... five seconds or something, whatever works"; the
# number and its justification are ours to pick). Reuses transition_phases.
# MAX_LEAD_MS rather than a second, disconnected constant: no lead this
# feature (or the plain resolved-scene_id rule above it) can ever compute
# exceeds that cap, so a horizon shorter than it would arrive too late to
# cover the worst case, and a horizon longer than it buys nothing (no lead
# could use the extra notice) while only widening the window a pinned
# pick's validity (disabled/mode/force-scene — see TriggerEngine._pin_
# still_valid) could drift before fire. MAX_LEAD_MS is therefore both
# necessary and sufficient for this horizon, not a separately-tuned number.
LOOKAHEAD_HORIZON_MS = transition_phases.MAX_LEAD_MS

# FLARE-KIND TRIGGER OFFSET peek window (his ask, 2026-08-21): how near a
# fire_response trigger's RAW timestamp tick() bothers asking the active
# scene's band for an authored FlareKind.trigger_offset_ms
# (scene_response.band_trigger_offset_ms). Derived, not tuned:
# FlareKind.trigger_offset_ms's own model clamp is +/-60_000ms
# (models/scene.py), so a legal offset can relocate the target at most 60s
# either side of the raw mark, and the lead system needs at most
# LOOKAHEAD_HORIZON_MS extra notice ahead of any relocated target — outside
# this band a peek could never change when the trigger fires, so skipping
# it there is pure cost avoidance, never a behaviour change
# (tests/test_flare_kind_trigger_offset.py pins the derivation against the
# model clamp itself).
RESPONSE_OFFSET_HORIZON_MS = 60_000 + LOOKAHEAD_HORIZON_MS


@dataclass
class _PinnedPick:
    """One trigger's early-resolved fire_scene pick (LOOKAHEAD, 2026-08-19).
    Committed ONCE, the moment the trigger enters LOOKAHEAD_HORIZON_MS, and
    reused VERBATIM at fire time — never re-drawn. That's the feature's
    actual safety property: there is no second draw to diverge from a first
    one, so "predicted vs. actual" can't disagree on WHICH scene fires (see
    TriggerEngine._pin_for's docstring). The residual risk his ask calls out
    — the world moving between commit and fire — is handled by
    TriggerEngine._pin_still_valid checking this pick is still legitimate
    right before it's used, not by drawing again."""
    scene_id: str
    lead_ms: int
    # Snapshot of Force Scene at commit time, timing-quality only: a force-
    # scene change never risks firing the WRONG scene (scene_sequencer.
    # fire_scene_by_id always applies the CURRENT redirect to whatever id
    # it's handed, pin or fresh draw alike) — but the stored lead_ms was
    # computed against THIS target's crossfade profile, and a changed
    # redirect would make that number describe the wrong transition. Same
    # "no lead rather than a wrong one" caution as everywhere else in this
    # module, applied to timing quality rather than content.
    force_scene: tuple[bool, Optional[str]]

# Serializes the file-writing body of concurrent auto-generations for
# DIFFERENT songs (trigger_store's read-modify-write cycle isn't itself
# lock-protected). Lazily created — mirrors spectra/services/ambient.py's
# _get_lock — so constructing the module-level TriggerEngine singleton
# below never requires a running event loop.
_generation_lock: Optional[asyncio.Lock] = None


def _get_generation_lock() -> asyncio.Lock:
    global _generation_lock
    if _generation_lock is None:
        _generation_lock = asyncio.Lock()
    return _generation_lock


class TriggerEngine:
    """One instance per process (singleton below). Constructor injectables
    exist for the executable spec only — production uses the defaults."""

    def __init__(
        self, *,
        list_triggers: Callable[[str], list[SpectraTrigger]] | None = None,
        fire_scene: Callable[..., Awaitable[Any]] | None = None,
        fire_response: Callable[[str, float, Optional[int]], Awaitable[Any]] | None = None,
        select_color_set: Callable[[str], Awaitable[Any]] | None = None,
        fire_scene_update: Callable[[float], Awaitable[Any]] | None = None,
        select_scene: Callable[[float], Optional[str]] | None = None,
        select_scene_from_pool: Callable[[list], Optional[str]] | None = None,
        scene_change_mode: Callable[[], str] | None = None,
        transition_intensity: Callable[[], float] | None = None,
        render_intensity: Callable[[float], float] | None = None,
        sequencer_enabled: Callable[[], bool] | None = None,
        auto_generate: Callable[[str], Awaitable[Any]] | None = None,
        lead_ms: Callable[[SpectraTrigger], int] | None = None,
        response_offset_ms: Callable[[Any], int] | None = None,
        intensity_event: Callable[[], None] | None = None,
        rng: Random | None = None,
    ) -> None:
        self._list_triggers = list_triggers or trigger_store.list_for_song
        self._fire_scene = fire_scene or self._default_fire_scene
        self._fire_response = fire_response or self._default_fire_response
        self._select_color_set = select_color_set or self._default_select_color_set
        self._fire_scene_update = fire_scene_update or self._default_fire_scene_update
        self._select_scene = select_scene or self._default_select_scene
        self._select_scene_from_pool = (select_scene_from_pool
                                        or self._default_select_scene_from_pool)
        self._scene_change_mode = scene_change_mode or self._default_scene_change_mode
        self._transition_intensity = (transition_intensity
                                      or self._default_transition_intensity)
        self._render_intensity = render_intensity or self._default_render_intensity
        self._sequencer_enabled = sequencer_enabled or self._default_sequencer_enabled
        self._auto_generate = auto_generate or self._default_auto_generate
        self._lead_ms = lead_ms or self._default_lead_ms
        self._response_offset_ms = response_offset_ms or self._default_response_offset_ms
        # Two-dimensional drift gradient retarget hook (owner ask
        # 2026-08-20) — deliberately NOT a lazy import of the production
        # engine.conductor singleton the way _default_fire_scene/
        # _default_fire_response are: those are the SUBJECT of every test
        # in this file and are always explicitly overridden; this one is a
        # small side call easy to forget to stub, so its own default is a
        # safe no-op instead. Production wiring happens explicitly in
        # services/engine.py (`trigger_engine._intensity_event =
        # conductor.on_intensity_event`), the same place that module
        # already owns the conductor/responses singletons.
        self._intensity_event = intensity_event or (lambda: None)
        self._generating: set[str] = set()
        self._rng = rng or Random()

        # LOOKAHEAD (2026-08-19): trigger_id -> _PinnedPick, or trigger_id ->
        # None for "already attempted once, the draw came back empty" (the
        # STAY rung / an empty scene_pool) — a bare-None cache entry so that
        # negative result is never retried either. See _pin_for.
        self._pins: dict[str, Optional[_PinnedPick]] = {}

        # EXACTLY-ONCE per approach (2026-08-21, found building the
        # flare-kind offset below): (trigger_id, timestamp_ms) keys already
        # fired since the last rearm. The docstring's own "fires once per
        # crossing" contract used to be emergent from the target being
        # constant and the position monotone — but the safety-net OR clause
        # in tick() breaks it for any EARLY fire more than one tick ahead
        # of its target (fired at fire_at, then AGAIN when the nominal
        # target itself crossed the window — reproduced red against the
        # pre-fix code in tests/test_flare_kind_trigger_offset.py), and a
        # LIVE-relocated fire_response target (the flare-kind offset, read
        # off the active scene each tick) can additionally move forward
        # across an already-fired position. This set makes the contract
        # explicit for both. Keyed on (id, timestamp_ms) — not id alone —
        # so a trigger whose stored timestamp he EDITS mid-song is a fresh
        # key and fires at its new mark (today's live-authoring
        # affordance), while an offset drag (timestamp unchanged) can
        # never machine-gun re-fires. Cleared exactly where _pins is:
        # song change and rewind ("approaching the same moment again
        # fires it again").
        self._fired: set[tuple[str, int]] = set()

        self._uri: Optional[str] = None
        self._last_position_ms: Optional[int] = None
        # Separate from _uri/_last_position_ms: mirrors
        # scene_sequencer.TransitionSource's arm/fire state so a stop/None
        # never counts as (or breaks arming for) a transition.
        self._last_transition_uri: Optional[str] = None
        self.last_fire: Optional[dict] = None  # observability

    # ── feed (services/engine.py calls both) ─────────────────────────────

    async def on_track_state(self, uri: Optional[str]) -> None:
        """A URI change rearms the tick clock: last_position resets so the
        next tick anchors fresh at wherever it finds the position, never
        backfiring the song's history. A genuine song-to-song change (armed
        after the first URI ever seen; a stop/None neither fires nor
        disarms) additionally fires the automatic transition scene change —
        see the module docstring's _fire_transition section."""
        if uri != self._uri:
            self._uri = uri
            self._last_position_ms = None
            # A new song's trigger list is unrelated to the old one's — any
            # LOOKAHEAD pin from the previous song is dead weight, never a
            # reusable commitment (see _pin_for). The fired-keys memory
            # rearms with it.
            self._pins.clear()
            self._fired.clear()
        if uri is None or uri == self._last_transition_uri:
            return
        armed = self._last_transition_uri is not None
        self._last_transition_uri = uri
        if armed:
            await self._fire_transition()

    async def _fire_transition(self) -> None:
        if self._sequencer_enabled():
            logger.info("song transition: scene_sequencer.config.enabled is "
                        "True — it already fires its own transition pick "
                        "(dwell/affinity), so trigger_engine defers to avoid "
                        "a double scene change")
            return
        if (self._scene_change_mode() == "triggers_only"
                and self._song_has_authored_triggers(self._uri)):
            logger.info("song transition: triggers_only and this song already "
                        "has an authored trigger of its own — automatic "
                        "transition fire silenced for it (room_controls.py's "
                        "scene_change_mode docstring, PER-SONG FALLBACK)")
            return
        intensity = self._transition_intensity()
        self._notify_intensity_event()
        scene_id = self._select_scene(intensity)
        if scene_id is None:
            logger.info("song transition: kernel picked no scene "
                        "(ladder terminated at stay) — nothing fired")
            return
        try:
            await self._fire_scene(scene_id, None, self._render_intensity(intensity))
        except Exception:
            logger.exception("song transition: firing scene %s failed", scene_id)
            return
        logger.info("song transition: fired scene %s", scene_id)
        self.last_fire = {"id": None, "kind": "transition", "ok": True}

    def _song_has_authored_triggers(self, uri: Optional[str]) -> bool:
        """The PER-SONG FALLBACK's own precondition (room_controls.py's
        scene_change_mode docstring, PER-SONG FALLBACK entry): True the
        moment this song has ANY stored trigger with source=="authored" —
        regardless of that trigger's own `enabled` flag (matches how his
        real-data 313/853 count was taken: a raw storage scan, not a
        live-gating simulation). Checked fresh from trigger_store on every
        call, never cached — he can author a trigger on a song mid-play."""
        if uri is None:
            return False
        return any(t.source == "authored" for t in self._list_triggers(uri))

    @staticmethod
    def _effective_mode_for_song(mode: str, triggers: list[SpectraTrigger]) -> str:
        """triggers_only is a per-song PREFERENCE WITH A FALLBACK, not an
        absolute (his 2026-08-20 correction, verbatim: "if no triggers
        exist, use the analyzed triggers" — room_controls.py's
        scene_change_mode docstring has the full reasoning and his real
        numbers). A song with at least one stored source=="authored"
        trigger keeps "triggers_only" exactly as-is (only his own
        triggers reach _trigger_allowed below); a song with none falls
        back to "analysed" for that song, so transitions + generated
        triggers fire exactly as the "analysed" tier always has. Every
        other mode passes through unchanged."""
        if mode == "triggers_only" and not any(t.source == "authored" for t in triggers):
            return "analysed"
        return mode

    def maybe_auto_generate(self, uri: Optional[str]) -> None:
        """Called by services/engine.py's _on_track_uri on the same
        first-time-seeing-this-URI edge that resets _last_track_uri — a
        song with zero stored triggers (of either source) gets generated
        for automatically. Fire-and-forget by design: the caller is never
        made to wait on this (see the module docstring's AUTO-GENERATION
        section)."""
        if not uri or uri in self._generating or self._list_triggers(uri):
            return
        self._generating.add(uri)
        asyncio.create_task(self._run_auto_generate(uri))

    async def _run_auto_generate(self, uri: str) -> None:
        try:
            await self._auto_generate(uri)
        except Exception:
            logger.exception("auto-generate: trigger generation failed for %s", uri)
        finally:
            self._generating.discard(uri)

    async def tick(self, position_ms: Optional[int]) -> list[SpectraTrigger]:
        """One evaluation, called every TICK_S with the CURRENT position.
        Also called directly by the executable spec / tests with a fake
        position feed. Returns the triggers fired this tick, in timestamp
        order."""
        if self._uri is None or position_ms is None:
            return []
        if self._last_position_ms is None:
            # Rearm: anchor one ms behind so a trigger sitting exactly AT
            # this position still fires, without backfiring further back.
            self._last_position_ms = position_ms - 1
        last = self._last_position_ms
        self._last_position_ms = position_ms
        if position_ms < last:
            # A rewind can re-approach an already-pinned trigger with a now-
            # stale commitment — arbitrary time may have passed off-screen
            # (room state can drift any amount during a scrub). Drop every
            # LOOKAHEAD pin rather than trust one across a rewind; a fresh
            # horizon entry re-pins cleanly on the next approach. The
            # fired-keys memory clears with it — "approaching the same
            # moment again fires it again" (module docstring).
            self._pins.clear()
            self._fired.clear()
            return []  # rewind/seek back: silently rearmed via the line above
        triggers = self._list_triggers(self._uri)
        mode = self._effective_mode_for_song(self._scene_change_mode(), triggers)
        fired: list[SpectraTrigger] = []
        for trig in triggers:
            if not trig.enabled:
                continue
            if not self._trigger_allowed(trig, mode):
                continue
            # EXACTLY-ONCE per approach (see self._fired's own comment in
            # __init__): a trigger that already fired since the last rearm
            # never re-fires, however its computed target/fire_at drift
            # afterwards — this is what lets the safety-net OR below stay a
            # NET (fire at the nominal target if the early window was
            # missed) instead of a second fire after a successful early
            # one, and what keeps a LIVE-relocated fire_response target
            # (below) from re-crossing an already-fired position.
            fired_key = (trig.id, trig.timestamp_ms)
            if fired_key in self._fired:
                continue
            # TRIGGER OFFSET (his sign convention throughout — negative =
            # fire earlier, positive = fire later, 0 = unchanged):
            # target_ms is the relocated moment every "when to fire"
            # comparison below uses in place of the raw stored
            # trig.timestamp_ms. TWO authored sources, one per action kind:
            #   - THE TRIGGER'S OWN SpectraTrigger.trigger_offset_ms —
            #     stored on the trigger, constant, cheap (a field read, no
            #     gate needed). Applied to EVERY action kind since
            #     2026-08-27 (fm/flare-preview-offsets-everywhere). #172
            #     originally wired it for fire_scene ONLY, leaving it
            #     silently inert on the other three — a trap its own model
            #     docstring named ("fire_response/select_color_set/
            #     fire_scene_update triggers still ignore it") against an
            #     ask that did not scope itself that way ("do events like
            #     flares and scene changes carry an offset value... they
            #     need to"). Nothing about an OFFSET is action-kind
            #     specific: unlike a LEAD (which must know what payoff it
            #     is aligning and how long that payoff takes to arrive),
            #     an offset only RELOCATES the moment, so it composes
            #     with any action — an instant apply included — by
            #     construction.
            #   - THE CONTENT'S OWN authored offset, where the content has
            #     one. Today that is fire_response's FLARE KIND offset
            #     (his ask, 2026-08-21 — "make the engine read the offset
            #     and work with the offset like we had in spot FX"): the
            #     FlareKind.trigger_offset_ms the flare scrubbing-preview's
            #     drag writes, read LIVE off the band the active scene
            #     would fire for this class at this intensity
            #     (scene_response.band_trigger_offset_ms via
            #     _default_response_offset_ms, mirroring
            #     _response_switch_lead_ms's own live peek), only within
            #     RESPONSE_OFFSET_HORIZON_MS of the raw mark (a derived
            #     cost gate — see that constant). Because this source is
            #     live (the active scene can change between ticks),
            #     target_ms for a fire_response trigger is NOT guaranteed
            #     constant — the fired-keys guard above and the
            #     stranded-target net below are what keep "at most once,
            #     never dropped" true anyway.
            #
            # THE TWO SOURCES ADD, and that is legal precisely because they
            # are BOTH in the OFFSET family (docs/SPECTRA_TIMING_
            # CONVENTIONS.md's master table): same unit, same sign, same
            # meaning of "later". Summing two same-family quantities is
            # ordinary arithmetic; it is only the LEAD family below that
            # must never be added to either of them. They are independent
            # corrections to the same moment and neither subsumes the
            # other: the trigger's own offset is a property of THIS MARK IN
            # THIS SONG (this beat sits a hair off where the analysis put
            # it), the kind's is a property of THE SCENE'S OWN FLARE
            # (this animation needs a head start wherever it fires). An
            # override rule would silently discard whichever he authored
            # second; adding honours both, and at the untouched default of
            # 0 on either side the sum degrades to exactly the other one.
            #
            # THE SIGN COMPOSITION WITH _lead_ms, STATED EXPLICITLY (a wrong
            # sign here is invisible to a naive test and has cost hours
            # twice): _lead_ms below uses the OPPOSITE sense from his
            # offset — a POSITIVE lead means fire EARLIER
            # (`fire_at = target - lead`), while his offset is NEGATIVE for
            # earlier. These are two independently-signed quantities and
            # must never be added or subtracted from each other directly —
            # doing so would silently invert one of them. They compose
            # correctly by each acting in its OWN native direction against
            # a shared base: his offset first relocates the base target
            # from trig.timestamp_ms to target_ms (ADDING a negative offset
            # moves target_ms earlier — his convention, unchanged); the
            # transition's own auto-computed lead THEN SUBTRACTS from that
            # relocated target, exactly as it always has (lead_ms's own
            # sign and its subtraction are untouched by this change). Net:
            # fire_at = trig.timestamp_ms + trig.trigger_offset_ms - lead_ms.
            # At offset=0 this is byte-identical to the pre-existing
            # formula (trig.timestamp_ms - lead_ms) — every one of his real
            # fire_scene triggers carries offset=0 today, so this is
            # provably a no-op for everything currently on disk. The
            # fire_response branch composes the SAME way with the SAME
            # proof obligation (both extremes — scripts/check_triggers.py
            # §11): the kind's offset relocates the base target in HIS
            # sense first, the lead then subtracts in its own sense,
            # and all 61 of his real flare kinds carried offset=0 when
            # this shipped (re-verified live), so it too is a no-op on
            # everything currently stored.
            target_ms = trig.timestamp_ms + trig.trigger_offset_ms
            if (trig.action.kind == "fire_response"
                    and abs(trig.timestamp_ms - last) <= RESPONSE_OFFSET_HORIZON_MS):
                target_ms += self._response_offset_ms(trig.action)
            # TRANSITION/FLARE LEAD-TIME ALIGNMENT (his ask, 2026-08-19):
            # fire up to lead_ms EARLY so a scene transition's mid-point (or
            # a registered phased effect's own payoff — see
            # services/transition_phases.py) or a momentary flare's first
            # switch lands exactly on target_ms instead of starting there.
            # Only bother computing it within striking distance (cheap:
            # most of a song's triggers sit far from `position_ms` on any
            # given tick) — LOOKAHEAD_HORIZON_MS both caps the computed
            # lead and bounds this gate, now measured against target_ms (not
            # the raw timestamp) so a large negative offset opens the
            # window — and commits a LOOKAHEAD pin, see _pin_for — early
            # enough to matter; for an unresolved fire_scene trigger it's
            # ALSO the moment _lead_ms's own _pin_for commits its one-shot
            # early pick (see that module-level constant's docstring).
            fire_at = target_ms
            if 0 <= target_ms - last <= LOOKAHEAD_HORIZON_MS:
                lead = self._lead_ms(trig)
                if lead > 0:
                    fire_at = target_ms - lead
            # The OR is a safety net, not an optimization: fire_at is
            # recomputed fresh every tick from live state (the registry
            # match against whatever effect is CURRENTLY live on a target
            # virtual), so it isn't guaranteed monotonic tick to tick — a
            # trigger must still fire by its own nominal (offset-relocated)
            # target even if an earlier tick's early-fire window was missed
            # for any reason. target_ms itself never drifts within a tick,
            # so this clause alone reproduces today's exact pre-lead
            # behaviour whenever trigger_offset_ms is 0. Comparing against
            # target_ms here — not the raw trig.timestamp_ms — is load-
            # bearing for a POSITIVE offset (fire later): without it, this
            # safety net would still fire at the raw, un-relocated
            # timestamp, defeating the entire point of asking for a later
            # fire.
            # STRANDED-TARGET NET (fire_response only — the one kind whose
            # target is read LIVE, above): a negative kind offset can
            # relocate the target BEHIND the tick window without it ever
            # being crossed — the active scene changing between ticks
            # (different band, different authored offset), a forward seek
            # landing between the relocated target and the raw mark, or a
            # process (re)start finding the relocated moment already past
            # while the raw mark is still ahead. "Late but never dropped"
            # (the same posture the OR net above takes for a missed early
            # window): fire NOW, once, provided the RAW mark hasn't itself
            # passed (last <= timestamp — past-mark triggers stay history,
            # the no-backfill rule) and playback actually advanced this
            # tick (position_ms > last — a paused poll must never fire).
            # Constant-target kinds (fire_scene's stored offset included)
            # can never strand, so they never take this branch.
            stranded = (trig.action.kind == "fire_response"
                        and target_ms < trig.timestamp_ms
                        and target_ms <= last <= trig.timestamp_ms
                        and position_ms > last)
            if (last < fire_at <= position_ms
                    or last < target_ms <= position_ms
                    or stranded):
                self._fired.add(fired_key)
                await self._fire(trig)
                fired.append(trig)
        return fired

    @staticmethod
    def _trigger_allowed(trig: SpectraTrigger, mode: str) -> bool:
        """The settings model's gate (room_controls.RoomControlState.
        scene_change_mode) — called with the PER-SONG EFFECTIVE mode
        (see _effective_mode_for_song, tick()'s own call site), not
        necessarily the raw stored setting: "full" and "triggers_only"
        both fire hand-authored triggers; "analysed" and "transitions"
        both skip them, and "transitions" additionally skips GENERATED
        (analysed mid-song) triggers — the automatic transition fire
        (_fire_transition) is the only thing that still happens in
        "transitions" mode, and it isn't a stored trigger at all, so it
        never reaches this gate."""
        if trig.source == "authored":
            return mode in ("full", "triggers_only")
        return mode in ("analysed", "full")

    def _notify_intensity_event(self) -> None:
        """The two-dimensional drift gradient's retarget hook (owner ask
        2026-08-20, drift_conductor.py's "gradient drift" docstring
        section) — "the target changes whenever a trigger or analyzed
        transition changes the intensity." Both _fire() (a trigger) and
        _fire_transition() (an analysed transition) call this at exactly
        the moment they resolve their own fire intensity. Best-effort: a
        failure here must never break the actual scene/response fire it's
        piggybacking on."""
        try:
            self._intensity_event()
        except Exception:
            logger.exception("gradient drift: on_intensity_event failed")

    async def _fire(self, trig: SpectraTrigger) -> None:
        a = trig.action
        self._notify_intensity_event()
        try:
            if a.kind == "fire_scene":
                scene_id = a.scene_id
                if scene_id is None:
                    # LOOKAHEAD (2026-08-19): reuse the pick already
                    # committed at horizon entry, if it's still valid — the
                    # fire never draws a second time when one is available
                    # (see _pin_for's docstring for why that, not the lead
                    # timing, is the actual safety property). No usable pin
                    # (never pinned, or invalidated since) falls through to
                    # exactly today's fresh, one-shot draw.
                    pin = self._pins.pop(trig.id, None)
                    if pin is not None and self._pin_still_valid(pin):
                        scene_id = pin.scene_id
                    elif a.scene_pool:
                        # scene_pool present: narrow-and-bias override — a
                        # pure weighted draw over just this trigger's named
                        # scenes (see models/trigger.py's SCENE POOLS
                        # section), bypassing the kernel's curve/genre/
                        # affinity draw entirely.
                        scene_id = self._select_scene_from_pool(a.scene_pool)
                    else:
                        # SELECTION uses the trigger's RAW intensity: the kernel
                        # already applies its own genre_mult (selection_kernel.py)
                        # — scaling here too would double-count genre in the pick.
                        scene_id = self._select_scene(a.intensity)
                    if scene_id is None:
                        logger.info("trigger %s: kernel picked no scene "
                                    "(ladder terminated at stay, or scene_pool "
                                    "had nothing valid to draw) — nothing fired",
                                    trig.id)
                        self.last_fire = {"id": trig.id, "kind": a.kind,
                                          "ok": True, "picked": None}
                        return
                await self._fire_scene(scene_id, a.color_set_id,
                                       self._render_intensity(a.intensity))
            elif a.kind == "fire_response":
                # OVERRIDE BLEND's dynamic half (2026-08-20, "fix the lull
                # ramp"): only charge/lull stretch a ramp to the real gap
                # — drop is always the fixed snap, so no gap is worth
                # computing for it (see _next_trigger_gap_ms/_phase_ramp_ms
                # for the full mechanism).
                gap_ms = (self._next_trigger_gap_ms(trig)
                         if a.event_class in ("charge", "lull") else None)
                await self._fire_response(a.event_class,
                                          self._render_intensity(a.intensity),
                                          gap_ms)
            elif a.kind == "fire_scene_update":
                await self._fire_scene_update(self._render_intensity(a.intensity))
            else:
                await self._select_color_set(a.set_id)
        except Exception:
            logger.exception("trigger %s (%s @ %dms) failed to fire",
                             trig.id, a.kind, trig.timestamp_ms)
            self.last_fire = {"id": trig.id, "kind": a.kind, "ok": False}
            return
        logger.info("trigger %s fired: %s @ %dms", trig.id, a.kind, trig.timestamp_ms)
        self.last_fire = {"id": trig.id, "kind": a.kind, "ok": True}
        from spectra.services import fire_history
        fire_history.record_fire(
            "triggers", f"{trig.source}:{a.kind}",
            {"trigger_id": trig.id, "action_kind": a.kind, "source": trig.source},
            uri=self._uri, position_ms=self._last_position_ms)

    def _next_trigger_gap_ms(self, trig: SpectraTrigger) -> Optional[int]:
        """OVERRIDE BLEND's dynamic half (ported from legacy trigger_engine.
        _phase_blend_ramp_ms/_blend_factor_for, missing from the SPECTRA
        port until 2026-08-20 — see scene_response.py's own OVERRIDE BLEND
        note for the full incident writeup): milliseconds from this trigger
        to the next trigger THIS SONG WILL ACTUALLY FIRE, honoring the same
        settings-model gate tick() itself applies. Resolves the PER-SONG
        EFFECTIVE mode exactly as tick() does (_effective_mode_for_song
        against this song's own trigger list, not the raw stored setting)
        before calling _trigger_allowed — load-bearing since "triggers_only"
        (#148): a trigger the effective mode won't actually fire is not a
        real "next moment" to stretch a ramp toward, and under
        "triggers_only" that set differs from the raw mode's own on a song
        with no authored trigger of its own (falls back to "analysed").
        None means there's nothing to stretch to: no next trigger is
        enabled/allowed for this song (this is the last one), or no song is
        loaded at all — the caller (scene_response._phase_ramp_ms) falls
        back to a documented flat default in that case, never a guess."""
        if self._uri is None:
            return None
        triggers = self._list_triggers(self._uri)
        mode = self._effective_mode_for_song(self._scene_change_mode(), triggers)
        nxt = min(
            (t.timestamp_ms for t in triggers
             if t.enabled and t.id != trig.id
             and t.timestamp_ms > trig.timestamp_ms
             and self._trigger_allowed(t, mode)),
            default=None)
        if nxt is None:
            return None
        gap = nxt - trig.timestamp_ms
        return gap if gap > 0 else None

    # ── observability ─────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "track_uri": self._uri,
            "position_ms": self._last_position_ms,
            "last_fire": self.last_fire,
        }

    # ── production defaults (lazy imports; the spec injects fakes) ──────────

    async def _default_fire_scene(self, scene_id: str,
                                  color_set_id: Optional[str],
                                  intensity: float) -> None:
        from spectra.services.scene_sequencer import fire_scene_by_id
        await fire_scene_by_id(scene_id, color_set_id, intensity)

    def _default_select_scene(self, intensity: float) -> Optional[str]:
        """A generated trigger's scene_id=None resolution: the SAME
        selection kernel the sequencer's own rolls use
        (scene_sequencer._roll), but a one-shot draw at the TRIGGER's own
        intensity — no dwell, no "current scene" affinity tracked across
        trigger fires (deliberately simpler than the sequencer's continuous
        state machine; a mid-song trigger names one moment, not a stream of
        them). picked_id None (the terminal STAY rung, or no configured
        sequencer entries at all) means nothing fires this crossing."""
        from spectra.services import mode_availability, scene_store, selection_kernel as kernel
        from spectra.services import sequencer_store
        from spectra.services.engine import bridge
        from spectra.services.room_controls import load_room_controls
        config = sequencer_store.load_config()
        curves = sequencer_store.load_curves()
        room_mode = load_room_controls().display_mode
        existing = {s.id for s in scene_store.list_all()
                   if mode_availability.available_in_room_mode(
                       s.display_availability, room_mode)
                   and not getattr(s, "disabled", False)}
        candidates = kernel.build_scene_candidates(
            config.entries, curves, config.affinity,
            genre_bucket=bridge.genre_bucket(), prev_id=None,
            restrict_ids=existing)
        pick = kernel.select(candidates, intensity=intensity, rng=self._rng,
                             current_id=None, terminal=kernel.TERMINAL_STAY)
        return pick.picked_id

    def _default_select_scene_from_pool(self, pool: list) -> Optional[str]:
        """A trigger's own scene_pool (models/trigger.py's SCENE POOLS
        section): a pure weighted draw over the pool's own weights,
        filtered to scenes that still exist — see
        selection_kernel.select_from_scene_pool's own docstring for why
        this deliberately skips curve/genre/affinity composition. None
        means nothing in the pool is both present and positively
        weighted."""
        from spectra.services import scene_store, selection_kernel as kernel
        existing = {s.id for s in scene_store.list_all()}
        return kernel.select_from_scene_pool(pool, self._rng, existing_ids=existing)

    def _default_scene_change_mode(self) -> str:
        from spectra.services.room_controls import load_room_controls
        return load_room_controls().scene_change_mode

    def _default_transition_intensity(self) -> float:
        # Same bridge feed + 0.5 neutral fallback as scene_sequencer's own
        # _default_intensity — no per-song analysis is required for the
        # automatic transition fire to work.
        from spectra.services.engine import bridge
        value = bridge.intensity()
        return value if value is not None else 0.5

    def _default_render_intensity(self, raw: float) -> float:
        """The RENDER/FIRE role (as opposed to _select_scene's SELECTION
        role, above): every value actually landed at a choke point
        (fire_scene/fire_response/fire_scene_update) passes through the
        current song's genre+bass scale via intensity_scale.
        combine_measured_and_scale — the ported-and-corrected SpotFX v2
        mechanism (spectra/services/intensity_scale.py's module docstring
        has the full headroom-reserve formula and its rationale)."""
        from spectra.services import intensity_scale
        from spectra.services.engine import bridge
        return intensity_scale.combine_measured_and_scale(
            raw, bridge.song_scaling_factor())

    def _default_sequencer_enabled(self) -> bool:
        # scene_sequencer's OWN dark switch (config.enabled, storage/
        # spectra/sequencer.json) — separate from scene_change_mode. When
        # True the sequencer is the live transition authority (see
        # _fire_transition's module-docstring section); this engine's
        # automatic transition fire only runs when it's False (the
        # sequencer's shipped default).
        from spectra.services import sequencer_store
        return sequencer_store.load_config().enabled

    async def _default_fire_response(self, event_class: str, intensity: float,
                                     gap_ms: Optional[int] = None) -> None:
        from spectra.services import engine
        # via_trigger=True: this call only ever happens for a trigger
        # _trigger_allowed already gated (necessarily source=="authored"),
        # so it must reach the real response engine whenever the room is
        # at "full" OR "triggers_only" — see engine.fire_response_event's
        # own docstring for the dual-path reasoning. gap_ms is the
        # SEPARATE charge/lull OVERRIDE BLEND stretch input (this
        # engine's own _next_trigger_gap_ms) — orthogonal to via_trigger,
        # threaded through unconditionally (None for a flare/drop, same
        # as always).
        await engine.fire_response_event(event_class, intensity,
                                         gap_ms=gap_ms, via_trigger=True)

    async def _default_fire_scene_update(self, intensity: float) -> None:
        from spectra.services import engine
        await engine.fire_scene_update_event(intensity)

    async def _default_select_color_set(self, set_id: str) -> None:
        from spectra.services import color_set_groups, color_sets, engine
        from spectra.services.room_controls import load_room_controls
        # §10 — a Group reference resolves to its picked member. Fetched
        # RAW (not via resolve_ref) so mode availability (owner ask
        # 2026-08-17) can gate the GROUP ITSELF before any member
        # substitution — resolve_ref's own hard-fail semantics stay for a
        # genuinely unknown id; a reference that resolves fine but is
        # currently disabled or mode-gated out (the card itself, or every
        # member) is a quiet skip instead, matching every other automatic
        # pick's degrade-gracefully posture. A stored trigger firing is an
        # AUTOMATIC path (he authored it earlier, he is not pressing a
        # button now), so disabled gates it hard — exactly as a stored
        # fire_scene trigger naming a disabled SCENE is gated at
        # fire_scene_by_id.
        card = color_sets.get_by_id(set_id)
        if card is None:
            raise ValueError(f"colour set '{set_id}' not found")
        room_mode = load_room_controls().display_mode
        gated = color_set_groups.resolve_for_fire_mode_gated(card, room_mode)
        if gated is None:
            logger.info("select_color_set trigger: '%s' disabled, unusable, "
                       "or unavailable in display_mode=%s — skipped",
                       card.name, room_mode)
            return
        await engine.conductor.apply_set_directly(gated)

    async def _default_auto_generate(self, uri: str) -> None:
        # Off the event loop entirely (candidate_moments can rescan
        # analysis_reader's whole shape index on a miss) and serialized
        # against any other song's concurrent auto-generation, so two songs
        # starting close together can't interleave trigger_store's
        # read-modify-write file cycle.
        from spectra.services import midsong_generator
        async with _get_generation_lock():
            result = await asyncio.to_thread(midsong_generator.generate_for_song, uri)
        if result.get("added"):
            logger.info("auto-generate: seeded %d mid-song trigger(s) for %s "
                        "(no timeline visit)", result["added"], uri)

    # ── lead-time alignment (his ask, 2026-08-19) ─────────────────────────

    def _default_lead_ms(self, trig: SpectraTrigger) -> int:
        """How many ms EARLY to fire this trigger so its transition/switch
        lands on the trigger's own timestamp instead of starting there.
        Dispatches by action kind; every other kind (select_color_set,
        fire_scene_update) is an instant apply with nothing to land early —
        0, unchanged."""
        a = trig.action
        if a.kind == "fire_scene":
            if a.scene_id is not None:
                return self._scene_transition_lead_ms(a)
            # LOOKAHEAD (2026-08-19): a.scene_id is None on every one of his
            # 22,013 real fire_scene triggers — the plain rule above never
            # engages for him at all, because it deliberately refuses to
            # guess an unresolved pick. _pin_for resolves that pick EARLY
            # instead (once, cached, reused verbatim at fire — see its own
            # docstring) so the lead can be computed from a real target.
            pin = self._pin_for(trig)
            return pin.lead_ms if pin is not None else 0
        if a.kind == "fire_response":
            return self._response_switch_lead_ms(a)
        return 0

    def _scene_transition_lead_ms(self, a) -> int:
        """A fire_scene action's lead when scene_id is already known
        (hand-picked, or committed early by LOOKAHEAD — see
        _scene_transition_lead_ms_for): anchor_frac x crossfade_ms, so a
        registered phased effect's own payoff (services/transition_phases)
        or — the generalization his ask adds on top of legacy's own
        registry-only behaviour, see that module's docstring — the plain
        0.5 MID-POINT of an ordinary crossfade lands on the trigger.

        Conservative like legacy's own _entry_transition_lead_ms: an
        UNRESOLVED pick (scene_id=None) yields NO lead rather than a guess,
        mirroring legacy's own "unresolved random branch" rule — LOOKAHEAD
        (_pin_for) is what turns that guess into a real, early-committed
        resolution before this function ever runs."""
        if a.scene_id is None:
            return 0
        return self._scene_transition_lead_ms_for(a.scene_id, a.intensity)

    def _scene_transition_lead_ms_for(self, scene_id: str, raw_intensity: float) -> int:
        """The lead computation itself, given a KNOWN scene_id — shared by
        the resolved-scene_id path above and LOOKAHEAD's early pin (below).
        Peeks Force Scene's redirect (room_controls) so the lead matches
        whatever will actually fire, same as legacy's own plan-time member
        peeking for scene_group redirects."""
        from spectra.services import room_controls, scene_compiler, scene_store
        from spectra.services.binding_resolver import FireContext

        controls = room_controls.load_room_controls()
        if controls.force_scene_enabled and controls.force_scene_scene_id:
            if scene_store.get_by_id(controls.force_scene_scene_id) is not None:
                scene_id = controls.force_scene_scene_id
        scene = scene_store.get_by_id(scene_id)
        if scene is None:
            return 0
        intensity = self._render_intensity(raw_intensity)
        crossfade_ms = (scene.entry_ramp_ms or controls.global_transition_ms
                        or room_controls.scene_transition_ms(controls, intensity))
        if crossfade_ms <= 0:
            return 0
        resolved = scene_compiler.resolve_scene(scene, FireContext(intensity, rng=self._rng))
        writes = scene_compiler.compile_scene(resolved, color_set=None)
        virtuals = self._live_virtuals()
        # Multiple matching switches take the max anchor (legacy's own
        # rule: the dominant transition lands on the trigger, shorter ones
        # bloom a hair early). 0.0 (nothing registered on any write) falls
        # back to the 0.5 midpoint — the one behaviour this build adds on
        # top of the ported registry itself.
        anchor = 0.0
        for w in writes:
            cur = virtuals.get(w["virtual_id"])
            cur_type = cur.effect_type if cur is not None else None
            anchor = max(anchor, transition_phases.anchor_frac(cur_type, w["effect_type"]))
        if anchor == 0.0:
            anchor = 0.5
        return min(round(anchor * crossfade_ms), transition_phases.MAX_LEAD_MS)

    # ── LOOKAHEAD: early scene-pick commitment (his ask, 2026-08-19) ────────
    #
    # The danger his ask names explicitly: a lookahead is a PREDICTION of a
    # decision that today only happens at fire time, and a prediction can be
    # wrong. The design below does not actually predict anything — it moves
    # the DECISION itself earlier, once, and never repeats it. _pin_for
    # draws a real pick from the SAME kernel/pool functions _fire() would
    # otherwise call, the FIRST time (and only the first time) a trigger
    # comes within LOOKAHEAD_HORIZON_MS; that pick is cached and _fire()
    # reuses it VERBATIM — there is no second draw for it to disagree with.
    # The only way this could still show the wrong scene is if the picked
    # scene stops being legitimate to fire between the pin and the fire (it
    # gets disabled, the room leaves its display_mode, Force Scene points
    # elsewhere) — _pin_still_valid checks exactly that, narrowly, right
    # before the pin is used for either the lead calculation or the fire
    # itself. Failing that check throws the pin away and falls through to
    # today's exact behaviour: a fresh, real draw at (or after) the
    # trigger's own nominal timestamp, with zero lead — late, never wrong.

    def _pin_for(self, trig: SpectraTrigger) -> Optional[_PinnedPick]:
        """The trigger's committed early pick — resolved ONCE, right now,
        the first time this is called for a given trigger id, then cached
        (positively or negatively — see __init__) and never re-drawn.
        Called every tick a trigger sits inside LOOKAHEAD_HORIZON_MS
        (tick()'s own MAX_LEAD_MS guard, reused as the horizon — see that
        constant's docstring); every call after the first is a cheap cache
        read plus _pin_still_valid's narrow revalidation, not a new draw."""
        if trig.id in self._pins:
            pin = self._pins[trig.id]
            return pin if (pin is not None and self._pin_still_valid(pin)) else None
        a = trig.action
        if a.kind != "fire_scene" or a.scene_id is not None:
            return None  # not LOOKAHEAD-eligible; nothing to cache
        scene_id = (self._select_scene_from_pool(a.scene_pool) if a.scene_pool
                   else self._select_scene(a.intensity))
        if scene_id is None:
            # Ladder terminated at stay, or an empty/all-vetoed pool: a
            # real, deliberate "nothing" — cache it so this is never
            # retried (retrying a probabilistic draw until it stops saying
            # "nothing" would silently raise how often this trigger fires
            # at all, compared to today's single draw). _fire() still gets
            # its own single fresh draw at the nominal time, unaffected.
            self._pins[trig.id] = None
            return None
        from spectra.services import room_controls
        controls = room_controls.load_room_controls()
        pin = _PinnedPick(
            scene_id=scene_id,
            lead_ms=self._scene_transition_lead_ms_for(scene_id, a.intensity),
            force_scene=(controls.force_scene_enabled, controls.force_scene_scene_id),
        )
        self._pins[trig.id] = pin
        return pin if self._pin_still_valid(pin) else None

    def _pin_still_valid(self, pin: _PinnedPick) -> bool:
        """Cheap, narrow revalidation — NOT a re-draw (see _pin_for). Mirrors
        exactly what scene_sequencer.fire_scene_by_id itself would gate on
        for this scene_id (disabled, mode availability) plus the Force
        Scene timing-quality check (_PinnedPick.force_scene's own
        docstring). Any of these failing means the world moved since the
        pin was made — LOOKAHEAD gets out of the way entirely (0 lead,
        _fire() re-resolves fresh) rather than firing, or timing, a stale
        pick."""
        from spectra.services import mode_availability, room_controls, scene_store
        scene = scene_store.get_by_id(pin.scene_id)
        if scene is None or getattr(scene, "disabled", False):
            return False
        controls = room_controls.load_room_controls()
        if not mode_availability.available_in_room_mode(
                getattr(scene, "display_availability", "default"), controls.display_mode):
            return False
        if (controls.force_scene_enabled, controls.force_scene_scene_id) != pin.force_scene:
            return False
        return True

    def _response_switch_lead_ms(self, a) -> int:
        """A fire_response action's lead — two DIFFERENT anchor rules by
        event class (his ruling, settled 2026-08-20 after Black Hole was
        tried and then withdrawn as a "known-good" reference for drop
        timing specifically — data/drops-still-fire-early-star-does-not-
        explode/: MOMENTARY FLARES anchor their first switch's END to the
        mark ('the first switch must finish on the trigger, then the hold,
        then the flip back after the trigger mark') — only a MOMENTARY
        kind's param move onto a registry-smooth target actually takes time
        to switch (scene_response.DICE_REROLL_GLIDE_MS), so that's the only
        case worth firing early for; an instant jump already finishes at
        fire time with zero lead needed.

        DROPS/explosions anchor their START to the mark instead — 'an
        explosion begins on the trigger mark rather than before it'. A drop
        therefore ALWAYS gets zero lead, structurally, before the momentary-
        glide check below is ever consulted — not merely because none of
        his real drop bands happen to carry a qualifying momentary+params
        kind today (proven true for his four real scenes in
        scripts/check_triggers.py, but that was incidental, not
        guaranteed). Without this explicit branch, a future drop band that
        added such a kind would silently start borrowing the momentary
        rule's END-anchor lead — exactly the anchor a drop must never take.
        Charge/lull are unaffected either way (still end-anchored like
        flare) — this settlement was about drop specifically, not the
        wider phase-driven family, and must not leak into it.

        Two independent contributors, taken as a MAX (mirrors
        _scene_transition_lead_ms_for's own max-across-virtuals shape): a
        registry-smooth momentary param glide always needs the fixed
        DICE_REROLL_GLIDE_MS; a color_rotate kind needs its own
        INTENSITY-SCALED ramp-in (color_rotate_lead_ms — a different
        function, not folded into momentary_switch_would_glide, because
        its duration varies by intensity where the dice-glide's doesn't —
        see that function's own docstring). Either, both, or neither may
        apply to a given band; every band on his real scenes today only
        ever hits the dice-glide branch (or neither) — color_rotate is
        declared, never attached, by this build's own scope."""
        if a.event_class == "drop":
            return 0
        from spectra.services.scene_response import (DICE_REROLL_GLIDE_MS,
                                                      color_rotate_lead_ms,
                                                      momentary_switch_would_glide)
        scene = self._active_scene()
        if scene is None:
            return 0
        intensity = self._render_intensity(a.intensity)
        virtuals = self._live_virtuals()
        lead = color_rotate_lead_ms(scene, a.event_class, intensity, virtuals)
        if momentary_switch_would_glide(scene, a.event_class, intensity, virtuals):
            lead = max(lead, DICE_REROLL_GLIDE_MS)
        return lead

    def _default_response_offset_ms(self, a) -> int:
        """A fire_response action's authored FLARE-KIND offset (his ask,
        2026-08-21 — the firing-path half of the flare scrubbing-preview's
        trigger_offset_ms drag): the FlareKind.trigger_offset_ms the band
        this fire would select carries, HIS sign convention (negative =
        fire earlier, positive = fire later). Mirrors
        _response_switch_lead_ms's own reads exactly — the ACTIVE scene
        (the scene whose kinds will actually fire) at the RENDER intensity
        (the same _render_intensity(a.intensity) the real fire hands
        on_event, so this peek selects the same band the fire will) — and
        delegates the band walk + multi-kind aggregation to
        scene_response.band_trigger_offset_ms (see its docstring for the
        min-over-nonzero rule and why a drop band's offset IS honoured
        where the lead's drop rule is not). No active scene = 0, the
        conservative nothing-to-read answer, same as the lead's own."""
        from spectra.services.scene_response import band_trigger_offset_ms
        scene = self._active_scene()
        if scene is None:
            return 0
        return band_trigger_offset_ms(scene, a.event_class,
                                      self._render_intensity(a.intensity))

    @staticmethod
    def _live_virtuals() -> dict:
        from spectra.services import engine
        return engine.responses.conductor.virtuals

    @staticmethod
    def _active_scene():
        from spectra.services import engine
        return engine.responses.conductor.scene


trigger_engine = TriggerEngine()
