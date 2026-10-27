"""THE PRE-DROP ON THE SHOW CLOCK (predrop plan step 5's acceptance): the
pre-drop lands within one 12 ms frame of its mark, and the colour change
starts on it and lands on the drop (an instant change on a drop without
one), in a show-clock test with a late lull.

The REAL TriggerEngine.tick() is driven over a 200 ms position feed (the
show clock's own cadence, TICK_S). Its lull member's fire reaches a real
ResponseEngine (a scratch pair on a RecordingExecutor), which decides the
pre-drop against the scene showing; Black Hole (not a member of
fx.device_model.PRE_DROP_EFFECTS) is made a stub member so the told keys
can be read off its arm. The drop's colour change is the engine's hook, recorded with
the show-clock position it was asked at.

The lull's MARK sits between two ticks, so it fires late — and the told
`pre_drop_at_s`, measured from where the lull ACTUALLY fired, still puts
the pre-drop on its own mark: fire position + pre_drop_at_s == the
pre-drop's target, moved with its drop by the drop timing offset.
"""
from __future__ import annotations

import asyncio
from random import Random

import pytest

from fx import device_model
from spectra.models.scene import SceneV2
from spectra.models.trigger import FireResponseAction, SpectraTrigger
from spectra.services import drop_switch, trigger_engine as te_mod
from spectra.services.trigger_engine import TriggerEngine

URI = "spotify:track:pre-drop-clock"
BEAT = 500.0
FRAME_MS = 12          # one stored audio-shape frame (api/audio_capture.py)


async def _noop(*_a, **_k):
    return None


class _Plan:
    flares: list = []
    scene_cues: list = []


def _seq(drop, lull, charge=None, pre=None, kind="spike", tier="confident"):
    s = {"key": f"drop:{drop}", "state": "confident", "origin": "detected",
         "drop_ms": drop, "lull_ms": lull, "charge_ms": charge,
         "tier": "confident", "step": 0.8,
         "parts": {"charge": "waiting", "lull": "waiting",
                   "pre_drop": "waiting", "drop": "waiting"}}
    if pre is not None:
        s.update(pre_drop_ms=pre, pre_drop_kind=kind, pre_drop_tier=tier)
    return s


def _view(seqs=(), authored=()):
    def fn(uri, triggers):
        return {"uri": URI, "status": "detected", "song": {"beat_ms": BEAT},
                "sequences": [dict(s) for s in seqs],
                "authored": [dict(g) for g in authored], "authored_lone": [],
                "excluded": [], "counts": {}}
    return fn


class Rig:
    def __init__(self, view, *, triggers=(), mode="analysed", drop_offset=0,
                 scene=None):
        from spectra.services import color_journey as cj
        from spectra.services import room_controls as rc
        from spectra.services import scene_response
        from spectra.services.drift_conductor import DriftConductor
        from spectra.services.fx_executor import RecordingExecutor
        self.scene = scene or SceneV2(name="Black Hole", devices=[
            {"target_kind": "category", "target": "Matrix",
             "effect_type": "blackhole"}])
        room = [cj.RoomColorState()]
        controls = rc.RoomControlState()
        self.now = [0.0]
        self.executor = RecordingExecutor(clock=lambda: self.now[0],
                                          room_controls_load=lambda: controls)
        conductor = DriftConductor(
            executor=self.executor, clock=lambda: self.now[0],
            drift_profiles=lambda: {}, curve_profiles=lambda: {},
            room_load=lambda: room[0], room_save=lambda st: room.__setitem__(0, st),
            set_cards=lambda: [], gradient_profiles=lambda: {},
            room_controls=lambda: controls, rng=Random(3))
        self.responder = scene_response.ResponseEngine(
            conductor=conductor, executor=self.executor, rng=Random(5),
            clock=lambda: self.now[0], curve_profiles=lambda: {},
            room_load=lambda: room[0], room_save=lambda st: room.__setitem__(0, st),
            room_controls=lambda: controls, room_energy=lambda: 0.85)
        self.responder.lull_handoff_resolver = scene_response.default_lull_handoff
        conductor.on_scene_fire(self.scene, [
            {"virtual_id": "matrix", "effect_type": d.effect_type, "config": {},
             "entry_id": d.id, "color_mode": "set"} for d in self.scene.devices])
        self.fires: list[dict] = []
        self.colour: list[dict] = []

        async def fire(cls, intensity, gap, pre_drop=None, *, source):
            self.fires.append({"cls": cls, "at": self.engine._last_position_ms,
                               "gap": gap, "pre_drop": pre_drop,
                               "source": source})
            return await self.responder.on_event(
                cls, intensity, gap, anchor_relocated=True, pre_drop=pre_drop)

        async def fire_sequence(cls, intensity, gap, pre_drop=None):
            return await fire(cls, intensity, gap, pre_drop, source="sequence")

        async def fire_response(cls, intensity, gap, pre_drop=None):
            return await fire(cls, intensity, gap, pre_drop, source="his")

        async def drop_colour(selection, pool, ramp_ms, moment, analysed):
            self.colour.append({"at": self.engine._last_position_ms,
                                "ramp_ms": ramp_ms, "moment": moment})
            return {"result": "jumped", "moment": moment, "ramp_ms": ramp_ms}

        self.engine = TriggerEngine(
            list_triggers=lambda uri: list(triggers),
            scene_change_mode=lambda: mode, drop_view=view,
            drop_revision=lambda: 1, drop_testing=lambda: False,
            fire_sequence=fire_sequence, fire_response=fire_response,
            drop_colour=drop_colour,
            switch_settings=lambda: drop_switch.SwitchSettings(enabled=False),
            switch_showing=lambda: None, switch_blocker=lambda: None,
            analysed_plan=lambda uri, stored: _Plan(), fire_analysed_flare=_noop,
            fire_scene=_noop, render_intensity=lambda x: x, lead_ms=lambda t: 0,
            response_offset_ms=lambda a: 0, drop_offset_ms=lambda: drop_offset,
            sequencer_enabled=lambda: False, auto_generate=_noop,
            auto_refresh=_noop)

    def sweep(self, stop=24_000, step=200, start=0):
        async def run():
            await self.engine.on_track_state(URI)
            for pos in range(start, stop + 1, step):
                self.now[0] = pos / 1000.0
                await self.engine.tick(pos)
        asyncio.run(run())

    def lull_arm(self):
        return next(w for w in self.executor.writes
                    if w["kind"] == "jump" and w["params"].get("phase") == "lull")


@pytest.fixture
def member(monkeypatch):
    monkeypatch.setattr(device_model, "PRE_DROP_EFFECTS", frozenset({"blackhole"}))
    real = device_model.pre_drop_looks
    looks = {"looks": {"ring": {"label": "Infall ring", "kinds": ["spike", "intro"]}},
             "auto": {"spike": "ring", "intro": "ring"}}
    monkeypatch.setattr(device_model, "pre_drop_looks",
                        lambda et: looks if et == "blackhole" else real(et))


def test_a_late_lull_still_lands_the_pre_drop_on_its_mark(member):
    """Lull mark 16 100 ms (between ticks: it fires on the 16 200 tick, 100 ms
    late), pre-drop 19 300, drop 20 000, the room's drop timing offset
    -100 ms moving both: the pre-drop's target is 19 200, the drop's 19 900."""
    rig = Rig(_view([_seq(20_000, 16_100, 12_000, pre=19_300)]), drop_offset=-100)
    rig.sweep()
    lull = next(f for f in rig.fires if f["cls"] == "lull")
    assert lull["at"] == 16_200, "the lull fired one tick late"
    cand = lull["pre_drop"]
    assert (cand.at_ms, cand.gap_ms, cand.kind) == (3000, 700, "spike")
    arm = rig.lull_arm()["params"]
    lands = lull["at"] + arm["pre_drop_at_s"] * 1000
    assert abs(lands - 19_200) <= FRAME_MS, "on its own mark, whatever the lull's lateness"
    assert lands == pytest.approx(19_200, abs=1e-6)
    assert arm["pre_drop_s"] == pytest.approx(0.7), "the music's gap"
    assert arm["lull_breath_at_s"] + arm["lull_breath_s"] == pytest.approx(
        arm["pre_drop_at_s"]), "the breath ends on the pre-drop"


def test_the_colour_change_starts_on_the_pre_drop_and_lands_on_the_drop(member):
    rig = Rig(_view([_seq(20_000, 16_100, 12_000, pre=19_300)]), drop_offset=-100)
    rig.sweep()
    [fade] = [c for c in rig.colour if c["moment"] == "pre_drop"]
    # one trigger tick BEFORE the pre-drop's target (19 200): his "on
    # (before) the pre-drop" — never after it
    assert 19_200 - te_mod.PRE_DROP_COLOUR_LEAD_MS <= fade["at"] < 19_200
    assert fade["at"] == 19_000
    assert fade["at"] + fade["ramp_ms"] == 19_900, "lands on the drop's target"
    assert not [c for c in rig.colour if c["moment"] == "drop"], \
        "one colour change per drop"
    drop = next(f for f in rig.fires if f["cls"] == "drop")
    assert drop["at"] == 20_000


def test_a_drop_without_a_pre_drop_changes_instantly_on_the_drop(member):
    rig = Rig(_view([_seq(20_000, 16_100, 12_000)]), drop_offset=-100)
    rig.sweep()
    assert [(c["moment"], c["at"], c["ramp_ms"]) for c in rig.colour] == [
        ("drop", 20_000, 0)]
    arm = rig.lull_arm()["params"]
    assert arm["pre_drop_at_s"] == 0.0 and arm["pre_drop_kind"] == ""
    lull = next(f for f in rig.fires if f["cls"] == "lull")
    assert lull["pre_drop"] is None


def test_a_pre_drop_the_scene_does_not_play_leaves_the_drop_instant(member):
    scene = SceneV2(name="Black Hole", devices=[
        {"target_kind": "category", "target": "Matrix", "effect_type": "blackhole"}],
        pre_drop_spike={"enabled": False, "min_ms": 350, "max_ms": 2000})
    rig = Rig(_view([_seq(20_000, 16_100, 12_000, pre=19_300)]), scene=scene)
    rig.sweep()
    assert [c["moment"] for c in rig.colour] == ["drop"]
    assert rig.engine.status()["pre_drops"]["drop:20000"]["reason"] == "kind_off"
    arm = rig.lull_arm()["params"]
    assert arm["pre_drop_at_s"] == 0.0


def test_a_scene_of_non_members_still_fades_the_colour_and_tells_nobody():
    """A scene whose effects have no pre-drop look (Black Hole, until step
    7): the pre-drop still plays (its verdict is the scene's), so the colour
    fades across it — and the lull arm is today's, with no pre-drop key at
    all."""
    assert "blackhole" not in device_model.PRE_DROP_EFFECTS
    rig = Rig(_view([_seq(20_000, 16_000, 12_000, pre=19_200)]))
    rig.sweep()
    assert [c["moment"] for c in rig.colour] == ["pre_drop"]
    arm = rig.lull_arm()["params"]
    assert not any(k.startswith("pre_drop") for k in arm)
    assert arm["lull_breath_at_s"] + arm["lull_breath_s"] == pytest.approx(4.0), \
        "Black Hole's breath ends on the drop, as today"


def test_a_rewind_tells_the_pre_drop_again(member):
    rig = Rig(_view([_seq(20_000, 16_000, 12_000, pre=19_200)]))

    async def run():
        await rig.engine.on_track_state(URI)
        for pos in list(range(0, 21_001, 200)) + list(range(10_000, 21_001, 200)):
            rig.now[0] = pos / 1000.0
            await rig.engine.tick(pos)
    asyncio.run(run())
    assert len([c for c in rig.colour if c["moment"] == "pre_drop"]) == 2
    assert len([f for f in rig.fires if f["cls"] == "lull"]) == 2


# ── his own grouped charge/lull/drop ──────────────────────────────────────

def _his(lull_ms=16_100, drop_ms=20_000, pre_ms=19_300, kind="intro",
         part="on", tier=None):
    triggers = [
        SpectraTrigger(id="his-lull", timestamp_ms=lull_ms, source="authored",
                       action=FireResponseAction(event_class="lull", intensity=0.7)),
        SpectraTrigger(id="his-drop", timestamp_ms=drop_ms, source="authored",
                       action=FireResponseAction(event_class="drop", intensity=0.9)),
    ]
    group = {"lull": {"id": "his-lull", "timestamp_ms": lull_ms},
             "drop": {"id": "his-drop", "timestamp_ms": drop_ms},
             "pre_drop": {"ms": pre_ms, "kind": kind, "off": False,
                          "part": part, "tier": tier}}
    return triggers, group


def test_his_own_lull_carries_his_grouped_pre_drop(member):
    triggers, group = _his()
    rig = Rig(_view(authored=[group]), triggers=triggers, mode="full",
              drop_offset=-100)
    rig.sweep()
    lull = next(f for f in rig.fires if f["cls"] == "lull")
    assert lull["source"] == "his" and lull["at"] == 16_200
    cand = lull["pre_drop"]
    assert (cand.kind, cand.gap_ms, cand.key) == ("intro", 700, "his:his-drop")
    assert lull["at"] + cand.at_ms == 19_200, "moved with his drop"
    arm = rig.lull_arm()["params"]
    assert arm["pre_drop_kind"] == "intro" and arm["pre_drop_look"] == "ring"
    [fade] = [c for c in rig.colour if c["moment"] == "pre_drop"]
    assert fade["at"] + fade["ramp_ms"] == 19_900
    assert not [c for c in rig.colour if c["moment"] == "drop"], \
        "his drop does not change colour again"


def test_his_waiting_suggested_pre_drop_waits(member):
    triggers, group = _his(part="waiting", tier="suggested")
    rig = Rig(_view(authored=[group]), triggers=triggers, mode="full")
    rig.sweep()
    lull = next(f for f in rig.fires if f["cls"] == "lull")
    assert lull["pre_drop"] is None
    assert [c["moment"] for c in rig.colour] == ["drop"]
