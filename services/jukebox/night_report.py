"""
SpotFX — the Jukebox's POST-PARTY REPORT (data/jukebox-plan/report.md §9
PR 3.3: "a post-party report (the night's ledger next to the §3 bands)";
§12 risk 3: "the post-party report measures the real night against the §3
bands so the next party starts from real numbers"). A SKELETON: everything
a night records today is measured, and every measure the guest page will
feed (phase 2) is reported as not measured yet, by name — never a zero.

WHAT IT READS, and nothing else: the night record (services/jukebox/
store.py — the latest night, whole) and that night's credits ledger
(services/jukebox/ledger.py, `storage/jukebox_ledger/<night>.jsonl`, when
one exists). It writes nothing.

THE SAME ROWS AS THE SIMULATOR. A measure here carries the key of
services/jukebox/simulator.ROWS, so "this night" sits beside the model's
nights at the same party size, settings and program (the Simulate tab's own
numbers) — one vocabulary, never a second idea of what "add to play" means.
A row this night can't measure says why (`why`).

GUESTS are the phones in the ledger (the host is not one); with no ledger
the party size is unknown and the comparison is only made when the caller
names a size.
"""
from __future__ import annotations

import statistics
from typing import Any, Optional

from models.jukebox import EconomyConfig, JukeboxNight
from services.jukebox import simulator
from services.jukebox.ledger import Entry

HOST = "host"
NO_GUESTS = "no guest credits were used this night (the guest page comes in phase 2)"
NOT_RECORDED = "this night's records don't hold it yet"
NOT_PLAYED_YET = "no guest song has played yet"


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
    phones = sorted({e.phone for e in entries if e.phone != HOST})
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


def measures(n: JukeboxNight, entries: Optional[list[Entry]], now_ms: int) -> dict[str, dict]:
    """This night's value for each simulator row it can measure; the rest
    say why not."""
    ns = night_section(n, now_ms)
    out: dict[str, dict] = {}
    guest_line = [e for e in n.line if e.added_by != HOST]
    out["juke_played"] = {"value": float(sum(1 for e in guest_line if e.state == "played"))
                          if entries else None, "why": None if entries else NO_GUESTS}
    waits = [(e.played_ms - e.added_ms) / 60_000 for e in guest_line
             if e.state == "played" and e.played_ms and e.added_ms]
    out["wait_to_play_median"] = {
        "value": _median(waits),
        "why": None if waits else (NOT_PLAYED_YET if entries else NO_GUESTS),
    }
    if entries:
        cs = credits_section(entries, ns["hours"])
        guests_added = {e.added_by for e in guest_line}
        got = {e.added_by for e in guest_line if e.state == "played"}
        out["got_played"] = {"value": (len(got) / len(guests_added)) if guests_added else None,
                             "why": None if guests_added else "no guest added a song"}
        for key in ("skips_hr", "nexts_hr", "tips_hr", "unspent_share", "add_price_median"):
            out[key] = {"value": cs[key], "why": None if cs[key] is not None else NOT_RECORDED}
    for k, _label, _unit in simulator.ROWS:
        out.setdefault(k, {"value": None, "why": NOT_RECORDED if entries else NO_GUESTS})
    return out


def build(n: Optional[JukeboxNight], entries: Optional[list[Entry]], cfg: EconomyConfig, *,
          now_ms: int, guests: Optional[int] = None, mode: str = "auto", every: int = 1,
          run: int = 1, compare: bool = True, nights: int = 20,
          verify: Optional[list[str]] = None) -> dict:
    if n is None:
        return {"status": "none", "summary": "No night has been played yet."}
    ns = night_section(n, now_ms)
    cs = credits_section(entries, ns["hours"]) if entries else None
    party = guests or (cs["phones"] if cs else None)
    ms = measures(n, entries, now_ms)
    comparison = None
    if compare and party and simulator.GUESTS_MIN <= party <= simulator.GUESTS_MAX:
        sim = simulator.simulate(party, cfg, mode=mode, every=every, run=run, nights=nights)
        comparison = {"guests": party, "nights": nights, "program": sim["program"],
                      "rows": [{**r, "this_night": ms[r["key"]]["value"],
                                "why": ms[r["key"]]["why"]} for r in sim["rows"]]}
    summary = (f"{'Running' if n.state == 'running' else 'The night'} on {ns['playlist'] or 'the set'}"
               + (f", {ns['hours']} hours" if ns['hours'] is not None else "")
               + f": {ns['played']['set']} set songs and {ns['played']['jukebox']} jukebox songs played"
               + (f"; {cs['phones']} guests used credits" if cs else f"; {NO_GUESTS}") + ".")
    return {"status": "ok", "summary": summary, "night": ns, "credits": cs,
            "integrity": verify, "measures": ms, "comparison": comparison,
            "guests": party, "guests_from": ("you" if guests else "the ledger" if cs else None),
            "rows": [{"key": k, "label": label, "unit": unit, "this_night": ms[k]["value"],
                      "why": ms[k]["why"]} for k, label, unit in simulator.ROWS]}


def load_entries(night_id: str, cfg: EconomyConfig) -> tuple[Optional[list[Entry]], Optional[list[str]]]:
    """That night's ledger entries and its own integrity check, or (None,
    None) when the night has no ledger file (no guest credits were used)."""
    from services.jukebox import ledger
    if not night_id or not (ledger.LEDGER_DIR / f"{night_id}.jsonl").exists():
        return None, None
    led = ledger.Ledger(night_id, cfg)
    return list(led.entries), led.verify()
