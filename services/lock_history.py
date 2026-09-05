"""
SpotFX — Per-play lock history.

One entry per completed xcorr play (any play that produced at least one
window measurement), recorded from auto_offset_service's finalize path.
This is the data behind the Timing page's "Lock history" panel: which songs
locked recently, how long the lock took, how good it was, and how much the
offset had to move.

Each entry:
    at               ISO timestamp (UTC) when the play's xcorr concluded
    uri / title / artist
    setlist_id       active Set List at the time (or None)
    play_type        "first" | "repeat" | ... (auto_offset classification)
    locked           True when lock-and-stop fired (hard lock mid-song)
    time_to_lock_ms  song position at the lock-and-stop moment (None when the
                     play only finished its planned windows without a hard lock)
    offset_ms        the winning offset for the play
    prev_offset_ms   offset on record before this play (None on first play)
    delta_ms         offset_ms − prev_offset_ms — the correction this lock needed
    quality          best Q of the play (pearson_r × difficulty, 0–1)
    n_windows        number of window measurements
    grade            A–F, see compute_grade()

Storage: storage/lock_history.json, most-recent first, capped. Same
single-process threading.Lock pattern as services/systemic_offset.py.
"""
from __future__ import annotations

import json
import logging
import statistics
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import BASE_DIR

logger = logging.getLogger(__name__)

_STORE_PATH = BASE_DIR / "storage" / "lock_history.json"
_CAP = 500          # entries kept on disk (~10s of KB)
_SLOW_LOCK_MS = 30_000   # hard lock landing after this long costs one grade notch

# ── Pipeline drift (the drift alarm) ──────────────────────────────────────────
# A pipeline-level latency change (a snapclient/monitor-chain fault, an audio
# routing shuffle) moves EVERY song's winning offset in the same direction.
# Per-song saves quietly re-learn it one play at a time, so the only place it
# is visible is the common component across a listening session: each play's
# winning offset minus that same song's own OLDER baseline, median'd per
# session. Calibrated against the real Aug 25 → Sep 2 2026 ratchet
# (~350 ms/day, reaching −3.2 s): with a 36 h minimum baseline age the median
# crossed 1.5 s on Aug 28 — four days before locks started failing — while
# every healthy session before the ratchet stayed well under 1 s. A younger
# baseline chases the drift and mutes the signal; a much older one starves
# sessions of baselined plays.
_DRIFT_SESSION_GAP_S = 2 * 3600   # a >2h silence starts a new listening session
_DRIFT_BASELINE_MIN_AGE_H = 36    # baseline plays must be at least this old …
_DRIFT_BASELINE_MAX_AGE_D = 21    # … and no older than this
DRIFT_ALARM_MS = 1500             # |session median| past this alarms — the lock
                                  # search tips over near 3 s stale-offset error,
                                  # so this fires with real headroom left
_DRIFT_MIN_BASELINED = 3          # sessions with fewer baselined plays are
                                  # reported but never drive the alarm

_lock = threading.Lock()
_entries: Optional[list[dict]] = None   # lazily loaded cache


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict]:
    global _entries
    if _entries is not None:
        return _entries
    try:
        raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        _entries = list(raw.get("entries") or [])
    except (FileNotFoundError, ValueError, OSError):
        _entries = []
    return _entries


def _persist() -> None:
    try:
        _STORE_PATH.write_text(
            json.dumps({"entries": _entries, "updated_at": _now_iso()}, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("lock_history: could not persist %s: %s", _STORE_PATH, exc)


def compute_grade(quality: float, locked: bool,
                  time_to_lock_ms: Optional[int]) -> str:
    """Letter grade for one play's lock.

    Base notch comes from the play's best Q (A ≥0.9, B ≥0.8, C ≥0.7,
    D ≥0.6, else F). A play that never hard-locked (no lock-and-stop) drops
    one notch — the offset was saved on looser evidence. A hard lock that
    took longer than _SLOW_LOCK_MS of song time also drops one notch: the
    song ran that long on the cold-start baseline before correction.
    """
    q = float(quality)
    if q >= 0.9:
        notch = 0
    elif q >= 0.8:
        notch = 1
    elif q >= 0.7:
        notch = 2
    elif q >= 0.6:
        notch = 3
    else:
        notch = 4
    if not locked:
        notch += 1
    if time_to_lock_ms is not None and time_to_lock_ms > _SLOW_LOCK_MS:
        notch += 1
    return "ABCDF"[min(notch, 4)]


def record(
    *,
    uri: str,
    title: str = "",
    artist: str = "",
    setlist_id: Optional[str] = None,
    play_type: str = "",
    locked: bool = False,
    time_to_lock_ms: Optional[int] = None,
    offset_ms: int = 0,
    prev_offset_ms: Optional[int] = None,
    quality: float = 0.0,
    n_windows: int = 0,
) -> None:
    """Append one play's lock outcome and persist. Never raises."""
    try:
        entry = {
            "at": _now_iso(),
            "uri": uri,
            "title": title or "",
            "artist": artist or "",
            "setlist_id": setlist_id,
            "play_type": play_type,
            "locked": bool(locked),
            "time_to_lock_ms": int(time_to_lock_ms) if time_to_lock_ms is not None else None,
            "offset_ms": int(offset_ms),
            "prev_offset_ms": int(prev_offset_ms) if prev_offset_ms is not None else None,
            "delta_ms": (int(offset_ms) - int(prev_offset_ms)
                         if prev_offset_ms is not None else None),
            "quality": round(float(quality), 3),
            "n_windows": int(n_windows),
            "grade": compute_grade(quality, locked, time_to_lock_ms),
        }
        with _lock:
            entries = _load()
            entries.insert(0, entry)
            del entries[_CAP:]
            _persist()
        logger.info(
            "lock_history: %s grade=%s ttl=%s offset=%+dms Q=%.2f (%s — %s)",
            "locked" if locked else "no hard lock", entry["grade"],
            f"{time_to_lock_ms}ms" if time_to_lock_ms is not None else "—",
            int(offset_ms), float(quality), artist, title,
        )
    except Exception as exc:   # history must never break the xcorr loop
        logger.warning("lock_history: record failed: %s", exc)


def recent_songs(limit: int = 10) -> list[dict]:
    """Most recent entry per distinct song (uri), newest first."""
    with _lock:
        entries = list(_load())
    seen: set[str] = set()
    out: list[dict] = []
    for e in entries:
        u = e.get("uri", "")
        if u in seen:
            continue
        seen.add(u)
        out.append(e)
        if len(out) >= limit:
            break
    return out


def search(q: str, limit: int = 100) -> list[dict]:
    """All entries matching `q` (case-insensitive substring on title, artist,
    or uri), newest first — multiple plays of the same song included."""
    needle = (q or "").strip().lower()
    with _lock:
        entries = list(_load())
    if not needle:
        return entries[:limit]
    out = []
    for e in entries:
        hay = " ".join([e.get("title") or "", e.get("artist") or "",
                        e.get("uri") or ""]).lower()
        if needle in hay:
            out.append(e)
            if len(out) >= limit:
                break
    return out


def entries_for_uri(uri: str, limit: int = 50) -> list[dict]:
    """All plays of one song, newest first."""
    with _lock:
        entries = list(_load())
    return [e for e in entries if e.get("uri") == uri][:limit]


def _parse_at(ts: str) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    if at.tzinfo is None:      # defensive — record() always stamps UTC-aware
        at = at.replace(tzinfo=timezone.utc)
    return at


def pipeline_drift(max_sessions: int = 10) -> dict:
    """The pipeline-drift instrument behind the Timing page's drift line.

    For each recorded play whose song has an OLDER baseline (plays of the
    same uri between _DRIFT_BASELINE_MIN_AGE_H and _DRIFT_BASELINE_MAX_AGE_D
    before it), the residual is `winning offset − median(baseline offsets)`.
    Plays are grouped into listening sessions (a >2h silence starts a new
    one) and each session reports the median residual over its baselined
    plays. Per-song capture quirks cancel in that median; what survives is
    the common component — exactly what a pipeline-level latency change
    (audio-chain fault, routing shuffle) produces and what per-song saves
    quietly absorb before anyone notices.

    First-ever plays have no baseline and are excluded by construction, so
    an album of new songs cannot move this number.

    `current` is the most recent session with at least _DRIFT_MIN_BASELINED
    baselined plays; `alarm` is true when its |median| ≥ DRIFT_ALARM_MS.
    Sessions come back newest first, capped at `max_sessions`.
    """
    with _lock:
        entries = list(_load())

    plays: list[tuple[datetime, str, int]] = []
    for e in entries:
        at = _parse_at(e.get("at", ""))
        if at is None:
            continue
        try:
            off = int(e.get("offset_ms", 0))
        except (TypeError, ValueError):
            continue
        plays.append((at, str(e.get("uri", "")), off))
    plays.sort(key=lambda p: p[0])

    by_uri: dict[str, list[tuple[datetime, int]]] = {}
    for at, uri, off in plays:
        by_uri.setdefault(uri, []).append((at, off))

    min_age = timedelta(hours=_DRIFT_BASELINE_MIN_AGE_H)
    max_age = timedelta(days=_DRIFT_BASELINE_MAX_AGE_D)

    sessions: list[dict] = []
    cur: Optional[dict] = None
    last_at: Optional[datetime] = None
    for at, uri, off in plays:
        if (last_at is None
                or (at - last_at).total_seconds() > _DRIFT_SESSION_GAP_S):
            cur = {"start": at, "end": at, "plays": 0, "residuals": []}
            sessions.append(cur)
        assert cur is not None
        cur["plays"] += 1
        cur["end"] = at
        last_at = at
        baseline = [o for (t, o) in by_uri.get(uri, ())
                    if at - max_age <= t <= at - min_age]
        if baseline:
            cur["residuals"].append(off - statistics.median(baseline))

    out: list[dict] = []
    for s in reversed(sessions):                     # newest first
        rs = s["residuals"]
        out.append({
            "start_at": s["start"].isoformat(),
            "end_at": s["end"].isoformat(),
            "plays": s["plays"],
            "baselined": len(rs),
            "median_residual_ms": int(round(statistics.median(rs))) if rs else None,
        })
        if len(out) >= max_sessions:
            break

    current = next((s for s in out
                    if s["baselined"] >= _DRIFT_MIN_BASELINED), None)
    alarm = bool(current
                 and abs(current["median_residual_ms"]) >= DRIFT_ALARM_MS)
    return {
        "sessions": out,
        "current": current,
        "alarm": alarm,
        "alarm_threshold_ms": DRIFT_ALARM_MS,
        "min_baselined": _DRIFT_MIN_BASELINED,
    }
