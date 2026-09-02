#!/usr/bin/env python3
"""THE DANCER FLAMES, MEASURED — the printed twin of
tests/test_dancer_flames_off.py.

His ask was to be able to turn the dancers' flames OFF. Two knobs were
supposed to do it and neither did:

  * `burst_threshold = 1.0` reads as "no burst can ever be loud enough",
    and it FIRED. `self.impulse` is an ExpFilter over a melbank power that
    audio.py already clips to EXACTLY 1.0 (`get_freq_power` ->
    `np.minimum(freq_power_raw, 1)`), so a sustained loud passage drives
    the filter to exactly 1.0 within ~9 audio frames — and the gate was
    `self.impulse >= thr`. Not an overshoot past 1.0: a saturation meeting
    a `>=`. The fix is a clamp (defence in depth, a no-op today) plus an
    explicit `thr < 1.0`, deliberately NOT a switch to strict `>` — see
    the comment at the gate in fx/effects/dancer.py for why.
  * `burst_size` could not reach 0 (schema `Range(min=3)`), and even at 0
    it would still have drawn: a burst seeds its spray `"acc": 1.0`
    ("first puff now"), so a rate of 0 emits one particle per spray per
    burst. Schema min is now 0 and the zero count returns before any
    emission.

FOUR flame sources exist, and the threshold gates only two of them —
re-verified here, not taken on trust:

  1. beat BURSTS        gated by `over`
  2. the EMBER trickle  gated by `over`
  3. FLOURISH payoff bursts  UNGATED (dancer.py `_flourish_j`)
  4. the six STUNT/impact moments  UNGATED (`_impact_flames`)

So the threshold alone can never silence the flames however it is set;
`burst_size = 0` is the load-bearing half of "off".

Offline only: fx.headless dummy Matrix host at his crystal-mapper's
72x37 shape, audio silenced, a fake clock, and a synthetic audio object
feeding the REAL `audio_data_updated` -> REAL ExpFilter -> REAL gate.
Nothing here reads or writes live storage.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import headless  # noqa: E402
from fx.effects import dancer_flames  # noqa: E402

# ── the pinned pre-change dancer.py ────────────────────────────────────
# PINNED, never a moving ref (`master` retired the fish camera proof into
# a permanent green skip once — see tests/test_fish_camera.py::_load_master
# for that history). This is the commit this PR branched from; the loader
# asserts it still carries the defect and does NOT carry the fix, so a
# drifted pin FAILS LOUDLY instead of quietly proving nothing.
BASELINE_REF = "765af84ebf093cabbdee34cb2aedad22b2a75e4e"

ROWS, COLS = 37, 72
DT = 1.0 / 60.0
BPM = 128.0

# his live Dancers entry's flame knobs, at the state that shipped
HIS_THRESHOLD = 0.7
HIS_BURST_SIZE = 30
# quiet enough that the gate never opens at his 0.7, so a run can isolate
# the flame sources the threshold does not gate
QUIET = 0.05


class FakeAudio:
    """The surface `Dancer.audio_data_updated` actually reads: one power
    func (whichever `frequency_range` selects) and the beat oscillator.
    Everything downstream of it — the ExpFilter, the impulse assignment,
    the gate — is the real production code."""

    def __init__(self) -> None:
        self.power = 0.0
        self.beat = 0.0

    def beat_power(self):
        return self.power

    def bass_power(self):
        return self.power

    def lows_power(self):
        return self.power

    def mids_power(self):
        return self.power

    def high_power(self):
        return self.power

    def beat_oscillator(self):
        return self.beat


def load_baseline(name: str = "dancer_baseline_probe") -> str:
    """Register the PINNED pre-change dancer.py beside the current one.

    An Effect subclass registers under its module's last name segment, so
    importing the baseline source under a different module name puts it in
    the registry next to `dancer` and `create(type=...)` reaches it.
    """
    if name in sys.modules:
        return name
    src = subprocess.run(
        ["git", "show", f"{BASELINE_REF}:fx/effects/dancer.py"],
        cwd=REPO, capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    assert "over = self.impulse >= thr" in src, (
        f"the pinned baseline {BASELINE_REF} does not carry the uncapped "
        "gate this proof exists to go red against — BASELINE_REF has drifted"
    )
    assert "sig = float(min(max(self.impulse" not in src, (
        f"the pinned baseline {BASELINE_REF} already carries the fix — "
        "BASELINE_REF is wrong; fail loudly rather than prove nothing"
    )
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


# ── the drive ──────────────────────────────────────────────────────────

# the whole arc, so bursts, embers, flourishes AND the six stunt moments
# all get their chance: ordinary dancing plus every choreography phase
SCRIPT = (
    ("none", 4.0),
    ("charge", 3.0),
    ("lull", 2.0),
    ("drop", 4.0),
    ("none", 4.0),
)


class Run:
    """One recorded drive of the real effect on the real render path."""

    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.emitted = 0          # particles that reached the FlameField
        self.gate_open_frames = 0  # frames the `over` gate was open
        self.max_alive = 0
        self.impulse_max = 0.0
        self.stunts = 0            # _impact_flames invocations (UNGATED)
        self.stunt_particles = 0
        self.sprays = 0            # sprays seeded by a burst (the zero leak)


async def drive(
    tmp: str,
    tag: str,
    *,
    effect_type: str = "dancer",
    threshold: float,
    burst_size: int,
    power: float = 1.0,
    seed: int = 7,
    force_burst_size: int | None = None,
    keep_frames: bool = False,
) -> Run:
    """Loudest-possible (or given) audio, a steady beat, the whole arc.

    `force_burst_size` assigns the attribute the emission actually reads,
    after every config write — the only way to drive the PINNED baseline
    at a size its own schema (`Range(min=3)`) refuses to validate.
    """
    host = await headless.start_headless_host(
        os.path.join(tmp, tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag,
    )
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    # DETERMINISM, and it has to be arranged BEFORE construction: the effect
    # picks its opening dance move and hands its FlameField a generator
    # inside __init__/config_updated, so reseeding `effect._rng` afterwards
    # is already too late — two runs would dance differently. Seeding the
    # factory instead gives the effect, its flames and its choreography one
    # generator from their very first draw. `np.random.seed` covers
    # fx/transitions.py, which builds its dissolve array off the GLOBAL RNG.
    np.random.seed(seed)
    real_default_rng = np.random.default_rng
    np.random.default_rng = lambda *a, **k: real_default_rng(seed)
    try:
        effect = headless.attach_effect(
            host, virtual, effect_type,
            {"burst_threshold": threshold, "burst_size": burst_size},
        )
    finally:
        np.random.default_rng = real_default_rng
    host.audio._volume = 1.0          # never below min_volume -> never suppressed
    audio = FakeAudio()
    audio.power = power

    run = Run()
    # observe the emitter itself: every particle that is actually born,
    # counted where it is born, not inferred from the arithmetic above it
    real_emit = effect.flames.emit
    real_emit_points = effect.flames.emit_points

    def emit(*a, **k):
        before = effect.flames.n
        real_emit(*a, **k)
        run.emitted += effect.flames.n - before

    def emit_points(*a, **k):
        before = effect.flames.n
        real_emit_points(*a, **k)
        run.emitted += effect.flames.n - before

    effect.flames.emit = emit
    effect.flames.emit_points = emit_points

    # the six STUNT/impact moments are UNGATED by burst_threshold — count
    # them separately so "zero means zero" can be claimed of the sources
    # burst_size actually feeds, not of the arc in aggregate
    real_impact = effect._impact_flames

    def impact(d, mag):
        before = effect.flames.n
        run.stunts += 1
        real_impact(d, mag)
        run.stunt_particles += effect.flames.n - before

    effect._impact_flames = impact

    t = 0.0
    if force_burst_size is not None:
        effect.burst_size = force_burst_size
    for phase, seconds in SCRIPT:
        n = int(seconds / DT)
        for i in range(1, n + 1):
            effect.update_config(
                {"phase": phase, "phase_progress": i / n}
            )
            if force_burst_size is not None:
                # config_updated re-reads burst_size from config
                effect.burst_size = force_burst_size
            t += DT
            audio.beat = (t * BPM / 60.0) % 1.0
            effect.audio_data_updated(audio)
            clock.advance(DT)
            before_sprays = len(effect._sprays)
            frame = virtual.assemble_frame()
            run.sprays += max(0, len(effect._sprays) - before_sprays)
            if frame is not None:
                virtual.flush(frame)
                if keep_frames:
                    run.frames.append(np.array(frame, copy=True))
            # THE GATE'S OWN STATE, not a second copy of its logic:
            # `_burst_window` is set to 0.45 only by `kick and over`, and
            # `_ember_acc` grows only inside `if over and not burst`.
            if effect._burst_window > 0.0 or effect._ember_acc > 0.0:
                run.gate_open_frames += 1
            run.max_alive = max(run.max_alive, effect.flames.n)
            run.impulse_max = max(run.impulse_max, effect.impulse)

    cm.__exit__(None, None, None)
    await host.shutdown()
    return run


# ── the report ─────────────────────────────────────────────────────────

def main() -> int:
    tmp = tempfile.mkdtemp()
    base = load_baseline()
    ok = True

    print("=" * 72)
    print("1. THRESHOLD 1.0 MEANS NEVER — loudest possible signal")
    print("=" * 72)
    old = asyncio.run(drive(
        tmp, "old_thr1", effect_type=base,
        threshold=1.0, burst_size=HIS_BURST_SIZE,
    ))
    new = asyncio.run(drive(
        tmp, "new_thr1", threshold=1.0, burst_size=HIS_BURST_SIZE,
    ))
    print(f"  impulse reached           : {new.impulse_max!r} "
          f"(saturating melbank power, clipped upstream to exactly 1.0)")
    print(f"  BASELINE {BASELINE_REF[:8]}  gate-open frames: "
          f"{old.gate_open_frames}")
    print(f"  THIS BRANCH             gate-open frames: "
          f"{new.gate_open_frames}")
    if old.gate_open_frames <= 0:
        print("  !! the baseline did not reproduce the defect")
        ok = False
    if new.gate_open_frames != 0:
        print("  !! the gate still opens at threshold 1.0")
        ok = False
    print(f"  -> {'FIXED' if ok else 'FAILED'}: a threshold of 1.0 now "
          "closes the beat-burst and ember gate for any signal")

    print()
    print("=" * 72)
    print("2. THE OTHER DIRECTION — 0.7 is bit-identical to the baseline")
    print("=" * 72)
    old7 = asyncio.run(drive(
        tmp, "old_thr07", effect_type=base, threshold=HIS_THRESHOLD,
        burst_size=HIS_BURST_SIZE, keep_frames=True,
    ))
    new7 = asyncio.run(drive(
        tmp, "new_thr07", threshold=HIS_THRESHOLD,
        burst_size=HIS_BURST_SIZE, keep_frames=True,
    ))
    same_frames = (
        len(old7.frames) == len(new7.frames)
        and all(
            np.array_equal(a, b) for a, b in zip(old7.frames, new7.frames)
        )
    )
    print(f"  particles emitted   baseline {old7.emitted:5d}   "
          f"branch {new7.emitted:5d}")
    print(f"  gate-open frames    baseline {old7.gate_open_frames:5d}   "
          f"branch {new7.gate_open_frames:5d}")
    print(f"  rendered frames     {len(new7.frames)} compared, "
          f"byte-identical: {same_frames}")
    if not (
        same_frames
        and old7.emitted == new7.emitted
        and old7.gate_open_frames == new7.gate_open_frames
    ):
        print("  !! 0.7 behaviour changed")
        ok = False

    print()
    print("=" * 72)
    print("3. ZERO MEANS ZERO — proven AT THE EMITTER")
    print("=" * 72)
    field = dancer_flames.FlameField(np.random.default_rng(1))
    field.emit(10.0, 10.0, 0, 0.8, 30.0)
    field.emit_points(
        np.array([1.0, 2.0]), np.array([1.0, 2.0]), 1.5, 1.5, 0, 0.8, 30.0
    )
    print(f"  FlameField.emit(count=0)        -> particles {field.n}, "
          f"vortices {field.n_w}")
    if field.n or field.n_w:
        print("  !! the emitter draws for a count of 0")
        ok = False

    print("  ...and on the real pipeline, gate WIDE OPEN so every burst")
    print("  path is exercised, at burst_size 0:")
    old0 = asyncio.run(drive(
        tmp, "old_size0", effect_type=base, threshold=0.0,
        burst_size=3, force_burst_size=0,
    ))
    new0 = asyncio.run(drive(tmp, "new_size0", threshold=0.0, burst_size=0))
    print(f"  BASELINE {BASELINE_REF[:8]}  sprays seeded {old0.sprays:4d}  "
          f"particles {old0.emitted:4d}")
    print(f"  THIS BRANCH             sprays seeded {new0.sprays:4d}  "
          f"particles {new0.emitted:4d}")
    print(f"  stunt moments hit: {new0.stunts} -> "
          f"{new0.stunt_particles} particles (the six UNGATED impacts obey "
          "zero)")
    if old0.sprays <= 0 or old0.emitted <= new0.emitted:
        print("  !! the baseline did not reproduce the zero leak")
        ok = False
    if new0.sprays != 0 or new0.stunt_particles != 0:
        print("  !! a burst path still draws at burst_size 0")
        ok = False
    if new0.stunts <= 0:
        print("  !! no stunt moment fired — the arc is not exercising them")
        ok = False

    print()
    print("=" * 72)
    print("3b. WHAT IS LEFT IS THE EMBER TRICKLE — stated, not fixed")
    print("=" * 72)
    print(f"  the {new0.emitted} particles above are ALL embers: no spray")
    print("  was seeded, no stunt drew, and the outline burst is a burst")
    print("  path. `embers` is a time accumulator that burst_size never")
    print("  scales — only the threshold silences it, which is why 'flames")
    print("  off' is BOTH knobs. Section 4 is that state.")

    print()
    print("=" * 72)
    print("4. FLAMES OFF — his deploy state: threshold 1.0 AND size 0")
    print("=" * 72)
    off = asyncio.run(drive(tmp, "off", threshold=1.0, burst_size=0))
    print(f"  particles born: {off.emitted}   gate-open frames: "
          f"{off.gate_open_frames}   max alive: {off.max_alive}")
    if off.emitted or off.gate_open_frames or off.max_alive:
        print("  !! the room still burns")
        ok = False
    else:
        print("  -> no flame particle exists at any point in the whole arc")

    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    status = 1
    try:
        status = main()
    except Exception:                                   # noqa: BLE001
        import traceback
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        # fx's TemporalEffect spawns non-daemon threads this frame-stepped
        # harness never joins, and FxHost.stop() refuses to stop the SpotFX
        # process — a plain return hangs forever. See AGENTS.md.
        os._exit(status)
