"""
Live smoke test for Morph Step (Phase 2).

Fires a single MorphStepAction against the live LedFX backend without
spinning up the full SpotFX server. Use to verify Phase 2 works on real
hardware before continuing.

USAGE
  .venv/bin/python scripts/smoke_morph_step.py                          # built-in example
  .venv/bin/python scripts/smoke_morph_step.py path/to/my_step.json     # custom payload

Built-in example: bump every Strips virtual to brightness 0.3 with a
500 ms ramp. Edit EXAMPLE below or pass your own JSON.

WHAT IT DOES
  1. Loads effect_params (so the aspect compiler can resolve params).
  2. Polls the live LedFX virtual state once and seeds the local cache.
  3. Builds a MorphStepAction from the payload.
  4. Calls TriggerEngine._execute_morph_step with await_ramps=True so
     all ramps complete before the script exits.
  5. Polls the post-fire virtual state and prints a before/after summary
     so you can see what changed without watching the lights (or, with
     the lights on, confirm the visible change matches the report).

CAVEAT
  SpotFX shouldn't be running and actively writing to the same LedFX
  while this script runs — they'd be competing publishers. Easiest:
  systemctl --user stop spotfx (or just don't start it). Music can be
  playing, the script doesn't care.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Bootstrap sys.path so this script runs from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params

# Load the param registry before any morph imports touch it
effect_params.load()

from api import ledfx_client                              # noqa: E402
from models.state import state                            # noqa: E402
from models.music_event import MorphStepAction            # noqa: E402
from services.trigger_engine import TriggerEngine         # noqa: E402


EXAMPLE: dict = {
    "type": "morph_step",
    "ramp_ms": 500,
    "targets": [
        {
            "scope": {"categories": ["Strips"]},
            "aspect": "brightness",
            "absolute_value": {"number": 0.3},
        },
    ],
}


def _summary(vid: str, data: dict) -> str:
    """One-line summary of a virtual: effect type + every aspect-tagged param's
    current value. Gradient strings are truncated so the line stays readable."""
    eff = data.get("effect") or {}
    cfg = eff.get("config") or {}
    etype = eff.get("type", "?")

    # Pull aspect-tagged params from the effect schema so the display tracks
    # whatever the Morph Step system can actually change.
    schema = effect_params._CONFIG.get("effects", {}).get(etype, {}).get("params", {})
    aspect_params = [name for name, meta in schema.items() if meta.get("aspect")]

    def _fmt(name: str) -> str:
        v = cfg.get(name)
        if isinstance(v, str) and len(v) > 40:
            v = v[:37] + "…"
        return f"{name}={v}"

    body = ", ".join(_fmt(k) for k in aspect_params if k in cfg) if aspect_params else "(no aspect params)"
    return f"  {vid:24s}  type={etype:12s}  {body}"


async def main() -> None:
    if len(sys.argv) > 1:
        payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        src = sys.argv[1]
    else:
        payload = EXAMPLE
        src = "(built-in example)"

    print(f"Payload from {src}:")
    print(json.dumps(payload, indent=2))

    action = MorphStepAction.model_validate(payload)

    # Seed cache from live LedFX state.
    # LedFX's /api/virtuals returns {"status": ..., "virtuals": {vid: record, ...}, "paused": ...}
    # — the per-virtual records live under the "virtuals" sub-key, not at the top level.
    print("\nPolling live LedFX state…")
    live = await ledfx_client.get_all_virtuals() or {}
    virtuals_only = live.get("virtuals") or {}
    imported = set(effect_params.get_all_virtual_ids())
    # Keep only virtuals that SpotFX has imported into a device category AND
    # that currently have an active effect we can patch.
    actionable = {k: v for k, v in virtuals_only.items()
                  if k in imported
                  and isinstance(v, dict)
                  and (v.get("effect") or {}).get("type")}
    state.ledfx_virtual_cache.update(actionable)
    print(f"Cached {len(actionable)} imported+active virtuals "
          f"(LedFX exposes {len(virtuals_only)}, SpotFX has imported {len(imported)})\n")
    print("BEFORE:")
    for vid, data in sorted(actionable.items()):
        print(_summary(vid, data))

    # Fire
    print("\nFiring Morph Step (await_ramps=True)…")
    engine = TriggerEngine()
    await engine._execute_morph_step(action, await_ramps=True)

    # Settle and re-poll — show the same imported set so the diff is direct
    await asyncio.sleep(0.3)
    live_after = (await ledfx_client.get_all_virtuals() or {}).get("virtuals") or {}
    print("\nAFTER:")
    for vid in sorted(actionable):
        data = live_after.get(vid)
        if isinstance(data, dict):
            print(_summary(vid, data))


if __name__ == "__main__":
    asyncio.run(main())
