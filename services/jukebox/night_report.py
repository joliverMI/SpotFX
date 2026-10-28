"""
SpotFX — the Jukebox's POST-PARTY REPORT (data/jukebox-plan/report.md §9
PR 3.3: "a post-party report (the night's ledger next to the §3 bands)";
§12 risk 3: "the post-party report measures the real night against the §3
bands so the next party starts from real numbers"). Every row of the
simulator's table the night's records can measure is measured; a row they
can't says why, by name — never a zero.

WHAT IT READS, and nothing else: the night record (services/jukebox/
store.py — the latest night, whole), that night's credits ledger
(services/jukebox/ledger.py, `storage/jukebox_ledger/<night>.jsonl`, when
one exists), and that night's guest book (services/jukebox/guests.py's
phones, votes and its REPORT RECORDS: one sample per song start, each
guest's first look at an add price, adds turned away as too late). It
writes nothing.

MEASURED THE MODEL'S WAY (services/jukebox/simulator.py's `summary`), each
with the one translation a real night needs, stated:
  * "mid-party" is the model's 60-200 minutes of its 240-minute party, as a
    share of this night's own length;
  * a "quiet guest" is the model's (voting on under 15% of songs): here,
    of the songs that started after the phone joined;
  * "can afford it right away" counts each guest's first look at an add
    price (their first search since their last add) — the page disables
    an Add they can't afford, so a want is visible only there — priced as a
    known 3.6-minute song at their place in line, the model's sample song;
  * the back of the line and the prices are the samples taken at each song
    start (the model samples its prices there too).
A free-play night has no credits, so its credit rows say so; everything
else it measures from the book and the line.

THE SAME ROWS AS THE SIMULATOR. A measure here carries the key of
services/jukebox/simulator.ROWS, so "this night" sits beside the model's
nights at the same party size, settings and program (the Simulate tab's own
numbers) — one vocabulary, never a second idea of what "add to play" means.
A row this night can't measure says why (`why`).

GUESTS are the phones in the ledger (the host is not one), or on a
free-play night the phones that joined the guest page (a phone the host
merged into another counts once); with neither the party size is unknown
and the comparison is only made when the caller names a size.
"""
from __future__ import annotations

import statistics
from typing import Any, Optional

import numpy as np

from models.jukebox import EconomyConfig, GuestBook, JukeboxNight
from services.jukebox import simulator
from services.jukebox.ledger import Entry

HOST = "host"
NO_GUESTS = "no phone used the guest page this night"
NOT_RECORDED = "this night's records don't hold it"
NOT_PLAYED_YET = "no guest song has played yet"
FREE_PLAY = "free play: nothing cost anything this night"
NO_BOOK = "this night's guest records aren't on hand"
NOT_SAMPLED = "no song started while a guest's page was open"
NO_WANTS = "no guest looked at an add price"
NO_QUIET = "no quiet guest (everyone voted on 15% of the songs or more)"

MODEL_NIGHT_MIN = 240          # the simulator's party
MODEL_MID_MIN = (60, 200)      # its "mid-party" window
QUIET_VOTE_SHARE = 0.15        # its quiet guest: votes on under this share of songs


def _median(xs: list[float]) -> Optional[float]:
    return float(statistics.median(xs)) if xs else None


def _hours(n: JukeboxNight, now_ms: int) -> Optional[float]:
    end = n.ended_ms or now_ms
    if not n.started_ms or end <= n.started_ms:
        return None
    return (end - n.started_ms) / 3_600_000


def night_section(n: JukeboxNight, now_ms: int) -> dict:
    kinds: dict[str, int] = {}
    for p in n.played:
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
    hours = _hours(n, now_ms)
    music = kinds.get("set", 0) + kinds.get("jukebox", 0)
    line_by: dict[str, int] = {}
    for e in n.line:
        line_by[e.state] = line_by.get(e.state, 0) + 1
    waits = [(e.played_ms - e.added_ms) / 60_000 for e in n.line
             if e.state == "played" and e.played_ms and e.added_ms]
    return {
        "id": n.id, "state": n.state, "playlist": n.playlist_name or n.playlist_uri or None,
        "started_ms": n.started_ms or None, "ended_ms": n.ended_ms,
        "end_reason": n.end_reason or None, "end_detail": n.end_detail or None,
        "hours": round(hours, 2) if hours is not None else None,
        "played": {"set": kinds.get("set", 0), "jukebox": kinds.get("jukebox", 0),
                   "skipped": kinds.get("skipped", 0), "foreign": kinds.get("foreign", 0)},
        "jukebox_share": round(kinds.get("jukebox", 0) / music, 3) if music else None,
        "songs_per_hour": round(music / hours, 1) if hours else None,
        "line": {"added": len(n.line),
                 "by_host": sum(1 for e in n.line if e.added_by == HOST),
                 "by_guests": sum(1 for e in n.line if e.added_by != HOST),
                 "played": line_by.get("played", 0), "removed": line_by.get("removed", 0),
                 "skipped": line_by.get("skipped", 0),
                 "playing_at_end": line_by.get("playing", 0),
                 "waiting_at_end": sum(line_by.get(s, 0) for s in ("queued", "committed"))},
        "add_to_play_median_min": round(_median(waits), 1) if waits else None,
        "warnings_at_end": list(n.warnings),
    }


def credits_section(entries: list[Entry], hours: Optional[float]) -> dict:
    gone = {e.phone for e in entries if e.kind == "merge_out"}    # merged into another guest
    phones = sorted({e.phone for e in entries if e.phone != HOST and e.phone not in gone})
    by_kind: dict[str, int] = {}
    counts: dict[str, int] = {}
    for e in entries:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + e.delta
        counts[e.kind] = counts.get(e.kind, 0) + 1
    minted = sum(d for k, d in by_kind.items()
                 if k in ("start", "start_rest", "topup", "qr_bonus", "host_gift", "vote",
                          "adder_up", "tip_bonus"))
    bal: dict[str, int] = {}
    for e in entries:
        bal[e.phone] = bal.get(e.phone, 0) + e.delta
    held = sum(v for p, v in bal.items() if p != HOST)
    per_hr = (lambda c: round(c / hours, 2)) if hours else (lambda c: None)
    return {"phones": len(phones), "minted": minted, "by_kind": by_kind, "counts": counts,
            "held_at_end": held, "unspent_share": round(held / minted, 3) if minted else None,
            "adds": counts.get("add", 0), "skips_hr": per_hr(counts.get("skip", 0)),
            "nexts_hr": per_hr(counts.get("play_next", 0)),
            "tips_hr": per_hr(counts.get("tip_out", 0)),
            "add_price_median": _median([-e.delta for e in entries if e.kind == "add"])}


def book_guests(book: Optional[GuestBook]) -> list:
    """The phones that joined the guest page tonight, each once (a phone the
    host merged into another is that guest)."""
    if book is None:
        return []
    return [p for p in book.phones.values() if p.joined and not p.merged_into]


def _mid_window(n: JukeboxNight, now_ms: int) -> Optional[tuple[int, int]]:
    hours = _hours(n, now_ms)
    if hours is None:
        return None
    length = hours * 3_600_000
    a, b = MODEL_MID_MIN
    return (int(n.started_ms + length * a / MODEL_NIGHT_MIN),
            int(n.started_ms + length * b / MODEL_NIGHT_MIN))


def _row(value: Any, why: Optional[str]) -> dict:
    return {"value": None if value is None else float(value), "why": None if value is not None else why}


def book_measures(n: JukeboxNight, book: GuestBook, credits: bool, now_ms: int) -> dict[str, dict]:
    """The rows the guest book measures: first song from arriving, the back
    of the line, the mid-party samples, the wants, the jail, quiet guests,
    adds turned away as too late."""
    out: dict[str, dict] = {}
    guests = book_guests(book)
    played_at: dict[str, list[int]] = {}
    for e in n.line:
        if e.added_by != HOST and e.state == "played" and e.played_ms:
            played_at.setdefault(e.added_by, []).append(e.played_ms)
    firsts = [(min(played_at[p.id]) - p.created_ms) / 60_000 for p in guests
              if p.id in played_at and p.created_ms]
    out["first_song_wait_all"] = _row(_median(firsts), NOT_PLAYED_YET)
    waits = [x.back_wait_ms / 60_000 for x in book.series if x.back_wait_ms is not None]
    out["back_wait_p90"] = _row(float(np.percentile(waits, 90)) if waits else None, NOT_SAMPLED)
    window = _mid_window(n, now_ms)
    mid = [x for x in book.series if window and window[0] <= x.t_ms <= window[1]]
    if credits:
        held = [x.held for x in mid if x.held is not None]
        prices = [x.price_back for x in mid if x.price_back is not None]
        out["held_mid_per_guest"] = _row(statistics.mean(held) / max(1, len(guests)) if held else None,
                                         NOT_SAMPLED)
        out["price_mid"] = _row(statistics.mean(prices) if prices else None, NOT_SAMPLED)
        wc = book.wants
        out["afford_rate"] = _row(wc.afford_now / wc.wants if wc.wants else None, NO_WANTS)
        first = wc.wants - wc.wish_more
        out["afford_empty"] = _row((wc.afford_now - wc.afford_more) / first if first else None,
                                   NO_WANTS if not wc.wants else "every look was for a 2nd song")
    else:
        for k in ("held_mid_per_guest", "price_mid", "afford_rate", "afford_empty"):
            out[k] = _row(None, FREE_PLAY)
    out["jails"] = _row(sum(p.jails for p in guests), None)
    votes: dict[str, int] = {}
    for by in book.votes.values():
        for pid in by:
            votes[pid] = votes.get(pid, 0) + 1
    quiet = []
    for p in guests:
        heard = sum(1 for x in n.played if x.kind in ("set", "jukebox")
                    and x.at_ms >= (p.joined_ms or p.created_ms))
        if heard and votes.get(p.id, 0) / heard < QUIET_VOTE_SHARE:
            quiet.append(len(played_at.get(p.id, [])))
    out["songs_per_lurk"] = _row(statistics.mean(quiet) if quiet else None, NO_QUIET)
    out["refused_late"] = _row(book.refused.get("too_late", 0), None)
    return out


def measures(n: JukeboxNight, entries: Optional[list[Entry]], now_ms: int,
             book: Optional[GuestBook] = None) -> dict[str, dict]:
    """This night's value for each simulator row it can measure; the rest
    say why not. `entries` is the night's ledger (credits mode), `book` its
    guest book."""
    ns = night_section(n, now_ms)
    out: dict[str, dict] = {}
    credits = entries is not None
    guest_line = [e for e in n.line if e.added_by != HOST]
    had_guests = credits or bool(book_guests(book)) or bool(guest_line)
    out["juke_played"] = _row(sum(1 for e in guest_line if e.state == "played") if had_guests else None,
                              NO_GUESTS)
    waits = [(e.played_ms - e.added_ms) / 60_000 for e in guest_line
             if e.state == "played" and e.played_ms and e.added_ms]
    out["wait_to_play_median"] = _row(_median(waits), NOT_PLAYED_YET if had_guests else NO_GUESTS)
    if had_guests:
        guests_added = {e.added_by for e in guest_line}
        got = {e.added_by for e in guest_line if e.state == "played"}
        out["got_played"] = _row((len(got) / len(guests_added)) if guests_added else None,
                                 "no guest added a song")
    if credits:
        cs = credits_section(entries, ns["hours"])
        for key in ("skips_hr", "nexts_hr", "tips_hr", "unspent_share", "add_price_median"):
            out[key] = _row(cs[key], NOT_RECORDED)
    elif had_guests:
        for key in ("skips_hr", "nexts_hr", "tips_hr", "unspent_share", "add_price_median"):
            out[key] = _row(None, FREE_PLAY)
    if book is not None and had_guests:
        out.update(book_measures(n, book, credits, now_ms))
    for k, _label, _unit in simulator.ROWS:
        out.setdefault(k, _row(None, NO_BOOK if had_guests else NO_GUESTS))
    return out


def build(n: Optional[JukeboxNight], entries: Optional[list[Entry]], cfg: EconomyConfig, *,
          now_ms: int, guests: Optional[int] = None, mode: str = "auto", every: int = 1,
          run: int = 1, compare: bool = True, nights: int = 20,
          verify: Optional[list[str]] = None, book: Optional[GuestBook] = None) -> dict:
    if n is None:
        return {"status": "none", "summary": "No night has been played yet."}
    ns = night_section(n, now_ms)
    cs = credits_section(entries, ns["hours"]) if entries else None
    on_page = len(book_guests(book))
    party = guests or (cs["phones"] if cs else None) or on_page or None
    ms = measures(n, entries, now_ms, book)
    comparison = None
    if compare and party and simulator.GUESTS_MIN <= party <= simulator.GUESTS_MAX:
        sim = simulator.simulate(party, cfg, mode=mode, every=every, run=run, nights=nights)
        comparison = {"guests": party, "nights": nights, "program": sim["program"],
                      "rows": [{**r, "this_night": ms[r["key"]]["value"],
                                "why": ms[r["key"]]["why"]} for r in sim["rows"]]}
    summary = (f"{'Running' if n.state == 'running' else 'The night'} on {ns['playlist'] or 'the set'}"
               + (f", {ns['hours']} hours" if ns['hours'] is not None else "")
               + f": {ns['played']['set']} set songs and {ns['played']['jukebox']} jukebox songs played"
               + (f"; {cs['phones']} guests used credits" if cs
                  else f"; {on_page} guest{'' if on_page == 1 else 's'} on the guest page (free play)"
                  if on_page else f"; {NO_GUESTS}") + ".")
    return {"status": "ok", "summary": summary, "night": ns, "credits": cs,
            "integrity": verify, "measures": ms, "comparison": comparison,
            "guests": party,
            "guests_from": ("you" if guests else "the ledger" if cs else "the guest book" if on_page else None),
            "rows": [{"key": k, "label": label, "unit": unit, "this_night": ms[k]["value"],
                      "why": ms[k]["why"]} for k, label, unit in simulator.ROWS]}


def load_book(night_id: str) -> Optional[GuestBook]:
    """That night's guest book, or None when the book on hand is another
    night's (it holds only the latest)."""
    from services.jukebox import store
    book = store.load_guests()
    return book if night_id and book.night_id == night_id else None


def load_entries(night_id: str, cfg: EconomyConfig) -> tuple[Optional[list[Entry]], Optional[list[str]]]:
    """That night's ledger entries and its own integrity check, or (None,
    None) when the night has no ledger file (no guest credits were used)."""
    from services.jukebox import ledger
    if not night_id or not (ledger.LEDGER_DIR / f"{night_id}.jsonl").exists():
        return None, None
    led = ledger.Ledger(night_id, cfg)
    return list(led.entries), led.verify()
