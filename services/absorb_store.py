"""
SpotFX — Absorb Music's four stores (models/absorb.py says what each holds).

Every write is tmp + os.replace, so a reader (or a crash) only ever sees a
whole file. Every read tolerates a missing or unreadable file by returning
the defaults — a corrupt run file must never stop his config from loading.
Paths are module attributes so a test repoints them.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

from config import BASE_DIR
from models.absorb import AbsorbConfig, AbsorbLedger, AbsorbRun, AbsorbSchedule

logger = logging.getLogger(__name__)

CONFIG_FILE = BASE_DIR / "storage" / "absorb.json"
RUN_FILE = BASE_DIR / "storage" / "absorb_run.json"
LEDGER_FILE = BASE_DIR / "storage" / "absorb_ledger.json"
SCHEDULE_FILE = BASE_DIR / "storage" / "absorb_schedule.json"

# Bounds that keep the run file small enough to rewrite on every song.
RUN_HISTORY_MAX = 20          # earlier runs kept beside the current one
RUN_LIST_MAX = 600            # each of captured/failed/parked/skipped/realigned
RUN_LOG_MAX = 400
SCHEDULE_OUTCOMES_MAX = 60   # the scheduler's outcome log, newest first

_lock = threading.Lock()


def _read(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Absorb: unreadable %s (%s) — using defaults", path.name, exc)
        return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── config (his) ─────────────────────────────────────────────────────────────

def load_config() -> AbsorbConfig:
    raw = _read(CONFIG_FILE)
    if not isinstance(raw, dict):
        return AbsorbConfig()
    try:
        return AbsorbConfig.model_validate(raw)
    except Exception as exc:
        logger.warning("Absorb: %s does not validate (%s) — using defaults",
                       CONFIG_FILE.name, exc)
        return AbsorbConfig()


def save_config(cfg: AbsorbConfig) -> None:
    with _lock:
        _write(CONFIG_FILE, cfg.model_dump(mode="json"))


# ── runs (churn) ─────────────────────────────────────────────────────────────
#
# The file holds the LATEST run in full and earlier runs as compact
# summaries: the latest is rewritten on every song event, so it must stay
# small, and a write must never re-parse the history. The history is read
# from disk once per path and then kept in memory.

_runs_cache: dict = {"path": None, "latest_id": None, "latest": None, "earlier": []}
# A monotonically increasing generation stamped by every `prepare_run_write`
# call (under `_lock`) and checked by `write_run_file` before it writes — the
# ordering guarantee the in-memory ledger/run record rely on, extended across
# the sync/async boundary (`save_run`'s direct callers vs. the runner's own
# off-loop persist).
_run_write_gen = 0


def compact(run: AbsorbRun) -> dict:
    """An earlier run, small: what it did and what it left for him."""
    return {
        "id": run.id, "state": run.state, "started_ms": run.started_ms,
        "ended_ms": run.ended_ms, "end_reason": run.end_reason,
        "end_detail": run.end_detail, "started_by": run.started_by,
        "window": dict(run.window or {}), "opened_ms": run.opened_ms,
        "source_playlist_uri": run.source_playlist_uri,
        "source_playlist_name": run.source_playlist_name,
        "counts": run.counts.model_dump(), "head_rate": run.head_rate.model_dump(),
        "parked": [e.model_dump() for e in run.parked],
        "realigned": [e.model_dump() for e in run.realigned],
    }


def _load_runs_file() -> None:
    if _runs_cache["path"] == RUN_FILE:
        return
    raw = _read(RUN_FILE)
    latest, earlier = None, []
    if isinstance(raw, dict):
        if isinstance(raw.get("run"), dict):
            try:
                latest = AbsorbRun.model_validate(raw["run"])
            except Exception:
                latest = None
        earlier = [e for e in (raw.get("earlier") or []) if isinstance(e, dict)]
    _runs_cache.update(path=RUN_FILE, latest=latest,
                       latest_id=latest.id if latest else None, earlier=earlier)


def prepare_run_write(run: AbsorbRun) -> tuple[int, dict]:
    """The cheap, synchronous half of a run save: bound `run` in place and
    fold it into the cache (pushing a changed previous run into history),
    returning a (generation, dict) pair ready to write. Callers that want
    the write OFF the event loop (the runner's own `_persist_run_record`)
    do this part on the loop and hand the pair to `write_run_file` via
    `to_thread` — so the only thing a worker thread ever touches is the
    file itself.

    The generation is what keeps a SYNCHRONOUS `save_run` (its only callers:
    `_refuse`, `recover_orphaned_run`) ordered against an in-flight ASYNC
    persist — the two never share a lock, so without it whichever `os.
    replace()` physically lands last would win, even if its own snapshot
    was prepared first (and is therefore stale)."""
    global _run_write_gen
    with _lock:
        _load_runs_file()
        prev = _runs_cache["latest"]
        if prev is not None and prev.id != run.id:
            _runs_cache["earlier"] = ([compact(prev)] + _runs_cache["earlier"])[:RUN_HISTORY_MAX]
        _bound(run)
        data = {"run": run.model_dump(mode="json"), "earlier": _runs_cache["earlier"]}
        _runs_cache.update(latest=run, latest_id=run.id)
        _run_write_gen += 1
        return _run_write_gen, data


def write_run_file(gen: int, data: dict) -> None:
    """The I/O-only half of a run save — safe to call from a worker thread,
    since `data` is already a plain dict with no shared mutable state. A
    `gen` that is no longer the newest PREPARED generation means a newer
    snapshot has already superseded this one; the stale write is dropped
    rather than landing over it."""
    with _lock:
        if gen != _run_write_gen:
            return
        _write(RUN_FILE, data)


def _bound(run: AbsorbRun) -> AbsorbRun:
    for name in ("captured", "failed", "parked", "skipped", "realigned",
                 "silence_checks", "yields"):
        items = getattr(run, name)
        if len(items) > RUN_LIST_MAX:
            setattr(run, name, items[-RUN_LIST_MAX:])
    if len(run.log) > RUN_LOG_MAX:
        run.log = run.log[-RUN_LOG_MAX:]
    return run


def latest_run() -> Optional[AbsorbRun]:
    """A COPY of the latest run (the runner keeps mutating its own)."""
    with _lock:
        _load_runs_file()
        latest = _runs_cache["latest"]
        return latest.model_copy(deep=True) if latest is not None else None


def earlier_runs() -> list[dict]:
    """Earlier runs, newest first, as `compact` summaries."""
    with _lock:
        _load_runs_file()
        return list(_runs_cache["earlier"])


def save_run(run: AbsorbRun) -> None:
    """Write `run` as the latest. A run with a new id pushes the previous
    latest into the compact history."""
    gen, data = prepare_run_write(run)
    write_run_file(gen, data)


# ── ledger (per song, across runs) ───────────────────────────────────────────

def load_ledger() -> AbsorbLedger:
    raw = _read(LEDGER_FILE)
    if not isinstance(raw, dict):
        return AbsorbLedger()
    try:
        return AbsorbLedger.model_validate(raw)
    except Exception as exc:
        logger.warning("Absorb: %s does not validate (%s) — starting empty",
                       LEDGER_FILE.name, exc)
        return AbsorbLedger()


def save_ledger(ledger: AbsorbLedger) -> None:
    save_ledger_dict(ledger.model_dump(mode="json"))


def save_ledger_dict(data: dict) -> None:
    """The dict-only half of a ledger save — the runner's own
    `_persist_ledger` dumps the in-memory ledger to a dict on the event
    loop (cheap) and hands this off to a worker thread, so a worker
    thread never touches the shared, still-mutating model object."""
    with _lock:
        _write(LEDGER_FILE, data)


# ── schedule (the scheduler's own memory) ────────────────────────────────────

def load_schedule() -> AbsorbSchedule:
    raw = _read(SCHEDULE_FILE)
    if not isinstance(raw, dict):
        return AbsorbSchedule()
    try:
        return AbsorbSchedule.model_validate(raw)
    except Exception as exc:
        logger.warning("Absorb: %s does not validate (%s) — starting empty",
                       SCHEDULE_FILE.name, exc)
        return AbsorbSchedule()


def save_schedule(schedule: AbsorbSchedule) -> None:
    if len(schedule.outcomes) > SCHEDULE_OUTCOMES_MAX:
        schedule.outcomes = schedule.outcomes[:SCHEDULE_OUTCOMES_MAX]
    with _lock:
        _write(SCHEDULE_FILE, schedule.model_dump(mode="json"))
