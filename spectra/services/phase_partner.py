"""THE PHASE PARTNER — what a charge or lull builds toward.

Phase 1 of the drop-detection plan (the Admiral approved it 2026-10-05:
"a charge builds to its own lull or drop, and a lull to its own drop,
whatever else sits between"). Read this before touching anything that
decides how long a charge or lull ramp runs; it is the ONE definition, and
three surfaces must agree with it:

  trigger_engine.TriggerEngine._phase_partner_gap_ms   the firing path
  spectra/web/src/timeline/phaseBlend.ts               the Timeline's mirror
  scripts/check_phase_partner_library.py               his library, old vs new

WHY IT EXISTS. A charge or lull ramps phase_progress to ~90% of a gap and
hangs the last ~10% (scene_response._phase_ramp_ms). Until this rule the
gap ran to the next trigger of ANY kind, so a flare placed inside a build
was taken as its end: 35 of his 167 sequence charges peaked at the flare
(median 2.3 s into a 6.8 s build) and then sat at full until the real drop.
A flare, a colour change or an update writes no phase, so it never ends a
build, and a build peaking there is just early. A scene change writes no
phase either; one that swaps the effect does lose the build (it builds a
fresh effect instance — drop-detection plan §2.4), but shortening every
build to it would not save the build. Keeping scene changes out of a
sequence is a placement problem (the plan's protected window, a later
phase), not a timing one. The next PHASE trigger is the one thing that
always ends a build, so only a phase trigger can be a build's target.

THE RULE, exactly. Among the triggers that will actually fire after this
one (the caller has already applied enabled + the song's effective mode):

  1. Find the next PHASE trigger (charge, lull or drop).
  2. If it is a PARTNER — later in charge → lull → drop than this one, so a
     lull or drop for a charge, a drop for a lull — and it sits within
     PARTNER_REACH_MS, the build runs to it. Everything in between is
     ignored.
  3. Otherwise there is no partner, and the build behaves EXACTLY AS IT
     DID BEFORE THIS RULE: the next trigger of any kind, else nothing
     (the caller's flat class default).

Step 3 is deliberate and is the narrow reading of "with no partner ahead,
keep today's fallback". He uses a charge with no lull or drop of its own
as an effect in itself (charge, flare, charge, flare …): measured on his
library, ~50 charges have no phase trigger after them at all and ~55 run
into ANOTHER charge first. Each of those builds into the next flare today.
Sending them to the flat 4 s default instead would change about a hundred
builds the plan never counted and he never approved; step 3 changes exactly
the sequences. A second charge (or, for a lull, a charge or another lull)
is a RESTART, not a partner: it rewrites phase_progress to 0 itself, so a
build reaching past it would be cut mid-ramp — the defect this rule fixes,
in reverse.

THE REACH is the effects' own absolute charge/lull cap
(fx.effects.particle_handoff.PHASE_HOLD_MAX_S, 60 s): a phase-capable
effect releases a build it has held that long whatever arrives, so no
partner past it can be built to. At the reach the ramp (54 s) still lands
inside that cap and the hang (6 s) inside its 12 s post-completion grace.
A partner beyond the reach falls to step 3 — today's behaviour.

DROP IS NEVER STRETCHED (scene_response.PHASE_RAMP_STRETCH_CLASSES), so a
drop has no build target; build_target answers TARGET_NONE for it.

Pure: no I/O, no engine state, so the engine, the library script and the
tests all call the same function.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from fx.effects.particle_handoff import PHASE_HOLD_MAX_S

# The phase family in the order a sequence runs. A later class is a partner;
# the same or an earlier class is a restart.
PHASE_ORDER: dict[str, int] = {"charge": 0, "lull": 1, "drop": 2}
BUILD_CLASSES: tuple[str, ...] = ("charge", "lull")

# Derived from the effects' own cap, never a second tuned number.
PARTNER_REACH_MS: int = round(PHASE_HOLD_MAX_S * 1000)

TARGET_PARTNER = "partner"            # its own lull or drop
TARGET_NEXT_TRIGGER = "next_trigger"  # no partner: the pre-rule behaviour
TARGET_NONE = "none"                  # nothing ahead: the flat class default


@dataclass(frozen=True)
class BuildTarget:
    """Where one charge/lull's build ends. `ms` is None exactly when
    `reason` is TARGET_NONE. `target_class` is the phase class of the
    target trigger, or None when the target is not a phase trigger."""
    ms: Optional[int]
    reason: str
    target_class: Optional[str] = None

    def gap_ms(self, start_ms: int) -> Optional[int]:
        if self.ms is None:
            return None
        gap = self.ms - start_ms
        return gap if gap > 0 else None


def is_partner(event_class: str, later_class: Optional[str]) -> bool:
    """True when `later_class` completes `event_class`'s build: a lull or
    drop for a charge, a drop for a lull."""
    if event_class not in BUILD_CLASSES or later_class not in PHASE_ORDER:
        return False
    return PHASE_ORDER[later_class] > PHASE_ORDER[event_class]


def build_target(event_class: str, start_ms: int,
                 later: Iterable[tuple[int, Optional[str]]]) -> BuildTarget:
    """The rule in the module docstring. `later` is (timestamp_ms,
    phase_class) for every OTHER trigger that will actually fire on this
    song — phase_class is "charge"/"lull"/"drop" for a phase trigger and
    None for anything else. Order does not matter; entries at or before
    `start_ms` are ignored, as the engine always has."""
    if event_class not in BUILD_CLASSES:
        return BuildTarget(None, TARGET_NONE)
    ahead = sorted(((ms, cls) for ms, cls in later if ms > start_ms),
                   key=lambda m: m[0])
    if not ahead:
        return BuildTarget(None, TARGET_NONE)
    nxt_phase = next(((ms, cls) for ms, cls in ahead if cls in PHASE_ORDER), None)
    if (nxt_phase is not None and is_partner(event_class, nxt_phase[1])
            and nxt_phase[0] - start_ms <= PARTNER_REACH_MS):
        return BuildTarget(nxt_phase[0], TARGET_PARTNER, nxt_phase[1])
    first_ms, first_cls = ahead[0]
    return BuildTarget(first_ms, TARGET_NEXT_TRIGGER,
                       first_cls if first_cls in PHASE_ORDER else None)

