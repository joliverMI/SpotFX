"""Sequencer runtime storage: storage/sequencer.json (gitignored).

COMMITTED schema (decision 4 — named curve profiles + inline escape hatch):

    { "curve_profiles": { "<profile_id>": CurveProfile },
      "config":         SequencerConfig }   # models/sequencer.py

config carries the scene selector (entries/affinity/dwell), the flare
selector (flare_entries), the colour-set selector (color_set_entries +
wheel_travel_curve — decision 3, wired last), and the dark switch (enabled,
default off). Writes are atomic (tmp + os.replace in the same directory).
Consumers: services/scene_sequencer.py (at change moments only) and the
agent-adjustment endpoints (routers/sequencer_router.py). Seeder:
scripts/seed_sequencer_from_legacy.py.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from config import PROFILES_DIR
from models.sequencer import CurveProfile, SequencerConfig

logger = logging.getLogger(__name__)

SEQUENCER_FILE = PROFILES_DIR.parent / "sequencer.json"


def _load_raw() -> dict:
    if SEQUENCER_FILE.exists():
        try:
            return json.loads(SEQUENCER_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("sequencer.json parse failed: %s", exc)
    return {}


def _save_raw(data: dict) -> None:
    SEQUENCER_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SEQUENCER_FILE.parent,
                               prefix=SEQUENCER_FILE.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, SEQUENCER_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_curves() -> dict[str, CurveProfile]:
    return {pid: CurveProfile(**p)
            for pid, p in _load_raw().get("curve_profiles", {}).items()}


def save_curves(curves: dict[str, CurveProfile]) -> None:
    raw = _load_raw()
    raw["curve_profiles"] = {
        pid: json.loads(p.model_dump_json()) for pid, p in curves.items()}
    _save_raw(raw)
    logger.info("Saved %d sequencer curve profiles", len(curves))


def load_config() -> SequencerConfig:
    return SequencerConfig(**_load_raw().get("config", {}))


def save_config(config: SequencerConfig) -> None:
    raw = _load_raw()
    raw["config"] = json.loads(config.model_dump_json())
    _save_raw(raw)
    logger.info("Saved sequencer config (%d entries, %d affinity edges)",
                len(config.entries), len(config.affinity))
