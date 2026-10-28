"""
SpotFX — the Jukebox's LIVE ECONOMY PANEL (data/jukebox-plan/report.md §9 PR
3.3 "Live economy panel"; §7's host Live view: "the line with what each song
paid, holds and the jail, the economy right now, recent events"). Pure: the
night's ledger entries, the guests' names and the songs' titles in; what the
master's Live tab draws out.

THE SAME VOCABULARY AS THE REPORT. The credits right now are services/
jukebox/night_report.py's `credits_section` — what was made, what is held,
the rates — read while the night runs instead of after it, so the panel and
the post-party report can never disagree about what "held" or "skips an
hour" means.

RECENT EVENTS are the ledger's own groups in words, newest first: a song
added and what it cost, a bump, a play next, a skip or a chip-in, a tip (with
its double-first bonus), a break-out, a bonus card, the host's gifts, zeros
and merges, a refund, Adder credits for a song that played. The routine
entries — a vote's +1, the welcome credits, a top-up — are left out (a party
of 15 votes on every song; they would bury everything else) and counted
instead. One host gift to everyone is one event, not one per phone.

It writes nothing and reads no clock: the caller passes the hours the night
has run.
"""
from __future__ import annotations

from typing import Any, Optional

from services.jukebox import night_report

ROUTINE = frozenset({"vote", "start", "start_rest", "topup"})
EVENTS_SHOWN = 20
GIFT_TOGETHER_MS = 2000      # host gifts this close together are one "Everyone +N"

SPEND_WORDS = {
    "add": "added {song}",
    "bump_up": "moved {song} up",
    "bump_down": "moved {song} down",
    "play_next": "played {song} next",
    "skip": "skipped {song}",
    "skip_pledge": "chipped in to skip {song}",
    "jail_breakout": "broke out of jail",
}


def _song(ref: str, titles: dict[str, str]) -> str:
    """A ledger ref names a play (`<uri>@<started>`) or a line entry."""
    title = titles.get(ref.split("@", 1)[0], "") or titles.get(ref, "")
    return f"“{title}”" if title else "a song"


def _name(pid: str, names: dict[str, str]) -> str:
    return "the host" if pid == "host" else names.get(pid, "a guest")


def _one(group: list[Any], names: dict[str, str], titles: dict[str, str]) -> Optional[dict]:
    """One ledger group in words: {at_ms, who, what, credits} (credits signed:
    + made or given to them, − spent), or None for a routine entry."""
    e = group[0]
    who = _name(e.phone, names)
    song = _song(e.ref, titles)
    if e.kind in ROUTINE:
        return None
    if e.kind in SPEND_WORDS:
        return {"at_ms": e.at_ms, "kind": e.kind, "who": who,
                "what": SPEND_WORDS[e.kind].format(song=song), "credits": e.delta}
    if e.kind == "tip_out":
        bonus = sum(x.delta for x in group if x.kind == "tip_bonus")
        to = _name(e.note, names)
        what = f"tipped {to} {-e.delta} on {song}" + (f" (+{bonus} bonus)" if bonus else "")
        return {"at_ms": e.at_ms, "kind": "tip", "who": who, "what": what, "credits": e.delta}
    if e.kind == "adder_up":
        return {"at_ms": e.at_ms, "kind": e.kind, "who": who,
                "what": f"got {e.delta} for the ▲ on {song}", "credits": e.delta}
    if e.kind == "qr_bonus":
        return {"at_ms": e.at_ms, "kind": e.kind, "who": who, "what": "used a bonus card",
                "credits": e.delta}
    if e.kind == "host_gift":
        return {"at_ms": e.at_ms, "kind": e.kind, "who": "the host",
                "what": f"gave {who} {e.delta}", "credits": e.delta}
    if e.kind == "refund":
        return {"at_ms": e.at_ms, "kind": e.kind, "who": who,
                "what": f"got {e.delta} back for {song}", "credits": e.delta}
    if e.kind == "host_zero":
        return {"at_ms": e.at_ms, "kind": e.kind, "who": "the host",
                "what": f"took {who}'s {-e.delta} credits back", "credits": e.delta}
    if e.kind == "merge_out":
        kept = _name(e.ref, names)
        return {"at_ms": e.at_ms, "kind": "merge", "who": "the host",
                "what": f"merged {who} into {kept}", "credits": 0}
    return {"at_ms": e.at_ms, "kind": e.kind, "who": who, "what": e.kind, "credits": e.delta}


def events(entries: list[Any], names: dict[str, str], titles: dict[str, str],
           limit: int = EVENTS_SHOWN) -> list[dict]:
    """The night's recent events, newest first. "Everyone +2" writes one gift
    per phone, moments apart: consecutive host gifts of the same amount to
    DIFFERENT phones, each within GIFT_TOGETHER_MS of the last, are one event
    (two gifts to one phone are two). Names only — no event carries a
    phone's code."""
    groups: dict[int, list[Any]] = {}
    for e in entries:
        groups.setdefault(e.group or e.seq, []).append(e)
    out: list[dict] = []
    gift: Optional[tuple[dict, set[str], int]] = None     # the event, its phones, its oldest moment
    for g in sorted(groups.values(), key=lambda g: g[0].seq, reverse=True):
        row = _one(g, names, titles)
        if row is None:
            continue
        e = g[0]
        if (row["kind"] == "host_gift" and gift is not None and out and out[-1] is gift[0]
                and gift[0]["credits"] == row["credits"] and e.phone not in gift[1]
                and gift[2] - row["at_ms"] <= GIFT_TOGETHER_MS):
            ev, phones, _ = gift
            phones.add(e.phone)
            ev["phones"] = len(phones)
            ev["what"] = f"gave {len(phones)} guests {row['credits']} each"
            gift = (ev, phones, row["at_ms"])
            continue
        gift = (row, {e.phone}, row["at_ms"]) if row["kind"] == "host_gift" else None
        out.append(row)
        if len(out) > limit:       # the limit-th event is whole (a gift may still group)
            break
    return out[:limit]


def routine_counts(entries: list[Any]) -> dict[str, int]:
    """What the event list leaves out, counted: votes paid, and the free
    credits handed out (welcomes and top-ups)."""
    return {"votes": sum(1 for e in entries if e.kind == "vote"),
            "free": sum(e.delta for e in entries if e.kind in ("start", "start_rest", "topup"))}


def credits_now(entries: list[Any], hours: Optional[float], guests: int) -> dict:
    """The economy right now: the report's own credits section, plus what is
    held per guest at the party (the §3 row "credits held per guest")."""
    cs = night_report.credits_section(entries, hours)
    per = round(cs["held_at_end"] / guests, 1) if guests else None
    return {"minted": cs["minted"], "held": cs["held_at_end"], "held_per_guest": per,
            "unspent_share": cs["unspent_share"], "by_kind": cs["by_kind"],
            "adds": cs["adds"], "skips_hr": cs["skips_hr"], "nexts_hr": cs["nexts_hr"],
            "tips_hr": cs["tips_hr"], "add_price_median": cs["add_price_median"],
            **routine_counts(entries)}
