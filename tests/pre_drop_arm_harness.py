"""The phase ARM WRITES a scene's lull/charge/drop makes, over his real scene
list — the instrument behind tests/test_pre_drop_engine.py's "with the set
empty, every arm write is byte-identical to today for every effect"
(predrop plan step 5's acceptance).

`arm_writes` drives the production ResponseEngine._drive_phase — the one
place a phase is written — against a RecordingExecutor, for one of his
scenes (one virtual per device entry, his own effect types), and returns
every executor write it made, in order, as plain JSON-able dicts. Nothing
here reads storage: room controls, the energy, the house layer, the
hand-off resolver and every profile read are pinned, so the same call
gives the same bytes on any machine.

`tests/fixtures/pre_drop/arm_writes_golden.json` was captured by running
`python tests/pre_drop_arm_harness.py` against the code as it was BEFORE
the pre-drop engine existed (origin/master 0dd0828e): it is "today", frozen.
The test replays every case on the current code — with no pre-drop, and
with a spike and a vocal intro inside the scene's own window — and compares
byte for byte.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures" / "pre_drop"
SCENES_FILE = FIXTURES / "his_scenes.json"
GOLDEN_FILE = FIXTURES / "arm_writes_golden.json"

CLASSES = ("charge", "lull", "drop")
GAPS = {"charge": (None, 900, 4000, 20000),
        "lull": (None, 900, 3200, 6040, 20000),
        "drop": (None,)}
INTENSITIES = (0.3, 0.8)
ENERGIES = (None, 0.85)


def his_scenes() -> list[dict]:
    return json.loads(SCENES_FILE.read_text())["scenes"]


def _virtuals(scene) -> list[dict]:
    out = []
    for i, dev in enumerate(scene.devices):
        out.append({"virtual_id": f"{dev.target or 'all'}-{i}",
                    "effect_type": dev.effect_type, "config": {},
                    "entry_id": dev.id, "color_mode": "set"})
    return out


async def _drive(scene_dict: dict, cls: str, gap_ms: Optional[int],
                 intensity: float, energy: Optional[float],
                 pre_drop: Any = None) -> list[dict]:
    from spectra.models.scene import SceneV2
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services import scene_response
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor

    scene = SceneV2(**scene_dict)
    clock = [100.0]
    room = [cj.RoomColorState()]
    controls = rc.RoomControlState()
    ex = RecordingExecutor(clock=lambda: clock[0],
                           room_controls_load=lambda: controls)
    conductor = DriftConductor(
        executor=ex, clock=lambda: clock[0], drift_profiles=lambda: {},
        curve_profiles=lambda: {}, room_load=lambda: room[0],
        room_save=lambda st: room.__setitem__(0, st), set_cards=lambda: [],
        gradient_profiles=lambda: {}, room_controls=lambda: controls,
        rng=Random(3))
    responder = scene_response.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(5),
        clock=lambda: clock[0], curve_profiles=lambda: {},
        room_load=lambda: room[0], room_save=lambda st: room.__setitem__(0, st),
        room_controls=lambda: controls, room_energy=lambda: energy)
    responder.lull_handoff_resolver = scene_response.default_lull_handoff
    conductor.on_scene_fire(scene, _virtuals(scene))
    ex.writes.clear()
    real_house = scene_response._house_owns_the_look
    scene_response._house_owns_the_look = lambda: None
    try:
        if pre_drop is None:
            await responder._drive_phase(cls, gap_ms, intensity)
        else:
            await responder._drive_phase(cls, gap_ms, intensity,
                                         pre_drop=pre_drop)
    finally:
        scene_response._house_owns_the_look = real_house
    return [{"kind": w["kind"], "virtual_id": w["virtual_id"],
             "effect_type": w["effect_type"], "params": w["params"],
             "duration_ms": w["duration_ms"]} for w in ex.writes]


def arm_writes(scene_dict: dict, cls: str, gap_ms: Optional[int],
               intensity: float, energy: Optional[float],
               pre_drop: Any = None) -> list[dict]:
    return asyncio.run(_drive(scene_dict, cls, gap_ms, intensity, energy,
                              pre_drop))


def cases() -> list[tuple[str, str, Optional[int], float, Optional[float]]]:
    out = []
    for scene in his_scenes():
        for cls in CLASSES:
            for gap in GAPS[cls]:
                for intensity in INTENSITIES:
                    for energy in ENERGIES:
                        out.append((scene["id"], cls, gap, intensity, energy))
    return out


def case_key(scene_id: str, cls: str, gap: Optional[int], intensity: float,
             energy: Optional[float]) -> str:
    return f"{scene_id}|{cls}|{gap}|{intensity}|{energy}"


def capture() -> dict:
    by_id = {s["id"]: s for s in his_scenes()}
    return {case_key(*c): arm_writes(by_id[c[0]], c[1], c[2], c[3], c[4])
            for c in cases()}


if __name__ == "__main__":
    golden = capture()
    GOLDEN_FILE.write_text(json.dumps(
        {"_captured_on": "origin/master 0dd0828e (before the pre-drop engine)",
         "writes": golden}, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"{len(golden)} cases -> {GOLDEN_FILE}")
