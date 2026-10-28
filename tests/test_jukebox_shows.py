"""His saved shows (the plan's §4: "a 'show' is a saved set of these", the
Show card's "Name"; services/jukebox/shows.py): everything §4 lists — the
show settings, the program and the guest link — saved under a name and
loaded back whole, through the same steps a page edit takes."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.jukebox import ProgramConfig, ShowConfig
from routers import jukebox_router
from services.jukebox import night as night_mod, shows, store
from tests.jukebox_world import PLAYLIST_URI, World


def _show(**kw) -> ShowConfig:
    return ShowConfig(**kw)


def test_a_show_saves_under_its_name_and_replaces_one_of_the_same_name():
    name, replaced = shows.save("  Big   night ", _show(play_mode="free"), ProgramConfig(every=3), True, 10)
    assert (name, replaced) == ("Big night", False)
    name, replaced = shows.save("big NIGHT", _show(play_mode="credits"), ProgramConfig(every=2), False, 20)
    assert replaced and name == "big NIGHT"
    rows = shows.listing()
    assert [r["name"] for r in rows] == ["big NIGHT"] and rows[0]["play_mode"] == "credits"
    key, saved = shows.get("BIG night")
    assert key == "big NIGHT" and saved.program.every == 2 and saved.show.name == "big NIGHT"
    assert shows.delete("big night") == "big NIGHT" and shows.listing() == []


def test_names_and_the_cap_are_refused_by_name():
    for bad in ("", "   ", "x" * 61, None):
        with pytest.raises(shows.ShowsError) as err:
            shows.save(bad, _show(), ProgramConfig(), False, 1)
        assert err.value.code == "bad_name"
    for i in range(shows.SHOWS_MAX):
        shows.save(f"Show {i}", _show(), ProgramConfig(), False, i)
    with pytest.raises(shows.ShowsError) as err:
        shows.save("One too many", _show(), ProgramConfig(), False, 99)
    assert err.value.code == "too_many"
    shows.save("Show 3", _show(), ProgramConfig(), False, 100)          # replacing still works at the cap
    with pytest.raises(shows.ShowsError) as err:
        shows.get("No such show")
    assert err.value.code == "no_show"


def test_an_unreadable_shows_file_is_never_written_over():
    store.SHOWS_FILE.write_text("{ not json", encoding="utf-8")
    for call in (shows.listing, lambda: shows.save("A", _show(), ProgramConfig(), False, 1),
                 lambda: shows.delete("A")):
        with pytest.raises(ValueError):
            call()
    assert store.SHOWS_FILE.read_text(encoding="utf-8") == "{ not json"


# ═══ the routes ═════════════════════════════════════════════════════════════

@pytest.fixture
def app(monkeypatch):
    w = World()
    w.deps.load_config = store.load_config
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    a = FastAPI()
    a.include_router(jukebox_router.router)
    with TestClient(a) as c:
        yield c, w


def test_save_keeps_what_is_in_force_and_load_puts_it_back_whole(app):
    c, w = app
    store.save_config(ProgramConfig(playlist=PLAYLIST_URI, every=3, run_out="end", next_jumps_set=True))
    assert c.put("/api/jukebox/show", json={"play_mode": "free", "last_call_min": 30}).status_code == 200
    assert c.put("/api/jukebox/guest-link", json={"enabled": True}).status_code == 200
    r = c.post("/api/jukebox/shows", json={"name": "Garden party"})
    assert r.status_code == 200 and r.json()["name"] == "Garden party" and not r.json()["replaced"]
    assert c.get("/api/jukebox/show").json()["show"]["name"] == "Garden party"
    # everything changes, then the show comes back whole
    store.save_config(ProgramConfig(playlist=PLAYLIST_URI, every=1))
    c.put("/api/jukebox/show", json={"play_mode": "credits", "last_call_min": 5, "name": "Other"})
    c.put("/api/jukebox/guest-link", json={"enabled": False})
    r = c.post("/api/jukebox/shows/load", json={"name": "garden PARTY"})
    assert r.status_code == 200 and r.json()["status"] == "loaded" and r.json()["guest_link"] is True
    cfg, show = store.load_config(), store.load_show()
    assert (cfg.every, cfg.run_out, cfg.next_jumps_set) == (3, "end", True)
    assert (show.play_mode, show.last_call_min, show.name) == ("free", 30, "Garden party")
    assert store.load_guest_link()[0].enabled is True
    listed = c.get("/api/jukebox/shows").json()
    assert [s["name"] for s in listed["shows"]] == ["Garden party"] and listed["current"] == "Garden party"
    assert c.delete("/api/jukebox/shows/Garden%20party").json()["shows"] == []
    assert c.delete("/api/jukebox/shows/Garden%20party").status_code == 404
    assert c.post("/api/jukebox/shows/load", json={"name": "Garden party"}).status_code == 404


def test_a_running_night_refuses_a_show_with_another_set_playlist(app):
    c, w = app
    store.save_config(ProgramConfig(playlist="spotify:playlist:another", every=3))
    c.post("/api/jukebox/shows", json={"name": "Other set"})
    store.save_config(ProgramConfig(playlist=PLAYLIST_URI, every=1))
    c.post("/api/jukebox/shows", json={"name": "Same set"})
    store.save_config(ProgramConfig(playlist=w.cfg.playlist))
    assert c.post("/api/jukebox/night/start", json={}).json()["status"] == "running"
    before = (store.load_config(), store.load_show())
    r = c.post("/api/jukebox/shows/load", json={"name": "Other set"})
    assert r.status_code == 409 and r.json()["reason"] == "playlist_locked"
    assert (store.load_config(), store.load_show()) == before          # nothing changed
    r = c.post("/api/jukebox/shows/load", json={"name": "Same set"})
    assert r.status_code == 200 and store.load_config().every == 1


def test_the_shows_name_is_a_show_setting(app):
    c, _ = app
    assert c.put("/api/jukebox/show", json={"name": "Movie night"}).json()["show"]["name"] == "Movie night"
    assert c.put("/api/jukebox/show", json={"name": ""}).status_code == 422
    assert c.post("/api/jukebox/shows", json={"name": "  "}).status_code == 422


def test_a_load_can_leave_the_guest_link_as_it_is(app):
    c, _ = app
    store.save_config(ProgramConfig(playlist=PLAYLIST_URI, every=2))
    assert c.put("/api/jukebox/guest-link", json={"enabled": True}).status_code == 200
    c.post("/api/jukebox/shows", json={"name": "Link on"})
    assert c.put("/api/jukebox/guest-link", json={"enabled": False}).status_code == 200
    r = c.post("/api/jukebox/shows/load", json={"name": "Link on", "guest_link": False})
    assert r.status_code == 200 and r.json()["guest_link"] is False and r.json()["guest_link_kept"]
    assert store.load_guest_link()[0].enabled is False
    r = c.post("/api/jukebox/shows/load", json={"name": "Link on"})       # the page's load: whole
    assert r.json()["guest_link"] is True and store.load_guest_link()[0].enabled is True
