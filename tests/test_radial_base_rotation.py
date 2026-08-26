"""radial's quiet BASE ROTATION floor (fx/VENDOR.md #21).

Fast, deterministic counterparts to scripts/check_radial_base_rotation.py:
the same properties, driven through the real vendored effect on a real
headless render pipeline under a fake clock. No hardware, no live storage.
"""
from __future__ import annotations

import asyncio
import tempfile

import numpy as np

from fx import headless

DT = 1.0 / 60.0
FRAMES = 120
SPIN = 0.55
BASE = 0.25


class _Impulse:
    def __init__(self, value: float):
        self.value = value

    def lows_power(self) -> float:
        return self.value


def _unwrapped(effect, before: float) -> float:
    d = effect.spin_total - before
    if d < -0.5:
        d += 1.0
    elif d > 0.5:
        d -= 1.0
    return d


def _run(virtual, effect, clock, impulse: float, frames: int = FRAMES):
    out: list[np.ndarray] = []
    total = 0.0
    data = _Impulse(impulse)
    for _ in range(frames):
        before = effect.spin_total
        effect.audio_data_updated(data)
        clock.advance(DT)
        frame = virtual.assemble_frame()
        if frame is not None:
            virtual.flush(frame)
            out.append(np.array(frame, copy=True))
        total += _unwrapped(effect, before)
    return out, total


def _attach(host, virtual, **overrides):
    cfg = {"spin": SPIN, "star": -0.5, "edges": 6, "twist": 0, "polygon": True}
    cfg.update(overrides)
    return headless.attach_effect(host, virtual, "radial", cfg)


async def _with_host(fn):
    with tempfile.TemporaryDirectory() as cfgdir:
        host = await headless.start_headless_host(
            cfgdir, pixel_count=512, rows=16, device_id="crystal-mapper")
        try:
            return fn(host, host.virtuals.get("crystal-mapper"))
        finally:
            await host.shutdown()


def _drive(host, virtual, impulse: float, **overrides):
    with headless.fake_clock() as clock:
        eff = _attach(host, virtual, **overrides)
        frames, rev = _run(virtual, eff, clock, impulse)
        spin_total = eff.spin_total
        eff.deactivate()
    return frames, rev, spin_total


def test_default_is_zero_and_declared_linear_in_rev_per_second():
    from fx.effects.radial import Radial2d

    import inspect

    cfg = Radial2d.CONFIG_SCHEMA({})
    assert cfg["base_rotation"] == 0.0
    # LINEAR: it must NOT be routed through nonlinear_log the way spin is
    line = next(
        ln for ln in inspect.getsource(Radial2d.config_updated).splitlines()
        if "self.base_rotation" in ln
    )
    assert "nonlinear_log" not in line, line
    assert "float(" in line, line


def test_base_zero_renders_byte_identical_to_the_key_being_absent():
    def body(host, virtual):
        absent, rev_absent, _ = _drive(host, virtual, 0.04)
        zero, rev_zero, _ = _drive(host, virtual, 0.04, base_rotation=0.0)
        assert len(absent) == FRAMES
        for a, b in zip(absent, zero):
            assert np.array_equal(a, b)
        assert rev_absent == rev_zero

    asyncio.run(_with_host(body))


def test_base_turns_at_the_declared_rate_with_zero_audio():
    def body(host, virtual):
        _, rev, spin_total = _drive(host, virtual, 0.0, base_rotation=BASE)
        assert abs(rev / (FRAMES * DT) - BASE) < 1e-6
        assert 0.0 <= spin_total < 1.0
        # and the same config without the base does not move at all
        _, rev0, _ = _drive(host, virtual, 0.0, base_rotation=0.0)
        assert rev0 == 0.0

    asyncio.run(_with_host(body))


def test_floor_never_adds_when_the_audio_drive_is_faster():
    loud = 0.30  # reactive ≈ 0.545 rev/s, well over BASE
    def body(host, virtual):
        no_base, rev_no_base, _ = _drive(
            host, virtual, loud, base_rotation=0.0)
        with_base, rev_base, _ = _drive(
            host, virtual, loud, base_rotation=BASE)
        assert rev_no_base / (FRAMES * DT) > BASE
        assert rev_base == rev_no_base
        for a, b in zip(no_base, with_base):
            assert np.array_equal(a, b)

    asyncio.run(_with_host(body))


def test_direction_follows_the_current_one_and_never_fights_it():
    def body(host, virtual):
        # a spin_sign/Flip write is a negative `spin`: the base must follow
        _, rev_neg, spin_total = _drive(
            host, virtual, 0.0, base_rotation=BASE, spin=-SPIN)
        assert rev_neg < 0
        assert abs(abs(rev_neg / (FRAMES * DT)) - BASE) < 1e-6
        assert 0.0 <= spin_total < 1.0
        # spin=0 falls through to twist's sign, then to clockwise
        _, rev_twist, _ = _drive(
            host, virtual, 0.0, base_rotation=BASE, spin=0.0, twist=-2.0)
        assert rev_twist < 0
        _, rev_cw, _ = _drive(
            host, virtual, 0.0, base_rotation=BASE, spin=0.0, twist=0.0)
        assert rev_cw > 0

    asyncio.run(_with_host(body))


def test_registry_declares_the_param_and_says_it_scales_unlike_speed():
    from fx import device_model

    meta = device_model.effect_params("radial")["base_rotation"]
    assert meta["default"] == 0.0
    assert meta["type"] == "numeric"
    assert meta["help_topic"] == "radial-base-rotation"
    note = meta["note"]
    assert "REVOLUTIONS PER SECOND" in note
    assert "LINEAR" in note
    assert "FLOOR, NOT A SUM" in note
