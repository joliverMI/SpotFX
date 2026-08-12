"""Phased effect transitions: fire the switch early so the payoff lands on the beat.

Some LedFX effect switches choreograph a multi-phase transition that rides the
crossfade (see ledfx/effects/particle_handoff.py). The visually loud moment —
the radial blooming out of gathered particles, the eruption burst out of a
collapsed radial, pacman's entities morphing into particles after the maze has
faded — doesn't happen at the switch instant but at a fixed FRACTION of the
crossfade. Because the whole choreography is deterministic (it advances on the
virtual's transition frame counter), the trigger engine can fire the switch
early by `anchor_frac × crossfade_ms` so that payoff phase, not the switch,
lands on the trigger's timestamp. The planner calls `lead_ms()` at plan time
(services/trigger_engine._plan_timeline) and shifts the plan entry's
fire_at_ms by the result.

Adding a new phased transition = appending one PhasedTransition below. The
`anchor_frac` must match the constant in the LedFX effect code that starts the
payoff phase (today they all key off particle_handoff.BLOOM_START /
PACMAN_MORPH_START = 0.45). Nothing else needs to change: any morph-step
effect switch whose (outgoing, incoming) types match an entry is scheduled
early automatically, on both the bus and the scene-override dispatch paths.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhasedTransition:
    name: str                   # for logs
    from_types: frozenset[str]  # outgoing LedFX effect types
    to_types: frozenset[str]    # incoming LedFX effect types
    anchor_frac: float          # payoff phase starts at this crossfade fraction


# 2D particle effects that share the particle_handoff choreography.
_PARTICLES = frozenset({"blackhole", "orbits", "fireworks"})
# squiggles shares the full choreography set: pacman two-phase morph,
# radial implode→segment-burst, and envoy-collision→radial-bloom.
# dancer joins it too: radial→dancer holds the body formation until the
# bloom; pacman→dancer rides the chomp wipe with a Neo drop-in.
# eye joins as well: eye→radial gathers the gaze to the radial's center
# for the bloom; radial→eye explodes the iris back out of the pinch;
# pacman→eye holds the infall until the maze has faded.
_PARTICLES_AND_SQUIGGLES = _PARTICLES | {"squiggles", "dancer", "eye"}

# Keep anchor fractions in sync with ledfx/effects/particle_handoff.py:
#   BLOOM_START = 0.45 (radial bloom / eruption burst)
#   PACMAN_MORPH_START = 0.45 (entities morph once the maze has faded)
TRANSITIONS: tuple[PhasedTransition, ...] = (
    PhasedTransition(
        "particles→radial (gather, then bloom)",
        _PARTICLES_AND_SQUIGGLES, frozenset({"radial"}), 0.45,
    ),
    PhasedTransition(
        "radial→particles (implode, then erupt)",
        frozenset({"radial"}), _PARTICLES_AND_SQUIGGLES, 0.45,
    ),
    PhasedTransition(
        "pacman→particles (maze fades, then entities morph)",
        frozenset({"pacman"}), _PARTICLES_AND_SQUIGGLES, 0.45,
    ),
    # dancer somersaults + fades over phase 1; the incoming particle
    # effect holds adoption until PACMAN_MORPH_START (same 0.45 hold the
    # siblings use for pacman) and the body-points burst lands on the beat
    PhasedTransition(
        "dancer→particles (somersault, then burst)",
        frozenset({"dancer"}), _PARTICLES | {"squiggles", "eye"}, 0.45,
    ),
    # the eye closes its lids over phase 1; the lids reopen at the bloom
    # revealing the dancer (who assembles from the iris at that moment)
    PhasedTransition(
        "eye→dancer (blink, then reveal)",
        frozenset({"eye"}), frozenset({"dancer"}), 0.45,
    ),
    # dancers run from the approaching chomp wipe; the maze reveal (the
    # wipe front crossing mid-panel) lands on the trigger
    PhasedTransition(
        "dancer→pacman (run away, then the wipe)",
        frozenset({"dancer"}), frozenset({"pacman"}), 0.45,
    ),
)

# Hard cap so a huge configured transition_time can't drag a trigger absurdly
# far ahead of its timestamp.
MAX_LEAD_MS = 5000


def find(from_type: str | None, to_type: str | None) -> PhasedTransition | None:
    """The registered phased transition for this switch pair, or None."""
    if not from_type or not to_type or from_type == to_type:
        return None
    for t in TRANSITIONS:
        if from_type in t.from_types and to_type in t.to_types:
            return t
    return None


def anchor_frac(from_type: str | None, to_type: str | None) -> float:
    """Crossfade fraction where the payoff phase starts; 0.0 = not phased."""
    t = find(from_type, to_type)
    return t.anchor_frac if t else 0.0


def lead_ms(from_type: str | None, to_type: str | None, crossfade_ms: int) -> int:
    """How many ms EARLY to fire this switch so its payoff phase lands on the
    planned time. 0 when the pair isn't phased or there is no crossfade."""
    if crossfade_ms <= 0:
        return 0
    return min(round(anchor_frac(from_type, to_type) * crossfade_ms), MAX_LEAD_MS)
