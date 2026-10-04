"""REFRESH ANALYSED TRIGGERS — re-plan the whole library's stored analysed
cues (or one song's) under the current settings and generator, behind a dry
run. The Admiral, 2026-10-04: "a Sonic 'refresh analysed triggers' command
(all songs or one): dry run first, one batched write inside SPECTRA,
backup, generated rows only, logged. NO scheduled refresh."

The per-song half (a stale song re-planned on its next play) is
midsong_generator.refresh_song_if_stale; this module is the library half.
Both reconcile through the ONE midsong_generator.merge_song, so a song
refreshed here and the same song refreshed on play end up identical.

DRY RUN FIRST — STRUCTURALLY, not by instruction. plan() computes every
song's change, reports the counts and keeps the plan in memory under a
plan_id; apply(plan_id) refuses without that id, and applies EXACTLY the
changes the dry run reported — never a fresh re-plan that could differ
from what he was shown. A song whose stored rows moved between the dry run
and the apply (he edited one, or it played and refreshed itself) is left
as it now is and NAMED in the result. A plan expires after PLAN_TTL_S; a
restart forgets it. Either way the answer is "run the dry run again".

ONE WRITE, INSIDE SPECTRA. The apply holds trigger_store.write_lock across
backup -> load -> rebuild -> verify -> save, i.e. one whole-file rewrite
serialised against every other writer in this process (the reason the old
offline scripts/import_analysed_triggers.py, ~20k single upserts from a
second process outside that lock, was never safe to run against his live
store). Planning — the slow part, ~20s for his library — runs BEFORE the
lock, in the caller's worker thread.

SAFETY, each rule a test (tests/test_analysed_refresh.py):
  - only source="generated" rows are written or removed; every other row of
    a touched song keeps its exact position and bytes;
  - a song holding no generated row is never touched (a song with only his
    own triggers stays exactly his);
  - a moment he edited or deleted by hand is never put back
    (spectra/services/analysed_claims.py, read by the planner);
  - a song whose analysis cannot be read keeps its stored cues;
  - the whole store is backed up first (backups/ beside triggers.json), and
    the rebuilt store is diffed against what was loaded BEFORE it is saved:
    any difference outside the planned generated rows is put back and
    counted as `restored` (never expected — it is the guard that makes
    "nothing else changed" a measurement rather than a belief), then the
    saved file is read back and compared to what was meant to be written.
  - every dry run and apply is appended to a bounded log beside
    triggers.json (analysed_refresh_log.json) and to the process log.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import statistics
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spectra import config
from spectra.models.trigger import SpectraTrigger
from spectra.services import analysis_reader, midsong_generator, trigger_store

logger = logging.getLogger(__name__)

PLAN_TTL_S = 3600.0
LOG_MAX_ENTRIES = 50
# A breath between songs while planning the library: the walk is pure
# Python on SPECTRA's own process, beside its render threads.
_YIELD_S = 0.002

_run_lock = threading.Lock()
_last_plan: Optional["LibraryPlan"] = None


def log_path() -> Path:
    return config.TRIGGERS_FILE.parent / "analysed_refresh_log.json"


def backups_dir() -> Path:
    return config.TRIGGERS_FILE.parent / "backups"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _generated_signature(raw_rows: Any) -> str:
    """What a song's GENERATED rows were when the dry run read them — the
    apply only touches a song whose generated rows are still exactly this."""
    rows = raw_rows if isinstance(raw_rows, list) else []
    gen = [r for r in rows if isinstance(r, dict) and r.get("source") == "generated"]
    blob = json.dumps(gen, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()


def _parse(rows: Any) -> list[SpectraTrigger]:
    out: list[SpectraTrigger] = []
    for v in rows if isinstance(rows, list) else []:
        try:
            out.append(SpectraTrigger(**v))
        except Exception:
            continue
    return out


@dataclass
class SongRefresh:
    uri: str
    snapshot: str
    stamp: str
    merge: midsong_generator.SongMerge


@dataclass
class LibraryPlan:
    plan_id: str
    scope: Optional[str]
    created_mono: float
    created_at: str
    songs: list[SongRefresh]
    report: dict = field(default_factory=dict)


def _move_stats(moves: list[int]) -> dict:
    if not moves:
        return {"median_ms": None, "p90_ms": None, "max_ms": None, "over_2s": 0}
    ordered = sorted(moves)
    return {
        "median_ms": int(statistics.median(ordered)),
        "p90_ms": ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))],
        "max_ms": ordered[-1],
        "over_2s": sum(1 for m in ordered if m > 2000),
    }


def _title(uri: str) -> Optional[str]:
    doc = analysis_reader.librosa_analysis_for_stem(analysis_reader.stem_for_uri(uri))
    if not doc:
        return None
    title, artist = doc.get("title"), doc.get("artist")
    return f"{title} — {artist}" if title and artist else title


def plan(uri: Optional[str] = None) -> dict:
    """THE DRY RUN. Plans every song holding generated cues (or just `uri`)
    against the stored rows, keeps the plan for apply(), and returns what
    applying it would do. Writes nothing but the log."""
    global _last_plan
    if not _run_lock.acquire(blocking=False):
        return {"status": "refused", "reason": "a refresh is already running"}
    try:
        from spectra.services.room_controls import load_room_controls
        controls = load_room_controls()
        raw = trigger_store.load_raw()
        if uri is not None:
            rows = raw.get(uri)
            if not rows:
                return _refused(uri, "no triggers are stored for this song")
            if not any(isinstance(r, dict) and r.get("source") == "generated" for r in rows):
                return _refused(uri, "this song holds only your own triggers — "
                                     "analysed cues are never added to it")
            targets = [uri]
        else:
            targets = sorted(u for u, rows in raw.items() if isinstance(rows, list)
                             and any(isinstance(r, dict) and r.get("source") == "generated"
                                     for r in rows))
        analysis_reader.stem_index()   # one index build for the whole walk
        songs: list[SongRefresh] = []
        skipped: list[dict] = []
        totals = {"added": 0, "updated": 0, "restamped": 0, "deleted": 0,
                  "unchanged": 0}
        moves: list[int] = []
        gen_before = gen_after = 0
        stale_songs = 0
        for u in targets:
            existing = _parse(raw.get(u))
            gen_rows = [t for t in existing if t.source == "generated"]
            result = midsong_generator.plan_song(u, controls)
            if result.moments is None:
                skipped.append({"uri": u, "reason": result.reason})
                continue
            merge = midsong_generator.merge_song(existing, result.moments, result.stamp)
            if midsong_generator.is_stale(existing, result.stamp):
                stale_songs += 1
            gen_before += len(gen_rows)
            gen_after += len(gen_rows) + merge.added - merge.deleted
            for k in totals:
                totals[k] += getattr(merge, k)
            moves.extend(merge.moved_ms)
            if merge.changed:
                songs.append(SongRefresh(u, _generated_signature(raw.get(u)),
                                         result.stamp, merge))
            time.sleep(_YIELD_S)
        digest = hashlib.sha1(json.dumps(
            [[s.uri, s.snapshot, s.stamp] for s in songs]).encode("utf-8")).hexdigest()[:10]
        plan_id = f"{digest}-{uuid.uuid4().hex[:6]}"
        examples = sorted(songs, key=lambda s: (-len(s.merge.moved_ms),
                                                -(s.merge.added + s.merge.deleted)))[:10]
        report = {
            "status": "dry_run",
            "plan_id": plan_id,
            "scope": uri or "library",
            "expires_in_s": int(PLAN_TTL_S),
            "songs": {"scanned": len(targets), "stale": stale_songs,
                      "to_change": len(songs),
                      "unchanged": len(targets) - len(songs) - len(skipped),
                      "skipped": len(skipped)},
            "cues": {**totals, "moved": len(moves),
                     "generated_before": gen_before, "generated_after": gen_after},
            "moved": _move_stats(moves),
            "skipped": skipped[:20],
            "examples": [{"uri": s.uri, "title": _title(s.uri),
                          **s.merge.summary(),
                          "median_move_ms": (int(statistics.median(s.merge.moved_ms))
                                             if s.merge.moved_ms else None)}
                         for s in examples],
        }
        report["summary"] = _dry_run_sentence(report)
        _last_plan = LibraryPlan(plan_id, uri, time.monotonic(), _now_iso(), songs, report)
        _log({"kind": "dry_run", "at": _now_iso(), **_log_view(report)})
        logger.info("analysed refresh dry run %s: %s", plan_id, report["summary"])
        return report
    finally:
        _run_lock.release()


def _refused(uri: Optional[str], reason: str) -> dict:
    return {"status": "refused", "scope": uri or "library", "reason": reason}


def _dry_run_sentence(r: dict) -> str:
    s, c, m = r["songs"], r["cues"], r["moved"]
    moved = (f", {c['moved']} cues move (median {m['median_ms'] / 1000:.1f}s, "
             f"{m['over_2s']} by more than 2s)" if c["moved"] else "")
    return (f"{s['to_change']} of {s['scanned']} songs would change: "
            f"{c['added']} cues added, {c['deleted']} removed{moved}, "
            f"{c['restamped']} only re-stamped. "
            f"{s['skipped']} skipped. Nothing has been written yet.")


def _log_view(report: dict) -> dict:
    return {k: report[k] for k in ("plan_id", "scope", "songs", "cues", "moved",
                                    "summary") if k in report}


def _rebuild(rows: list, merge: midsong_generator.SongMerge) -> list:
    """The song's new row list: every row he owns stays in place, as is;
    generated rows are replaced in place or dropped; new ones go last."""
    upserts = {t.id: json.loads(t.model_dump_json()) for t in merge.upserts}
    dead = set(merge.delete_ids)
    out = []
    for r in rows:
        rid = r.get("id") if isinstance(r, dict) else None
        if rid in dead:
            continue
        if rid in upserts:
            out.append(upserts.pop(rid))
            continue
        out.append(r)
    out.extend(upserts.values())
    return out


def _owned(rows: Any) -> list:
    return [r for r in (rows if isinstance(rows, list) else [])
            if not (isinstance(r, dict) and r.get("source") == "generated")]


def _restore_unintended(old: dict, new: dict, applied: set[str]) -> int:
    """Put back anything the rebuild changed that it was not meant to: every
    song outside `applied` must be exactly as loaded, and every row of an
    applied song that is not a generated row must be identical and in the
    same order. Returns how many songs had to be restored."""
    restored = 0
    for u in set(old) | set(new):
        if u not in applied:
            if u not in old:
                new.pop(u, None)
                restored += 1
            elif new.get(u) is not old[u] and new.get(u) != old[u]:
                new[u] = old[u]
                restored += 1
            continue
        if _owned(new.get(u)) != _owned(old.get(u)):
            new[u] = old[u]
            applied.discard(u)
            restored += 1
    return restored


def apply(plan_id: Optional[str], uri: Optional[str] = None) -> dict:
    """Apply the dry run named `plan_id` — and nothing else. Refuses without
    a current matching plan. One backup, one write, verified."""
    global _last_plan
    if not plan_id:
        return _refused(uri, "run the dry run first and pass its plan_id")
    if not _run_lock.acquire(blocking=False):
        return {"status": "refused", "reason": "a refresh is already running"}
    try:
        p = _last_plan
        if p is None or p.plan_id != plan_id:
            return _refused(uri, "that dry run is not the current one (a newer "
                                 "dry run replaced it, or SPECTRA restarted) — "
                                 "run the dry run again")
        if p.scope != uri:
            return _refused(uri, f"that dry run was for {p.scope or 'the whole library'}, "
                                 "not this scope — run the dry run again")
        if time.monotonic() - p.created_mono > PLAN_TTL_S:
            return _refused(uri, "that dry run is more than an hour old — run it again")
        with trigger_store.write_lock:
            backup = _backup()
            old = trigger_store.load_raw()
            new = dict(old)
            applied: set[str] = set()
            changed_since: list[str] = []
            for s in p.songs:
                rows = old.get(s.uri)
                if rows is None or _generated_signature(rows) != s.snapshot:
                    changed_since.append(s.uri)
                    continue
                rebuilt = _rebuild(rows, s.merge)
                if rebuilt:
                    new[s.uri] = rebuilt
                else:
                    new.pop(s.uri, None)
                applied.add(s.uri)
            restored = _restore_unintended(old, new, applied)
            trigger_store.save_raw(new)
            verified = trigger_store.load_raw() == json.loads(json.dumps(new))
        done = [s for s in p.songs if s.uri in applied]
        totals = {k: sum(getattr(s.merge, k) for s in done)
                  for k in ("added", "updated", "restamped", "deleted")}
        moves = [m for s in done for m in s.merge.moved_ms]
        result = {
            "status": "applied" if verified else "applied-unverified",
            "plan_id": plan_id, "scope": uri or "library",
            "backup": str(backup) if backup else None,
            "songs": {"applied": len(done),
                      "changed_since_dry_run": len(changed_since)},
            "changed_since_dry_run": changed_since[:20],
            "cues": {**totals, "moved": len(moves)},
            "moved": _move_stats(moves),
            "restored": restored,
            "verified": verified,
        }
        result["summary"] = (
            f"Refreshed {len(done)} songs: {totals['added']} cues added, "
            f"{totals['deleted']} removed, {len(moves)} moved, "
            f"{totals['restamped']} re-stamped."
            + (f" {len(changed_since)} songs changed since the dry run and were "
               "left as they are." if changed_since else "")
            + (f" {restored} songs were put back untouched." if restored else "")
            + ("" if verified else " The saved file did NOT read back as written."))
        _log({"kind": "apply", "at": _now_iso(),
              **{k: result[k] for k in ("plan_id", "scope", "backup", "songs",
                                        "cues", "moved", "restored", "verified",
                                        "summary")}})
        logger.info("analysed refresh %s applied: %s", plan_id, result["summary"])
        _last_plan = None
        return result
    finally:
        _run_lock.release()


def _backup() -> Optional[Path]:
    src = config.TRIGGERS_FILE
    if not src.exists():
        return None
    dest_dir = backups_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"triggers-before-analysed-refresh-{stamp}.json"
    shutil.copy2(src, dest)
    return dest


def load_log() -> list[dict]:
    path = log_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _log(entry: dict) -> None:
    try:
        entries = (load_log() + [entry])[-LOG_MAX_ENTRIES:]
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        logger.exception("analysed refresh: could not write the refresh log")


async def refresh(uri: Optional[str] = None, dry_run: bool = True,
                  plan_id: Optional[str] = None) -> dict:
    """The one entry point Sonic and the HTTP route share: the dry run or
    the apply, off the event loop, then the playing song's cached analysed
    plan forgotten so its flares and markers follow the new cues."""
    import asyncio
    if dry_run:
        return await asyncio.to_thread(plan, uri)
    result = await asyncio.to_thread(apply, plan_id, uri)
    if result.get("status", "").startswith("applied"):
        try:
            from spectra.services.trigger_engine import trigger_engine
            trigger_engine.invalidate_analysed_plan()
        except Exception:
            logger.exception("analysed refresh: could not reset the playing song's plan")
    return result
