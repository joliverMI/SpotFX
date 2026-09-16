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
# is visible is the common component across a listening session.
#
# TWO readings are computed from the same gated pool, and they answer
# different questions — data/spectra-timing-drift-cause/report.md §4/§9:
#   - `level_ms` (LEVEL — the primary reading): each play's winning offset
#     minus that SAME SONG's own FIXED anchor (the median of its earliest
#     gated plays, never re-chosen as time passes). A steady chain reads
#     near zero; a step reads as a step; a ramp reads as a ramp. This is
#     what drives `current`/`alarm`.
#   - `median_residual_ms` (kept for continuity — NOT the headline any
#     more): each play's offset minus a SLIDING 36h–21d-old window of that
#     song's own gated plays. Because that window keeps re-centering on
#     recent history, this number approximates the *recent change in
#     level*, not the level itself — a steady ratchet reads as a small
#     constant, and a one-time step reads as a sign flip that decays over
#     days as the step ages into the sliding window. This is exactly what
#     turned a real ramp-then-step into "scattered further and crossed
#     sign" for two independent reports in 2026-09 (report §4, §6).
#
# Both pools are gated to LOCKED, quality-floor plays (`_is_baseline_grade`)
# — an unlocked or near-zero-Q play is not evidence of "this song's normal
# state," whichever mechanism is asking. Before this gate, real garbage sat
# in the pool at any quality (report §5.1: `Como Antes` +27575ms @ Q .41).
_DRIFT_SESSION_GAP_S = 2 * 3600   # a >2h silence starts a new listening session
_DRIFT_BASELINE_MIN_AGE_H = 36    # baseline plays must be at least this old …
_DRIFT_BASELINE_MAX_AGE_D = 21    # … and no older than this
DRIFT_ALARM_MS = 1500             # |session level| past this alarms — the lock
                                  # search tips over near 3 s stale-offset error,
                                  # so this fires with real headroom left
_DRIFT_MIN_BASELINED = 3          # sessions with fewer gated plays are
                                  # reported but never drive the alarm (applies
                                  # to both the level and the legacy residual)
_DRIFT_ANCHOR_ERA_DAYS = 4        # a song's fixed LEVEL anchor is the median of
                                  # its gated plays within this many days of the
                                  # OLDEST retained history — one shared
                                  # calendar window, not a per-song play count
                                  # (report §2's own method: "reference =
                                  # median offset over the oldest era the store
                                  # still holds"). Never re-chosen as later
                                  # plays arrive.
_DRIFT_STEP_MS = 2500             # a session-to-session LEVEL jump at/above this
                                  # is a discrete step (report's measured step
                                  # was ~4.7–5.1 s; its ramp deltas topped out
                                  # ~1.2 s) — never a session drifting on its own
_DRIFT_STABLE_BAND_MS = 200       # consecutive LEVELs within this band of each
                                  # other read as settled, not still moving
                                  # (the report's own post-step "rock-stable"
                                  # session held an IQR of ~150 ms)


def _drift_quality_floor() -> float:
    """The same bar `xcorr_sweep` requires before it will save an offset to
    disk (services/xcorr_sweep.py, `settings.xcorr_save_min_quality`,
    default 0.50) — a play too weak to trust for storage is too weak to
    trust as this song's "normal" state either."""
    try:
        from config import settings
        return float(getattr(settings, "xcorr_save_min_quality", 0.50))
    except Exception:
        return 0.50


def _is_baseline_grade(e: dict, floor: float) -> bool:
    """A play worth remembering as "this song's normal state": hard-locked
    (not just a best-of-planned-windows guess) and at/above the quality
    floor. Filters the unlocked/near-zero-Q garbage class out of both the
    legacy sliding baseline and the new fixed anchor — report §5.1."""
    if not e.get("locked"):
        return False
    try:
        q = float(e.get("quality", 0.0))
    except (TypeError, ValueError):
        return False
    return q >= floor

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

    Every play is gated to `_is_baseline_grade` (locked, at/above the same
    quality floor a disk save requires) before it can form or be measured
    against either pool below — an unlocked/near-zero-Q play is not
    evidence of a song's normal state, whichever pool is asking
    (report §5.1: this is what let `Como Antes` +27575ms @ Q .41 poison a
    session's numbers).

    Two readings per session, from that one gated pool:

    - LEVEL (`level_ms` / `level_baselined`, the primary reading): a song's
      FIXED anchor is the median of its own gated plays that fall inside one
      shared calendar era — the oldest _DRIFT_ANCHOR_ERA_DAYS of gated
      history the store still holds — never re-chosen as later plays
      arrive. A play only measures against the anchor once it is itself at
      least _DRIFT_BASELINE_MIN_AGE_H past the era's end. Every such play's
      residual is `offset − anchor`. Because the anchor never moves, a
      steady chain reads near zero, a step reads as a step, and a ramp
      reads as a ramp — this is what `current`/`alarm`/`shape` are built
      from. `shape` per session is computed against the previous qualifying
      session's level: "step" (|Δ| ≥ _DRIFT_STEP_MS), "stable" (|Δ| ≤
      _DRIFT_STABLE_BAND_MS), "ramp" (between), "start" (first qualifying
      session — nothing to compare yet), or "insufficient" (too few gated
      plays this session to trust a level at all).
    - median_residual_ms / baselined (kept for continuity, no longer the
      headline): the legacy SLIDING 36h–21d-old-baseline residual. Because
      that window keeps re-centering on recent history, it approximates the
      *recent change* in level, not the level — a steady ratchet reads as a
      small constant, and a one-time step reads as a sign flip that decays
      over days as the step ages into the window. This is what turned a
      real ramp-then-step into "scattered further and crossed sign" twice
      in 2026-09 (report §4, §6) — see the module-level comment above.

    A song with no gated play in the anchor era has no anchor and never
    contributes to the level pool — so an album of new songs, or a song
    first heard after the era, cannot move that number either.

    `current` is the most recent session with at least _DRIFT_MIN_BASELINED
    level-gated plays; `alarm` is true when its |level| ≥ DRIFT_ALARM_MS.
    Sessions come back newest first, capped at `max_sessions`.
    """
    with _lock:
        entries = list(_load())

    floor = _drift_quality_floor()
    plays: list[tuple[datetime, str, int, bool]] = []
    for e in entries:
        at = _parse_at(e.get("at", ""))
        if at is None:
            continue
        try:
            off = int(e.get("offset_ms", 0))
        except (TypeError, ValueError):
            continue
        plays.append((at, str(e.get("uri", "")), off, _is_baseline_grade(e, floor)))
    plays.sort(key=lambda p: p[0])

    by_uri_gated: dict[str, list[tuple[datetime, int]]] = {}
    for at, uri, off, gated in plays:
        if gated:
            by_uri_gated.setdefault(uri, []).append((at, off))

    min_age = timedelta(hours=_DRIFT_BASELINE_MIN_AGE_H)
    max_age = timedelta(days=_DRIFT_BASELINE_MAX_AGE_D)

    # Fixed per-song anchor: one shared calendar era (the oldest
    # _DRIFT_ANCHOR_ERA_DAYS of gated history the store still holds), never
    # re-chosen as later plays arrive. A play only measures against it once
    # it is itself at least min_age past the era's end, so the era is never
    # immediately treated as a settled reference the moment it closes.
    gated_ats = [at for (at, _, _, gated) in plays if gated]
    anchor_era_end = (min(gated_ats) + timedelta(days=_DRIFT_ANCHOR_ERA_DAYS)
                       if gated_ats else None)
    anchor_val: dict[str, float] = {}
    if anchor_era_end is not None:
        for uri, samples in by_uri_gated.items():
            era_samples = [o for (t, o) in samples if t <= anchor_era_end]
            if era_samples:
                anchor_val[uri] = statistics.median(era_samples)

    sessions: list[dict] = []
    cur: Optional[dict] = None
    last_at: Optional[datetime] = None
    for at, uri, off, gated in plays:
        if (last_at is None
                or (at - last_at).total_seconds() > _DRIFT_SESSION_GAP_S):
            cur = {"start": at, "end": at, "plays": 0, "residuals": [], "levels": []}
            sessions.append(cur)
        assert cur is not None
        cur["plays"] += 1
        cur["end"] = at
        last_at = at
        if not gated:
            continue
        baseline = [o for (t, o) in by_uri_gated.get(uri, ())
                    if at - max_age <= t <= at - min_age]
        if baseline:
            cur["residuals"].append(off - statistics.median(baseline))
        anchor = anchor_val.get(uri)
        if (anchor is not None
                and anchor_era_end is not None
                and at - anchor_era_end >= min_age):
            cur["levels"].append(off - anchor)

    # Second pass, oldest → newest (sessions is already in that order): fold
    # each session's residual/level lists into their reported numbers, and
    # classify LEVEL shape against the previous qualifying session.
    prev_level: Optional[float] = None
    for s in sessions:
        rs = s["residuals"]
        lv = s["levels"]
        s["baselined"] = len(rs)
        s["median_residual_ms"] = int(round(statistics.median(rs))) if rs else None
        s["level_baselined"] = len(lv)
        level = statistics.median(lv) if lv else None
        s["level_ms"] = int(round(level)) if level is not None else None
        if level is not None and len(lv) >= _DRIFT_MIN_BASELINED:
            if prev_level is None:
                s["shape"] = "start"
            else:
                delta = level - prev_level
                if abs(delta) >= _DRIFT_STEP_MS:
                    s["shape"] = "step"
                elif abs(delta) <= _DRIFT_STABLE_BAND_MS:
                    s["shape"] = "stable"
                else:
                    s["shape"] = "ramp"
            prev_level = level
        else:
            s["shape"] = "insufficient"

    out: list[dict] = []
    for s in reversed(sessions):                     # newest first
        out.append({
            "start_at": s["start"].isoformat(),
            "end_at": s["end"].isoformat(),
            "plays": s["plays"],
            "baselined": s["baselined"],
            "median_residual_ms": s["median_residual_ms"],
            "level_baselined": s["level_baselined"],
            "level_ms": s["level_ms"],
            "shape": s["shape"],
        })
        if len(out) >= max_sessions:
            break

    current = next((s for s in out
                    if s["level_baselined"] >= _DRIFT_MIN_BASELINED), None)
    alarm = bool(current
                 and current["level_ms"] is not None
                 and abs(current["level_ms"]) >= DRIFT_ALARM_MS)
    return {
        "sessions": out,
        "current": current,
        "alarm": alarm,
        "alarm_threshold_ms": DRIFT_ALARM_MS,
        "min_baselined": _DRIFT_MIN_BASELINED,
    }
