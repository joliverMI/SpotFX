"""The Jukebox's guest link (services/jukebox/guest_link.py, N1 of
data/jukebox-plan/report.md §8.3): the guests' public HTTPS link through
Tailscale Funnel, on only during a night, forwarding only to the guest app.

No test runs `tailscale` (conftest replaces the command runner with one that
fails loudly). Everything here drives a FAKE Tailscale that keeps a Funnel
serve-config in memory — his own tailnet-only `tailscale serve` (:443 → the
master) included, so "never touches his Serve" is checked, not assumed.

Held: the link SHIPS OFF and a whole night with it off runs nothing; the
model refuses a guest port of :8000/:8010; when on, a night's start opens one
port to the guest app and its end closes it and rotates the token; a public
port Serve already uses is refused; a read-back that shows the master
published closes it again; switching it off mid-night closes it at once; a
Funnel left open by a crash is closed by the supervised check; the
self-test reads only the plan while closed and the real status plus the
public address while live."""
from __future__ import annotations

import asyncio
import copy
import subprocess
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.jukebox import GuestLinkConfig, GuestLinkState
from routers import jukebox_router
from services.jukebox import guest_link as gl
from services.jukebox import night as night_mod, store
from tests.jukebox_world import World

HOST = "serenity.tailtest.ts.net"


def _run(coro):
    return asyncio.run(coro)


class FakeTailscale:
    """`tailscale funnel` and `tailscale status` over an in-memory serve
    config. His own Serve (tailnet-only, not funneled) is on :443 → :8000."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.conf = {"TCP": {"443": {"HTTPS": True}},
                     "Web": {f"{HOST}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}},
                     "AllowFunnel": {}}
        self.fail: dict[str, tuple[int, str, str]] = {}
        self.also_publish: dict | None = None      # something extra the read-back shows

    def run(self, argv, timeout):
        self.calls.append(list(argv))
        key = " ".join(argv[1:3])
        if key in self.fail:
            return self.fail[key]
        if argv[1:] == ["status", "--json"]:
            return 0, json.dumps({"Self": {"DNSName": HOST + "."}}), ""
        if argv[1:] == ["funnel", "status", "--json"]:
            conf = copy.deepcopy(self.conf)
            if self.also_publish:
                for k, v in self.also_publish.items():
                    conf.setdefault(k, {}).update(v)
            return 0, json.dumps(conf), ""
        if argv[1] == "funnel" and argv[-1] == "off":
            port = argv[2].split("=")[1]
            self.conf["TCP"].pop(port, None)
            self.conf["Web"].pop(f"{HOST}:{port}", None)
            self.conf["AllowFunnel"].pop(f"{HOST}:{port}", None)
            return 0, "", ""
        if argv[1] == "funnel" and "--bg" in argv:
            port = next(a for a in argv if a.startswith("--https=")).split("=")[1]
            self.conf["TCP"][port] = {"HTTPS": True}
            self.conf["Web"][f"{HOST}:{port}"] = {"Handlers": {"/": {"Proxy": argv[-1]}}}
            self.conf["AllowFunnel"][f"{HOST}:{port}"] = True
            return 0, "", ""
        return 1, "", f"unexpected {argv}"

    def published(self) -> list[str]:
        return sorted(k for k, on in self.conf["AllowFunnel"].items() if on)


async def _inline(fn, *a, **k):
    return fn(*a, **k)


@pytest.fixture
def ts():
    return FakeTailscale()


@pytest.fixture
def world(ts, monkeypatch):
    """A fake night (tests/jukebox_world.py) wired to a guest link that
    runs the fake Tailscale."""
    w = World()
    link = gl.GuestLink(gl.GuestLinkDeps(
        run=ts.run, to_thread=_inline, now_ms=lambda: int(w.clock.t * 1000),
        night_running=lambda: w.runner.running, probe=lambda url, timeout: 404))
    w.deps.guest_link_start = link.on_night_start
    w.deps.guest_link_end = link.on_night_end
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(gl, "controller", link)
    w.link, w.ts = link, ts
    return w


def _enable(**kw):
    cfg, st = store.load_guest_link()
    store.save_guest_link(GuestLinkConfig(**{**cfg.model_dump(), "enabled": True, **kw}), st)


# ═══ 1. it ships off, and off means nothing runs ═════════════════════════════

def test_the_link_ships_off():
    cfg, st = store.load_guest_link()
    assert cfg.enabled is False and not st.funnel_open
    assert gl.controller.status()["state"] == "off"


def test_a_whole_night_with_the_link_off_never_runs_tailscale(world):
    assert _run(world.runner.start())["status"] == "running"
    _run(world.runner.stop())
    assert world.ts.calls == []
    assert not any("guest link" in line for line in world.runner.night.log)


def test_production_wires_the_night_to_the_guest_link(monkeypatch):
    seen = []

    class Rec:
        async def on_night_start(self, nid):
            seen.append(("start", nid))

        async def on_night_end(self, nid):
            seen.append(("end", nid))
    monkeypatch.setattr(gl, "controller", Rec())
    monkeypatch.setattr(night_mod, "default_gateway", lambda: object())
    d = night_mod.production_deps()
    _run(d.guest_link_start("n1"))
    _run(d.guest_link_end("n1"))
    assert seen == [("start", "n1"), ("end", "n1")]


# ═══ 2. the rules no setting can break ══════════════════════════════════════

@pytest.mark.parametrize("bad", [{"guest_port": 8000}, {"guest_port": 8010}, {"public_port": 8080},
                                 {"public_host": "https://serenity.x.ts.net"}, {"nonsense": 1}])
def test_the_settings_refuse_what_would_publish_the_master(bad):
    with pytest.raises(ValueError):
        gl.apply_patch(GuestLinkConfig(), bad)


def test_the_commands_name_one_port_and_a_loopback_target():
    cfg = GuestLinkConfig()
    assert gl.open_argv(cfg) == ["tailscale", "funnel", "--bg", "--https=8443", "http://127.0.0.1:8020"]
    assert gl.close_argv(cfg) == ["tailscale", "funnel", "--https=8443", "off"]
    assert all(c["ok"] for c in gl.judge_config(cfg))


def test_the_token_and_the_link():
    st = GuestLinkState(token="abc")
    assert gl.token_matches("abc", st) and not gl.token_matches("abd", st)
    assert not gl.token_matches(None, st) and not gl.token_matches("", GuestLinkState())
    assert gl.link_for(HOST, 8443, "abc") == f"https://{HOST}:8443/?t=abc"
    assert gl.link_for(HOST, 443, "abc") == f"https://{HOST}/?t=abc"
    assert gl.link_for("", 8443, "abc") is None


# ═══ 3. on: open with the night, close with it ═══════════════════════════════

def test_a_night_opens_one_port_to_the_guest_app_and_closes_it(world):
    _enable()
    his_serve = copy.deepcopy(world.ts.conf["Web"][f"{HOST}:443"])
    _run(world.runner.start())
    assert world.ts.published() == [f"{HOST}:8443"]
    s = gl.controller.status()
    assert s["state"] == "live" and s["link"].startswith(f"https://{HOST}:8443/?t=")
    token = store.load_guest_link()[1].token
    assert any("guest link live" in line for line in world.runner.night.log)
    assert not world.runner.night.warnings
    _run(world.runner.stop())
    assert world.ts.published() == []
    assert world.ts.conf["Web"][f"{HOST}:443"] == his_serve          # his Serve untouched
    _, st = store.load_guest_link()
    assert not st.funnel_open and st.token and st.token != token     # the next party's token
    assert gl.controller.status()["state"] == "armed"


def test_the_host_comes_from_tailscale_when_not_set(world):
    _enable()
    _run(world.runner.start())
    assert store.load_guest_link()[1].host == HOST
    assert ["tailscale", "status", "--json"] in world.ts.calls


def test_a_public_port_his_serve_uses_is_refused(world):
    _enable(public_port=443)
    _run(world.runner.start())
    assert world.runner.running                                     # the night plays on
    assert world.ts.published() == []
    assert not any(c[-1] == "http://127.0.0.1:8020" for c in world.ts.calls)
    assert any("already used" in w for w in world.runner.night.warnings)
    assert gl.controller.status()["state"] == "error"


def test_an_open_that_fails_is_a_warning_on_a_night_that_plays_on(world):
    _enable()
    world.ts.fail["funnel --bg"] = (1, "", "Funnel is not enabled on your tailnet")
    _run(world.runner.start())
    assert world.runner.running and not store.load_guest_link()[1].funnel_open
    assert any("not enabled on your tailnet" in w for w in world.runner.night.warnings)


def test_a_read_back_that_shows_the_master_published_closes_it_again(world):
    _enable()
    world.ts.also_publish = {"AllowFunnel": {f"{HOST}:443": True}}   # his :8000 on the internet
    _run(world.runner.start())
    assert not store.load_guest_link()[1].funnel_open
    assert ["tailscale", "funnel", "--https=8443", "off"] in world.ts.calls
    assert world.runner.night.warnings


def test_switching_it_off_mid_night_closes_it_at_once(world):
    _enable()
    _run(world.runner.start())
    assert world.ts.published() == [f"{HOST}:8443"]
    _run(gl.controller.edit({"enabled": False}))
    assert world.ts.published() == [] and world.runner.running


def test_a_live_links_ports_cant_change(world):
    _enable()
    _run(world.runner.start())
    with pytest.raises(ValueError):
        _run(gl.controller.edit({"guest_port": 8030}))
    assert store.load_guest_link()[0].guest_port == 8020


def test_a_funnel_left_open_with_no_night_is_closed(world):
    _enable()
    _run(world.runner.start())
    world.runner.night.state = "ended"                              # a crash: no _end ran
    assert not world.runner.running
    assert "closed" in _run(world.link.reconcile())
    assert world.ts.published() == [] and not store.load_guest_link()[1].funnel_open


def test_reconcile_leaves_a_live_night_alone(world):
    _enable()
    _run(world.runner.start())
    n = len(world.ts.calls)
    assert _run(world.link.reconcile()) is None and len(world.ts.calls) == n


def test_a_close_that_fails_stays_marked_open_and_is_retried(world):
    _enable()
    _run(world.runner.start())
    world.ts.fail["funnel --https=8443"] = (1, "", "boom")
    _run(world.runner.stop())
    assert store.load_guest_link()[1].funnel_open
    del world.ts.fail["funnel --https=8443"]
    _run(world.link.reconcile())
    assert not store.load_guest_link()[1].funnel_open and world.ts.published() == []


def test_an_open_that_times_out_after_publishing_is_taken_down(world):
    """`tailscale funnel --bg` published the port and then never answered:
    the link must not be left on the internet with no marker to close it."""
    _enable()
    real = world.ts.run

    def slow(argv, timeout):
        out = real(argv, timeout)
        if "--bg" in argv:
            raise subprocess.TimeoutExpired(argv, timeout)
        return out
    world.link.deps.run = slow
    _run(world.runner.start())
    assert world.runner.running
    assert world.ts.published() == []                               # taken down again
    _, st = store.load_guest_link()
    assert not st.funnel_open and st.last_action.what == "open" and not st.last_action.ok
    assert any("didn't open" in w for w in world.runner.night.warnings)


def test_a_crash_right_after_the_open_command_leaves_it_marked_open_and_restart_closes_it(world):
    """The durable record must be written BEFORE the real `tailscale funnel
    --bg` call, not after its own read-back check, so a crash in that
    window still leaves `funnel_open` true on disk — and a restarted
    process (a fresh GuestLink reading only the store) can close the real
    Funnel it left behind."""
    _enable()
    seen = {}

    def run(argv, timeout):
        rc, out, err = world.ts.run(argv, timeout)
        if argv[1] == "funnel" and "--bg" in argv:
            seen["persisted_before_readback"] = store.load_guest_link()[1].funnel_open
        return rc, out, err
    world.link.deps.run = run

    _run(world.runner.start())
    assert seen["persisted_before_readback"] is True
    assert world.ts.published() == [f"{HOST}:8443"]

    restarted = gl.GuestLink(gl.GuestLinkDeps(
        run=world.ts.run, to_thread=_inline, now_ms=lambda: int(world.clock.t * 1000),
        night_running=lambda: False, probe=lambda url, timeout: 404))
    assert "closed" in _run(restarted.reconcile())
    assert not store.load_guest_link()[1].funnel_open and world.ts.published() == []


def test_a_stale_open_marker_with_nothing_published_is_cleared_not_retried_forever(world):
    """A marker left `funnel_open=True` by a crash before anything was ever
    actually published must self-heal even when its own close command
    fails — never stay stuck retrying a close against a Funnel that isn't
    there."""
    _enable()
    cfg, st = store.load_guest_link()
    st.funnel_open, st.opened_ms, st.opened_for_night, st.host = (
        True, int(world.clock.t * 1000), "n0", HOST)
    store.save_guest_link(cfg, st)
    assert world.ts.published() == []                               # nothing was ever opened

    world.ts.fail["funnel --https=8443"] = (1, "", "no such funnel")
    said = _run(world.link.reconcile())
    assert said is not None and "closed" in said
    assert not store.load_guest_link()[1].funnel_open

    calls_before = len(world.ts.calls)
    assert _run(world.link.reconcile()) is None
    assert len(world.ts.calls) == calls_before                      # never retried again


def test_the_token_rotates_only_between_nights(world):
    _enable()
    first = _run(world.link.rotate())
    assert first["status"] == "rotated"
    _run(world.runner.start())
    r = _run(world.link.rotate())
    assert r["status"] == "refused" and r["reason"] == "night_running"


# ═══ 4. the self-test ═══════════════════════════════════════════════════════

def test_the_self_test_reads_only_the_plan_while_closed(world):
    r = _run(world.link.self_test())
    assert r["mode"] == "planned" and r["ok"] and world.ts.calls == []


def test_the_self_test_reads_funnel_and_asks_the_public_address_while_live(world, monkeypatch):
    _enable()
    _run(world.runner.start())
    asked = []

    def probe(url, timeout):
        asked.append(url)
        return 404
    world.link.deps.probe = probe
    r = _run(world.link.self_test())
    assert r["mode"] == "live" and r["ok"], r
    assert {u.split(":8443", 1)[1] for u in asked} == set(gl.PROBE_PATHS)
    world.link.deps.probe = lambda url, timeout: 200 if url.endswith("/api/jukebox/status") else 404
    bad = _run(world.link.self_test())
    assert not bad["ok"] and any("ANSWERED: /api/jukebox/status" in c["detail"] for c in bad["checks"])


@pytest.mark.parametrize("extra, why", [
    ({"AllowFunnel": {f"{HOST}:443": True}}, "the master's :443 also on the internet"),
    ({"Web": {f"{HOST}:8443": {"Handlers": {"/admin": {"Proxy": "http://127.0.0.1:8010"}}}}}, "a path to SPECTRA"),
])
def test_the_status_judgement_catches_the_master_published(extra, why):
    conf = {"Web": {f"{HOST}:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8020"}}}},
            "AllowFunnel": {f"{HOST}:8443": True}}
    assert all(c["ok"] for c in gl.judge_status(conf, GuestLinkConfig()))
    for k, v in extra.items():
        for kk, vv in v.items():
            if isinstance(vv, dict) and kk in conf.get(k, {}):
                conf[k][kk]["Handlers"].update(vv["Handlers"])
            else:
                conf.setdefault(k, {})[kk] = vv
    assert not all(c["ok"] for c in gl.judge_status(conf, GuestLinkConfig())), why


# ═══ 5. the routes ══════════════════════════════════════════════════════════

def test_the_routes(world):
    app = FastAPI()
    app.include_router(jukebox_router.router)
    with TestClient(app) as c:
        assert c.get("/api/jukebox/guest-link").json()["state"] == "off"
        r = c.put("/api/jukebox/guest-link?dry_run=true", json={"enabled": True})
        assert r.json()["dry_run"] and not store.load_guest_link()[0].enabled
        assert c.put("/api/jukebox/guest-link", json={"guest_port": 8000}).status_code == 422
        assert c.put("/api/jukebox/guest-link", json={"funnel": True}).status_code == 422
        r = c.put("/api/jukebox/guest-link", json={"enabled": True, "public_host": HOST})
        assert r.status_code == 200 and r.json()["state"] == "armed"
        assert c.post("/api/jukebox/guest-link/rotate").json()["status"] == "rotated"
        assert c.post("/api/jukebox/guest-link/self-test").json()["mode"] == "planned"
        assert world.ts.calls == []
