"""Free play's rules (services/jukebox/guests.py and night.py, the plan's
§6 and PR 2.3): the room's skip (3 ▼ and two-thirds of the votes, never in a
song's first seconds), bumps by count (your own song up, someone else's down,
2 an hour, a song pushed back at most 3 places, nothing passes the song sent
to Spotify), and the jail as a time-out (a guest whose songs reach the net ▼
bar sits out 5 songs; the count starts again after; the host pardons).
Driven over the fake Jukebox world (tests/jukebox_world.py), so what these
tests check is what the engine actually plays."""
from __future__ import annotations

import asyncio
import random

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jukebox_guest import key as guest_key
from models.jukebox import EconomyConfig, ShowConfig
from routers import jukebox_guest_router, jukebox_router
from services.jukebox import economy, guests as G, night as night_mod, show as show_mod, store
from tests.jukebox_world import World, jb_uri, set_uri
from tests.test_jukebox_guest_add import TOKEN, Catalog, Lib, _inline, _night, _phone


def _run(coro):
    return asyncio.run(coro)


def _show(**kw) -> ShowConfig:
    eco = kw.pop("economy", {})
    kw.setdefault("play_mode", "free")          # free play's own rules (credits is the default)
    return ShowConfig(economy=EconomyConfig(**eco), **kw)


def _setup(w: World, show: ShowConfig | None = None) -> G.Guests:
    store.save_show(show or _show())

    async def sleep(s: float) -> None:          # time passes in the world while a timer waits
        await w.run(int(s) + 1)

    return G.Guests(G.GuestDeps(
        state=lambda: w.runner.guest_state(count=24), token_ok=lambda t: t == TOKEN,
        now_ms=lambda: int(w.clock.t * 1000), to_thread=_inline, rng=random.Random(1),
        runner=lambda: w.runner, gateway=lambda: Catalog(w), library_search=Lib([]),
        known=lambda uris: {u: False for u in uris}, clock=w.clock, sleep=sleep))


async def _phones(g: G.Guests, n: int) -> list[str]:
    return [await _phone(g) for _ in range(n)]


async def _until_playing(w: World, uri: str, limit: int = 900) -> None:
    for _ in range(limit):
        if w.player.current == uri:
            return
        await w.run(1)
    raise AssertionError(f"{uri} never played; played {w.played()}")


async def _timers(g: G.Guests) -> None:
    while g._tasks:
        await asyncio.gather(*list(g._tasks))


def _waiting(w: World) -> list[str]:
    return [e.title for e in w.runner.night.line if e.state in ("queued", "committed")]


# ═══ 1. the room's skip ════════════════════════════════════════════════════

def test_three_downs_skip_the_song_playing_even_the_hosts_set():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show(economy={"skip_grace_s": 0}))
        a, b, c = await _phones(g, 3)
        await g.vote(a, "down")
        await g.vote(b, "down")
        view = (await g.view(a))[1]["view"]
        assert view["now"]["skip"]["needed"] == 1                 # one more ▼ skips it
        code, out = await g.vote(c, "down")
        assert code == 200
        assert out["view"]["now"]["skip"]["skipping"] is True
        assert out["view"]["now"]["why_not"] == "The room voted to skip it."
        await w.run(1)
        assert w.played() == ["S0", "S1"]                         # S0 was voted off
        assert any("voted S0 off" in line for line in w.runner.night.log)
    _run(go())


def test_a_room_skip_is_recorded_so_the_night_report_counts_it():
    """`skip_by_vote` must record the skip the same way the "removed after
    it was committed" repair path does (night.py's own `_played`), or the
    night report's `played.skipped` undercounts the headline feature of
    free play."""
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show(economy={"skip_grace_s": 0}))
        a, b, c = await _phones(g, 3)
        await g.vote(a, "down")
        await g.vote(b, "down")
        await g.vote(c, "down")
        await w.run(1)
        assert w.played() == ["S0", "S1"]
        kinds = [p.kind for p in w.runner.night.played]
        assert kinds.count("skipped") == 1
        from services.jukebox import night_report
        section = night_report.night_section(w.runner.night, w.deps.now_ms())
        assert section["played"]["skipped"] == 1
    _run(go())


def test_the_share_counts_too_and_two_of_three_is_two_thirds():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show(economy={"skip_grace_s": 0}))
        ps = await _phones(g, 6)
        await g.vote(ps[0], "up")
        await g.vote(ps[1], "up")
        for p in ps[2:5]:
            await g.vote(p, "down")                               # 3 of 5 ▼: 60%, not two-thirds
        assert w.player.current == set_uri(0)
        assert (await g.view(ps[0]))[1]["view"]["now"]["skip"]["needed"] == 1
        await g.vote(ps[5], "down")                               # 4 of 6: 67%
        await w.run(1)
        assert w.player.current == set_uri(1)
        # two of three is two-thirds when two ▼ are enough
        assert G.share_met(2, 1, 67) and not G.share_met(3, 2, 67)
        assert G.skip_needed(2, 1, _show(free_skip_downs=2)) == 0
    _run(go())


def test_no_skip_in_the_first_seconds_it_waits_and_checks_again():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)                                             # the 20 s grace
        a, b, c, d = await _phones(g, 4)
        for p in (a, b, c):
            await g.vote(p, "down")
        assert w.player.current == set_uri(0)                     # 2 s in: not yet
        view = (await g.view(a))[1]["view"]
        assert view["now"]["skip"]["needed"] == 0 and view["now"]["skip"]["grace_left_ms"] > 0
        await _timers(g)                                          # the grace ends
        await w.run(1)
        assert w.played() == ["S0", "S1"]
    _run(go())


def test_a_vote_taken_back_in_the_grace_means_no_skip():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        a, b, c = await _phones(g, 3)
        for p in (a, b, c):
            await g.vote(p, "down")
        await g.vote(c, "none")                                   # changed their mind
        await _timers(g)
        assert w.player.current == set_uri(0)
    _run(go())


def test_a_song_waiting_for_the_next_slot_is_sent_first_so_the_skip_lands_on_it():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show(economy={"skip_grace_s": 0}))
        ana, b, c, d = await _phones(g, 4)
        assert (await g.add(ana, jb_uri(0)))[0] == 200            # waits for the slot after S0
        for p in (b, c, d):
            await g.vote(p, "down")
        await w.run(1)
        assert w.played() == ["S0", "J0"]                         # not S1: the slot is kept
        assert w.runner.night.now.kind == "jukebox"
    _run(go())


def test_only_the_same_play_is_skipped():
    async def go():
        w = await _night(set_s=300)
        out = await w.runner.skip_by_vote(123, set_uri(0))
        assert out["reason"] == "moved_on"
        out = await w.runner.skip_by_vote(w.runner.night.now.started_ms, set_uri(5))
        assert out["reason"] == "moved_on"
        assert w.player.current == set_uri(0)
    _run(go())


def test_a_voted_off_song_cant_be_voted_on():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show(economy={"skip_grace_s": 0}))
        ps = await _phones(g, 4)
        w.gw.fail["next_track"] = 1                               # Spotify is slow to skip
        for p in ps[:3]:
            await g.vote(p, "down")
        code, out = await g.vote(ps[3], "up")
        assert code == 409 and out["reason"] == "skipping"
    _run(go())


# ═══ 2. the jail ═══════════════════════════════════════════════════════════

JAIL_SHOW = dict(free_skip_downs=10, economy={"jail_scale": False, "skip_grace_s": 0})


async def _jailed_ana(w: World, g: G.Guests, voters: int = 5):
    ps = await _phones(g, voters + 2)
    ana, ben, rest = ps[0], ps[1], ps[2:]
    assert (await g.add(ana, jb_uri(0)))[0] == 200
    assert (await g.add(ana, jb_uri(1)))[0] == 200                # her 2nd song waits
    await _until_playing(w, jb_uri(0))
    for p in rest:
        await g.vote(p, "down")
    return ana, ben, rest


def test_net_downs_on_a_guests_songs_send_them_to_a_time_out():
    async def go():
        w = await _night(set_s=60, jb_s=60)
        g = _setup(w, _show(**JAIL_SHOW))
        ana, ben, rest = await _jailed_ana(w, g)
        assert ana in w.runner.night.jail
        view = (await g.view(ana))[1]["view"]
        assert view["me"]["jail"]["in"] and view["me"]["jail"]["songs_left"] == 5
        assert view["strip"]["tone"] == "playing"                 # her song still plays out
        await w.run(61)                                           # J0 ends; a set song starts
        view = (await g.view(ana))[1]["view"]
        assert view["strip"]["tone"] == "jail" and view["strip"]["jail_left"] == 4
        assert [m["jailed"] for m in view["mine"]] == [True]
        # she can't add or bump, but she can still vote
        code, out = await g.add(ana, jb_uri(5))
        assert code == 409 and out["reason"] == "jailed" and "4 more songs" in out["detail"]
        code, out = await g.bump(ana, w.runner.night.line[1].id, "up")
        assert out["reason"] == "jailed"
        assert (await g.vote(ana, "up"))[0] == 200
    _run(go())


def test_a_jailed_guests_song_keeps_its_place_but_isnt_sent_until_the_time_out_ends():
    async def go():
        w = await _night(set_s=60, jb_s=60)
        g = _setup(w, _show(free_skip_downs=10, economy={"jail_scale": False, "skip_grace_s": 0,
                                                         "fair_order": False}))
        ana, ben, rest = await _jailed_ana(w, g)
        await g.add(ben, jb_uri(2))                               # behind Ana's 2nd song
        assert _waiting(w)[:2] == ["J1 Song", "J2 Song"]
        await w.run(61)                                           # J0 ends -> S1 plays
        await w.run(30)                                           # the slot after S1 commits
        sent = [e.title for e in w.runner.night.line if e.state == "committed"]
        assert sent == ["J2 Song"]                                # Ana's was passed over
        assert _waiting(w)[0] == "J1 Song"                        # and kept its place
        await w.run(60 * 5)                                       # five songs start
        assert ana not in w.runner.night.jail
        assert any("time-out is over" in line for line in w.runner.night.log)
        await _until_playing(w, jb_uri(1))                        # her song plays after all
        # and her count started again at 0: one more ▼ doesn't send her back
        await g.vote(rest[0], "down")
        view = (await g.view(ana))[1]["view"]
        assert not view["me"]["jail"]["in"] and view["me"]["jail"]["count"] == 1
        assert w.runner.night.jail == {}
    _run(go())


def test_the_bar_rises_with_the_crowd():
    async def go():
        w = await _night(set_s=60, jb_s=60)
        g = _setup(w, _show(free_skip_downs=10, economy={"skip_grace_s": 0}))   # jail_scale on
        await _phones(g, 8)                                        # 15 phones at the party
        ana, ben, rest = await _jailed_ana(w, g, voters=5)
        assert economy.jail_threshold(15, store.load_show().economy) == 8
        view = (await g.view(ana))[1]["view"]
        assert view["me"]["jail"]["at"] == 8 and view["me"]["jail"]["count"] == 5
        assert ana not in w.runner.night.jail                      # 5 ▼ in a crowd of 15: not yet
        for p in (await _phones(g, 3)):
            await g.vote(p, "down")
        assert ana in w.runner.night.jail                          # 8 ▼
    _run(go())


def test_the_crowd_is_the_phones_seen_in_the_last_fifteen_minutes():
    seen = {"a": 0, "b": 10 * 60_000, "c": 20 * 60_000}
    assert G.present(seen, 20 * 60_000) == 2
    assert G.present({}, 0) == 1


def test_the_host_pardons_and_the_count_starts_again():
    async def go():
        w = await _night(set_s=60, jb_s=60)
        g = _setup(w, _show(**JAIL_SHOW))
        ana, ben, rest = await _jailed_ana(w, g)
        code, out = await g.host_set(ana, pardon=True)
        assert code == 200
        row = next(p for p in out["phones"] if p["id"] == ana)
        assert row["jail_left"] == 0 and row["jail_count"] == 0 and row["jails"] == 1
        assert ana not in w.runner.night.jail
        assert any("pardoned" in line for line in w.runner.night.log)
        code, out = await g.host_set(ana, pardon=True, name="Somebody Else")
        assert code == 409 and out["reason"] == "not_jailed"
        assert g._book.phones[ana].name != "Somebody Else"         # a refused pardon changes nothing
        assert (await g.add(ana, jb_uri(5)))[0] == 200            # she can add again
    _run(go())


def test_no_jail_when_the_show_turns_it_off():
    async def go():
        w = await _night(set_s=60, jb_s=60)
        g = _setup(w, _show(free_jail_songs=0, **JAIL_SHOW))
        ana, ben, rest = await _jailed_ana(w, g)
        assert w.runner.night.jail == {}
        assert not any("sit out" in r for r in (await g.view(ana))[1]["view"]["house_rules"])
    _run(go())


def test_the_hosts_songs_never_go_to_jail():
    async def go():
        w = await _night(set_s=60, jb_s=60)
        g = _setup(w, _show(**JAIL_SHOW))
        ps = await _phones(g, 6)
        assert (await w.runner.add(jb_uri(0)))["status"] == "added"      # the host's song
        await _until_playing(w, jb_uri(0))
        for p in ps:
            await g.vote(p, "down")
        assert w.runner.night.jail == {} and g._book.play_by == {}
    _run(go())


# ═══ 3. bumps ══════════════════════════════════════════════════════════════

async def _three_in_line(w: World, g: G.Guests):
    ana, ben, cy = await _phones(g, 3)
    for p, i in ((ana, 0), (ben, 1), (cy, 2)):
        assert (await g.add(p, jb_uri(i)))[0] == 200
    return ana, ben, cy


def _id(w: World, title: str) -> str:
    return next(e.id for e in w.runner.night.line if e.title == title)


def test_your_own_song_up_or_someone_elses_down_one_place():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana, ben, cy = await _three_in_line(w, g)
        code, out = await g.bump(cy, _id(w, "J2 Song"), "up")
        assert code == 200, out
        assert _waiting(w) == ["J0 Song", "J2 Song", "J1 Song"]
        assert out["view"]["me"]["bumps"]["left"] == 1
        # the up-bump stepped past J1, pushing IT back one place -- that
        # counts toward J1's own cap exactly as a down-bump of J1 would
        assert next(e for e in w.runner.night.line if e.title == "J1 Song").pushed_back == 1
        code, out = await g.bump(ana, _id(w, "J0 Song"), "down")
        assert out["reason"] == "bump_others_down"
        code, out = await g.bump(ana, _id(w, "J2 Song"), "up")
        assert out["reason"] == "bump_own_up"
        assert (await g.bump(ana, _id(w, "J2 Song"), "down"))[0] == 200
        assert _waiting(w) == ["J0 Song", "J1 Song", "J2 Song"]
        assert w.runner.night.line[2].pushed_back == 1
        # what each phone's Queue offers matches
        view = (await g.view(ben))[1]["view"]
        offers = {s["title"]: s.get("bump") for s in view["next"] if s["kind"] == "jukebox"}
        assert offers == {"J0 Song": "down", "J1 Song": "up", "J2 Song": None}
    _run(go())


def test_two_bumps_an_hour():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana, ben, cy = await _three_in_line(w, g)
        assert (await g.bump(cy, _id(w, "J2 Song"), "up"))[0] == 200
        assert (await g.bump(cy, _id(w, "J2 Song"), "up"))[0] == 200
        assert _waiting(w) == ["J2 Song", "J0 Song", "J1 Song"]
        code, out = await g.bump(cy, _id(w, "J0 Song"), "down")
        assert code == 409 and out["reason"] == "bumps_used" and "free at" in out["detail"]
        w.clock.t += 3601                                         # an hour later
        assert (await g.bump(cy, _id(w, "J0 Song"), "down"))[0] == 200
        g_off = _setup(w, _show(free_bumps_per_hour=0))
        g_off._book = g._book
        assert (await g_off.bump(ana, _id(w, "J0 Song"), "up"))[1]["reason"] == "bumps_off"
    _run(go())


def test_nothing_passes_the_song_sent_to_spotify():
    async def go():
        w = await _night(set_s=60)
        g = _setup(w)
        ana, ben, cy = await _three_in_line(w, g)
        await w.run(20)                                           # J0 is sent for the slot
        assert [e.title for e in w.runner.night.line if e.state == "committed"] == ["J0 Song"]
        code, out = await g.bump(ben, _id(w, "J1 Song"), "up")
        assert code == 409 and out["reason"] == "at_front"
        code, out = await g.bump(ben, _id(w, "J0 Song"), "down")
        assert out["reason"] == "committed_fixed"
    _run(go())


def test_a_song_is_pushed_back_at_most_three_places():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ps = await _phones(g, 5)
        for i, p in enumerate(ps):
            await g.add(p, jb_uri(i))
        j0 = _id(w, "J0 Song")
        for p in ps[1:4]:
            assert (await g.bump(p, j0, "down"))[0] == 200
        assert _waiting(w).index("J0 Song") == 3
        code, out = await g.bump(ps[4], j0, "down")
        assert out["reason"] == "pushed_max"
        view = (await g.view(ps[4]))[1]["view"]
        j0_row = next(s for s in view["next"] if s["title"] == "J0 Song")
        assert j0_row["bump"] is None and "as far as it can go" in j0_row["bump_why"]
    _run(go())


def test_up_bumps_from_fresh_phones_cannot_push_one_song_past_the_cap():
    """The cap is a PER-SONG total, not a per-direction one: a guest can't
    dodge it by adding a fresh song right behind the target and bumping
    THAT song up instead of bumping the target down directly. A brand-new
    phone gets its own 2-bumps/hour allowance, so cycling fresh phones (a
    throwaway song, one up-bump, repeat) must still be refused once the
    target has already been pushed back `bump_down_max_places` times."""
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)
        assert (await g.add(ana, jb_uri(0)))[0] == 200            # the target
        j0 = _id(w, "J0 Song")
        for i in range(1, 4):
            p = await _phone(g)                                   # a brand-new phone each time
            assert (await g.add(p, jb_uri(i)))[0] == 200
            code, out = await g.bump(p, _id(w, f"J{i} Song"), "up")
            assert code == 200, out
        assert next(e for e in w.runner.night.line if e.id == j0).pushed_back == 3
        p4 = await _phone(g)
        assert (await g.add(p4, jb_uri(4)))[0] == 200
        code, out = await g.bump(p4, _id(w, "J4 Song"), "up")
        assert code == 409 and out["reason"] == "pushed_max"
        assert "as far as it can go" in out["detail"]
        assert next(e for e in w.runner.night.line if e.id == j0).pushed_back == 3
    _run(go())


def test_the_queue_preview_refuses_an_up_bump_too_once_the_song_ahead_is_capped():
    """The Queue preview (build_view) must agree with what a real up-bump
    would be refused for — a guest should never see a live "up" arrow for a
    bump night.py is about to turn down."""
    async def go():
        w = await _night(set_s=300, mode="jukebox_first")
        g = _setup(w)
        ps = await _phones(g, 5)
        for i, p in enumerate(ps):
            await g.add(p, jb_uri(i))
        j0 = _id(w, "J0 Song")
        for p in ps[1:4]:
            assert (await g.bump(p, j0, "down"))[0] == 200
        assert next(e for e in w.runner.night.line if e.id == j0).pushed_back == 3
        view = (await g.view(ps[4]))[1]["view"]
        j4_row = next(s for s in view["next"] if s["title"] == "J4 Song")
        assert j4_row["bump"] is None and "as far as it can go" in j4_row["bump_why"]
        code, out = await g.bump(ps[4], _id(w, "J4 Song"), "up")
        assert code == 409 and out["reason"] == "pushed_max"
    _run(go())


def test_a_held_song_stays_where_it_is_and_bumps_pass_it():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana, ben, cy = await _three_in_line(w, g)
        await w.runner.hold(_id(w, "J1 Song"), True)
        code, out = await g.bump(ben, _id(w, "J1 Song"), "up")
        assert out["reason"] == "on_hold"
        assert (await g.bump(cy, _id(w, "J2 Song"), "up"))[0] == 200
        assert [e.title for e in w.runner.night.line] == ["J2 Song", "J1 Song", "J0 Song"]
        upcoming = [s["title"] for s in (await g.view(ana))[1]["view"]["next"]
                    if s["kind"] == "jukebox"]
        assert upcoming == ["J2 Song", "J0 Song"]                 # the held one isn't offered
    _run(go())


# ═══ 4. the page's words, the settings and the doors ═══════════════════════

def test_the_house_rules_say_the_free_play_rules():
    rules = G.house_rules(_show())
    assert "3 ▼ and two-thirds of the votes skip a song." in rules
    assert any("5 more ▼ than ▲ (more in a big crowd), they sit out 5 songs" in r for r in rules)
    rules = G.house_rules(_show(free_skip_downs=4, free_skip_share=75, free_jail_songs=1,
                                economy={"jail_scale": False}))
    assert "4 ▼ and three-quarters of the votes skip a song." in rules
    assert any(r.endswith("they sit out 1 song.") and "crowd" not in r for r in rules)


def test_the_free_play_settings_are_validated_by_the_one_validator():
    cur = ShowConfig()
    new = show_mod.apply_patch(cur, {"free_skip_downs": 4, "free_play_next": "off",
                                     "free_jail_songs": 0, "free_bumps_per_hour": 5,
                                     "free_skip_share": 80})
    assert (new.free_skip_downs, new.free_play_next, new.free_jail_songs) == (4, "off", 0)
    for key, bad in (("free_skip_downs", 1), ("free_skip_share", 95), ("free_play_next", "anyone"),
                     ("free_bumps_per_hour", 11), ("free_jail_songs", 16)):
        try:
            show_mod.apply_patch(cur, {key: bad})
        except ValueError as exc:
            assert key in str(exc)
        else:
            raise AssertionError(f"{key}={bad!r} was accepted")
    fields = {f["key"]: f for f in show_mod.guest_fields()}
    assert {k for k, f in fields.items() if f["card"] == "Free play"} == {
        "free_skip_downs", "free_skip_share", "free_bumps_per_hour", "free_play_next",
        "free_jail_songs"}
    assert fields["free_skip_downs"]["min"] == 2 and fields["free_skip_downs"]["max"] == 10
    assert [c["value"] for c in fields["free_play_next"]["choices"]] == ["host", "off"]


def test_the_bump_door_and_the_pardon_route(monkeypatch):
    w = World(set_s=300)
    w.deps.load_config = store.load_config
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    store.save_show(_show(**JAIL_SHOW))
    g = G.Guests(G.GuestDeps(token_ok=lambda t: t == TOKEN, to_thread=_inline,
                             now_ms=lambda: int(w.clock.t * 1000),
                             gateway=lambda: Catalog(w), library_search=Lib([]),
                             known=lambda uris: {u: False for u in uris}))
    monkeypatch.setattr(G, "book", g)
    app = FastAPI()
    app.include_router(jukebox_guest_router.router)
    app.include_router(jukebox_router.router)
    key = guest_key.load_or_create(jukebox_guest_router.KEY_FILE)
    with TestClient(app) as c:
        store.save_config(store.load_config().model_copy(update={"playlist": w.cfg.playlist}))
        assert c.post("/api/jukebox/night/start", json={}).json()["status"] == "running"
        ana, ben = c.portal.call(_phone, g), c.portal.call(_phone, g)
        c.portal.call(g.add, ana, jb_uri(0))
        c.portal.call(g.add, ben, jb_uri(1))
        j1 = w.runner.night.line[1].id
        body = {"phone": ben, "entry_id": j1, "direction": "up"}
        assert c.post("/api/jukebox/guest/bump", json=body).status_code == 401
        r = c.post("/api/jukebox/guest/bump", json=body, headers={guest_key.HEADER: key})
        assert r.status_code == 200 and r.json()["bumped"]["place"] == 1
        c.portal.call(w.runner.jail, ana, 5)
        r = c.post(f"/api/jukebox/guests/{ana}", json={"pardon": True})
        assert r.status_code == 200 and w.runner.night.jail == {}
        assert c.post(f"/api/jukebox/guests/{ana}", json={"pardon": True}).status_code == 409
