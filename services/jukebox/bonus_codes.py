"""
SpotFX — the Jukebox's BONUS CODES (data/jukebox-plan/report.md §1 rule 1,
§4's Free credits card, §9's N2 "one-time +5 bonus codes"): the codes the
printed cards carry. A code is good for `qr_bonus` credits (5) ONCE, EVER,
and a phone can use one code a night — the plan's "(one per phone)".

The host makes codes in batches (`mint`) before a party; the printed card
(N2) carries each code as text and inside the join QR (`?b=`). A guest uses
one from the link or by typing it in the Shop (services/jukebox/guests.py,
`redeem_bonus`, credits mode only), and the credits go through the night's
ledger as a "qr_bonus" grant like any other.

THE STORE IS ITS OWN FILE (storage/jukebox_bonus_codes.json), not the
night's: cards are printed before a night exists and kept between parties.
A file that is there but unreadable is NEVER written over (store.load_bonus
raises) — printed cards may carry its codes.

Codes are 8 characters from an alphabet with no look-alikes (no 0/O, 1/I/L,
U), shown "ABCD-EFGH"; what a guest types is folded to that before it is
looked up (case, spaces, dashes). 8 characters of 30 is about 2^39 codes, and
a phone gets BONUS_TRIES wrong tries a night (guests.py), so guessing is
not a way in.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from typing import Optional

from models.jukebox import BonusCode, BonusCodes
from services.jukebox import store

ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
LENGTH = 8
MINT_MAX = 200          # codes in one batch
STORE_MAX = 2000        # codes kept in all (used ones are the first to go)

# Every write below is a load-decide-save against the one bonus-codes file;
# store.save_bonus() only locks the final write, not that whole transaction.
# This lock covers each function's entire read-modify-write so a concurrent
# mint/claim/void can't read a stale copy and silently undo another's change
# (a reverted "used" mark would let a code be claimed, and its credits
# granted, more than once — see this module's own "ONCE, EVER" docstring).
# Every caller already runs these off the event loop (asyncio.to_thread or
# the guests' _ledger helper), so a plain threading.Lock never blocks it.
_lock = threading.Lock()


def fold(text: object) -> str:
    """What a guest typed, as a stored code: upper case, no spaces or dashes."""
    return re.sub(r"[^0-9A-Z]", "", str(text or "").upper())


def pretty(code: str) -> str:
    return f"{code[:4]}-{code[4:]}" if len(code) == LENGTH else code


def _new(existing: set[str]) -> str:
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
        if code not in existing:
            return code


def mint(count: int, batch: str = "", now_ms: Optional[int] = None) -> list[str]:
    """`count` new codes (1..MINT_MAX), saved before they are returned."""
    count = int(count)
    if not 1 <= count <= MINT_MAX:
        raise ValueError(f"make 1 to {MINT_MAX} codes at a time")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    batch = (batch or "").strip()[:40] or time.strftime("%Y-%m-%d %H:%M", time.localtime(now_ms / 1000))
    with _lock:
        codes = store.load_bonus()
        room = STORE_MAX - len(codes.codes)
        if count > room:
            # make room by forgetting the oldest USED codes; an unused one may be on a card
            used = sorted((c for c, v in codes.codes.items() if v.used_ms is not None),
                          key=lambda c: codes.codes[c].used_ms or 0)
            for c in used[:count - room]:
                del codes.codes[c]
            if STORE_MAX - len(codes.codes) < count:
                raise ValueError(f"there are already {len(codes.codes)} unused codes — "
                                 "void some before making more")
        out = []
        for _ in range(count):
            code = _new(set(codes.codes))
            codes.codes[code] = BonusCode(batch=batch, created_ms=now_ms)
            out.append(code)
        store.save_bonus(codes)
        return out


def claim(code_text: object, night_id: str, name: str, now_ms: int) -> tuple[str, Optional[str]]:
    """Mark a code used. ("ok", code) on success, else (reason, None):
    "unknown", or "spent" for a code already used. The caller holds the
    guests' lock, so two phones can't claim one code — this module's own
    lock is what stops a concurrent mint/void from losing that mark."""
    code = fold(code_text)
    with _lock:
        codes = store.load_bonus()
        entry = codes.codes.get(code)
        if entry is None:
            return "unknown", None
        if entry.used_ms is not None:
            return "spent", None
        entry.used_ms, entry.used_night, entry.used_name = now_ms, night_id, name
        store.save_bonus(codes)
        return "ok", code


def unclaim(code: str) -> None:
    """Undo a claim whose credits couldn't be written."""
    with _lock:
        codes = store.load_bonus()
        entry = codes.codes.get(code)
        if entry is not None:
            entry.used_ms, entry.used_night, entry.used_name = None, "", ""
            store.save_bonus(codes)


def void(code_text: object) -> bool:
    """Forget an UNUSED code (a card lost, a batch printed wrong). True if it went."""
    code = fold(code_text)
    with _lock:
        codes = store.load_bonus()
        entry = codes.codes.get(code)
        if entry is None or entry.used_ms is not None:
            return False
        del codes.codes[code]
        store.save_bonus(codes)
        return True


def summary() -> dict:
    """What the host's Bonus cards card shows: every code, unused first."""
    with _lock:
        codes = store.load_bonus()
    rows = [{"code": pretty(c), "batch": v.batch, "created_ms": v.created_ms,
             "used": v.used_ms is not None, "used_ms": v.used_ms, "used_name": v.used_name}
            for c, v in codes.codes.items()]
    rows.sort(key=lambda r: (r["used"], -(r["created_ms"] or 0), r["code"]))
    return {"unused": sum(1 for r in rows if not r["used"]),
            "used": sum(1 for r in rows if r["used"]), "codes": rows}
