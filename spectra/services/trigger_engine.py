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
                       what its build ends on — its own lull or drop when
                       it has one, whatever sits between, else the next
                       trigger this song will fire
                       (_phase_partner_gap_ms, spectra/services/
                       phase_partner.py) — OVERRIDE BLEND's dynamic ramp
                       stretch (scene_response._phase_ramp_ms), 2026-08-20.
                       A bridge-classified flare carries no such gap; drop
                       is never stretched either way.
  select_color_set      drift_conductor.apply_set_directly — the SAME
                       manual-apply surface POST /api/room-color/apply uses.
  fire_scene_update      engine.fire_scene_update_event — UPDATE (data/
                       spectra-trigger-migration-scoping RULING.md): a
                       major change WITHIN the active scene, not band-
                       gated like fire_response. Reset is the same action
                       as update (his correction — one behaviour).

ENERGY (2026-10-28, the Admiral's Energy plan — spectra/services/
energy.py is the binding statement): every trigger's own intensity is
ENERGY — the song's normalized section energy with the Mark math
(the song's genre+bass scale, intensity_scale.py) already applied
once, inside energy.py's own mark_math. `_energized()` resolves it onto
a copy of the trigger before both the lead/offset peeks and the fire,
so SELECTION (_select_scene, when a generated trigger's scene_id is
None) and the FIRE both read the identical Energy value —
selection_kernel.py's own genre_mult is a per-candidate weight on the
pick, not a second scaling of the x position, so this is not the old
double count. _render_intensity/_default_render_intensity is now the
identity: applying the Mark again at this seam would apply it twice.

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

PLANNED SCENE CHANGES WITHOUT STORAGE (2026-10-08, data/drop-scene-variety-
plan/report.md option A): a song carrying his own triggers is never
auto-generated, so under "Transitions + analysed" it used to hold no
analysed scene change at all — one scene, picked at song start, for the
whole song, while the markers drew the planner's kept cues. tick() now
fires the cached plan's KEPT cues (_scene_cue_plan, the same list GET
/api/analysed-plan draws) as synthetic generated fire_scene triggers
whenever analysed events apply to the song and it holds no enabled stored
generated scene cue (analysed_flares.has_stored_scene_cues) — the analysed
flares' shape: derived at play time, never stored, the planned-cue dwell
tolerance, the drop sequences' protected windows, the LOOKAHEAD pin and
lead exactly as a stored cue gets them. A song that does hold stored
generated cues fires those and never the plan, so the two never double-
fire; "My triggers only" on a song of his is untouched.

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
    first, not just happen to evaluate to 0 today. Since 2026-10-12 the
    MARK a drop begins on is itself relocated by the room's drop timing
    offset (default -400 ms, spectra/services/drop_timing.py) — an OFFSET,
    summed into target_ms; the drop's lead is still 0.
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
import time
from dataclasses import dataclass, replace
from random import Random
from typing import Any, Awaitable, Callable, Optional

from spectra.models.trigger import FireResponseAction, FireSceneAction, SpectraTrigger
from spectra.services import energy as energy_mod
from spectra.services import (analysed_flares, drop_firing, drop_sequences,
                               drop_switch, drop_timing, phase_partner,
                               pre_drop_play, transition_phases,
                               trigger_store)

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

# THE DROP COLOUR CHANGE ACROSS A PRE-DROP starts one trigger tick EARLY
# (LEAD family, positive = earlier; docs/SPECTRA_TIMING_CONVENTIONS.md):
# his words, "I want the color change to hit on (before) the pre-drop".
# A tick-crossing fire lands up to one TICK_S after its target; leading by
# one tick puts it at most one tick BEFORE the pre-drop, never after it —
# inside the breath's black that ends on the pre-drop for every effect
# that plays one. Its glide is timed from the tick that fires it to the
# drop's target, so it lands on the drop whatever the lead.
PRE_DROP_COLOUR_LEAD_MS = round(TICK_S * 1000)


@dataclass(frozen=True)
class PreDropTold:
    """What one lull carrying a pre-drop was told (spectra/services/
    pre_drop_play.py): whose pre-drop (`key` — a sequence key, or
    "his:<drop trigger id>"), the response engine's verdict, and the
    show-clock targets it was computed against — the pre-drop's and the
    drop's, both moved with the drop. A pre-drop that PLAYS is what the
    drop's colour change fades across (_tick_drop_colour_fades)."""
    key: str
    pre_target_ms: int
    drop_target_ms: int
    kind: str
    intensity: float
    verdict: dict
    seq: Optional[drop_firing.FiringSequence] = None
    fire_mode: Optional[str] = None

    @property
    def plays(self) -> bool:
        return bool(self.verdict.get("plays"))


@dataclass(frozen=True)
class _PreDropPlan:
    candidate: pre_drop_play.PreDropCandidate
    pre_target_ms: int
    drop_target_ms: int
    intensity: float
    seq: Optional[drop_firing.FiringSequence] = None
    fire_mode: Optional[str] = None


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


SHOW_CUE_SEEK_SKIP_MS = 3_000
"""A Light Show High/Low cue crossed this far in the past (a forward seek
over it) is skipped, never fired late."""


async def _no_show_cue(_level: str, _cue_ms: int, _ahead_ms: int) -> None:
    return None


def _get_generation_lock() -> asyncio.Lock:
    global _generation_lock
    if _generation_lock is None:
        _generation_lock = asyncio.Lock()
    return _generation_lock


# next_colour_cue refuses a show clock not fed for this long (tick() runs
# every TICK_S while a song plays).
POSITION_STALE_S = 3.0


def _phase_class(trig: SpectraTrigger) -> Optional[str]:
    """A stored trigger's phase class ("charge"/"lull"/"drop") for the
    phase-partner rule, or None for anything that writes no phase."""
    a = trig.action
    if a.kind == "fire_response" and a.event_class in phase_partner.PHASE_ORDER:
        return a.event_class
    return None


def _colour_landed(record: Optional[dict]) -> bool:
    """A drop's colour change is on the lights: it landed now, or its
    pre-drop's fade landed on this drop."""
    return bool(record) and record.get("result") in ("jumped", "faded_at_pre_drop")


def drop_colour_brief(record: dict) -> dict:
    """The drop colour change's outcome as a drop's show-log entry carries it
    (the Review page names it): what happened, from which set to which, how
    far round the wheel, why that set, the band the pick used (spread_deg —
    the page words "none in the band" from it, never from the default), and
    any hold — each key only when the record has it."""
    jump = record.get("color_jump") or {}
    out: dict[str, Any] = {"result": record.get("result")}
    for k in ("held_for", "reason", "moment", "ramp_ms", "rung",
              "distance_deg", "spread_deg", "from_set_id", "forced_color",
              "pool_scene"):
        if record.get(k) is not None:
            out[k] = record[k]
    if jump.get("result") == "jumped":
        out["to_set_id"] = jump.get("picked_id")
        out["to_set_name"] = jump.get("set_name")
    if record.get("pre_drop") is not None:
        out["pre_drop"] = record["pre_drop"]
    return out


@dataclass(frozen=True)
class NextCue:
    """The next colour/scene cue on the show clock (next_colour_cue).
    at_ms and position_ms are both show-clock song ms; set_id is the colour
    set the cue itself names, when it names one."""
    uri: str
    key: str
    at_ms: int
    position_ms: int
    kind: str
    source: str
    intensity: Optional[float] = None
    set_id: Optional[str] = None


class TriggerEngine:
    """One instance per process (singleton below). Constructor injectables
    exist for the executable spec only — production uses the defaults."""

    def __init__(
        self, *,
        list_triggers: Callable[[str], list[SpectraTrigger]] | None = None,
        fire_scene: Callable[..., Awaitable[Any]] | None = None,
        fire_planned_scene: Callable[..., Awaitable[Any]] | None = None,
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
        auto_refresh: Callable[[str], Awaitable[Any]] | None = None,
        lead_ms: Callable[[SpectraTrigger], int] | None = None,
        response_offset_ms: Callable[[Any], int] | None = None,
        drop_offset_ms: Callable[[], int] | None = None,
        intensity_event: Callable[[], None] | None = None,
        analysed_plan: Callable[[str, list], Any] | None = None,
        fire_analysed_flare: Callable[[float], Awaitable[Any]] | None = None,
        analysed_color: Callable[[float, float, Optional[str]], Awaitable[Any]] | None = None,
        colour_cue: Callable[[], None] | None = None,
        drop_view: Callable[[str, list], dict] | None = None,
        drop_revision: Callable[[], Any] | None = None,
        fire_sequence: Callable[[str, float, Optional[int]], Awaitable[Any]] | None = None,
        drop_testing: Callable[[], bool] | None = None,
        drop_played: Callable[[dict], None] | None = None,
        drop_colour: Callable[..., Awaitable[Any]] | None = None,
        switch_showing: Callable[[], Optional[drop_switch.Showing]] | None = None,
        switch_settings: Callable[[], drop_switch.SwitchSettings] | None = None,
        switch_blocker: Callable[[], Optional[str]] | None = None,
        switch_pick: Callable[[float], Callable] | None = None,
        fire_drop_switch: Callable[[str, float], Awaitable[Any]] | None = None,
        rearm_phase: Callable[[str, float, int], Awaitable[Any]] | None = None,
        clock: Callable[[], float] | None = None,
        rng: Random | None = None,
        energy_for: Callable[[str, SpectraTrigger], Optional[float]] | None = None,
    ) -> None:
        self._list_triggers = list_triggers or trigger_store.list_for_song
        # ENERGY AT A TRIGGER'S OWN MOMENT (spectra/services/energy.py, the
        # Energy plan's D2/D4): what every pick, lead peek and fire of that
        # trigger reads — never the trigger's stored ⚡ value. None
        # (unknowable) holds energy.NEUTRAL.
        self._energy_for = energy_for or self._default_energy_for
        self._energy_injected = energy_for is not None
        self._fire_scene = fire_scene or self._default_fire_scene
        # PLANNED SCENE CHANGES (2026-10-04): a generated cue the scene-change
        # planner placed fires with dwell.PLANNED_CUE_TOLERANCE_S of the hold
        # allowed to remain. A spec that injects fire_scene alone keeps
        # receiving every fire through it, unchanged.
        self._fire_planned_scene = (fire_planned_scene
                                    or (self._default_fire_planned_scene
                                        if fire_scene is None else fire_scene))
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
        self._auto_refresh = auto_refresh or self._default_auto_refresh
        self._refreshing: set[str] = set()
        self._lead_ms = lead_ms or self._default_lead_ms
        self._response_offset_ms = response_offset_ms or self._default_response_offset_ms
        # THE DROP TIMING OFFSET (2026-10-12, spectra/services/drop_timing.py
        # is the binding statement): every fire_response drop's target moves
        # by this much (OFFSET family, negative = earlier), and a build
        # ending on a drop is told the gap to the shifted mark. Read live
        # (room controls + the showing scene's own override) — a test injects
        # a constant. `_drop_applied` remembers, per drop trigger id, the
        # offset tick() actually applied (after drop_timing's clamp), so a
        # Fireworks meld's late cut is measured from the drop's real fire.
        self._drop_offset_ms = drop_offset_ms or self._default_drop_offset_ms
        self._drop_applied: dict[str, int] = {}
        self._tick_drop_offset: Optional[int] = None
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
        # ANALYSED COLOUR (owner ask 2026-09-25): the colour moment every
        # generated cue on an untriggered song carries — see
        # _fire_analysed_color. A safe no-op default, wired to the
        # production engine explicitly in services/engine.py — the same
        # reasoning as _intensity_event above: a side call on every
        # generated fire_scene is easy to forget to stub, and a forgotten
        # stub must not reach real storage.
        self._analysed_color = analysed_color or self._no_analysed_color
        # TRIGGER-TIMED COLOUR JOURNEY (2026-09-26): called after a cue that
        # changes colour or scene fires, so the drift conductor picks the
        # NEXT horizon at once instead of up to a leg later. Safe no-op
        # default, wired in services/engine.py — same reasoning as the two
        # hooks above.
        self._colour_cue = colour_cue or (lambda: None)
        # How many times the journey has been told (_notify_colour_cue) —
        # lets one fire tell it at most once (a drop whose colour change and
        # cut land together: each would otherwise run its own journey leg).
        self._colour_cues_told = 0
        self._clock = clock or time.monotonic
        # When _last_position_ms was last fed (clock time) — next_colour_cue
        # refuses a stale show clock rather than time a walk against it.
        self._position_at: Optional[float] = None
        # (uri, has_authored) from the latest read of this song's trigger
        # list — tick() already parses it every TICK_S, so readers
        # (song_untriggered, _fire) reuse that answer instead of a second
        # ~9.5MB parse.
        self._authored_cache: Optional[tuple[str, bool]] = None
        self._generating: set[str] = set()
        self._rng = rng or Random()

        # ANALYSED FLARES (2026-09-26, spectra/services/analysed_flares.py):
        # the transitions that did not make the density cut, fired as the
        # current scene's flare band. Planned ONCE per song in a worker
        # thread (the analysis read is disk I/O and tick() runs on the
        # event loop), cached for the current URI only, and fed into tick()
        # as synthetic fire_response triggers — never stored.
        self._analysed_plan = analysed_plan or self._default_analysed_plan
        self._fire_analysed_flare = (fire_analysed_flare
                                     or self._default_fire_analysed_flare)
        self._flare_plan_uri: Optional[str] = None
        self._flare_triggers: list[SpectraTrigger] = []
        self._flare_ids: set[str] = set()
        self._flare_planning: Optional[str] = None
        # Bumped by invalidate_analysed_plan: a plan computed before a
        # re-analysis rewrote this song's stored cues is discarded on
        # arrival rather than cached over the fresher state.
        self._flare_epoch = 0
        # The same plan's KEPT cues — the planned scene changes. Read by the
        # colour journey (next_colour_cue) and the markers, and FIRED by
        # tick() as synthetic generated fire_scene triggers while the song
        # holds no stored generated scene cue (the module docstring's
        # PLANNED SCENE CHANGES WITHOUT STORAGE).
        self._scene_cue_plan: list = []
        self._scene_cue_triggers: list[SpectraTrigger] = []
        self._scene_cue_ids: set[str] = set()
        # generator_key -> (rank, rank_of) for the cached plan's actions —
        # read by GET /api/analysed-plan's rank markers (cached_plan_ranks).
        self._plan_ranks: dict = {}

        # DROP SEQUENCES (2026-10-06, drop-detection plan phase 5 —
        # spectra/services/drop_firing.py is the binding statement). The
        # song's merged drop-sequence view is read through `_drop_view`
        # (drop_sequences.view over the trigger list tick() already holds:
        # one small stat-cached file, no analysis I/O) and memoised on the
        # store's revision plus his own phase triggers, so a tick costs one
        # stat. Each firing member becomes a synthetic fire_response trigger
        # ("drop-seq:<key>:<class>") fed into tick() beside the stored ones;
        # `_seq_meta` maps those ids back to (sequence, class, mode) for
        # _fire — the mode is the tick's own effective mode at the moment
        # the synthetic trigger was built, so `_fire` can resolve the SAME
        # mode-gated member set (`seq.members(mode)`/`seq.gap_ms(cls,
        # mode)`) the tick that fired it already decided on.
        # `_drop_windows` are the protected windows tick() holds analysed
        # scene changes and flares out of.
        self._drop_view = drop_view or self._default_drop_view
        self._drop_revision = drop_revision or drop_sequences.revision
        self._fire_sequence = fire_sequence or self._default_fire_sequence
        # DROP TESTING (2026-10-26, RoomControlState.drop_testing — the Home
        # Drops panel's Testing toggle): read once per tick and folded into
        # the memo key below, so a suggestion starts or stops firing on the
        # first tick after he flips it. `drop_played` is told {"uri", "key",
        # "at_ms", "position_ms"} each time a drop fires (a sequence's, or
        # one of his own authored drop triggers, key "his:<id>") — the
        # panel's "just played" row; a no-op unless engine.py wires it to
        # the SPECTRA websocket. `last_drop` is the same record, read by
        # status() as the push's backstop.
        self._drop_testing = drop_testing or self._default_drop_testing
        self._drop_played = drop_played or (lambda _record: None)
        self.last_drop: Optional[dict] = None
        # THE DROP COLOUR CHANGE (2026-10-26, predrop plan step 2 —
        # spectra/services/drop_colour.py is the pick, scene_response.
        # ResponseEngine.drop_color_change the precedence): every drop that
        # fires lands a colour set about opposite the one showing — on the
        # drop, before its drop-led cut and its own response
        # (_drop_colour_on_drop), or faded across its pre-drop when one plays
        # (_tick_drop_colour_fades — the verdict its lull reached, PreDropTold).
        # `drop_colour(selection_intensity, pool_scene_id, ramp_ms, moment,
        # analysed)` returns the outcome record; a safe no-op default wired to
        # engine.fire_drop_colour_event in services/engine.py (the
        # _analysed_color reasoning above). `_drop_colour_faded` maps a
        # sequence key to its pre-drop fade's record once that fade LANDED, so
        # its drop never changes colour twice; cleared with the fired-keys
        # memory (song change, rewind).
        self._drop_colour = drop_colour or self._no_drop_colour
        self._drop_colour_faded: dict[str, dict] = {}
        # THE PRE-DROP (spectra/services/pre_drop_play.py is the one rule):
        # what each lull carrying a pre-drop was told this play, keyed by
        # whose pre-drop it is (PreDropTold) — read by the colour fade, and
        # cleared with the fired-keys memory (song change, rewind).
        # `_his_pre_drops` is the memo's {his lull trigger id: HisPreDrop}:
        # his own grouped drops whose pre-drop may play.
        self._pre_drop_told: dict[str, PreDropTold] = {}
        self._his_pre_drops: dict[str, drop_firing.HisPreDrop] = {}
        # (uri, triggers) the current tick holds — his own lull's pre-drop
        # reads it rather than parsing triggers.json again mid-tick.
        self._tick_triggers: Optional[tuple[str, list]] = None
        self._drop_memo: Optional[tuple[tuple, tuple[list, list, list, dict]]] = None
        self._seq_meta: dict[str, tuple[drop_firing.FiringSequence, str, str]] = {}
        self._drop_windows: list[drop_firing.Window] = []
        # (uri, phase moments) from the same memo — THE LIGHT SHOW's own
        # "next drop / lull / charge" arms read it through
        # `phase_cue_moments` (show_arms.phase_moments' default seam). Keyed
        # by uri rather than cleared on a song change, so the previous
        # song's moments can never be read as this one's.
        self._phase_cues: tuple[Optional[str], list] = (None, [])

        # THE DROP-LED SCENE SWITCH (2026-10-08, spectra/services/
        # drop_switch.py is the binding statement): a drop sequence may be
        # the scene change — a hard cut ON its drop, or, as the stated
        # exception, early in its charge. Decided once per sequence at the
        # first member the clock fires (_decide_switch), executed at the
        # planned member or riding flare (_execute_switch), recorded per
        # song (_drop_history: which stint played which drop). Injectables
        # for the specs; production reads dwell, the room and the kernel.
        # A spec that injects fire_scene alone has the switch's cut land
        # through that fake (scene_id, None, intensity), never a real fire.
        self._switch_showing = switch_showing or drop_switch.default_showing
        self._switch_settings = switch_settings or drop_switch.default_settings
        self._switch_blocker = switch_blocker or drop_switch.default_blocker
        self._switch_pick = switch_pick or drop_switch.default_pick_target
        if fire_drop_switch is not None:
            self._fire_drop_switch = fire_drop_switch
        elif fire_scene is not None:
            self._fire_drop_switch = (
                lambda scene_id, intensity: fire_scene(scene_id, None, intensity))
        else:
            self._fire_drop_switch = self._default_fire_drop_switch
        self._rearm_phase = rearm_phase or self._default_rearm_phase
        self._switch_plans: dict[str, drop_switch.SwitchPlan] = {}
        self._switch_seqs: dict[str, tuple[drop_firing.FiringSequence, str]] = {}
        self._switch_done: set[str] = set()
        self._ride_ids: dict[str, str] = {}
        # THE FIREWORKS MELDS' late switches (drop_switch.py): armed at the
        # drop, cut swallow_delay_s after it ("after_drop") or on the next
        # big bass hit / its deadline ("next_hit"). `_late_pending` maps a
        # sequence key to its armed plan, `_hit_ids` the hit flare's
        # trigger id to that key (its fire cuts first, like a ride).
        self._late_pending: dict[str, drop_switch.SwitchPlan] = {}
        self._hit_ids: dict[str, str] = {}
        self._drop_history = drop_switch.DropHistory()
        # (trigger id, song ms) of every flare this tick may fire — the
        # candidates a cut can RIDE inside a charge (drop_switch.find_ride).
        self._tick_flares: list[tuple[str, int]] = []
        # (trigger id, song ms, intensity) of every ANALYSED flare this tick
        # may fire — the candidates for the next big bass hit
        # (drop_switch.next_big_hit).
        self._tick_hits: list[tuple[str, int, float]] = []

        # THE LIGHT SHOW's HIGH / LOW TRIGGERS (spectra/services/show_arms.py
        # and show_cues.py). Two hooks, both no-ops by default and wired in
        # services/engine.py (the _intensity_event precedent — a forgotten
        # stub costs nothing): `_show_cue_plan(uri)` returns this song's
        # (level, cue_ms, lead_ms) — never blocks; `_show_cue(level, cue_ms,
        # ahead_ms)` runs when the clock crosses `cue_ms - lead_ms` (or,
        # as a net, `cue_ms` itself), EXACTLY ONCE per approach via the same
        # fired-keys memory the stored triggers use. NO OFFSET FAMILY
        # applies: a cue is a song-time moment, and its lead is the show's
        # own finish-on-the-mark start (LEAD family, positive = earlier,
        # subtracted like _lead_ms).
        self._show_cue_plan: Callable[[str], list] = lambda _uri: []
        self._show_cue: Callable[[str, int, int], Awaitable[Any]] = _no_show_cue

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

        # THE RUNNING LOOP (2026-10-06, drop_sequences._changed's thread-
        # safety fix): remembered on every on_track_state/tick — both always
        # run on the event loop that drives this engine — so a caller on a
        # DIFFERENT thread (drop_sequences' own asyncio.to_thread worker)
        # can marshal a mutation back onto it instead of racing tick()'s own
        # reads of _flare_* state. None until the engine has run at least
        # once (construction happens at module import time, with no loop
        # running yet); a caller with no loop known falls back to a direct
        # call, matching every pre-existing single-threaded caller.
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _remember_loop(self) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """The event loop this engine's on_track_state/tick last ran on, or
        None if neither has run yet. See drop_sequences._changed."""
        return self._loop

    # ── feed (services/engine.py calls both) ─────────────────────────────

    async def on_track_state(self, uri: Optional[str]) -> None:
        """A URI change rearms the tick clock: last_position resets so the
        next tick anchors fresh at wherever it finds the position, never
        backfiring the song's history. A genuine song-to-song change (armed
        after the first URI ever seen; a stop/None neither fires nor
        disarms) additionally fires the automatic transition scene change —
        see the module docstring's _fire_transition section."""
        self._remember_loop()
        if uri != self._uri:
            self._uri = uri
            self._last_position_ms = None
            # A new song's trigger list is unrelated to the old one's — any
            # LOOKAHEAD pin from the previous song is dead weight, never a
            # reusable commitment (see _pin_for). The fired-keys memory
            # rearms with it.
            self._pins.clear()
            self._fired.clear()
            self._flare_plan_uri = None
            self._flare_triggers = []
            self._flare_ids = set()
            self._scene_cue_plan = []
            self._scene_cue_triggers = []
            self._scene_cue_ids = set()
            self._plan_ranks = {}
            self._seq_meta = {}
            self._drop_windows = []
            self._drop_colour_faded = {}
            self._pre_drop_told = {}
            self._his_pre_drops = {}
            self._forget_switches()
            self._drop_history = drop_switch.DropHistory()
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

    def song_untriggered(self) -> Optional[bool]:
        """True when the song playing carries NO authored trigger, False
        when it carries one, None when no song is known. Reuses tick()'s
        own read (_authored_cache) when it is for this song; one fresh read
        otherwise."""
        uri = self._uri
        if uri is None:
            return None
        cached = self._authored_cache
        if cached is None or cached[0] != uri:
            cached = (uri, self._song_has_authored_triggers(uri))
            self._authored_cache = cached
        return not cached[1]

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
        section).

        RE-ANALYSIS (2026-10-04, midsong_generator's RE-ANALYSIS section):
        a song that already holds GENERATED cues gets a background check on
        the same edge — if any of them was planned under a stale stamp, the
        song is re-planned and re-stored in one batched write. A song
        holding only his own triggers is never scheduled at all."""
        if not uri:
            return
        triggers = self._list_triggers(uri)
        if not triggers:
            if uri in self._generating:
                return
            self._generating.add(uri)
            asyncio.create_task(self._run_auto_generate(uri))
            return
        if uri in self._refreshing or not any(
                t.source == "generated" for t in triggers):
            return
        self._refreshing.add(uri)
        asyncio.create_task(self._run_auto_refresh(uri))

    async def _run_auto_refresh(self, uri: str) -> None:
        try:
            result = await self._auto_refresh(uri)
        except Exception:
            logger.exception("re-analysis: refreshing analysed cues failed for %s", uri)
            result = None
        finally:
            self._refreshing.discard(uri)
        if isinstance(result, dict) and result.get("status") == "refreshed":
            self.invalidate_analysed_plan(uri)

    def invalidate_analysed_plan(self, uri: Optional[str] = None) -> None:
        """Forget the cached analysed plan (flares + planned scene cues) for
        `uri` (None = whatever is cached), so the next tick re-plans it
        against the stored cues a re-analysis just rewrote."""
        if uri is not None and uri != self._flare_plan_uri and uri != self._flare_planning:
            return
        self._flare_epoch += 1
        self._flare_plan_uri = None
        self._flare_planning = None
        self._flare_triggers = []
        self._flare_ids = set()
        self._scene_cue_plan = []
        self._scene_cue_triggers = []
        self._scene_cue_ids = set()
        self._plan_ranks = {}

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
        self._remember_loop()
        if self._uri is None or position_ms is None:
            return []
        if self._last_position_ms is None:
            # Rearm: anchor one ms behind so a trigger sitting exactly AT
            # this position still fires, without backfiring further back.
            self._last_position_ms = position_ms - 1
        last = self._last_position_ms
        self._last_position_ms = position_ms
        self._position_at = self._clock()
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
            self._drop_colour_faded.clear()
            self._pre_drop_told.clear()
            # a sequence approached again is decided again
            self._forget_switches()
            return []  # rewind/seek back: silently rearmed via the line above
        # Cues run BEFORE the stored triggers in the same tick, so a set that
        # forces a scene or a colour governs the scene change landing on
        # that same moment.
        await self._tick_show_cues(last, position_ms)
        triggers = self._list_triggers(self._uri)
        self._tick_triggers = (self._uri, triggers)
        self._authored_cache = (self._uri,
                                any(t.source == "authored" for t in triggers))
        has_authored = self._authored_cache[1]
        mode = self._effective_mode_for_song(self._scene_change_mode(), triggers)
        candidates = triggers
        if analysed_flares.analysed_flares_allowed(mode, has_authored):
            candidates = triggers + self._analysed_flare_triggers(self._uri, triggers)
            if not analysed_flares.has_stored_scene_cues(triggers):
                candidates = candidates + self._planned_scene_triggers(self._uri)
        seq_trigs = self._sequence_triggers(self._uri, triggers, mode, has_authored)
        if seq_trigs:
            candidates = candidates + seq_trigs
        windows = self._drop_windows
        self._tick_drop_offset = None
        self._tick_flares = [
            (t.id, t.timestamp_ms + t.trigger_offset_ms) for t in candidates
            if t.enabled and t.action.kind == "fire_response"
            and getattr(t.action, "event_class", None) == "flare"
            and t.id not in self._seq_meta
            and (t.id in self._flare_ids or self._trigger_allowed(t, mode))]
        # one timeline read per tick for every analysed flare; a spec that
        # injects energy_for declares each moment's Energy through it instead
        hit_tl = (energy_mod.timeline(self._uri)
                  if self._flare_ids and not self._energy_injected else None)
        self._tick_hits = [
            (t.id, t.timestamp_ms + t.trigger_offset_ms,
             self._trigger_energy(t) if self._energy_injected
             else self._moment_energy(hit_tl, t))
            for t in candidates if t.enabled and t.id in self._flare_ids]
        # THE FIREWORKS MELDS: an armed late switch whose moment this tick
        # crosses cuts before anything else fires on it
        if self._late_pending:
            await self._tick_late_switches(last, position_ms)
        # THE DROP COLOUR CHANGE across a pre-drop that plays: a fade whose
        # pre-drop this tick reaches (one tick early) starts now.
        await self._tick_drop_colour_fades(last, position_ms)
        fired: list[SpectraTrigger] = []
        for trig in candidates:
            if not trig.enabled:
                continue
            if (trig.id not in self._flare_ids and trig.id not in self._seq_meta
                    and not self._trigger_allowed(trig, mode)):
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
            #     one. TWO sources, one per action kind, both authored by
            #     dragging a scrubbing preview's trigger-alignment marker:
            #     fire_scene reads the TARGET SCENE's own
            #     SceneV2.trigger_offset_ms (2026-08-27, the transition
            #     preview's drag — _scene_offset_ms below, and see that
            #     field's docstring for the one honest bound on an
            #     unresolved pick), fire_response reads the FLARE KIND
            #     offset (his ask, 2026-08-21 — "make the engine read the
            #     offset and work with the offset like we had in spot FX"): the
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
            if abs(trig.timestamp_ms - last) <= RESPONSE_OFFSET_HORIZON_MS:
                if trig.action.kind == "fire_response":
                    target_ms += self._response_offset_ms(trig.action)
                    # THE DROP TIMING OFFSET (drop_timing.py): a third
                    # OFFSET-family term for a DROP, summed like the two
                    # above — the one place a drop's moment moves. The
                    # drop's LEAD stays 0 (_response_switch_lead_ms), so
                    # fire_at == target_ms: it begins on the shifted mark.
                    if getattr(trig.action, "event_class", None) == "drop":
                        target_ms += self._drop_shift_ms(trig, triggers)
                elif trig.action.kind == "fire_scene":
                    target_ms += self._scene_offset_ms(trig)
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
            stored = trig
            if 0 <= target_ms - last <= LOOKAHEAD_HORIZON_MS:
                trig = self._energized(trig)
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
                held = self._held_by_drop_window(trig, target_ms, windows)
                if held is not None:
                    self._record_window_hold(trig, target_ms, held)
                    continue
                await self._fire(self._energized(trig))
                fired.append(stored)
        return fired

    # ── drop sequences (drop_firing.py) ──────────────────────────────────

    def _drop_state(self, uri: str, triggers: list[SpectraTrigger],
                    testing: bool = False) -> tuple[list, list, list, dict]:
        """(firing sequences, protected windows, phase moments, his
        pre-drops) for `uri` —
        mode-independent, memoised on the store's revision and his own
        phase triggers (the two things the view reads). A view that cannot
        be read fires nothing, protects nothing and has no phase moment,
        and says so once.

        The third element is drop_firing.phase_moments: where this song
        plays a charge/lull/drop, published for the Light Show's own
        "next drop / lull / charge" arms (`phase_cue_moments` below). It
        rides this memo rather than a second read because the view costs a
        full triggers.json parse and the cue plan is asked every tick."""
        marks = tuple(sorted(
            (t.id, t.timestamp_ms, t.trigger_offset_ms, t.enabled, _phase_class(t))
            for t in triggers
            if t.source == "authored" and _phase_class(t) is not None))
        try:
            rev = self._drop_revision()
        except Exception:
            rev = None
        key = (uri, rev, marks, bool(testing))
        if self._drop_memo is not None and self._drop_memo[0] == key:
            return self._drop_memo[1]
        try:
            view = self._drop_view(uri, triggers)
            state = (drop_firing.firing_sequences(view, testing),
                     drop_firing.windows_from_view(view, testing),
                     drop_firing.phase_moments(view, testing),
                     drop_firing.his_pre_drops(view, testing))
        except Exception:
            logger.exception("drop sequences: view unreadable for %s — none "
                             "fire and none protect on this song for now", uri)
            state = ([], [], [], {})
        self._drop_memo = (key, state)
        return state

    def _sequence_triggers(self, uri: str, triggers: list[SpectraTrigger],
                           mode: str, has_authored: bool) -> list[SpectraTrigger]:
        """This song's firing drop-sequence members as synthetic
        fire_response triggers — only the sequences the room's gate lets
        fire right now (drop_firing.fires_here), with `mode` resolving
        which members stand down alone (seq.members(mode) — a member
        within reach of a same-class authored mark that fires in THIS
        mode). Also refreshes `_seq_meta` and `_drop_windows`."""
        try:
            testing = bool(self._drop_testing())
        except Exception:                                # noqa: BLE001
            testing = False
        seqs, windows, moments, his_pre = self._drop_state(uri, triggers,
                                                           testing)
        self._drop_windows = windows
        self._his_pre_drops = his_pre
        # Published for show_arms.cue_plan (the Light Show's phase arms) —
        # keyed by uri so a stale list can never be read as this song's.
        self._phase_cues = (uri, moments)
        out: list[SpectraTrigger] = []
        meta: dict[str, tuple[drop_firing.FiringSequence, str, str]] = {}
        for seq in seqs:
            if not drop_firing.fires_here(seq, mode, has_authored):
                continue
            for cls, ms in seq.members(mode):
                tid = seq.trigger_id(cls)
                meta[tid] = (seq, cls, mode)
                out.append(SpectraTrigger(
                    id=tid, timestamp_ms=ms,
                    source="authored" if seq.his else "generated",
                    action=FireResponseAction(event_class=cls,
                                              intensity=seq.intensity)))
        self._seq_meta = meta
        return out

    def _held_by_drop_window(self, trig: SpectraTrigger, target_ms: int,
                             windows: list) -> Optional[drop_firing.Window]:
        """THE PROTECTED WINDOW at fire time (drop_firing.py): a GENERATED
        scene change landing inside a window, or an analysed flare in a
        lull or on a drop, is held back. His own triggers and the
        sequences' own members are never held."""
        if not windows or trig.id in self._seq_meta:
            return None
        if trig.source == "generated" and trig.action.kind == "fire_scene":
            return drop_firing.holding_window(windows, target_ms)
        if trig.id in self._flare_ids:
            return drop_firing.silencing_window(windows, target_ms)
        return None

    def _record_window_hold(self, trig: SpectraTrigger, target_ms: int,
                            window: drop_firing.Window) -> None:
        what = "analysed flare" if trig.id in self._flare_ids else "analysed scene change"
        logger.info("drop sequence %s: %s @ %dms held back by its protected "
                    "window (%d–%dms)", window.key, what, target_ms,
                    window.start_ms, window.end_ms)
        self.last_fire = {"id": trig.id, "kind": trig.action.kind, "ok": True,
                          "held_by": window.key}
        from spectra.services import fire_history
        fire_history.record_fire(
            "deferred", "drop_window",
            {"trigger_id": trig.id, "what": what, "window": window.key,
             "window_source": window.source, "start_ms": window.start_ms,
             "drop_ms": window.drop_ms, "end_ms": window.end_ms},
            uri=self._uri, position_ms=self._last_position_ms)

    async def _tick_show_cues(self, last: int, position_ms: int) -> None:
        try:
            plan = self._show_cue_plan(self._uri) or []
        except Exception:
            logger.exception("light show: cue plan failed")
            return
        for level, cue_ms, lead in plan:
            key = (f"show-cue:{level}", int(cue_ms))
            if key in self._fired:
                continue
            fire_at = cue_ms - max(0, int(lead))
            if last < fire_at <= position_ms or last < cue_ms <= position_ms:
                self._fired.add(key)
                if position_ms - cue_ms > SHOW_CUE_SEEK_SKIP_MS:
                    # A forward seek jumped over the mark: a blackout armed
                    # for the drop must not land a minute after it.
                    continue
                try:
                    await self._show_cue(level, int(cue_ms), int(cue_ms - position_ms))
                except Exception:
                    logger.exception("light show: %s cue hook failed", level)

    def _analysed_flare_triggers(self, uri: str,
                                 stored: list[SpectraTrigger]) -> list[SpectraTrigger]:
        """This song's analysed flare moments as synthetic fire_response
        triggers, or [] while the plan is still being computed (the first
        tick(s) of a song — a flare in the song's first moments is never
        lost to this, since the opening section is never a candidate)."""
        if self._flare_plan_uri == uri:
            return self._flare_triggers
        if self._flare_planning != uri:
            self._flare_planning = uri
            asyncio.create_task(self.plan_analysed_flares(uri, stored))
        return []

    def _planned_scene_triggers(self, uri: str) -> list[SpectraTrigger]:
        """The cached plan's KEPT scene cues as synthetic generated
        fire_scene triggers (the module docstring's PLANNED SCENE CHANGES
        WITHOUT STORAGE), or [] while the plan is still being computed —
        _analysed_flare_triggers, called first on the same tick, schedules
        that planning for both lists."""
        if self._flare_plan_uri == uri:
            return self._scene_cue_triggers
        return []

    def phase_cue_moments(self, uri: Optional[str]) -> Optional[list]:
        """Where `uri` plays a charge / lull / drop (drop_firing.
        PhaseMoment), or None when this engine has not worked that out for
        `uri` — a DIFFERENT answer from the empty list, which means the
        song genuinely has none (so the Light Show's armed board can say
        "none on this song" rather than implying it is still thinking).

        Published by `_sequence_triggers` off `_drop_state`'s own memo, so
        reading it costs a tuple compare and never does I/O on the event
        loop. THE ONE TICK OF LAG, stated: `_tick_show_cues` runs BEFORE
        `tick()` resolves the triggers the view needs, so on the first
        tick of a song this still holds the previous song's uri and
        answers None. Nothing is lost by it beyond the 1 ms rearm window
        at that first observed position (`_last_position_ms = position_ms
        - 1`): the next tick's crossing window starts where this one's
        ended, so a phase anywhere after it is still crossed exactly
        once.
        """
        if uri is None or self._phase_cues[0] != uri:
            return None
        return list(self._phase_cues[1])

    def cached_scene_cues(self, uri: str) -> Optional[list]:
        """The planned scene cues (CandidateMoment) tick() fires from for
        `uri` when none are stored, or None when no plan for `uri` is
        cached — GET /api/analysed-plan reads this first so the scene-change
        markers it serves are the SAME list the engine fires."""
        if self._flare_plan_uri == uri:
            return list(self._scene_cue_plan)
        return None

    def cached_flare_triggers(self, uri: str) -> Optional[list[SpectraTrigger]]:
        """The analysed flare moments tick() is firing from for `uri`, or
        None when no plan for `uri` is cached (not the current song, or
        still planning). GET /api/analysed-plan reads this first so the
        markers it serves are the SAME list the engine fires."""
        if self._flare_plan_uri == uri:
            return list(self._flare_triggers)
        return None

    def cached_plan_ranks(self, uri: str) -> Optional[dict]:
        """generator_key -> (rank, rank_of) for `uri`'s cached plan, or None
        when no plan for `uri` is cached (cached_flare_triggers' rule)."""
        if self._flare_plan_uri == uri:
            return dict(self._plan_ranks)
        return None

    async def plan_analysed_flares(self, uri: str,
                                   stored: Optional[list[SpectraTrigger]] = None) -> None:
        """Compute and cache `uri`'s analysed flare plan (tick() schedules
        this itself; the spec awaits it directly). A result for a song that
        is no longer current is discarded. A failure is logged and caches
        an EMPTY plan — the song plays without analysed flares rather than
        re-planning (and re-failing) every tick."""
        if stored is None:
            stored = self._list_triggers(uri)
        epoch = self._flare_epoch
        try:
            plan = await asyncio.to_thread(self._analysed_plan, uri, list(stored))
            flares = list(plan.flares)
            scene_cues = list(plan.scene_cues)
        except Exception:
            logger.exception("analysed flares: planning failed for %s", uri)
            flares = []
            scene_cues = []
        finally:
            if self._flare_planning == uri and epoch == self._flare_epoch:
                self._flare_planning = None
        if uri != self._uri or epoch != self._flare_epoch:
            return
        self._flare_triggers = [
            SpectraTrigger(
                id=m.trigger_id, timestamp_ms=m.timestamp_ms, source="generated",
                generator_key=m.generator_key, snap_grid=m.snap_grid,
                snap_moved_ms=m.snap_moved_ms,
                action=FireResponseAction(event_class="flare", intensity=m.intensity))
            for m in flares]
        self._flare_ids = {t.id for t in self._flare_triggers}
        self._scene_cue_plan = scene_cues
        self._scene_cue_triggers = [
            SpectraTrigger(
                id=analysed_flares.SCENE_CUE_ID_PREFIX + m.generator_key,
                timestamp_ms=m.timestamp_ms, source="generated",
                generator_key=m.generator_key, snap_grid=m.snap_grid,
                snap_moved_ms=m.snap_moved_ms,
                action=FireSceneAction(intensity=m.intensity))
            for m in scene_cues]
        self._scene_cue_ids = {t.id for t in self._scene_cue_triggers}
        self._plan_ranks = {
            m.generator_key: (getattr(m, "rank", None), getattr(m, "rank_of", None))
            for m in [*scene_cues, *flares] if getattr(m, "generator_key", None)}
        self._flare_plan_uri = uri
        logger.info("analysed flares: %d planned for %s (and %d scene "
                    "changes)", len(flares), uri, len(scene_cues))

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

    def _notify_colour_cue(self) -> None:
        """A cue that changes colour or scene just fired: tell the colour
        journey, which picks its next horizon (next_colour_cue). Best-effort
        like _notify_intensity_event — never breaks the fire itself."""
        self._colour_cues_told += 1
        try:
            self._colour_cue()
        except Exception:
            logger.exception("colour journey: on_colour_cue failed")

    def next_colour_cue(self) -> Optional[NextCue]:
        """THE NEXT-CUE HORIZON for the trigger-timed colour journey
        (drift_conductor's _journey_leg): the next cue that will change
        colour or scene on the SHOW CLOCK for the song playing, or None.

        The candidates are exactly what tick() would fire — the enabled
        stored triggers the per-song effective mode allows
        (_effective_mode_for_song + _trigger_allowed, the same two calls) —
        narrowed to the two action kinds that change colour or scene:
        fire_scene and select_color_set. On a song with his triggers under
        "triggers_only" that is his next authored scene/colour trigger; on
        a song without, the next analysed scene change. When no generated
        cue is stored (first play before auto-generation lands, or a song
        carrying his own triggers) the analysed plan's own kept cues stand
        in — tick() fires exactly those — read through
        analysed_flares.scene_change_moments, the ONE list GET
        /api/analysed-plan's markers also use, never a second computation.
        Analysed FLARES are not colour cues (a flare fires the scene's own
        band, not a colour change) and never count.

        Times are target times — timestamp + the trigger's own offset, the
        same relocation tick() makes first. The scene/flare-kind offsets
        and the automatic lead are not added: the lead is what makes a
        crossfade's MIDDLE land on this mark, which is exactly where the
        journey aims to arrive.

        None when no song is known, the show clock has not been fed for
        POSITION_STALE_S (paused / bridge down — a walk timed against a
        frozen clock would arrive at the wrong moment), or nothing is
        ahead. The caller then falls back to the distance-paced walk."""
        uri, pos = self._uri, self._last_position_ms
        if uri is None or pos is None or self._position_at is None:
            return None
        if self._clock() - self._position_at > POSITION_STALE_S:
            return None
        triggers = self._list_triggers(uri)
        has_authored = any(t.source == "authored" for t in triggers)
        mode = self._effective_mode_for_song(self._scene_change_mode(), triggers)
        best: Optional[NextCue] = None
        # A generated scene cue inside a drop sequence's protected window is
        # held back at fire time (tick()), so it is not the next cue.
        windows = (self._drop_windows if self._drop_memo is not None
                   and self._drop_memo[0][0] == uri else [])

        best_trig: Optional[SpectraTrigger] = None

        def consider(cue: NextCue, trig: Optional[SpectraTrigger] = None) -> None:
            nonlocal best, best_trig
            if cue.at_ms > pos and (best is None or cue.at_ms < best.at_ms):
                best, best_trig = cue, trig

        for t in triggers:
            a = t.action
            if (not t.enabled or not self._trigger_allowed(t, mode)
                    or a.kind not in ("fire_scene", "select_color_set")):
                continue
            if (t.source == "generated" and a.kind == "fire_scene"
                    and drop_firing.holding_window(
                        windows, t.timestamp_ms + t.trigger_offset_ms) is not None):
                continue
            consider(NextCue(
                uri=uri, key=t.id, at_ms=t.timestamp_ms + t.trigger_offset_ms,
                position_ms=pos, kind=a.kind, source=t.source,
                intensity=getattr(a, "intensity", None),
                set_id=(a.set_id if a.kind == "select_color_set"
                        else a.color_set_id)), t)
        if analysed_flares.analysed_flares_allowed(mode, has_authored):
            planned = (self._scene_cue_plan
                       if self._flare_plan_uri == uri else [])
            moments, source = analysed_flares.scene_change_moments(
                triggers, lambda: planned, windows)
            if source == "planned":
                for m in moments:
                    consider(NextCue(uri=uri, key=m.key, at_ms=m.timestamp_ms,
                                     position_ms=pos, kind="fire_scene",
                                     source="planned", intensity=m.intensity),
                             SpectraTrigger(id=m.key, timestamp_ms=m.timestamp_ms,
                                            source="generated",
                                            generator_key=m.generator_key,
                                            action=FireSceneAction(intensity=m.intensity)))
        if best is not None and best.kind == "fire_scene" and best_trig is not None:
            # the cue's Energy (spectra/services/energy.py), never a stored value
            best = replace(best, intensity=self._trigger_energy(best_trig))
        return best

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
        drop_colour: Optional[dict] = None
        pre_drop_note: Optional[dict] = None
        self._notify_intensity_event()
        if trig.id in self._ride_ids:
            # THE DROP-LED SWITCH riding a flare inside the charge: cut to
            # the planned scene first, so this flare lands on its band.
            try:
                await self._switch_on_ride(trig)
            except Exception:
                logger.exception("drop switch: riding %s failed — the flare "
                                 "fires on the showing scene", trig.id)
        if trig.id in self._hit_ids:
            # THE FIREWORKS MELD's next big bass hit: cut to the planned
            # scene first, so this flare is the incoming scene's loud entry.
            try:
                await self._release_late(self._hit_ids[trig.id],
                                         drop_switch.MOMENT_NEXT_HIT, loud=False)
            except Exception:
                logger.exception("drop switch: the hit %s failed to cut — the "
                                 "flare fires on the showing scene", trig.id)
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
                        # SELECTION reads Energy (a.intensity, already
                        # energized by _energized() above _fire): the
                        # kernel's own genre_mult (selection_kernel.py) is
                        # a per-candidate weight on the pick, not a second
                        # scaling of the x position — no double count.
                        scene_id = self._select_scene(a.intensity)
                    if scene_id is None:
                        logger.info("trigger %s: kernel picked no scene "
                                    "(ladder terminated at stay, or scene_pool "
                                    "had nothing valid to draw) — nothing fired",
                                    trig.id)
                        self.last_fire = {"id": trig.id, "kind": a.kind,
                                          "ok": True, "picked": None}
                        await self._fire_analysed_color(trig, None)
                        self._notify_colour_cue()
                        return
                fire = (self._fire_planned_scene if trig.source == "generated"
                        else self._fire_scene)
                await fire(scene_id, a.color_set_id,
                           self._render_intensity(a.intensity))
                await self._fire_analysed_color(trig, scene_id)
                self._notify_colour_cue()
            elif a.kind == "fire_response" and trig.id in self._flare_ids:
                await self._fire_analysed_flare(self._render_intensity(a.intensity))
            elif a.kind == "fire_response" and trig.id in self._seq_meta:
                # A DROP SEQUENCE member (drop_firing.py): the same charge/
                # lull/drop response his own triggers fire, building to its
                # OWN partner in the sequence (the phase-partner rule).
                seq, cls, fire_mode = self._seq_meta[trig.id]
                render = self._render_intensity(a.intensity)
                if cls == "drop":
                    # THE DROP COLOUR CHANGE: before the drop-led cut (so the
                    # cut wears the new set) and before the drop's own phase
                    # arm (so the drop lands in it) — decided switch first,
                    # so the set comes from the scene the drop will show.
                    plan = await self._ensure_switch_plan(seq, cls, fire_mode)
                    drop_colour = await self._drop_colour_on_drop(seq, plan,
                                                                  a.intensity)
                # THE DROP-LED SWITCH (drop_switch.py): decided at the first
                # member, cut before the planned member (the drop, or the
                # charge) in this same call, so the member's own phase arm
                # lands on the NEW scene.
                told = self._colour_cues_told
                plan = await self._switch_before_member(seq, cls, fire_mode, render)
                if _colour_landed(drop_colour) and self._colour_cues_told == told:
                    # the new set is on the lights: the colour journey picks
                    # its next horizon from it — once (a cut just now told it)
                    self._notify_colour_cue()
                gap = (seq.gap_ms(cls, fire_mode, self._live_drop_offset_ms())
                       if cls in phase_partner.BUILD_CLASSES else None)
                if cls == "lull":
                    # THE PRE-DROP (pre_drop_play.py): the lull carries its
                    # sequence's pre-drop, timed against this tick's own
                    # show-clock position; the response engine decides
                    # against the scene showing and says so back.
                    pre = self._sequence_pre_drop(seq, cls, fire_mode)
                    with drop_switch.lull_plan(plan):
                        if pre is None:
                            await self._fire_sequence(cls, render, gap)
                        else:
                            result = await self._fire_sequence(
                                cls, render, gap, pre_drop=pre.candidate)
                            pre_drop_note = self._note_pre_drop(pre, result)
                else:
                    await self._fire_sequence(cls, render, gap)
                if cls == "drop":
                    self._note_drop(seq, plan)
                    self._arm_late_switch(seq)
                    self._note_drop_played(seq.key)
            elif a.kind == "fire_response":
                # OVERRIDE BLEND's dynamic half (2026-08-20, "fix the lull
                # ramp"): only charge/lull stretch a ramp to the real gap
                # — drop is always the fixed snap, so no gap is worth
                # computing for it (see _phase_partner_gap_ms/_phase_ramp_ms
                # for the full mechanism).
                gap_ms = (self._phase_partner_gap_ms(trig)
                         if a.event_class in ("charge", "lull") else None)
                if a.event_class == "drop":
                    # THE DROP COLOUR CHANGE on one of his own drop triggers
                    # (no drop-led switch): the showing scene's pool,
                    # instant, before the drop's own response — unless his
                    # pre-drop's fade already landed it (one change a drop).
                    faded = self._drop_colour_faded.get(f"his:{trig.id}")
                    if faded is not None:
                        drop_colour = {"result": "faded_at_pre_drop",
                                       "moment": "drop", "pre_drop": faded}
                    else:
                        drop_colour = await self._run_drop_colour(
                            a.intensity, None, 0, "drop", analysed=False)
                    if _colour_landed(drop_colour):
                        self._notify_colour_cue()
                pre = (self._his_pre_drop(trig)
                       if a.event_class == "lull" and trig.source == "authored"
                       else None)
                if pre is None:
                    await self._fire_response(a.event_class,
                                              self._render_intensity(a.intensity),
                                              gap_ms)
                else:
                    result = await self._fire_response(
                        a.event_class, self._render_intensity(a.intensity),
                        gap_ms, pre_drop=pre.candidate)
                    pre_drop_note = self._note_pre_drop(pre, result)
                if a.event_class == "drop" and trig.source == "authored":
                    self._note_drop_played(f"his:{trig.id}")
            elif a.kind == "fire_scene_update":
                await self._fire_scene_update(self._render_intensity(a.intensity))
            else:
                await self._select_color_set(a.set_id)
                self._notify_colour_cue()
        except Exception:
            logger.exception("trigger %s (%s @ %dms) failed to fire",
                             trig.id, a.kind, trig.timestamp_ms)
            self.last_fire = {"id": trig.id, "kind": a.kind, "ok": False}
            return
        logger.info("trigger %s fired: %s @ %dms", trig.id, a.kind, trig.timestamp_ms)
        self.last_fire = {"id": trig.id, "kind": a.kind, "ok": True}
        from spectra.services import fire_history
        detail = {"trigger_id": trig.id, "action_kind": a.kind, "source": trig.source}
        key = f"{trig.source}:{a.kind}"
        if trig.id in self._flare_ids:
            detail["analysed_flare"] = True
            key = "analysed:flare"
        if trig.id in self._scene_cue_ids:
            # A planned scene change fired from the plan itself (no stored
            # generated cue on this song) — the Review page names it so.
            detail["planned_scene_cue"] = True
        seq_meta = self._seq_meta.get(trig.id)
        if seq_meta is not None:
            seq, cls, fire_mode = seq_meta
            members = [c for c, _ms in seq.members(fire_mode)]
            detail.update({"drop_sequence": seq.key, "member": cls,
                           "state": seq.state, "origin": seq.origin,
                           "his": seq.his, "members": members,
                           "intensity": a.intensity})
            plan = self._switch_plans.get(seq.key)
            if plan is not None:
                detail["drop_switch"] = {
                    "switch": plan.switch, "reason": plan.reason,
                    "to": plan.to_scene_name, "moment": plan.moment,
                    "result": (plan.outcome or {}).get("result")}
            key = f"drop_sequence:{cls}"
        if drop_colour is not None:
            detail["drop_colour"] = drop_colour_brief(drop_colour)
        if pre_drop_note is not None:
            detail["pre_drop"] = pre_drop_note
        if trig.snap_grid is not None:
            # Phase 2 (spectra/services/beat_snap.py) — which grid this
            # generated cue was snapped to and how far, so the Review
            # page can show WHY it landed here (describeEvent.ts).
            detail["snap_grid"] = trig.snap_grid
            detail["snap_moved_ms"] = trig.snap_moved_ms
        fire_history.record_fire(
            "triggers", key, detail,
            uri=self._uri, position_ms=self._last_position_ms)

    # ── the drop-led scene switch (drop_switch.py) ───────────────────────

    def _forget_switches(self) -> None:
        self._switch_plans = {}
        self._switch_seqs = {}
        self._switch_done = set()
        self._ride_ids = {}
        self._late_pending = {}
        self._hit_ids = {}

    def _decide_switch(self, seq: drop_firing.FiringSequence, cls: str,
                       fire_mode: str) -> drop_switch.SwitchPlan:
        """The one decision for `seq`, at the first member the clock fires.
        Never raises into the fire: a failure is a named no-switch plan."""
        members = dict(seq.members(fire_mode))
        can_go_early = cls == "charge"
        end_ms = members.get("lull", members.get("drop"))
        ride = (drop_switch.find_ride(members.get("charge"), end_ms,
                                      self._tick_flares)
                if can_go_early else None)
        try:
            showing = self._switch_showing()
            record = self._drop_history.record_for(
                showing.stint if showing is not None else None)
            plan = drop_switch.decide(
                key=seq.key, uri=self._uri, members=members, showing=showing,
                record=record, settings=self._switch_settings(),
                pick_target=self._switch_pick(self._sequence_energy(seq)), ride=ride,
                can_go_early=can_go_early, blocker=self._switch_blocker(),
                decided_at_ms=self._last_position_ms,
                flares=self._tick_hits, beat_ms=seq.beat_ms)
        except Exception:
            logger.exception("drop switch: deciding %s failed — the drop "
                             "plays on the showing scene", seq.key)
            plan = drop_switch.SwitchPlan(
                key=seq.key, uri=self._uri, switch=False, reason="error",
                sentence="The drop switch could not decide (see the log) — "
                         "the drop plays on the showing scene.",
                charge_ms=members.get("charge"), lull_ms=members.get("lull"),
                drop_ms=members.get("drop"))
        self._switch_plans[seq.key] = plan
        self._switch_seqs[seq.key] = (seq, fire_mode)
        drop_switch.record_plan(plan)
        if plan.switch and plan.moment == drop_switch.MOMENT_CHARGE_FLARE:
            self._ride_ids[plan.ride_trigger_id] = seq.key
        logger.info("drop sequence %s: %s", seq.key, plan.sentence)
        return plan

    async def _ensure_switch_plan(self, seq: drop_firing.FiringSequence,
                                  cls: str, fire_mode: str) -> drop_switch.SwitchPlan:
        """This sequence's switch plan, decided now if it has not been (at
        the first member the clock fires) — WITHOUT executing its cut, so
        the drop colour change can pick from the scene the drop will show
        before the cut lands."""
        plan = self._switch_plans.get(seq.key)
        if plan is None:
            # a Fireworks meld still pending from an EARLIER sequence cuts
            # now, before this one is decided against a scene about to go
            for key in [k for k in self._late_pending if k != seq.key]:
                await self._release_late(key, "before_next_sequence", loud=False)
            plan = self._decide_switch(seq, cls, fire_mode)
        return plan

    async def _switch_before_member(self, seq: drop_firing.FiringSequence,
                                    cls: str, fire_mode: str,
                                    intensity: float) -> drop_switch.SwitchPlan:
        plan = await self._ensure_switch_plan(seq, cls, fire_mode)
        if not plan.switch or seq.key in self._switch_done:
            return self._switch_plans.get(seq.key, plan)
        at = None
        if plan.moment == drop_switch.MOMENT_CHARGE_START and cls == "charge":
            at = drop_switch.MOMENT_CHARGE_START
        elif plan.moment == drop_switch.MOMENT_DROP and cls == "drop":
            at = drop_switch.MOMENT_DROP
        elif (plan.moment == drop_switch.MOMENT_CHARGE_FLARE
              and cls in ("lull", "drop")):
            # the ride never fired (disabled, held, gated): never leave the
            # switch hanging — this member cuts instead
            at = "charge_flare_missed"
        if at is not None:
            await self._execute_switch(plan, at, intensity)
        return self._switch_plans.get(seq.key, plan)

    async def _switch_on_ride(self, trig: SpectraTrigger) -> None:
        key = self._ride_ids.get(trig.id)
        plan = self._switch_plans.get(key) if key else None
        if plan is None or key in self._switch_done:
            return
        seq, fire_mode = self._switch_seqs[key]
        outcome = await self._execute_switch(
            plan, drop_switch.MOMENT_CHARGE_FLARE,
            self._render_intensity(self._sequence_energy(seq)))
        if outcome.get("result") != "switched":
            return
        # carry the build on on the new scene from where it is
        from spectra.services.scene_response import _phase_ramp_ms
        charge_ms = plan.charge_ms if plan.charge_ms is not None else trig.timestamp_ms
        ramp = _phase_ramp_ms("charge", seq.gap_ms("charge", fire_mode))
        now = (self._last_position_ms if self._last_position_ms is not None
               else trig.timestamp_ms)
        elapsed = max(0, now - charge_ms)
        progress = min(1.0, elapsed / ramp) if ramp > 0 else 1.0
        try:
            await self._rearm_phase("charge", progress, max(0, ramp - elapsed))
        except Exception:
            logger.exception("drop switch %s: charge re-arm failed", key)

    async def _execute_switch(self, plan: drop_switch.SwitchPlan, at: str,
                              intensity: float) -> dict:
        """The cut itself (drop_switch.py): only while the scene the plan
        was decided against is still showing — a scene change in between
        SUPERSEDES it. Every outcome is recorded on the plan and in the show
        log under the sequence key."""
        self._switch_done.add(plan.key)
        if plan.ride_trigger_id:
            self._ride_ids.pop(plan.ride_trigger_id, None)
        try:
            showing = self._switch_showing()
        except Exception:
            showing = None
        showing_id = showing.scene.id if showing is not None else None
        outcome: dict[str, Any] = {"at": at, "position_ms": self._last_position_ms}
        if showing_id != plan.from_scene_id:
            outcome.update(result="superseded", showing=showing_id)
        else:
            try:
                result = await self._fire_drop_switch(plan.to_scene_id, intensity)
            except Exception:
                logger.exception("drop switch %s: the cut to %s failed",
                                 plan.key, plan.to_scene_name)
                result = {"skipped": "error"}
            skipped = result.get("skipped") if isinstance(result, dict) else None
            outcome["result"] = "skipped" if skipped else "switched"
            if skipped:
                outcome["skipped"] = skipped
            if isinstance(result, dict) and result.get("overrode_dwell_for_drop"):
                outcome["overrode_dwell_for_drop"] = result["overrode_dwell_for_drop"]
        plan = drop_switch.note_outcome(plan, outcome)
        self._switch_plans[plan.key] = plan
        logger.info("drop sequence %s: switch %s at %s (%s → %s)", plan.key,
                    outcome["result"], at, plan.from_scene_name, plan.to_scene_name)
        from spectra.services import fire_history
        fire_history.record_fire(
            "triggers", "drop_sequence:switch",
            {"drop_sequence": plan.key, "member": "switch", "at": at,
             "moment": plan.moment, "from_scene": plan.from_scene_name,
             "to_scene": plan.to_scene_name, "to_scene_id": plan.to_scene_id,
             "handoff": plan.handoff, "stale_by": list(plan.stale_by),
             "sentence": plan.sentence, **outcome},
            uri=self._uri, position_ms=self._last_position_ms)
        if outcome["result"] == "switched":
            self._notify_colour_cue()
        return outcome

    def _arm_late_switch(self, seq: drop_firing.FiringSequence) -> None:
        """THE FIREWORKS MELDS (drop_switch.py): Fireworks has played its
        own drop — arm the late cut, its moment recomputed now (the song's
        analysed flares may have been planned since the decision)."""
        plan = self._switch_plans.get(seq.key)
        if (plan is None or not plan.late or seq.key in self._switch_done
                or seq.key in self._late_pending):
            return
        try:
            settings = self._switch_settings()
        except Exception:
            settings = drop_switch.SwitchSettings()
        plan = drop_switch.late_release(
            plan, settings, self._tick_hits, seq.beat_ms,
            drop_offset_ms=self._drop_applied.get(seq.trigger_id("drop"), 0))
        self._switch_plans[seq.key] = plan
        drop_switch.record_plan(plan)
        self._late_pending[seq.key] = plan
        if plan.release_by == "hit" and plan.hit_trigger_id:
            self._hit_ids[plan.hit_trigger_id] = seq.key
        logger.info("drop sequence %s: %s → %s armed, released by %s at %sms",
                    seq.key, plan.from_scene_name, plan.to_scene_name,
                    plan.release_by, plan.release_ms)

    async def _tick_late_switches(self, last: int, position_ms: int) -> None:
        """Cut every armed late switch whose moment this tick reaches: the
        swallow delay, or (for a next-hit plan) the deadline — the hit
        itself cuts from _fire, just before its flare fires. A `hit` plan's
        own release_ms is always <= its deadline_ms (drop_switch.next_big_hit),
        so the two can land in the SAME tick's (last, position_ms] crossing
        window — if so, defer to the hit's own _fire() crossing instead of
        releasing here too, or the incoming scene's flare fires twice."""
        for key, plan in list(self._late_pending.items()):
            if plan.release_by == "hit":
                due_ms = plan.deadline_ms
                at, loud = "deadline", True
                if (plan.release_ms is not None
                        and last < plan.release_ms <= position_ms):
                    continue
            else:
                due_ms = plan.release_ms
                at = "deadline" if plan.release_by == "deadline" else plan.moment
                loud = plan.moment == drop_switch.MOMENT_NEXT_HIT
            if due_ms is None or position_ms < due_ms:
                continue
            await self._release_late(key, at, loud=loud)

    async def _release_late(self, key: str, at: str, loud: bool) -> None:
        plan = self._late_pending.pop(key, None)
        if plan is None:
            return
        if plan.hit_trigger_id:
            self._hit_ids.pop(plan.hit_trigger_id, None)
        seq = (self._switch_seqs.get(key) or (None, None))[0]
        intensity = self._render_intensity(self._sequence_energy(seq))
        outcome = await self._execute_switch(plan, at, intensity)
        if loud and outcome.get("result") == "switched":
            # the incoming scene comes in loud: its own flare band, now
            try:
                await self._fire_analysed_flare(intensity)
            except Exception:
                logger.exception("drop switch %s: the incoming scene's flare "
                                 "failed", key)

    def _note_drop(self, seq: drop_firing.FiringSequence,
                   plan: Optional[drop_switch.SwitchPlan]) -> None:
        """Which stint played this drop, and whether this sequence installed
        it (a scene installed for a drop, at its charge or on it, is fresh
        for the next one)."""
        try:
            showing = self._switch_showing()
        except Exception:
            return
        plan = self._switch_plans.get(seq.key, plan)
        arrived = bool(plan is not None and plan.switch
                       and (plan.outcome or {}).get("result") == "switched")
        self._drop_history.note_drop(
            seq.key, showing.stint if showing is not None else None, arrived)

    # ── the drop colour change (drop_colour.py) ──────────────────────────

    def _incoming_scene_id(self, seq: drop_firing.FiringSequence,
                           plan: Optional[drop_switch.SwitchPlan]) -> Optional[str]:
        """The scene whose pool the drop's new set comes from: the INCOMING
        one while a drop-led switch is planned and has not cut yet, else
        None (the scene showing)."""
        if plan is not None and plan.switch and seq.key not in self._switch_done:
            return plan.to_scene_id
        return None

    async def _drop_colour_on_drop(self, seq: drop_firing.FiringSequence,
                                   plan: Optional[drop_switch.SwitchPlan],
                                   intensity: float) -> Optional[dict]:
        """A drop sequence's drop: its instant colour change — unless its
        pre-drop's fade already landed it (one change per drop)."""
        faded = self._drop_colour_faded.get(seq.key)
        if faded is not None:
            return {"result": "faded_at_pre_drop", "moment": "drop",
                    "pre_drop": faded}
        return await self._run_drop_colour(
            intensity, self._incoming_scene_id(seq, plan), 0, "drop",
            analysed=True)

    async def _run_drop_colour(self, selection_intensity: float,
                               pool_scene_id: Optional[str], ramp_ms: int,
                               moment: str, *, analysed: bool) -> Optional[dict]:
        """One drop colour change through the hook (None when the hook is
        the unwired default). Never raises into the fire: a failure is a
        named outcome and the drop fires regardless."""
        try:
            record = await self._drop_colour(selection_intensity, pool_scene_id,
                                             int(ramp_ms), moment, analysed)
        except Exception:
            logger.exception("drop colour change failed (%s) — the drop fires "
                             "in the colours it has", moment)
            return {"result": "error", "moment": moment}
        return record if isinstance(record, dict) else None

    async def _tick_drop_colour_fades(self, last: int, position_ms: int) -> None:
        """THE DROP COLOUR CHANGE across a pre-drop (predrop plan 2.2 and
        2.3; his approval: "if we have a pre-drop, fade the color throught
        the predrop, not an instant change"). A pre-drop whose lull told it
        and which PLAYS (pre_drop_play.py — the same verdict that tells the
        pre-drop effects, so the colour and the lights agree) starts the
        drop's colour change ON the pre-drop — one trigger tick EARLY
        (PRE_DROP_COLOUR_LEAD_MS, his "on (before) the pre-drop"), at the
        target computed when the lull fired: moved with its drop, the
        drop's own fire shift applying to both — and glides round the
        wheel over the time left from the tick that fires it to the drop's
        target, so it lands on the drop, never after it. A LANDED fade is
        remembered (`_drop_colour_faded`) and its drop does not change
        again; a held one leaves the drop its own instant try. A pre-drop
        that does not play (its kind off on the scene showing, its gap
        outside the window, its lull never fired) leaves the drop's change
        instant. Exactly once per approach (the fired-keys memory)."""
        for told in list(self._pre_drop_told.values()):
            if not told.plays or told.key in self._drop_colour_faded:
                continue
            key = (f"drop-colour:{told.key}", int(told.pre_target_ms))
            if key in self._fired:
                continue
            if told.pre_target_ms >= told.drop_target_ms:
                continue
            fire_at = told.pre_target_ms - PRE_DROP_COLOUR_LEAD_MS
            if not (last < fire_at <= position_ms
                    or last < told.pre_target_ms <= position_ms):
                continue
            self._fired.add(key)
            ramp_ms = max(0, told.drop_target_ms - position_ms)
            try:
                pool_scene: Optional[str] = None
                if told.seq is not None:
                    plan = await self._ensure_switch_plan(told.seq, "drop",
                                                          told.fire_mode)
                    pool_scene = self._incoming_scene_id(told.seq, plan)
                record = await self._run_drop_colour(
                    told.intensity, pool_scene, ramp_ms, "pre_drop",
                    analysed=told.seq is not None)
            except Exception:
                logger.exception("pre-drop %s: the colour fade failed — its "
                                 "drop changes colour instead", told.key)
                continue
            if record is None:
                continue
            brief = drop_colour_brief(record)
            if record.get("result") == "jumped":
                self._drop_colour_faded[told.key] = brief
            logger.info("pre-drop %s: colour change at its pre-drop (%s), "
                        "landing on the drop in %d ms", told.key,
                        brief.get("result") or brief.get("held_for"), ramp_ms)
            from spectra.services import fire_history
            detail = {"member": "pre_drop", "pre_drop_key": told.key,
                      "kind": told.kind,
                      "pre_drop_target_ms": told.pre_target_ms,
                      "drop_target_ms": told.drop_target_ms,
                      "drop_colour": brief}
            if told.seq is not None:
                detail.update({"drop_sequence": told.seq.key,
                               "pre_drop_ms": told.seq.pre_drop_ms,
                               "drop_ms": told.seq.drop_ms})
            fire_history.record_fire(
                "triggers", "drop_sequence:pre_drop_colour", detail,
                uri=self._uri, position_ms=position_ms)

    # ── the pre-drop (spectra/services/pre_drop_play.py) ─────────────────

    def _sequence_pre_drop(self, seq: drop_firing.FiringSequence, cls: str,
                           fire_mode: str) -> Optional[_PreDropPlan]:
        """The pre-drop this sequence's LULL carries (FiringSequence.
        pre_drop_for), as a candidate timed against THIS tick's show-clock
        position (the lull's actual fire, up to one TICK_S after its mark)
        — its target moved with its drop: the drop's own fire shift (band
        anchor plus the drop timing offset, _drop_fire_shift_ms) applies to
        both, so the gap stays the music's gap. None when it carries none."""
        got = seq.pre_drop_for(cls, fire_mode)
        pos = self._last_position_ms
        if got is None or pos is None:
            return None
        pre_ms, kind = got
        shift = self._drop_fire_shift_ms(seq, fire_mode)
        pre_target, drop_target = pre_ms + shift, seq.drop_ms + shift
        return _PreDropPlan(
            candidate=pre_drop_play.PreDropCandidate(
                at_ms=int(pre_target - pos), gap_ms=int(drop_target - pre_target),
                kind=kind, key=seq.key),
            pre_target_ms=int(pre_target), drop_target_ms=int(drop_target),
            intensity=self._sequence_energy(seq), seq=seq, fire_mode=fire_mode)

    def _his_pre_drop(self, lull: SpectraTrigger) -> Optional[_PreDropPlan]:
        """The pre-drop one of his own authored LULLS carries: its grouped
        sequence's (drop_firing.his_pre_drops — the view's authored group,
        under the part rule), timed against this tick's position, its target
        moved with his drop exactly as tick() moves the drop (his trigger's
        own offset, his drop band's anchor, the drop timing offset)."""
        his = self._his_pre_drops.get(lull.id)
        pos = self._last_position_ms
        if his is None or pos is None:
            return None
        triggers = (self._tick_triggers[1]
                    if self._tick_triggers is not None
                    and self._tick_triggers[0] == self._uri
                    else self._list_triggers(self._uri))
        drop = next((t for t in triggers if t.id == his.drop_id), None)
        if drop is None or not drop.enabled or drop.timestamp_ms != his.drop_ms:
            return None
        target = drop.timestamp_ms + drop.trigger_offset_ms
        try:
            target += int(self._response_offset_ms(drop.action))
        except Exception:
            logger.exception("pre-drop: his drop's band offset is unreadable "
                             "— the pre-drop is timed to the unshifted drop")
        target += self._drop_shift_ms(drop, triggers)
        shift = target - drop.timestamp_ms
        pre_target = his.pre_drop_ms + shift
        return _PreDropPlan(
            candidate=pre_drop_play.PreDropCandidate(
                at_ms=int(pre_target - pos), gap_ms=int(target - pre_target),
                kind=his.kind, key=his.key),
            pre_target_ms=int(pre_target), drop_target_ms=int(target),
            intensity=float(getattr(drop.action, "intensity", 0.0) or 0.0))

    def _note_pre_drop(self, plan: _PreDropPlan, result: Any) -> dict:
        """Remember what the lull was told (PreDropTold) from the response
        record it came back with: `phase.pre_drop`, the verdict. A fire the
        gate held (None back), or a record without one, did not play it."""
        verdict = None
        if isinstance(result, dict):
            verdict = (result.get("phase") or {}).get("pre_drop")
        if not isinstance(verdict, dict):
            verdict = {**plan.candidate.as_dict(), "plays": False,
                       "reason": "not_fired", "told": []}
        verdict = {**verdict, "key": plan.candidate.key,
                   "pre_drop_target_ms": plan.pre_target_ms,
                   "drop_target_ms": plan.drop_target_ms}
        self._pre_drop_told[plan.candidate.key] = PreDropTold(
            key=plan.candidate.key, pre_target_ms=plan.pre_target_ms,
            drop_target_ms=plan.drop_target_ms, kind=plan.candidate.kind,
            intensity=plan.intensity, verdict=verdict, seq=plan.seq,
            fire_mode=plan.fire_mode)
        logger.info("pre-drop %s (%s): %s", plan.candidate.key,
                    plan.candidate.kind, verdict.get("reason"))
        return verdict

    def _drop_fire_shift_ms(self, seq: drop_firing.FiringSequence,
                            fire_mode: str) -> int:
        """How far this sequence's drop fires off its mark: its band's anchor
        (the live peek tick() makes for the drop member) plus the drop timing
        offset as drop_timing clamps it against the build — the same two
        terms tick() sums into the drop member's target."""
        try:
            band = int(self._response_offset_ms(
                FireResponseAction(event_class="drop", intensity=self._sequence_energy(seq))))
        except Exception:
            logger.exception("drop colour: the drop band's offset is unreadable "
                             "— the fade is timed to the unshifted drop")
            band = 0
        offset = self._tick_drop_offset_ms()
        return drop_timing.fire_moment_ms(
            seq.drop_ms, offset, seq.build_start_ms(fire_mode), band) - seq.drop_ms

    def drop_fire_ms(self, drop_ms: int, intensity: float,
                     build_start_ms: Optional[int] = None,
                     offset_ms: Optional[int] = None,
                     band_offset_ms: Optional[int] = None) -> int:
        """WHEN A DROP MARKED AT `drop_ms` FIRES, read live — the Drops
        panel's countdown and the top bar's next-event box (2026-10-28, the
        Admiral's Q4). `intensity` is the drop's own (a sequence's
        `sequence_intensity`, or his trigger's), so the band peek selects
        the band the fire will; `build_start_ms` the lull/charge its build
        starts from; `offset_ms` the drop timing offset and `band_offset_ms`
        the drop band's offset when the caller has read them already
        (live_drop_offset_ms / drop_band_offset_ms — one read a song).
        drop_timing.fire_moment_ms over the same two live reads tick() makes
        (the drop band's offset, the drop timing offset); a read that fails
        counts as 0, the drop on its mark."""
        band = (self.drop_band_offset_ms(intensity) if band_offset_ms is None
                else int(band_offset_ms))
        offset = self._live_drop_offset_ms() if offset_ms is None else int(offset_ms)
        return drop_timing.fire_moment_ms(int(drop_ms), offset, build_start_ms, band)

    def his_drop_fire_ms(self, timestamp_ms: int, trigger_offset_ms: int,
                        intensity: float, build_timestamp_ms: Optional[int] = None,
                        build_trigger_offset_ms: int = 0,
                        offset_ms: Optional[int] = None,
                        band_offset_ms: Optional[int] = None) -> int:
        """WHEN ONE OF HIS OWN AUTHORED DROP TRIGGERS FIRES, read live —
        `drop_fire_ms`'s own twin for the Drops panel's "yours" rows
        (2026-10-28): `timestamp_ms`/`build_timestamp_ms` are the STORED,
        offset-inclusive moments drop_sequences.HisMark carries;
        `trigger_offset_ms`/`build_trigger_offset_ms` are each trigger's
        own SpectraTrigger.trigger_offset_ms, so the clamp this composes
        runs against the RAW stored timestamps — exactly as
        `_drop_shift_ms` picks its build start from the real triggers'
        own `timestamp_ms` — never the offset-inclusive ones, which would
        silently double-count a nonzero trigger_offset_ms inside the
        clamp floor. See drop_timing.his_fire_moment_ms."""
        band = (self.drop_band_offset_ms(intensity) if band_offset_ms is None
                else int(band_offset_ms))
        offset = self._live_drop_offset_ms() if offset_ms is None else int(offset_ms)
        return drop_timing.his_fire_moment_ms(
            int(timestamp_ms), int(trigger_offset_ms), offset,
            build_timestamp_ms, build_trigger_offset_ms, band)

    def drop_band_offset_ms(self, intensity: float) -> int:
        """The drop band's flare-kind offset at this drop intensity — the
        live peek tick() makes for a drop (0 when unreadable)."""
        try:
            return int(self._response_offset_ms(
                FireResponseAction(event_class="drop", intensity=float(intensity))))
        except Exception:
            logger.exception("drop fire moment: the drop band's offset is unreadable")
            return 0

    def live_drop_offset_ms(self) -> int:
        """The drop timing offset in force now (room, or the showing scene's
        own) — 0 when unreadable. Public for drop_fire_ms's callers."""
        return self._live_drop_offset_ms()

    def switch_plans(self, uri: Optional[str]) -> list[drop_switch.SwitchPlan]:
        """This play's drop-switch decisions for `uri` (the Timeline, Sonic)."""
        return drop_switch.plans_for(uri)

    async def _fire_analysed_color(self, trig: SpectraTrigger,
                                   scene_id: Optional[str]) -> None:
        """ANALYSED COLOUR (owner ask 2026-09-25, "colour jump on every
        analysed moment"): a GENERATED fire_scene cue on a song with NO
        authored trigger also lands a colour moment — whether its scene
        fired, re-fired, was deferred by minimum dwell, or the kernel
        picked nothing. Runs AFTER the scene fire, in the same _fire call,
        so it shares the scene fire's show clock (tick() already fired this
        cue `lead` early so the crossfade's middle lands on the mark; the
        jump rides the same crossfade length, so its middle lands there
        too) and glides over the scene the fire just installed. Selection
        is at the cue's RAW section energy (a.intensity), the same value
        the scene pick used; the ramp at render intensity, like the fire.
        What lands — a colour-set jump, the gradient's own kick, or a named
        hold — is scene_response.ResponseEngine.analysed_color_jump's
        precedence. Best-effort: a failure never undoes the scene fire."""
        if trig.source == "authored" or self.song_untriggered() is not True:
            return
        a = trig.action
        try:
            await self._analysed_color(a.intensity,
                                       self._render_intensity(a.intensity),
                                       scene_id)
        except Exception:
            logger.exception("trigger %s: analysed colour jump failed", trig.id)

    def _drop_shift_ms(self, trig: SpectraTrigger,
                       triggers: list[SpectraTrigger]) -> int:
        """The drop timing offset tick() applies to this drop trigger
        (drop_timing.py): the live offset, clamped so the drop never fires
        within drop_timing.MIN_BUILD_MS of the lull/charge its build starts
        from. Remembered in `_drop_applied`. Never raises — an unreadable
        offset is 0 (the drop on its mark), named in the log."""
        offset = self._tick_drop_offset_ms()
        meta = self._seq_meta.get(trig.id)
        if meta is not None:
            seq, _cls, fire_mode = meta
            start = seq.build_start_ms(fire_mode)
        else:
            builds = [t.timestamp_ms for t in triggers
                      if t.enabled and t.id != trig.id
                      and _phase_class(t) in phase_partner.BUILD_CLASSES
                      and t.timestamp_ms < trig.timestamp_ms]
            start = max(builds) if builds else None
        applied = drop_timing.applied_offset_ms(trig.timestamp_ms, offset, start)
        self._drop_applied[trig.id] = applied
        return applied

    def _tick_drop_offset_ms(self) -> int:
        """The live drop timing offset, read once per tick however many drops
        sit in the horizon (0 when unreadable — the drop on its mark)."""
        if self._tick_drop_offset is None:
            try:
                self._tick_drop_offset = int(self._drop_offset_ms())
            except Exception:
                logger.exception("drop timing: offset unreadable — the drop "
                                 "fires on its mark")
                self._tick_drop_offset = 0
        return self._tick_drop_offset

    def _live_drop_offset_ms(self) -> int:
        """The offset a build ending on a drop is told about (never
        raises; 0 when unreadable, matching _drop_shift_ms)."""
        try:
            return int(self._drop_offset_ms())
        except Exception:
            logger.exception("drop timing: offset unreadable — builds run to "
                             "the drop's own mark")
            return 0

    def _default_drop_offset_ms(self) -> int:
        """The room's drop timing offset, or the SHOWING scene's own
        SceneV2.drop_timing_offset_ms when it has one — the scene whose drop
        band fires, the same live peek _default_response_offset_ms makes."""
        from spectra.services.room_controls import load_room_controls
        return drop_timing.resolve_offset_ms(load_room_controls(),
                                             self._active_scene())

    def _phase_partner_gap_ms(self, trig: SpectraTrigger) -> Optional[int]:
        """OVERRIDE BLEND's dynamic half (ported from legacy trigger_engine.
        _phase_blend_ramp_ms/_blend_factor_for, missing from the SPECTRA
        port until 2026-08-20 — see scene_response.py's own OVERRIDE BLEND
        note for the full incident writeup): milliseconds from this charge
        or lull to the end of its build.

        THE PHASE PARTNER RULE (2026-10-06, drop-detection plan phase 1 —
        spectra/services/phase_partner.py is the binding statement): a
        charge builds to its own next lull or drop and a lull to its own
        next drop, whatever flare, scene change, colour change or update
        sits between, provided the partner is within the effects' own 60 s
        cap. A charge or lull with no partner ahead keeps the pre-rule
        answer: the next trigger of any kind. Before this rule every build
        ran to the next trigger of any kind, so a flare inside a charge
        made the build peak at the flare.

        "Will actually fire" is unchanged: only ENABLED triggers count, and
        the PER-SONG EFFECTIVE mode is resolved exactly as tick() does
        (_effective_mode_for_song against this song's own trigger list,
        not the raw stored setting) before _trigger_allowed — load-bearing
        since "triggers_only" (#148): a trigger the effective mode won't
        fire is neither a partner nor a next moment. None means there's
        nothing to stretch to: nothing ahead fires (this is the last one),
        or no song is loaded at all — the caller (scene_response.
        _phase_ramp_ms) falls back to a documented flat default in that
        case, never a guess."""
        if self._uri is None:
            return None
        triggers = self._list_triggers(self._uri)
        mode = self._effective_mode_for_song(self._scene_change_mode(), triggers)
        later = [(t.timestamp_ms, _phase_class(t)) for t in triggers
                 if t.enabled and t.id != trig.id
                 and self._trigger_allowed(t, mode)]
        target = phase_partner.build_target(
            trig.action.event_class, trig.timestamp_ms, later)
        # A build ending on a drop runs to where the drop FIRES (drop_
        # timing.py), so the ramp's hang and the breath-hold end on it.
        return drop_timing.build_gap_ms(trig.timestamp_ms, target.ms,
                                        target.target_class,
                                        self._live_drop_offset_ms())

    # ── observability ─────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "track_uri": self._uri,
            "position_ms": self._last_position_ms,
            "last_fire": self.last_fire,
            "last_drop": self.last_drop,
            # THE PRE-DROP: what each lull carrying one was told this play
            "pre_drops": {k: t.verdict for k, t in self._pre_drop_told.items()},
        }

    def _note_drop_played(self, key: str) -> None:
        """A drop just fired (DROP TESTING in __init__): remember it and
        tell `drop_played`. Never raises into the fire path."""
        import time as _time
        self.last_drop = {"uri": self._uri, "key": key,
                          "at_ms": int(_time.time() * 1000),
                          "position_ms": self._last_position_ms}
        try:
            self._drop_played(dict(self.last_drop))
        except Exception:                                # noqa: BLE001
            logger.exception("drop played: the push failed for %s", key)

    # ── production defaults (lazy imports; the spec injects fakes) ──────────

    async def _default_fire_scene(self, scene_id: str,
                                  color_set_id: Optional[str],
                                  intensity: float) -> None:
        from spectra.services.scene_sequencer import fire_scene_by_id
        await fire_scene_by_id(scene_id, color_set_id, intensity)

    async def _default_fire_planned_scene(self, scene_id: str,
                                          color_set_id: Optional[str],
                                          intensity: float) -> None:
        from spectra.services import dwell
        from spectra.services.scene_sequencer import fire_scene_by_id
        await fire_scene_by_id(scene_id, color_set_id, intensity,
                               dwell_tolerance_s=dwell.PLANNED_CUE_TOLERANCE_S)

    @staticmethod
    async def _no_analysed_color(selection_intensity: float,
                                 render_intensity: float,
                                 scene_id: Optional[str]) -> None:
        return None

    @staticmethod
    async def _no_drop_colour(selection_intensity: float,
                              pool_scene_id: Optional[str], ramp_ms: int,
                              moment: str, analysed: bool) -> None:
        return None

    def _default_select_scene(self, intensity: float) -> Optional[str]:
        """A generated trigger's scene_id=None resolution: the SAME
        selection kernel the sequencer's own rolls use
        (scene_sequencer._roll), but a one-shot draw at the TRIGGER's own
        intensity — no dwell, no "current scene" affinity tracked across
        trigger fires (deliberately simpler than the sequencer's continuous
        state machine; a mid-song trigger names one moment, not a stream of
        them). picked_id None (the terminal STAY rung, or no configured
        sequencer entries at all) means nothing fires this crossing.

        NEVER THE SCENE ALREADY SHOWING (2026-10-04): the room's active
        scene (dwell.active_scene_id — the one every real fire latches) is
        passed as the kernel's current_id, so it is drawn only when nothing
        else can be (the kernel's re-admit rung). Before this every draw
        passed None and 17.5% of his real "scene changes" re-fired the
        scene already showing."""
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
        from spectra.services import dwell
        pick = kernel.select(candidates, intensity=intensity, rng=self._rng,
                             current_id=dwell.active_scene_id(),
                             terminal=kernel.TERMINAL_STAY)
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

    def _default_drop_testing(self) -> bool:
        from spectra.services.room_controls import load_room_controls
        return bool(load_room_controls().drop_testing)

    def _default_transition_intensity(self) -> float:
        # ENERGY at the show clock, with the look-ahead a scene change takes
        # (spectra/services/energy.py) + the 0.5 neutral fallback — no
        # per-song analysis is required for the transition fire to work.
        from spectra.services.engine import bridge
        value = bridge.intensity(look_ahead=True)
        return value if value is not None else energy_mod.NEUTRAL

    def _default_energy_for(self, uri: str, trig: SpectraTrigger) -> Optional[float]:
        a = trig.action
        return energy_mod.energy_for_moment(
            uri, trig.timestamp_ms + trig.trigger_offset_ms, a.kind,
            getattr(a, "event_class", None), trig.generator_key)

    def _trigger_energy(self, trig: SpectraTrigger) -> float:
        """Energy at this trigger's own moment (its source section when it
        was generated from one; the look-ahead for a drop or a scene change;
        the present otherwise). 0.5 neutral when unknowable."""
        try:
            value = self._energy_for(self._uri, trig) if self._uri else None
        except Exception:                                # noqa: BLE001
            logger.exception("trigger %s: energy unreadable — neutral", trig.id)
            value = None
        return energy_mod.NEUTRAL if value is None else float(value)

    def _energized(self, trig: SpectraTrigger) -> SpectraTrigger:
        """A copy of `trig` whose action carries Energy at its moment in place
        of the stored value — so every read downstream (the pick, the lead and
        offset peeks, the fire) is Energy. An action with no intensity
        (select_color_set) is returned as it is. Idempotent: an energized
        copy energizes to the same value."""
        a = trig.action
        if not hasattr(a, "intensity"):
            return trig
        return trig.model_copy(update={"action": a.model_copy(
            update={"intensity": round(self._trigger_energy(trig), 4)})})

    @staticmethod
    def _moment_energy(tl, trig: SpectraTrigger) -> float:
        """An analysed flare's Energy from an already-read timeline (the
        drop switch's "next big hit" reads every one each tick): its own
        source section, else the present."""
        if tl is None:
            return energy_mod.NEUTRAL
        src = energy_mod.source_ms(trig.generator_key)
        value = tl.at_source(src) if src is not None else None
        if value is None:
            value = tl.at(trig.timestamp_ms + trig.trigger_offset_ms)
        return energy_mod.NEUTRAL if value is None else float(value)

    def _sequence_energy(self, seq) -> float:
        """A drop sequence's Energy (the Energy plan's D3): at its drop, with
        the look-ahead every drop takes — not the detector's jump size."""
        if seq is None or not self._uri:
            return energy_mod.NEUTRAL
        return self._trigger_energy(SpectraTrigger(
            id=seq.trigger_id("drop"), timestamp_ms=int(seq.drop_ms),
            action=FireResponseAction(event_class="drop", intensity=seq.intensity)))

    def _default_render_intensity(self, raw: float) -> float:
        """The RENDER/FIRE role. Every value it is handed is already ENERGY
        (spectra/services/energy.py) — the song's normalized section energy
        WITH the Mark math applied once, inside Energy — so the fire lands it
        as it is. Applying the Mark here again would apply it twice. Kept as
        an injectable seam for the tests that drive a fire at a known value."""
        return raw

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
                                     gap_ms: Optional[int] = None,
                                     pre_drop: Optional[
                                         pre_drop_play.PreDropCandidate] = None
                                     ) -> Optional[dict]:
        from spectra.services import engine
        # via_trigger=True: this call only ever happens for a trigger
        # _trigger_allowed already gated (necessarily source=="authored"),
        # so it must reach the real response engine whenever the room is
        # at "full" OR "triggers_only" — see engine.fire_response_event's
        # own docstring for the dual-path reasoning. gap_ms is the
        # SEPARATE charge/lull OVERRIDE BLEND stretch input (this
        # engine's own _phase_partner_gap_ms) — orthogonal to via_trigger,
        # threaded through unconditionally (None for a flare/drop, same
        # as always).
        if pre_drop is None:
            return await engine.fire_response_event(event_class, intensity,
                                                    gap_ms=gap_ms,
                                                    via_trigger=True)
        return await engine.fire_response_event(event_class, intensity,
                                                gap_ms=gap_ms, via_trigger=True,
                                                pre_drop=pre_drop)

    async def _default_fire_analysed_flare(self, intensity: float) -> None:
        from spectra.services import engine
        # via_trigger=True: tick() relocated this fire by its band's anchor
        # exactly as it does a stored fire_response trigger. analysed=True
        # widens the tier gate to "analysed" — tick() has already applied
        # the per-song rule (analysed_flares.analysed_flares_allowed).
        await engine.fire_response_event("flare", intensity, via_trigger=True,
                                         analysed=True)

    async def _default_fire_sequence(self, event_class: str, intensity: float,
                                     gap_ms: Optional[int] = None,
                                     pre_drop: Optional[
                                         pre_drop_play.PreDropCandidate] = None
                                     ) -> Optional[dict]:
        from spectra.services import engine
        # via_trigger=True: tick() relocated this member by its band's
        # anchor exactly as it does a stored fire_response trigger.
        # analysed=True admits the analysed tier beside "full"/
        # "triggers_only": tick() has already applied the sequence's own
        # gate (drop_firing.fires_here) before calling. The record comes
        # back so a lull's pre-drop verdict reaches _note_pre_drop.
        if pre_drop is None:
            return await engine.fire_response_event(
                event_class, intensity, gap_ms=gap_ms, via_trigger=True,
                analysed=True)
        return await engine.fire_response_event(
            event_class, intensity, gap_ms=gap_ms, via_trigger=True,
            analysed=True, pre_drop=pre_drop)

    async def _default_fire_drop_switch(self, scene_id: str,
                                        intensity: float) -> dict:
        from spectra.services.scene_sequencer import fire_scene_by_id
        return await fire_scene_by_id(scene_id, None, intensity,
                                      origin="drop", cut=True)

    async def _default_rearm_phase(self, event_class: str, progress: float,
                                   remaining_ms: int) -> Any:
        from spectra.services import engine
        return await engine.rearm_phase_event(event_class, progress, remaining_ms)

    @staticmethod
    def _default_drop_view(uri: str, triggers: list) -> dict:
        return drop_sequences.view(uri, triggers=triggers)

    @staticmethod
    def _default_analysed_plan(uri: str, stored: list):
        return analysed_flares.plan_for_song(uri, stored)

    async def _default_fire_scene_update(self, intensity: float) -> None:
        from spectra.services import engine
        await engine.fire_scene_update_event(intensity)

    async def _default_select_color_set(self, set_id: str) -> None:
        from spectra.services import (color_set_groups, color_sets, engine,
                                      force_color)
        from spectra.services.room_controls import load_room_controls
        # FORCE COLOUR (owner ask 2026-08-27, spectra/services/
        # force_color.py) redirects an automatic colour choice exactly the
        # way Force Scene redirects an automatic scene choice — a stored
        # trigger firing IS automatic (he authored it earlier; he is not
        # pressing a button now), so the pin wins and the redirect is
        # NAMED in the record (forced_from=<the id the trigger asked for>)
        # rather than silently logging an apply of a set he never wrote.
        # Resolved once, here, which is also the single advance of a
        # pinned GROUP's rotation for this fire.
        # ABSORB MUSIC (spectra/services/absorb_hold.py): a stored colour
        # trigger on a song nobody is hearing lands nothing — ahead of
        # Force Colour, whose apply would still be a write.
        from spectra.services import absorb_hold
        if absorb_hold.active():
            absorb_hold.record_deferral(f"select_color_set:{set_id}",
                                        {"set_id": set_id})
            return
        forced = force_color.pinned_card()
        if forced is not None:
            await engine.conductor.apply_set_directly(forced,
                                                      forced_from=set_id)
            return
        # HOUSE LIGHTING (spectra/services/house.py): a mode that keeps its
        # look through music ("calm"/"ignore") owns the colours too — a
        # stored colour trigger waits, the same way its scene triggers do.
        from spectra.services import house
        house_reason = house.scene_deferral()
        if house_reason is not None:
            logger.info("select_color_set trigger: deferred — %s", house_reason)
            return
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

    async def _default_auto_refresh(self, uri: str) -> dict:
        # Same off-loop + serialized shape as _default_auto_generate: the
        # stamp check reads the song's analysis, and the write is one
        # whole-file rewrite under trigger_store.write_lock.
        from spectra.services import midsong_generator
        async with _get_generation_lock():
            result = await asyncio.to_thread(midsong_generator.refresh_song_if_stale, uri)
        if result.get("status") == "refreshed":
            logger.info("re-analysis: %s re-planned on play (%s)", uri, {
                k: result.get(k) for k in ("added", "updated", "deleted",
                                           "restamped", "moved")})
        return result

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
        from spectra.services import (room_controls, scene_compiler,
                                      scene_store, scene_transition_lead)
        from spectra.services.binding_resolver import FireContext

        controls = room_controls.load_room_controls()
        if controls.force_scene_enabled and controls.force_scene_scene_id:
            if scene_store.get_by_id(controls.force_scene_scene_id) is not None:
                scene_id = controls.force_scene_scene_id
        scene = scene_store.get_by_id(scene_id)
        if scene is None:
            return 0
        intensity = self._render_intensity(raw_intensity)
        # ONE definition of crossfade/anchor/lead, shared verbatim with the
        # transition scrubbing-preview (spectra/services/
        # scene_transition_lead.py — see its docstring for why a preview
        # that re-derives production's timing is a preview that can lie).
        # The 0.5-midpoint fallback and the max-across-virtuals rule both
        # live there now; this function's job is supplying the LIVE inputs.
        crossfade_ms = scene_transition_lead.crossfade_ms_for(
            scene, controls, intensity)
        resolved = scene_compiler.resolve_scene(scene, FireContext(intensity, rng=self._rng))
        writes = scene_compiler.compile_scene(resolved, color_set=None)
        current_types = {vid: getattr(st, "effect_type", None)
                         for vid, st in self._live_virtuals().items()}
        # A TRANSITION PROGRAM (transitions-drop plan phase 3) runs its own
        # clock, not the crossfade: its payoff is what lands on the mark.
        program_lead = scene_transition_lead.program_lead_ms(
            current_types, writes, controls)
        if program_lead is not None:
            return program_lead
        if crossfade_ms <= 0:
            return 0
        anchor = scene_transition_lead.anchor_frac_for(current_types, writes)
        return scene_transition_lead.lead_ms_for(anchor, crossfade_ms)

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
        from spectra.services import dwell, mode_availability, room_controls, scene_store
        if pin.scene_id == dwell.active_scene_id():
            # Pinned while another scene showed, but something has fired the
            # pinned one since: firing it again would change nothing — draw
            # fresh (excluding it) at the trigger's own moment instead.
            return False
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
        scene_response.band_trigger_offset_ms (see _band_anchor_ms for the
        min-over-every-declared-kind rule, zero included, and
        band_trigger_offset_ms for why a drop band's offset IS honoured
        where the lead's drop rule is not). No active scene = 0, the
        conservative nothing-to-read answer, same as the lead's own."""
        from spectra.services.scene_response import band_trigger_offset_ms
        scene = self._active_scene()
        if scene is None:
            return 0
        return band_trigger_offset_ms(scene, a.event_class,
                                      self._render_intensity(a.intensity))

    def _scene_offset_ms(self, trig: SpectraTrigger) -> int:
        """A fire_scene trigger's SCENE-side authored offset — the
        SceneV2.trigger_offset_ms of the scene this trigger will actually
        fire, HIS sign convention (negative = earlier). The scene-transition
        twin of _default_response_offset_ms above, authored by dragging the
        TRANSITION scrubbing-preview's marker, and summed with the
        trigger's own field by tick() exactly the way the flare-kind offset
        already is.

        ONLY CONSULTED FOR A SCENE THAT IS ALREADY KNOWN — a named
        scene_id, or a LOOKAHEAD pin that has already committed. This is a
        deliberate bound, not an oversight: an unresolved pick has no scene
        to read an offset from until _pin_for draws one, and forcing that
        draw here (from the much wider RESPONSE_OFFSET_HORIZON_MS gate
        tick() uses for offset peeks) would commit the pin up to 65s early
        instead of LOOKAHEAD_HORIZON_MS's 5s — widening the window a pin's
        validity can drift before it fires, which is the exact risk
        _pin_still_valid exists to contain. So the pin keeps its own
        horizon and an offset simply becomes visible once it commits: an
        authored offset inside that 5s horizon lands normally, one more
        negative than it degrades to firing at the un-relocated mark —
        late, never wrong, the same posture _scene_transition_lead_ms's own
        "no lead rather than a wrong one" rule already takes.

        Force Scene is deliberately NOT peeked here, unlike
        _scene_transition_lead_ms_for's own redirect peek. A redirect
        changes WHICH scene's crossfade the LEAD is describing (a timing
        quality question about a computed number); an offset is HIS
        AUTHORED alignment for the scene he was looking at, and silently
        swapping in a pinned override scene's alignment instead would
        retime his marks for a reason he never authored. A forced scene
        keeps its own offset only when it is genuinely the trigger's target.
        """
        from spectra.services import scene_store
        a = trig.action
        scene_id = a.scene_id
        if scene_id is None:
            pin = self._pins.get(trig.id)
            if pin is None:
                return 0
            scene_id = pin.scene_id
        scene = scene_store.get_by_id(scene_id)
        return getattr(scene, "trigger_offset_ms", 0) if scene is not None else 0

    @staticmethod
    def _live_virtuals() -> dict:
        from spectra.services import engine
        return engine.responses.conductor.virtuals

    @staticmethod
    def _active_scene():
        from spectra.services import engine
        return engine.responses.conductor.scene


trigger_engine = TriggerEngine()
