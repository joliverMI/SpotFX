"""A MAP TAKEN AT 10% FIRMWARE BRIGHTNESS MEASURES THE DIMMER, NOT THE ROOM.

THE LIVE FINDING (2026-08-31, the captain's verdict on his first real map):
his fixture sat at ten percent firmware brightness through the whole run, so
every footprint came out about ten times too dim — five blocks at 0.1 or
less, which is the unseen threshold's own tail, and blocks plainly in shot
reading a fraction of what the same room's whole-device map measured. The
instrument was measuring his dimmer and nothing in the map said so.

THE RULE SINCE 2026-10-12 (the Admiral, data/wled-bri-audit/report.md D1a):
a WLED's master brightness is Home Assistant's, and Spectra never writes it
— not even for a capture. What is proved here:

  * the fixture's own brightness is READ AT PLAN TIME and warned about
    LOUDLY, before the room ever goes dark, naming what to do (raise it in
    Home Assistant);
  * a capture MEASURES AS IS: `measured_as_is` writes nothing — on entry,
    on exit, or when the capture raises — and names every fixture captured
    below full for the run's notes;
  * a NIGHT run's request ("raise X to 100% in Home Assistant") is a
    sentence for the morning, never a write;
  * a fixture with no such setting (Hue, e131, a dummy) is reported as "not
    applicable" and never given a fabricated full reading, and a fixture
    that could not be asked is reported as unreadable — the three states
    stay distinct, because "we could not ask" must never render as "fine";
  * the vendored `WLED.set_brightness` no longer exists.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.services import fixture_brightness as fb


class _Helper:
    """A WLED helper, reduced to the two calls this path makes."""

    def __init__(self, value=26, fail_set=False, fail_get=False):
        self.value = value
        self.writes: list[int] = []
        self.fail_set = fail_set
        self.fail_get = fail_get

    async def get_brightness(self):
        if self.fail_get:
            raise OSError("no answer")
        return self.value

    async def set_brightness(self, value):             # must never be called
        self.writes.append(int(value))
        self.value = int(value)


class _Device:
    def __init__(self, device_id, type_="wled", helper=None):
        self.id = device_id
        self.type = type_
        self.wled = helper


# ── 1. reading, and the three distinct states ──────────────────────────────

def test_a_wled_fixture_reports_its_real_level():
    r = asyncio.run(fb.read_one(_Device("tv", helper=_Helper(26))))
    assert r.state == "read" and r.value == 26
    assert r.percent == 10                    # his actual level
    assert r.low is True


def test_a_fixture_with_no_such_setting_is_never_given_a_fabricated_full():
    for kind in ("hue", "e131", "ddp", "dummy"):
        r = asyncio.run(fb.read_one(_Device("x", kind)))
        assert r.state == "not_applicable"
        # the trap this avoids: a made-up 255 makes an UNGUARDED fixture
        # look guarded, which is the exact failure this module exists to end
        assert r.value is None
        assert r.low is False
        assert kind in r.reason


def test_a_fixture_that_cannot_be_asked_is_unreadable_not_fine():
    r = asyncio.run(fb.read_one(
        _Device("tv", helper=_Helper(fail_get=True))))
    assert r.state == "unreadable"
    assert r.value is None
    assert r.low is False                     # never claimed to be low OR fine
    assert "brightness is unknown" in r.reason


# ── 2. the warning, before the cost ────────────────────────────────────────

def test_the_warning_names_the_fixture_and_its_level():
    readings = [fb.FixtureBrightness("tv", "read", 26),
                fb.FixtureBrightness("lamp", "read", 255)]
    warning = fb.warning_for(readings)
    assert "TURNED DOWN" in warning
    assert "tv at 10%" in warning
    assert "lamp" not in warning              # a fixture at full is not nagged
    # it says what HE can do — Spectra never changes it
    assert "raise it to 100% in Home Assistant" in warning
    assert "measures it as it is" in warning


def test_nothing_to_say_says_nothing():
    assert fb.warning_for([fb.FixtureBrightness("tv", "read", 255)]) == ""
    assert fb.warning_for([fb.FixtureBrightness("tv", "not_applicable")]) == ""
    assert fb.warning_for([]) == ""


# ── 3. measured as is: never a write ───────────────────────────────────────

def test_a_capture_measures_a_dim_fixture_as_is_and_names_it():
    helper = _Helper(26)
    device = _Device("tv", helper=helper)
    inside = []

    async def go():
        async with fb.measured_as_is([device]) as as_is:
            inside.append(helper.value)
            return as_is

    as_is = asyncio.run(go())
    assert inside == [26]                     # his level while photographed
    assert helper.value == 26 and helper.writes == []
    assert "tv at 10%" in as_is.note
    assert "Home Assistant" in as_is.note


def test_nothing_is_written_even_when_the_capture_raises():
    helper = _Helper(26)

    async def go():
        async with fb.measured_as_is([_Device("tv", helper=helper)]):
            raise RuntimeError("the run died mid-capture")

    with pytest.raises(RuntimeError, match="died mid-capture"):
        asyncio.run(go())
    assert helper.writes == []


def test_a_fixture_at_full_or_unreadable_gets_no_note():
    for helper in (_Helper(255), _Helper(fail_get=True)):
        async def go(h=helper):
            async with fb.measured_as_is([_Device("tv", helper=h)]) as as_is:
                return as_is
        assert asyncio.run(go()).note == ""
        assert helper.writes == []


def test_a_night_records_a_request_rather_than_writing():
    readings = [fb.FixtureBrightness("crystal", "read", 34),
                fb.FixtureBrightness("porch", "read", 255)]
    request = fb.raise_request(readings)
    assert request.startswith("Raise crystal (it was at 13%) to 100% in Home "
                              "Assistant")
    assert "porch" not in request
    assert fb.raise_request([fb.FixtureBrightness("x", "read", 255)]) == ""


# ── 4. the vendored driver call is gone ────────────────────────────────────

def test_the_vendored_set_brightness_no_longer_exists():
    from fx.utils import WLED
    assert not hasattr(WLED, "set_brightness")
    assert hasattr(WLED, "get_brightness")     # reading stays
