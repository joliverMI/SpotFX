"""Named drift profiles — storage/spectra/drift_profiles.json.

The decision-4 pattern applied to drift: scenes declare mechanisms by NAME
("put Slow Wander on Orbits"); one profile edit retunes every scene using
it. Inline one-off specs live inside the scene (models/scene.DriftRef).
Adjusted by telling the agent (PUT /spectra/api/drift-profiles); the one
graphical piece is a follow profile's intensity→value curve.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from pydantic import BaseModel, Field
import uuid

from spectra import config
from spectra.models.scene import DriftSpec

logger = logging.getLogger(__name__)


class DriftProfile(BaseModel):
    id:   str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    spec: DriftSpec


def load_all() -> dict[str, DriftProfile]:
    path = config.DRIFT_PROFILES_FILE
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {pid: DriftProfile(**p) for pid, p in raw.items()}
        except Exception as exc:
            logger.warning("drift_profiles.json parse failed: %s", exc)
    return {}


def save_all(profiles: dict[str, DriftProfile]) -> None:
    path = config.DRIFT_PROFILES_FILE
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
    logger.info("Saved %d drift profiles", len(profiles))
