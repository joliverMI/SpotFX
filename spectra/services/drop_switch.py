"""THE DROP-LED SCENE SWITCH — a drop sequence IS the scene change (drop-
scene-variety plan, phase 2; /home/javi/fleet-spotfx/data/drop-scene-
variety-plan/report.md options B + D, as the Admiral revised them).

Read this before touching anything that decides whether a drop sequence
changes the scene, or what a lull is told about the drop it leads into.

WHY. On a drop-heavy song the drops themselves never changed the scene: a
drop sequence fires as the SHOWING scene's charge/lull/drop responses
(drop_firing.py), and every sequence holds a protected window no planned
scene change may land in — so FINA played 13 drops, all on Fish. His ask:
let the drop BE the scene change when the showing scene has grown stale.
His two rulings on the plan (2026-10-08, verbatim):

  "I don't think it should cross fade, but just switch at the drop.
   Cross-fading during the lull could blend very different effects, but
   switching at the drop should be clean."

  "It should only do it at the beginning of the charge if it doesn't fit
   well at the drop because either A) The current scene doesn't have a good
   drop transition built for the next scene B) the current scene is already
   stale. Also, if there is a transiton/flare during the charge, that could
   be a good time to switch, other than right at the beginning."

THE DEFAULT: ON THE DROP, A HARD CUT.
  The charge and the lull run ENTIRELY on the outgoing scene; the lull is
  TOLD what is coming through the lull hand-off hook (fx/effects/
  lull_handoff.py — this module supplies its RESOLVER, `lull_handoff_
  resolver`, installed once from spectra/services/engine.py; it never
  builds a second hook). On the drop mark the trigger clock fires the
  target scene with a HARD CUT (scene_sequencer.fire_scene_by_id(...,
  origin="drop", cut=True) -> fx_seam.apply_writes(cut=True) -> the
  virtual's set_effect(cut=True), fx/VENDOR.md #63): the virtual's stored
  crossfade (his matrices: Add / 0.5 s, which every ordinary scene change
  still rides) is skipped for that write only, the outgoing effect's
  deactivate() leaves its particle snapshot, and the incoming effect adopts
  the leftover pieces on its first draw (fx/effects/particle_handoff.py's
  no-transition path). The drop member then fires in the SAME _fire call,
  on the new scene — so the incoming scene's own drop begins on the mark.
  (An effect born with a stale `phase` key never edge-fires it — the
  creation baseline every phase effect keeps — so the drop arm is the
  response's own write that immediately follows the cut, not a key smuggled
  into the scene write.)

THE EXCEPTION: EARLY, IN THE CHARGE (option D, his comment 2).
  Only when (A) the showing scene has no good drop hand-off into the chosen
  target (`HANDOFF`, below — no showing scene at all counts: there is
  nothing to hand off) or (B) the showing scene is ALREADY stale — it has
  OVERSTAYED: shown longer than its own minimum dwell plus
  `drop_switch_stale_margin_s`. (The other two stale reasons — it repeated
  the previous drop, it carried N drops in a row — are about the DROP, so
  they switch on the drop.) Then:
    - if a flare fires INSIDE the charge (>= RIDE_EDGE_MS from both ends),
      the cut RIDES the first one ("charge_flare"): the cut lands on the
      flare's mark, the charge is re-armed on the new effect at its current
      progress (ResponseEngine.rearm_phase), and the flare fires on the new
      scene's own band;
    - otherwise, at the charge START ("charge_start"): the cut, then the
      charge member fires on the new scene.
  A ride that never fires (disabled, held, gated) does not leave the switch
  hanging: the next member cuts instead ("charge_flare_missed"). A sequence
  with no charge, or one the trigger clock first meets at its lull, has no
  early moment and switches on the drop. A scene change that lands between
  the decision and the cut (his own fire_scene trigger) SUPERSEDES the
  plan: nothing is cut, and it says so.

THE STALE RULE (`decide`; every threshold is a RoomControlState field, his
to tune — the plan calls them "a first guess for his eye"):
  previous_drop    the showing scene played the PREVIOUS drop sequence's
                   drop on this song without arriving on it (a scene
                   installed BY a drop is fresh for the next one — so the
                   default alternates rather than switching every drop).
                   drop_switch_after_previous_drop.
  drops_in_a_row   it has carried drop_switch_drops_in_a_row drops (0 =
                   off), the drop that installed it included.
  overstayed       shown > its own latched dwell + drop_switch_stale_
                   margin_s. The reason that switches EARLY.
  nothing_showing  no scene is showing at all (100 MILLONES sat on nothing
                   through nine drops) — the first drop installs one,
                   early, since there is nothing to hand off.
  Not stale -> no switch ("fresh"). Force Scene on -> no switch (the pin
  owns the scene). A resting house mode -> no switch. All NAMED.

THE TARGET. A scene whose Matrix effect is in a drop-switch family (fx.
device_model.CENTRE_BURST_EFFECTS — STAR's radial, Orbits, Black Hole,
Squiggles, Fish — or DROP_FIREWORKS_EFFECTS), enabled, available in the
room's display mode, with a sequencer entry (so House Star / House Fish /
Pulse Test are never drawn), never the showing scene; drawn by the SAME
selection kernel the planned scene changes use, at the sequence's own
intensity, with a Random seeded by (song, sequence key, showing scene) —
DETERMINISTIC, so the room, the Timeline and Sonic agree about one decision.

THE HAND-OFF TABLE (`HANDOFF`). Every ordered pair of drop-switch effects
has one, because every member's _adopt_handoff takes any predecessor's
snapshot (report E6): "choreographed" where the incoming effect stages the
arrival (radial's standalone bloom out of the particles; a particle effect
erupting from STAR's imploded point), "generic" otherwise (the pieces join
the incoming effect as its own particles), and the three FIREWORKS MELDS
below. An outgoing effect outside the families (the Eye, the Dancer,
Pac-Man) has no row: no good drop hand-off, so its switch goes early (A).

THE FIREWORKS MELDS (drop-scene-variety plan phase 3, option C — his ask:
"fish and orbits could have 3 'particles' remain instead of just 1 and
then they could explode into fireworks on the drop, but going from
fireworks to others might need to have the standard effect followed by a
transition into the other effects after the initial burst, but the other
effect needs to come in loud to maintain the energy. So example could be
the fireworks drops, then immediately those big fireworks get swallowed by
the black hole, or they explode and then on the next big bass hit they
implode into the fish, orbit particle, squiggle, etc."). All three are the
SAME one-call hard cut every drop-led switch makes; only the moment moves.
  INTO FIREWORKS ("keepers", fish/orbits -> fireworks): the lull is told
    `lull_keep = FIREWORKS_KEEP` (3) and `lull_next = "fireworks"`; the
    fish leaves three spaced searching keepers, orbits three spaced blobs,
    and each flags them in its snapshot. The cut lands ON the drop mark as
    usual; Fireworks turns every flagged keeper into a held rocket where it
    stands and the drop arm that follows explodes each one (fx/effects/
    fireworks.py's KEEPERS MELD). Every other pair into Fireworks keeps the
    generic cut on the drop.
  OUT 1, SWALLOWED ("swallowed", fireworks -> blackhole): Fireworks plays
    its OWN drop, then `drop_switch_swallow_delay_s` (1 s) after the drop
    mark the scene cuts to the Black Hole, whose generic adopt pulls the
    whole burst cloud into its infall ("after_drop").
  OUT 2, IMPLODE ON THE NEXT HIT ("implode_on_hit", fireworks -> fish /
    orbits / squiggles / STAR): Fireworks plays its own drop; the switch is
    ARMED at the drop and released by THE NEXT BIG BASS HIT, defined once
    (`next_big_hit`): the first ANALYSED flare after the drop (past the
    drop's own MATCH_BEATS reach, where a flare is silenced anyway) whose
    intensity is at least `drop_switch_hit_threshold`. The cut lands just
    before that flare fires, so the flare itself lands on the incoming
    scene's own band — the "comes in loud". No hit by the DEADLINE (the
    sequence's protected tail plus one bar, `hit_deadline_ms`) and the cut
    lands there, firing the incoming scene's flare itself — a pending
    switch is never left hanging. STAR is included beside his three named
    effects (his "etc.": its adopt gathers the particles into its bloom).
  A late switch still pending when the NEXT sequence's first member fires
  is cut at that moment ("before_next_sequence"), so two decisions never
  hold the room at once.

THE LULL IS TOLD (`handoff_for`). A plan switching ON the drop answers the
lull: `next_effect` per virtual = the effect the target scene will install
there, `keep` = KEEP_FOR the target's family (Fireworks: FIREWORKS_KEEP).
A late plan (Out 1/2) runs its lull on the showing scene, which is not
told anything new. An early plan has already switched by the lull, so the
lull is told the same effect (""), keep default. The trigger clock marks the plan
current around the lull member's fire (`lull_plan`, a ContextVar — the
resolver runs inside that same await chain), with a song-position lookup
as the fallback; no plan -> the hook's own default.

WHAT IS RECORDED. Every decision — switch or not, and why — lands in the
process-wide registry (`record_plan`, `plans_for`), read by the Timeline's
drop-sequence strip (drop_firing.annotate's `switch`), the sequence
preview, and Sonic's read-only `explain_drop_switch`. Every executed (or
superseded / gated) cut lands in the show log under the sequence key
(fire_history "triggers" / "drop_sequence:switch") and on the plan as its
`outcome`.

Every time is SONG time (the trigger clock's frame).
"""
from __future__ import annotations

import hashlib
import logging
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field, replace
from random import Random
from typing import Any, Callable, Mapping, Optional

from fx import device_model
from fx.effects import lull_handoff

logger = logging.getLogger(__name__)

MOMENT_DROP = "drop"
MOMENT_CHARGE_START = "charge_start"
MOMENT_CHARGE_FLARE = "charge_flare"
EARLY_MOMENTS = (MOMENT_CHARGE_START, MOMENT_CHARGE_FLARE)
# THE FIREWORKS MELDS' two moments AFTER the drop (module docstring)
MOMENT_AFTER_DROP = "after_drop"
MOMENT_NEXT_HIT = "next_hit"
LATE_MOMENTS = (MOMENT_AFTER_DROP, MOMENT_NEXT_HIT)

STALE_PREVIOUS_DROP = "previous_drop"
STALE_DROPS_IN_A_ROW = "drops_in_a_row"
STALE_OVERSTAYED = "overstayed"
STALE_NOTHING_SHOWING = "nothing_showing"

# A flare counts as INSIDE the charge only this far from both of the
# charge's ends (the plan's own measurement rule, report E8).
RIDE_EDGE_MS = 250

HANDOFF_CHOREOGRAPHED = "choreographed"
HANDOFF_GENERIC = "generic"
HANDOFF_SAME_EFFECT = "same_effect"
# THE FIREWORKS MELDS (module docstring)
HANDOFF_KEEPERS = "keepers"
HANDOFF_SWALLOWED = "swallowed"
HANDOFF_IMPLODE_ON_HIT = "implode_on_hit"

# How many keepers a lull leaves for a Fireworks drop (his "3 'particles'
# remain instead of just 1").
FIREWORKS_KEEP = 3

# THE NEXT BIG BASS HIT (`next_big_hit`): never sooner than this after the
# drop mark, whatever the beat (the payoff's own burst is the first ~second).
HIT_MIN_AFTER_MS = 500
# ... and the deadline: the sequence's protected tail plus one bar.
BAR_BEATS = 4
FALLBACK_BEAT_MS = 500.0


def _handoff_table() -> dict[tuple[str, str], str]:
    """(outgoing Matrix effect, incoming Matrix effect) -> how the pieces
    cross on a cut (module docstring, THE HAND-OFF TABLE)."""
    table: dict[tuple[str, str], str] = {}
    particles = device_model.CENTRE_BURST_EFFECTS - {"radial"}
    fireworks = device_model.DROP_FIREWORKS_EFFECTS
    for out in device_model.DROP_SWITCH_EFFECTS:
        for inc in device_model.DROP_SWITCH_EFFECTS:
            if out == inc:
                table[(out, inc)] = HANDOFF_SAME_EFFECT
            elif inc in fireworks and out in device_model.LULL_HANDOFF_EFFECTS:
                # the lull leaves FIREWORKS_KEEP keepers that burst on the drop
                table[(out, inc)] = HANDOFF_KEEPERS
            elif out in fireworks and inc == "blackhole":
                # Fireworks drops, then the Black Hole swallows the cloud
                table[(out, inc)] = HANDOFF_SWALLOWED
            elif out in fireworks and inc in device_model.CENTRE_BURST_EFFECTS:
                # Fireworks drops, then implodes into the next scene on the
                # next big bass hit
                table[(out, inc)] = HANDOFF_IMPLODE_ON_HIT
            elif inc == "radial" and out in particles:
                # radial gathers the particles and blooms out of the centre
                table[(out, inc)] = HANDOFF_CHOREOGRAPHED
            elif out == "radial" and inc in particles:
                # the imploded point erupts as the incoming particles
                table[(out, inc)] = HANDOFF_CHOREOGRAPHED
            else:
                table[(out, inc)] = HANDOFF_GENERIC
    return table


HANDOFF: dict[tuple[str, str], str] = _handoff_table()

# How many pieces the lull leaves for each target family: Fireworks wants
# FIREWORKS_KEEP keepers as its payoff's origins (the KEEPERS meld).
KEEP_FOR: dict[str, int] = {
    "centre_burst": lull_handoff.DEFAULT_KEEP,
    "fireworks": FIREWORKS_KEEP,
}


def family_of(effect: Optional[str]) -> Optional[str]:
    if effect in device_model.CENTRE_BURST_EFFECTS:
        return "centre_burst"
    if effect in device_model.DROP_FIREWORKS_EFFECTS:
        return "fireworks"
    return None


def handoff_kind(out_effect: Optional[str], in_effect: Optional[str]) -> Optional[str]:
    """The hand-off for a pair, or None when there is no good one."""
    if out_effect is None or in_effect is None:
        return None
    return HANDOFF.get((out_effect, in_effect))


# ── the inputs ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SwitchSettings:
    """The room's tunables (RoomControlState.drop_switch_*)."""
    enabled: bool = True
    after_previous_drop: bool = True
    stale_margin_s: float = 10.0
    drops_in_a_row: int = 2
    # THE FIREWORKS MELDS (module docstring)
    swallow_delay_s: float = 1.0
    hit_threshold: float = 0.6

    @classmethod
    def from_room(cls, room: Any) -> "SwitchSettings":
        d = cls()
        return cls(
            enabled=bool(getattr(room, "drop_switch_enabled", d.enabled)),
            after_previous_drop=bool(getattr(room, "drop_switch_after_previous_drop",
                                             d.after_previous_drop)),
            stale_margin_s=float(getattr(room, "drop_switch_stale_margin_s",
                                         d.stale_margin_s)),
            drops_in_a_row=int(getattr(room, "drop_switch_drops_in_a_row",
                                       d.drops_in_a_row)),
            swallow_delay_s=float(getattr(room, "drop_switch_swallow_delay_s",
                                          d.swallow_delay_s)),
            hit_threshold=float(getattr(room, "drop_switch_hit_threshold",
                                        d.hit_threshold)))


@dataclass(frozen=True)
class SceneInfo:
    id: str
    name: str
    effect: Optional[str]


@dataclass(frozen=True)
class Showing:
    """The showing scene's run, as the decision reads it. `stint` is its
    identity (dwell.stint(): scene id + latch ms)."""
    scene: SceneInfo
    stint: Any
    shown_s: Optional[float]
    dwell_s: Optional[float]


@dataclass(frozen=True)
class StintRecord:
    """What this song's drop history says about the showing stint."""
    drops_carried: int = 0
    carried_previous_drop: bool = False
    arrived_on_previous_drop: bool = False


class DropHistory:
    """Per song (the trigger clock owns one and resets it on a song change):
    which stint played each drop sequence's drop, and whether that drop
    installed it."""

    def __init__(self) -> None:
        self._counts: dict[Any, int] = {}
        self._previous: Optional[tuple[str, Any, bool]] = None

    def record_for(self, stint: Any) -> StintRecord:
        prev = self._previous
        carried = prev is not None and stint is not None and prev[1] == stint
        return StintRecord(
            drops_carried=self._counts.get(stint, 0) if stint is not None else 0,
            carried_previous_drop=carried,
            arrived_on_previous_drop=bool(carried and prev[2]))

    def note_drop(self, key: str, stint: Any, arrived: bool) -> None:
        if stint is None:
            return
        self._counts[stint] = self._counts.get(stint, 0) + 1
        self._previous = (key, stint, bool(arrived))

    def as_dict(self) -> dict:
        prev = self._previous
        return {"previous_drop": None if prev is None else
                {"key": prev[0], "scene_id": prev[1][0] if prev[1] else None,
                 "arrived": prev[2]}}


# ── the plan ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SwitchPlan:
    """One decision for one drop sequence. `switch` False carries the
    reason nothing switches; True names the target, the moment and the
    hand-off. `outcome` is filled in when the cut is executed (or
    superseded / gated) — see `note_outcome`."""
    key: str
    uri: Optional[str]
    switch: bool
    reason: str
    sentence: str
    stale_by: tuple[str, ...] = ()
    from_scene_id: Optional[str] = None
    from_scene_name: Optional[str] = None
    from_effect: Optional[str] = None
    to_scene_id: Optional[str] = None
    to_scene_name: Optional[str] = None
    to_effect: Optional[str] = None
    handoff: Optional[str] = None
    moment: Optional[str] = None
    ride_trigger_id: Optional[str] = None
    ride_ms: Optional[int] = None
    charge_ms: Optional[int] = None
    lull_ms: Optional[int] = None
    drop_ms: Optional[int] = None
    shown_s: Optional[float] = None
    dwell_s: Optional[float] = None
    drops_carried: int = 0
    decided_at_ms: Optional[int] = None
    outcome: Optional[dict] = None
    lull_handoff: Optional[dict] = None
    # THE FIREWORKS MELDS' late moments: where the cut lands after the drop
    # (`release_ms`), what releases it ("delay" | "hit" | "deadline"), the
    # analysed flare that is the next big hit, and the hit's deadline.
    release_ms: Optional[int] = None
    release_by: Optional[str] = None
    hit_trigger_id: Optional[str] = None
    deadline_ms: Optional[int] = None

    @property
    def early(self) -> bool:
        return self.switch and self.moment in EARLY_MOMENTS

    @property
    def late(self) -> bool:
        return self.switch and self.moment in LATE_MOMENTS

    def cut_ms(self) -> Optional[int]:
        """Where the cut is planned to land (song time)."""
        if not self.switch:
            return None
        if self.moment in LATE_MOMENTS:
            return self.release_ms
        if self.moment == MOMENT_CHARGE_FLARE:
            return self.ride_ms
        if self.moment == MOMENT_CHARGE_START:
            return self.charge_ms
        return self.drop_ms

    def as_dict(self) -> dict:
        d = asdict(self)
        d["stale_by"] = list(self.stale_by)
        d["cut_ms"] = self.cut_ms()
        return d


def _sentence_no(reason: str, showing: Optional[Showing]) -> str:
    name = showing.scene.name if showing is not None else "the scene"
    return {
        "off": "The drop-led scene switch is turned off.",
        "force_scene": "Force Scene is on — the pinned scene owns the room.",
        "house_mode": "A house mode is resting — it owns the room's scene.",
        "fresh": f"{name} is still fresh — the drop plays on it.",
        "no_target": (f"{name} is stale, but no other drop-ready scene "
                      "(STAR, Orbits, Black Hole, Squiggles, Fish, "
                      "Fireworks) can be picked."),
    }.get(reason, reason)


_STALE_WORDS = {
    STALE_PREVIOUS_DROP: "it already played the previous drop",
    STALE_DROPS_IN_A_ROW: "it has carried {n} drops in a row",
    STALE_OVERSTAYED: "it has overstayed its dwell",
    STALE_NOTHING_SHOWING: "nothing was showing",
}

_MOMENT_WORDS = {
    MOMENT_DROP: "a hard cut on the drop",
    MOMENT_CHARGE_START: "a hard cut at the start of the charge",
    MOMENT_CHARGE_FLARE: "a hard cut on the flare inside the charge",
    MOMENT_AFTER_DROP: "a hard cut just after its own drop",
    MOMENT_NEXT_HIT: "a hard cut on the next big bass hit after its own drop",
}

_HANDOFF_WORDS = {
    HANDOFF_KEEPERS: "the lull leaves three keepers that burst on the drop",
    HANDOFF_SWALLOWED: "the Black Hole swallows the burst",
    HANDOFF_IMPLODE_ON_HIT: "the burst implodes into it, which comes in loud",
}


def _sentence_yes(showing: Optional[Showing], target: SceneInfo,
                  stale_by: tuple[str, ...], moment: str,
                  handoff: Optional[str], drops: int) -> str:
    why = "; ".join(_STALE_WORDS[s].format(n=drops) for s in stale_by)
    frm = showing.scene.name if showing is not None else "nothing"
    early_why = ""
    if moment in EARLY_MOMENTS and STALE_NOTHING_SHOWING in stale_by:
        early_why = " — early, since there is nothing to hand off"
    elif moment in EARLY_MOMENTS:
        parts = []
        if handoff is None:
            parts.append("there is no good drop hand-off from "
                         f"{frm} into {target.name}")
        if STALE_OVERSTAYED in stale_by:
            parts.append("it is already stale")
        if parts:
            early_why = " — early because " + " and ".join(parts)
    hand = f" ({handoff} hand-off)" if handoff else ""
    meld = _HANDOFF_WORDS.get(handoff or "")
    meld = f" — {meld}" if meld else ""
    return (f"{frm} → {target.name}, {_MOMENT_WORDS[moment]}{hand}: "
            f"{why}{early_why}{meld}.")


def hit_deadline_ms(drop_ms: int, beat_ms: Optional[float]) -> int:
    """OUT 2's deadline: the sequence's protected tail (drop_detector.
    TAIL_BEATS) plus one bar after the drop mark."""
    from spectra.services import drop_detector
    beat = float(beat_ms) if beat_ms and beat_ms > 0 else FALLBACK_BEAT_MS
    return int(round(drop_ms + (drop_detector.TAIL_BEATS + BAR_BEATS) * beat))


def next_big_hit(flares, drop_ms: int, beat_ms: Optional[float],
                 threshold: float, until_ms: Optional[int] = None
                 ) -> Optional[tuple[str, int]]:
    """THE NEXT BIG BASS HIT, defined once: the first ANALYSED flare
    (`flares` = (trigger id, song ms, intensity)) strictly after the drop's
    own reach — MATCH_BEATS beats, where an analysed flare is silenced
    anyway (drop_firing.Window.at_drop), and never sooner than
    HIT_MIN_AFTER_MS — up to `until_ms`, whose intensity is at least
    `threshold`. None when there is no such flare."""
    from spectra.services import drop_firing
    beat = float(beat_ms) if beat_ms and beat_ms > 0 else FALLBACK_BEAT_MS
    after = drop_ms + max(HIT_MIN_AFTER_MS, drop_firing.MATCH_BEATS * beat)
    hits = sorted((int(ms), tid) for tid, ms, inten in flares
                  if ms > after and (until_ms is None or ms <= until_ms)
                  and float(inten) >= float(threshold))
    return (hits[0][1], hits[0][0]) if hits else None


def late_release(plan: SwitchPlan, settings: SwitchSettings,
                 flares=(), beat_ms: Optional[float] = None) -> SwitchPlan:
    """Where a late plan's cut lands (module docstring, THE FIREWORKS
    MELDS): `swallow_delay_s` after the drop, or the next big hit, or the
    deadline. Recomputed when the drop arms it, since the song's analysed
    flares may have been planned since the decision."""
    if not plan.late or plan.drop_ms is None:
        return plan
    if plan.moment == MOMENT_AFTER_DROP:
        return replace(plan, release_by="delay", hit_trigger_id=None,
                       deadline_ms=None,
                       release_ms=int(round(plan.drop_ms
                                            + max(0.0, settings.swallow_delay_s) * 1000)))
    deadline = hit_deadline_ms(plan.drop_ms, beat_ms)
    hit = next_big_hit(flares, plan.drop_ms, beat_ms, settings.hit_threshold,
                       until_ms=deadline)
    if hit is not None:
        return replace(plan, release_by="hit", hit_trigger_id=hit[0],
                       release_ms=hit[1], deadline_ms=deadline)
    return replace(plan, release_by="deadline", hit_trigger_id=None,
                   release_ms=deadline, deadline_ms=deadline)


def stale_reasons(showing: Optional[Showing], record: StintRecord,
                  settings: SwitchSettings) -> tuple[str, ...]:
    if showing is None:
        return (STALE_NOTHING_SHOWING,)
    out = []
    if (settings.after_previous_drop and record.carried_previous_drop
            and not record.arrived_on_previous_drop):
        out.append(STALE_PREVIOUS_DROP)
    if settings.drops_in_a_row > 0 and record.drops_carried >= settings.drops_in_a_row:
        out.append(STALE_DROPS_IN_A_ROW)
    if (showing.shown_s is not None and showing.dwell_s is not None
            and showing.shown_s > showing.dwell_s + settings.stale_margin_s):
        out.append(STALE_OVERSTAYED)
    return tuple(out)


def seeded_rng(uri: Optional[str], key: str, showing_id: Optional[str]) -> Random:
    """The determinism the plan requires: one (song, sequence, showing
    scene) always draws the same target."""
    h = hashlib.sha256(f"{uri}|{key}|{showing_id}".encode()).hexdigest()
    return Random(int(h[:16], 16))


def decide(*, key: str, uri: Optional[str], members: Mapping[str, int],
           showing: Optional[Showing], record: StintRecord,
           settings: SwitchSettings,
           pick_target: Callable[[Optional[str], Random], Optional[SceneInfo]],
           ride: Optional[tuple[str, int]] = None,
           can_go_early: bool = True,
           blocker: Optional[str] = None,
           decided_at_ms: Optional[int] = None,
           flares=(), beat_ms: Optional[float] = None) -> SwitchPlan:
    """The resolver's one decision for one sequence (module docstring).
    Pure: everything live is handed in. `members` is {class: song ms} for
    the members that will fire; `ride` the first flare inside the charge;
    `can_go_early` False when the charge has already passed (the clock met
    the sequence at its lull or drop); `flares` the song's ANALYSED flares
    as (trigger id, song ms, intensity) and `beat_ms` the sequence's beat,
    for a late Fireworks meld (late_release)."""
    base = dict(key=key, uri=uri, charge_ms=members.get("charge"),
                lull_ms=members.get("lull"), drop_ms=members.get("drop"),
                decided_at_ms=decided_at_ms,
                drops_carried=record.drops_carried)
    if showing is not None:
        base.update(from_scene_id=showing.scene.id,
                    from_scene_name=showing.scene.name,
                    from_effect=showing.scene.effect,
                    shown_s=None if showing.shown_s is None else round(showing.shown_s, 2),
                    dwell_s=None if showing.dwell_s is None else round(showing.dwell_s, 2))

    def no(reason: str, stale: tuple[str, ...] = ()) -> SwitchPlan:
        return SwitchPlan(switch=False, reason=reason, stale_by=stale,
                          sentence=_sentence_no(reason, showing), **base)

    if not settings.enabled:
        return no("off")
    if blocker is not None:
        return no(blocker)
    stale = stale_reasons(showing, record, settings)
    if not stale:
        return no("fresh")
    showing_id = showing.scene.id if showing is not None else None
    target = pick_target(showing_id, seeded_rng(uri, key, showing_id))
    if target is None or target.id == showing_id:
        return no("no_target", stale)
    handoff = handoff_kind(showing.scene.effect if showing else None, target.effect)
    wants_early = handoff is None or STALE_OVERSTAYED in stale \
        or STALE_NOTHING_SHOWING in stale
    has_charge = members.get("charge") is not None
    if wants_early and has_charge and can_go_early:
        moment = MOMENT_CHARGE_FLARE if ride is not None else MOMENT_CHARGE_START
    elif handoff == HANDOFF_SWALLOWED and members.get("drop") is not None:
        moment = MOMENT_AFTER_DROP
    elif handoff == HANDOFF_IMPLODE_ON_HIT and members.get("drop") is not None:
        moment = MOMENT_NEXT_HIT
    else:
        moment = MOMENT_DROP
    plan = SwitchPlan(
        switch=True, reason="stale", stale_by=stale,
        sentence=_sentence_yes(showing, target, stale, moment, handoff,
                               record.drops_carried),
        to_scene_id=target.id, to_scene_name=target.name, to_effect=target.effect,
        handoff=handoff, moment=moment,
        ride_trigger_id=ride[0] if moment == MOMENT_CHARGE_FLARE else None,
        ride_ms=ride[1] if moment == MOMENT_CHARGE_FLARE else None,
        **base)
    return late_release(plan, settings, flares, beat_ms)


def find_ride(charge_ms: Optional[int], end_ms: Optional[int],
              flares: list[tuple[str, int]]) -> Optional[tuple[str, int]]:
    """The first flare strictly inside the charge (RIDE_EDGE_MS from both
    ends), or None. `flares` is (trigger id, song ms)."""
    if charge_ms is None or end_ms is None:
        return None
    lo, hi = charge_ms + RIDE_EDGE_MS, end_ms - RIDE_EDGE_MS
    inside = sorted((ms, tid) for tid, ms in flares if lo <= ms <= hi)
    return (inside[0][1], inside[0][0]) if inside else None


# ── the lull hand-off resolver (the hook's plug-in) ──────────────────────

def scene_effect(scene: Any) -> Optional[str]:
    """A scene's drop-deciding effect: its Matrix entry's base effect, else
    the first entry whose effect is in a drop-switch family."""
    devices = list(getattr(scene, "devices", None) or [])
    for e in devices:
        if getattr(e, "target_kind", None) == "category" and getattr(e, "target", "") == "Matrix":
            return e.effect_type or None
    for e in devices:
        if e.effect_type in device_model.DROP_SWITCH_EFFECTS:
            return e.effect_type
    return None


def scene_virtual_effects(scene: Any) -> dict[str, str]:
    """{virtual id: effect type} the scene installs (base effects; narrower
    entries win: all < category < virtual, the compiler's own order)."""
    out: dict[str, str] = {}
    rank = {"all": 0, "category": 1, "virtual": 2}
    entries = sorted(getattr(scene, "devices", None) or [],
                     key=lambda e: rank.get(getattr(e, "target_kind", "category"), 1))
    for e in entries:
        if not e.effect_type:
            continue
        if e.target_kind == "virtual":
            vids = [e.target]
        elif e.target_kind == "category":
            try:
                vids = device_model.get_virtuals_for_category(e.target)
            except Exception:                            # noqa: BLE001
                vids = []
        elif e.target_kind == "all":
            try:
                vids = device_model.get_all_virtual_ids()
            except Exception:                            # noqa: BLE001
                vids = []
        else:
            continue
        for vid in vids:
            out[vid] = e.effect_type
    return out


def handoff_for(plan: Optional[SwitchPlan], ctx: Any,
                target_scene: Any = None) -> "Any":
    """What a lull is told under `plan` (module docstring, THE LULL IS
    TOLD). Returns a scene_response.LullHandoff."""
    from spectra.services.scene_response import LullHandoff
    lull_s = getattr(ctx, "lull_s", 0.0)
    if plan is None or not plan.switch or plan.moment != MOMENT_DROP:
        return LullHandoff(keep=lull_handoff.DEFAULT_KEEP, next_effect={},
                           lull_s=lull_s)
    if target_scene is None:
        target_scene = _scene_by_id(plan.to_scene_id)
    installs = scene_virtual_effects(target_scene) if target_scene is not None else {}
    current = dict(getattr(ctx, "virtuals", {}) or {})
    nxt = {vid: eff for vid, eff in installs.items()
           if vid in current and current.get(vid) != eff}
    keep = KEEP_FOR.get(family_of(plan.to_effect) or "", lull_handoff.DEFAULT_KEEP)
    return LullHandoff(keep=keep, next_effect=nxt, lull_s=lull_s)


_lull_plan: ContextVar[Optional[SwitchPlan]] = ContextVar("drop_switch_lull_plan",
                                                          default=None)


class lull_plan:
    """`with lull_plan(plan): await fire_lull(...)` — marks `plan` as the one
    the resolver answers from while this lull's arm is resolved."""

    def __init__(self, plan: Optional[SwitchPlan]) -> None:
        self.plan = plan
        self._token = None

    def __enter__(self):
        self._token = _lull_plan.set(self.plan)
        return self

    def __exit__(self, *exc):
        _lull_plan.reset(self._token)
        return False


def plan_for_position(uri: Optional[str], position_ms: Optional[int],
                      slack_ms: int = 2000) -> Optional[SwitchPlan]:
    """The plan whose lull..drop span covers `position_ms` on `uri` — the
    resolver's fallback when no lull plan was marked current."""
    if uri is None or position_ms is None:
        return None
    for p in plans_for(uri):
        if p.lull_ms is None or p.drop_ms is None:
            continue
        if p.lull_ms - slack_ms <= position_ms <= p.drop_ms:
            return p
    return None


def lull_handoff_resolver(ctx: Any):
    """THE resolver installed into scene_response's lull hand-off hook
    (engine.py). Pure and cheap: a ContextVar read or a short scan."""
    plan = _lull_plan.get()
    if plan is None:
        plan = plan_for_position(getattr(ctx, "uri", None),
                                 getattr(ctx, "position_ms", None))
    answer = handoff_for(plan, ctx)
    if plan is not None:
        record_lull_handoff(plan, answer)
    return answer


lull_handoff_resolver.__name__ = "drop_switch"


# ── the registry ─────────────────────────────────────────────────────────

MAX_SONGS = 8
_plans: dict[str, dict[str, SwitchPlan]] = {}


def record_plan(plan: SwitchPlan) -> SwitchPlan:
    uri = plan.uri or ""
    song = _plans.setdefault(uri, {})
    song[plan.key] = plan
    while len(_plans) > MAX_SONGS:
        _plans.pop(next(iter(_plans)))
    return plan


def note_outcome(plan: SwitchPlan, outcome: dict) -> SwitchPlan:
    updated = replace(plan, outcome=dict(outcome))
    return record_plan(updated)


def record_lull_handoff(plan: SwitchPlan, answer: Any) -> None:
    cur = (_plans.get(plan.uri or "") or {}).get(plan.key)
    if cur is None:
        return
    record_plan(replace(cur, lull_handoff={
        "keep": getattr(answer, "keep", None),
        "next": dict(getattr(answer, "next_effect", {}) or {})}))


def plans_for(uri: Optional[str]) -> list[SwitchPlan]:
    return sorted((_plans.get(uri or "") or {}).values(),
                  key=lambda p: (p.drop_ms or 0))


def plan(uri: Optional[str], key: str) -> Optional[SwitchPlan]:
    return (_plans.get(uri or "") or {}).get(key)


def forget(uri: Optional[str] = None) -> None:
    if uri is None:
        _plans.clear()
    else:
        _plans.pop(uri, None)


def explain(uri: Optional[str], key: Optional[str] = None,
            drop_ms: Optional[int] = None) -> Optional[dict]:
    """Sonic's "why did it (not) switch": the plan for a sequence key, or
    the one nearest `drop_ms`, with its sentence and outcome."""
    plans = plans_for(uri)
    if not plans:
        return None
    if key is not None:
        hit = next((p for p in plans if p.key == key), None)
    elif drop_ms is not None:
        hit = min(plans, key=lambda p: abs((p.drop_ms or 0) - drop_ms))
    else:
        hit = plans[-1]
    return None if hit is None else hit.as_dict()


# ── production defaults (lazy: the trigger clock injects fakes in tests) ──

def _scene_by_id(scene_id: Optional[str]) -> Any:
    if scene_id is None:
        return None
    try:
        from spectra.services import scene_store
        return scene_store.get_by_id(scene_id)
    except Exception:                                    # noqa: BLE001
        return None


def scene_info(scene: Any) -> Optional[SceneInfo]:
    if scene is None:
        return None
    return SceneInfo(id=scene.id, name=scene.name, effect=scene_effect(scene))


def eligible_targets() -> dict[str, SceneInfo]:
    """Every scene a drop may switch INTO (module docstring, THE TARGET)."""
    from spectra.services import mode_availability, scene_store, sequencer_store
    from spectra.services.room_controls import load_room_controls
    config = sequencer_store.load_config()
    room_mode = load_room_controls().display_mode
    out: dict[str, SceneInfo] = {}
    for s in scene_store.list_all():
        if s.id not in config.entries or getattr(s, "disabled", False):
            continue
        if not mode_availability.available_in_room_mode(
                s.display_availability, room_mode):
            continue
        eff = scene_effect(s)
        if family_of(eff) is None:
            continue
        out[s.id] = SceneInfo(id=s.id, name=s.name, effect=eff)
    return out


def default_pick_target(intensity: float) -> Callable[[Optional[str], Random], Optional[SceneInfo]]:
    """The kernel draw over `eligible_targets`, the showing scene excluded
    (the kernel's current_id) and its affinity applied (prev_id)."""
    def pick(showing_id: Optional[str], rng: Random) -> Optional[SceneInfo]:
        from spectra.services import selection_kernel as kernel, sequencer_store
        try:
            from spectra.services.engine import bridge
            genre = bridge.genre_bucket()
        except Exception:                                # noqa: BLE001
            genre = None
        targets = eligible_targets()
        if showing_id is not None:
            targets.pop(showing_id, None)
        if not targets:
            return None
        config = sequencer_store.load_config()
        candidates = kernel.build_scene_candidates(
            config.entries, sequencer_store.load_curves(), config.affinity,
            genre_bucket=genre, prev_id=showing_id, restrict_ids=set(targets))
        picked = kernel.select(candidates, intensity=intensity, rng=rng,
                               current_id=showing_id,
                               terminal=kernel.TERMINAL_STAY).picked_id
        return targets.get(picked) if picked is not None else None
    return pick


def default_showing() -> Optional[Showing]:
    from spectra.services import dwell
    stint = dwell.stint()
    if stint is None:
        return None
    scene = _scene_by_id(stint[0])
    if scene is None:
        return None
    return Showing(scene=scene_info(scene), stint=stint,
                   shown_s=dwell.shown_s(), dwell_s=dwell.latched_dwell_s())


def default_blocker() -> Optional[str]:
    """Force Scene owns the room; a resting house mode owns the room."""
    try:
        from spectra.services.room_controls import load_room_controls
        room = load_room_controls()
        if room.force_scene_enabled and room.force_scene_scene_id:
            return "force_scene"
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from spectra.services import house
        if house.scene_deferral() is not None:
            return "house_mode"
    except Exception:                                    # noqa: BLE001
        pass
    return None


def default_settings() -> SwitchSettings:
    from spectra.services.room_controls import load_room_controls
    return SwitchSettings.from_room(load_room_controls())


# ── the sequence preview (phase_preview.py) ──────────────────────────────

def preview_plan(scene: Any, intensity: float,
                 pick_target: Optional[Callable] = None,
                 settings: Optional[SwitchSettings] = None) -> SwitchPlan:
    """What the resolver would do for `scene` at a drop where it has grown
    stale by repetition (it played the previous drop) — the case the
    sequence preview shows him, deterministic for the scene. The moment
    follows the hand-off table only (the preview has no dwell to have
    overstayed)."""
    info = scene_info(scene)
    showing = Showing(scene=info, stint=("preview", scene.id),
                      shown_s=None, dwell_s=None)
    record = StintRecord(drops_carried=1, carried_previous_drop=True,
                         arrived_on_previous_drop=False)
    return decide(key=f"preview:{scene.id}", uri=None,
                  members={"charge": 0, "lull": 1, "drop": 2},
                  showing=showing, record=record,
                  # only the room's on/off applies: the staleness is the
                  # preview's stated assumption, not a threshold to clear
                  settings=SwitchSettings(enabled=(settings or SwitchSettings()).enabled),
                  pick_target=pick_target or default_pick_target(intensity))
