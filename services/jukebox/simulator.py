"""
SpotFX — the Jukebox's PARTY SIMULATOR (data/jukebox-plan/report.md
Appendix A, `jukesim2.py`; phase 3 PRs 3.1 and 3.4). One party night,
agent-based: guests arrive, vote, earn as Adders, tip, add songs, bump, buy
play next, skip (alone or chipping in), go to jail and break out.

ONE COPY, TWO USES:
  * the EXECUTABLE SPEC of the credits economy — tests/test_jukebox_economy.py
    runs it at 4, 8, 15 and 30 guests with the plan's own seeds and holds it
    to the plan's §3.2 results, so a price function that drifts from the
    tuned one moves the night and the test sees it;
  * the master view's party simulator (`POST /api/jukebox/simulate`,
    `simulate()` below): one night under HIS current settings recorded for
    the page to play back, beside the same nights under the tuned defaults.

The model is the plan's own, line for line, with ONE change: every price and
every earning rule is the REAL one — services/jukebox/economy.py, under the
given models.jukebox.EconomyConfig — instead of the planning formulas.
Recording (`Party(record=True)`) only appends what already happened; it
draws nothing from the random stream, so a recorded night is the same night
an unrecorded one is (asserted).

Guest BEHAVIOUR (how often people want a song, tip, bump, skip) is the
plan's model, held fixed; it is a model, not a measurement (report §12 risk
3), which is why the post-party report measures the real night later. The
songs are synthetic too: his library's length distribution, no Spotify.
Pure: numpy and the economy, no I/O, no clock.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from models.jukebox import EconomyConfig
from services.jukebox import economy

SONG_MU, SONG_SIGMA = 1.296, 0.358   # his library: median 3.65 min, mean 3.91
SET_MEAN = 3.91
# per-party-size calibration so realised voters per song match target_voters
# (the plan's vote_cal.json)
VOTE_CAL: dict = {4: 1.0795, 5: 1.108, 6: 1.0858, 8: 1.0728, 10: 1.0801, 12: 1.0891,
                  15: 1.0979, 18: 1.0874, 20: 1.0758, 25: 1.1329, 30: 1.1479}


def target_voters(n: int) -> float:
    """Active voters per song: 3 of 4 at a small party, ~6 at 30 (his numbers)."""
    return 3.0 * (n / 4.0) ** 0.345


@dataclass
class Params:
    # program --------------------------------------------------------------
    set_per_slot: int = 1          # set songs between jukebox slots (0 = jukebox only)
    juke_per_slot: int = 1         # jukebox songs in a row at a slot
    party_min: float = 240.0
    last_call_min: float = 20.0
    fair_order: bool = True        # a guest's 1st song goes ahead of anyone's 2nd
    max_waiting: int = 3
    # free credits ---------------------------------------------------------
    start_credits: int = 6
    topup_every_min: float = 30.0
    topup_cap: int = 12
    # earning --------------------------------------------------------------
    vote_reward: int = 1
    adder_up_reward: int = 1
    tip_unit: int = 1
    tip_max_per_song: int = 3
    gift_double_first: int = 5
    # jail -----------------------------------------------------------------
    jail_net_downs: int = 5
    jail_fee: int = 10
    jail_scale: bool = False       # threshold rises with active voters (5 at 3 voters)
    # add price ------------------------------------------------------------
    add_base: int = 3
    add_free_min: float = 10.0     # waits shorter than this: base price
    add_double_min: float = 20.0   # beyond it the price doubles every X min of wait
    add_cap: int = 60
    long_extra_per_min: int = 1
    learn_first_extra: int = 1
    # bumps ----------------------------------------------------------------
    bump_up_base: int = 1
    bump_up_per_behind: float = 0.5
    bump_down_base: int = 2
    bump_down_per_ahead: float = 0.5
    bump_down_max_places: int = 3
    # play next ------------------------------------------------------------
    next_base: int = 15
    next_per_min: float = 0.75
    # skip -----------------------------------------------------------------
    skip_max: int = 40             # nothing queued, a room of 8
    skip_half_min: float = 30.0
    skip_floor: int = 16
    skip_crowd: bool = True        # base and floor scale with sqrt(present / 8)
    skip_down_mult: float = 0.85   # x per net down vote ...
    skip_down_by_share: bool = True  # ... per net down as a share of a typical vote count
    skip_min: int = 4
    chip_in: bool = True
    # guest behaviour (held fixed) ----------------------------------------
    wish_min: float = 35.0
    p_tip: float = 0.25
    p_bump_up: float = 0.10
    p_bump_down: float = 0.05
    p_next: float = 0.06
    p_skip: float = 0.30
    ready_share: float = 0.55
    vote_scale: float = 1.0        # calibration knob for voters per song
    # the REAL settings every price reads (params_for copies them into the
    # rule fields above too, so the model's own reads agree with them)
    economy: EconomyConfig = field(default_factory=EconomyConfig)


@dataclass
class Song:
    sid: int
    adder: int
    dur: float
    appeal: float
    added_t: float
    rnd: int = 0
    ups: int = 0
    downs: int = 0
    pushed_back: int = 0
    nexted: bool = False
    paid: int = 0


@dataclass
class Guest:
    gid: int
    w: float
    p_vote: float
    pick_q: float
    arrive: float
    leave: float
    wish_every: float
    credits: float = 0.0
    next_wish: float = 0.0
    wish_since: float = -1.0
    jailed: bool = False
    jailed_t: float = 0.0
    net: int = 0
    given: int = 0
    last_topup: float = 0.0
    played_n: int = 0
    # stats
    earned: dict = field(default_factory=lambda: dict(start=0, topup=0, votes=0, adder=0, tips=0))
    spent_add: int = 0
    spent_other: int = 0
    songs_added: int = 0
    votes: int = 0
    wishes: int = 0
    wish_more: int = 0
    afford_more: int = 0
    wish_waits: list = field(default_factory=list)   # minutes from wanting to adding
    afford_now: int = 0
    first_add_t: float = -1.0
    first_play_t: float = -1.0
    jail_count: int = 0
    jail_min: float = 0.0
    tips_given: int = 0
    ups_received: int = 0
    downs_received: int = 0
    present_min: float = 0.0


class Party:
    def __init__(self, n: int, p: Params, seed: int, record: bool = False):
        self.n, self.p = n, p
        # the master view's playback (simulate()): what happened, appended
        # as it happens — never a draw from the random stream
        self.record = record
        self.frames: list[dict] = []
        self.events: list[dict] = []
        self.songs_log: list[dict] = []
        self.cfg = p.economy
        self.rng = rng = np.random.default_rng(seed)
        w = rng.lognormal(0.0, 0.9, n)
        w = w / w.mean()
        # arrival spread grows with the party; small parties arrive together
        arr_win = 15 + 2.0 * n
        late_share = 0.15 * min(1.0, n / 20)
        early_leave = 0.30 * min(1.0, n / 15)
        tv = target_voters(n) * p.vote_scale * VOTE_CAL.get(n, 1.0)
        presence = 0.92 - 0.10 * min(1.0, n / 20)
        lo, hi = 0.0, 8.0
        for _ in range(40):
            c = (lo + hi) / 2
            if np.minimum(0.95, c * w).sum() * presence > tv:
                hi = c
            else:
                lo = c
        pv = np.minimum(0.95, c * w)
        self.guests: list[Guest] = []
        for i in range(n):
            late = rng.random() < late_share
            arrive = rng.uniform(75, 150) if late else rng.uniform(0, arr_win)
            leave = rng.uniform(150, p.party_min) if rng.random() < early_leave else p.party_min + 1
            leave = max(leave, min(p.party_min + 1, arrive + 45))
            wish = float(np.clip(p.wish_min / math.sqrt(max(w[i], 0.05)), 20, 180))
            g = Guest(gid=i, w=float(w[i]), p_vote=float(pv[i]),
                      pick_q=float(rng.normal(0.30, 0.55)), arrive=arrive, leave=leave,
                      wish_every=wish)
            g.next_wish = arrive + rng.exponential(wish * 0.4)
            g.last_topup = arrive
            self.guests.append(g)
        self.t = 0.0
        self._op: dict = {}
        self.queue: list[Song] = []
        self.sid = 0
        self.cycle = 0
        self.cur_rem = 0.0
        self._eta_cache = None
        self.minted = dict(start=0, topup=0, votes=0, adder=0, tip_bonus=0)
        self.spent = dict(add=0, bump_up=0, bump_down=0, next=0, skip=0, jail=0)
        self.transfers = 0
        self.c = dict(skip=0, skip_host=0, skip_chip=0, next=0, bump_up=0, bump_down=0, jail=0,
                      jail_out=0, tips=0, adds=0, juke_played=0, set_played=0,
                      empty_juke_slot=0, refunds=0, refused_late=0)
        self.queue_waits: list[float] = []
        self.add_prices: list[int] = []
        self.add_prices_first: list[int] = []
        self.wait_to_play: list[float] = []
        self.voters: list[int] = []
        self.skip_paid: list[int] = []
        self.next_paid: list[int] = []
        self.series: list[tuple] = []   # (t, held credits, back-of-queue wait, add price, jailed)

    # helpers ---------------------------------------------------------------
    def present(self, g: Guest) -> bool:
        return g.arrive <= self.t < g.leave

    def n_present(self) -> int:
        return sum(1 for g in self.guests if self.present(g))

    def opinion(self, g: Guest, s: Song) -> float:
        key = (g.gid, s.sid)
        r = self._op.get(key)
        if r is None:
            r = float(self.rng.normal(0, 0.9))
            self._op[key] = r
        return s.appeal + r

    def slot_is_juke(self, k: int) -> bool:
        if self.p.set_per_slot == 0:
            return True
        return (k % (self.p.set_per_slot + self.p.juke_per_slot)) >= self.p.set_per_slot

    def live(self) -> list[Song]:
        return [s for s in self.queue if not (s.adder >= 0 and self.guests[s.adder].jailed)]

    def etas(self) -> tuple[list[float], float]:
        """(start-in minutes for each live song, wait for a brand-new song at the back)."""
        if self._eta_cache is not None:
            return self._eta_cache
        q = self.live()
        out, tt, k, i = [], self.cur_rem, self.cycle, 0
        while i < len(q):
            if self.slot_is_juke(k):
                out.append(tt)
                tt += q[i].dur
                i += 1
            else:
                tt += SET_MEAN
            k += 1
        while not self.slot_is_juke(k):
            tt += SET_MEAN
            k += 1
        self._eta_cache = (out, tt)
        return self._eta_cache

    def dirty(self):
        self._eta_cache = None

    def wait_for_round(self, rnd: int) -> tuple[float, int]:
        """Wait and insertion index (in self.queue) for a new song of this round."""
        q = self.queue
        if not self.p.fair_order:
            return self.etas()[1], len(q)
        idx = len(q)
        for i, s in enumerate(q):
            if i == 0:
                continue  # never jump the song that's next
            if s.rnd > rnd:
                idx = i
                break
        # wait = eta of the live song currently at idx (or the back)
        live = self.live()
        etas, back = self.etas()
        if idx >= len(q):
            return back, idx
        target = q[idx]
        if target in live:
            return etas[live.index(target)], idx
        return back, idx

    # ── the REAL prices (services/jukebox/economy.py) ───────────────────────
    def add_price(self, wait: float, dur: float, ready: bool) -> int:
        return economy.add_price(wait, dur, ready, self.cfg)

    def crowd(self) -> float:
        return economy.crowd(self.n_present(), self.cfg)

    def skip_price(self, s: Song, queue_wait: float) -> int:
        return economy.skip_price(queue_wait, s.ups, s.downs, self.n_present(), self.cfg)

    # recording (record=True only; draws nothing, changes nothing) ----------
    def _ev(self, kind: str, **kw):
        if self.record:
            self.events.append(dict(t=round(self.t, 2), kind=kind, **kw))

    def _frame(self):
        if not self.record:
            return
        self.dirty()                      # leave the cache as cold as it was
        _, back = self.etas()
        self.dirty()
        self.frames.append(dict(
            t=round(self.t, 2), song=len(self.songs_log) - 1,
            cr=[int(round(g.credits)) for g in self.guests],
            back=round(back, 1), price=self.add_price(back, 3.6, True), line=len(self.live()),
            jailed=[g.gid for g in self.guests if g.jailed]))

    def grant(self, g: Guest, amt: float, kind: str, ekind: str):
        g.credits += amt
        self.minted[kind] += amt
        g.earned[ekind] += amt

    # the night ----------------------------------------------------------------
    def run(self) -> dict:
        p, rng = self.p, self.rng
        arrived = set()
        while self.t < p.party_min:
            for g in self.guests:
                if g.gid not in arrived and g.arrive <= self.t:
                    arrived.add(g.gid)
                    self.grant(g, p.start_credits, 'start', 'start')
            juke = self.slot_is_juke(self.cycle)
            song = None
            if juke:
                lv = self.live()
                if lv:
                    song = lv[0]
                    self.queue.remove(song)
                else:
                    self.c['empty_juke_slot'] += 1
            if song is None:
                song = Song(self.sid, -1, float(rng.lognormal(SONG_MU, SONG_SIGMA)),
                            float(rng.normal(0.45, 0.6)), self.t)
                self.sid += 1
                self.c['set_played'] += 1
            else:
                self.c['juke_played'] += 1
                self.wait_to_play.append(self.t - song.added_t)
                ad = self.guests[song.adder]
                ad.played_n += 1
                if ad.first_play_t < 0:
                    ad.first_play_t = self.t
            self.cycle += 1
            self.dirty()
            held = sum(g.credits for g in self.guests if self.present(g))
            self.cur_rem = song.dur
            _, back = self.etas()
            self.series.append((self.t, held, back, self.add_price(back, 3.6, True),
                                sum(1 for g in self.guests if g.jailed),
                                sum(1 for g in self.guests if self.present(g))))
            if self.record:
                self.songs_log.append(dict(t=round(self.t, 2), dur=round(song.dur, 2),
                                           by=song.adder if song.adder >= 0 else None))
                self._frame()
            self.play(song)
        for s in self.queue:
            if s.adder >= 0 and s.paid:
                self.guests[s.adder].credits += s.paid
                self.c['refunds'] += 1
                self._ev('refund', g=s.adder, amt=s.paid)
        self._frame()
        return self.summary()

    def play(self, s: Song):
        p, rng = self.p, self.rng
        start = self.t
        cps = [0.15, 0.35, 0.55, 0.75, 0.95]
        vote_at = {}
        for g in self.guests:
            if self.present(g) and g.gid != s.adder and rng.random() < g.p_vote:
                vote_at[g.gid] = int(rng.integers(0, 3))
        nvotes = 0
        tipped: dict[int, int] = {}
        skipped = False
        last = 0
        for ci, frac in enumerate(cps):
            last = ci
            self.t = start + frac * s.dur
            self.cur_rem = s.dur * (1 - frac)
            self.dirty()
            for gid, at in vote_at.items():
                if at != ci:
                    continue
                g = self.guests[gid]
                if not self.present(g):
                    continue
                nvotes += 1
                op = self.opinion(g, s)
                up = op > -0.15
                g.votes += 1
                self.grant(g, p.vote_reward, 'votes', 'votes')
                if up:
                    s.ups += 1
                else:
                    s.downs += 1
                if s.adder >= 0:
                    ad = self.guests[s.adder]
                    if up:
                        self.grant(ad, p.adder_up_reward, 'adder', 'adder')
                        ad.ups_received += 1
                        ad.net -= 1
                    else:
                        ad.downs_received += 1
                        ad.net += 1
                    thr = economy.jail_threshold(self.n_present(), self.cfg)
                    if not ad.jailed and ad.net >= thr:
                        ad.jailed, ad.jailed_t = True, self.t
                        ad.jail_count += 1
                        self.c['jail'] += 1
                        self.dirty()
                        self._ev('jail', g=ad.gid, downs=thr)
                    if up and op > 0.6 and rng.random() < p.p_tip * min(1.6, g.w ** 0.5):
                        units = 1 if op < 1.4 else 2
                        units = min(units, economy.tip_units_allowed(tipped.get(gid, 0), self.cfg))
                        amt = units * p.tip_unit
                        if units > 0 and g.credits - amt >= 2:
                            g.credits -= amt
                            g.tips_given += amt
                            tipped[gid] = tipped.get(gid, 0) + units
                            dbl = economy.tip_bonus(g.given, amt, self.cfg)
                            g.given += amt
                            ad.credits += amt
                            ad.earned['tips'] += amt
                            self.transfers += amt
                            if dbl:
                                self.grant(ad, dbl, 'tip_bonus', 'tips')
                            self.c['tips'] += 1
                            self._ev('tip', g=gid, to=ad.gid, amt=amt, bonus=dbl)
            if ci in (2, 3) and not skipped:
                _, back = self.etas()
                price = self.skip_price(s, back)
                haters = [g for g in self.guests if self.present(g) and g.gid != s.adder
                          and self.opinion(g, s) < -0.7]
                bought = None
                if haters:
                    rng.shuffle(haters)
                    for g in haters:
                        if g.credits >= price + 2 and rng.random() < p.p_skip * min(1.6, g.w ** 0.5):
                            bought = [(g, price)]
                            break
                    if bought is None and p.chip_in and len(haters) >= 2:
                        pledges = [(g, int(max(0, min(g.credits - 2, g.credits * 0.5))))
                                   for g in haters if rng.random() < 0.5]
                        if len([x for _, x in pledges if x > 0]) >= 2 and sum(x for _, x in pledges) >= price \
                                and rng.random() < p.p_skip:
                            bought, left = [], price
                            for g, x in sorted(pledges, key=lambda z: -z[1]):
                                share = min(x, left)
                                if share > 0:
                                    bought.append((g, share))
                                    left -= share
                                if left <= 0:
                                    break
                            self.c['skip_chip'] += 1
                if bought:
                    for g, amt in bought:
                        g.credits -= amt
                        g.spent_other += amt
                    self.spent['skip'] += price
                    self.c['skip'] += 1
                    if s.adder < 0:
                        self.c['skip_host'] += 1
                    self.skip_paid.append(price)
                    skipped = True
                    self._ev('skip', price=price, payers=[g.gid for g, _a in bought],
                             of=s.adder if s.adder >= 0 else None)
            for g in self.guests:
                if self.present(g):
                    self.act(g)
            self._frame()
            if skipped:
                break
        self.voters.append(nvotes)
        if self.record and self.songs_log:
            self.songs_log[-1].update(ups=s.ups, downs=s.downs,
                                      skipped=round(self.t, 2) if skipped else None)
        self.t = start + (cps[last] if skipped else 1.0) * s.dur

    def act(self, g: Guest):
        p, rng = self.p, self.rng
        while self.t - g.last_topup >= p.topup_every_min:
            g.last_topup += p.topup_every_min
            up = economy.topup_amount(int(g.credits), self.cfg)
            if up:
                self.grant(g, up, 'topup', 'topup')
        if g.jailed:
            mine = any(s.adder == g.gid for s in self.queue)
            if (mine or self.t >= g.next_wish) and g.credits >= p.jail_fee and rng.random() < 0.7:
                g.credits -= p.jail_fee
                g.spent_other += p.jail_fee
                self.spent['jail'] += p.jail_fee
                g.jailed = False
                g.net = 0
                g.jail_min += self.t - g.jailed_t
                self.c['jail_out'] += 1
                self.dirty()
                self._ev('jail_out', g=g.gid, fee=p.jail_fee)
            else:
                return
        waiting = [s for s in self.queue if s.adder == g.gid]
        etas, back = self.etas()
        self.queue_waits.append(back)
        if self.t >= g.next_wish and len(waiting) < p.max_waiting and self.t < p.party_min - p.last_call_min:
            rnd = g.played_n + len(waiting) + 1
            wait, idx = self.wait_for_round(rnd)
            if g.wish_since < 0:
                g.wish_since = self.t
                g.wishes += 1
                first_look = True
            else:
                first_look = False
            dur = float(rng.lognormal(SONG_MU, SONG_SIGMA))
            ready = rng.random() < p.ready_share
            price = self.add_price(wait, dur, ready)
            if wait > p.party_min - self.t:
                self.c['refused_late'] += 1
                self._ev('too_late', g=g.gid, wait=round(wait, 1))
                g.next_wish = self.t + 10
                g.wish_since = -1
                return
            if first_look:
                self.add_prices.append(price)
                if rnd == 1:
                    self.add_prices_first.append(price)
                if g.credits >= price:
                    g.afford_now += 1
                if waiting:
                    g.wish_more += 1
                    g.afford_more += 1 if g.credits >= price else 0
            if g.credits >= price:
                g.credits -= price
                g.spent_add += price
                self.spent['add'] += price
                s = Song(self.sid, g.gid, dur, float(rng.normal(g.pick_q, 0.7)), self.t,
                         rnd=rnd, paid=price)
                self.sid += 1
                self.queue.insert(idx, s)
                self.dirty()
                g.songs_added += 1
                if g.first_add_t < 0:
                    g.first_add_t = self.t
                self.c['adds'] += 1
                self._ev('add', g=g.gid, price=price, wait=round(wait, 1), rnd=rnd)
                g.wish_waits.append(self.t - g.wish_since)
                g.wish_since = -1
                g.next_wish = self.t + rng.exponential(g.wish_every)
            return
        if not self.queue:
            return
        live = self.live()
        reserve = self.add_price(back, 3.6, True)
        for s in waiting:
            if s.nexted or s not in live:
                continue
            i = live.index(s)
            if i == 0 or not economy.play_next_allowed(etas[i], s.nexted, self.cfg):
                continue
            price = economy.play_next_price(etas[i], self.cfg)
            if g.credits >= price + 3 and rng.random() < p.p_next * min(1.6, g.w ** 0.5):
                g.credits -= price
                g.spent_other += price
                self.spent['next'] += price
                self.c['next'] += 1
                self.next_paid.append(price)
                self._ev('next', g=g.gid, price=price, jump=round(etas[i], 1))
                self.queue.remove(s)
                self.queue.insert(self.queue.index(live[0]), s)
                s.nexted = True
                self.dirty()
                return
        for s in waiting:
            if s not in live:
                continue
            i = live.index(s)
            if i <= 1 or etas[i] < 12:
                continue
            behind = len(live) - 1 - i
            price = economy.bump_up_price(behind, self.cfg)
            if g.credits >= price + reserve and rng.random() < p.p_bump_up * min(1.6, g.w ** 0.5):
                g.credits -= price
                g.spent_other += price
                self.spent['bump_up'] += price
                self.c['bump_up'] += 1
                self._ev('bump_up', g=g.gid, price=price)
                j, k = self.queue.index(s), self.queue.index(live[i - 1])
                self.queue[j], self.queue[k] = self.queue[k], self.queue[j]
                self.dirty()
                return
        for i, s in enumerate(live):
            if s.adder == g.gid or not economy.can_push_back(s.pushed_back, self.cfg) or i >= len(live) - 1:
                continue
            if self.opinion(g, s) > -1.3:
                continue
            price = economy.bump_down_price(i, self.cfg)
            if g.credits >= price + reserve and rng.random() < p.p_bump_down * min(1.6, g.w ** 0.5):
                g.credits -= price
                g.spent_other += price
                self.spent['bump_down'] += price
                self.c['bump_down'] += 1
                self._ev('bump_down', g=g.gid, price=price, of=s.adder if s.adder >= 0 else None)
                j, k = self.queue.index(s), self.queue.index(live[i + 1])
                self.queue[j], self.queue[k] = self.queue[k], self.queue[j]
                s.pushed_back += 1
                self.dirty()
                return

    def summary(self) -> dict:
        gs, n = self.guests, self.n
        hrs = self.p.party_min / 60
        for g in gs:
            g.present_min = max(0.0, min(g.leave, self.p.party_min) - g.arrive)
        played = np.array([g.played_n for g in gs])
        wanted = [g for g in gs if g.wishes > 0]
        core = [g for g in gs if g.p_vote >= 0.45]
        lurk = [g for g in gs if g.p_vote < 0.15]
        mid = [g for g in gs if 0.15 <= g.p_vote < 0.45]

        def got(group):
            grp = [g for g in group if g.wishes > 0]
            return float(np.mean([g.played_n > 0 for g in grp])) if grp else float('nan')

        def first_wait(group):
            vals = [g.first_play_t - g.arrive for g in group if g.first_play_t >= 0]
            return float(np.median(vals)) if vals else float('nan')

        def earn_rate(group):
            vals = [(g.earned['votes'] + g.earned['adder'] + g.earned['tips']) / max(0.5, g.present_min / 60)
                    for g in group]
            return float(np.mean(vals)) if vals else float('nan')

        ww = [w for g in gs for w in g.wish_waits]
        minted = sum(self.minted.values())
        end_bal = np.array([g.credits for g in gs])
        ap = np.array(self.add_prices) if self.add_prices else np.array([np.nan])
        apf = np.array(self.add_prices_first) if self.add_prices_first else np.array([np.nan])
        qw = np.array(self.queue_waits) if self.queue_waits else np.array([0.0])
        wp = np.array(self.wait_to_play) if self.wait_to_play else np.array([np.nan])
        srt = np.sort(played)
        gini = 0.0
        if played.sum() > 0:
            cum = np.cumsum(srt)
            gini = float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)
        mid_series = [h for (t, h, *_r) in self.series if 60 <= t <= 200]
        mid_price = [pr for (t, h, b, pr, j, *_x) in self.series if 60 <= t <= 200]
        return dict(
            n=n, voters_per_song=float(np.mean(self.voters)),
            songs=self.c['juke_played'] + self.c['set_played'],
            juke_played=self.c['juke_played'], set_played=self.c['set_played'],
            empty_juke_slots=self.c['empty_juke_slot'],
            minted=minted, spent=sum(self.spent.values()), transfers=self.transfers,
            minted_by=dict(self.minted), spent_by=dict(self.spent),
            end_bal_median=float(np.median(end_bal)),
            unspent_share=float(end_bal.sum() / max(1, minted)),
            held_mid_per_guest=float(np.mean(mid_series) / max(1, n)) if mid_series else float('nan'),
            price_mid=float(np.mean(mid_price)) if mid_price else float('nan'),
            add_price_median=float(np.nanmedian(ap)), add_price_p90=float(np.nanpercentile(ap, 90)),
            add_price_first_median=float(np.nanmedian(apf)),
            afford_rate=float(sum(g.afford_now for g in gs) / max(1, sum(g.wishes for g in gs))),
            afford_empty=float((sum(g.afford_now for g in gs) - sum(g.afford_more for g in gs)) / max(1, sum(g.wishes for g in gs) - sum(g.wish_more for g in gs))),
            afford_more=float(sum(g.afford_more for g in gs) / max(1, sum(g.wish_more for g in gs))) if sum(g.wish_more for g in gs) else float('nan'),
            more_share=float(sum(g.wish_more for g in gs) / max(1, sum(g.wishes for g in gs))),
            wish_wait_median=float(np.median(ww)) if ww else float('nan'),
            wish_wait_p90=float(np.percentile(ww, 90)) if ww else float('nan'),
            back_wait_median=float(np.median(qw)), back_wait_p90=float(np.percentile(qw, 90)),
            wait_to_play_median=float(np.nanmedian(wp)), wait_to_play_p90=float(np.nanpercentile(wp, 90)),
            got_played=got(gs), got_played_lurk=got(lurk), got_played_mid=got(mid), got_played_core=got(core),
            first_song_wait_lurk=first_wait(lurk), first_song_wait_all=first_wait(gs),
            n_core=len(core), n_mid=len(mid), n_lurk=len(lurk),
            songs_per_guest=float(played.mean()), songs_per_core=float(np.mean([g.played_n for g in core])) if core else float('nan'),
            songs_per_lurk=float(np.mean([g.played_n for g in lurk])) if lurk else float('nan'),
            gini=gini,
            skips_hr=self.c['skip'] / hrs, skips_host_hr=self.c['skip_host'] / hrs,
            skip_chip_share=self.c['skip_chip'] / max(1, self.c['skip']),
            nexts_hr=self.c['next'] / hrs, bump_up_hr=self.c['bump_up'] / hrs,
            bump_down_hr=self.c['bump_down'] / hrs, tips_hr=self.c['tips'] / hrs,
            jails=self.c['jail'], jail_outs=self.c['jail_out'],
            jail_min=float(np.mean([g.jail_min / g.jail_count for g in gs if g.jail_count])) if any(g.jail_count for g in gs) else float('nan'),
            refunds=self.c['refunds'], refused_late=self.c['refused_late'],
            earn_core_hr=earn_rate(core), earn_mid_hr=earn_rate(mid), earn_lurk_hr=earn_rate(lurk),
            skip_paid=float(np.median(self.skip_paid)) if self.skip_paid else float('nan'),
            next_paid=float(np.median(self.next_paid)) if self.next_paid else float('nan'),
        )


def run_many(n: int, p: Params, seeds: int = 60, base_seed: int = 1, keep=False):
    rows = []
    parties = []
    for s in range(seeds):
        pa = Party(n, p, base_seed * 100003 + s)
        rows.append(pa.run())
        if keep:
            parties.append(pa)
    out = {}
    for k, v0 in rows[0].items():
        if isinstance(v0, dict):
            out[k] = {kk: float(np.mean([r[k][kk] for r in rows])) for kk in v0}
        else:
            vals = np.array([r[k] for r in rows], dtype=float)
            out[k] = float(np.nanmean(vals)) if not np.all(np.isnan(vals)) else float('nan')
    return (out, parties) if keep else out


# ── the plan's presets, and the shipped settings ─────────────────────────────

# Rule fields of Params that are economy settings by the same name.
SHARED = ("start_credits", "topup_every_min", "topup_cap", "vote_reward", "adder_up_reward",
          "tip_unit", "tip_max_per_song", "gift_double_first", "jail_net_downs", "jail_fee",
          "jail_scale", "add_base", "add_free_min", "add_double_min", "add_cap",
          "long_extra_per_min", "learn_first_extra", "bump_up_base", "bump_up_per_behind",
          "bump_down_base", "bump_down_per_ahead", "bump_down_max_places", "next_base",
          "next_per_min", "skip_max", "skip_half_min", "skip_floor", "skip_crowd", "skip_min",
          "chip_in", "max_waiting", "fair_order")


def plan_preset(n: int) -> str:
    """The plan's preset for a party of `n` (report §3.5; services/jukebox/
    show.PRESETS carries the same three)."""
    return "small" if n <= 8 else "medium" if n <= 16 else "large"


def program(n: int) -> dict:
    """The plan's jukebox share by party size (D3; report §3.5)."""
    if n <= 8:
        return dict(set_per_slot=1, juke_per_slot=1)   # every other
    if n <= 16:
        return dict(set_per_slot=1, juke_per_slot=2)   # two per set song
    return dict(set_per_slot=0, juke_per_slot=1)       # jukebox first


def params_for(n: int, cfg: EconomyConfig | None = None) -> Params:
    """A night at `n` guests under `cfg` (default: the SHIPPED settings)."""
    cfg = cfg or EconomyConfig()
    rules = {k: getattr(cfg, k) for k in SHARED}
    rules["skip_down_mult"] = economy.skip_down_mult(cfg)
    return replace(Params(), economy=cfg, **rules, **program(n))


# ── the master view's party simulator (phase 3 PR 3.4) ───────────────────────

GUESTS_MIN, GUESTS_MAX = 2, 40
NIGHTS_MIN, NIGHTS_MAX = 1, 40


def _clean(v):
    """JSON-safe: a NaN (a measure with nothing to measure) is None."""
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 4)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def program_mix(mode: str, every: int, run: int, n: int) -> tuple[dict, str]:
    """His program as the simulator's slot pattern, and how to say it. A
    Manual program's slots sit after particular songs of his playlist,
    which a model night does not have, so it plays the plan's mix for the
    party size instead — and says so."""
    if mode == "jukebox_first":
        return dict(set_per_slot=0, juke_per_slot=1), "jukebox first; the set fills any gap"
    if mode == "auto":
        sets = "every set song" if every == 1 else f"every {every} set songs"
        juke = "a jukebox song" if run == 1 else f"{run} jukebox songs"
        return dict(set_per_slot=every, juke_per_slot=run), f"{juke} after {sets}"
    mix = program(n)
    _, plan_words = program_mix("auto" if mix["set_per_slot"] else "jukebox_first",
                                max(1, mix["set_per_slot"]), mix["juke_per_slot"], n)
    return mix, (f"your program is Manual (slots placed after particular songs), which a model "
                 f"night has no playlist for — this night uses the plan's mix for {n} guests: "
                 f"{plan_words}")


def night_params(n: int, cfg: EconomyConfig, mix: dict) -> Params:
    """A night at `n` guests under `cfg`, with the given slot pattern. The
    night is the model's four hours: its arrivals and early leavers are
    timed for that length, so it is not a setting."""
    return replace(params_for(n, cfg), **mix)


def _guest_kind(g: Guest) -> str:
    if g.p_vote >= 0.45:
        return "regular"
    if g.p_vote < 0.15:
        return "quiet"
    return "middle"


def recording(party: Party, summary: dict) -> dict:
    """One recorded night as the page plays it back."""
    end = party.p.party_min
    guests = [dict(id=g.gid, kind=_guest_kind(g), arrive=round(g.arrive, 1),
                   leave=round(min(g.leave, end), 1), played=g.played_n, added=g.songs_added,
                   earned=int(sum(g.earned.values())), spent=int(g.spent_add + g.spent_other),
                   tips_given=g.tips_given, jails=g.jail_count, end_credits=int(round(g.credits)))
              for g in party.guests]
    return _clean(dict(minutes=end, last_call=end - party.p.last_call_min, guests=guests,
                       songs=party.songs_log, frames=party.frames, events=party.events,
                       summary=summary))


# What the page compares, his settings against the tuned ones — the plan's
# §3.2 rows, in its words.
ROWS = (
    ("got_played", "Got at least one song (of those who asked)", "share"),
    ("juke_played", "Guest songs played in the night", "count"),
    ("first_song_wait_all", "First song, from arriving (median)", "min"),
    ("add_price_median", "Add price when they want one (median)", "credits"),
    ("price_mid", "Price at the back of the line, mid-party", "credits"),
    ("afford_rate", "Can afford it right away (all requests)", "share"),
    ("afford_empty", "… with nothing already in line", "share"),
    ("wait_to_play_median", "Add to play (median)", "min"),
    ("back_wait_p90", "Back of the line, p90", "min"),
    ("skips_hr", "Skips an hour", "rate"),
    ("nexts_hr", "Play next an hour", "rate"),
    ("tips_hr", "Tips an hour", "rate"),
    ("jails", "Jails a night", "count"),
    ("songs_per_lurk", "Songs per quiet guest", "count"),
    ("held_mid_per_guest", "Credits held per guest, mid-party", "credits"),
    ("unspent_share", "Credits unspent at the end", "share"),
    ("refused_late", "Turned away as too late (a night)", "count"),
)

# The promises the plan's tuning keeps at every party size (§3.1, §3.4,
# §3.6) — what a change of settings should not break.
CHECKS = (
    ("got_played", "Everyone who asks gets a song", lambda v: v >= 0.995, "100%"),
    ("wait_to_play_median", "Median wait to play, 30 min or less", lambda v: v <= 30.5, "≤ 30 min"),
    ("back_wait_p90", "Back of the line, 75 min or less (p90)", lambda v: v <= 75.5, "≤ 75 min"),
    ("songs_per_lurk", "Quiet guests get a song", lambda v: v >= 1.0, "≥ 1 song"),
    ("skips_hr", "Skips stay under two an hour", lambda v: v < 2.0, "< 2 an hour"),
)


def simulate(guests: int, cfg: EconomyConfig, *, mode: str = "auto", every: int = 1,
             run: int = 1, seed: int = 1, nights: int = 20) -> dict:
    """One party night under his settings, recorded for the page, plus the
    average of `nights` nights (the watched night is the first of them)
    under his settings AND under the tuned defaults, on the same guests,
    seeds and program — so a change he made shows as a difference."""
    if not GUESTS_MIN <= guests <= GUESTS_MAX:
        raise ValueError(f"guests must be {GUESTS_MIN}-{GUESTS_MAX}")
    if not NIGHTS_MIN <= nights <= NIGHTS_MAX:
        raise ValueError(f"nights must be {NIGHTS_MIN}-{NIGHTS_MAX}")
    mix, words = program_mix(mode, every, run, guests)
    yours = night_params(guests, cfg, mix)
    party = Party(guests, yours, seed * 100003, record=True)
    night = recording(party, party.run())
    avg = run_many(guests, yours, seeds=nights, base_seed=seed)
    tuned_cfg = EconomyConfig()
    same = cfg == tuned_cfg
    tuned = avg if same else run_many(guests, night_params(guests, tuned_cfg, mix),
                                      seeds=nights, base_seed=seed)
    rows = [dict(key=k, label=label, unit=unit, yours=_clean(avg.get(k)), tuned=_clean(tuned.get(k)))
            for k, label, unit in ROWS]
    checks = []
    for k, label, ok, target in CHECKS:
        v = avg.get(k)
        known = isinstance(v, (int, float)) and not math.isnan(v)
        checks.append(dict(key=k, label=label, target=target, value=_clean(v) if known else None,
                           ok=bool(ok(v)) if known else None))
    return dict(guests=guests, nights=nights, seed=seed, program=words, mix=mix,
                plan_preset=plan_preset(guests), mix_is_plans=mix == program(guests),
                same_as_tuned=same, night=night, rows=rows, checks=checks)
