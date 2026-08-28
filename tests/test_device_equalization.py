"""PER-DEVICE MEASUREMENT -> PROPOSED EQUALIZATION.

His belief that the Hue lights are slower than the WLEDs is a HYPOTHESIS
this mode measures, not a fact encoded anywhere: nothing in the arithmetic
knows a device's type, and the ordering falls out of the numbers.

What is proven here:
  * the pattern can be narrowed to ONE device, and a narrowed run leaves
    every other virtual completely alone — not snapshotted, not written,
    not reverted, still playing the show;
  * a run records WHICH device it measured, so the log can be grouped;
  * the proposal takes the SLOWEST device as the reference, so every
    proposed offset is a WAIT (>= 0, his convention: positive = later) and
    nothing is ever asked to fire before the renderer drew it;
  * the offsets already in force are subtracted back out, so re-measuring
    after applying does not count the correction twice;
  * it NEVER writes — applying is his press, per device.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.services import device_equalization as eq
from spectra.services.av_sync_pattern import PatternDriver


def _rec(device_id, offset, ok=True, sigma=8.0, at="2026-08-28T20:00:00+0000"):
    return {"ok": ok, "device_id": device_id, "av_offset_ms": offset,
            "sigma_ms": sigma, "at_iso": at, "mode": "pattern"}


# ── the proposal ────────────────────────────────────────────────────────────

def test_one_device_alone_says_nothing_and_refuses_by_name():
    prop = eq.proposal([_rec("hue", 120.0)])
    assert not prop.applicable
    assert "at least two devices" in prop.reason
    assert prop.proposals == []


def test_the_slowest_device_is_the_reference_and_every_proposal_is_a_wait():
    """A fixture can only be made to WAIT. The device whose light arrives
    LATEST sets the pace at 0; each faster device is asked to hold back the
    difference — so no proposal is ever negative, because a negative one
    would be asking a light to fire before its frame was drawn."""
    prop = eq.proposal([_rec("hue", 120.0), _rec("wled", 40.0), _rec("strip", 95.0)])
    assert prop.applicable
    assert prop.reference_device_id == "hue"
    by_id = {p["device_id"]: p for p in prop.proposals}
    assert by_id["hue"]["proposed_timing_offset_ms"] == 0
    assert by_id["strip"]["proposed_timing_offset_ms"] == 25
    assert by_id["wled"]["proposed_timing_offset_ms"] == 80
    assert all(p["proposed_timing_offset_ms"] >= 0 for p in prop.proposals)
    assert prop.spread_ms == pytest.approx(80.0)


def test_the_type_of_a_device_never_enters_the_arithmetic():
    """His Hue-slower-than-WLED belief is measured, not assumed: the same
    numbers with the names swapped produce the mirrored answer."""
    a = eq.proposal([_rec("hue", 120.0), _rec("wled", 40.0)])
    b = eq.proposal([_rec("hue", 40.0), _rec("wled", 120.0)])
    assert a.reference_device_id == "hue"
    assert b.reference_device_id == "wled"


def test_the_offsets_already_applied_are_subtracted_back_out():
    """The flash pattern's writes leave through the SAME delayed device
    flush as everything else, so a device already held back 80 ms measures
    80 ms later. Counting that again would make every re-measure chase its
    own tail — after applying an equalization, re-measuring must propose
    keeping it, not doubling it."""
    # after applying the equalization above, wled is held 80 ms and now
    # measures level with hue
    prop = eq.proposal([_rec("hue", 120.0), _rec("wled", 120.0)],
                       offsets={"hue": 0, "wled": 80})
    by_id = {p["device_id"]: p for p in prop.proposals}
    assert by_id["wled"]["proposed_timing_offset_ms"] == 80
    assert by_id["wled"]["delta_ms"] == 0, "a settled room proposes no change"
    assert by_id["hue"]["proposed_timing_offset_ms"] == 0


def test_the_delay_is_taken_from_the_offsets_the_way_the_engine_takes_it():
    """`applied_delay = offset - min(offset)` — the same translation
    fx/device_timing.py makes, so an all-negative or all-positive authored
    set is read exactly as the lights see it."""
    assert eq.applied_delays_ms({"a": -100, "b": 0, "c": 150}) == {"a": 0, "b": 100, "c": 250}
    assert eq.applied_delays_ms({"a": 200, "b": 300}) == {"a": 0, "b": 100}
    assert eq.applied_delays_ms({}) == {}


def test_a_refused_run_contributes_nothing_rather_than_a_guess():
    prop = eq.proposal([_rec("hue", 120.0), _rec("wled", 40.0),
                        _rec("wled", 999.0, ok=False)])
    by_id = {p["device_id"]: p for p in prop.proposals}
    assert by_id["wled"]["measured_av_offset_ms"] == 40.0


def test_repeat_runs_collapse_to_a_median_and_report_their_own_spread():
    prop = eq.proposal([_rec("wled", 40.0), _rec("wled", 44.0), _rec("wled", 120.0),
                        _rec("hue", 200.0)])
    wled = next(m for m in prop.measured if m.device_id == "wled")
    assert wled.av_offset_ms == 44.0          # median, not the outlier
    assert wled.runs == 3
    assert wled.spread_ms == pytest.approx(80.0)


def test_a_proposal_past_the_clamp_is_named_not_silently_applied():
    prop = eq.proposal([_rec("slow", 1500.0), _rec("fast", 0.0)])
    by_id = {p["device_id"]: p for p in prop.proposals}
    assert by_id["fast"]["proposed_timing_offset_ms"] == 1000
    assert prop.out_of_range == ["fast"]


def test_every_result_says_the_global_shift_is_the_rooms_own_loop():
    """After equalizing, the room as a whole lands later by the spread —
    absorbed by the EXISTING re-measure + apply loop, not by anything
    here. That sentence ships with every result."""
    for prop in (eq.proposal([_rec("a", 1.0)]),
                 eq.proposal([_rec("a", 1.0), _rec("b", 2.0)])):
        assert "re-measure" in prop.after_note
        assert "A/V sync lead" in prop.after_note


def test_the_proposal_never_writes_anything():
    from spectra.services import device_settings
    eq.proposal([_rec("hue", 120.0), _rec("wled", 40.0)])
    assert device_settings.load_all() == {}


def test_each_row_carries_a_sentence_a_human_can_read():
    prop = eq.proposal([_rec("hue", 120.0), _rec("wled", 40.0)])
    by_id = {p["device_id"]: p for p in prop.proposals}
    assert "slowest" in by_id["hue"]["sentence"]
    assert "waits 80 ms" in by_id["wled"]["sentence"]


# ── the pattern's per-device targeting ──────────────────────────────────────

def _driver(virtuals):
    written: list[list[dict]] = []

    async def get_virtuals():
        return virtuals

    async def apply_writes(writes, *, transition_ms=0):
        written.append(list(writes))

    async def sleep(_s):
        return None

    driver = PatternDriver(get_virtuals=get_virtuals, apply_writes=apply_writes,
                           clock=lambda: 100.0, sleep=sleep)
    return driver, written


async def _drive(driver, *, seed, device_id=None):
    """Start a run and let it finish. The driver's sleep is faked to return
    immediately, so the whole schedule (type switch, every edge, the
    revert) runs as soon as the drive task gets control."""
    done = asyncio.Event()
    run = await driver.start(duration_s=1.0, seed=seed, device_id=device_id,
                             on_done=lambda _r: done.set())
    await asyncio.wait_for(done.wait(), 5.0)
    return run


ROOM = {
    "crystal": {"active": True, "effect": {"type": "blackhole", "config": {"spin": 0.5}}},
    "hue-lights": {"active": True, "effect": {"type": "power", "config": {"brightness": 1.0}}},
    "tv-mapper": {"active": True, "effect": {"type": "melt", "config": {}}},
}


def test_a_narrowed_run_flashes_only_that_devices_virtuals(monkeypatch):
    driver, written = _driver(ROOM)

    async def fake_virtuals_for_device(device_id):
        return {"hue-bridge-1": ["hue-lights"]}.get(device_id, [])

    import spectra.services.av_sync_pattern as pat
    monkeypatch.setattr(pat, "virtuals_for_device", fake_virtuals_for_device)

    run = asyncio.run(_drive(driver, seed=7, device_id="hue-bridge-1"))
    assert run.virtual_ids == ["hue-lights"]
    assert run.device_id == "hue-bridge-1"
    touched = {w["virtual_id"] for batch in written for w in batch}
    assert touched == {"hue-lights"}, \
        "a per-device run must leave every other virtual playing the show"


def test_an_unnarrowed_run_still_flashes_the_whole_room():
    driver, written = _driver(ROOM)

    run = asyncio.run(_drive(driver, seed=7))
    assert run.virtual_ids == ["crystal", "hue-lights", "tv-mapper"]
    assert run.device_id is None


def test_a_device_with_no_virtual_is_a_named_refusal_not_a_silent_no_op(monkeypatch):
    driver, written = _driver(ROOM)

    async def none_for_device(_device_id):
        return []

    import spectra.services.av_sync_pattern as pat
    monkeypatch.setattr(pat, "virtuals_for_device", none_for_device)

    async def go():
        await driver.start(duration_s=1.0, device_id="ghost")

    with pytest.raises(RuntimeError, match="no virtual rendering onto it"):
        asyncio.run(go())
    assert written == [], "a refused run must never write to the room"
    assert not driver.active


def test_a_narrowed_run_reverts_only_what_it_touched(monkeypatch):
    driver, written = _driver(ROOM)

    async def one(_device_id):
        return ["hue-lights"]

    import spectra.services.av_sync_pattern as pat
    monkeypatch.setattr(pat, "virtuals_for_device", one)

    asyncio.run(_drive(driver, seed=3, device_id="hue-bridge-1"))
    revert = written[-1]
    assert [w["virtual_id"] for w in revert] == ["hue-lights"]
    assert revert[0]["effect_type"] == "power"
    assert revert[0]["config"] == {"brightness": 1.0}


def test_the_run_record_carries_the_device_so_the_log_can_be_grouped():
    driver, _ = _driver(ROOM)

    assert asyncio.run(_drive(driver, seed=1)).as_dict()["device_id"] is None


# ── the wire ────────────────────────────────────────────────────────────────

def test_the_measure_message_carries_a_device_id_to_the_pattern(monkeypatch):
    """The phone's `measure` message accepts `device_id`, and it reaches
    the pattern driver — the per-device mode is not a separate code path,
    it is the same measurement narrowed."""
    from spectra.services import av_sync_session as ses

    seen = {}

    class _Pattern:
        active = False

        async def start(self, **kw):
            seen.update(kw)
            from spectra.services.av_sync_pattern import PatternRun
            return PatternRun(seed=1, started_at=0.0, duration_s=1.0,
                              virtual_ids=["hue-lights"],
                              device_id=kw.get("device_id"))

    sent: list[dict] = []

    async def send(m):
        sent.append(m)

    async def go():
        session = ses.Session(send, pattern=_Pattern(),
                              audio_ref=_NullAudioRef())
        await session.handle({"type": "measure", "mode": "pattern",
                              "duration_s": 4, "device_id": "hue-bridge-1"})
        return session

    session = asyncio.run(go())
    assert seen["device_id"] == "hue-bridge-1"
    assert session.device_id == "hue-bridge-1"
    assert any(m.get("type") == "measure_started" and m.get("device_id") == "hue-bridge-1"
               for m in sent)


def test_a_per_device_run_in_passive_mode_is_refused_by_name():
    """Passive mode watches the whole show; it cannot isolate one device,
    and saying so is better than quietly measuring the room instead."""
    from spectra.services import av_sync_session as ses

    sent: list[dict] = []

    async def send(m):
        sent.append(m)

    async def go():
        session = ses.Session(send, pattern=None, audio_ref=_NullAudioRef())
        await session.handle({"type": "measure", "mode": "show",
                              "device_id": "hue-bridge-1"})

    asyncio.run(go())
    assert sent and sent[-1]["type"] == "error"
    assert "flash pattern" in sent[-1]["message"]


class _NullAudioRef:
    def start(self):
        return True

    def available(self):
        return False

    def stats(self):
        return {}

    def stop(self):
        pass
