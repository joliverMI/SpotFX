"""
SpotFX — the Jukebox's BOARD (data/jukebox-plan/report.md §1 rule 11, §2.2,
§4's Board card, §7; D1 at its default, (a)): "Tonight's top songs".

THE BOARD RANKS SONGS, NOT PEOPLE (§2.2: Spotify's Developer Policy says
"Do not create a game", and a ranked board of people reads that way). The
songs that got the most ▲ tonight, with who added each as attribution, like
a chart. People boards — top pickers (the ▲ on the songs they added), top
voters (the songs they voted on) and most generous (the credits they gave
as tips) — exist behind switches that ship OFF (ShowConfig.board_top_*,
board_most_generous): his call, not a default. There are no prizes, and
none of the words in BANNED_WORDS appear in anything this module returns
(tests/test_jukebox_board.py holds every string to that).

Pure: built from the guest book (votes, who added each play, names), the
engine's lean read (the line, the set, what is playing) and, for "most
generous", each phone's tips out of the ledger. A phone is only ever named
by its name, never its id.

A song that played twice is one row: its ▲ and ▼ are added up across its
plays. Ties go to fewer ▼, then to the song that played first. A song with
no ▲ isn't on the board.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from models.jukebox import GuestBook, ShowConfig

LIMIT = 10
#: never in anything the board says (§2.2: no game framing, no prizes)
BANNED_WORDS = ("win", "winner", "won", "score", "points", "level", "rank", "game",
                "prize", "leaderboard")

TITLE = "Tonight's top songs"
EMPTY = "No ▲ yet tonight — the songs the room likes most show up here."
#: id -> (title, unit, the unit for a count of one)
PEOPLE = {
    "pickers": ("Top pickers", "▲ on the songs they added", "▲ on the songs they added"),
    "voters": ("Top voters", "songs voted on", "song voted on"),
    "generous": ("Most generous", "credits given as tips", "credit given as tips"),
}
SWITCH = {"pickers": "board_top_pickers", "voters": "board_top_voters",
          "generous": "board_most_generous"}


def _key_parts(key: str) -> tuple[str, int]:
    uri, _, at = key.rpartition("@")
    try:
        return uri, int(at)
    except ValueError:
        return key, 0


def song_info(gs: dict) -> dict[str, dict]:
    """uri -> what the board shows of a song: title, artist, art, and who
    added it when it was a jukebox song (a phone id, or "host")."""
    out: dict[str, dict] = {}
    for it in gs.get("set_items") or []:
        out.setdefault(it.uri, {"title": it.title, "artist": it.artist,
                                "image": getattr(it, "image", ""), "thumb": getattr(it, "thumb", ""),
                                "added_by": None})
    for e in gs.get("line") or []:
        out[e.uri] = {"title": e.title, "artist": e.artist, "image": e.image,
                      "thumb": e.thumb, "added_by": e.added_by}
    now = gs.get("now")
    if now is not None and getattr(now, "uri", "") and now.uri not in out:
        out[now.uri] = {"title": getattr(now, "title", ""), "artist": "", "image": "",
                        "thumb": "", "added_by": None}
    return out


def _by(added_by: Optional[str], names: dict[str, str]) -> dict:
    if added_by is None:
        return {"kind": "set", "name": "Host's set"}
    if added_by == "host":
        return {"kind": "host", "name": "the host"}
    return {"kind": "guest", "name": names.get(added_by, "a guest")}


def top_songs(book: GuestBook, gs: dict, limit: int = LIMIT,
              viewer: Optional[str] = None) -> list[dict]:
    """The songs with the most ▲ tonight, a row per song (its plays added up).
    `mine` marks the songs `viewer` (a phone) added — the id itself never
    leaves this function."""
    from services.jukebox.guests import open_url
    info = song_info(gs)
    names = {pid: p.name for pid, p in book.phones.items()}
    rows: dict[str, dict] = {}
    for key, votes in book.votes.items():
        uri, at = _key_parts(key)
        if not uri:
            continue
        ups = sum(1 for v in votes.values() if v > 0)
        downs = sum(1 for v in votes.values() if v < 0)
        row = rows.get(uri)
        if row is None:
            meta = info.get(uri, {})
            adder = book.play_by.get(key) or meta.get("added_by")
            row = rows[uri] = {"kind": "set" if adder is None else "jukebox",
                               "mine": viewer is not None and adder == viewer,
                               "uri": uri, "title": meta.get("title", ""),
                               "artist": meta.get("artist", ""), "image": meta.get("image", ""),
                               "thumb": meta.get("thumb", ""), "open_url": open_url(uri),
                               "by": _by(adder, names), "ups": 0, "downs": 0, "plays": 0,
                               "first": at}
        row["ups"] += ups
        row["downs"] += downs
        row["plays"] += 1
        row["first"] = min(row["first"], at)
    out = sorted((r for r in rows.values() if r["ups"] > 0),
                 key=lambda r: (-r["ups"], r["downs"], r["first"]))[:limit]
    for r in out:
        r.pop("first", None)
    return out


def _people(counts: dict[str, int], book: GuestBook, limit: int) -> list[dict]:
    names = {pid: p.name for pid, p in book.phones.items() if not p.blocked and not p.merged_into}
    rows = [(n, names[pid]) for pid, n in counts.items() if n > 0 and pid in names]
    rows.sort(key=lambda r: (-r[0], r[1].casefold()))
    return [{"name": name, "value": n} for n, name in rows[:limit]]


def top_pickers(book: GuestBook, limit: int = LIMIT) -> list[dict]:
    counts: dict[str, int] = {}
    for key, adder in book.play_by.items():
        ups = sum(1 for v in (book.votes.get(key) or {}).values() if v > 0)
        counts[adder] = counts.get(adder, 0) + ups
    return _people(counts, book, limit)


def top_voters(book: GuestBook, limit: int = LIMIT) -> list[dict]:
    counts: dict[str, int] = {}
    for votes in book.votes.values():
        for pid in votes:
            counts[pid] = counts.get(pid, 0) + 1
    return _people(counts, book, limit)


def tips_given(entries: list[Any]) -> dict[str, int]:
    """Credits each guest gave as tips, from the night's ledger entries — a
    phone the host merged into another counts as that one."""
    out: dict[str, int] = {}
    for e in entries:
        if e.kind == "tip_out":
            out[e.phone] = out.get(e.phone, 0) - e.delta
        elif e.kind == "merge_out":       # the ledger writes nothing to it after this
            out[e.ref] = out.get(e.ref, 0) + out.pop(e.phone, 0)
    return out


def build_board(book: GuestBook, gs: dict, show: ShowConfig,
                tips: Optional[dict[str, int]] = None, *, every_people_board: bool = False,
                limit: int = LIMIT, viewer: Optional[str] = None) -> dict:
    """The board: tonight's top songs, and the people boards his switches
    turn on (all of them, each marked with its switch, for the host's own
    view: `every_people_board`). "Most generous" needs `tips` (credits
    mode); without it that board is left out."""
    people = []
    for pid, (title, unit, unit_one) in PEOPLE.items():
        on = bool(getattr(show, SWITCH[pid]))
        if not (on or every_people_board):
            continue
        if pid == "generous" and tips is None:
            continue
        rows = (top_pickers(book, limit) if pid == "pickers" else
                top_voters(book, limit) if pid == "voters" else
                _people(tips or {}, book, limit))
        people.append({"id": pid, "title": title, "unit": unit, "unit_one": unit_one, "shown": on,
                       "rows": rows})
    return {"title": TITLE, "empty": EMPTY, "songs": top_songs(book, gs, limit, viewer),
            "people": people}


def words_of(board: dict) -> list[str]:
    """Every word-bearing string the board says (for the no-game-words check)."""
    out = [board.get("title", ""), board.get("empty", "")]
    for p in board.get("people", []):
        out += [p["title"], p["unit"], p["unit_one"]]
    return out


def banned_in(text: str) -> list[str]:
    return [w for w in BANNED_WORDS if re.search(rf"\b{w}\b", text, re.IGNORECASE)]
