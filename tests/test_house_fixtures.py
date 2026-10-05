"""HOUSE LIGHTING phase 2 — the fixtures half of the Home Assistant seam
(spectra/services/house_fixtures.py). The proofs, in the module's order:

  1. INERT: no mode, the room released, or standby → nothing withheld and
     no WLED written; a request is still RECORDED.
  2. BRIGHTNESS: a mode drives the room → every in-scope WLED is held on at
     the owned brightness (confirmed by read-back); Hue and dummies are
     never written; a drift read back later is re-asserted and NAMED; an
     unreadable fixture is left alone.
  3. LEND: TV Music off / a media source on → the TV strip is withheld and
     told {"live": false}; the sconces on the same virtual are untouched;
     return → power-on write FIRST, stream after.
  4. ON / OFF: off = withheld, then the SOFT dim {"bri": 1} (phase 3), then
     {"live": false}, then {"on": false}; on = {"on": true, "bri": 1} while
     still withheld, stream after, THEN the owned {"bri": 255} — the WLED's
     own preset is never seen at full between the steps.
  5. SCOPE (PR 317): a fixture outside the take is recorded, never written.
  6. HAND-BACK: a fixture this process switched off is switched back on
     when the mode is cleared while SPECTRA still holds the room.
  7. RECHECK: re-find, re-init, re-apply power/brightness when it answers;
     unknown / outside-the-take named; not acted on when the room is not
     SPECTRA's.

No network: the WLED transport, the host, relocation and the probe are
fakes behind house_fixtures.deps.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from spectra.models.house_mode import FixtureHook, HouseMode, HouseTarget


class FakeDev:
    def __init__(self, did, name, kind="wled"):
        self.id = did
        self.name = name
        self.type = kind
        self.wled = SimpleNamespace(ip_address=f"ip-{did}") if kind == "wled" else None
        self._destination = "10.0.0.1" if kind == "wled" else None
        self.frozen = False


class FakeHost:
    def __init__(self, scope=None):
        self.devices = {
            "crystal": FakeDev("crystal", "Crystal"),
            "tv-backlight": FakeDev("tv-backlight", "TV Mapper"),
            "sconce-kitchen-left": FakeDev("sconce-kitchen-left", "Sconce, Kitchen, Left"),
            "sconce-kitchen-right": FakeDev("sconce-kitchen-right", "Sconce, Kitchen, Right"),
            "porch-rail": FakeDev("porch-rail", "Porch Rail"),
            "hue-lights": FakeDev("hue-lights", "Hue Lights", kind="hue"),
            "radial-dummy": FakeDev("radial-dummy", "Radial Dummy", kind="dummy"),
            "gap-matrix": FakeDev("gap-matrix", "gap", kind="dummy"),
        }
        self.virtuals = {}
        self._scope = scope

    def scope_device_ids(self):
        return self._scope


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class World:
    pass


@pytest.fixture
def seam(monkeypatch):
    from spectra.services import house, house_fixtures, house_store, show_output
    w = World()
    w.host = FakeHost()
    w.clock = Clock()
    w.gate = [(None, None)]
    w.refusal = [None]
    w.posts: list = []
    w.state = {d: {"on": True, "bri": 34, "live": True} for d in w.host.devices}
    w.gates: dict = {}            # did -> asyncio.Event blocking its posts
    w.unreadable: set = set()

    monkeypatch.setattr(house, "gate", lambda: w.gate[0])

    async def no_house_tick():
        return None
    # The resting layer itself is test_house_lighting.py's business; here
    # set_media must only move the facts the seam reads.
    monkeypatch.setattr(house, "tick", no_house_tick)
    monkeypatch.setattr(show_output, "ownership_refusal", lambda: w.refusal[0])
    monkeypatch.setattr(show_output, "_host", lambda: w.host)

    async def post(dev, payload):
        ev = w.gates.get(dev.id)
        if ev is not None:
            await ev.wait()
        w.posts.append((dev.id, dict(payload)))
        st = w.state[dev.id]
        for k in ("on", "bri", "live"):
            if k in payload:
                st[k] = payload[k]

    async def get_state(dev):
        if dev.id in w.unreadable:
            raise TimeoutError("no answer")
        return dict(w.state[dev.id])

    async def no_sleep(_s):
        await asyncio.sleep(0)

    w.reach = {"ok": True, "after": 0, "calls": 0}

    async def reachable(did):
        w.reach["calls"] += 1
        if w.reach["calls"] > w.reach["after"]:
            return True, ""
        return False, "no answer"

    w.relocated: list = []
    w.reinited: list = []

    async def relocate(dev, host):
        w.relocated.append(dev.id)
        return False

    async def reinit(dev):
        w.reinited.append(dev.id)
        return True

    async def report_refresh():
        return None

    w.released = [False]
    w.ip_posts: list = []

    async def post_ip(ip, payload):
        did = ip[len("ip-"):]
        w.ip_posts.append((did, dict(payload)))
        if did in w.unreachable_ips:
            raise TimeoutError("no answer")
        w.state[did].update({k: payload[k] for k in ("on", "bri") if k in payload})

    async def get_ip(ip):
        did = ip[len("ip-"):]
        if did in w.unreachable_ips:
            raise TimeoutError("no answer")
        return dict(w.state[did])
    w.unreachable_ips: set = set()
    w.hyperion_live: dict = {}

    async def read_live(did):
        return w.hyperion_live.get(did)

    house_fixtures.deps = house_fixtures.Deps(
        post=post, get_state=get_state, host=lambda: w.host,
        relocate=relocate, reinit=reinit, reachable=reachable,
        report_refresh=report_refresh, clock=w.clock, sleep=no_sleep,
        post_ip=post_ip, get_ip=get_ip, released=lambda: w.released[0],
        read_live=read_live)
    w.hf, w.house, w.store = house_fixtures, house, house_store

    def set_mode(name="Standard", fixtures=None):
        mode = house_store.put_mode(HouseMode(name=name, fixtures=fixtures or []))
        st = house_store.state()
        st.mode_id = mode.id
        house_store.save_state()
        return mode
    w.set_mode = set_mode
    return w


async def _settle(hf, passes=2):
    """A supervisor pass, then every write it started, then a pass to push
    what they changed."""
    for _ in range(passes):
        await hf.tick()
        while hf._rt.inflight:
            tasks = [t for _, t in list(hf._rt.inflight.values())]
            await asyncio.gather(*tasks, return_exceptions=True)
    await hf.tick()


def _run(coro):
    return asyncio.run(coro)


WLEDS = {"crystal", "tv-backlight", "sconce-kitchen-left",
         "sconce-kitchen-right", "porch-rail"}


# ═══ 1. inert ═══════════════════════════════════════════════════════════════

def test_with_no_mode_nothing_is_withheld_or_written(seam):
    from fx import device_output
    seam.hf.set_tv_music(False)
    seam.hf.set_fixture("crystal", power="off")
    _run(_settle(seam.hf))
    assert seam.posts == []
    assert device_output.withheld() == {}
    # …but both facts are recorded for when a mode drives the room
    st = seam.store.state()
    assert st.tv_music is False and st.fixtures["crystal"].power == "off"


def test_a_released_room_is_never_written(seam):
    from fx import device_output
    seam.set_mode()
    seam.refusal[0] = "the room is released"
    seam.hf.set_fixture("crystal", power="off")
    _run(_settle(seam.hf))
    assert seam.posts == []
    assert device_output.withheld() == {}


def test_standby_changes_nothing(seam):
    from fx import device_output
    seam.set_mode()
    _run(_settle(seam.hf))
    seam.posts.clear()
    seam.gate[0] = ("standby", "a camera run is measuring the room")
    seam.hf.set_tv_music(False)
    _run(_settle(seam.hf))
    assert seam.posts == []
    assert "tv-backlight" not in device_output.withheld()


# ═══ 2. brightness ══════════════════════════════════════════════════════════

def test_a_mode_holds_every_in_scope_wled_on_at_the_owned_brightness(seam):
    seam.set_mode()
    _run(_settle(seam.hf))
    written = {did for did, p in seam.posts}
    assert written == WLEDS, "Hue / dummies must never be written"
    for did, payload in seam.posts:
        assert payload == {"on": True, "bri": 255}
    for did in WLEDS:
        assert seam.state[did]["bri"] == 255
        assert seam.hf._rt.applied[did].outcome == "landed"


def test_own_brightness_off_writes_nothing(seam):
    from spectra.models.house_mode import HouseSettings
    seam.store.put_settings(HouseSettings(own_brightness=False))
    seam.set_mode()
    _run(_settle(seam.hf))
    assert seam.posts == []


def test_a_drift_is_re_asserted_and_named(seam):
    seam.set_mode()
    _run(_settle(seam.hf))
    seam.posts.clear()
    seam.state["crystal"]["bri"] = 34          # Home Assistant wrote it
    seam.clock.now += seam.hf.DRIFT_CHECK_S + 1
    _run(_settle(seam.hf))
    assert ("crystal", {"on": True, "bri": 255}) in seam.posts
    corr = seam.hf.status()["corrections"]
    assert any(c["device"] == "crystal" and c["found"]["bri"] == 34 for c in corr)
    # the fixtures that had not drifted were read, not written
    assert {d for d, _ in seam.posts} == {"crystal"}


def test_an_unreadable_fixture_is_left_alone_on_a_drift_check(seam):
    seam.set_mode()
    _run(_settle(seam.hf))
    seam.posts.clear()
    seam.unreadable.add("tv-backlight")
    seam.state["tv-backlight"]["bri"] = 10
    seam.clock.now += seam.hf.DRIFT_CHECK_S + 1
    _run(_settle(seam.hf))
    assert all(d != "tv-backlight" for d, _ in seam.posts)


# ═══ 3. lend ════════════════════════════════════════════════════════════════

def test_tv_music_off_lends_the_strip_and_leaves_the_sconces(seam):
    from fx import device_output
    seam.set_mode()
    _run(_settle(seam.hf))
    seam.posts.clear()
    seam.hf.set_tv_music(False)
    _run(_settle(seam.hf))
    assert set(device_output.withheld()) == {"tv-backlight"}
    assert seam.posts == [("tv-backlight", {"live": False})]
    assert seam.hf.tv_strip_status()["owner"] == "hyperion"


def test_reclaim_powers_on_first_and_streams_after(seam):
    from fx import device_output

    async def scenario():
        seam.set_mode()
        await _settle(seam.hf)
        seam.hf.set_tv_music(False)
        await _settle(seam.hf)
        seam.posts.clear()
        gate = asyncio.Event()
        seam.gates["tv-backlight"] = gate
        seam.hf.set_tv_music(True)
        await seam.hf.tick()
        await asyncio.sleep(0)
        # the power-on write is in flight: the strip is STILL withheld
        assert "tv-backlight" in device_output.withheld()
        gate.set()
        await _settle(seam.hf)
        assert "tv-backlight" not in device_output.withheld()
        # SOFT POWER (phase 3): on at the soft brightness, stream, then full
        assert seam.posts[:2] == [("tv-backlight", {"on": True, "bri": 1}),
                                  ("tv-backlight", {"on": True, "bri": 255})]
    _run(scenario())
    assert seam.hf.tv_strip_status()["owner"] == "spectra"


def test_a_media_source_lends_the_strip_until_it_stops(seam):
    from fx import device_output

    async def scenario():
        seam.set_mode()
        await _settle(seam.hf)
        await seam.house.set_media(source="roku", state="playing")
        await _settle(seam.hf)
        assert "tv-backlight" in device_output.withheld()
        assert "Roku" in seam.hf.tv_strip_status()["why"] \
            or "roku" in seam.hf.tv_strip_status()["why"]
        await seam.house.set_media(source="roku", state="stopped")
        await _settle(seam.hf)
        assert "tv-backlight" not in device_output.withheld()
    _run(scenario())


def test_an_explicit_lend_is_honoured_and_given_back(seam):
    from fx import device_output
    seam.set_mode()
    res = seam.hf.set_fixture("tv-backlight", lent_to="hyperion")
    assert res["status"] == "recorded"
    _run(_settle(seam.hf))
    assert "tv-backlight" in device_output.withheld()
    seam.hf.set_fixture("tv-backlight", lent_to=None)
    _run(_settle(seam.hf))
    assert "tv-backlight" not in device_output.withheld()


def test_a_mode_off_tv_strip_switches_off_when_hyperion_is_not_streaming(seam):
    """Decision (2026-10-05, the TV backlight incident): when the mode's
    plan powers the TV strip off, Spectra switches it off UNLESS Hyperion
    is actually streaming to it — never because the lend reason (TV Music
    off) alone says so. Unconfirmed reads as "not streaming". While the
    mode's own fade hasn't landed it in mode_off_devices() yet, the strip
    gets no action (never lent, never guessed on) — then, once house.py's
    own supervisor catches up (simulated here directly), it goes off like
    any other mode-off fixture."""
    from fx import device_output
    seam.set_mode("Away", fixtures=[
        FixtureHook(target=HouseTarget(kind="fixture", id="tv-backlight"),
                    off=True)])
    seam.hf.set_tv_music(False)
    _run(_settle(seam.hf))
    assert "tv-backlight" not in device_output.withheld()
    assert all(did != "tv-backlight" for did, _p in seam.posts)
    # house.py's own supervisor (a no-op in this harness) has now applied
    # the mode's fade — the fixture's fade-to-black has landed.
    seam.house._rt.off_ready["tv-backlight"] = seam.clock.now
    seam.house._rt.phase = seam.house.PHASE_RESTING
    _run(_settle(seam.hf))
    assert device_output.withheld().get("tv-backlight") == "switched off"
    assert ("tv-backlight", {"on": False}) in seam.posts
    assert seam.state["tv-backlight"]["on"] is False


def test_a_mode_off_tv_strip_stays_lent_while_hyperion_actually_streams(seam):
    from fx import device_output
    seam.set_mode("Away", fixtures=[
        FixtureHook(target=HouseTarget(kind="fixture", id="tv-backlight"),
                    off=True)])
    seam.hf.set_tv_music(False)
    seam.hyperion_live["tv-backlight"] = True
    _run(_settle(seam.hf))
    assert device_output.withheld().get("tv-backlight") == "lent: TV Music is off — Hyperion drives the strip"
    assert [p for d, p in seam.posts if d == "tv-backlight"] == [{"live": False}]


def test_the_admirals_tv_default_on_preference_is_unchanged(seam):
    """TV Music on (the Admiral's default, no mode off) still streams the
    strip normally — this decision only narrows the LEND, never the
    default."""
    seam.set_mode()
    _run(_settle(seam.hf))
    assert ("tv-backlight", {"on": True, "bri": 255}) in seam.posts


# ═══ 3b. a mode-off fixture is never switched on while activating ═════════

def test_a_plan_off_fixture_is_never_switched_on_during_activation(seam):
    """The dining-table flash (2026-10-05): house.py's own fade/off_ready
    hasn't landed this fixture in mode_off_devices() yet — because this
    harness's house.tick is a no-op, exactly as it never does — so
    house_fixtures must not guess it ON in the meantime. Every OTHER
    fixture the mode doesn't plan to power off still gets the ordinary
    own-brightness treatment."""
    seam.set_mode("Away", fixtures=[
        FixtureHook(target=HouseTarget(kind="fixture", id="crystal"), off=True)])
    _run(_settle(seam.hf))
    assert all(did != "crystal" for did, _payload in seam.posts), \
        "a plan-off fixture must never be switched on as a side effect"
    assert "crystal" not in seam.hf._rt.applied
    from fx import device_output
    assert "crystal" not in device_output.withheld()
    # the rest of the room still comes up normally
    written = {did for did, _p in seam.posts}
    assert written == WLEDS - {"crystal"}


def test_a_plan_off_fixture_that_was_already_on_is_never_re_asserted_on(seam):
    """The same race with the fixture already reporting ON before the
    take: it must go straight to its eventual fade/off, never an extra ON
    write first."""
    seam.state["crystal"]["on"] = True
    seam.set_mode("Away", fixtures=[
        FixtureHook(target=HouseTarget(kind="fixture", id="crystal"), off=True)])
    _run(_settle(seam.hf))
    assert all(did != "crystal" for did, _payload in seam.posts)


# ═══ 4. on / off ════════════════════════════════════════════════════════════

def test_off_withholds_then_leaves_realtime_then_powers_down(seam):
    from fx import device_output
    seam.set_mode()
    _run(_settle(seam.hf))
    seam.posts.clear()
    seam.hf.set_fixture("Crystal", power="off")      # by NAME
    _run(_settle(seam.hf))
    assert device_output.withheld().get("crystal") == "switched off"
    assert [p for d, p in seam.posts if d == "crystal"] == [
        {"bri": 1}, {"live": False}, {"on": False}]
    assert seam.state["crystal"]["on"] is False
    assert seam.hf._rt.applied["crystal"].outcome == "landed"


def test_on_writes_power_and_brightness_before_the_stream(seam):
    from fx import device_output

    async def scenario():
        seam.set_mode()
        seam.hf.set_fixture("crystal", power="off")
        await _settle(seam.hf)
        seam.posts.clear()
        gate = asyncio.Event()
        seam.gates["crystal"] = gate
        seam.hf.set_fixture("crystal", power="on")
        await seam.hf.tick()
        await asyncio.sleep(0)
        assert "crystal" in device_output.withheld()
        gate.set()
        await _settle(seam.hf)
        assert "crystal" not in device_output.withheld()
        assert seam.posts == [("crystal", {"on": True, "bri": 1}),
                              ("crystal", {"on": True, "bri": 255})]
    _run(scenario())


def test_a_hue_area_cannot_be_switched_off_here(seam):
    res = seam.hf.set_fixture("hue-lights", power="off")
    assert res["status"] == "invalid"
    res = seam.hf.set_fixture("nope", power="off")
    assert res["status"] == "unknown_fixture"


def test_a_name_naming_two_fixtures_is_refused(seam):
    seam.host.devices["porch-rail"].name = "Crystal"
    dev, why = seam.hf.resolve_fixture("crystal ")
    assert dev is not None and dev["id"] == "crystal"      # the id wins
    dev, why = seam.hf.resolve_fixture("CRYSTAL")
    assert dev is None and "2 fixtures" in why


# ═══ 5. scope ═══════════════════════════════════════════════════════════════

def test_a_fixture_outside_the_take_is_never_written(seam):
    from fx import device_output
    seam.host._scope = {"tv-backlight", "sconce-kitchen-left", "sconce-kitchen-right"}
    seam.set_mode()
    seam.hf.set_fixture("crystal", power="off")
    _run(_settle(seam.hf))
    written = {d for d, _ in seam.posts}
    assert "crystal" not in written and "porch-rail" not in written
    assert "crystal" not in device_output.withheld()
    assert written == {"tv-backlight", "sconce-kitchen-left", "sconce-kitchen-right"}


# ═══ 6. hand-back ═══════════════════════════════════════════════════════════

def test_clearing_the_mode_switches_back_on_what_we_switched_off(seam):
    from fx import device_output
    seam.set_mode()
    seam.hf.set_fixture("crystal", power="off")
    _run(_settle(seam.hf))
    seam.posts.clear()
    st = seam.store.state()
    st.mode_id = None
    seam.store.save_state()
    _run(_settle(seam.hf))
    assert seam.posts == [("crystal", {"on": True})]
    assert device_output.withheld() == {}
    assert "crystal" not in seam.hf._rt.applied


# ═══ 7. recheck ═════════════════════════════════════════════════════════════

def test_recheck_refinds_and_reapplies_when_the_sconce_answers(seam):
    async def scenario():
        seam.set_mode()
        await _settle(seam.hf)
        seam.posts.clear()
        seam.state["sconce-kitchen-left"].update({"on": True, "bri": 128})
        seam.reach["after"] = 2          # boots on the third ask
        res = seam.hf.recheck(["sconce-kitchen-left", "Sconce, Kitchen, Right",
                               "nope"])
        assert res["status"] == "rechecking"
        assert res["fixtures"] == ["sconce-kitchen-left", "sconce-kitchen-right"]
        assert res["unknown"][0]["fixture"] == "nope"
        while seam.hf._rt.recheck_tasks:
            await asyncio.gather(*seam.hf._rt.recheck_tasks.values())
        await _settle(seam.hf)
        return res
    _run(scenario())
    rc = seam.hf.status()["rechecks"]
    assert rc["sconce-kitchen-left"]["state"] == "found"
    assert "sconce-kitchen-left" in seam.relocated
    # its boot-preset brightness was put back to the owned one
    assert ("sconce-kitchen-left", {"on": True, "bri": 255}) in seam.posts
    assert seam.state["sconce-kitchen-left"]["bri"] == 255


def test_recheck_gives_up_after_its_window(seam):
    async def scenario():
        seam.set_mode()
        seam.reach["after"] = 10 ** 6
        seam.hf.recheck(["porch-rail"])
        task = seam.hf._rt.recheck_tasks["porch-rail"]
        # let it try a couple of times, then move the clock past the window
        for _ in range(5):
            await asyncio.sleep(0)
        seam.clock.now += seam.hf.RECHECK_WINDOW_S + 1
        await task
    _run(scenario())
    assert seam.hf.status()["rechecks"]["porch-rail"]["state"] == "not_found"


def test_recheck_outside_the_take_and_room_not_ours(seam):
    async def scenario():
        seam.host._scope = {"tv-backlight"}
        res = seam.hf.recheck(["sconce-kitchen-left"])
        assert res["outside_take"] == ["sconce-kitchen-left"]
        assert res["status"] == "nothing_to_recheck"
        seam.refusal[0] = "the room is released"
        res = seam.hf.recheck(["tv-backlight"])
        assert res["status"] == "skipped"
    _run(scenario())
    assert seam.reach["calls"] == 0


# ═══ 8. phase 3: a mode's "off" is no stream ════════════════════════════════

def test_a_modes_off_is_withheld_and_powered_down_softly(seam, monkeypatch):
    from fx import device_output
    seam.set_mode()
    _run(_settle(seam.hf))
    seam.posts.clear()
    monkeypatch.setattr(seam.house, "mode_off_devices",
                        lambda: {"porch-rail": "Night light"})
    _run(_settle(seam.hf))
    assert device_output.withheld().get("porch-rail") == "switched off"
    assert [p for d, p in seam.posts if d == "porch-rail"] == [
        {"bri": 1}, {"live": False}, {"on": False}]
    view = [f for f in seam.hf.status()["fixtures"] if f["device"] == "porch-rail"][0]
    assert view["why"] == "house mode 'Night light' has it off"
    # the next mode has it on again: soft power-on, then the stream
    seam.posts.clear()
    monkeypatch.setattr(seam.house, "mode_off_devices", lambda: {})
    _run(_settle(seam.hf))
    assert "porch-rail" not in device_output.withheld()
    assert [p for d, p in seam.posts if d == "porch-rail"] == [
        {"on": True, "bri": 1}, {"on": True, "bri": 255}]


def test_a_light_show_steady_hold_wins_over_a_modes_off(seam, monkeypatch):
    from fx import device_output
    from spectra.models.light_show import DeviceHold
    from spectra.services import show_store
    seam.set_mode()
    monkeypatch.setattr(seam.house, "mode_off_devices",
                        lambda: {"porch-rail": "Away"})
    show_store.state().holds["porch-rail"] = DeviceHold(
        device_id="porch-rail", state="steady", color=[255, 0, 0])
    try:
        _run(_settle(seam.hf))
        assert "porch-rail" not in device_output.withheld()
        show_store.state().holds["porch-rail"] = DeviceHold(
            device_id="porch-rail", state="dark")
        _run(_settle(seam.hf))
        assert device_output.withheld().get("porch-rail") == "switched off", \
            "a Dark hold shows nothing either — the off may stand"
    finally:
        show_store.state().holds.pop("porch-rail", None)


# ═══ 9. phase 3: mains off — no stream and no search ════════════════════════

def test_mains_off_is_recorded_whatever_the_room_and_acted_on_only_with_a_mode(seam):
    from fx import device_output
    res = seam.hf.set_mains(["sconce-kitchen-left", "Sconce, Kitchen, Right"], False)
    assert res["status"] == "recorded" and res["acting"] is False
    assert set(seam.store.state().mains_off) == {"sconce-kitchen-left",
                                                 "sconce-kitchen-right"}
    _run(_settle(seam.hf))
    assert device_output.withheld() == {}, "no mode: recorded, not acted on"
    assert seam.hf.mains_off_acting() == {}
    seam.set_mode()
    _run(_settle(seam.hf))
    wh = device_output.withheld()
    assert wh.get("sconce-kitchen-left") == "mains off"
    assert wh.get("sconce-kitchen-right") == "mains off"
    assert set(seam.hf.mains_off_acting()) == {"sconce-kitchen-left",
                                               "sconce-kitchen-right"}
    # nothing is written to a fixture with no power, not even a read
    assert all(d not in ("sconce-kitchen-left", "sconce-kitchen-right")
               for d, _ in seam.posts)


def test_a_mains_off_fixture_is_never_drift_checked(seam):
    seam.set_mode()
    seam.hf.set_mains(["sconce-kitchen-left"], False)
    _run(_settle(seam.hf))
    seam.posts.clear()
    seam.unreadable.add("sconce-kitchen-left")
    seam.clock.now += seam.hf.DRIFT_CHECK_S + 1
    _run(_settle(seam.hf))
    assert all(d != "sconce-kitchen-left" for d, _ in seam.posts)


def test_mains_on_clears_it_and_refinds_the_fixture(seam):
    from fx import device_output

    async def scenario():
        seam.set_mode()
        seam.hf.set_mains(["sconce-kitchen-left"], False)
        await _settle(seam.hf)
        assert "sconce-kitchen-left" in device_output.withheld()
        res = seam.hf.set_mains(["sconce-kitchen-left"], True)
        assert res["status"] == "recorded"
        assert res["recheck"]["status"] == "rechecking"
        while seam.hf._rt.recheck_tasks:
            await asyncio.gather(*list(seam.hf._rt.recheck_tasks.values()),
                                 return_exceptions=True)
        await _settle(seam.hf)
        assert "sconce-kitchen-left" not in device_output.withheld()
        assert seam.store.state().mains_off == {}
        assert ("sconce-kitchen-left", {"on": True, "bri": 255}) in seam.posts
    _run(scenario())


def test_a_recheck_says_the_mains_are_on_even_with_the_room_released(seam):
    seam.hf.set_mains(["sconce-kitchen-left"], False)
    seam.refusal[0] = "the room is released"
    res = seam.hf.recheck(["sconce-kitchen-left"])
    assert res["status"] == "skipped"
    assert seam.store.state().mains_off == {}, "the fact is recorded anyway"


def test_a_missed_mains_on_is_caught_by_the_knock(seam):
    from fx import device_output

    async def scenario():
        seam.set_mode()
        seam.reach["after"] = 10 ** 6          # silent while unpowered
        seam.hf.set_mains(["sconce-kitchen-left"], False)
        await _settle(seam.hf)
        seam.clock.now += seam.hf.MAINS_KNOCK_S - 1
        await _settle(seam.hf)
        assert seam.reach["calls"] == 0, "no knock before MAINS_KNOCK_S"
        seam.clock.now += 2
        await _settle(seam.hf)
        assert seam.reach["calls"] == 1, "one knock, never a search"
        assert "sconce-kitchen-left" in device_output.withheld()
        seam.reach["after"] = 0                # its mains came on, HA silent
        seam.clock.now += seam.hf.MAINS_KNOCK_S + 1
        await _settle(seam.hf)
        await _settle(seam.hf)
        assert seam.store.state().mains_off == {}
        assert "sconce-kitchen-left" not in device_output.withheld()
    _run(scenario())


def test_an_unknown_mains_fixture_is_named(seam):
    res = seam.hf.set_mains(["nope"], False)
    assert res["status"] == "invalid" and res["unknown"][0]["fixture"] == "nope"
    res = seam.hf.set_mains([], False)
    assert res["status"] == "invalid"


def test_an_already_off_fixture_is_never_dimmed_first(seam, monkeypatch):
    """A bare {"bri": 1} turns an OFF WLED on (its JSON API reads a
    brightness above zero as "on") — so the soft dim reads first and only
    dims a fixture that is on."""
    seam.set_mode()
    _run(_settle(seam.hf))
    seam.posts.clear()
    seam.state["porch-rail"]["on"] = False         # HA switched it off already
    monkeypatch.setattr(seam.house, "mode_off_devices",
                        lambda: {"porch-rail": "Away"})
    _run(_settle(seam.hf))
    writes = [p for d, p in seam.posts if d == "porch-rail"]
    assert {"bri": 1} not in writes
    assert writes == [{"live": False}, {"on": False}]


def test_a_restart_keeps_a_mode_off_fixture_withheld_from_the_first_pass(seam):
    """house_restart pre-installs the mode's switched-off WLEDs before the
    house layer's first pass: the fixtures half never switches them back on
    for the second before the mode is re-entered."""
    from fx import device_output
    seam.set_mode()
    seam.house.preinstall_off(["porch-rail"])
    assert seam.house.mode_off_devices() == {"porch-rail": "Standard"}
    _run(_settle(seam.hf))
    assert device_output.withheld().get("porch-rail") == "switched off"



# ═══ 10. phase 3: a release hands back what Spectra switched on ═════════════

def _release(seam):
    seam.refusal[0] = "the room is released"
    seam.released[0] = True


def test_a_fixture_that_was_off_before_the_take_is_off_after_the_release(seam):
    """2026-10-05: a take switched his dining-table under-glow on at full
    (owned brightness) and nothing switched it back off — River's restore
    does not capture it. Spectra remembers what it found before its first
    write and puts it back when the room is released."""
    seam.state["porch-rail"].update({"on": False, "bri": 40})
    seam.set_mode()
    _run(_settle(seam.hf))
    assert seam.state["porch-rail"]["on"] is True          # owned: on at 255
    before = seam.store.state().pre_take["porch-rail"]
    assert (before["on"], before["bri"]) == (False, 40)
    assert seam.store.state().pre_take["crystal"]["on"] is True
    _release(seam)

    async def release_pass():
        await seam.hf.tick()
        assert seam.hf._rt.handback_task is not None
        await seam.hf._rt.handback_task
    _run(release_pass())
    assert ("porch-rail", {"on": False, "bri": 40}) in seam.ip_posts
    assert seam.state["porch-rail"]["on"] is False
    assert seam.state["crystal"]["on"] is True and seam.state["crystal"]["bri"] == 34
    assert seam.store.state().pre_take == {}
    handed = seam.hf.status()["handed_back"]
    assert {h["device"] for h in handed} >= {"porch-rail", "crystal"}
    assert all(h["outcome"] == "landed" for h in handed)


def test_the_first_reading_wins_until_it_is_handed_back(seam):
    seam.state["porch-rail"].update({"on": False, "bri": 40})
    seam.set_mode()
    _run(_settle(seam.hf))
    seam.hf._rt.applied.clear()                    # a second pass re-writes
    _run(_settle(seam.hf))
    assert seam.store.state().pre_take["porch-rail"]["on"] is False


def test_a_restart_or_a_handover_hands_nothing_back(seam):
    """Only a RELEASE hands back: a restart keeps the picture, and a
    handover to the older SpotFX process needs the fixtures on."""
    seam.state["porch-rail"].update({"on": False, "bri": 40})
    seam.set_mode()
    _run(_settle(seam.hf))
    seam.refusal[0] = "SPECTRA's live light stack is not up"   # not released
    _run(_settle(seam.hf))
    assert seam.ip_posts == []
    assert "porch-rail" in seam.store.state().pre_take


def test_a_fixture_that_does_not_confirm_is_retried_then_dropped_and_named(seam):
    async def scenario():
        seam.state["porch-rail"].update({"on": False, "bri": 40})
        seam.set_mode()
        await _settle(seam.hf)
        seam.unreachable_ips.add("porch-rail")
        _release(seam)
        for _ in range(seam.hf.HANDBACK_ATTEMPTS + 1):
            await seam.hf.tick()
            if seam.hf._rt.handback_task:
                await seam.hf._rt.handback_task
        assert "porch-rail" not in seam.store.state().pre_take
        failed = [h for h in seam.hf.status()["handed_back"] if h["device"] == "porch-rail"]
        assert failed and failed[0]["outcome"] == "failed"
        assert len([p for d, p in seam.ip_posts if d == "porch-rail"]) == seam.hf.HANDBACK_ATTEMPTS
    _run(scenario())
