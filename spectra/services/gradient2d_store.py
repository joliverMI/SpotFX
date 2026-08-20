"""Named 2D drift gradients — storage/spectra/gradients2d.json. Same
named-profile pattern as spectra/services/drift_profiles.py (dwell: he asked
for the identical curve-selector storage shape — "store these gradients as
settings... pick other saved one or make a new one/edit... save as new or
overwrite").
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from spectra import config
from spectra.models.gradient2d import GradientProfile

logger = logging.getLogger(__name__)


def load_all() -> dict[str, GradientProfile]:
    path = config.GRADIENT2D_FILE
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {pid: GradientProfile(**p) for pid, p in raw.items()}
        except Exception as exc:
            logger.warning("gradients2d.json parse failed: %s", exc)
    return {}


def save_all(profiles: dict[str, GradientProfile]) -> None:
    path = config.GRADIENT2D_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({pid: json.loads(p.model_dump_json())
                       for pid, p in profiles.items()}, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info("Saved %d 2D drift gradient profiles", len(profiles))
