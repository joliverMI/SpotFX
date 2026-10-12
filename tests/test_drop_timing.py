"""THE DROP TIMING OFFSET (spectra/services/drop_timing.py — the Admiral,
2026-10-12: "Let's start by shifting the drops so they fire 400ms
earlier"). Every test here runs with the REAL offset resolution
(@pytest.mark.drop_timing_live — tests/conftest.py holds it at 0 for the
suites about other timing).

What is proven:
  - the room default is -400 and a scene's own value wins;
  - tick() applies it ONCE, to drops only — his stored drops and the drop
    sequence members — summed with the trigger's and the band's own
    offsets, and a drop fires exactly once (never again at its raw mark);
  - a build ending on a drop is told the gap to the SHIFTED mark, so the
    breath-hold ends exactly on it (stored lull and sequence lull);
  - a drop never relocates to within MIN_BUILD_MS of its own lull;
  - a Fireworks meld's swallow delay is measured from the drop's real fire;
  - the drop-sequence preview's drop mark (the red line) moves, the lull's
    hang and the drop's fire cue move with it, and the live program builds
    the lull over the same shortened gap.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model
from fx.effects import phase_grammar
from spectra.models.trigger import FireResponseAction, SpectraTrigger
from spectra.services import drop_switch, drop_timing
from spectra.services.room_controls import RoomControlState
from spectra.services.trigger_engine import TriggerEngine

pytestmark = pytest.mark.drop_timing_live

URI = "spotify:track:droptiming"


# ── the rule ────────────────────────────────────────────────────────────

def test_the_room_default_is_400_ms_earlier():
    assert RoomControlState().drop_timing_offset_ms == -400
    assert drop_timing.DEFAULT_DROP_OFFSET_MS == -400
    assert drop_timing.resolve_offset_ms(RoomControlState(), None) == -400


def test_a_scene_value_wins_and_none_means_the_room():
    from spectra.models.scene import SceneV2
    room = RoomControlState(drop_timing_offset_ms=-250)
    assert drop_timing.resolve_offset_ms(room, SceneV2(name="a")) == -250
    assert drop_timing.resolve_offset_ms(
        room, SceneV2(name="b", drop_timing_offset_ms=-700)) == -700
    assert drop_timing.resolve_offset_ms(
        room, SceneV2(name="c", drop_timing_offset_ms=0)) == 0


def test_a_drop_never_relocates_onto_its_own_lull():
    assert drop_timing.shift_drop_ms(10_000, -400, 7_000) == 9_600
    # a lull 300 ms ahead: the drop stops MIN_BUILD_MS after it
    assert drop_timing.shift_drop_ms(10_000, -400, 9_700) == 9_700 + drop_timing.MIN_BUILD_MS
    # already closer than the floor: never moved earlier at all
    assert drop_timing.shift_drop_ms(10_000, -400, 9_950) == 10_000
    # later is never clamped
    assert drop_timing.shift_drop_ms(10_000, 300, 9_950) == 10_300
    assert drop_timing.build_gap_ms(7_000, 10_000, "drop", -400) == 2_600
    assert drop_timing.build_gap_ms(7_000, 10_000, None, -400) == 3_000


# ── the trigger clock ──────────────────────────────────────────────────

def _resp(ms, cls, offset=0, tid=None):
    return SpectraTrigger(id=tid or f"{cls}-{ms}", timestamp_ms=ms,
                          trigger_offset_ms=offset,
                          action=FireResponseAction(event_class=cls, intensity=0.8))


class _Rec:
    def __init__(self):
        self.position = 0
        self.resp: list[tuple] = []
        self.seq: list[tuple] = []

    async def fire_response(self, cls, intensity, gap=None):
        self.resp.append((self.position, cls, gap))

    async def fire_sequence(self, cls, intensity, gap):
        self.seq.append((self.position, cls, gap))


async def _noop(_uri):
    return None


def _engine(triggers, rec, *, offset=-400, response_offset=0, view=None):
    kw = {}
    if view is not None:
        kw.update(drop_view=lambda uri, trigs: view, drop_revision=lambda: 0)
    return TriggerEngine(
        list_triggers=lambda uri: list(triggers),
        scene_change_mode=lambda: "full" if view is None else "analysed",
        fire_response=rec.fire_response, fire_sequence=rec.fire_sequence,
        render_intensity=lambda x: x, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: response_offset,
        drop_offset_ms=(None if offset is None else (lambda: offset)),
        sequencer_enabled=lambda: False, transition_intensity=lambda: 0.5,
        select_scene=lambda i: "S", auto_generate=_noop, auto_refresh=_noop,
        **kw)


def _sweep(engine, rec, stop, step=50):
    async def run():
        await engine.on_track_state(URI)
        for pos in range(0, stop + step, step):
            rec.position = pos
            await engine.tick(pos)
    asyncio.run(run())


def test_a_stored_drop_fires_400ms_early_exactly_once():
    rec = _Rec()
    _sweep(_engine([_resp(10_000, "drop")], rec), rec, 12_000)
    drops = [p for p, c, _g in rec.resp if c == "drop"]
    assert drops == [9_600], "fires once, on the shifted mark, never again at 10 s"


def test_flares_charges_and_lulls_are_not_moved():
    rec = _Rec()
    trigs = [_resp(3_000, "charge"), _resp(5_000, "flare"), _resp(7_000, "lull")]
    _sweep(_engine(trigs, rec), rec, 8_000)
    assert [(p, c) for p, c, _g in rec.resp] == [(3_000, "charge"), (5_000, "flare"),
                                                 (7_000, "lull")]


def test_the_offset_sums_with_the_triggers_and_bands_own_offsets_once():
    rec = _Rec()
    _sweep(_engine([_resp(10_000, "drop", offset=-50)], rec, response_offset=-100),
           rec, 12_000)
    assert [p for p, c, _g in rec.resp if c == "drop"] == [10_000 - 50 - 100 - 400]


def test_the_default_reads_the_room_and_the_showing_scene(monkeypatch):
    from spectra.models.scene import SceneV2
    from spectra.services import room_controls
    monkeypatch.setattr(room_controls, "load_room_controls",
                        lambda: RoomControlState(drop_timing_offset_ms=-300))
    scene = {"s": None}
    monkeypatch.setattr(TriggerEngine, "_active_scene", staticmethod(lambda: scene["s"]))
    rec = _Rec()
    _sweep(_engine([_resp(10_000, "drop")], rec, offset=None), rec, 12_000)
    assert [p for p, c, _g in rec.resp if c == "drop"] == [9_700]
    scene["s"] = SceneV2(name="x", drop_timing_offset_ms=-800)
    rec = _Rec()
    _sweep(_engine([_resp(10_000, "drop")], rec, offset=None), rec, 12_000)
    assert [p for p, c, _g in rec.resp if c == "drop"] == [9_200]


def test_a_stored_lull_builds_to_the_shifted_drop_and_its_breath_ends_on_it():
    rec = _Rec()
    trigs = [_resp(7_000, "lull"), _resp(10_000, "drop")]
    _sweep(_engine(trigs, rec), rec, 12_000)
    (lull_at, _c, gap), = [r for r in rec.resp if r[1] == "lull"]
    drop_at = next(p for p, c, _g in rec.resp if c == "drop")
    assert gap == 2_600
    assert lull_at + gap == drop_at == 9_600
    keys = phase_grammar.breath_keys_for(gap / 1000.0, 0.4, 3.0)
    breath_end_s = keys[phase_grammar.BREATH_AT_KEY] + keys[phase_grammar.BREATH_KEY]
    assert lull_at + breath_end_s * 1000 == pytest.approx(drop_at)


def test_a_lull_300ms_ahead_keeps_its_drop_after_it():
    rec = _Rec()
    trigs = [_resp(9_700, "lull"), _resp(10_000, "drop")]
    _sweep(_engine(trigs, rec, offset=-400), rec, 12_000, step=10)
    order = [c for _p, c, _g in rec.resp]
    assert order == ["lull", "drop"]
    lull_at, _c, gap = rec.resp[0]
    drop_at = rec.resp[1][0]
    assert gap == drop_timing.MIN_BUILD_MS
    assert drop_at == 9_700 + drop_timing.MIN_BUILD_MS


def _view():
    return {"uri": URI, "song": {"beat_ms": 500.0},
            "sequences": [{"key": "drop:10000", "state": "confident",
                           "origin": "detected", "tier": "confident",
                           "drop_ms": 10_000, "lull_ms": 7_000, "charge_ms": 3_000,
                           "step": 0.8}],
            "authored": [], "authored_lone": []}


def test_a_drop_sequence_drop_fires_early_and_its_lull_builds_to_it():
    rec = _Rec()
    _sweep(_engine([], rec, view=_view()), rec, 12_000)
    fired = {c: (p, g) for p, c, g in rec.seq}
    assert fired["charge"] == (3_000, 4_000), "the charge builds to its lull, unmoved"
    assert fired["lull"] == (7_000, 2_600)
    assert fired["drop"][0] == 9_600
    assert fired["lull"][0] + fired["lull"][1] == fired["drop"][0]


def test_a_fireworks_meld_swallow_delay_counts_from_the_fired_drop():
    plan = drop_switch.SwitchPlan(
        key="drop:10000", uri=URI, switch=True, reason="stale", sentence="",
        moment=drop_switch.MOMENT_AFTER_DROP, drop_ms=10_000)
    settings = drop_switch.SwitchSettings(swallow_delay_s=1.0)
    assert drop_switch.late_release(plan, settings).release_ms == 11_000
    assert drop_switch.late_release(plan, settings, drop_offset_ms=-400).release_ms == 10_600
    # the trigger clock hands it the offset it applied to that drop
    rec = _Rec()
    eng = _engine([], rec, view=_view())
    eng._switch_settings = lambda: settings
    _sweep(eng, rec, 9_000)
    seq = next(m[0] for m in eng._seq_meta.values())
    eng._switch_plans[seq.key] = plan
    rec.position = 9_600
    asyncio.run(eng.tick(9_600))
    assert eng._drop_applied[seq.trigger_id("drop")] == -400
    eng._switch_plans[seq.key] = plan
    eng._late_pending.pop(seq.key, None)
    eng._arm_late_switch(seq)
    assert eng._late_pending[seq.key].release_ms == 10_600


# ── the drop-sequence preview (the red line) ───────────────────────────

VID = "v1"


@pytest.fixture
def _preview_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    for name, fn in (("SCENES_FILE", "scenes.json"),
                     ("SEQUENCER_FILE", "sequencer.json"),
                     ("DRIFT_PROFILES_FILE", "drift_profiles.json"),
                     ("ROOM_COLOR_FILE", "room_color.json"),
                     ("ROOM_CONTROLS_FILE", "room_controls.json"),
                     ("GRADIENT2D_FILE", "gradients2d.json"),
                     ("COLOR_SETS_FILE", "color_sets.json")):
        monkeypatch.setattr(scfg, name, tmp_path / fn)
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    return tmp_path


def _scene(**kw):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    return SceneV2(name="Phase Scene",
                   devices=[SceneDeviceConfig(id="d1", target_kind="virtual",
                                              target=VID, effect_type="blackhole",
                                              params={})], **kw)


def _set_room(offset):
    from spectra.services import room_controls
    room_controls.save_room_controls(RoomControlState(drop_timing_offset_ms=offset))


def _timeline(scene, gaps=None):
    from spectra.services import phase_preview
    tl = asyncio.run(phase_preview.build_timeline(
        scene, 0.7, gaps=gaps, drop_switch_enabled=False))
    return tl, {m["event_class"]: m for m in tl["marks"]}


def test_the_preview_red_line_moves_400ms_earlier(_preview_storage):
    gaps = {"charge": 4000, "lull": 3000}
    _set_room(0)
    _tl0, on_mark = _timeline(_scene(), gaps)
    _set_room(-400)
    tl, early = _timeline(_scene(), gaps)
    assert {k: tl["drop_timing"][k] for k in ("offset_ms", "applied_ms", "source")} == {
        "offset_ms": -400, "applied_ms": -400, "source": "room"}
    assert early["drop"]["drop_timing_offset_ms"] == -400
    # the red line (mark_s) and the drop's fire cue: 0.4 s earlier than the
    # charge and lull, which stay put relative to each other
    shift = early["charge"]["mark_s"] - on_mark["charge"]["mark_s"]
    assert early["lull"]["mark_s"] - on_mark["lull"]["mark_s"] == pytest.approx(shift)
    assert early["drop"]["mark_s"] - on_mark["drop"]["mark_s"] == pytest.approx(shift - 0.4)
    drop_cue = next(c for c in tl["cues"] if c["step"] == "drop")
    assert drop_cue["at_s"] == pytest.approx(early["drop"]["fire_at_s"])
    # the lull builds to the moved mark: ramp + hang end on the red line
    assert early["lull"]["gap_ms"] == 2600
    assert early["lull"]["hang_end_s"] == pytest.approx(early["drop"]["mark_s"])
    assert tl["gaps"]["lull"] == 3000, "his slider value is reported unchanged"


def test_the_preview_reads_the_scenes_own_value_first(_preview_storage):
    _set_room(-400)
    tl, marks = _timeline(_scene(drop_timing_offset_ms=-900), {"charge": 4000, "lull": 3000})
    assert tl["drop_timing"]["source"] == "scene"
    assert marks["drop"]["drop_timing_offset_ms"] == -900
    assert marks["lull"]["gap_ms"] == 2100


def test_the_live_preview_program_builds_the_lull_over_the_same_gap(_preview_storage):
    from spectra.services import phase_preview
    _set_room(-400)
    program = phase_preview.PhaseSequenceProgram(_scene(), {"charge": 4000, "lull": 3000})
    assert program.gaps["lull"] == 2600
    assert program.gaps["charge"] == 4000
