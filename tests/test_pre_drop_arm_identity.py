"""ONLY THE MEMBERS' LULL ARMS CHANGE — every other arm write is
byte-identical to before the pre-drop engine existed, over his real scene
list (predrop plan steps 5 and 6).

Every phase arm write `scene_response._drive_phase` makes — charge, lull
and drop, every one of his 14 scenes, every gap and intensity in
tests/pre_drop_arm_harness.py — is compared with what the code wrote before
the engine existed (tests/fixtures/pre_drop/arm_writes_golden.json,
captured on origin/master 0dd0828e). Since steps 6-7 `fx.device_model.
PRE_DROP_EFFECTS` holds Fireworks, Pulse, Orbits and Black Hole, so:

- with no pre-drop, a member's lull arm is today's plus the four told keys
  at NOT_TOLD (and a zero breath for a member that is no breath-hold effect:
  Fireworks) — fx/effects/pre_drop.py's rule 2, so a pre-drop told for one
  lull never survives into the next — and every other write is today's,
  byte for byte;
- with a pre-drop that plays, every non-member write is still today's, and
  a member's lull arm carries the told kind, moment, gap and its own
  resolved look, its breath ending exactly on the pre-drop.
"""
from __future__ import annotations

import copy
import json

import pytest

from fx import device_model
from fx.effects import phase_grammar, pre_drop
from tests import pre_drop_arm_harness as harness

GOLDEN = json.loads(harness.GOLDEN_FILE.read_text())["writes"]
SCENES = {s["id"]: s for s in harness.his_scenes()}
CASES = harness.cases()
LULL_CASES = [c for c in CASES if c[1] == "lull"]
ZERO_BREATH = {phase_grammar.BREATH_AT_KEY: 0.0, phase_grammar.BREATH_KEY: 0.0}
# the look each member's "auto" plays (his entries all choose "auto")
AUTO_LOOK = {("fireworks", "spike"): "rockets", ("fireworks", "intro"): "rockets",
             ("pulse", "spike"): "burst", ("pulse", "intro"): "swell",
             ("orbits", "spike"): "jitter", ("orbits", "intro"): "jitter",
             ("blackhole", "spike"): "ring", ("blackhole", "intro"): "ring"}


def _dump(writes) -> str:
    return json.dumps(writes, sort_keys=True)


def _member(w) -> bool:
    return w["effect_type"] in device_model.PRE_DROP_EFFECTS


def _untold(golden_writes):
    """The golden writes as the engine now writes them when no pre-drop
    plays: a member's lull arm also carries the told keys at NOT_TOLD (and
    a zero breath when it is no breath-hold effect); nothing else moves."""
    out = copy.deepcopy(golden_writes)
    for w in out:
        if _member(w) and w["params"].get("phase") == "lull":
            w["params"].update(pre_drop.NOT_TOLD)
            if w["effect_type"] not in device_model.BREATH_HOLD_EFFECTS:
                w["params"].update(ZERO_BREATH)
    return out


def test_the_members_are_fireworks_pulse_orbits_and_black_hole():
    assert device_model.PRE_DROP_EFFECTS == frozenset(
        {"fireworks", "pulse", "orbits", "blackhole"})
    for et in device_model.PRE_DROP_EFFECTS:
        assert device_model.pre_drop_looks(et), et


def test_the_golden_covers_every_case_of_his_scene_list():
    assert len(SCENES) == 14
    assert set(GOLDEN) == {harness.case_key(*c) for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=[harness.case_key(*c) for c in CASES])
def test_arm_writes_with_no_pre_drop_are_todays_plus_the_untold_keys(case):
    scene_id, cls, gap, intensity, energy = case
    got = harness.arm_writes(SCENES[scene_id], cls, gap, intensity, energy)
    gold = GOLDEN[harness.case_key(*case)]
    assert _dump([w for w in got if not _member(w)]) == _dump(
        [w for w in gold if not _member(w)])
    assert _dump(got) == _dump(_untold(gold))


def _candidates():
    from spectra.services.pre_drop_play import PreDropCandidate
    # both kinds, well inside every scene's default window, landing well
    # after the lull starts
    return (PreDropCandidate(at_ms=2400, gap_ms=800, kind="spike", key="k"),
            PreDropCandidate(at_ms=1900, gap_ms=3300, kind="intro", key="k"))


SEEN_TOLD: set = set()


@pytest.mark.parametrize("case", LULL_CASES,
                         ids=[harness.case_key(*c) for c in LULL_CASES])
def test_with_a_pre_drop_that_plays_only_the_members_lull_arms_change(case):
    scene_id, cls, gap, intensity, energy = case
    gold = GOLDEN[harness.case_key(*case)]
    for cand in _candidates():
        got = harness.arm_writes(SCENES[scene_id], cls, gap, intensity, energy,
                                 pre_drop=cand)
        assert _dump([w for w in got if not _member(w)]) == _dump(
            [w for w in gold if not _member(w)]), cand.kind
        for w in got:
            p = w["params"]
            if not _member(w) or p.get("phase") != "lull":
                continue
            et = w["effect_type"]
            assert p[pre_drop.KIND_KEY] == cand.kind
            assert p[pre_drop.AT_KEY] == pytest.approx(cand.at_ms / 1000.0)
            assert p[pre_drop.GAP_KEY] == pytest.approx(cand.gap_ms / 1000.0)
            assert p[pre_drop.LOOK_KEY] == AUTO_LOOK[(et, cand.kind)]
            b = p[phase_grammar.BREATH_KEY]
            assert b > 0.0
            assert p[phase_grammar.BREATH_AT_KEY] + b == pytest.approx(
                p[pre_drop.AT_KEY], abs=1e-9), "the breath ends on the pre-drop"
            SEEN_TOLD.add(et)


def test_every_member_was_told_on_his_scenes():
    """Run last (file order): his scenes carry Pulse on the Singles and
    Fireworks, Orbits and Black Hole on their V2 scenes' crystal, so every
    member was told."""
    if not SEEN_TOLD:
        pytest.skip("run with the parametrised test above")
    assert SEEN_TOLD == {"fireworks", "pulse", "orbits", "blackhole"}


def test_the_engine_decides_on_his_scenes():
    """The verdict is the scene's — it is what the drop's colour fade
    follows, member or not."""
    from spectra.models.scene import SceneV2
    from spectra.services import scene_response
    fish = next(s for s in SCENES.values() if s["name"] == "Fish")
    scene = SceneV2(**fish)
    for cand in _candidates():
        verdict = scene_response.pre_drop_play.decide(scene, cand)
        assert verdict.plays, verdict
