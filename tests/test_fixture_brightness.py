"""A MAP TAKEN AT 10% FIRMWARE BRIGHTNESS MEASURES THE DIMMER, NOT THE ROOM.

THE LIVE FINDING (2026-08-31, the captain's verdict on his first real map):
his fixture sat at ten percent firmware brightness through the whole run, so
every footprint came out about ten times too dim — five blocks at 0.1 or
less, which is the unseen threshold's own tail, and blocks plainly in shot
reading a fraction of what the same room's whole-device map measured. The
instrument was measuring his dimmer and nothing in the map said so.

What is proved here:

  * the fixture's own brightness is READ AT PLAN TIME and warned about
    LOUDLY, before the room ever goes dark and before the cost is spent;
  * a run TAKES the fixture to full for the capture and puts HIS level back
    — including when the capture raises, which is the case that would
    otherwise leave his lounge at full;
  * a restore that genuinely fails is NAMED, never swallowed;
  * a fixture with no such setting (Hue, e131, a dummy) is reported as "not
    applicable" and never given a fabricated full reading, and a fixture
    that could not be asked is reported as unreadable — the three states
    stay distinct, because "we could not ask" must never render as "fine";
  * the vendored `WLED.set_brightness` actually sends the value it was
    given. Upstream's double `max` forced every input to 255, which would
    have turned every RESTORE into "set it to full" — the single most
    damaging way this feature could have failed.
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

    async def set_brightness(self, value):
        if self.fail_set:
            raise OSError("refused")
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
    # it says what the run will do about it, so he need not act
    assert "put your own level back" in warning


def test_nothing_to_say_says_nothing():
    assert fb.warning_for([fb.FixtureBrightness("tv", "read", 255)]) == ""
    assert fb.warning_for([fb.FixtureBrightness("tv", "not_applicable")]) == ""
    assert fb.warning_for([]) == ""


# ── 3. owning it for the capture, and giving it back ───────────────────────

def test_the_capture_takes_it_to_full_and_puts_his_level_back():
    helper = _Helper(26)
    device = _Device("tv", helper=helper)
    inside = []

    async def go():
        async with fb.owned([device]) as owned:
            inside.append(helper.value)
            return owned

    owned = asyncio.run(go())
    assert inside == [255]                    # full while being photographed
    assert helper.value == 26                 # HIS level back afterwards
    assert helper.writes == [255, 26]
    assert owned.restored == ["tv"]
    assert "tv (10% -> 100%)" in owned.raised[0]
    assert not owned.problems


def test_his_level_comes_back_even_when_the_capture_raises():
    helper = _Helper(26)

    async def go():
        async with fb.owned([_Device("tv", helper=helper)]):
            raise RuntimeError("the run died mid-capture")

    with pytest.raises(RuntimeError, match="died mid-capture"):
        asyncio.run(go())
    # the case that would otherwise leave his lounge at full all evening
    assert helper.value == 26
    assert helper.writes == [255, 26]


def test_a_restore_that_fails_is_named_rather_than_swallowed():
    class _FailsOnRestore(_Helper):
        async def set_brightness(self, value):
            if self.writes:                   # the second write is the restore
                raise OSError("gone")
            await super().set_brightness(value)

    helper = _FailsOnRestore(26)

    async def go():
        async with fb.owned([_Device("tv", helper=helper)]) as owned:
            pass
        return owned

    owned = asyncio.run(go())
    assert owned.restored == []
    assert len(owned.problems) == 1
    assert "could NOT be put back to 10%" in owned.problems[0]
    assert "set it on the fixture itself" in owned.problems[0]


def test_a_fixture_already_at_full_is_never_written_to_at_all():
    helper = _Helper(255)

    async def go():
        async with fb.owned([_Device("tv", helper=helper)]) as owned:
            pass
        return owned

    owned = asyncio.run(go())
    # no write means no restore that could fail — the quietest correct thing
    assert helper.writes == []
    assert owned.raised == [] and owned.problems == []


def test_an_unreadable_fixture_is_left_completely_alone():
    helper = _Helper(fail_get=True)

    async def go():
        async with fb.owned([_Device("tv", helper=helper)]) as owned:
            pass
        return owned

    owned = asyncio.run(go())
    # never set to a value we would then have to guess how to undo
    assert helper.writes == []
    assert owned.raised == []


def test_a_fixture_that_will_not_turn_up_is_named_and_the_run_goes_on():
    helper = _Helper(26, fail_set=True)

    async def go():
        async with fb.owned([_Device("tv", helper=helper)]) as owned:
            pass
        return owned

    owned = asyncio.run(go())
    assert owned.raised == []
    assert "measured at 10% brightness and is not comparable" in owned.problems[0]


# ── 4. the vendored driver call itself ─────────────────────────────────────

def test_the_vendored_set_brightness_sends_the_value_it_was_given():
    """Upstream's `max(0, max(int(x), 255))` forced EVERY input to 255, so a
    restore would silently have set full and called itself a restore. Proved
    against the real vendored function, at the request it builds."""
    from fx.utils import WLED

    sent = {}

    class _Response:
        ok = True

        def json(self):
            return {}

    def _post(url, timeout=None, **kwargs):
        sent["url"] = url
        sent.update(kwargs)
        return _Response()

    import fx.utils as utils
    original = utils.requests.post
    utils.requests.post = _post
    try:
        asyncio.run(WLED("1.2.3.4").set_brightness(26))
    finally:
        utils.requests.post = original

    assert sent["json"] == {"bri": 26}        # the value, not 255
    assert "data" not in sent                 # JSON body, not form-encoded
    assert sent["url"] == "http://1.2.3.4/json/state"   # no double slash


def test_the_vendored_set_brightness_still_clamps_to_the_real_range():
    from fx.utils import WLED

    sent = []

    class _Response:
        ok = True

    def _post(url, timeout=None, **kwargs):
        sent.append(kwargs.get("json"))
        return _Response()

    import fx.utils as utils
    original = utils.requests.post
    utils.requests.post = _post
    try:
        asyncio.run(WLED("1.2.3.4").set_brightness(9999))
        asyncio.run(WLED("1.2.3.4").set_brightness(-5))
    finally:
        utils.requests.post = original

    assert sent == [{"bri": 255}, {"bri": 0}]
