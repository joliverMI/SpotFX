"""
SpotFX — the Jukebox's WALLET (data/jukebox-plan/report.md §1 and §7, phase 3
PR 3.2): credits mode as the guest page lives it — what a phone holds, what
it earns as the night goes on, what each thing costs right now, and its
history in words. services/jukebox/guests.py decides what a guest may do;
this module is the credits side of it.

THE LEDGER IS THE TRUTH (services/jukebox/ledger.py, one append-only file per
night). Nothing here stores a balance; every grant, earning, tip, spend and
refund is a ledger entry, and every number the page shows is read back from
it. The ledger's own rules (never below zero, a vote paid once, a tip never to
the host or yourself, the double-first bonus capped, a refund once) refuse a
bad write before anything is written.

EARNING, as §1 rule 1-4 says and the plan's simulator does:
  * the first-visit credits — half when the phone taps "Let's go", the rest
    after `start_rest_after_min` on the page (so a cookie reset buys little);
  * a top-up of +1 every `topup_every_min` while the phone is here (it polled
    within the last 15 minutes), paused while it holds `topup_cap` or more;
    a phone that was away doesn't get the missed top-ups;
  * +`vote_reward` for voting on a song, once per play;
  * +`adder_up_reward` per ▲ on a guest's song, paid once it has played;
  * tips, with the first `gift_double_first` credits a giver gives doubled.
Every grant is checked on the phone's own polls (`tick`), so nothing runs on a
timer and a restart loses nothing: what was granted is in the ledger.

PRICES are services/jukebox/economy.py's, worked from the night as it stands:
the add price from when the new song would start (`JukeboxRunner.quote_wait`),
the skip price from the wait for a song added at the back now, the ▲ and ▼ on
the song, and the room (phones seen in the last 15 minutes); a bump's from the
songs behind or ahead of it; play next's from how far it jumps.

Every ledger write goes through `to_thread` (it fsyncs) — never on the loop
that runs the music.
"""
from __future__ import annotations

from typing import Any, Optional

from models.jukebox import EconomyConfig
from services.jukebox import economy, ledger as ledger_mod


WORDS: dict[str, str] = {
    "start": "Welcome credits",
    "start_rest": "The rest of your welcome credits",
    "topup": "A top-up for being here",
    "qr_bonus": "A bonus card",
    "host_gift": "From the host",
    "vote": "For voting",
    "adder_up": "▲ on your song",
    "tip_in": "A tip on your song",
    "tip_bonus": "Tip bonus (the first credits given count double)",
    "tip_out": "You tipped",
    "add": "Added a song",
    "bump_up": "Moved your song up",
    "bump_down": "Moved a song down",
    "play_next": "Played your song next",
    "skip": "Skipped a song",
    "skip_pledge": "Chipped in to skip",
    "jail_breakout": "Broke out of jail",
    "refund": "Refund",
}
EARN_GROUPS: dict[str, tuple[str, ...]] = {
    "free": ("start", "start_rest", "topup", "qr_bonus", "host_gift"),
    "votes": ("vote",),
    "your songs": ("adder_up",),
    "tips": ("tip_in", "tip_bonus"),
}
DISCLAIMER = ("Credits are free and only for tonight. They can't be bought, sold, traded "
              "or cashed out.")
HOW_TO_EARN = (
    "+1 for each song you vote on",
    "+1 for every ▲ your song gets",
    "Tips from the room when they love your song (the first credits given count double)",
    "A free top-up every 45 minutes you're here",
)


# ── pure: prices and words ───────────────────────────────────────────────────

def minutes(ms: Optional[int]) -> float:
    return max(0.0, (ms or 0) / 60_000)


def add_price(wait_ms: Optional[int], duration_ms: int, known: bool, cfg: EconomyConfig) -> int:
    return economy.add_price(minutes(wait_ms), duration_ms / 60_000, known, cfg)


def skip_price(back_wait_ms: Optional[int], ups: int, downs: int, present: int,
               cfg: EconomyConfig) -> int:
    return economy.skip_price(minutes(back_wait_ms), ups, downs, present, cfg)


def bump_prices(movable_ids: list[str], entry_id: str, cfg: EconomyConfig) -> tuple[int, int]:
    """(up, down) for one waiting song: up by the songs behind it, down by
    the songs ahead of it."""
    i = movable_ids.index(entry_id)
    return (economy.bump_up_price(len(movable_ids) - 1 - i, cfg),
            economy.bump_down_price(i, cfg))


def next_quote(eta_ms: Optional[int], front_eta_ms: Optional[int], nexted: bool,
               cfg: EconomyConfig) -> dict:
    """Play next for one of your songs: its price by how far it jumps, and
    whether it is allowed (at least `next_min_away_min` away, once per song)."""
    eta = minutes(eta_ms)
    jump = max(0.0, eta - minutes(front_eta_ms))
    ok = eta_ms is not None and economy.play_next_allowed(eta, nexted, cfg)
    why = ("" if ok else "It has had its play next." if nexted else
           f"Only for a song at least {int(cfg.next_min_away_min)} minutes away.")
    return {"price": economy.play_next_price(jump, cfg), "allowed": ok, "why": why,
            "jump_min": round(jump, 1)}


def history_rows(entries: list[Any], names: dict[str, str], titles: dict[str, str]) -> list[dict]:
    """One phone's ledger entries as the Shop's history, newest first: what,
    how much (signed), when, and a word about it (the song, who tipped)."""
    out = []
    for e in reversed(entries):
        detail = ""
        if e.kind in ("tip_in",):
            detail = f"from {names.get(e.note, 'a guest')}"
        elif e.kind == "tip_out":
            detail = f"to {names.get(e.note, 'a guest')}"
        elif e.kind == "adder_up":
            detail = e.note
        song = titles.get(e.ref.split("@", 1)[0], "") or titles.get(e.ref, "")
        if song and e.kind not in ("start", "start_rest", "topup"):
            detail = f"{song} · {detail}" if detail else song
        out.append({"seq": e.seq, "at_ms": e.at_ms, "kind": e.kind, "what": WORDS.get(e.kind, e.kind),
                    "delta": e.delta, "detail": detail})
    return out


def earned(entries: list[Any]) -> dict:
    """How the balance was made: credits in by source, and spent."""
    got = {k: 0 for k in EARN_GROUPS}
    spent = refunded = 0
    for e in entries:
        for group, kinds in EARN_GROUPS.items():
            if e.kind in kinds:
                got[group] += e.delta
        if e.kind in ledger_mod.SPENDS or e.kind == "tip_out":
            spent += -e.delta
        if e.kind == "refund":
            refunded += e.delta
    return {**got, "spent": spent, "refunded": refunded}


# ── the night's wallet ───────────────────────────────────────────────────────

class Wallet:
    """One night's ledger, plus what the page reads every poll kept handy:
    which one-off grants each phone has had and which skip pots still hold
    pledges. Rebuilt from the ledger on open, so a restart loses nothing."""

    def __init__(self, night_id: str, cfg: EconomyConfig, persist: bool = True) -> None:
        self.night_id = night_id
        self.led = ledger_mod.Ledger(night_id, cfg, persist=persist)
        self.got: dict[str, set[str]] = {}
        self.pledges: dict[str, list[tuple[str, int, int]]] = {}   # pot -> [(phone, amount, seq)]
        for e in self.led.entries:
            self._note(e)

    def _note(self, e: Any) -> None:
        self.got.setdefault(e.phone, set()).add(e.kind)
        if e.kind == "skip_pledge":
            self.pledges.setdefault(e.ref, []).append((e.phone, -e.delta, e.seq))

    def noted(self, entries: list[Any]) -> list[Any]:
        for e in entries:
            self._note(e)
        return entries

    def balance(self, phone: str) -> int:
        return self.led.balance(phone)

    def pot(self, key: str) -> tuple[int, dict[str, int]]:
        """(credits pledged toward skipping this play, each phone's share)."""
        mine: dict[str, int] = {}
        for phone, amount, seq in self.pledges.get(key, []):
            if not self.led.is_refunded(seq):
                mine[phone] = mine.get(phone, 0) + amount
        return sum(mine.values()), mine

    def due_grants(self, phone: str, joined_ms: Optional[int], last_tick: Optional[int],
                   now_ms: int, cfg: EconomyConfig) -> tuple[list[tuple[str, int]], Optional[int]]:
        """The grants due to a phone at this poll, and its new top-up tick
        (the caller moves the tick to now when the phone was away, so missed
        top-ups never pile up). Reads only; the caller writes them."""
        if joined_ms is None:
            return [], last_tick
        got = self.got.get(phone, set())
        now_amt, later_amt, after_min = economy.start_grants(cfg)
        due: list[tuple[str, int]] = []
        if "start" not in got and now_amt > 0:
            due.append(("start", now_amt))
        if "start_rest" not in got and later_amt > 0 and now_ms - joined_ms >= after_min * 60_000:
            due.append(("start_rest", later_amt))
        tick = last_tick if last_tick is not None else joined_ms
        every = int(cfg.topup_every_min * 60_000)
        if every > 0:
            bal = self.balance(phone) + sum(a for _, a in due)
            while now_ms - tick >= every:
                tick += every
                up = economy.topup_amount(bal, cfg)
                if up:
                    due.append(("topup", up))
                    bal += up
        return due, tick


def back_wait_quote(runner: Any) -> Optional[int]:
    """How long a song added at the back of the line now would wait."""
    try:
        return runner.quote_wait(10 ** 6, True)
    except Exception:                                              # noqa: BLE001
        return None
