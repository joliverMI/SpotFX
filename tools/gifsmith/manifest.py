"""The GIF asset manifest: storage/gif_assets.json.

SpotFX (router, event seeder) and the toolkit both read this. Binary assets
live in LedFX's asset store; white masters are also kept in-repo under
tools/gifsmith/masters/ so recolor/re-publish never depends on LedFX.
"""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "storage" / "gif_assets.json"


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"version": 1, "assets": {}}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def upsert_asset(asset_id: str, entry: dict) -> dict:
    manifest = load_manifest()
    existing = manifest["assets"].get(asset_id, {})
    existing.update(entry)
    manifest["assets"][asset_id] = existing
    save_manifest(manifest)
    return existing
