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
The drift instrument's per-song anchors live beside it in
storage/lock_history_anchors.json, written as plays are recorded and never
evicted with the capped log — see pipeline_drift(). The anchor era never
moves on its own; the one way to adopt a new one is reanchor(), an explicit,
audited act a person takes (POST /api/lock-history/drift/reanchor).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import statistics
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
#     minus that SAME SONG's own FIXED anchor (the median of its gated plays
#     in the anchor era, recorded into the anchors store as they arrive, so
#     the capped log evicting them can never move it). A steady chain reads
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
                                  # OLDEST gated history — one shared calendar
                                  # window, not a per-song play count (report
                                  # §2's own method: "reference = median offset
                                  # over the oldest era the store still holds").
                                  # The era and its samples are recorded once
                                  # into the anchors store, so later eviction
                                  # from the capped log cannot re-choose them;
                                  # only reanchor() — a person, on purpose —
                                  # ever adopts a different era.
_DRIFT_STEP_MS = 2500             # a session-to-session LEVEL jump at/above this
                                  # is a discrete step (report's measured step
                                  # was ~4.7–5.1 s; its ramp deltas topped out
                                  # ~1.2 s) — never a session drifting on its own
_DRIFT_RAMP_MAX_MS_PER_DAY = 1000 # … but only when no ramp this fast could have
                                  # covered the jump in the time between the two
                                  # readings (previous session's start → this
                                  # session's end); otherwise two points that far
                                  # apart cannot tell a step from a ramp, and the
                                  # session reads "step_or_ramp". Measured on a
                                  # read-only copy of storage/lock_history.json
                                  # (500 plays, Aug 28 → Sep 14 2026): 6 transitions
                                  # between qualifying sessions, 0.94–4.02 d apart;
                                  # the four ramps ran −236/−455/−290/−297 ms/d
                                  # (fastest −491 start→start); the one real step,
                                  # +5122 ms, ran +2370 ms/d; 94 same-song gated
                                  # pairs ≥12 h apart that do not straddle it:
                                  # |rate| p50 254 / p90 550 / p95 986 ms/d. 1000 is
                                  # ~2× the fastest session ramp and ≥2.3× under
                                  # the step. (At 491 ms/d the flat 2500 ms bound
                                  # alone mislabels a ramp only across ≥5.1 d; the
                                  # longest real gap so far is 4.02 d.)
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
_anchor_seed_oldest: Optional[str] = None   # oldest `at` the log held when an
                                            # anchor era was last derived for a
                                            # save that has not landed yet
_anchors_persisted_at: Optional[str] = None  # when an anchors store was first
                                             # written; once set, a missing
                                             # store is never rebuilt on its own
_anchor_samples_unsaved: list[dict] = []     # gated in-era plays whose save into
                                             # an already-written store failed,
                                             # retried while their era is open


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict]:
    global _entries, _anchor_seed_oldest, _anchors_persisted_at, _anchor_samples_unsaved
    if _entries is not None:
        return _entries
    try:
        raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        _entries = list(raw.get("entries") or [])
        _anchor_seed_oldest = raw.get("anchor_seed_oldest_at")
        _anchors_persisted_at = raw.get("anchors_persisted_at")
        _anchor_samples_unsaved = [dict(p) for p in raw.get("anchor_samples_unsaved") or []
                                   if isinstance(p, dict)]
    except (FileNotFoundError, ValueError, OSError):
        _entries = []
        _anchor_seed_oldest = None
        _anchors_persisted_at = None
        _anchor_samples_unsaved = []
    return _entries


def _persist() -> None:
    try:
        _STORE_PATH.write_text(
            json.dumps({"entries": _entries,
                        "anchor_seed_oldest_at": _anchor_seed_oldest,
                        "anchors_persisted_at": _anchors_persisted_at,
                        "anchor_samples_unsaved": _anchor_samples_unsaved,
                        "updated_at": _now_iso()}, indent=2),
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
            _extend_anchor_era(entries, entry)
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


def _gated_plays(entries: list[dict], floor: float) -> list[tuple[datetime, str, int, bool]]:
    """(at, uri, offset_ms, baseline-grade) for every parseable entry, oldest first."""
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
    return plays


def _anchor_path() -> Path:
    return _STORE_PATH.with_name(_STORE_PATH.stem + "_anchors.json")


class AnchorStoreUnreadable(ValueError):
    """The anchors store exists but cannot be trusted. It is never rebuilt
    from the capped log in that case: re-deriving it there would silently
    swap every song's fixed anchor for a later, moving one."""


class ReanchorRefused(ValueError):
    """A re-anchor that cannot be carried out honestly, said in words.
    Nothing is written when one is raised."""


def _load_anchor_era() -> Optional[dict]:
    """The recorded anchor era — {"start", "end", "samples": {uri: [ms]},
    "reanchors": [audit events]} — or None when none has been recorded yet."""
    path = _anchor_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise AnchorStoreUnreadable(f"{path}: {exc}") from exc
    try:
        start = _parse_at(raw["era_start"])
        end = _parse_at(raw["era_end"])
        samples = {str(uri): [int(o) for o in offs]
                   for uri, offs in dict(raw["samples"]).items()}
        reanchors = [dict(ev) for ev in raw.get("reanchors", [])]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise AnchorStoreUnreadable(f"{path}: {exc!r}") from exc
    if start is None or end is None:
        raise AnchorStoreUnreadable(f"{path}: unparseable era bounds")
    return {"start": start, "end": end, "samples": samples, "reanchors": reanchors}


def _oldest_at(entries: list[dict]) -> Optional[datetime]:
    ats = [at for at in (_parse_at(e.get("at", "")) for e in entries) if at is not None]
    return min(ats) if ats else None


def _era_derivable_from_log(entries: list[dict]) -> bool:
    """Whether reading the anchor era off `entries` in memory is honest.

    Never once an anchors store has been written: a store missing after that
    (deleted, lost, or holding a re-anchored era the log's oldest-days rule
    cannot reproduce) is restored only by an explicit reanchor(). Before the
    first write lands, only while the log still holds the oldest play it held
    when the latest save was attempted — in the gap after a failed save on a
    full log, the era the next record() will persist is not knowable yet, so
    no song has a level rather than a moving one."""
    if _anchors_persisted_at is not None:
        return False
    if _anchor_seed_oldest is None:
        return True
    seed = _parse_at(_anchor_seed_oldest)
    oldest = _oldest_at(entries)
    return seed is not None and oldest is not None and oldest <= seed


def _derive_anchor_era(plays: list[tuple[datetime, str, int, bool]]) -> Optional[dict]:
    """The anchor era as the log holds it right now: the oldest
    _DRIFT_ANCHOR_ERA_DAYS of gated plays. Used to seed the store (and
    re-seed it after a save that did not land), and to read a log whose
    store has never been written (`_era_derivable_from_log`)."""
    gated = [(at, uri, off) for (at, uri, off, ok) in plays if ok]
    if not gated:
        return None
    start = min(at for at, _, _ in gated)
    end = start + timedelta(days=_DRIFT_ANCHOR_ERA_DAYS)
    samples: dict[str, list[int]] = {}
    for at, uri, off in gated:
        if at <= end:
            samples.setdefault(uri, []).append(off)
    return {"start": start, "end": end, "samples": samples, "reanchors": []}


def _save_anchor_era(era: dict) -> None:
    path = _anchor_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({
        "era_start": era["start"].isoformat(),
        "era_end": era["end"].isoformat(),
        "samples": era["samples"],
        "reanchors": era.get("reanchors", []),
        "updated_at": _now_iso(),
    }, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _extend_anchor_era(entries: list[dict], entry: dict) -> None:
    """Called under _lock with the log as it stands BEFORE `entry` is
    inserted and anything is evicted.

    Until an anchors store has been written, every call derives the era from
    the gated history the log holds right now and tries to write it — so a
    save that fails (a transient OSError) is simply tried again on the next
    play, from whatever the log still holds, instead of blinding the level
    for good. Once one has landed, the call only adds `entry` if it is a
    gated play inside the era, plus any earlier in-era play whose own save
    failed (`_anchor_samples_unsaved`) while the era is still open; once a
    play lands past the era's end nothing is ever added again, so every
    song's anchor is fixed from then on. A store that was written and later
    goes missing is never rebuilt here — that would be the anchor moving on
    its own; reanchor() is the way back."""
    global _anchor_seed_oldest, _anchors_persisted_at, _anchor_samples_unsaved
    try:
        floor = _drift_quality_floor()
        # A store that was written once and later vanishes or turns
        # unreadable is deliberately NOT rebuilt or re-derived here, unlike a
        # store whose first write never landed. On a capped log a re-anchor
        # to the original era's own start is refused as evicted, so an
        # automatic rebuild could only adopt a DIFFERENT era while presenting
        # as the original — a confident wrong answer, the one outcome this
        # instrument exists to refuse. A vanished store is an operator-visible
        # event (a disk fault, a deletion, corruption): it is reported loudly
        # (anchor_status "missing"/"unreadable") and repaired only by a
        # person's explicit reanchor().
        try:
            era = _load_anchor_era()
        except AnchorStoreUnreadable as exc:
            logger.warning("lock_history: anchors store unreadable, left untouched — "
                           "the drift level reports no anchors until someone re-anchors "
                           "on purpose: %s", exc)
            return
        changed = False
        retried: list[dict] = []
        at = _parse_at(entry.get("at", ""))
        if era is None:
            if _anchors_persisted_at is not None:
                logger.warning("lock_history: anchors store %s was written %s and is now "
                               "missing — not rebuilt, which would move every anchor; the "
                               "drift level reports no anchors until someone re-anchors on "
                               "purpose (POST /api/lock-history/drift/reanchor)",
                               _anchor_path(), _anchors_persisted_at)
                return
            # KNOWN FOLLOW-UP, not built (firstmate's ruling, decision key
            # drift-era-shift-on-heal): if the very first save attempt fails
            # (e.g. a transient OSError) and a LATER record() heals it here,
            # this derives the era from the log AS IT STANDS NOW — one play
            # newer than the original attempt saw — rather than from the
            # exact original window. Measured effect: the era's own start
            # can shift by minutes and a few already-reported levels can
            # shift ~15-39ms. Ruled acceptable to ship because nothing
            # USER-VISIBLE ever moved: a pending save reports
            # anchor_status="save_pending" and NO level, never a displayed
            # one that later changes — so the shift is against a value he
            # never saw, not an anchor moving under him. The gap that still
            # wants closing: when a heal CANNOT reproduce the original
            # window (the plays it needs are already evicted), it should
            # either derive from the ORIGINAL window (if still available)
            # or refuse to substitute silently and leave it to the audited
            # re-anchor path (loud-and-missing beats silently-wrong) — it
            # currently always substitutes from the current log instead.
            era = _derive_anchor_era(_gated_plays(entries, floor))
            changed = era is not None
        else:
            if _anchors_persisted_at is None:
                _anchors_persisted_at = _now_iso()
            # Retrying an in-era play whose save failed only ever adds its
            # sample to the still-open era: bounds and every sample already
            # stored stay exactly as they are, and nothing is added once the
            # era has closed, when its anchors start being read against. His
            # live era closed long ago, so this cannot bite today — but the
            # explicit reanchor() this instrument offers is exactly what makes
            # an era that includes the present reachable again.
            now_at = at if at is not None else _parse_at(_now_iso())
            if _anchor_samples_unsaved and now_at is not None and now_at <= era["end"]:
                for pending in _anchor_samples_unsaved:
                    p_at = _parse_at(pending.get("at", ""))
                    if p_at is not None and era["start"] <= p_at <= era["end"]:
                        era["samples"].setdefault(str(pending.get("uri", "")), []).append(
                            int(pending.get("offset_ms", 0)))
                        retried.append(pending)
                changed = bool(retried)
        added: Optional[dict] = None
        if at is not None and _is_baseline_grade(entry, floor):
            if era is None:
                era = {"start": at,
                       "end": at + timedelta(days=_DRIFT_ANCHOR_ERA_DAYS),
                       "samples": {}, "reanchors": []}
            if era["start"] <= at <= era["end"]:
                added = {"at": entry.get("at", ""), "uri": str(entry.get("uri", "")),
                         "offset_ms": int(entry.get("offset_ms", 0))}
                era["samples"].setdefault(added["uri"], []).append(added["offset_ms"])
                changed = True
        if not (changed and era is not None):
            return
        was_persisted = _anchors_persisted_at is not None
        if not was_persisted:
            oldest = _oldest_at(entries + [entry])
            _anchor_seed_oldest = oldest.isoformat() if oldest is not None else None
        try:
            _save_anchor_era(era)
        except Exception as exc:
            if not was_persisted:
                logger.warning("lock_history: could not write the anchors store — no song "
                               "has a level until a later play's save lands, which retries "
                               "from the history the log still holds: %s", exc)
                return
            if added is not None:
                _anchor_samples_unsaved = _anchor_samples_unsaved + [added]
            logger.warning("lock_history: could not save %d in-era play(s) into the anchors "
                           "store — retried on every later play while the era is open "
                           "(until %s): %s", len(_anchor_samples_unsaved),
                           era["end"].isoformat(), exc)
            return
        if retried:
            _anchor_samples_unsaved = [p for p in _anchor_samples_unsaved
                                       if not any(p is r for r in retried)]
        if not was_persisted:
            _anchors_persisted_at = _now_iso()
    except Exception as exc:
        logger.warning("lock_history: could not update anchors store: %s", exc)


def _anchor_values(era: dict) -> dict[str, float]:
    return {uri: statistics.median(s) for uri, s in era["samples"].items() if s}


def _era_summary(era: dict) -> dict:
    return {"start_at": era["start"].isoformat(),
            "end_at": era["end"].isoformat(),
            "songs": len(_anchor_values(era)),
            "plays": sum(len(s) for s in era["samples"].values())}


def _plan_reanchor(entries: list[dict], start_at: str, now: datetime) -> dict:
    """The era a re-anchor starting at `start_at` would adopt, taken from the
    log's gated plays inside it — or ReanchorRefused, in words."""
    start = _parse_at(start_at) if isinstance(start_at, str) else None
    if start is None:
        raise ReanchorRefused(f"start_at {start_at!r} is not an ISO-8601 timestamp")
    if start > now:
        raise ReanchorRefused(f"start_at {start.isoformat()} is in the future — "
                              "an anchor era can only begin at or before now")
    oldest = _oldest_at(entries)
    if oldest is None:
        raise ReanchorRefused("the lock history holds no plays to anchor against")
    if len(entries) >= _CAP and start < oldest:
        raise ReanchorRefused(
            f"start_at {start.isoformat()} is before the oldest play the capped lock "
            f"history still holds ({oldest.isoformat()}) — plays from that window may "
            "already be evicted, so the anchors could not be taken from them whole")
    end = start + timedelta(days=_DRIFT_ANCHOR_ERA_DAYS)
    samples: dict[str, list[int]] = {}
    for at, uri, off, ok in _gated_plays(entries, _drift_quality_floor()):
        if ok and start <= at <= end:
            samples.setdefault(uri, []).append(off)
    if not samples and end <= now:
        raise ReanchorRefused(
            f"no locked, quality-gated play falls between {start.isoformat()} and "
            f"{end.isoformat()}, and that window has closed — no song would have an anchor")
    return {"start": start, "end": end, "samples": samples, "reanchors": []}


def _salvage_reanchors() -> list[dict]:
    """Every re-anchor audit event still recoverable from an anchors store
    that no longer loads as a whole — one bad sample or era bound must not
    cost the history of who re-anchored, when, why, and what they replaced."""
    try:
        raw = json.loads(_anchor_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    events = raw.get("reanchors") if isinstance(raw, dict) else None
    return [dict(ev) for ev in events if isinstance(ev, dict)] if isinstance(events, list) else []


def _current_era_for_reanchor() -> tuple[Optional[dict], Optional[str], list[dict]]:
    """The era a re-anchor would replace, a note when there is none to read,
    and the audit trail to carry forward (salvaged when the store is unreadable)."""
    try:
        era = _load_anchor_era()
    except AnchorStoreUnreadable as exc:
        return None, f"unreadable: {exc}", _salvage_reanchors()
    if era is None:
        return None, ("missing after it was written" if _anchors_persisted_at is not None
                      else "never written"), []
    return era, None, era["reanchors"]


def _anchor_moves(previous: Optional[dict], new: dict) -> dict:
    before = _anchor_values(previous) if previous is not None else {}
    after = _anchor_values(new)
    moves = [after[u] - before[u] for u in after if u in before]
    return {"songs_compared": len(moves),
            "median_move_ms": int(round(statistics.median(moves))) if moves else None}


def preview_reanchor(start_at: str) -> dict:
    """What reanchor() would adopt from `start_at`, without writing anything."""
    with _lock:
        entries = list(_load())
        now = _parse_at(_now_iso())
        assert now is not None
        new = _plan_reanchor(entries, start_at, now)
        previous, note, history = _current_era_for_reanchor()
    return {
        "new": {**_era_summary(new),
                "open": new["end"] > now,
                "measurable_from": (new["end"]
                                    + timedelta(hours=_DRIFT_BASELINE_MIN_AGE_H)).isoformat()},
        "previous": _era_summary(previous) if previous is not None else None,
        "previous_note": note,
        "reanchors_carried": len(history),
        "anchor_moves": _anchor_moves(previous, new),
    }


def reanchor(*, start_at: str, by: str, reason: str,
             client: Optional[str] = None) -> dict:
    """Adopt a new anchor era on purpose — the only way the era ever changes.

    Never called by anything automatic. The new era is the
    _DRIFT_ANCHOR_ERA_DAYS from `start_at`, its anchors taken from the gated
    plays the log holds in that window (and, while the window is still open,
    from gated plays recorded into it afterwards). The whole replaced era —
    its bounds and every sample — is kept in the store's `reanchors` audit
    trail with who asked, why, when, and from where, and a WARNING is logged.
    Also the repair for a store that is unreadable or missing after it was
    written; an unreadable store is first copied aside byte-for-byte (its
    path recorded in the event's `previous_note`) and every audit event
    still recoverable from it is carried forward. Raises ReanchorRefused (nothing written) when it cannot be done
    honestly; an OSError writing the store propagates, also with nothing
    changed."""
    global _anchor_seed_oldest, _anchors_persisted_at, _anchor_samples_unsaved
    by = (by or "").strip()
    reason = (reason or "").strip()
    if not by:
        raise ReanchorRefused("say who is re-anchoring (`by`) — a re-anchor is an audited act")
    if not reason:
        raise ReanchorRefused("say why (`reason`) — a re-anchor is an audited act")
    with _lock:
        entries = _load()
        now_iso = _now_iso()
        now = _parse_at(now_iso)
        assert now is not None
        new = _plan_reanchor(entries, start_at, now)
        previous, note, history = _current_era_for_reanchor()
        if note is not None and note.startswith("unreadable"):
            path = _anchor_path()
            stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            aside = path.with_name(f"{path.stem}.unreadable-{stamp}{path.suffix}")
            shutil.copy2(path, aside)
            note = (f"{note} — the unreadable store was kept as {aside}; "
                    f"{len(history)} earlier re-anchor event(s) recovered from it")
        event = {
            "at": now_iso,
            "by": by,
            "reason": reason,
            "client": client,
            "previous": ({**_era_summary(previous), "samples": previous["samples"]}
                         if previous is not None else None),
            "previous_note": note,
            "new": _era_summary(new),
            "anchor_moves": _anchor_moves(previous, new),
        }
        new["reanchors"] = history + [event]
        _save_anchor_era(new)
        oldest = _oldest_at(entries)
        _anchor_seed_oldest = oldest.isoformat() if oldest is not None else None
        _anchors_persisted_at = now_iso
        _anchor_samples_unsaved = []
        _persist()
    logger.warning(
        "lock_history: anchor era RE-ANCHORED by %s from %s (reason: %s) — was %s, now "
        "%s → %s (%d songs); anchors moved by a median of %s ms over %d songs",
        by, client or "an unknown client", reason,
        (f"{event['previous']['start_at']} → {event['previous']['end_at']}"
         if event["previous"] else note),
        event["new"]["start_at"], event["new"]["end_at"], event["new"]["songs"],
        event["anchor_moves"]["median_move_ms"], event["anchor_moves"]["songs_compared"])
    return {k: v for k, v in event.items() if k != "previous"} | {
        "previous": ({k: v for k, v in event["previous"].items() if k != "samples"}
                     if event["previous"] is not None else None)}


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
      shared calendar era — the first _DRIFT_ANCHOR_ERA_DAYS of gated
      history. record() writes the era and its plays into the anchors store
      as they arrive (seeding it from the log, and re-seeding it on every
      later play until a write lands), so the capped log dropping them never
      re-chooses either. A log whose store has never been written derives
      the era in memory, but only while it still holds what the latest save
      attempt was seeded from; an anchors store that exists but cannot be
      read, one missing after it was written, or one whose write has not
      landed since the log evicted past that seed yields NO anchors — every
      level is None — never a re-derived, moving one. Only reanchor(), a
      person's explicit and audited act, ever adopts a different era
      (`anchor_era.last_reanchor` names the latest). A play only measures
      against the anchor once it is itself at least
      _DRIFT_BASELINE_MIN_AGE_H past the era's end. Every such play's
      residual is `offset − anchor`. Because the anchor never moves, a
      steady chain reads near zero, a step reads as a step, and a ramp
      reads as a ramp — this is what `current`/`alarm`/`shape` are built
      from. `shape` per session is computed against the previous qualifying
      session's level: "stable" (|Δ| ≤ _DRIFT_STABLE_BAND_MS); "step" (|Δ| ≥
      _DRIFT_STEP_MS and faster than _DRIFT_RAMP_MAX_MS_PER_DAY over the
      previous session's start → this session's end); "step_or_ramp" (a
      step-sized move across a gap long enough that a ramp could also have
      made it); "ramp" (a smaller move in the same direction as the last
      session that moved, or with no earlier move to compare); "reversal"
      (a smaller move the opposite way from the last session that moved —
      several in a row is scatter, not a trend); "start" (first qualifying
      session — nothing to compare yet); or "insufficient" (too few gated
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
    `anchor_status` says where the era came from, or why there is none:
    "recorded", "not_yet_recorded" (derived from a log whose store has never
    been written), "no_gated_history", "save_pending", "missing", "unreadable"
    — or, for a recorded era, "samples_pending" / "samples_lost" when
    `anchor_samples_unsaved` in-era plays could not be saved into it (still
    retried while the era is open / no longer, once it has closed).
    """
    floor = _drift_quality_floor()
    with _lock:
        entries = list(_load())
        plays = _gated_plays(entries, floor)
        try:
            era = _load_anchor_era()
            anchor_status = "recorded"
            if era is None:
                if _era_derivable_from_log(entries):
                    era = _derive_anchor_era(plays)
                    anchor_status = "not_yet_recorded"
                elif _anchors_persisted_at is not None:
                    anchor_status = "missing"
                    logger.warning("lock_history: anchors store %s was written %s and is now "
                                   "missing — no song has an anchor until someone re-anchors "
                                   "on purpose", _anchor_path(), _anchors_persisted_at)
                else:
                    anchor_status = "save_pending"
                    logger.warning("lock_history: anchors store %s has not been written yet "
                                   "and the log has evicted plays since the last attempt — no "
                                   "song has an anchor until a later play's save lands",
                                   _anchor_path())
        except AnchorStoreUnreadable as exc:
            logger.warning("lock_history: anchors store unreadable — no song has "
                           "an anchor until someone re-anchors on purpose: %s", exc)
            era = None
            anchor_status = "unreadable"
        unsaved = len(_anchor_samples_unsaved)
    if era is None and anchor_status in ("recorded", "not_yet_recorded"):
        anchor_status = "no_gated_history"
    if anchor_status == "recorded" and unsaved:
        now = _parse_at(_now_iso())
        anchor_status = ("samples_pending" if now is not None and now <= era["end"]
                         else "samples_lost")
        logger.warning("lock_history: %d gated play(s) inside the anchor era (until %s) "
                       "could not be saved into the anchors store — %s", unsaved,
                       era["end"].isoformat(),
                       "retried on every later play while the era is open"
                       if anchor_status == "samples_pending" else
                       "the era has closed, so their songs' anchors are missing those "
                       "plays until someone re-anchors on purpose")

    by_uri_gated: dict[str, list[tuple[datetime, int]]] = {}
    for at, uri, off, gated in plays:
        if gated:
            by_uri_gated.setdefault(uri, []).append((at, off))

    min_age = timedelta(hours=_DRIFT_BASELINE_MIN_AGE_H)
    max_age = timedelta(days=_DRIFT_BASELINE_MAX_AGE_D)

    # A play only measures against its song's anchor once it is itself at
    # least min_age past the era's end, so the era is never immediately
    # treated as a settled reference the moment it closes.
    anchor_era_end = era["end"] if era is not None else None
    anchor_val: dict[str, float] = {}
    if era is not None:
        for uri, samples in era["samples"].items():
            if samples:
                anchor_val[uri] = statistics.median(samples)

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
    prev: Optional[dict] = None
    last_move_sign = 0
    for s in sessions:
        rs = s["residuals"]
        lv = s["levels"]
        s["baselined"] = len(rs)
        s["median_residual_ms"] = int(round(statistics.median(rs))) if rs else None
        s["level_baselined"] = len(lv)
        level = statistics.median(lv) if lv else None
        s["level_ms"] = int(round(level)) if level is not None else None
        if level is not None and len(lv) >= _DRIFT_MIN_BASELINED:
            if prev is None:
                s["shape"] = "start"
            else:
                delta = level - prev["level"]
                sign = 1 if delta > 0 else -1
                span_days = (s["end"] - prev["start"]).total_seconds() / 86400
                if abs(delta) <= _DRIFT_STABLE_BAND_MS:
                    s["shape"] = "stable"
                elif abs(delta) >= _DRIFT_STEP_MS:
                    s["shape"] = ("step" if abs(delta) > _DRIFT_RAMP_MAX_MS_PER_DAY * span_days
                                  else "step_or_ramp")
                elif last_move_sign and sign != last_move_sign:
                    s["shape"] = "reversal"
                else:
                    s["shape"] = "ramp"
                if s["shape"] != "stable":
                    last_move_sign = sign
            prev = {"level": level, "start": s["start"]}
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
        "anchor_era": ({"start_at": era["start"].isoformat(),
                        "end_at": era["end"].isoformat(),
                        "songs": len(anchor_val),
                        "reanchors": len(era["reanchors"]),
                        "last_reanchor": ({k: era["reanchors"][-1].get(k)
                                           for k in ("at", "by", "reason")}
                                          if era["reanchors"] else None)}
                       if era is not None else None),
        "anchor_status": anchor_status,
        "anchor_samples_unsaved": unsaved,
    }
