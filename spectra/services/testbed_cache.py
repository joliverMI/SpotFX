"""Precomputed-engine-output cache for the music-analysis test bed
(data/spotfx-music-analysis-plan/report.md, Part 3's own "What it reads":
"each candidate engine's own output, computed once per song, offline,
cached to a flat file... never re-run live in the request path — several
of these engines take 80-560 seconds per song"). One JSON file per
(engine, song): `storage/spectra/testbed/analysis/<engine>/<safe_uri>.json`.

Written only by `scripts/testbed_precompute.py` (an offline CLI, never by
any request handler); read by `spectra/api/testbed.py` and
`spectra/services/testbed_engines.py`. A missing cache file means "not
computed yet for this engine/song," reported as such rather than triggering
a live run.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from spectra import config

logger = logging.getLogger(__name__)


def _safe_stem(uri: str) -> str:
    return uri.replace(":", "_").replace("/", "_")


def cache_path(engine: str, uri: str) -> Path:
    return config.TESTBED_ANALYSIS_DIR / engine / f"{_safe_stem(uri)}.json"


def has_cache(engine: str, uri: str) -> bool:
    return cache_path(engine, uri).exists()


def load(engine: str, uri: str) -> Optional[dict]:
    """{"engine", "engine_version", "computed_at", "uri", "marks": [...]}
    or None when nothing has been precomputed for this pair."""
    p = cache_path(engine, uri)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("testbed cache parse failed (%s/%s): %s", engine, uri, exc)
        return None


def save(engine: str, uri: str, engine_version: str, marks: list[dict]) -> Path:
    """`marks`: [{"time_ms": int, "kind": str, "label": str|None,
    "score": float|None}, ...] — the one shape every engine adapter in
    testbed_engines.py normalizes to."""
    path = cache_path(engine, uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine": engine,
        "engine_version": engine_version,
        "uri": uri,
        "computed_at": time.time(),
        "marks": marks,
    }
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info("testbed cache saved: %s/%s (%d marks)", engine, uri, len(marks))
    return path
