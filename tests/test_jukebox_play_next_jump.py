"""§4's "Play next may jump the set" (Program card, off by default): a song
played next — a guest's paid play next, or the host's Play next — plays
straight after the song playing, ahead of the next set song, instead of at
the next jukebox slot. It is an extra item that uses no slot, so the set's
rhythm around it is unchanged; it is priced by how far it actually jumps.
Driven through services/jukebox/program.py and the real runner over the fake
Spotify world (which models Spotify's own queue rule)."""
from __future__ import annotations

import asyncio

from models.jukebox import Cursor, SetItem
from services.jukebox import program
from tests.jukebox_world import jb_uri
from tests.test_jukebox_credits_play import _gift, _setup
from tests.test_jukebox_guest_add import _night, _phone


def _run(coro):
    return asyncio.run(coro)


SET = [SetItem(uri=f"s{i}", title=f"S{i}", duration_ms=300_000) for i in range(4)]


def _kinds(items):
    return [(i.kind, i.uri or "") for i in items]


def test_a_jump_fill_plays_ahead_of_the_next_set_song_and_uses_no_slot():
    from models.jukebox import ProgramConfig
    cfg = ProgramConfig(mode="auto", every=2, run=1)
    cur = program.on_set_start(cfg, SET, Cursor(), 0)          # S0 playing, no slot after it (every 2)
    assert cur.gap_left == 0
    plain = program.project(cfg, SET, cur, [program.Fill("a", "ja")], 4)
    assert _kinds(plain)[:3] == [("set", "s1"), ("jukebox", "ja"), ("set", "s2")]
    jumped = program.project(cfg, SET, cur, [program.Fill("a", "ja", jump=True),
                                             program.Fill("b", "jb")], 5)
    assert _kinds(jumped)[:4] == [("jukebox", "ja"), ("set", "s1"), ("jukebox", "jb"), ("set", "s2")]
    # the set's own slot after S1 is still there, for the next song in line


def test_a_jump_with_a_slot_already_open_simply_takes_it():
    from models.jukebox import ProgramConfig
    cfg = ProgramConfig(mode="auto", every=1, run=1)
    cur = program.on_set_start(cfg, SET, Cursor(), 0)          # a slot is open after S0
    jumped = program.project(cfg, SET, cur, [program.Fill("a", "ja", jump=True),
                                             program.Fill("b", "jb")], 4)
    assert _kinds(jumped)[:4] == [("jukebox", "ja"), ("set", "s1"), ("jukebox", "jb"), ("set", "s2")]


def test_a_guests_play_next_jumps_the_set_and_the_set_carries_on():
    async def go():
        # a slot after every 2nd set song: S0 · S1 · slot · S2 · S3 · slot ...
        w = await _night(set_s=300, jb_s=200, every=2, next_jumps_set=True)
        g = _setup(w)
        ana, ben = await _phone(g), await _phone(g)
        _gift(g, w, ana, 40)
        _gift(g, w, ben, 40)
        assert (await g.add(ana, jb_uri(0)))[0] == 200
        assert (await g.add(ben, jb_uri(1)))[0] == 200
        view = (await g.view(ben))[1]["view"]
        mine = next(s for s in view["next"] if s.get("entry_id") and s["mine"])
        q = mine["next"]
        assert q["allowed"], q
        code, out = await g.play_next(ben, mine["entry_id"], q["price"])
        assert code == 200, out
        ben_entry = next(e for e in w.runner.night.line if e.added_by == ben)
        assert ben_entry.jump and ben_entry.nexted
        first = w.runner.status()["next"][0]
        assert first["kind"] == "jukebox" and first["entry_id"] == ben_entry.id     # ahead of S1
        for _ in range(900):
            await w.run(1)
            if len(w.played()) >= 4:
                break
        assert w.played()[:4] == ["S0", "J1", "S1", "J0"], w.played()              # S1's slot still Ana's
    _run(go())


def test_the_jump_is_priced_by_how_far_it_really_jumps():
    async def go():
        w = await _night(set_s=300, jb_s=200, every=2)
        g = _setup(w)
        ana, ben = await _phone(g), await _phone(g)
        _gift(g, w, ana, 40)
        _gift(g, w, ben, 40)
        await g.add(ana, jb_uri(0))
        await g.add(ben, jb_uri(1))

        async def quote() -> dict:
            view = (await g.view(ben))[1]["view"]
            return next(s for s in view["next"] if s.get("entry_id") and s["mine"])["next"]
        plain = await quote()
        w.runner.cfg = w.runner.cfg.model_copy(update={"next_jumps_set": True})
        far = await quote()
        assert far["jump_min"] > plain["jump_min"] and far["price"] >= plain["price"]
        # it jumps from where it waits to the very next song to start (the quote rounds to 0.1 min)
        assert abs(far["jump_min"] - (ben_eta(w, ben) - w.runner.guest_state()["next"][0].starts_in_ms)
                   / 60_000) < 0.06
    _run(go())


def ben_eta(w, ben) -> int:
    e = next(e for e in w.runner.night.line if e.added_by == ben)
    return w.runner._starts_in(e.id)


def test_the_front_song_can_jump_but_a_song_already_next_cannot():
    async def go():
        w = await _night(set_s=900, jb_s=200, every=2, next_jumps_set=True)
        g = _setup(w)
        ana = await _phone(g)
        _gift(g, w, ana, 40)
        await g.add(ana, jb_uri(0))                           # first in line, but S1 plays first
        entry = next(e for e in w.runner.night.line if e.added_by == ana)
        view = (await g.view(ana))[1]["view"]
        mine = next(s for s in view["next"] if s.get("entry_id") == entry.id)
        code, out = await g.play_next(ana, entry.id, mine["next"]["price"])
        assert code == 200, out
        assert w.runner.status()["next"][0]["entry_id"] == entry.id
        assert (await w.runner.play_next(entry.id))["reason"] in ("nexted", "at_front_next")
    _run(go())


def test_the_hosts_play_next_jumps_and_a_drag_drops_the_jump():
    async def go():
        w = await _night(set_s=300, jb_s=200, every=2, next_jumps_set=True)
        await w.add(0)
        await w.add(1)
        e1 = next(e for e in w.runner.night.line if e.uri == jb_uri(1))
        out = await w.runner.move(e1.id, 0, play_next=True)
        assert out["status"] == "moved" and e1.jump
        assert w.runner.status()["next"][0]["entry_id"] == e1.id
        await w.runner.move(e1.id, 1)                          # dragged down again
        assert not e1.jump and w.runner.status()["next"][0]["kind"] == "set"
    _run(go())


def test_off_by_default_play_next_waits_for_the_slot():
    async def go():
        w = await _night(set_s=300, jb_s=200, every=2)
        assert w.runner.cfg.next_jumps_set is False
        await w.add(0)
        await w.add(1)
        e1 = next(e for e in w.runner.night.line if e.uri == jb_uri(1))
        await w.runner.move(e1.id, 0, play_next=True)
        assert not e1.jump and w.runner.status()["next"][0]["kind"] == "set"
    _run(go())
