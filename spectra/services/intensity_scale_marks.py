"""SPECTRA — per-track manual intensity marks (2026-08-15, the Admiral's
ruling on the headroom-reserve gate): the AUTO ceiling
(intensity_scale.HEADROOM_RESERVE * intensity_scale.SCALE_MAX = 0.75)
STANDS for every song the AUTO path resolves — nothing automatic ever
exceeds it. A manual mark is the ONE way past it, his own words: "he
marks the track; automatic never does." Restores the control SpotFX's own
per-song manual slider gave him (SongProfile.intensity_scale, source=
"user", never touched by the auto backfill) — without a way to open it,
the 0.6 headroom reserve is a CAP with no release, not a GATE.

intensity_scale.song_scaling_factor() checks get_mark() FIRST, before
falling through to the AUTO genre+bass computation — a marked song's
factor is exactly what he set, clamped to [MANUAL_MIN, MANUAL_MAX] (0.0-
2.0, the SAME ceiling SpotFX's own manual slider had —
services/trigger_engine.py's _intensity_scale_now: "max(0.0, min(2.0,
float(prof.intensity_scale)))"), NEVER re-clamped down to the AUTO range
[intensity_scale.SCALE_MIN, intensity_scale.SCALE_MAX]. Clearing a mark
(clear_mark) reverts the song to AUTO — un-capped-by-a-mark, but back
under the 0.75 ceiling.

Storage: storage/spectra/intensity_scale_marks.json, {uri: {factor,
set_at}}, same atomic tmp+replace discipline as room_controls.py. No
bound on the number of marks — this is a small, owner-curated set (he
marks tracks he actually cares about), not an unbounded log like
fire_history's show log.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Optional

from spectra import config

MANUAL_MIN = 0.0
MANUAL_MAX = 2.0   # matches SpotFX's own manual per-song slider ceiling


def _load() -> dict[str, dict]:
    path = config.INTENSITY_SCALE_MARKS_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(marks: dict[str, dict]) -> None:
    path = config.INTENSITY_SCALE_MARKS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(marks, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_all() -> dict[str, dict]:
    """Every marked track — observability only (no list endpoint yet;
    callers needing one can build it on this)."""
    return _load()


def get_mark(spotify_uri: str) -> Optional[float]:
    entry = _load().get(spotify_uri)
    if entry is None:
        return None
    try:
        return float(entry["factor"])
    except (KeyError, TypeError, ValueError):
        return None


def set_mark(spotify_uri: str, factor: float) -> float:
    """Clamp and persist a manual factor for a song. Returns the clamped
    value actually stored (the caller should trust this, not its own
    unclamped input)."""
    clamped = max(MANUAL_MIN, min(MANUAL_MAX, float(factor)))
    marks = _load()
    marks[spotify_uri] = {"factor": clamped, "set_at": time.time()}
    _save(marks)
    return clamped


def clear_mark(spotify_uri: str) -> bool:
    """True if a mark existed and was removed; False if there was none —
    lets a caller tell "cleared" from "already unmarked"."""
    marks = _load()
    if spotify_uri not in marks:
        return False
    del marks[spotify_uri]
    _save(marks)
    return True
