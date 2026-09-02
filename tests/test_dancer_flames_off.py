"""THE DANCER FLAMES CAN BE TURNED OFF — frame-level proofs on the real
vendored render pipeline (fx.headless dummy Matrix host at his
crystal-mapper's 72x37 shape, audio silenced, fake clock).

scripts/check_dancer_flames_off.py is the measured, printed twin and owns
the drive harness AND the pinned baseline ref; this file pins the
properties the change has to hold. The harness is IMPORTED from there,
never copied — two copies of a measurement drift apart and rebuild the
same fault in a new shape (tests/test_fish_camera.py's own lesson).

The four properties:

  1. THE POINT OF THE CHANGE: the loudest possible signal fires NOTHING
     at `burst_threshold = 1.0` — and the same drive against the PINNED
     pre-change module goes RED, so the defect that shipped cannot come
     back quietly.
  2. THE OTHER DIRECTION: at his live 0.7, with the same audio and the
     same seed, the branch is BYTE-IDENTICAL to that baseline — every
     rendered frame, every particle.
  3. ZERO MEANS ZERO, proven at the EMITTER: `burst_size = 0` seeds no
     spray, draws no stunt particle and adds no vortex. The baseline
     leaks here (a burst seeds its spray `"acc": 1.0` — "first puff now"
     — so a rate of 0 still puffs once per spray).
  4. FLAMES OFF: at threshold 1.0 AND size 0, no flame particle exists at
     any point of the whole arc.

WHY BOTH KNOBS. Four flame sources exist and the threshold gates only
two of them (beat bursts, the ember trickle); the flourish payoff burst
and the six stunt/impact moments are ungated, so `burst_size = 0` is the
load-bearing half of "off". The ember trickle is the mirror case: it is
a time accumulator `burst_size` never scales, so only the threshold
silences it. Neither knob alone is "off"; together they are.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx.effects import dancer_flames  # noqa: E402


def _check_module():
    """The measured twin, loaded as a module: one harness, one pinned
    baseline ref, one definition of the drive."""
    path = REPO / "scripts" / "check_dancer_flames_off.py"
    spec = importlib.util.spec_from_file_location("_dancer_flames_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHK = _check_module()


@pytest.fixture(scope="module")
def baseline():
    """The PINNED pre-change dancer.py, registered beside the current one."""
    try:
        return CHK.load_baseline()
    except Exception as exc:                            # noqa: BLE001
        # A stated skip for a genuinely unavailable input (offline, a
        # shallow clone) names a missing input; it never retires the proof
        # because the code changed underneath it — load_baseline() asserts
        # the pin still carries the defect and not the fix, and FAILS if not.
        pytest.skip(f"cannot read the pinned baseline out of git: {exc}")


def _drive(tmp_path, tag, **kw):
    return asyncio.run(CHK.drive(str(tmp_path), tag, **kw))


# ── 1. the point of the change ─────────────────────────────────────────

def test_threshold_one_fires_nothing_however_loud(tmp_path):
    """The loudest signal there is — a melbank power saturated at the clip
    audio.py already applies — must not open the burst/ember gate at
    `burst_threshold = 1.0`.

    The gate is observed through the state it ALONE sets, never through a
    second copy of its logic: `_burst_window` is assigned 0.45 only inside
    `if kick and over`, and `_ember_acc` grows only inside
    `if over and not burst`.
    """
    run = _drive(
        tmp_path, "thr1", threshold=1.0, burst_size=CHK.HIS_BURST_SIZE,
    )
    assert run.impulse_max == pytest.approx(1.0), (
        "the drive is not actually saturating the signal, so this proves "
        f"nothing: impulse only reached {run.impulse_max}"
    )
    assert run.gate_open_frames == 0
    # NOT `sprays == 0`: a FLOURISH payoff burst is ungated by the
    # threshold and still seeds one, which is the whole reason burst_size
    # is the other half of "off" — see test_neither_knob_alone_is_silence.


def test_the_pinned_baseline_goes_red_on_the_same_drive(tmp_path, baseline):
    """RED-WHEN-LYING: the identical drive against the pre-change module
    must show the gate OPEN at threshold 1.0. A proof bar that cannot fail
    on the defect it was written for is decoration."""
    run = _drive(
        tmp_path, "thr1_base", effect_type=baseline, threshold=1.0,
        burst_size=CHK.HIS_BURST_SIZE,
    )
    assert run.gate_open_frames > 0, (
        "the pinned baseline did not reproduce the shipped defect — the "
        "pin has drifted, or the drive stopped saturating the signal"
    )
    assert run.emitted > 0


def test_the_mechanism_is_saturation_meeting_a_greater_or_equal():
    """Re-verified, not taken on trust: the impulse never EXCEEDS 1.0 — it
    REACHES it exactly, because audio.py clips the melbank power to exactly
    1.0 before the filter. That is why a clamp alone could not have fixed
    this and the `thr < 1.0` guard is what carries it."""
    from fx.effects.math import ExpFilter

    filt = ExpFilter(alpha_decay=0.06, alpha_rise=0.99)
    filt.update(0.0)
    values = [filt.update(1.0) for _ in range(60)]
    assert max(values) == 1.0
    assert not any(v > 1.0 for v in values)
    assert any(v >= 1.0 for v in values[:20]), (
        "saturation must reach exact 1.0 quickly — this is the shipped "
        "defect's whole mechanism"
    )


# ── 2. the other direction ─────────────────────────────────────────────

def test_his_live_threshold_is_byte_identical_to_the_baseline(
    tmp_path, baseline
):
    """0.7 with the same audio and the same seed: every rendered frame
    identical, every particle identical, the gate opening on exactly the
    same frames. Asserted on the real pipeline, not claimed."""
    old = _drive(
        tmp_path, "old07", effect_type=baseline,
        threshold=CHK.HIS_THRESHOLD, burst_size=CHK.HIS_BURST_SIZE,
        keep_frames=True,
    )
    new = _drive(
        tmp_path, "new07", threshold=CHK.HIS_THRESHOLD,
        burst_size=CHK.HIS_BURST_SIZE, keep_frames=True,
    )
    assert len(new.frames) == len(old.frames) > 0
    assert new.emitted == old.emitted > 0
    assert new.gate_open_frames == old.gate_open_frames > 0
    assert new.stunts == old.stunts > 0
    assert new.sprays == old.sprays > 0
    for i, (a, b) in enumerate(zip(old.frames, new.frames)):
        assert np.array_equal(a, b), f"frame {i} differs at threshold 0.7"


# ── 3. zero means zero ─────────────────────────────────────────────────

def test_the_emitter_draws_nothing_for_a_count_of_zero():
    """No inner minimum raises 0 to 1: both emitters return before any
    particle AND before the vortices that ride along with a plume."""
    field = dancer_flames.FlameField(np.random.default_rng(1))
    field.emit(10.0, 10.0, 0, 0.8, 30.0)
    assert (field.n, field.n_w) == (0, 0)
    field.emit_points(
        np.array([1.0, 2.0]), np.array([1.0, 2.0]), 1.5, 1.5, 0, 0.8, 30.0
    )
    assert (field.n, field.n_w) == (0, 0)
    # and it still draws for a real count, so the guard is not just "off"
    field.emit(10.0, 10.0, 7, 0.8, 30.0)
    assert field.n == 7


def test_burst_size_zero_seeds_no_spray_and_no_stunt_particle(tmp_path):
    """Gate WIDE OPEN (threshold 0.0) so every burst path is exercised,
    at `burst_size = 0`: no spray is seeded and the six ungated stunt
    moments draw nothing."""
    run = _drive(tmp_path, "size0", threshold=0.0, burst_size=0)
    assert run.stunts > 0, "the arc never reached a stunt moment"
    assert run.stunt_particles == 0
    assert run.sprays == 0


def test_the_pinned_baseline_leaks_a_particle_per_spray(tmp_path, baseline):
    """RED-WHEN-LYING for the zero path: the pre-change module seeds sprays
    at `burst_size = 0` and each one puffs once, because a spray is seeded
    `"acc": 1.0` and `int(1.0)` is 1 however small the rate.

    Driven by assigning the attribute the emission actually reads — the
    baseline's own schema (`Range(min=3)`) is what this change widened, so
    it cannot validate a 0.
    """
    old = _drive(
        tmp_path, "size0_base", effect_type=baseline, threshold=0.0,
        burst_size=3, force_burst_size=0,
    )
    new = _drive(tmp_path, "size0_cmp", threshold=0.0, burst_size=0)
    assert old.sprays > 0
    assert old.emitted > new.emitted, (
        "the baseline did not reproduce the zero leak — this proof would "
        "pass against the very defect it was written for"
    )


def test_the_schema_accepts_zero_and_still_refuses_out_of_range():
    """The range was widened at the bottom only."""
    from fx.effects import dancer as FX
    import voluptuous as vol

    schema = FX.Dancer2d.schema()
    assert schema({"burst_size": 0})["burst_size"] == 0
    assert schema({"burst_size": 60})["burst_size"] == 60
    with pytest.raises(vol.Invalid):
        schema({"burst_size": -1})
    with pytest.raises(vol.Invalid):
        schema({"burst_size": 61})


def test_the_param_registry_agrees_with_the_schema():
    """`config/effect_params.json` is the SECOND definition of this range —
    the documented defined-twice trap. A value the effect accepts and the
    registry refuses can never be authored."""
    import json

    reg = json.loads((REPO / "config" / "effect_params.json").read_text())
    entry = reg["effects"]["dancer"]["params"]["burst_size"]
    assert entry["min"] == 0
    assert entry["max"] == 60


# ── 4. flames off ──────────────────────────────────────────────────────

def test_both_knobs_together_are_silence(tmp_path):
    """His deploy state. No flame particle exists at any point of the whole
    arc — ordinary dancing, charge, lull, drop and back."""
    run = _drive(tmp_path, "off", threshold=1.0, burst_size=0)
    assert run.emitted == 0
    assert run.max_alive == 0
    assert run.gate_open_frames == 0
    assert run.sprays == 0
    assert run.stunt_particles == 0
    assert run.stunts > 0, (
        "the arc never reached a stunt moment, so silence here proves "
        "nothing about the ungated sources"
    )


def test_neither_knob_alone_is_silence(tmp_path):
    """The finding that makes the restore recipe two values, not one:
    the threshold alone leaves the ungated bursts and the stunts burning,
    and the size alone leaves the ember trickle."""
    thr_only = _drive(
        tmp_path, "thronly", threshold=1.0, burst_size=CHK.HIS_BURST_SIZE,
    )
    size_only = _drive(tmp_path, "sizeonly", threshold=0.0, burst_size=0)
    assert thr_only.emitted > 0
    assert size_only.emitted > 0
