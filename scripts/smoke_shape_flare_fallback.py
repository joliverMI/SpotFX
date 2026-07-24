"""
Offline smoke test for Shape Flare → Color Flare fallback.

Verifies that when a Scene Update's Shape lane (2) has no alternatives, firing a
`shape_flare` runs the Color lane (3) instead — and that a non-empty Shape lane
still fires Shape as before. No live LedFX backend needed: device execution
(`_execute_action`) and the event lookup (`get_event`) are stubbed.

USAGE
  .venv/bin/python scripts/smoke_shape_flare_fallback.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.music_event import MusicEvent, MorphLane, LedFxSceneAction  # noqa: E402
import services.trigger_engine as te                                    # noqa: E402


def _scene(shape_alts, color_alts) -> MusicEvent:
    return MusicEvent(
        id="scene-1", name="Test Scene", event_type="scene_update",
        morph_lanes=[
            MorphLane(name="First",  alternatives=[LedFxSceneAction(scene_id="first")]),
            MorphLane(name="Rest",   alternatives=[LedFxSceneAction(scene_id="rest")]),
            MorphLane(name="Shape",  alternatives=shape_alts),
            MorphLane(name="Color",  alternatives=color_alts),
        ],
    )


async def _run_case(label, scene, expect_fired_scene_ids) -> bool:
    fired: list[str] = []

    async def _fake_execute_action(action, labels, skip_event_ids=None, **kwargs):
        fired.append(getattr(action, "scene_id", "?"))

    engine = te.TriggerEngine()
    engine._execute_action = _fake_execute_action          # stub device push
    engine._last_scene_update_id = scene.id

    orig_get_event = te.get_event
    te.get_event = lambda eid: scene if eid == scene.id else orig_get_event(eid)
    try:
        flare = MusicEvent(name="Shape Flare", event_type="shape_flare")
        summary = await engine._execute_scene_event(flare, labels=[])
    finally:
        te.get_event = orig_get_event

    ok = fired == expect_fired_scene_ids
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print(f"        fired={fired}  expected={expect_fired_scene_ids}")
    print(f"        summary={summary!r}")
    return ok


async def main() -> None:
    color = [LedFxSceneAction(scene_id="color")]
    shape = [LedFxSceneAction(scene_id="shape")]

    results = [
        await _run_case(
            "empty Shape lane → falls back to Color",
            _scene(shape_alts=[], color_alts=color),
            ["color"],
        ),
        await _run_case(
            "non-empty Shape lane → fires Shape (no fallback)",
            _scene(shape_alts=shape, color_alts=color),
            ["shape"],
        ),
        await _run_case(
            "empty Shape AND empty Color → nothing fires",
            _scene(shape_alts=[], color_alts=[]),
            [],
        ),
    ]
    print()
    if all(results):
        print("ALL PASS")
    else:
        print("FAILURES present")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
