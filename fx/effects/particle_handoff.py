"""Cross-instance particle handoff for the Blackhole / Orbits matrix effects.

When a virtual switches between these effects (or recreates one of them),
the OUTGOING instance leaves a snapshot of its live particle state here,
keyed by virtual id, and the INCOMING instance adopts it on its first draw —
so the particles already on screen become part of the new effect instead of
vanishing.

Two delivery paths:
  * crossfade: the incoming effect reads the outgoing instance directly via
    ``virtual._transition_effect`` (still alive during the blend) — this
    registry is only the fallback;
  * no-transition switches / recreations: the outgoing ``deactivate()``
    stores a snapshot here before the instance is destroyed.

Snapshot format (built by each effect's ``_handoff_snapshot``)::

    {
      "src":    "blackhole" | "orbits",   # exporter kind
      "t":      timeit.default_timer(),
      "dims":   (r_width, r_height),      # render space, for validity check
      "px","py": float32 (n,)             # PIXEL-space particle positions
      "grad":   float32 (n,)              # gradient sample positions 0..1
      "bright": float32 (n,)              # brightness 0..1
      "trail":  float32 (H,W,3) | None    # trail history buffer
      "native": {...}                     # full effect-specific state for
                                          # same-type restore
    }

Positions travel in pixel space because the two effects' normalized spaces
differ (radius_scale / x_offset); each importer re-normalizes with its own
projection.
"""

from __future__ import annotations

import timeit

MAX_AGE_S = 2.0

# ── particle ⇄ radial choreography ("gather & bloom" / "suck in & erupt") ──
GATHER_FRAC = 0.6        # phase 1 / phase 2 split of the crossfade
BLOOM_START = 0.45       # eruption/bloom starts here — overlaps the gather
                         # tail so the explosion doesn't feel delayed
REVEAL_FEATHER = 0.18    # soft edge of the stretch boundary, in norm radius
REVEAL_FALLBACK_S = 0.5  # standalone bloom duration on the no-transition path
COLLAPSE_FALLBACK_S = 1.0  # collapse duration when transition counters die
SWIRL_TURNS = 0.75       # extra revolutions particles make while spiraling in
ERUPT_HOLD_MAX_S = 4.0   # wall-clock safety release for a held eruption
PACMAN_MORPH_START = 0.45  # pacman → particles: the maze (walls/dots) fades
                         # over [0, this); at this frac the entities morph
                         # into particles. SpotFX schedules the switch early
                         # so this lands on the trigger — keep in sync with
                         # SpotFX services/transition_phases.py
BURST_N = 12             # blobs in a blackhole eruption burst
SURPLUS_FLYOUT_MAX = 12  # max surplus blobs that fly out on a bh→orbits
                         # handoff; the rest fade out via the merged trail
# Empirical sign between the particle effects' screen-rotation convention and
# radial's twist × source-scroll apparent rotation. Flip to -1.0 if a live
# check shows the rotation reversing across the handoff.
RADIAL_SPIN_PARITY = 1.0

_store: dict[str, dict] = {}


def now() -> float:
    return timeit.default_timer()


def transition_progress(virtual) -> float | None:
    """Fraction 0..1 of a live crossfade on `virtual`, or None when there is
    no usable live transition (no sibling, or zero-length). Gating on the
    sibling's presence means stale counters are never consumed."""
    if virtual is None or getattr(virtual, "_transition_effect", None) is None:
        return None
    total = getattr(virtual, "transition_frame_total", 0)
    if not total or total <= 0:
        return None
    return min(getattr(virtual, "transition_frame_counter", 0) / total, 1.0)


def incoming_sibling(virtual, outgoing):
    """The incoming effect while `outgoing` is serving as the crossfade
    sibling on `virtual`, else None."""
    if (
        virtual is None
        or getattr(virtual, "_transition_effect", None) is not outgoing
    ):
        return None
    return getattr(virtual, "_active_effect", None)


def store(virtual_id: str, snapshot: dict | None) -> None:
    """Register the outgoing effect's snapshot for `virtual_id`."""
    if not virtual_id or not snapshot:
        return
    snapshot.setdefault("t", now())
    _store[virtual_id] = snapshot


def take(virtual_id: str, max_age: float = MAX_AGE_S) -> dict | None:
    """Pop and return a fresh snapshot for `virtual_id`, or None if absent
    or older than `max_age` seconds."""
    snap = _store.pop(virtual_id, None)
    if snap is None:
        return None
    if now() - snap.get("t", 0.0) > max_age:
        return None
    return snap


# ── charge/lull/drop orphan watchdog ─────────────────────────────────────────
# A charge or lull whose payoff never arrives (lost drop write, skipped
# track, no drop trigger) must never latch an effect forever. Every
# phase-capable effect calls phase_release_due() from its phase step and
# gracefully releases itself when it returns True.
PHASE_GRACE_S = 12.0     # release this long after the build completed
PHASE_HOLD_MAX_S = 60.0  # absolute charge/lull cap, build complete or not


def phase_release_due(phase, progress, t, done_t):
    """Charge/lull orphan check. `progress` is the SpotFX-ramped
    phase_progress, `t` seconds in phase, `done_t` the previously recorded
    completion time (None = not yet complete). A build counts as complete
    when the ramp peaked — or never moved at all (lost tween) for 3 s.
    Returns (release_now, new_done_t)."""
    if phase not in ("charge", "lull"):
        return False, None
    done = progress >= 0.99 or (progress <= 0.001 and t >= 3.0)
    if done and done_t is None:
        done_t = t
    due = (
        (done_t is not None and (t - done_t) > PHASE_GRACE_S)
        or t > PHASE_HOLD_MAX_S
    )
    return due, done_t
