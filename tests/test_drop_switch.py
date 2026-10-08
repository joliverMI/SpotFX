"""THE DROP-LED SCENE SWITCH (spectra/services/drop_switch.py; drop-scene-
variety plan phase 2 — options B + D as the Admiral revised them: "just
switch at the drop", early in the charge only when the pair has no good drop
hand-off or the scene is already stale, riding a flare inside the charge
when there is one).

Two halves:

  1. THE DECISION, pure: the stale rule's three reasons (and "nothing
     showing"), the families, the hand-off table, the moment rule, the
     named no-switch reasons, determinism, the lull hand-off it tells.
  2. THE TRIGGER CLOCK on his real songs: the real TriggerEngine sweeping
     FINA and 100 MILLONES (tests/fixtures — his authored triggers, the
     drop-sequence store with his confirmations, the analysed plan, all
     captured 2026-10-08 from temp copies of the live stores) under his
     live "analysed" mode, against a modelled room (which scene is showing,
     since when). Measured before the change (the switch off): FINA played
     every drop on whatever the planned cues left showing, 100 MILLONES on
     nothing at all. With it on: the cut lands on the drop member's own
     tick, in the same fire, before the drop's phase arm; the early cut
     lands at the charge start or on the flare inside the charge; every
     decision and cut is in the registry and the show log.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from random import Random

import pytest

from spectra import config as scfg
from spectra.models.trigger import SpectraTrigger
from spectra.services import (analysed_flares, drop_firing, drop_sequences,
                              drop_switch as ds, fire_history,
                              midsong_generator)
from spectra.services.scene_response import LullContext, LullHandoff
from spectra.services.trigger_engine import TriggerEngine

FIXTURES = Path(__file__).parent / "fixtures"
STEP = 200


# ═══ 1. the decision ════════════════════════════════════════════════════

SCENES = {
    "fish": ds.SceneInfo("fish", "Fish", "fish"),
    "orbits": ds.SceneInfo("orbits", "Orbits V2", "orbits"),
    "star": ds.SceneInfo("star", "STAR", "radial"),
    "bh": ds.SceneInfo("bh", "Black Hole V2", "blackhole"),
    "sq": ds.SceneInfo("sq", "Squiggles V2", "squiggles"),
    "fw": ds.SceneInfo("fw", "Fireworks V2", "fireworks"),
    "eye": ds.SceneInfo("eye", "Eye V2", "eye"),
}
READY = [k for k, v in SCENES.items() if ds.family_of(v.effect)]


def pick_first_other(prefer=None):
    def pick(showing_id, rng):
        order = ([prefer] if prefer else []) + sorted(READY)
        for sid in order:
            if sid and sid != showing_id and sid in READY:
                return SCENES[sid]
        return None
    return pick


def showing(sid, shown_s=5.0, dwell_s=8.0):
    return ds.Showing(scene=SCENES[sid], stint=(sid, 0), shown_s=shown_s,
                      dwell_s=dwell_s)


MEMBERS = {"charge": 10_000, "lull": 14_000, "drop": 16_000}


def decide(**kw):
    args = dict(key="drop:16000", uri="u", members=MEMBERS,
                showing=showing("orbits"), record=ds.StintRecord(),
                settings=ds.SwitchSettings(), pick_target=pick_first_other("star"))
    args.update(kw)
    return ds.decide(**args)


def test_a_fresh_scene_plays_its_drop_and_says_why():
    p = decide()
    assert not p.switch and p.reason == "fresh"
    assert "Orbits V2 is still fresh" in p.sentence


def test_repeating_the_previous_drop_switches_ON_the_drop_as_a_cut():
    p = decide(record=ds.StintRecord(drops_carried=1, carried_previous_drop=True,
                                     arrived_on_previous_drop=False))
    assert p.switch and p.moment == ds.MOMENT_DROP
    assert p.stale_by == (ds.STALE_PREVIOUS_DROP,)
    assert (p.from_scene_name, p.to_scene_name) == ("Orbits V2", "STAR")
    assert p.handoff == ds.HANDOFF_CHOREOGRAPHED      # orbits -> radial bloom
    assert p.cut_ms() == 16_000
    assert "hard cut on the drop" in p.sentence


def test_a_scene_installed_BY_the_previous_drop_is_fresh_for_the_next():
    p = decide(record=ds.StintRecord(drops_carried=1, carried_previous_drop=True,
                                     arrived_on_previous_drop=True))
    assert not p.switch and p.reason == "fresh"


def test_drops_in_a_row_and_its_off_switch():
    rec = ds.StintRecord(drops_carried=2, carried_previous_drop=True,
                         arrived_on_previous_drop=True)
    assert decide(record=rec).stale_by == (ds.STALE_DROPS_IN_A_ROW,)
    off = ds.SwitchSettings(drops_in_a_row=0)
    assert not decide(record=rec, settings=off).switch


def test_previous_drop_rule_can_be_turned_off():
    rec = ds.StintRecord(drops_carried=1, carried_previous_drop=True)
    assert not decide(record=rec,
                      settings=ds.SwitchSettings(after_previous_drop=False)).switch


def test_an_overstayed_scene_switches_EARLY_at_the_charge_start():
    p = decide(showing=showing("orbits", shown_s=30.0, dwell_s=8.0))
    assert p.stale_by == (ds.STALE_OVERSTAYED,)
    assert p.moment == ds.MOMENT_CHARGE_START and p.cut_ms() == 10_000
    assert "early because it is already stale" in p.sentence


def test_an_overstayed_scene_rides_the_flare_inside_the_charge():
    ride = ds.find_ride(10_000, 14_000, [("f1", 12_500), ("f0", 10_100)])
    assert ride == ("f1", 12_500)        # f0 sits within 250 ms of the start
    p = decide(showing=showing("orbits", shown_s=30.0), ride=ride)
    assert p.moment == ds.MOMENT_CHARGE_FLARE
    assert (p.ride_trigger_id, p.cut_ms()) == ("f1", 12_500)


def test_no_good_drop_handoff_switches_early_even_when_only_repetition_stale():
    rec = ds.StintRecord(drops_carried=1, carried_previous_drop=True)
    p = decide(showing=showing("eye"), record=rec)
    assert p.handoff is None and p.moment == ds.MOMENT_CHARGE_START
    assert "no good drop hand-off from Eye V2" in p.sentence


def test_nothing_showing_installs_a_scene_at_the_charge():
    p = decide(showing=None)
    assert p.switch and p.stale_by == (ds.STALE_NOTHING_SHOWING,)
    assert p.moment == ds.MOMENT_CHARGE_START and p.from_scene_id is None


def test_with_no_charge_or_a_charge_already_passed_the_early_switch_is_the_drop():
    early = dict(showing=showing("orbits", shown_s=30.0))
    assert decide(members={"lull": 14_000, "drop": 16_000},
                  **early).moment == ds.MOMENT_DROP
    assert decide(can_go_early=False, **early).moment == ds.MOMENT_DROP


@pytest.mark.parametrize("kw,reason", [
    (dict(settings=ds.SwitchSettings(enabled=False)), "off"),
    (dict(blocker="force_scene"), "force_scene"),
    (dict(blocker="house_mode"), "house_mode"),
    (dict(pick_target=lambda sid, rng: None), "no_target"),
    (dict(pick_target=lambda sid, rng: SCENES["orbits"]), "no_target"),
])
def test_every_no_switch_is_named(kw, reason):
    stale = ds.StintRecord(drops_carried=3, carried_previous_drop=True)
    p = decide(record=stale, **kw)
    assert not p.switch and p.reason == reason and p.sentence


def test_the_target_draw_is_deterministic_per_song_sequence_and_scene():
    a = ds.seeded_rng("u", "drop:1", "fish").random()
    assert a == ds.seeded_rng("u", "drop:1", "fish").random()
    assert a != ds.seeded_rng("u", "drop:2", "fish").random()
    assert a != ds.seeded_rng("u", "drop:1", "orbits").random()


def test_every_drop_ready_pair_has_a_handoff_and_fireworks_stays_generic():
    from fx import device_model as dm
    for out in dm.DROP_SWITCH_EFFECTS:
        for inc in dm.DROP_SWITCH_EFFECTS:
            assert ds.handoff_kind(out, inc) is not None
    for other in dm.DROP_SWITCH_EFFECTS - {"fireworks"}:
        assert ds.handoff_kind(other, "fireworks") == ds.HANDOFF_GENERIC
        assert ds.handoff_kind("fireworks", other) == ds.HANDOFF_GENERIC
    for outside in ("eye", "dancer", "pacman", None):
        assert ds.handoff_kind(outside, "radial") is None
    assert ds.handoff_kind("radial", "blackhole") == ds.HANDOFF_CHOREOGRAPHED
    assert ds.handoff_kind("squiggles", "blackhole") == ds.HANDOFF_GENERIC


def _ctx(virtuals, lull_s=2.0):
    return LullContext(scene=None, intensity=0.8, gap_ms=int(lull_s * 1000),
                       lull_s=lull_s, virtuals=virtuals, uri="u",
                       position_ms=14_000)


def test_the_lull_is_told_what_the_drop_will_install(monkeypatch):
    from fx import device_model as dm
    monkeypatch.setattr(dm, "get_virtuals_for_category",
                        lambda c: {"Matrix": ["crystal"], "Strips": ["strip"]}.get(c, []))
    from types import SimpleNamespace as NS
    target = NS(devices=[NS(target_kind="category", target="Matrix", effect_type="radial"),
                         NS(target_kind="category", target="Strips", effect_type="melt")])
    plan = decide(record=ds.StintRecord(drops_carried=1, carried_previous_drop=True))
    ans = ds.handoff_for(plan, _ctx({"crystal": "fish", "strip": "orbits1d"}),
                         target_scene=target)
    assert isinstance(ans, LullHandoff)
    assert dict(ans.next_effect) == {"crystal": "radial", "strip": "melt"}
    assert ans.keep == 1 and ans.lull_s == 2.0
    # an early plan already switched by the lull: told the same effect
    early = decide(showing=showing("orbits", shown_s=30.0))
    assert dict(ds.handoff_for(early, _ctx({"crystal": "fish"})).next_effect) == {}
    # no plan: the hook's own default
    assert ds.handoff_for(None, _ctx({"crystal": "fish"})).keep == 1


def test_the_installed_resolver_answers_from_the_plan_marked_current(monkeypatch):
    monkeypatch.setattr(ds, "_scene_by_id", lambda sid: None)
    plan = ds.record_plan(decide(record=ds.StintRecord(
        drops_carried=1, carried_previous_drop=True)))
    with ds.lull_plan(plan):
        ds.lull_handoff_resolver(_ctx({"crystal": "fish"}))
    assert ds.plan("u", plan.key).lull_handoff == {"keep": 1, "next": {}}
    # outside a marked lull it finds the plan by song position, or none
    assert ds.plan_for_position("u", 14_500).key == plan.key
    assert ds.plan_for_position("u", 30_000) is None


def test_the_preview_plan_is_the_resolver_for_a_stale_scene():
    from types import SimpleNamespace as NS
    scene = NS(id="orbits", name="Orbits V2",
               devices=[NS(target_kind="category", target="Matrix", effect_type="orbits")])
    p = ds.preview_plan(scene, 0.8, pick_target=pick_first_other("star"))
    assert p.switch and p.moment == ds.MOMENT_DROP and p.to_scene_name == "STAR"
    off = ds.preview_plan(scene, 0.8, pick_target=pick_first_other("star"),
                          settings=ds.SwitchSettings(enabled=False))
    assert not off.switch and off.reason == "off"


# ═══ 2. the trigger clock on his real songs ═════════════════════════════

def _load(name):
    fix = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    his = [SpectraTrigger.model_validate(t) for t in fix["triggers"]]
    plan = analysed_flares.SongPlan(
        [midsong_generator.CandidateMoment(**m) for m in fix["plan"]["scene_cues"]],
        [analysed_flares.FlareMoment(**m) for m in fix["plan"]["flares"]],
        fix["plan"]["rank_of"])
    return fix, his, plan


class Room:
    """Which scene is showing and since when — the modelled room the switch
    reads (dwell's stint), moved by planned cues and by the cuts."""

    def __init__(self, start, dwell_s=8.0):
        self.position = 0
        self.scene = start
        self.entered = 0
        self.dwell_s = dwell_s
        self.log: list[tuple] = []
        self._rot = Random(7)

    def showing(self):
        if self.scene is None:
            return None
        return ds.Showing(scene=SCENES[self.scene], stint=(self.scene, self.entered),
                          shown_s=(self.position - self.entered) / 1000.0,
                          dwell_s=self.dwell_s)

    def _install(self, sid):
        self.scene, self.entered = sid, self.position

    async def fire_drop_switch(self, sid, intensity):
        self.log.append(("switch", self.position, sid))
        self._install(sid)
        return {"scene_id": sid}

    async def fire_planned_scene(self, sid, color_set_id, intensity):
        nxt = self._rot.choice([s for s in READY if s != self.scene])
        self.log.append(("planned", self.position, nxt))
        self._install(nxt)

    async def fire_sequence(self, cls, intensity, gap=None):
        self.log.append(("member", self.position, cls, self.scene))

    async def flare(self, intensity):
        self.log.append(("flare", self.position, self.scene))

    async def rearm(self, cls, progress, remaining_ms):
        self.log.append(("rearm", self.position, cls, round(progress, 3), remaining_ms))

    async def noop(self, *a, **k):
        return None

    def pick(self, intensity):
        def p(showing_id, rng):
            options = sorted(s for s in READY if s != showing_id)
            return SCENES[rng.choice(options)] if options else None
        return p

    def drops(self):
        return [e for e in self.log if e[0] == "member" and e[2] == "drop"]


def _sweep(fixture, *, start, settings=None, dwell_s=8.0):
    fix, his, plan = _load(fixture)
    uri = fix["uri"]
    scfg.DROP_SEQUENCES_FILE.write_text(
        json.dumps({uri: fix["drop_sequences_store"]}), encoding="utf-8")
    drop_sequences.reset()
    room = Room(start, dwell_s=dwell_s)
    eng = TriggerEngine(
        list_triggers=lambda u: list(his),
        scene_change_mode=lambda: "analysed",
        fire_scene=room.noop, fire_planned_scene=room.fire_planned_scene,
        fire_response=room.noop, fire_sequence=room.fire_sequence,
        fire_analysed_flare=room.flare, fire_scene_update=room.noop,
        select_color_set=room.noop, analysed_plan=lambda u, s: plan,
        render_intensity=lambda x: x, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: 0, sequencer_enabled=lambda: False,
        select_scene=lambda i: "S", select_scene_from_pool=lambda p: "S",
        transition_intensity=lambda: 0.5, auto_generate=room.noop,
        auto_refresh=room.noop,
        switch_showing=room.showing,
        switch_settings=lambda: settings or ds.SwitchSettings(),
        switch_blocker=lambda: None, switch_pick=room.pick,
        fire_drop_switch=room.fire_drop_switch, rearm_phase=room.rearm)
    duration = int(fix["drop_sequences_store"]["detected"]["duration_ms"])

    async def run():
        await eng.on_track_state(uri)
        await eng.plan_analysed_flares(uri)
        for pos in range(0, duration + STEP, STEP):
            room.position = pos
            await eng.tick(pos)

    asyncio.run(run())
    drop_sequences.reset()
    return fix, room, eng


def test_before_FINA_played_every_drop_on_the_scene_the_planned_cues_left():
    fix, room, _ = _sweep("fina_planned_scene_changes.json", start="fish",
                          settings=ds.SwitchSettings(enabled=False))
    drops = room.drops()
    assert len(drops) >= 13
    assert not [e for e in room.log if e[0] == "switch"]
    # the report's own run fired no planned cues at all (option A had not
    # landed); with A the planned cues move it a little — still few scenes
    # for the number of drops
    assert len({d[3] for d in drops}) <= 6


def test_FINA_drops_become_scene_changes_cut_on_the_drop_member():
    fix, room, eng = _sweep("fina_planned_scene_changes.json", start="fish")
    log, drops = room.log, room.drops()
    switches = [e for e in log if e[0] == "switch"]
    assert len(switches) >= len(drops) // 3, (len(switches), len(drops))
    plans = {p.key: p for p in ds.plans_for(fix["uri"])}
    assert len(plans) >= len(drops)
    on_drop = [p for p in plans.values()
               if p.switch and p.moment == ds.MOMENT_DROP
               and (p.outcome or {}).get("result") == "switched"]
    assert on_drop, [p.sentence for p in plans.values()]
    for p in on_drop:
        i = next(i for i, e in enumerate(log)
                 if e[0] == "switch" and e[2] == p.to_scene_id
                 and abs(e[1] - p.drop_ms) <= STEP)
        # ATOMIC: the very next thing is the drop member, same tick, on the
        # scene the cut installed
        assert log[i + 1][0] == "member" and log[i + 1][2] == "drop"
        assert log[i + 1][1] == log[i][1] and log[i + 1][3] == p.to_scene_id
        # the lull before it ran on the OUTGOING scene
        lull = [e for e in log[:i] if e[0] == "member" and e[2] == "lull"
                and p.lull_ms is not None and abs(e[1] - p.lull_ms) <= STEP]
        if lull:
            assert lull[-1][3] == p.from_scene_id
    # more variety than with the switch off
    assert len({d[3] for d in drops}) >= 4
    # a scene installed by a drop is never switched out on the very next
    # drop for repetition alone (the default alternates)
    ordered = sorted(plans.values(), key=lambda p: p.drop_ms)
    for prev, cur in zip(ordered, ordered[1:]):
        installed = (prev.switch and (prev.outcome or {}).get("result") == "switched"
                     and cur.from_scene_id == prev.to_scene_id)
        if installed and cur.switch:
            assert cur.stale_by != (ds.STALE_PREVIOUS_DROP,), cur.sentence


def test_every_cut_is_in_the_show_log_under_its_sequence_key():
    fix, room, _ = _sweep("fina_planned_scene_changes.json", start="fish")
    entries = [e for e in fire_history.load_show_log(uri=fix["uri"])
               if e.get("key") == "drop_sequence:switch"]
    switches = [e for e in room.log if e[0] == "switch"]
    assert len(entries) == len(switches) > 0
    for e in entries:
        d = e["detail"]
        assert d["drop_sequence"].startswith("drop:")
        assert d["result"] == "switched" and d["sentence"]
        assert d["to_scene"] and d["at"] in (ds.MOMENT_DROP, ds.MOMENT_CHARGE_START,
                                             ds.MOMENT_CHARGE_FLARE,
                                             "charge_flare_missed")
    members = [e for e in fire_history.load_show_log(uri=fix["uri"])
               if (e.get("detail") or {}).get("member") == "drop"
               and (e.get("detail") or {}).get("drop_switch")]
    assert members


def test_an_overstayed_scene_cuts_early_and_rides_a_flare_inside_the_charge():
    # dwell 0 and margin 0: every showing scene has overstayed, so every
    # sequence with a charge switches early — at the charge start, or on a
    # flare inside the charge where FINA has one (report E8: 5 of 14)
    fix, room, _ = _sweep("fina_planned_scene_changes.json", start="fish",
                          dwell_s=0.0,
                          settings=ds.SwitchSettings(stale_margin_s=0.0))
    plans = ds.plans_for(fix["uri"])
    starts = [p for p in plans if p.switch and p.moment == ds.MOMENT_CHARGE_START]
    rides = [p for p in plans if p.switch and p.moment == ds.MOMENT_CHARGE_FLARE]
    assert starts and rides
    log = room.log
    for p in starts:
        if (p.outcome or {}).get("result") != "switched":
            continue
        i = next(i for i, e in enumerate(log) if e[0] == "switch"
                 and abs(e[1] - p.charge_ms) <= STEP)
        assert log[i + 1][:3] == ("member", log[i][1], "charge")
        assert log[i + 1][3] == p.to_scene_id      # the build runs on the new scene
    for p in rides:
        assert p.charge_ms + ds.RIDE_EDGE_MS <= p.ride_ms
        assert (p.outcome or {}).get("at") in (ds.MOMENT_CHARGE_FLARE,
                                               "charge_flare_missed")
        if (p.outcome or {}).get("at") == ds.MOMENT_CHARGE_FLARE:
            i = next(i for i, e in enumerate(log) if e[0] == "switch"
                     and abs(e[1] - p.ride_ms) <= STEP)
            # cut, then the charge carried on at its progress, then the flare
            # on the NEW scene — all on the flare's tick
            assert log[i + 1][0] == "rearm" and log[i + 1][2] == "charge"
            assert 0.0 < log[i + 1][3] < 1.0
            assert log[i + 2] == ("flare", log[i][1], p.to_scene_id)


def test_100_MILLONES_no_longer_plays_its_drops_on_nothing():
    fix, room, _ = _sweep("millones_drop_switch.json", start=None,
                          settings=ds.SwitchSettings(enabled=False))
    assert room.drops() and all(d[3] is None for d in room.drops()[:1])
    fix, room, _ = _sweep("millones_drop_switch.json", start=None)
    first = ds.plans_for(fix["uri"])[0]
    assert first.switch and first.stale_by == (ds.STALE_NOTHING_SHOWING,)
    assert first.moment == ds.MOMENT_CHARGE_START
    drops = room.drops()
    assert drops[0][3] is not None
    assert len({d[3] for d in drops}) >= 3


def test_the_timeline_view_names_each_decision():
    fix, room, _ = _sweep("fina_planned_scene_changes.json", start="fish")
    _f, his, _p = _load("fina_planned_scene_changes.json")
    scfg.DROP_SEQUENCES_FILE.write_text(
        json.dumps({fix["uri"]: fix["drop_sequences_store"]}), encoding="utf-8")
    drop_sequences.reset()
    view = drop_firing.annotate(drop_sequences.view(fix["uri"], triggers=his),
                                "analysed", True)
    drop_sequences.reset()
    named = [s for s in view["sequences"] if s.get("switch")]
    assert named
    for s in named:
        assert s["switch"]["sentence"] and "switch" in s["switch"]
