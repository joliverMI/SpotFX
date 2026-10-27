"""The Jukebox's credits economy (services/jukebox/economy.py) and its
ledger (services/jukebox/ledger.py) — phase 3 PR 3.1 of
data/jukebox-plan/report.md.

Three things held:
  1. the rulebook's worked prices (§1, with the D4 re-tune's numbers);
  2. the plan's simulator, run against the REAL price functions under the
     SHIPPED settings (services/jukebox/simulator.py), lands on the plan's
     own §3.2 results at 4, 8, 15 and 30 guests — and a drifted setting
     moves it off them (the spec bites);
  3. the ledger's invariants: no balance below zero, every credit traceable
     to its entry, no tip to the host or yourself, a vote paid once, the
     double-first bonus capped per giver per night, a refund once.
"""
from __future__ import annotations

import json
import random
import threading
import time

import pytest
from pydantic import ValidationError

from models.jukebox import EconomyConfig
from services.jukebox import economy, ledger as ledger_mod
from services.jukebox.ledger import Ledger, LedgerError

CFG = EconomyConfig()


# ── 1. the worked prices ────────────────────────────────────────────────────

def test_the_shipped_settings_are_the_tuned_ones():
    c = CFG
    assert (c.start_credits, c.topup_every_min, c.topup_cap, c.qr_bonus) == (8, 45, 10, 5)
    assert (c.add_base, c.add_free_min, c.add_double_min, c.add_cap) == (4, 15, 15, 60)
    assert (c.max_waiting, c.fair_order) == (2, True)              # D4: two songs in line
    assert (c.skip_max, c.skip_half_min, c.skip_floor, c.skip_down_pct) == (40, 20, 16, 15)
    assert (c.jail_net_downs, c.jail_scale, c.jail_fee) == (5, True, 10)


@pytest.mark.parametrize("wait, price", [(0, 4), (14, 4), (15, 4), (20, 5), (25, 6), (30, 8),
                                         (35, 10), (45, 16), (55, 25), (200, 60)])
def test_add_price_doubles_every_15_minutes_of_wait(wait, price):
    assert economy.add_price(wait, 3.5, True, CFG) == price


@pytest.mark.parametrize("dur, extra", [(5.0, 0), (5.01, 1), (6.0, 1), (6.5, 2), (9.0, 4)])
def test_plus_one_per_started_minute_over_5(dur, extra):
    assert economy.add_price(0, dur, True, CFG) == 4 + extra


def test_not_learned_yet_costs_one_more_and_a_flat_price_stays_flat():
    assert economy.add_price(0, 3.5, False, CFG) == 5
    assert economy.add_price(90, 3.5, True, EconomyConfig(add_double_min=0)) == 4


@pytest.mark.parametrize("jump, price", [(10, 11), (20, 13), (30, 16), (60, 23)])
def test_play_next(jump, price):
    assert economy.play_next_price(jump, CFG) == price


def test_play_next_only_from_ten_minutes_away_and_once():
    assert economy.play_next_allowed(10, False, CFG)
    assert not economy.play_next_allowed(9.9, False, CFG)
    assert not economy.play_next_allowed(30, True, CFG)


@pytest.mark.parametrize("behind, price", [(0, 2), (1, 3), (4, 3), (5, 4), (12, 5)])
def test_bump_up_is_dearer_near_the_front(behind, price):
    assert economy.bump_up_price(behind, CFG) == price


@pytest.mark.parametrize("ahead, price", [(0, 3), (1, 4), (4, 4), (8, 5)])
def test_bump_down_is_dearer_near_the_back(ahead, price):
    assert economy.bump_down_price(ahead, CFG) == price


def test_a_song_can_be_pushed_back_three_places_at_most():
    assert economy.can_push_back(2, CFG) and not economy.can_push_back(3, CFG)


@pytest.mark.parametrize("guests, table", [
    # §1's worked skip prices: (empty, 0▼) (10-min line, 2▼) (20-min, 4▼) (40-min, 4▼)
    (4, (30, 14, 8, 6)),
    (8, (40, 21, 12, 10)),
    (15, (55, 30, 18, 15)),
    (30, (77, 44, 28, 22)),
])
def test_skip_prices_match_the_rulebook(guests, table):
    got = (economy.skip_price(0, 0, 0, guests, CFG),
           economy.skip_price(10, 0, 2, guests, CFG),
           economy.skip_price(20, 0, 4, guests, CFG),
           economy.skip_price(40, 0, 4, guests, CFG))
    assert got == table


def test_up_votes_cancel_down_votes_and_skip_never_goes_below_its_minimum():
    assert economy.skip_price(10, 2, 4, 8, CFG) == economy.skip_price(10, 0, 2, 8, CFG)
    assert economy.skip_price(60, 0, 40, 4, CFG) == CFG.skip_min
    assert not economy.skip_allowed(19.9, CFG) and economy.skip_allowed(20, CFG)


@pytest.mark.parametrize("guests, threshold", [(2, 5), (4, 5), (8, 6), (15, 8), (30, 10)])
def test_jail_rises_with_the_crowd(guests, threshold):
    assert economy.jail_threshold(guests, CFG) == threshold
    assert economy.jail_threshold(guests, EconomyConfig(jail_scale=False)) == 5


def test_free_credits():
    assert economy.start_grants(CFG) == (4, 4, 20.0)
    assert economy.topup_amount(9, CFG) == 1
    assert economy.topup_amount(10, CFG) == 0            # paused while 10 are held
    assert economy.topup_amount(0, EconomyConfig(topup_every_min=0)) == 0


def test_the_first_five_given_count_double():
    assert economy.tip_bonus(0, 3, CFG) == 3
    assert economy.tip_bonus(3, 3, CFG) == 2
    assert economy.tip_bonus(5, 3, CFG) == 0
    assert economy.tip_units_allowed(2, CFG) == 1 and economy.tip_units_allowed(3, CFG) == 0
    assert economy.tip_units_allowed(0, EconomyConfig(tips=False)) == 0


@pytest.mark.parametrize("bad", [{"topup_every_min": 10}, {"add_double_min": 5},
                                 {"max_waiting": 4}, {"skip_down_pct": 31}, {"jail_fee": 0}])
def test_settings_outside_the_plans_ranges_are_refused(bad):
    with pytest.raises(ValidationError):
        EconomyConfig(**bad)


# ── 2. the simulator as the executable spec ─────────────────────────────────

# The plan's §3.2 table (two songs in line, 100 nights per size, base seed
# 77), as the plan printed it: each value with the precision it was
# printed at.
PLAN = {
    4: dict(afford_rate=0.85, wait_to_play_median=10, price_mid=4.9, held_mid_per_guest=14.0,
            skips_hr=1.1, nexts_hr=0.09, tips_hr=1.3, jails=0.7, unspent_share=0.29,
            first_song_wait_all=22, back_wait_p90=25),
    8: dict(afford_rate=0.50, wait_to_play_median=26, price_mid=14.5, held_mid_per_guest=7.9,
            skips_hr=1.1, nexts_hr=0.12, tips_hr=2.7, jails=0.8, unspent_share=0.26,
            first_song_wait_all=28, back_wait_p90=49),
    15: dict(afford_rate=0.37, wait_to_play_median=29, price_mid=18.2, held_mid_per_guest=6.9,
             skips_hr=0.9, nexts_hr=0.18, tips_hr=4.9, jails=1.0, unspent_share=0.31,
             first_song_wait_all=29, back_wait_p90=53),
    30: dict(afford_rate=0.32, wait_to_play_median=25, price_mid=20.4, held_mid_per_guest=6.7,
             skips_hr=1.1, nexts_hr=0.23, tips_hr=11.0, jails=1.4, unspent_share=0.37,
             first_song_wait_all=26, back_wait_p90=56),
}
# How far a value may sit from the printed one: half its printed precision.
PRINTED = dict(afford_rate=0.005, wait_to_play_median=0.5, price_mid=0.05, held_mid_per_guest=0.05,
               skips_hr=0.05, nexts_hr=0.005, tips_hr=0.05, jails=0.05, unspent_share=0.005,
               first_song_wait_all=0.5, back_wait_p90=0.5)


@pytest.fixture(scope="module")
def sim():
    from services.jukebox import simulator as J
    return J


@pytest.mark.parametrize("guests", [4, 8, 15, 30])
def test_the_shipped_economy_reproduces_the_plans_night(sim, guests):
    r = sim.run_many(guests, sim.params_for(guests), seeds=100, base_seed=77)
    assert r["got_played"] == 1.0                     # everyone who asked got a song
    off = {k: (want, round(r[k], 3)) for k, want in PLAN[guests].items()
           if abs(r[k] - want) > PRINTED[k] + 1e-9}
    assert not off, f"at {guests} guests the night moved off the plan's §3.2: {off}"


def test_a_drifted_price_moves_the_night_off_the_plan(sim):
    """The red control: the old one-song tuning (the price doubling every 20
    minutes instead of 15) is a different night, and the spec says so."""
    drifted = sim.params_for(15, EconomyConfig(add_double_min=20))
    r = sim.run_many(15, drifted, seeds=100, base_seed=77)
    assert abs(r["price_mid"] - PLAN[15]["price_mid"]) > PRINTED["price_mid"]


def test_the_port_reads_its_prices_from_the_economy(sim, monkeypatch):
    """Behavioural proof the simulator's prices ARE economy.py's: change the
    function and the simulated night changes with it."""
    base = sim.run_many(8, sim.params_for(8), seeds=5, base_seed=3)
    monkeypatch.setattr(economy, "add_price", lambda *a, **k: 1)
    cheap = sim.run_many(8, sim.params_for(8), seeds=5, base_seed=3)
    assert cheap["add_price_median"] == 1 and base["add_price_median"] > 1


# ── 3. the ledger ───────────────────────────────────────────────────────────

def _ledger(tmp_path=None, **cfg) -> Ledger:
    return Ledger("night-1", EconomyConfig(**cfg), path=(tmp_path / "n.jsonl") if tmp_path else None,
                  persist=tmp_path is not None, now_ms=lambda: 1000)


def test_a_balance_is_the_sum_of_its_entries_and_never_negative():
    led = _ledger()
    led.grant("a", "start", 4)
    led.spend("a", "add", 3, "song-1")
    assert led.balance("a") == 1
    with pytest.raises(LedgerError) as e:
        led.spend("a", "skip", 2, "song-2")
    assert e.value.code == "not_enough" and led.balance("a") == 1
    assert len(led.entries) == 2                     # a refusal writes nothing
    assert sum(x.delta for x in led.history("a")) == led.balance("a")
    assert led.verify() == []


def test_a_vote_is_paid_once_and_never_on_your_own_song():
    led = _ledger()
    assert led.vote("a", "s1", own_song=False).delta == 1
    assert led.vote("a", "s1", own_song=False) is None            # a changed vote pays nothing
    with pytest.raises(LedgerError) as e:
        led.vote("a", "s2", own_song=True)
    assert e.value.code == "own_song"
    assert led.balance("a") == 1


def test_adder_credits_once_per_song_and_never_to_the_host():
    led = _ledger()
    assert led.adder_ups("a", "s1", 3, adder_is_host=False).delta == 3
    with pytest.raises(LedgerError):
        led.adder_ups("a", "s1", 3, adder_is_host=False)
    with pytest.raises(LedgerError) as e:
        led.adder_ups("host", "s2", 3, adder_is_host=True)
    assert e.value.code == "host_song"
    assert led.adder_ups("a", "s3", 0, adder_is_host=False) is None


def test_tips_go_to_a_guests_adder_only_and_the_first_five_count_double():
    led = _ledger()
    led.grant("g", "start", 8)
    with pytest.raises(LedgerError) as e:
        led.tip("g", "host", "s1", 1, adder_is_host=True)
    assert e.value.code == "host_song"
    with pytest.raises(LedgerError) as e:
        led.tip("g", "g", "s1", 1, adder_is_host=False)
    assert e.value.code == "own_tip"
    parts = led.tip("g", "a", "s1", 3, adder_is_host=False)
    assert [p.kind for p in parts] == ["tip_out", "tip_in", "tip_bonus"]
    assert {p.group for p in parts} == {parts[0].seq}
    assert (led.balance("g"), led.balance("a")) == (5, 6)        # 3 given, 3 + 3 bonus
    with pytest.raises(LedgerError) as e:
        led.tip("g", "a", "s1", 1, adder_is_host=False)          # 3 a song, per giver
    assert e.value.code == "tip_cap"
    led.tip("g", "b", "s2", 3, adder_is_host=False)
    assert led.balance("b") == 3 + 2                              # only 2 of the 5 left
    led.tip("g", "a", "s3", 1, adder_is_host=False)
    assert led.balance("a") == 7                                  # the allowance is spent
    assert led.verify() == []


def test_a_refund_returns_a_spend_once_to_whoever_paid_it():
    led = _ledger()
    led.grant("a", "start", 8)
    sp = led.spend("a", "add", 6, "song-1")
    with pytest.raises(LedgerError) as e:
        led.refund(1)                                             # a grant is not a spend
    assert e.value.code == "no_spend"
    with pytest.raises(LedgerError) as e:
        led.refund(sp.seq, 7)
    assert e.value.code == "over_refund"
    r = led.refund(sp.seq, note="the host removed it")
    assert (r.phone, r.delta, r.link) == ("a", 6, sp.seq) and led.balance("a") == 8
    with pytest.raises(LedgerError) as e:
        led.refund(sp.seq)
    assert e.value.code == "refunded"
    assert led.verify() == []


def test_jail_breakout_costs_the_fee():
    led = _ledger()
    led.grant("a", "start", 8)
    with pytest.raises(LedgerError):
        led.jail_breakout("a")
    led.grant("a", "host_gift", 2)
    assert led.jail_breakout("a").delta == -10 and led.balance("a") == 0


def test_the_file_is_append_only_and_replays_to_the_same_balances(tmp_path):
    led = _ledger(tmp_path)
    led.grant("a", "start", 4)
    led.grant("b", "start", 4)
    led.tip("a", "b", "s1", 2, adder_is_host=False)
    sp = led.spend("b", "add", 5, "s2")
    led.refund(sp.seq)
    lines = (tmp_path / "n.jsonl").read_text().splitlines()
    assert len(lines) == len(led.entries) == 7
    again = Ledger("night-1", CFG, path=tmp_path / "n.jsonl")
    assert again.balance("a") == led.balance("a") and again.balance("b") == led.balance("b")
    assert again.given("a") == 2 and again.verify() == []
    with pytest.raises(LedgerError):
        again.refund(sp.seq)                                      # the refund was replayed too


def test_verify_catches_a_tampered_file(tmp_path):
    led = _ledger(tmp_path)
    led.grant("a", "start", 2)
    led.spend("a", "add", 2, "s1")
    path = tmp_path / "n.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    rows[1]["delta"] = -5                                         # a spend bigger than the balance
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert any("went to -3" in v for v in Ledger("night-1", CFG, path=path).verify())


def test_a_random_night_keeps_every_invariant():
    """Thousands of random operations — grants, votes, Adder pays, tips,
    spends, refunds, jail — the rules refusing whatever breaks them; the
    entries must still verify, and no giver's gifts may have made more than
    five bonus credits."""
    rng = random.Random(7)
    led = _ledger()
    phones = [f"p{i}" for i in range(12)] + ["host"]
    songs = [f"s{i}" for i in range(40)]
    spends = []
    for _ in range(4000):
        op = rng.random()
        a, b = rng.choice(phones), rng.choice(phones)
        song = rng.choice(songs)
        try:
            if op < 0.15:
                led.grant(a, rng.choice(["start", "topup", "qr_bonus", "host_gift"]), rng.randint(1, 5))
            elif op < 0.45:
                led.vote(a, song, own_song=rng.random() < 0.05)
            elif op < 0.55:
                led.adder_ups(a, song, rng.randint(0, 6), adder_is_host=(a == "host"))
            elif op < 0.75:
                led.tip(a, b, song, rng.randint(1, 3), adder_is_host=(b == "host"))
            elif op < 0.93:
                spends.append(led.spend(a, rng.choice(["add", "bump_up", "skip", "play_next"]),
                                        rng.randint(1, 12), song).seq)
            elif op < 0.97 and spends:
                led.refund(rng.choice(spends))
            else:
                led.jail_breakout(a)
        except LedgerError:
            pass
    assert led.verify() == []
    assert all(led.balance(p) >= 0 for p in led.phones())
    assert led.balance("host") >= 0
    bonus_by_giver: dict[str, int] = {}
    for e in led.entries:
        if e.kind == "tip_bonus":
            giver = led.entries[e.link - 1].phone
            bonus_by_giver[giver] = bonus_by_giver.get(giver, 0) + e.delta
    assert bonus_by_giver and max(bonus_by_giver.values()) <= 5
    assert not any(e.kind in ("tip_in", "tip_bonus", "adder_up") and e.phone == "host"
                   for e in led.entries)


def test_concurrent_spends_and_votes_do_not_race(monkeypatch):
    """A live multi-guest jukebox has several phones hitting one shared
    Ledger at once — the check (balance, already-voted) and the write it
    guards must be one atomic step, or two threads can both pass the same
    check before either of their entries has landed. `_write` is widened
    with a real sleep (which releases the GIL) so every racing thread gets
    a chance to run its own check during the gap between a check passing
    and its entry actually being appended — deterministic regardless of
    scheduling, not a probabilistic bet on the interpreter's own switch
    timing. Fire a spend from many threads at a phone that can only afford
    some of them, and a vote on one song from many threads at once, both
    released together via a barrier to maximize contention."""
    led = _ledger()
    led.grant("a", "start", 37)
    real_write = Ledger._write

    def slow_write(self: Ledger, parts):
        time.sleep(0.002)
        return real_write(self, parts)

    monkeypatch.setattr(Ledger, "_write", slow_write)

    n = 100
    barrier = threading.Barrier(n)
    lock = threading.Lock()
    spends: list[object] = []

    def spend_one() -> None:
        barrier.wait()
        try:
            e = led.spend("a", "add", 1, "s1")
        except LedgerError:
            return
        with lock:
            spends.append(e)

    threads = [threading.Thread(target=spend_one) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(spends) == 37                     # exactly the affordable number landed
    assert led.balance("a") == 0 and led.balance("a") >= 0
    assert len(led.entries) == 1 + 37             # the grant, plus only the paid spends
    assert led.verify() == []

    votes = 50
    vote_barrier = threading.Barrier(votes)
    paid: list[object] = []

    def vote_once() -> None:
        vote_barrier.wait()
        e = led.vote("a", "song-x", own_song=False)
        if e is not None:
            with lock:
                paid.append(e)

    voters = [threading.Thread(target=vote_once) for _ in range(votes)]
    for t in voters:
        t.start()
    for t in voters:
        t.join()

    assert len(paid) == 1                             # the same vote is paid exactly once
    assert led.balance("a") == 1
    assert led.verify() == []


def test_ledgers_live_one_file_per_night(tmp_path):
    led = ledger_mod.open_night("n-2026-10-31")
    led.grant("a", "start", 4)
    assert list(ledger_mod.all_nights()) == ["n-2026-10-31"]
