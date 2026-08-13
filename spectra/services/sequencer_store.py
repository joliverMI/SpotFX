"""SPECTRA sequencer storage: storage/spectra/sequencer.json.

Same committed schema as the spot-effects original (named curve profiles +
config with the three selectors and the dark switch); seeded from the live
storage/sequencer.json by scripts/seed_spectra_from_v2.py. Writes are atomic.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from spectra import config
from spectra.models.sequencer import CurveProfile, SequencerConfig

logger = logging.getLogger(__name__)


def _load_raw() -> dict:
    if config.SEQUENCER_FILE.exists():
        try:
            return json.loads(config.SEQUENCER_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("spectra sequencer.json parse failed: %s", exc)
    return {}


def _save_raw(data: dict) -> None:
    path = config.SEQUENCER_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
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


def save_config(config_obj: SequencerConfig) -> None:
    raw = _load_raw()
    raw["config"] = json.loads(config_obj.model_dump_json())
    _save_raw(raw)
    logger.info("Saved sequencer config (%d entries, %d affinity edges)",
                len(config_obj.entries), len(config_obj.affinity))
