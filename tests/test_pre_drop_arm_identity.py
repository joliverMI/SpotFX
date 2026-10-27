"""WITH THE SET EMPTY, EVERY ARM WRITE IS BYTE-IDENTICAL TO TODAY — for
every effect, over his real scene list (predrop plan step 5's acceptance).

`fx.device_model.PRE_DROP_EFFECTS` ships empty: the pre-drop engine decides
whether a pre-drop plays (the colour change fades across it when it does),
but no effect is told anything about it yet. So every phase arm write
`scene_response._drive_phase` makes — charge, lull and drop, every one of
his 14 scenes, every gap and intensity in tests/pre_drop_arm_harness.py —
must equal what the code wrote before the engine existed
(tests/fixtures/pre_drop/arm_writes_golden.json, captured on origin/master
0dd0828e), byte for byte: with no pre-drop at all, and with a spike and a
vocal intro inside the showing scene's own window on every lull.
"""
from __future__ import annotations

import json

import pytest

from tests import pre_drop_arm_harness as harness

GOLDEN = json.loads(harness.GOLDEN_FILE.read_text())["writes"]
SCENES = {s["id"]: s for s in harness.his_scenes()}
CASES = harness.cases()


def _dump(writes) -> str:
    return json.dumps(writes, sort_keys=True)


def test_the_golden_covers_every_case_of_his_scene_list():
    assert len(SCENES) == 14
    assert set(GOLDEN) == {harness.case_key(*c) for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=[harness.case_key(*c) for c in CASES])
def test_arm_writes_with_no_pre_drop_are_todays(case):
    scene_id, cls, gap, intensity, energy = case
    got = harness.arm_writes(SCENES[scene_id], cls, gap, intensity, energy)
    assert _dump(got) == _dump(GOLDEN[harness.case_key(*case)])


def _candidates():
    from spectra.services.pre_drop_play import PreDropCandidate
    # both kinds, well inside every scene's default window, landing well
    # after the lull starts — the case most likely to change something
    return (PreDropCandidate(at_ms=2400, gap_ms=800, kind="spike", key="k"),
            PreDropCandidate(at_ms=1900, gap_ms=3300, kind="intro", key="k"))


LULL_CASES = [c for c in CASES if c[1] == "lull"]


@pytest.mark.parametrize("case", LULL_CASES,
                         ids=[harness.case_key(*c) for c in LULL_CASES])
def test_arm_writes_with_a_pre_drop_that_plays_are_todays_while_the_set_is_empty(case):
    from fx import device_model
    assert device_model.PRE_DROP_EFFECTS == frozenset()
    scene_id, cls, gap, intensity, energy = case
    for cand in _candidates():
        got = harness.arm_writes(SCENES[scene_id], cls, gap, intensity, energy,
                                 pre_drop=cand)
        assert _dump(got) == _dump(GOLDEN[harness.case_key(*case)]), cand.kind


def test_the_engine_does_decide_on_his_scenes_while_telling_nobody():
    """The candidate is not ignored: the verdict is reached (it is what the
    drop's colour fade follows) — only the telling is empty."""
    from spectra.models.scene import SceneV2
    from spectra.services import scene_response
    fish = next(s for s in SCENES.values() if s["name"] == "Fish")
    spike, intro = _candidates()
    scene = SceneV2(**fish)
    for cand in (spike, intro):
        verdict = scene_response.pre_drop_play.decide(scene, cand)
        assert verdict.plays, verdict
