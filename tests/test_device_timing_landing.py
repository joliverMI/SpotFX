"""THE PROOF BAR FOR PER-DEVICE TIMING EQUALIZATION (owner ask 2026-08-28:
"Different devices seem to have different network and physical latencies...
add an ability to tune the per device settings so that they are timed
equally").

A store that round-trips an integer proves the JSON survived a save. It
proves nothing about whether one fixture's light now lands before another's
— which is the entire claim the device page makes to him. So this measures
that, on the real render pipeline, the way tests/test_av_sync_lead_landing.py
measures the room lead: it watches WHEN EACH DEVICE'S LIGHT ACTUALLY
CHANGES, and asks whether the gap between the two moved by exactly the
amount authored.

The instrument: two dummy devices with their own virtuals in ONE real
FxHost, the vendored singleColor effect on each, stepped frame by frame
through fx.headless's real assemble/flush path. Every frame that reaches a
transport is recorded AT THE TRANSPORT — the `flush(data)` call itself, the
last thing before the wire on every device type — with the timestamp
fx.device_timing's own clock read when it was released. A "light edge" is
the first flushed frame whose pixels are lit.

NEGATIVE CONTROL, and the byte-identity hold: all-offsets-equal (including
the shipped all-zero default) must produce pacing byte-identical to a run
with the timing store never touched at all. Nobody's room may change
because this feature shipped. That is asserted against the recorded flush
log frame for frame, not asserted in a docstring.

VERIFIED RED: with the delay branch bypassed (_flush_timed forced down its
own immediate path), the offset tests below fail — the harness cannot pass
on a broken seam. `test_the_harness_fails_when_the_delay_seam_is_bypassed`
re-creates that world and proves the instrument goes red on it, because a
proof bar that cannot fail on the defect it was written for is decoration.
"""
from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

from fx import device_timing, headless
from fx.host import FxHost

D1, D2 = "timing-dev-a", "timing-dev-b"
PIXELS = 8
FRAME_HZ = 60.0
FRAME_MS = 1000.0 / FRAME_HZ
EDGE_FRAME = 60          # the frame on which both effects are lit
TOTAL_FRAMES = 240


def _write_two_device_config(config_dir, tmp_path):
    """One fx config with two dummy devices, each with its own span virtual
    — the same shape headless.write_headless_config writes for one."""
    import os
    os.makedirs(config_dir, exist_ok=True)

    def entry(did):
        return (
            {"id": did, "type": "dummy",
             "config": {"name": did, "pixel_count": PIXELS}},
            {"id": did, "is_device": did, "auto_generated": False,
             "config": {"name": did, "mapping": "span", "rows": 1},
             "segments": [[did, 0, PIXELS - 1, False]]},
        )

    d1, v1 = entry(D1)
    d2, v2 = entry(D2)
    from fx.consts import CONFIGURATION_VERSION
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": [d1, d2], "virtuals": [v1, v2]}, fh)


class _FlushLog:
    """Records every frame that reaches a device's transport, at the
    transport. Wraps the real DummyDevice.flush — the abstract method every
    vendored driver implements and the ONE thing _flush_timed releases to."""

    def __init__(self, host, clock):
        self.rows: list[tuple[str, float, bool]] = []   # (device, t_ms, lit)
        self._clock = clock
        for device in host.devices.values():
            self._wrap(device)

    def _wrap(self, device):
        rows, clock = self.rows, self._clock
        real = device.flush

        def flush(data):
            rows.append((device.id, clock.now * 1000.0,
                         bool(np.asarray(data).max() > 0)))
            return real(data)

        device.flush = flush

    def edge_ms(self, device_id):
        return next((t for did, t, lit in self.rows if did == device_id and lit),
                    None)

    def counts(self):
        out: dict[str, int] = {}
        for did, _t, _lit in self.rows:
            out[did] = out.get(did, 0) + 1
        return out


class _Clock:
    """One clock for both the effect layer and the flush deadline, so 'song
    time' and 'when the transport released it' sit on one axis."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, dt):
        self.now += dt


async def _run(tmp_path, offsets, *, install: bool = True):
    """Render TOTAL_FRAMES on both virtuals, lighting both at EDGE_FRAME.
    `offsets` is his authored per-device map (ms, negative = earlier);
    install=False leaves fx.device_timing completely untouched — the
    'before this feature existed' control."""
    config_dir = str(tmp_path / f"fx-{abs(hash(json.dumps(offsets, sort_keys=True))) % 10**8}-{int(install)}")
    _write_two_device_config(config_dir, tmp_path)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    clock = _Clock()
    device_timing.set_clock(clock)
    if install:
        device_timing.apply_offsets(offsets)
    log = _FlushLog(host, clock)
    try:
        with headless.fake_clock() as effect_clock:
            effects = {}
            for did in (D1, D2):
                virtual = host.virtuals.get(did)
                effects[did] = headless.attach_effect(
                    host, virtual, "singleColor",
                    {"color": "#ffffff", "brightness": 0.0})
            for frame in range(TOTAL_FRAMES):
                if frame == EDGE_FRAME:
                    for effect in effects.values():
                        effect.update_config({"brightness": 1.0})
                effect_clock.advance(1.0 / FRAME_HZ)
                clock.advance(1.0 / FRAME_HZ)
                for did in (D1, D2):
                    virtual = host.virtuals.get(did)
                    assembled = virtual.assemble_frame()
                    if assembled is not None:
                        virtual.flush(assembled)
    finally:
        await host.shutdown()
        device_timing.set_clock(None)
        device_timing.clear()
    return log


def _edges(tmp_path, offsets, **kw):
    log = asyncio.run(_run(tmp_path, offsets, **kw))
    e1, e2 = log.edge_ms(D1), log.edge_ms(D2)
    assert e1 is not None and e2 is not None, "a device's light never lit"
    return e1, e2, log


# ── the negative control: nothing about his room changes ────────────────────

def test_all_zero_offsets_are_byte_identical_to_the_feature_not_existing(tmp_path):
    """THE HOLD. Every device at the shipped default must flush exactly the
    frames, in exactly the order, at exactly the times a run that never
    touched fx.device_timing at all does."""
    untouched = asyncio.run(_run(tmp_path, {}, install=False))
    defaulted = asyncio.run(_run(tmp_path, {D1: 0, D2: 0}, install=True))
    assert defaulted.rows == untouched.rows


def test_equal_nonzero_offsets_are_also_byte_identical(tmp_path):
    """Only DIFFERENCES are meaningful: shifting the whole room by the same
    amount is not a shift at all, because the anchoring minimum moves with
    it. -250/-250 must pace exactly like 0/0."""
    baseline = asyncio.run(_run(tmp_path, {D1: 0, D2: 0}))
    shifted = asyncio.run(_run(tmp_path, {D1: -250, D2: -250}))
    assert shifted.rows == baseline.rows


def test_equal_offsets_land_both_lights_simultaneously(tmp_path):
    e1, e2, _ = _edges(tmp_path, {D1: 0, D2: 0})
    assert e1 == pytest.approx(e2, abs=FRAME_MS / 2)


# ── the measurement: his sign law at the transport ──────────────────────────

@pytest.mark.parametrize("offset_ms", [-100, -300])
def test_a_negative_offset_fires_that_device_earlier_by_exactly_that_much(
        tmp_path, offset_ms):
    """His convention, measured: negative = EARLIER. Device A is authored
    early, so device B is the one that waits — and the GAP between the two
    edges equals the authored magnitude."""
    e1, e2, _ = _edges(tmp_path, {D1: offset_ms, D2: 0})
    assert e1 < e2, "the device authored EARLIER did not fire first"
    assert (e2 - e1) == pytest.approx(abs(offset_ms), abs=FRAME_MS)


@pytest.mark.parametrize("offset_ms", [100, 300])
def test_a_positive_offset_fires_that_device_later_by_exactly_that_much(
        tmp_path, offset_ms):
    """The other direction on the same instrument — a sign law proven one
    way is half a proof."""
    e1, e2, _ = _edges(tmp_path, {D1: offset_ms, D2: 0})
    assert e1 > e2, "the device authored LATER did not fire second"
    assert (e1 - e2) == pytest.approx(offset_ms, abs=FRAME_MS)


def test_the_earliest_device_is_never_delayed_so_the_room_never_moves(tmp_path):
    """A fixture can only be made to WAIT. Authoring one device early must
    leave THAT device's edge exactly where an unequalized room put it, and
    move the others back — never the reverse, which would need to send a
    frame before it was drawn."""
    base_1, base_2, _ = _edges(tmp_path, {D1: 0, D2: 0})
    early_1, early_2, _ = _edges(tmp_path, {D1: -200, D2: 0})
    assert early_1 == pytest.approx(base_1, abs=FRAME_MS / 2)
    assert (early_2 - base_2) == pytest.approx(200, abs=FRAME_MS)


def test_a_delayed_device_still_flushes_every_frame_it_was_given(tmp_path):
    """Held back, not dropped: the delayed device's transport sees the same
    number of frames minus only the ones still in flight when the run ended
    (a 200 ms delay at 60 fps = 12 frames)."""
    log = asyncio.run(_run(tmp_path, {D1: 0, D2: 200}))
    counts = log.counts()
    in_flight = round(200 / FRAME_MS)
    assert counts[D1] == TOTAL_FRAMES
    assert counts[D2] == pytest.approx(TOTAL_FRAMES - in_flight, abs=1)


def test_a_held_frame_is_a_copy_not_a_live_reference(tmp_path):
    """assemble_frame() can hand back the device's own pixel buffer, which
    the next frame overwrites in place. If a held frame were a reference,
    the delayed device would show the CURRENT frame at the delayed time —
    i.e. no delay at all at the light, while the log still looked right.
    The edge measurement above would catch it; this names it."""
    _e1, _e2, log = _edges(tmp_path, {D1: 0, D2: 200})
    lit_before_edge = [t for did, t, lit in log.rows
                       if did == D2 and lit and t < log.edge_ms(D1) - 1e-9]
    assert lit_before_edge == []


# ── the instrument must be able to fail ─────────────────────────────────────

def test_the_harness_fails_when_the_delay_seam_is_bypassed(tmp_path, monkeypatch):
    """VERIFIED RED. Force every device down _flush_timed's immediate path
    (the pre-feature world) and the measurement above must break — if it
    still passed, it would be measuring nothing."""
    from fx.devices import Device

    def immediate(self, frame):
        self._emit_frame(frame)

    monkeypatch.setattr(Device, "_flush_timed", immediate)
    e1, e2, _ = _edges(tmp_path, {D1: -200, D2: 0})
    assert (e2 - e1) == pytest.approx(0, abs=FRAME_MS / 2), (
        "with the seam bypassed the two edges must coincide — if they do "
        "not, this test is not bypassing what it thinks it is")
