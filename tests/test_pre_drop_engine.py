"""THE PRE-DROP ENGINE (predrop plan step 5) — the told keys, the one play
rule, and what a member's lull arm carries.

These tests make real effects that are not members (Black Hole, Orbits)
STUB MEMBERS by patching fx.device_model.PRE_DROP_EFFECTS (and the
registry's looks), so they hold whatever the real members are: the
acceptance is that the keys — kind and look included — arrive on the lull
arm only when the showing scene allows that kind and the gap is inside its
window; that a member's told breath ends exactly at `pre_drop_at_s` while a
non-member breath effect on the same arm keeps today's breath before the
drop; and that the lull hand-off and the keepers meld are told exactly what
they were. Every arm is read off the production ResponseEngine._drive_phase
through a RecordingExecutor (tests/pre_drop_arm_harness.py), over his own
Black Hole V2 and Orbits V2 scenes.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model
from fx.effects import lull_dark, phase_grammar
from fx.effects import pre_drop as fx_pre_drop
from spectra.models.scene import (PreDropIntroWindow, PreDropLooks,
                                  PreDropSpikeWindow, SceneV2)
from spectra.services import pre_drop_play
from tests import pre_drop_arm_harness as harness

SCENES = {s["name"]: s for s in harness.his_scenes()}
LOOKS = {"looks": {"ring": {"label": "Infall ring", "kinds": ["spike", "intro"]},
                   "spin": {"label": "Spin-up", "kinds": ["intro"]}},
         "auto": {"spike": "ring", "intro": "ring"}}


def _cand(at_ms=2400, gap_ms=800, kind="spike"):
    return pre_drop_play.PreDropCandidate(at_ms=at_ms, gap_ms=gap_ms,
                                          kind=kind, key="seq")


@pytest.fixture
def members(monkeypatch):
    """Black Hole (a lull-dark AND breath-hold effect) and its strip
    blackhole1d (lull-dark, no breath-hold) as stub members; Black Hole
    declares two looks. Pulse, on the same scene, is not a member."""
    monkeypatch.setattr(device_model, "PRE_DROP_EFFECTS",
                        frozenset({"blackhole", "blackhole1d"}))
    real = device_model.pre_drop_looks
    monkeypatch.setattr(device_model, "pre_drop_looks",
                        lambda et: LOOKS if et == "blackhole" else real(et))


def _by_vid(writes):
    out = {}
    for w in writes:
        out.setdefault(w["virtual_id"], []).append(w)
    return out


def _arm(writes, vid):
    return next(w for w in _by_vid(writes)[vid] if w["kind"] == "jump")["params"]


def _ramp(writes, vid):
    return next(w for w in _by_vid(writes)[vid] if w["kind"] == "glide")["duration_ms"]


def _lull(scene_name, cand=None, gap=3200, scene_edit=None):
    scene = dict(SCENES[scene_name])
    if scene_edit:
        scene = scene_edit(json.loads(json.dumps(scene)))
    return harness.arm_writes(scene, "lull", gap, 0.8, 0.85, pre_drop=cand)


def _golden(scene_name, cls="lull", gap=3200):
    sid = SCENES[scene_name]["id"]
    return json.loads(harness.GOLDEN_FILE.read_text())["writes"][
        harness.case_key(sid, cls, gap, 0.8, 0.85)]


# ── 1. fx/effects/pre_drop.py ──────────────────────────────────────────────

def test_the_keys_and_not_told():
    assert fx_pre_drop.KEYS == ("pre_drop_at_s", "pre_drop_s", "pre_drop_kind",
                                "pre_drop_look")
    k = fx_pre_drop.keys_for(2.4, 0.8, "spike", "ring")
    assert k == {"pre_drop_at_s": 2.4, "pre_drop_s": 0.8,
                 "pre_drop_kind": "spike", "pre_drop_look": "ring"}
    assert fx_pre_drop.told(k)
    assert not fx_pre_drop.told(fx_pre_drop.NOT_TOLD)
    assert not fx_pre_drop.told({})
    assert fx_pre_drop.at_s(fx_pre_drop.NOT_TOLD) == 0.0


def test_a_member_keeps_the_keys_through_its_own_schema():
    import voluptuous as vol
    schema = vol.Schema(fx_pre_drop.schema_fields())
    told = schema(fx_pre_drop.keys_for(2.4, 0.8, "intro", "ring"))
    assert told["pre_drop_kind"] == "intro"
    assert schema({}) == fx_pre_drop.NOT_TOLD
    with pytest.raises(vol.Invalid):
        schema({"pre_drop_kind": "clap"})


@pytest.mark.parametrize("chosen,kind,expect", [
    (None, "spike", "ring"),
    ({"spike": "auto", "intro": "auto"}, "intro", "ring"),
    ({"spike": "ring", "intro": "spin"}, "intro", "spin"),
    ({"spike": "ring", "intro": "same"}, "intro", "ring"),
    ({"spike": "nope", "intro": "auto"}, "spike", "ring"),     # unknown -> auto
])
def test_looks_resolve_against_what_the_effect_declares(chosen, kind, expect):
    assert fx_pre_drop.resolve_look(LOOKS, kind, chosen) == expect


def test_an_effect_with_no_looks_resolves_to_none():
    assert fx_pre_drop.resolve_look(None, "spike", {"spike": "ring"}) == ""
    assert fx_pre_drop.resolve_look(LOOKS, "clap", None) == ""


def _lull_config(pre=True):
    cfg = {**lull_dark.keys_for(3.2, 2.88, 3.0),
           **phase_grammar.breath_keys_for(2.4 if pre else 3.2, 0.4, 3.0)}
    if pre:
        cfg.update(lull_dark.keys_for(2.4, 2.16, 3.0))
        cfg.update(fx_pre_drop.keys_for(2.4, 0.8, "spike", "ring"))
    return cfg


def test_the_phase_clock_names_the_lull_with_a_pre_drop():
    cfg = _lull_config(pre=True)
    walk = [(t, fx_pre_drop.phase_clock(cfg, "lull", 0.5, t).segment)
            for t in (0.1, 1.3, 1.9, 2.05, 2.3, 2.5, 3.1)]
    # a 2.4 s lull to the pre-drop: dark from 1.2 s (half of it), the 0.4 s
    # breath from 2.0 s, the pre-drop at 2.4 s, the drop 0.8 s later
    assert walk == [(0.1, "approach"), (1.3, "dark"), (1.9, "dark"),
                    (2.05, "breath"), (2.3, "breath"), (2.5, "pre_drop"),
                    (3.1, "pre_drop")]
    clk = fx_pre_drop.phase_clock(cfg, "lull", 0.5, 2.8)
    assert (clk.kind, clk.look) == ("spike", "ring")
    assert clk.frac == pytest.approx(0.5)
    assert clk.until_drop == pytest.approx(0.4)


def test_the_phase_clock_names_the_lull_without_one():
    cfg = _lull_config(pre=False)
    walk = [fx_pre_drop.phase_clock(cfg, "lull", 0.5, t).segment
            for t in (0.5, 2.0, 2.9, 3.19)]
    assert walk == ["approach", "dark", "breath", "breath"]
    clk = fx_pre_drop.phase_clock(cfg, "lull", 0.5, 3.0)
    assert (clk.kind, clk.look) == ("", "")
    assert clk.until_drop == pytest.approx(0.2)


def test_the_phase_clock_edges_once_per_segment_and_on_a_fresh_lull():
    cfg = _lull_config(pre=True)
    prev, edges = None, []
    for i in range(0, 320):
        t = i / 100.0
        prev = fx_pre_drop.phase_clock(cfg, "lull", 0.5, t, prev)
        if prev.edge:
            edges.append((t, prev.segment))
    assert [s for _t, s in edges] == ["approach", "dark", "breath", "pre_drop"]
    assert edges[-1][0] == pytest.approx(2.4)
    again = fx_pre_drop.phase_clock(cfg, "lull", 0.0, 0.0, prev)
    assert again.edge, "phase_t went back: a new lull"
    assert fx_pre_drop.phase_clock({}, "charge", 0.3, 1.0).segment == "charge"
    assert fx_pre_drop.phase_clock({}, "drop", 0.3, 1.0).until_drop == 0.0
    assert fx_pre_drop.phase_clock({}, "none", 0.0, 0.0).segment == "none"


# ── 2. the breath ends on the pre-drop, with no overrun ─────────────────────

def test_a_breath_ending_on_a_told_pre_drop_lifts_exactly_on_it():
    cfg = _lull_config(pre=True)
    assert fx_pre_drop.breath_ends_on_pre_drop(cfg)
    assert phase_grammar.breath_gain(cfg, 2.2) == 0.0        # the black
    assert phase_grammar.breath_gain(cfg, 2.399) == 0.0
    assert phase_grammar.breath_gain(cfg, 2.4) == 1.0        # the pre-drop
    assert phase_grammar.breath_gain(cfg, 2.6) == 1.0


def test_a_breath_ending_on_the_drop_keeps_its_overrun():
    cfg = _lull_config(pre=False)
    assert not fx_pre_drop.breath_ends_on_pre_drop(cfg)
    assert phase_grammar.breath_gain(cfg, 3.3) == 0.0        # drop late: holds
    assert phase_grammar.breath_gain(cfg, 3.2 + phase_grammar.BREATH_OVERRUN_S) == 1.0


def test_a_breath_not_ending_on_the_told_pre_drop_keeps_its_overrun():
    cfg = {**_lull_config(pre=True),
           **phase_grammar.breath_keys_for(3.2, 0.4, 3.0)}   # to the drop
    assert not fx_pre_drop.breath_ends_on_pre_drop(cfg)
    assert phase_grammar.breath_gain(cfg, 3.3) == 0.0


# ── 3. the play rule ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("cand,edit,reason", [
    (_cand(), None, "plays"),
    (_cand(kind="intro", gap_ms=3300), None, "plays"),
    (_cand(), lambda s: setattr(s, "pre_drop_spike",
                                PreDropSpikeWindow(enabled=False)), "kind_off"),
    (_cand(gap_ms=300), None, "gap_below_min"),
    (_cand(gap_ms=2500), None, "gap_above_max"),
    (_cand(kind="intro", gap_ms=4200), None, "gap_above_max"),
    (_cand(at_ms=150), None, "too_soon_after_lull"),
    (_cand(kind="clap"), None, "unknown_kind"),
])
def test_the_one_rule(cand, edit, reason):
    scene = SceneV2(name="x")
    if edit:
        edit(scene)
    verdict = pre_drop_play.decide(scene, cand)
    assert verdict.reason == reason
    assert verdict.plays is (reason == "plays")
    assert pre_drop_play.sentence(verdict.as_dict())


def test_no_scene_plays_nothing():
    assert pre_drop_play.decide(None, _cand()).reason == "no_scene"


def test_a_scenes_own_window_decides():
    scene = SceneV2(name="x", pre_drop_spike={"enabled": True, "min_ms": 900,
                                              "max_ms": 1500})
    assert pre_drop_play.decide(scene, _cand(gap_ms=800)).reason == "gap_below_min"
    assert pre_drop_play.decide(scene, _cand(gap_ms=1200)).plays


# ── 4. the scene model ───────────────────────────────────────────────────────

def test_the_windows_ship_on_with_his_defaults():
    scene = SceneV2(name="x")
    assert scene.pre_drop_spike.model_dump() == {"enabled": True, "min_ms": 350,
                                                 "max_ms": 2000}
    assert scene.pre_drop_intro.model_dump() == {"enabled": True, "min_ms": 350,
                                                 "max_ms": 4000}
    assert scene.pre_drop_window("spike") is scene.pre_drop_spike
    assert scene.pre_drop_window("clap") is None


@pytest.mark.parametrize("cls,body", [
    (PreDropSpikeWindow, {"min_ms": 200, "max_ms": 2000}),     # under 250
    (PreDropSpikeWindow, {"min_ms": 350, "max_ms": 3100}),     # over 3000
    (PreDropIntroWindow, {"min_ms": 300, "max_ms": 4000}),     # under 350
    (PreDropIntroWindow, {"min_ms": 350, "max_ms": 4600}),     # over 4500
    (PreDropSpikeWindow, {"min_ms": 1500, "max_ms": 1500}),    # min == max
])
def test_window_bounds_and_order_are_refused(cls, body):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        cls(**body)


def test_looks_default_auto_and_same_is_the_intros_only():
    from pydantic import ValidationError
    assert PreDropLooks().model_dump() == {"spike": "auto", "intro": "auto"}
    assert PreDropLooks(intro="same").intro == "same"
    with pytest.raises(ValidationError):
        PreDropLooks(spike="same")


def test_his_scenes_load_unchanged_with_the_defaults():
    for raw in SCENES.values():
        scene = SceneV2(**raw)
        assert scene.pre_drop_spike.enabled and scene.pre_drop_intro.enabled
        assert all(d.pre_drop_looks.spike == "auto" for d in scene.devices)


def test_the_registry_serves_the_bounds_and_only_declared_looks(monkeypatch):
    from spectra.api import registry
    real = device_model.pre_drop_looks
    monkeypatch.setattr(device_model, "pre_drop_looks",
                        lambda et: LOOKS if et == "blackhole" else real(et))
    body = asyncio.run(registry.get_registry())
    assert body["pre_drop"]["kinds"]["spike"] == {
        "label": "Spike", "min_bound": 250, "max_bound": 3000,
        "default_min_ms": 350, "default_max_ms": 2000}
    assert body["pre_drop"]["kinds"]["intro"]["max_bound"] == 4500
    assert body["effects"]["blackhole"]["pre_drop_looks"] == LOOKS
    assert "pre_drop_looks" not in body["effects"]["squiggles"]


# ── 5. the lull arm, with stub members ───────────────────────────────────────

def test_a_member_is_told_the_pre_drop_and_its_lull_is_measured_to_it(members):
    writes = _lull("Black Hole V2", _cand())
    arm = _arm(writes, "Matrix-0")                          # blackhole
    assert arm["pre_drop_at_s"] == 2.4 and arm["pre_drop_s"] == 0.8
    assert (arm["pre_drop_kind"], arm["pre_drop_look"]) == ("spike", "ring")
    # THE BREATH ENDS EXACTLY ON THE PRE-DROP
    assert arm["lull_breath_at_s"] + arm["lull_breath_s"] == pytest.approx(
        arm["pre_drop_at_s"], abs=1e-9)
    assert arm["lull_breath_s"] == 0.4
    # the ramp and the dark point measured to the pre-drop, not the drop
    assert _ramp(writes, "Matrix-0") == round(2400 * 0.9)
    assert arm["lull_ramp_s"] == pytest.approx(2.16)
    assert arm["lull_dark_s"] == pytest.approx(lull_dark.dark_start_s(2.4, 3.0))


def test_a_member_with_no_breath_hold_of_its_own_is_told_the_shifted_breath(members):
    writes = _lull("Black Hole V2", _cand())
    strip = _arm(writes, "Strips-1")                        # blackhole1d
    assert strip["pre_drop_at_s"] == 2.4
    assert strip["pre_drop_look"] == "", "it declares no looks"
    assert strip["lull_breath_at_s"] + strip["lull_breath_s"] == pytest.approx(2.4)
    assert strip["lull_dark_s"] == pytest.approx(lull_dark.dark_start_s(2.4, 3.0))


def test_a_non_member_breath_effect_on_the_same_arm_keeps_todays_breath(members):
    writes = _lull("Black Hole V2", _cand())
    golden = _by_vid(_golden("Black Hole V2"))
    assert _by_vid(writes)["Singles-2"] == golden["Singles-2"]   # pulse
    pulse = _arm(writes, "Singles-2")
    assert pulse["lull_breath_at_s"] + pulse["lull_breath_s"] == pytest.approx(3.2)
    assert "pre_drop_at_s" not in pulse


def _spike_off(s):
    s["pre_drop_spike"] = {"enabled": False, "min_ms": 350, "max_ms": 2000}
    return s


@pytest.mark.parametrize("cand,edit,reason", [
    (_cand(), _spike_off, "kind_off"),
    (_cand(gap_ms=2600), None, "gap_above_max"),
    (_cand(at_ms=100), None, "too_soon_after_lull"),
])
def test_a_pre_drop_that_does_not_play_tells_members_nothing(members, cand, edit, reason):
    writes = _lull("Black Hole V2", cand, scene_edit=edit)
    rec = asyncio.run(_record(edit(json.loads(json.dumps(SCENES["Black Hole V2"])))
                              if edit else SCENES["Black Hole V2"], cand))
    assert rec["pre_drop"]["reason"] == reason
    golden = _by_vid(_golden("Black Hole V2"))
    arm = _arm(writes, "Matrix-0")
    for k, v in fx_pre_drop.NOT_TOLD.items():
        assert arm[k] == v
    # everything else on the arm is today's: breath to the drop, today's ramp
    today = next(w for w in golden["Matrix-0"] if w["kind"] == "jump")["params"]
    assert {k: v for k, v in arm.items() if k not in fx_pre_drop.KEYS} == today
    assert _ramp(writes, "Matrix-0") == _ramp(_golden("Black Hole V2"), "Matrix-0")
    strip = _arm(writes, "Strips-1")
    assert (strip["lull_breath_at_s"], strip["lull_breath_s"]) == (0.0, 0.0), \
        "a member with no breath-hold of its own is told none (rule 2)"


def test_every_member_is_told_on_every_lull_arm_even_without_a_candidate(members):
    writes = _lull("Black Hole V2", None)
    for vid in ("Matrix-0", "Strips-1"):
        arm = _arm(writes, vid)
        assert {k: arm[k] for k in fx_pre_drop.KEYS} == fx_pre_drop.NOT_TOLD


def test_charge_and_drop_arms_are_never_told_a_pre_drop(members):
    for cls, gap in (("charge", 4000), ("drop", None)):
        writes = harness.arm_writes(SCENES["Black Hole V2"], cls, gap, 0.8, 0.85,
                                    pre_drop=_cand())
        sid = SCENES["Black Hole V2"]["id"]
        golden = json.loads(harness.GOLDEN_FILE.read_text())["writes"][
            harness.case_key(sid, cls, gap, 0.8, 0.85)]
        assert json.dumps(writes, sort_keys=True) == json.dumps(golden, sort_keys=True)


def test_the_intros_same_look_wears_the_spikes(members):
    def same(s):
        for d in s["devices"]:
            d["pre_drop_looks"] = {"spike": "ring", "intro": "same"}
        return s
    writes = _lull("Black Hole V2", _cand(kind="intro", gap_ms=3300, at_ms=2900),
                   gap=6040, scene_edit=same)
    arm = _arm(writes, "Matrix-0")
    assert (arm["pre_drop_kind"], arm["pre_drop_look"]) == ("intro", "ring")


def test_the_record_names_the_verdict_and_who_was_told(members):
    rec = asyncio.run(_record(SCENES["Black Hole V2"], _cand()))
    pd = rec["pre_drop"]
    assert pd["plays"] and pd["reason"] == "plays"
    assert sorted(pd["told"]) == ["Matrix-0", "Strips-1"]
    assert pd["member_lull"]["ramp_ms"] == 2160
    assert pd["member_lull"]["breath_at_s"] + pd["member_lull"]["breath_s"] == \
        pytest.approx(2.4)
    off = asyncio.run(_record(SCENES["Black Hole V2"], _cand(gap_ms=2600)))
    assert off["pre_drop"]["reason"] == "gap_above_max"
    assert off["pre_drop"]["told"] == [] and "member_lull" not in off["pre_drop"]


async def _record(scene_dict, cand, gap=3200, resolver=None, intensity=0.8):
    from random import Random
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services import scene_response
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor
    scene = SceneV2(**scene_dict)
    room = [cj.RoomColorState()]
    controls = rc.RoomControlState()
    ex = RecordingExecutor(clock=lambda: 1.0, room_controls_load=lambda: controls)
    conductor = DriftConductor(
        executor=ex, clock=lambda: 1.0, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, room_load=lambda: room[0],
        room_save=lambda st: room.__setitem__(0, st), set_cards=lambda: [],
        gradient_profiles=lambda: {}, room_controls=lambda: controls,
        rng=Random(3))
    responder = scene_response.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(5), clock=lambda: 1.0,
        curve_profiles=lambda: {}, room_load=lambda: room[0],
        room_save=lambda st: room.__setitem__(0, st),
        room_controls=lambda: controls, room_energy=lambda: 0.85)
    responder.lull_handoff_resolver = (resolver
                                       or scene_response.default_lull_handoff)
    conductor.on_scene_fire(scene, harness._virtuals(scene))
    ex.writes.clear()
    real = scene_response._house_owns_the_look
    scene_response._house_owns_the_look = lambda: None
    try:
        rec = await responder._drive_phase("lull", gap, intensity, pre_drop=cand)
    finally:
        scene_response._house_owns_the_look = real
    rec["_writes"] = list(ex.writes)
    return rec


# ── 6. the lull hand-off and the keepers meld are told what they were ──────

def test_the_hand_off_and_the_keepers_are_untouched_by_a_pre_drop(monkeypatch):
    """Orbits is a LULL_HANDOFF member (the keepers meld tells it how many
    blobs to keep for the drop) and a breath-hold effect. As a stub member
    told a pre-drop it keeps exactly the keep, next and lull_s it is told
    without one — the hand-off is about what the DROP lands on, so its
    lull_s stays the gap to the drop — while its breath moves to the
    pre-drop."""
    from spectra.services import scene_response
    monkeypatch.setattr(device_model, "PRE_DROP_EFFECTS", frozenset({"orbits"}))

    def keepers(ctx):
        return scene_response.LullHandoff(
            keep=3, next_effect={vid: "fireworks" for vid in ctx.virtuals},
            lull_s=ctx.lull_s)

    plain = asyncio.run(_record(SCENES["Orbits V2"], None, resolver=keepers))
    told = asyncio.run(_record(SCENES["Orbits V2"], _cand(), resolver=keepers))

    def arm(rec):
        return next(w for w in rec["_writes"]
                    if w["virtual_id"] == "Matrix-0" and w["kind"] == "jump")["params"]

    a, b = arm(plain), arm(told)
    for k in ("lull_keep", "lull_next", "lull_s"):
        assert a[k] == b[k], k
    assert (b["lull_keep"], b["lull_next"]) == (3, "fireworks")
    assert b["lull_s"] == pytest.approx(3.2), "the drop's gap, not the pre-drop's"
    assert b["lull_breath_at_s"] + b["lull_breath_s"] == pytest.approx(2.4)
    assert a["lull_breath_at_s"] + a["lull_breath_s"] == pytest.approx(3.2)
    assert told["lull_handoff"] == plain["lull_handoff"]


# ── 7. drop_firing: whose pre-drop may play ─────────────────────────────────

def _view_seq(**extra):
    base = {"key": "drop:20000", "state": "confident", "origin": "detected",
            "drop_ms": 20000, "lull_ms": 16000, "charge_ms": 12000,
            "tier": "confident", "step": 0.8,
            "parts": {"charge": "waiting", "lull": "waiting",
                      "pre_drop": "waiting", "drop": "waiting"}}
    base.update(extra)
    return {"sequences": [base], "song": {"beat_ms": 500}}


@pytest.mark.parametrize("extra,testing,plays", [
    ({"pre_drop_ms": 19200, "pre_drop_kind": "spike", "pre_drop_tier": "confident"}, False, True),
    ({"pre_drop_ms": 19200, "pre_drop_kind": "spike", "pre_drop_tier": "suggested"}, False, False),
    ({"pre_drop_ms": 19200, "pre_drop_kind": "spike", "pre_drop_tier": "suggested"}, True, True),
    ({"pre_drop_ms": 19200, "pre_drop_kind": "intro", "pre_drop_tier": None,
      "parts": {"pre_drop": "on", "drop": "on", "lull": "on", "charge": "on"}}, False, True),
    ({"pre_drop_ms": 19200, "pre_drop_kind": "spike", "pre_drop_tier": "confident",
      "parts": {"pre_drop": "off", "drop": "on", "lull": "on", "charge": "on"}}, True, False),
    ({"pre_drop_ms": None, "pre_drop_kind": None}, True, False),
])
def test_a_sequences_pre_drop_part_decides_whether_it_may_play(extra, testing, plays):
    from spectra.services import drop_firing
    [seq] = drop_firing.firing_sequences(_view_seq(**extra), testing=testing)
    got = seq.pre_drop_for("lull", "analysed")
    assert (got is not None) is plays
    if plays:
        assert got == (19200, extra["pre_drop_kind"])
    assert seq.pre_drop_for("drop", "analysed") is None
    assert seq.pre_drop_for("charge", "analysed") is None


def test_no_lull_no_pre_drop():
    from spectra.services import drop_firing
    [seq] = drop_firing.firing_sequences(_view_seq(
        lull_ms=None, pre_drop_ms=19200, pre_drop_kind="spike",
        pre_drop_tier="confident"))
    assert seq.pre_drop_ms == 19200
    assert seq.pre_drop_for("lull", "analysed") is None


def test_his_own_grouped_drops_pre_drops():
    from spectra.services import drop_firing
    view = {"authored": [
        {"lull": {"id": "L1", "timestamp_ms": 16000},
         "drop": {"id": "D1", "timestamp_ms": 20000},
         "pre_drop": {"ms": 19300, "kind": "intro", "off": False,
                      "part": "waiting", "tier": "confident"}},
        {"lull": {"id": "L2", "timestamp_ms": 40000},
         "drop": {"id": "D2", "timestamp_ms": 44000},
         "pre_drop": {"ms": 43500, "kind": "spike", "off": False,
                      "part": "waiting", "tier": "suggested"}},
        {"drop": {"id": "D3", "timestamp_ms": 60000},
         "pre_drop": {"ms": 59500, "kind": "spike", "off": False,
                      "part": "on", "tier": None}},
    ]}
    got = drop_firing.his_pre_drops(view)
    assert list(got) == ["L1"]
    assert (got["L1"].key, got["L1"].pre_drop_ms, got["L1"].kind) == (
        "his:D1", 19300, "intro")
    assert list(drop_firing.his_pre_drops(view, testing=True)) == ["L1", "L2"]


def test_a_worked_out_pre_drop_of_his_moves_the_revision(monkeypatch):
    from spectra.services import drop_detector, drop_sequences as ds
    before = ds.revision()

    class _A:
        shape = None
    monkeypatch.setattr(drop_detector, "analyse", lambda uri: _A())
    from spectra.services import predrop_detector
    monkeypatch.setattr(predrop_detector, "detect", lambda shape, ms: None)
    ds.his_pre_drop("spotify:track:x", "stamp", 20000, compute=True)
    assert ds.revision() != before
    known, pre = ds.his_pre_drop("spotify:track:x", "stamp", 20000)
    assert known and pre is None
