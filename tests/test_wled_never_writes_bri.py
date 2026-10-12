"""A WLED'S MASTER BRIGHTNESS IS HOME ASSISTANT'S — Spectra never sends it.

The Admiral, 2026-10-12 (data/wled-bri-audit/report.md): "Home assistant can
set the WLED global brightness of any of these lights, and spectra doesn't
touch that value." The guard is AT THE TRANSPORT, not in the source text:
`fx.utils.WLED._wled_request` is the one call every WLED JSON write in this
repo goes through (house_fixtures' power writes, night_power,
release_realtime, and the vendored sync-mode flush). It refuses a json/data
body carrying `bri` — top level or on a segment — before anything leaves.
It refuses "Force max brightness" (`maxbri`, anywhere in a json= or data=
body) the same way: it stays OFF so Home Assistant's brightness keeps
scaling the stream (River's acceptance, 2026-10-12).

Every test below drives that transport, or a real caller of it, and asserts
on observable behaviour — a raised `WLEDBrightnessRefused` and nothing
reaching `requests.post` — never on what the source text of a call site
happens to spell.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.parametrize("body", [
    {"bri": 255},
    {"on": True, "bri": 1},
    {"seg": [{"id": 0, "bri": 3}]},
    {"seg": {"bri": 3}},
])
def test_the_transport_refuses_a_brightness_body_before_it_leaves(body):
    from fx.utils import WLED, WLEDBrightnessRefused
    sent = []

    def post(url, timeout=None, **kwargs):          # pragma: no cover
        sent.append(kwargs)

    with pytest.raises(WLEDBrightnessRefused, match="Home Assistant"):
        asyncio.run(WLED._wled_request(post, "10.0.0.9", "json/state",
                                       json=body))
    assert sent == [], "nothing may reach the wire"


@pytest.mark.parametrize("kw", [
    {"json": {"if": {"live": {"maxbri": True}}}},
    {"json": {"if": {"live": {"maxbri": False}}}},
    {"data": {"if": {"live": {"maxbri": False, "timeout": 5}}}},
])
def test_the_transport_refuses_force_max_brightness_however_it_is_sent(kw):
    from fx.utils import WLED, WLEDBrightnessRefused
    sent = []

    def post(url, timeout=None, **kwargs):          # pragma: no cover
        sent.append(kwargs)

    with pytest.raises(WLEDBrightnessRefused, match="maxbri"):
        asyncio.run(WLED._wled_request(post, "10.0.0.9", "json/cfg", **kw))
    assert sent == []


def test_nothing_can_flush_force_max_brightness():
    """The vendored sync-settings flush always carries the `maxbri` it read,
    so it is refused at the transport."""
    from fx.utils import WLED, WLEDBrightnessRefused
    wled = WLED("10.0.0.9")
    wled.sync_settings = {"if": {"live": {"maxbri": False, "timeout": 2}}}
    wled.force_max_brightness()
    with pytest.raises(WLEDBrightnessRefused):
        asyncio.run(wled.flush_sync_settings())


def test_set_wleds_sync_mode_is_refused_before_reaching_the_wire(monkeypatch):
    """`fx.devices.Devices.set_wleds_sync_mode` — the vendored sync-mode
    switch, with no caller anywhere in this fork today — flushes the same
    read-back sync block as `flush_sync_settings` above, so it is refused
    at the transport too, before a single byte reaches `requests.post`."""
    from types import SimpleNamespace

    import fx.utils as fx_utils
    from fx.devices import Devices
    from fx.utils import WLED, WLEDBrightnessRefused

    sent = []
    monkeypatch.setattr(fx_utils.requests, "post",
                        lambda *a, **k: sent.append((a, k)))

    wled = WLED("10.0.0.48")
    wled.sync_settings = {"if": {"live": {"port": 5568, "maxbri": False,
                                          "timeout": 2}}}
    device = SimpleNamespace(type="wled", pixel_count=560,
                             config={"sync_mode": "udp"}, wled=wled)
    registry = SimpleNamespace(values=lambda: [device])

    with pytest.raises(WLEDBrightnessRefused):
        asyncio.run(Devices.set_wleds_sync_mode(registry, "ddp"))
    assert sent == [], "nothing may reach the wire"


def test_a_power_only_body_still_goes_out():
    from types import SimpleNamespace

    from fx.utils import WLED
    sent = []

    def post(url, timeout=None, **kwargs):
        sent.append(kwargs["json"])
        return SimpleNamespace(ok=True)

    for body in ({"on": True}, {"on": False}, {"live": False},
                 {"seg": [{"id": 0, "on": True}]}):
        asyncio.run(WLED._wled_request(post, "10.0.0.9", "json/state",
                                       json=body))
    assert sent == [{"on": True}, {"on": False}, {"live": False},
                    {"seg": [{"id": 0, "on": True}]}]


def test_house_fixtures_own_transport_goes_through_the_guarded_call():
    """The house seam's real default transport (`_post_blocking`) is the
    guarded `_wled_request`, so even a future payload bug there is refused
    at the wire."""
    from fx.utils import WLED, WLEDBrightnessRefused
    from spectra.services import house_fixtures
    with pytest.raises(WLEDBrightnessRefused):
        house_fixtures._post_blocking(WLED("10.0.0.9"), {"on": True, "bri": 34},
                                      0.1)


def test_every_house_power_write_including_retries_is_power_only(monkeypatch):
    """River's acceptance: every power write is exactly {"on": true|false},
    INCLUDING the retries a refused or unconfirmed write gets — driven
    through the house seam's real `_write_confirmed`/`_transition` with a
    fixture that refuses twice, then never confirms."""
    from types import SimpleNamespace

    from spectra.services import house_fixtures as hf
    posts, reads = [], {"n": 0}

    async def post(dev, payload):
        posts.append(dict(payload))
        if len(posts) <= 2:
            raise TimeoutError("refused")              # the first two fail

    async def get_state(dev):
        reads["n"] += 1
        return {"on": not payload_on[0], "bri": 1}     # never confirms

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(hf, "deps", hf.Deps(post=post, get_state=get_state,
                                             sleep=no_sleep))
    monkeypatch.setattr(hf, "_remember_before", _noop_remember)
    monkeypatch.setattr(hf, "_record_power", lambda *a, **k: None)
    monkeypatch.setattr(hf, "_record", lambda *a, **k: None)
    monkeypatch.setattr(hf, "kick", lambda: None)
    dev = SimpleNamespace(id="crystal", type="wled",
                          wled=SimpleNamespace(ip_address="10.0.0.48"))
    payload_on = [True]
    asyncio.run(hf._transition("crystal", dev, hf.TARGET_ON, "test", owned=True))
    payload_on[0] = False
    asyncio.run(hf._transition("crystal", dev, hf.TARGET_OFF, "test", owned=True))
    on_writes = [p for p in posts if "on" in p]
    assert len(on_writes) == 2 * hf.WRITE_ATTEMPTS, "every retry was tried"
    assert all(p in ({"on": True}, {"on": False}) for p in on_writes), posts
    assert all(set(p) <= {"on", "live"} for p in posts), posts
    assert all("bri" not in p for p in posts)


async def _noop_remember(_did, _dev):
    return None


def test_set_brightness_no_longer_exists():
    from fx.utils import WLED
    assert not hasattr(WLED, "set_brightness")
