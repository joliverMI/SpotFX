"""The Jukebox API (routers/jukebox_router.py) over the fake world, the dry
run (scripts/jukebox_dry_run.py), and the two cross-checks with the rest of
SpotFX: Absorb's production gate sees a running night, and main.py wires
the engine's poll hook without waiting on it."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import jukebox_router
from services.jukebox import night as night_mod, store
from tests.jukebox_world import PLAYLIST_URI, World, jb_uri


@pytest.fixture
def api(monkeypatch):
    w = World()
    w.deps.load_config = store.load_config
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    app = FastAPI()
    app.include_router(jukebox_router.router)
    with TestClient(app) as client:
        yield w, client


def test_config_is_a_partial_update_validated_whole(api):
    _, c = api
    assert c.get("/api/jukebox/config").json()["mode"] == "auto"
    r = c.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI, "every": 3})
    assert r.status_code == 200 and r.json()["config"]["every"] == 3
    r = c.put("/api/jukebox/config", json={"run": 2})
    cfg = r.json()["config"]
    assert (cfg["every"], cfg["run"], cfg["playlist"]) == (3, 2, PLAYLIST_URI)
    assert store.load_config().run == 2


@pytest.mark.parametrize("patch, word", [
    ({"nonsense": 1}, "unknown"),
    ({"every": 9}, "every"),
    ({"run_out": "forever"}, "run_out"),
    ({"commit_lead_s": 5}, "commit_lead_s"),
    ({"manual": [{"after_uri": "not-a-uri"}]}, "manual"),
])
def test_a_bad_edit_is_a_422_naming_it_and_writes_nothing(api, patch, word):
    _, c = api
    r = c.put("/api/jukebox/config", json=patch)
    assert r.status_code == 422 and word in r.json()["detail"]
    assert not store.CONFIG_FILE.exists()


def test_dry_run_validates_and_writes_nothing(api):
    _, c = api
    r = c.put("/api/jukebox/config?dry_run=true", json={"every": 2})
    assert r.json()["dry_run"] is True and r.json()["config"]["every"] == 2
    assert not store.CONFIG_FILE.exists()


def test_a_night_from_start_to_stop(api):
    w, c = api
    c.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI})
    r = c.post("/api/jukebox/night/start", json={})
    assert r.json()["status"] == "running"
    r = c.post("/api/jukebox/line", json={"uri": jb_uri(0)})
    assert r.json()["status"] == "added"
    r = c.post("/api/jukebox/line", json={"uri": "a playlist"})
    assert r.json()["reason"] == "not_a_track"
    s = c.get("/api/jukebox/status").json()
    assert s["running"] and [e["title"] for e in s["line"]] == ["J0"]
    # no step has observed S0 starting yet, so the program still reads from S0
    assert [i["title"] for i in s["next"][:2]] == ["S0", "J0"]
    # the set can't be swapped under a running night
    r = c.put("/api/jukebox/config", json={"playlist": "spotify:playlist:other"})
    assert r.status_code == 409
    # the slot rule can, from the next set song
    assert c.put("/api/jukebox/config", json={"every": 2}).status_code == 200
    assert w.runner.cfg.every == 2
    entry = s["line"][0]["id"]
    assert c.post(f"/api/jukebox/line/{entry}/move", json={"to": 0}).json()["status"] == "moved"
    assert c.delete(f"/api/jukebox/line/{entry}").json()["status"] == "removed"
    assert c.post("/api/jukebox/night/stop", json={}).json()["status"] == "ended"
    assert c.get("/api/jukebox/status").json()["running"] is False


def test_a_refused_start_answers_200_with_its_reason(api):
    _, c = api
    r = c.post("/api/jukebox/night/start", json={})
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["reason"]) == ("refused", "no_playlist")


def test_preview_reads_the_set_and_changes_nothing(api):
    w, c = api
    c.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI, "every": 2})
    r = c.get("/api/jukebox/preview?count=5").json()
    assert r["status"] == "ok" and r["set_songs"] == 12
    assert [i["kind"] for i in r["next"]] == ["set", "set", "open", "set", "set"]
    writes = {"add_to_queue", "start_context", "set_shuffle", "set_repeat", "pause",
              "next_track"}
    assert not writes & set(w.gw.names())


# ── the dry run ─────────────────────────────────────────────────────────────

def _fixture(tmp_path, n=8):
    rows = [{"uri": f"spotify:track:set{i:03d}aaaaaaaaaaaaaa", "title": f"Song {i}",
             "artist": "Band", "duration_ms": 180_000} for i in range(n)]
    path = tmp_path / "set.json"
    path.write_text(json.dumps(rows))
    return path


def test_the_dry_run_prints_the_next_20_items(tmp_path, capsys):
    from scripts import jukebox_dry_run
    assert jukebox_dry_run.main(["--fixture", str(_fixture(tmp_path)), "--line", "2"]) == 0
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if ln[:3].strip().isdigit()]
    assert len(rows) == 20
    assert "SET   1  Band — Song 0" in rows[0]
    assert "(jukebox song 1)" in rows[1] and "(jukebox song 2)" in rows[3]
    assert "open slot" in rows[5]
    assert "3:00" in rows[1]


def test_the_dry_run_ends_where_the_program_does(tmp_path, capsys):
    from scripts import jukebox_dry_run
    jukebox_dry_run.main(["--fixture", str(_fixture(tmp_path, 2)), "--run-out", "end",
                          "--line", "5"])
    out = capsys.readouterr().out
    assert "the program ends here" in out
    assert "One pass through the set: 2 set songs" in out


def test_the_dry_run_against_spotify_uses_only_reads(tmp_path, capsys, monkeypatch):
    """--playlist reads through the ReadOnlyGateway: a write would raise."""
    from scripts import jukebox_dry_run
    from services.jukebox import gateway

    class Sp:
        def playlist(self, pid, fields=None):
            return {"id": pid, "name": "His set", "uri": f"spotify:playlist:{pid}"}

        def playlist_items(self, pid, **kw):
            return {"items": [{"track": {"uri": f"spotify:track:t{i:019d}", "name": f"T{i}",
                                         "duration_ms": 200_000, "artists": []}}
                              for i in range(3)], "next": None}
    real = gateway.JukeboxGateway
    monkeypatch.setattr(gateway, "JukeboxGateway",
                        lambda: real(Sp(), sleep=lambda s: None))
    assert jukebox_dry_run.main(["--playlist", "spotify:playlist:abcdefghijklmnop1234",
                                 "--count", "4"]) == 0
    out = capsys.readouterr().out
    assert "Set: His set — 3 songs" in out


# ── the rest of SpotFX ──────────────────────────────────────────────────────

def test_absorbs_production_gate_sees_a_running_night(monkeypatch):
    from services import absorb
    w = World()
    monkeypatch.setattr(night_mod, "runner", w.runner)
    assert absorb._jukebox_night() is False
    import asyncio
    asyncio.run(w.start())
    assert absorb._jukebox_night() is True


def test_the_poll_hook_never_awaits_spotify():
    """main.py calls `on_track_state` synchronously from the poll: it only
    wakes the engine's own task, and never raises."""
    import inspect
    r = night_mod.JukeboxRunner(World().deps)
    assert not inspect.iscoroutinefunction(r.on_track_state)
    r.on_track_state(object())          # no night: nothing happens
    r.night = None
    assert r.on_track_state(None) is None


def test_main_wires_the_engine():
    import main
    src = open(main.__file__, encoding="utf-8").read()
    assert "jukebox.runner.on_track_state(track)" in src
    assert "jukebox.runner.recover()" in src
    assert "jukebox.runner.run_supervised()" in src
    assert any(getattr(r, "path", "").startswith("/api/jukebox") for r in main.app.routes) \
        or "app.include_router(jukebox_router.router)" in src
