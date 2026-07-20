"""
SpotFX — Per-virtual per-effect last-known config store.

When a Morph Step switches a virtual to a new effect type, the starter config
for the new effect would otherwise come from `effect_params.json` defaults
(generic, taste-neutral). This module remembers the user's most recent state
for each (virtual_id, effect_type) pair so switching back resumes whatever
the user had dialed in last time.

Storage:
  /home/javi/SpotFX/storage/morph_effect_state.json
  {
    "<virtual_id>": {
      "<effect_type>": { "<param>": <value>, ... },
      ...
    },
    ...
  }

Writes happen at two points in `_execute_morph_step`:
  1. Just before a switch, snapshot the pre-switch (effect, config) so the
     state being replaced is preserved.
  2. At end of action, snapshot the post-action (effect, config) for every
     virtual touched.

Reads happen in `morph_compiler.compile_target` when an effect-switch target
needs a starter config — preferred over `effect_params.json` defaults.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_STORE_FILE = Path(__file__).parent.parent / "storage" / "morph_effect_state.json"
_STATE: dict[str, dict[str, dict]] = {}
_LOCK = threading.Lock()  # protects in-memory dict + disk writes


def load() -> None:
    """Load morph_effect_state.json into memory. Called once at startup."""
    global _STATE
    if not _STORE_FILE.exists():
        _STATE = {}
        return
    try:
        _STATE = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        if not isinstance(_STATE, dict):
            logger.warning("morph_effect_state.json has unexpected shape; resetting in-memory store")
            _STATE = {}
    except Exception as exc:
        logger.warning("Could not parse morph_effect_state.json (%r) — starting fresh", exc)
        _STATE = {}


def get(virtual_id: str, effect_type: str) -> dict | None:
    """Return a copy of the last-known config for (virtual_id, effect_type),
    or None if no entry has been recorded."""
    entry = _STATE.get(virtual_id, {}).get(effect_type)
    return dict(entry) if isinstance(entry, dict) else None


def all_for_virtual(virtual_id: str) -> dict[str, dict]:
    """Return {effect_type: config} snapshots recorded for a virtual (copies)."""
    entries = _STATE.get(virtual_id, {})
    return {
        etype: dict(cfg)
        for etype, cfg in entries.items()
        if isinstance(cfg, dict)
    }


def save(virtual_id: str, effect_type: str, config: dict) -> None:
    """Persist one (virtual_id, effect_type) → config snapshot."""
    save_many([(virtual_id, effect_type, config)])


def save_many(updates: list[tuple[str, str, dict]]) -> None:
    """Persist a batch of snapshots in one disk write."""
    if not updates:
        return
    with _LOCK:
        for vid, etype, cfg in updates:
            if not vid or not etype or not isinstance(cfg, dict):
                continue
            _STATE.setdefault(vid, {})[etype] = dict(cfg)
        try:
            _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = _STORE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(_STATE, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(_STORE_FILE)
        except Exception as exc:
            logger.warning("Failed to persist morph_effect_state: %r", exc)
