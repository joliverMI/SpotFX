"""
SpotFX — the Jukebox's credits economy: every PRICE and every EARNING rule
of the plan's rulebook (data/jukebox-plan/report.md §1, tuned in §3 for two
songs in line, D4), pure — numbers in, numbers out, no I/O, no clock.

THE SIMULATOR IS THE SPEC. Each function is the planning simulator's own
formula (the report's Appendix A, `jukesim2.py`), rounding included —
Python's `round` (half to even) where it rounds, a ceiling where it counts
"per 4 songs" or "per 4 minutes", so a single song behind already costs the
+1. tests/jukebox_economy_sim.py is that simulator with its prices replaced
by THESE functions, and tests/test_jukebox_economy.py holds it to the plan's
§3.2 results at 4, 8, 15 and 30 guests: a price function that drifts from
the tuned one moves the night it produces, and the test sees it.

Credits are free, have no cash value and never leave the night (§2.1):
nothing here knows about money, and nothing ever will.

The settings are models.jukebox.EconomyConfig (§4's every economy setting,
the tuned values as defaults). "Guests" in the crowd-scaled rules is the
phones seen in the last 15 minutes — the caller's count, passed in.
"""
from __future__ import annotations

import math

from models.jukebox import EconomyConfig

# Active voters per song the plan calibrated against: 3 of 4 at a small
# party, ~6 at 30 (his numbers; report §3.1). Skip's per-▼ discount and
# jail's threshold scale with it, so a bigger room's ▼ count for less each.
VOTERS_AT_4 = 3.0
VOTERS_EXPONENT = 0.345
CROWD_REF = 8.0                     # skip prices are quoted for a room of 8
CROWD_MIN, CROWD_MAX = 0.75, 2.0


def expected_voters(present: int) -> float:
    """The voters a song typically gets in a room of `present` guests."""
    return VOTERS_AT_4 * (max(4, int(present)) / 4.0) ** VOTERS_EXPONENT


def crowd(present: int, cfg: EconomyConfig) -> float:
    """Skip's room factor: √(guests ÷ 8), held to 0.75-2."""
    if not cfg.skip_crowd:
        return 1.0
    return min(CROWD_MAX, max(CROWD_MIN, math.sqrt(max(1, int(present)) / CROWD_REF)))


# ── adding a song ────────────────────────────────────────────────────────────

def add_price(wait_min: float, duration_min: float, ready: bool, cfg: EconomyConfig) -> int:
    """§1 rule 5. `wait_min` is how long until the song would play. The base
    price holds while the wait is under `add_free_min`, then doubles every
    `add_double_min` of wait (never above `add_cap`); +1 per STARTED minute
    over 5:00; +1 if the lights haven't learned it yet."""
    over = max(0.0, float(wait_min) - cfg.add_free_min)
    base = (cfg.add_base * 2.0 ** (over / cfg.add_double_min)
            if cfg.add_double_min > 0 else float(cfg.add_base))
    base = min(cfg.add_cap, int(round(base)))
    extra = 0
    if duration_min > cfg.long_over_min:
        extra += cfg.long_extra_per_min * math.ceil(duration_min - cfg.long_over_min)
    if not ready:
        extra += cfg.learn_first_extra
    return int(base + extra)


# ── bumps and play next ──────────────────────────────────────────────────────

def bump_up_price(behind: int, cfg: EconomyConfig) -> int:
    """§1 rule 6: up one place — dearer near the front (more songs behind)."""
    return int(cfg.bump_up_base + math.ceil(cfg.bump_up_per_behind * max(0, int(behind))))


def bump_down_price(ahead: int, cfg: EconomyConfig) -> int:
    """§1 rule 6: down one place — dearer near the back (more songs ahead)."""
    return int(cfg.bump_down_base + math.ceil(cfg.bump_down_per_ahead * max(0, int(ahead))))


def can_push_back(pushed_back_so_far: int, cfg: EconomyConfig) -> bool:
    return int(pushed_back_so_far) < cfg.bump_down_max_places


def play_next_price(jump_min: float, cfg: EconomyConfig) -> int:
    """§1 rule 7: to the front of the jukebox line, by how far it jumps."""
    return int(cfg.next_base + math.ceil(cfg.next_per_min * max(0.0, float(jump_min))))


def play_next_allowed(eta_min: float, already_nexted: bool, cfg: EconomyConfig) -> bool:
    """Only for a song at least `next_min_away_min` away, once per song."""
    return not already_nexted and float(eta_min) >= cfg.next_min_away_min


# ── skip ─────────────────────────────────────────────────────────────────────

def skip_down_mult(cfg: EconomyConfig) -> float:
    return 1.0 - cfg.skip_down_pct / 100.0


def skip_price(queue_wait_min: float, ups: int, downs: int, present: int,
               cfg: EconomyConfig) -> int:
    """§1 rule 8. `skip_max` with nothing waiting, halving as the line reaches
    `skip_half_min`, never below `skip_floor` — both × the room factor; each
    net ▼ takes `skip_down_pct` off, weighted by how many vote in a room this
    size; never below `skip_min`."""
    cr = crowd(present, cfg)
    base = max(cfg.skip_floor * cr,
               cfg.skip_max * cr * cfg.skip_half_min / (cfg.skip_half_min + max(0.0, queue_wait_min)))
    net_down = max(0, int(downs) - int(ups))
    expo = net_down * VOTERS_AT_4 / max(VOTERS_AT_4, expected_voters(max(4, present)))
    return int(max(cfg.skip_min, round(base * skip_down_mult(cfg) ** expo)))


def skip_allowed(played_s: float, cfg: EconomyConfig) -> bool:
    """No skip in the first `skip_grace_s` of a song (stops mis-taps)."""
    return float(played_s) >= cfg.skip_grace_s


# ── jail ─────────────────────────────────────────────────────────────────────

def jail_threshold(present: int, cfg: EconomyConfig) -> int:
    """§1 rule 9: net ▼ on your songs tonight that sends you to jail — 5 at
    a small party, rising with the crowd (6 at 8, 8 at 15, 10 at 30)."""
    if not cfg.jail_scale:
        return cfg.jail_net_downs
    return int(round(cfg.jail_net_downs * max(1.0, expected_voters(max(4, present)) / VOTERS_AT_4)))


def jailed(net_downs: int, present: int, cfg: EconomyConfig) -> bool:
    return int(net_downs) >= jail_threshold(present, cfg)


# ── earning ──────────────────────────────────────────────────────────────────

def start_grants(cfg: EconomyConfig) -> tuple[int, int, float]:
    """The first-visit credits as (now, later, after_min): half at once and
    the rest after `start_rest_after_min` on the page (so clearing cookies
    for a fresh start buys little)."""
    now = (cfg.start_credits + 1) // 2
    return now, cfg.start_credits - now, cfg.start_rest_after_min


def topup_amount(balance: int, cfg: EconomyConfig) -> int:
    """+1 at each top-up while here; paused while you hold `topup_cap` or
    more (earning itself has no cap)."""
    if cfg.topup_every_min <= 0:
        return 0
    return 1 if int(balance) < cfg.topup_cap else 0


def tip_units_allowed(already_tipped_on_song: int, cfg: EconomyConfig) -> int:
    """How many more 1-credit taps this giver may put on this song."""
    if not cfg.tips:
        return 0
    return max(0, cfg.tip_max_per_song - int(already_tipped_on_song))


def tip_bonus(given_tonight: int, amount: int, cfg: EconomyConfig) -> int:
    """§1 rule 4: the first `gift_double_first` credits a guest gives in a
    night arrive doubled — the bonus is the part of THIS gift that still
    falls inside that allowance."""
    return max(0, min(int(amount), cfg.gift_double_first - int(given_tonight)))
