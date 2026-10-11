"""THE EASED HA VOLUME STEP (spectra/services/ha_volume_ease.py) — the
plan arithmetic, the ramp against a stateful fake Home Assistant (no
network anywhere: `ha_client.call_service`/`get_state` are replaced), the
last-step-wins replacement, a relative step carrying the stopped ramp's
remainder, a mid-ramp failure, a restart mid-ramp, and the Light Show /
Sonic surfaces that reach it.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.services import ha_client, ha_volume_ease, show_actions, show_console
from tests.test_light_show import A, fire, room  # noqa: F401  (fixture)

E = ha_volume_ease


# ── the plan (pure) ─────────────────────────────────────────────────────────

def test_absolute_plan_walks_in_fours_and_lands_exactly():
    plan = E.plan_absolute(12, 52, 1.0)
    values = [v for _, v in plan]
    assert values == [16, 20, 24, 28, 32, 36, 40, 44, 48, 52]
    times = [t for t, _ in plan]
    assert times[0] == 0
    assert times == sorted(times) and times[-1] < 1.0
    assert all(b - a >= E.MIN_WRITE_INTERVAL_S - 1e-9 for a, b in zip(times, times[1:]))


def test_absolute_plan_never_writes_faster_than_ten_a_second():
    plan = E.plan_absolute(0, 100, 1.0)
    assert len(plan) == 10, "25 levels over 1 s must take bigger steps, not write faster"
    values = [v for _, v in plan]
    assert values[-1] == 100
    assert all(v % 4 == 0 for v in values)
    assert values == sorted(values)


def test_absolute_plan_from_an_off_grid_level_still_lands_on_target():
    values = [v for _, v in E.plan_absolute(13, 50, 1.0)]
    assert values[-1] == 50
    assert all(v % 4 == 0 for v in values[:-1])
    assert all(13 <= v <= 50 for v in values)


@pytest.mark.parametrize("start,target,ease", [(52, 52, 1.0), (48, 52, 1.0), (12, 52, 0.0)])
def test_absolute_plan_is_one_write_when_there_is_nothing_to_ease(start, target, ease):
    assert E.plan_absolute(start, target, ease) == [(0.0, target)]


def test_absolute_plan_downwards():
    values = [v for _, v in E.plan_absolute(52, 12, 1.0)]
    assert values == [48, 44, 40, 36, 32, 28, 24, 20, 16, 12]


def test_relative_plan_splits_into_fours_summing_exactly():
    assert E.plan_relative(8, 1.0) == [(0.0, 4), (0.5, 4)]
    incs = [i for _, i in E.plan_relative(-10, 1.0)]
    assert sum(incs) == -10
    assert E.plan_relative(8, 0.0) == [(0.0, 8)]


# ── a stateful fake Home Assistant ──────────────────────────────────────────

class FakeHA:
    """snap_volume as HA holds it, moved by the two scripts exactly as
    River's YAML moves it (set_value; the step clamps 0-100)."""

    def __init__(self, volume=12.0):
        self.volume = float(volume)
        self.calls: list = []
        self.reads = 0
        self.fail_on: set = set()
        self.read_ok = True

    async def call_service(self, domain, service, data=None, *, client=None):
        n = len(self.calls) + 1
        self.calls.append((asyncio.get_running_loop().time(), service, dict(data or {})))
        if n in self.fail_on:
            return ha_client.HAResult(status=ha_client.STATUS_FAILED, http_status=500,
                                      detail="Home Assistant answered 500")
        if service == "music_volume_set":
            self.volume = float(data["volume"])
        else:
            self.volume = max(0.0, min(100.0, self.volume + float(data["delta"])))
        return ha_client.HAResult(status=ha_client.STATUS_SENT, http_status=200)

    async def get_state(self, entity_id, *, client=None):
        self.reads += 1
        if not self.read_ok:
            return ha_client.HAEntityState(status=ha_client.STATUS_FAILED,
                                           detail="Home Assistant answered 404")
        return ha_client.HAEntityState(status=ha_client.STATUS_SENT,
                                       http_status=200, state=f"{self.volume}")


@pytest.fixture
def ha(monkeypatch):
    fake = FakeHA()
    monkeypatch.setenv("SPECTRA_HA_URL", "http://ha.invalid")
    monkeypatch.setattr(ha_client, "call_service", fake.call_service)
    monkeypatch.setattr(ha_client, "get_state", fake.get_state)
    # Fast but real time: 10 ms between writes instead of 100.
    monkeypatch.setattr(E, "MIN_WRITE_INTERVAL_S", 0.01)
    return fake


def _run(coro):
    return asyncio.run(coro)


# ── absolute ────────────────────────────────────────────────────────────────

def test_absolute_eases_from_the_read_level_to_the_target(ha):
    async def go():
        r = await E.set_absolute(52, 0.2)
        assert r.ha.ok and "easing 12 → 52" in r.detail
        await E.wait_idle()
    _run(go())
    values = [d["volume"] for _, _, d in ha.calls]
    assert values == [16, 20, 24, 28, 32, 36, 40, 44, 48, 52]
    assert ha.volume == 52
    span = ha.calls[-1][0] - ha.calls[0][0]
    assert 0.15 <= span < 0.4, f"ten writes spread over ~0.18 s, got {span:.3f}"
    assert E.status()["last"]["state"] == "done"
    assert E.status()["in_flight"] is None


def test_absolute_ease_zero_is_one_write_and_no_read(ha):
    async def go():
        r = await E.set_absolute(40, 0)
        assert r.detail == "HA volume set to 40"
    _run(go())
    assert ha.reads == 0
    assert [d for _, _, d in ha.calls] == [{"volume": 40}]


def test_absolute_falls_back_to_instant_when_the_level_cannot_be_read(ha):
    ha.read_ok = False

    async def go():
        r = await E.set_absolute(52, 1.0)
        assert r.ha.ok
        assert "instantly" in r.detail and "404" in r.detail
    _run(go())
    assert [d for _, _, d in ha.calls] == [{"volume": 52}]


def test_unconfigured_ha_never_reads_and_reports_not_configured(monkeypatch):
    monkeypatch.delenv("SPECTRA_HA_URL", raising=False)

    async def no_read(*a, **k):
        raise AssertionError("must not read when HA is not configured")
    monkeypatch.setattr(ha_client, "get_state", no_read)
    r = _run(E.set_absolute(52, 1.0))
    assert r.ha.status == ha_client.STATUS_UNCONFIGURED


# ── one ramp at a time: the last step wins ──────────────────────────────────

def test_a_newer_absolute_step_stops_the_ramp_and_wins(ha):
    ha.volume = 0

    async def go():
        await E.set_absolute(100, 0.5)          # 10 writes, 50 ms apart
        await asyncio.sleep(0.12)
        r = await E.set_absolute(20, 0)
        assert r.ha.ok
        await asyncio.sleep(0.6)                  # past the first ramp's end
    _run(go())
    assert ha.calls[-1][2] == {"volume": 20}, "nothing from the old ramp after the newer step"
    assert ha.volume == 20
    assert E.status()["in_flight"] is None


def test_a_newer_eased_absolute_starts_from_where_the_old_one_stopped(ha):
    ha.volume = 0

    async def go():
        await E.set_absolute(100, 0.5)
        await asyncio.sleep(0.12)
        partway = ha.volume
        r = await E.set_absolute(0, 0.2)
        assert f"easing {partway:g} → 0" in r.detail
        await E.wait_idle()
    _run(go())
    assert ha.volume == 0


def test_a_relative_step_carries_what_the_stopped_relative_ramp_still_owed(ha):
    ha.volume = 12

    async def go():
        await E.set_absolute(12, 0)               # nothing in flight
        await E.step_relative("script", "music_volume_step", 40, 0.4)
        await asyncio.sleep(0.1)
        r = await E.step_relative("script", "music_volume_step", 8, 0)
        assert "still owed" in r.detail
    _run(go())
    assert ha.volume == 12 + 40 + 8


def test_a_relative_step_is_relative_to_where_an_absolute_ramp_was_heading(ha):
    ha.volume = 0

    async def go():
        await E.set_absolute(40, 0.4)
        await asyncio.sleep(0.1)
        await E.step_relative("script", "music_volume_step", 8, 0.1)
        await E.wait_idle()
    _run(go())
    assert ha.volume == 48


def test_two_quick_eased_plus_eights_land_at_plus_sixteen(ha):
    ha.volume = 20

    async def go():
        await E.step_relative("script", "music_volume_step", 8, 0.3)
        await E.step_relative("script", "music_volume_step", 8, 0.3)
        await E.wait_idle()
    _run(go())
    assert ha.volume == 36


def test_a_relative_ramp_uses_only_the_relative_script(ha):
    async def go():
        await E.step_relative("script", "other_step", -8, 0.1)
        await E.wait_idle()
    _run(go())
    assert {s for _, s, _ in ha.calls} == {"other_step"}
    assert sum(d["delta"] for _, _, d in ha.calls) == -8
    assert ha.reads == 0, "a relative step never needs to read the level"


# ── failure and restart ─────────────────────────────────────────────────────

def test_a_failed_write_mid_ramp_ends_it_loudly(ha):
    ha.fail_on = {3}

    async def go():
        r = await E.set_absolute(52, 0.2)
        assert r.ha.ok
        await E.wait_idle()
    _run(go())
    assert len(ha.calls) == 3, "no writes after the failure"
    last = E.status()["last"]
    assert last["state"] == "failed" and "500" in last["detail"]
    assert E.status()["in_flight"] is None


def test_a_failed_first_write_fails_the_step_and_starts_no_ramp(ha):
    ha.fail_on = {1}
    r = _run(E.set_absolute(52, 0.2))
    assert not r.ha.ok
    assert len(ha.calls) == 1
    assert E.status()["in_flight"] is None


def test_restart_mid_ramp_leaves_a_real_level_between_start_and_target(ha):
    """The process going away mid-ramp is the loop ending with the ramp in
    flight: whatever was written last is a multiple of 4 between where the
    ramp started and where it was going, and the next process's step
    works with nothing left over."""
    async def interrupted():
        await E.set_absolute(52, 0.5)
        await asyncio.sleep(0.12)                 # the "restart"
    _run(interrupted())
    assert 12 < ha.volume < 52 and ha.volume % 4 == 0
    E.reset()                                     # a fresh process remembers nothing
    r = _run(E.set_absolute(40, 0))
    assert r.ha.ok and ha.volume == 40


def test_a_step_on_a_new_loop_drops_a_ramp_left_by_a_dead_one(ha):
    async def interrupted():
        await E.set_absolute(52, 0.5)
        await asyncio.sleep(0.05)
    _run(interrupted())
    # No reset this time: the stale slot must be dropped, not awaited.
    r = _run(E.set_absolute(8, 0))
    assert r.ha.ok and ha.volume == 8


# ── the Light Show and Sonic surfaces ──────────────────────────────────────

def test_both_volume_kinds_carry_an_ease_defaulting_to_one_second():
    kinds = {k["kind"]: k for k in show_actions.catalogue()["kinds"]}
    for name in ("ha_volume_absolute", "ha_volume_relative"):
        ease = next(p for p in kinds[name]["params"] if p["name"] == "ease_s")
        assert ease["default"] == 1.0 and ease["min"] == 0 and ease["unit"] == "s"
    # A step saved before the setting existed gets the default.
    assert show_actions.validate("ha_volume_absolute", {"volume": 40})["ease_s"] == 1.0
    with pytest.raises(show_actions.ActionError):
        show_actions.validate("ha_volume_absolute", {"volume": 40, "ease_s": -1})


def test_a_light_show_step_eases_and_reports_it(room, ha):
    run = fire([A("ha_volume_absolute", volume=52, ease_s=0.2)])
    step = run["steps"][0]
    assert step["status"] == "applied"
    assert "easing 12 → 52 over 0.2 s" in step["detail"]
    assert step["ease"]["writes"] == 10


def test_sonic_passes_ease_through(room, ha):
    result = _run(show_console._op_set_ha_volume_absolute(volume=40, ease_s=0))
    assert result["status"] == "applied"
    assert [d for _, _, d in ha.calls] == [{"volume": 40}]
    result = _run(show_console._op_set_ha_volume_relative(delta=8, ease_s=0))
    assert result["status"] == "applied"
    assert ha.calls[-1][2] == {"delta": 8}
    schema = show_console.OPERATIONS["set_ha_volume_relative"].input_schema
    assert "ease_s" in schema["properties"]
