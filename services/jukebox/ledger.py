"""
SpotFX — the Jukebox's credits LEDGER: one append-only file per night
(data/jukebox-plan/report.md §9, phase 3 PR 3.1). Every credit that exists
was written here as an entry with its reason; a balance is never stored, it
is the sum of the phone's entries, so "where did my credits go?" is always a
read of the same file that decided them.

APPEND-ONLY. An entry is never edited or deleted. A refund is a NEW entry
that points at the spend it returns; a tip is three entries written as one
group (the giver's −, the Adder's +, and any double-first bonus). Each group
is one write of whole lines, flushed and fsynced, so a crash leaves either
the whole group or none of it.

THE RULES IT ENFORCES before anything is written (each refusal is a
`LedgerError` with a code and one sentence, nothing appended):
  - no balance ever goes below zero — a spend needs the credits now;
  - a vote is paid ONCE per phone per song (changing your vote pays
    nothing more), never on your own song;
  - Adder credits are paid ONCE per song, never to the host;
  - a tip goes only to the Adder of a guest's song — never the host, never
    yourself — at most `tip_max_per_song` taps per giver per song, and its
    double-first bonus (§1 rule 4) is capped at `gift_double_first` per
    giver per NIGHT, counted from this file, not from a counter that could
    drift from it;
  - a refund returns a spend once, to the phone that paid it, never more
    than it cost.
`verify()` re-checks all of that from the entries alone — the invariants a
test (and the post-party report) holds the file to.

Credits are free and worth nothing outside the night (§2.1): every amount
here is a whole number of credits and nothing else.

The prices come from services/jukebox/economy.py; this module only records
what was granted, earned, given and spent. Paths are module attributes so a
test repoints them (tests/conftest.py's `_isolated_jukebox`).
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from config import BASE_DIR
from models.jukebox import EconomyConfig
from services.jukebox import economy

LEDGER_DIR = BASE_DIR / "storage" / "jukebox_ledger"

GRANTS = frozenset({"start", "start_rest", "topup", "qr_bonus", "host_gift"})
EARNINGS = frozenset({"vote", "adder_up"})
SPENDS = frozenset({"add", "bump_up", "bump_down", "play_next", "skip", "skip_pledge",
                    "jail_breakout"})
TIP_KINDS = frozenset({"tip_out", "tip_in", "tip_bonus"})
KINDS = GRANTS | EARNINGS | SPENDS | TIP_KINDS | {"refund"}

SENTENCES = {
    "not_enough": "Not enough credits for that ({need} needed, {have} held).",
    "own_song": "You can't vote on your own song.",
    "already_voted": "Your vote on this song has already been paid.",
    "adder_paid": "This song's Adder credits have already been paid.",
    "host_song": "The host's songs take no tips and earn no Adder credits.",
    "own_tip": "You can't tip yourself.",
    "tips_off": "Tips are switched off tonight.",
    "tip_cap": "That's the most you can tip on this song ({cap}).",
    "bad_amount": "That amount isn't a whole number of credits above zero.",
    "bad_kind": "That isn't a ledger entry kind.",
    "no_spend": "There's no such spend to refund.",
    "refunded": "That spend has already been refunded.",
    "over_refund": "A refund can't be more than the spend it returns.",
}


class LedgerError(ValueError):
    def __init__(self, code: str, **fmt: object) -> None:
        self.code = code
        text = SENTENCES.get(code, code)
        try:
            text = text.format(**fmt)
        except (KeyError, IndexError):
            pass
        self.sentence = text
        super().__init__(text)


@dataclass
class Entry:
    seq: int
    at_ms: int
    phone: str
    delta: int
    kind: str
    ref: str = ""            # what it is for: a song id, a skip pot, a card code…
    link: Optional[int] = None   # the entry it answers: a refund's spend, a tip part's tip_out
    group: int = 0           # entries written together share the first one's seq
    note: str = ""

    def as_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


@dataclass
class _Phone:
    balance: int = 0
    given: int = 0           # credits tipped out tonight (the double-first allowance)


class Ledger:
    """One night's ledger. `path` None keeps it in memory (the simulator,
    a test); otherwise it is LEDGER_DIR/<night_id>.jsonl, replayed on open."""

    def __init__(self, night_id: str, cfg: Optional[EconomyConfig] = None, *,
                 path: Optional[Path] = None, persist: bool = True,
                 now_ms: Callable[[], int] = lambda: int(time.time() * 1000)) -> None:
        self.night_id = night_id
        self.cfg = cfg or EconomyConfig()
        self.now_ms = now_ms
        self.path = (path or LEDGER_DIR / f"{night_id}.jsonl") if persist else None
        self.entries: list[Entry] = []
        self._phones: dict[str, _Phone] = {}
        self._voted: set[tuple[str, str]] = set()
        self._adder_paid: set[str] = set()
        self._tipped: dict[tuple[str, str], int] = {}
        self._refunded: dict[int, int] = {}
        self._lock = threading.RLock()
        if self.path is not None and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._apply(Entry(**json.loads(line)))

    # ── reads ───────────────────────────────────────────────────────────────

    def balance(self, phone: str) -> int:
        return self._phones.get(phone, _Phone()).balance

    def given(self, phone: str) -> int:
        return self._phones.get(phone, _Phone()).given

    def history(self, phone: str) -> list[Entry]:
        return [e for e in self.entries if e.phone == phone]

    def phones(self) -> list[str]:
        return list(self._phones)

    def tipped_on(self, giver: str, song_ref: str) -> int:
        return self._tipped.get((giver, song_ref), 0)

    def is_refunded(self, spend_seq: int) -> bool:
        return int(spend_seq) in self._refunded

    def voted_paid(self, voter: str, song_ref: str) -> bool:
        return (voter, song_ref) in self._voted

    # ── writing ─────────────────────────────────────────────────────────────

    def _apply(self, e: Entry) -> None:
        """Fold one entry into the derived state. Also the replay path."""
        st = self._phones.setdefault(e.phone, _Phone())
        st.balance += e.delta
        if e.kind == "vote":
            self._voted.add((e.phone, e.ref))
        elif e.kind == "adder_up":
            self._adder_paid.add(e.ref)
        elif e.kind == "tip_out":
            st.given += -e.delta
            key = (e.phone, e.ref)
            self._tipped[key] = self._tipped.get(key, 0) + (-e.delta) // max(1, self.cfg.tip_unit)
        elif e.kind == "refund" and e.link is not None:
            self._refunded[e.link] = self._refunded.get(e.link, 0) + e.delta
        self.entries.append(e)

    def _write(self, parts: list[tuple[str, int, str, str, Optional[int], str]]) -> list[Entry]:
        """Append one GROUP: [(phone, delta, kind, ref, link, note)]. A link
        of -1 means "the first entry of this group". One write, fsynced."""
        with self._lock:
            first = len(self.entries) + 1
            at = int(self.now_ms())
            new = []
            for i, (phone, delta, kind, ref, link, note) in enumerate(parts):
                new.append(Entry(seq=first + i, at_ms=at, phone=phone, delta=int(delta), kind=kind,
                                 ref=ref, link=first if link == -1 else link, group=first,
                                 note=note))
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write("".join(e.as_line() + "\n" for e in new))
                    f.flush()
                    os.fsync(f.fileno())
            for e in new:
                self._apply(e)
            return new

    @staticmethod
    def _amount(amount: int) -> int:
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise LedgerError("bad_amount")
        return amount

    def grant(self, phone: str, kind: str, amount: int, ref: str = "", note: str = "") -> Entry:
        """A free credit: the first-visit credits, a top-up, a QR card, a
        host gift."""
        with self._lock:
            if kind not in GRANTS:
                raise LedgerError("bad_kind")
            return self._write([(phone, self._amount(amount), kind, ref, None, note)])[0]

    def vote(self, voter: str, song_ref: str, own_song: bool) -> Optional[Entry]:
        """+vote_reward for voting on the playing song — once per song.
        Returns None when this vote pays nothing (already paid, or 0)."""
        with self._lock:
            if own_song:
                raise LedgerError("own_song")
            if (voter, song_ref) in self._voted:
                return None
            if self.cfg.vote_reward <= 0:
                return None
            return self._write([(voter, self.cfg.vote_reward, "vote", song_ref, None, "")])[0]

    def adder_ups(self, adder: str, song_ref: str, ups: int, adder_is_host: bool) -> Optional[Entry]:
        """When a guest's song has played: +adder_up_reward per ▲, once."""
        with self._lock:
            if adder_is_host:
                raise LedgerError("host_song")
            if song_ref in self._adder_paid:
                raise LedgerError("adder_paid")
            amount = int(ups) * self.cfg.adder_up_reward
            if amount <= 0:
                return None
            return self._write([(adder, amount, "adder_up", song_ref, None, f"{int(ups)} ▲")])[0]

    def spend(self, phone: str, kind: str, amount: int, ref: str = "", note: str = "") -> Entry:
        """Pay for something: refused, with nothing written, unless the
        phone holds the credits now."""
        with self._lock:
            if kind not in SPENDS:
                raise LedgerError("bad_kind")
            amount = self._amount(amount)
            have = self.balance(phone)
            if have < amount:
                raise LedgerError("not_enough", need=amount, have=have)
            return self._write([(phone, -amount, kind, ref, None, note)])[0]

    def jail_breakout(self, phone: str, ref: str = "") -> Entry:
        with self._lock:
            return self.spend(phone, "jail_breakout", self.cfg.jail_fee, ref)

    def refund(self, spend_seq: int, amount: Optional[int] = None, note: str = "") -> Entry:
        """Return a spend (a song the host removed, one that can't be
        learned, a skip pot that wasn't filled, the night ending first) —
        to the phone that paid it, at most once, never more than it cost."""
        with self._lock:
            if not 0 < int(spend_seq) <= len(self.entries):
                raise LedgerError("no_spend")
            sp = self.entries[int(spend_seq) - 1]
            if sp.kind not in SPENDS:
                raise LedgerError("no_spend")
            if int(spend_seq) in self._refunded:
                raise LedgerError("refunded")
            cost = -sp.delta
            amount = cost if amount is None else self._amount(amount)
            if amount > cost:
                raise LedgerError("over_refund")
            return self._write([(sp.phone, amount, "refund", sp.ref, sp.seq, note)])[0]

    def tip(self, giver: str, adder: str, song_ref: str, units: int,
            adder_is_host: bool) -> list[Entry]:
        """§1 rule 4: 1 credit a tap to the Adder of the song playing, at
        most `tip_max_per_song` taps per giver per song; the first
        `gift_double_first` credits a giver gives tonight arrive doubled."""
        with self._lock:
            cfg = self.cfg
            if not cfg.tips:
                raise LedgerError("tips_off")
            if adder_is_host:
                raise LedgerError("host_song")
            if giver == adder:
                raise LedgerError("own_tip")
            units = self._amount(units)
            allowed = economy.tip_units_allowed(self.tipped_on(giver, song_ref), cfg)
            if units > allowed:
                raise LedgerError("tip_cap", cap=cfg.tip_max_per_song)
            amount = units * cfg.tip_unit
            have = self.balance(giver)
            if have < amount:
                raise LedgerError("not_enough", need=amount, have=have)
            bonus = economy.tip_bonus(self.given(giver), amount, cfg)
            parts = [(giver, -amount, "tip_out", song_ref, None, adder),
                     (adder, amount, "tip_in", song_ref, -1, giver)]
            if bonus:
                parts.append((adder, bonus, "tip_bonus", song_ref, -1,
                              f"first {cfg.gift_double_first} given count double"))
            return self._write(parts)

    # ── the invariants, from the entries alone ──────────────────────────────

    def verify(self) -> list[str]:
        """Every rule above, re-checked by replaying the entries. Returns
        the violations (empty = the file is sound)."""
        bad: list[str] = []
        bal: dict[str, int] = {}
        bonus: dict[str, int] = {}
        voted: set[tuple[str, str]] = set()
        adder_paid: set[str] = set()
        refunded: set[int] = set()
        by_seq = {e.seq: e for e in self.entries}
        for i, e in enumerate(self.entries, 1):
            if e.seq != i:
                bad.append(f"entry {i} carries seq {e.seq}")
            if e.kind not in KINDS:
                bad.append(f"entry {e.seq}: unknown kind {e.kind!r}")
            positive = e.kind in GRANTS | EARNINGS | {"tip_in", "tip_bonus", "refund"}
            if (positive and e.delta <= 0) or (not positive and e.delta >= 0):
                bad.append(f"entry {e.seq}: {e.kind} with delta {e.delta}")
            bal[e.phone] = bal.get(e.phone, 0) + e.delta
            if bal[e.phone] < 0:
                bad.append(f"entry {e.seq}: {e.phone} went to {bal[e.phone]}")
            if e.kind == "vote":
                if (e.phone, e.ref) in voted:
                    bad.append(f"entry {e.seq}: a second vote payment on {e.ref}")
                voted.add((e.phone, e.ref))
            if e.kind == "adder_up":
                if e.ref in adder_paid:
                    bad.append(f"entry {e.seq}: Adder paid twice for {e.ref}")
                adder_paid.add(e.ref)
            if e.kind == "tip_out":
                if e.note == e.phone:
                    bad.append(f"entry {e.seq}: {e.phone} tipped themself")
            if e.kind in ("tip_in", "tip_bonus"):
                out = by_seq.get(e.link or 0)
                if out is None or out.kind != "tip_out" or out.group != e.group:
                    bad.append(f"entry {e.seq}: {e.kind} with no tip_out in its group")
                elif out.phone == e.phone:
                    bad.append(f"entry {e.seq}: a tip to the giver themself")
                elif e.kind == "tip_in" and e.delta != -out.delta:
                    bad.append(f"entry {e.seq}: tip_in {e.delta} for a tip_out of {-out.delta}")
                elif e.kind == "tip_bonus":
                    bonus[out.phone] = bonus.get(out.phone, 0) + e.delta
                    if bonus[out.phone] > self.cfg.gift_double_first:
                        bad.append(f"entry {e.seq}: {out.phone}'s gifts made {bonus[out.phone]} "
                                   f"bonus credits (cap {self.cfg.gift_double_first})")
            if e.kind == "refund":
                sp = by_seq.get(e.link or 0)
                if sp is None or sp.kind not in SPENDS:
                    bad.append(f"entry {e.seq}: a refund of no spend")
                elif sp.seq in refunded:
                    bad.append(f"entry {e.seq}: spend {sp.seq} refunded twice")
                elif sp.phone != e.phone or e.delta > -sp.delta:
                    bad.append(f"entry {e.seq}: refund doesn't match spend {sp.seq}")
                if sp is not None:
                    refunded.add(sp.seq)
        for phone, st in self._phones.items():
            if st.balance != bal.get(phone, 0):
                bad.append(f"{phone}: held {st.balance}, entries say {bal.get(phone, 0)}")
        return bad

    def minted(self) -> int:
        """Every credit that entered the night (grants, earnings, bonuses —
        a tip moves credits and makes none but its bonus; a refund returns
        credits that were already made)."""
        return sum(e.delta for e in self.entries if e.kind in GRANTS | EARNINGS | {"tip_bonus"})


def open_night(night_id: str, cfg: Optional[EconomyConfig] = None) -> Ledger:
    return Ledger(night_id, cfg)


def all_nights() -> Iterable[str]:
    return sorted(p.stem for p in LEDGER_DIR.glob("*.jsonl")) if LEDGER_DIR.exists() else []
