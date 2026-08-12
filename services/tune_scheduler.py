"""
SpotFX — Training-profile tune runner + scheduler.

One shared, self-healing execution path for every tuning run (the UI's
"train now", scheduled runs, and queued runs):

  run_tune_blocking(profile_id)
    3-phase grid search (scene → flare → placement), progress + cancel via
    the module dicts below, auto-applies improved params to
    storage/training_profiles.json, and NEVER raises — failures are caught,
    logged to storage/tune_runs.log, and recorded in storage/tune_history.json
    so the UI can surface them.

Scheduling: a persisted FIFO queue (storage/tune_schedule.json). Entries run
strictly in order; an entry may be due immediately ("after" — chained behind
whatever precedes it) or at a time of day ("HH:MM" — next occurrence, today
if still ahead else tomorrow). The worker task is armed from main.py's
lifespan, so pending schedules survive restarts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import BASE_DIR

logger = logging.getLogger(__name__)

SCHEDULE_FILE = BASE_DIR / "storage" / "tune_schedule.json"
HISTORY_FILE = BASE_DIR / "storage" / "tune_history.json"
RUN_LOG_FILE = BASE_DIR / "storage" / "tune_runs.log"
HISTORY_MAX = 50

# ── Shared run state (progress banner + cancellation), keyed by profile_id ───
tune_progress: dict[str, dict] = {}
tune_cancel: dict[str, bool] = {}


def any_running() -> Optional[dict]:
    for prog in tune_progress.values():
        if prog.get("running"):
            return prog
    return None


# ── Human-readable run log (shared with scripts; tail -f friendly) ───────────

def _log_line(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    logger.info("tune: %s", msg)
    try:
        RUN_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with RUN_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        logger.exception("Failed writing %s", RUN_LOG_FILE)


# ── History ───────────────────────────────────────────────────────────────────

def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("Failed reading %s", HISTORY_FILE)
        return []


def _append_history(entry: dict) -> None:
    try:
        history = [entry] + load_history()
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(
            json.dumps(history[:HISTORY_MAX], indent=2), encoding="utf-8"
        )
    except Exception:
        logger.exception("Failed writing %s", HISTORY_FILE)


# ── Schedule queue (persisted FIFO) ───────────────────────────────────────────

def load_schedule() -> list[dict]:
    if not SCHEDULE_FILE.exists():
        return []
    try:
        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        entries = data.get("entries", []) if isinstance(data, dict) else []
        return entries if isinstance(entries, list) else []
    except Exception:
        logger.exception("Failed reading %s", SCHEDULE_FILE)
        return []


def _save_schedule(entries: list[dict]) -> None:
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(
        json.dumps({"entries": entries}, indent=2), encoding="utf-8"
    )


def add_schedule_entry(profile_id: str, profile_name: str, at: str) -> dict:
    """at: "HH:MM" (next occurrence) or "after" (chained behind the queue)."""
    entry = {
        "id": str(uuid.uuid4()),
        "profile_id": profile_id,
        "profile_name": profile_name,
        "at": at,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    entries = load_schedule()
    entries.append(entry)
    _save_schedule(entries)
    _log_line(f"Scheduled tune for '{profile_name}' ({'right after previous' if at == 'after' else at})")
    return entry


def remove_schedule_entry(entry_id: str) -> bool:
    entries = load_schedule()
    kept = [e for e in entries if e.get("id") != entry_id]
    if len(kept) == len(entries):
        return False
    _save_schedule(kept)
    return True


def _next_occurrence(hhmm: str) -> Optional[datetime]:
    try:
        hour, minute = (int(x) for x in hhmm.split(":", 1))
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
    except Exception:
        return None


def entry_due_at(entry: dict) -> Optional[str]:
    """ISO timestamp when a timed entry will fire (None for 'after' entries)."""
    at = entry.get("at", "")
    if at == "after":
        return None
    nxt = _next_occurrence(at)
    return nxt.isoformat(timespec="seconds") if nxt else None


# ── Tune runner (blocking; call via executor) ─────────────────────────────────

def run_tune_blocking(profile_id: str, trigger: str = "immediate") -> dict:
    """Full 3-phase grid search for one profile. Self-healing: never raises.
    Progress → tune_progress[profile_id]; cancel via tune_cancel[profile_id].
    Auto-applies improved params and records the run in tune_history.json."""
    started_at = datetime.now().isoformat(timespec="seconds")
    profile_name = "?"
    try:
        result = _run_tune_inner(profile_id)
        profile_name = result.pop("_profile_name", "?")
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {exc}", "improved": False,
                  "traceback": traceback.format_exc()}
    finally:
        tune_progress[profile_id] = {"running": False}
        tune_cancel.pop(profile_id, None)

    status = ("cancelled" if result.get("cancelled")
              else "failed" if result.get("error")
              else "completed")
    _append_history({
        "profile_id": profile_id,
        "profile_name": profile_name,
        "trigger": trigger,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "error": result.get("error"),
        "improved": bool(result.get("improved")),
        "baseline_f1": result.get("baseline_f1"),
        "tuned_f1": result.get("tuned_f1"),
        "best_params": result.get("best_params") or {},
    })
    if status == "failed":
        _log_line(f"'{profile_name}' tune FAILED: {result.get('error')}")
        if result.get("traceback"):
            _log_line(result["traceback"])
    elif status == "cancelled":
        _log_line(f"'{profile_name}' tune cancelled")
    else:
        _log_line(
            f"'{profile_name}' tune completed: F1 {result.get('baseline_f1')} → "
            f"{result.get('tuned_f1')} ({'applied ' + str(len(result.get('best_params') or {})) + ' params' if result.get('improved') else 'no improvement'})"
        )
    return result


def _run_tune_inner(profile_id: str) -> dict:
    from services.training_profile_manager import TrainingProfile, TRAINING_PROFILES_FILE

    sys.path.insert(0, str(TRAINING_PROFILES_FILE.parent.parent))
    from scripts.tune_triggers import _grid_combos, \
        _apply_overrides, preload_songs, score_fast, \
        SCENE_GRID, FLARE_GRID, PLACEMENT_GRID
    from scripts.score_triggers import (
        build_role_map, DEFAULT_SCORE_WEIGHTS, match_triggers,
        SongScore, SCENE_CATEGORIES, FLARE_CATEGORIES,
    )

    raw_profiles = (json.loads(TRAINING_PROFILES_FILE.read_text(encoding="utf-8"))
                    if TRAINING_PROFILES_FILE.exists() else {})
    if profile_id not in raw_profiles:
        return {"error": f"Training profile {profile_id} not found", "improved": False}
    tp = TrainingProfile(**raw_profiles[profile_id])

    tune_cancel[profile_id] = False
    tune_progress[profile_id] = {
        "running": True, "phase": "loading", "pct": 0,
        "profile_name": tp.name, "profile_id": profile_id,
    }

    def _cancelled() -> bool:
        return bool(tune_cancel.get(profile_id))

    t_start = time.monotonic()

    role_map = build_role_map(tp)
    weights = DEFAULT_SCORE_WEIGHTS
    all_uris = list(set(tp.training_uris + tp.embedded_only_uris))
    songs = preload_songs(all_uris)
    if not songs:
        return {"error": "No usable training songs", "improved": False,
                "_profile_name": tp.name}

    song_list = [{"title": s["title"], "artist": s["artist"], "uri": s["uri"]} for s in songs]

    beat_ms = (60_000 / songs[0]["analysis"].tempo_bpm) if songs[0]["analysis"].tempo_bpm else 500
    tolerance_ms = int(2 * beat_ms)

    baseline_f1 = score_fast(tp, songs, role_map, tolerance_ms, weights)

    scene_combos = _grid_combos(SCENE_GRID)
    flare_combos = _grid_combos(FLARE_GRID)
    placement_combos = _grid_combos(PLACEMENT_GRID)
    total_combos = len(scene_combos) + len(flare_combos) + len(placement_combos)

    def _phase(name: str, combos: list[dict], base_overrides: dict,
               base_f1: float, done_before: int) -> tuple[dict, float, bool]:
        """Grid-search one phase. Returns (best_overrides, best_f1, cancelled)."""
        best: dict = {}
        best_f1 = base_f1
        tune_progress[profile_id].update(phase=name, pct=round(done_before / total_combos * 100, 1))
        for i, overrides in enumerate(combos):
            if _cancelled():
                return best, best_f1, True
            trial = _apply_overrides(tp, {**base_overrides, **overrides})
            f1 = score_fast(trial, songs, role_map, tolerance_ms, weights)
            if f1 > best_f1:
                best_f1 = f1
                best = overrides.copy()
            if (i + 1) % 50 == 0:
                time.sleep(0)  # release GIL so the event loop can serve requests
            if (i + 1) % 100 == 0 or i == len(combos) - 1:
                tune_progress[profile_id].update(
                    pct=round((done_before + i + 1) / total_combos * 100, 1),
                    phase=name,
                    elapsed_s=round(time.monotonic() - t_start, 1),
                )
        return best, best_f1, False

    best_scene, best_f1, cancelled = _phase("scene", scene_combos, {}, baseline_f1, 0)
    if cancelled:
        return {"improved": False, "cancelled": True, "_profile_name": tp.name}

    scene_f1 = score_fast(_apply_overrides(tp, best_scene), songs, role_map, tolerance_ms, weights) \
        if best_scene else best_f1
    best_flare, flare_f1, cancelled = _phase(
        "flare", flare_combos, best_scene, scene_f1, len(scene_combos))
    if cancelled:
        return {"improved": False, "cancelled": True, "_profile_name": tp.name}

    sf_overrides = {**best_scene, **best_flare}
    sf_f1 = score_fast(_apply_overrides(tp, sf_overrides), songs, role_map, tolerance_ms, weights) \
        if best_flare else flare_f1
    best_placement, final_f1, cancelled = _phase(
        "placement", placement_combos, sf_overrides, sf_f1,
        len(scene_combos) + len(flare_combos))
    if cancelled:
        return {"improved": False, "cancelled": True, "_profile_name": tp.name}

    all_best = {**best_scene, **best_flare, **best_placement}
    duration_s = round(time.monotonic() - t_start, 1)

    # Score breakdown: run final params on each song for detailed results
    final_tp = _apply_overrides(tp, all_best) if all_best else tp
    score_breakdown: dict = {}
    total_scene_triggers = 0
    total_flare_triggers = 0
    from services.embedded_trigger_service import suggest_triggers
    for song in songs:
        available = set(role_map.keys())
        try:
            generated = suggest_triggers(
                target_uri=song["uri"],
                all_training_uris=[],
                available_event_ids=available,
                training_profile=final_tp,
                _cached_analysis=song["analysis"],
            )
            categories = match_triggers(song["human"], generated, role_map, tolerance_ms)
        except Exception:
            logger.exception("Breakdown scoring failed for %s — skipping", song["uri"])
            continue
        for cat, cs in categories.items():
            if cat in SCENE_CATEGORIES:
                total_scene_triggers += cs.gen_count
            elif cat in FLARE_CATEGORIES:
                total_flare_triggers += cs.gen_count
            agg = score_breakdown.setdefault(cat, {
                "tp": 0.0, "fp": 0, "fn": 0.0,
                "human_count": 0, "gen_count": 0, "match_count": 0,
                "intensity_err_sum": 0.0, "intensity_pairs": 0,
            })
            agg["tp"] += cs.tp
            agg["fp"] += cs.fp
            agg["fn"] += cs.fn
            agg["human_count"] += cs.human_count
            agg["gen_count"] += cs.gen_count
            agg["match_count"] += cs.match_count
            agg["intensity_err_sum"] += cs.intensity_err_sum
            agg["intensity_pairs"] += cs.intensity_pairs

    for cat, agg in score_breakdown.items():
        p = agg["tp"] / (agg["tp"] + agg["fp"]) if (agg["tp"] + agg["fp"]) > 0 else 0.0
        r = agg["tp"] / (agg["tp"] + agg["fn"]) if (agg["tp"] + agg["fn"]) > 0 else 0.0
        agg["precision"] = round(p, 3)
        agg["recall"] = round(r, 3)
        agg["f1"] = round(2 * p * r / (p + r) if (p + r) > 0 else 0.0, 3)
        agg["weight"] = weights.get(cat, 1.0)
        pairs = agg.pop("intensity_pairs")
        err_sum = agg.pop("intensity_err_sum")
        agg["intensity_mae"] = round(err_sum / pairs, 3) if pairs > 0 else None

    improved = bool(all_best) and final_f1 > baseline_f1

    # Auto-apply improved params (shared by immediate + scheduled runs).
    # Re-read the file to avoid clobbering edits made while tuning ran.
    if improved:
        raw_now = json.loads(TRAINING_PROFILES_FILE.read_text(encoding="utf-8"))
        if profile_id in raw_now:
            raw_now[profile_id].update(all_best)
            TRAINING_PROFILES_FILE.write_text(json.dumps(raw_now, indent=2), encoding="utf-8")

    return {
        "baseline_f1": round(baseline_f1, 3),
        "tuned_f1": round(final_f1, 3),
        "improvement_pct": round((final_f1 - baseline_f1) / max(baseline_f1, 0.001) * 100, 1),
        "best_params": all_best,
        "songs_used": len(songs),
        "song_list": song_list,
        "improved": improved,
        "duration_s": duration_s,
        "score_breakdown": score_breakdown,
        "scene_triggers": total_scene_triggers,
        "flare_triggers": total_flare_triggers,
        "total_triggers": total_scene_triggers + total_flare_triggers,
        "timestamp": time.time(),
        "_profile_name": tp.name,
    }


# ── Scheduler worker (armed from main.py lifespan) ────────────────────────────

async def worker_loop() -> None:
    """Process the schedule queue strictly in order. Head entry: 'after' runs
    as soon as nothing else is running; 'HH:MM' waits for its next occurrence.
    Survives restarts (queue is on disk). Never dies on a bad entry."""
    _log_line("Tune scheduler armed" + (
        f" — {len(load_schedule())} pending entr(y/ies)" if load_schedule() else ""))
    loop = asyncio.get_running_loop()
    while True:
        try:
            entries = load_schedule()
            if not entries:
                await asyncio.sleep(10)
                continue

            head = entries[0]
            at = head.get("at", "after")
            if at != "after":
                target = _next_occurrence(at)
                if target is None:
                    _log_line(f"Dropping schedule entry with bad time {at!r}: {head}")
                    remove_schedule_entry(head["id"])
                    continue
                wait_s = (target - datetime.now()).total_seconds()
                if wait_s > 0:
                    # Sleep in short slices so newly-added/removed entries and
                    # shutdown are picked up promptly.
                    await asyncio.sleep(min(wait_s, 20))
                    continue

            # Due — but let any in-flight run (immediate or previous) finish first
            if any_running():
                await asyncio.sleep(10)
                continue

            remove_schedule_entry(head["id"])
            _log_line(f"Scheduled tune starting: '{head.get('profile_name', '?')}'")
            await loop.run_in_executor(
                None, run_tune_blocking, head["profile_id"], "scheduled")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Tune scheduler worker error — continuing")
            await asyncio.sleep(30)
