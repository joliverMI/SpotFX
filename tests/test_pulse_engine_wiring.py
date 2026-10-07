"""Pulse wired into the engine (single-led-power plan, phase 2).

What is proven here, each on the real code it names:

- THE FEED (spectra/services/pulse_feed.py): a song's sections land in song
  time with their generated-cue intensity, scaled through the show's own
  render seam; the tick pushes ONLY a changed value (a section edge, a new
  song), only to one-colour virtuals, and moves the conductor's baseline so
  the parameter watchdog agrees; a deferred conductor stands it down.
- A SCENE FIRE that installs Pulse carries the section's values, and a
  Power scene's fire is byte-identical to before.
- THE COLOUR (scene_compiler.set_entries_for): his own Singles colour is
  kept; a set with none, or a rainbow set, gives Pulse the strips' first
  colour; a Power virtual is never touched.
- THE SHARED CLOCK, on the real render pipeline (fx.headless, the real
  ResponseEngine + FacadeExecutor): a lull takes Pulse to black on the same
  frame the strip's ramp completes, and the drop bursts on the first frame
  after its mark; the eased intensity a push starts.
- THE HOUSE LAYER stays in force after the effect: a level and a dark state
  at the device apply to Pulse's light, and a resting house look withholds
  the lull so true black happens only during a music show.
- THE TEST SCENE seeder: a copy with Pulse on the Singles, every other scene
  byte-identical, no sequencer entry.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from random import Random

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, device_output, facade, headless  # noqa: E402
from spectra.services import pulse_feed  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services.color_sets import (ColorSetCard, ColorSetEntry,  # noqa: E402
                                         SetScope)

STRIP_V, SINGLE_V, HUES_V, MATRIX_V = "strips-v", "singles-v", "hues-v", "matrix-v"
STRIP_DEV, SINGLE_DEV = "strip-dev", "single-dev"
URI = "spotify:track:pulse-wiring"
FPS = 60
DT = 1.0 / FPS


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def categories(tmp_path, monkeypatch):
    path = tmp_path / "device_categories.json"
    path.write_text(json.dumps({
        "m": {"id": "m", "name": "Matrix", "parent_id": None,
              "virtuals": [MATRIX_V], "effects": [], "role": None},
        "s": {"id": "s", "name": "Strips", "parent_id": None,
              "virtuals": [STRIP_V], "effects": [], "role": None},
        "g": {"id": "g", "name": "Singles", "parent_id": None,
              "virtuals": [SINGLE_V, HUES_V], "effects": [], "role": "ambient"},
    }))
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", path)
    device_model.refresh()
    yield
    device_model.refresh()


# ── a fake song ─────────────────────────────────────────────────────────────

SECTIONS = [  # WAV frame, as librosa stores them; long enough for the
    # generator's 15 s edge trim to leave a middle that sets the stretch
    {"start_ms": 0, "end_ms": 30_000, "energy_rms": 0.20},
    {"start_ms": 30_000, "end_ms": 60_000, "energy_rms": 0.40},
    {"start_ms": 60_000, "end_ms": 90_000, "energy_rms": 0.90},
    {"start_ms": 90_000, "end_ms": 120_000, "energy_rms": 0.30},
    {"start_ms": 120_000, "end_ms": 150_000, "energy_rms": 0.60},
    {"start_ms": 150_000, "end_ms": 180_000, "energy_rms": 0.10},
]
OFFSET_MS = 4_000        # the capture started 4 s into the song
BPM = 120.0


@pytest.fixture
def song(monkeypatch):
    from spectra.services import analysis_reader, testbed_audio
    monkeypatch.setattr(analysis_reader, "sections_for_uri",
                        lambda uri: list(SECTIONS) if uri == URI else None)
    monkeypatch.setattr(analysis_reader, "tempo_bpm_for_uri",
                        lambda uri: BPM if uri == URI else None)
    monkeypatch.setattr(testbed_audio, "capture_offset_ms_or_zero",
                        lambda uri: OFFSET_MS if uri == URI else 0)
    return URI


def _measured():
    from spectra.services import midsong_generator
    return midsong_generator.section_intensities(SECTIONS)


def _feed(factor=1.0, calls=None):
    def fac(uri, genres):
        if calls is not None:
            calls.append(uri)
        return factor
    return pulse_feed.PulseFeed(factor=fac)


# ── the feed's values ───────────────────────────────────────────────────────

def test_a_song_lands_in_song_time_with_its_cue_intensity(song):
    s = pulse_feed.load_song(URI)
    assert [(a, b) for a, b, _m in s.sections] == [
        (sec["start_ms"] + OFFSET_MS, sec["end_ms"] + OFFSET_MS)
        for sec in SECTIONS]
    measured = [m for _a, _b, m in s.sections]
    assert measured == _measured()
    assert len(set(measured)) >= 4                   # a real spread
    assert s.beat_ms == pytest.approx(500.0)


def test_energy_is_the_render_intensity_a_cue_at_that_section_fires_at(song):
    from spectra.services import intensity_scale
    f = _feed(factor=1.2)
    _run(f.prepare(URI))
    measured = _measured()
    for pos, idx in ((40_000, 1), (80_000, 2), (110_000, 3)):
        v = f.values(URI, pos)
        assert v["energy"] == pytest.approx(
            intensity_scale.combine_measured_and_scale(measured[idx], 1.2), abs=1e-3)
        assert v["beat_ms"] == pytest.approx(500.0)
    # the automatic ceiling holds: never above HEADROOM_RESERVE x factor
    assert f.values(URI, 80_000)["energy"] == pytest.approx(0.6 * 1.2, abs=1e-3)


def test_an_implausible_tempo_is_fed_as_unknown(song, monkeypatch):
    from spectra.services import analysis_reader
    monkeypatch.setattr(analysis_reader, "tempo_bpm_for_uri", lambda uri: 9.0)
    assert pulse_feed.load_song(URI).beat_ms == 0.0   # 6667 ms: off the schema


def test_before_the_capture_began_the_nearest_section_speaks(song):
    f = _feed()
    _run(f.prepare(URI))
    assert f.values(URI, 1_000) == f.values(URI, 10_000)


def test_a_song_with_no_analysis_is_fed_neutral():
    f = _feed()
    _run(f.prepare("spotify:track:unknown"))
    assert f.values("spotify:track:unknown", 5_000) == {
        "energy": pulse_feed.NEUTRAL_ENERGY, "beat_ms": 0.0}


def test_the_factor_is_read_once_per_section_not_per_tick(song):
    calls: list = []
    f = _feed(calls=calls)
    _run(f.prepare(URI))
    for pos in range(34_500, 63_500, 250):         # one whole section
        f.values(URI, pos)
    assert len(calls) == 1
    f.values(URI, 70_000)                          # the next section
    assert len(calls) == 2


def test_values_need_the_table_loaded():
    f = _feed()
    assert f.values(URI, 10_000) is None
    assert f.values(None, 10_000) is None


# ── the tick ────────────────────────────────────────────────────────────────

def _conductor(effects: dict[str, str]):
    from spectra.models.scene import SceneV2
    from spectra.services import color_journey as cj
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor
    room = [cj.RoomColorState()]
    ex = RecordingExecutor(room_controls_load=lambda: rc.RoomControlState())
    c = DriftConductor(
        executor=ex, drift_profiles=lambda: {}, curve_profiles=lambda: {},
        room_load=lambda: room[0], room_save=lambda st: room.__setitem__(0, st),
        set_cards=lambda: [], gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(1))
    c.on_scene_fire(SceneV2(name="t"), [
        {"virtual_id": vid, "effect_type": et, "config": {"gradient": "#ff0000"},
         "entry_id": "", "color_mode": "set"} for vid, et in effects.items()])
    return c


def _pushes(c):
    return [(w["virtual_id"], dict(w["params"])) for w in c.executor.writes]


def test_the_tick_pushes_only_to_one_colour_virtuals(song):
    c = _conductor({SINGLE_V: "pulse", HUES_V: "pulse", STRIP_V: "orbits1d"})
    f = _feed()
    assert _run(f.tick(URI, 80_000, conductor=c)) == 2
    pushed = _pushes(c)
    assert {vid for vid, _p in pushed} == {SINGLE_V, HUES_V}
    e0 = f.values(URI, 80_000)["energy"]
    assert pushed[0][1] == {"energy": e0, "beat_ms": 500.0}
    # the baseline moved: what the watchdog compares against IS the push
    assert c.virtuals[SINGLE_V].param_baseline["energy"] == e0
    assert c.virtuals[SINGLE_V].param_baseline["beat_ms"] == 500.0


def test_the_tick_pushes_a_value_once_then_again_at_the_section_edge(song):
    c = _conductor({SINGLE_V: "pulse"})
    f = _feed()
    for pos in range(34_500, 63_900, 250):
        _run(f.tick(URI, pos, conductor=c))
    assert len(c.executor.writes) == 1               # one section, one push
    _run(f.tick(URI, 64_100, conductor=c))           # crossed into the next
    assert len(c.executor.writes) == 2
    assert _pushes(c)[-1][1] == {"energy": f.values(URI, 64_100)["energy"]}


def test_a_deferred_conductor_stands_the_feed_down_then_it_catches_up(song):
    c = _conductor({SINGLE_V: "pulse"})
    f = _feed()
    assert _run(f.tick(URI, 10_000, conductor=c, deferral="preview")) == 0
    assert not c.executor.writes and f.status()["deferred_by"] == "preview"
    assert _run(f.tick(URI, 10_000, conductor=c)) == 1


def test_no_one_colour_virtual_means_no_write_and_no_load(song):
    loads: list = []
    c = _conductor({STRIP_V: "orbits1d", SINGLE_V: "power"})
    f = pulse_feed.PulseFeed(loader=lambda uri: loads.append(uri)
                             or pulse_feed.load_song(uri))
    assert _run(f.tick(URI, 10_000, conductor=c)) == 0
    assert not c.executor.writes and not loads


# ── the scene fire ──────────────────────────────────────────────────────────

def test_the_overlay_adds_values_to_pulse_writes_without_touching_shared_config(song):
    f = _feed()
    _run(f.prepare(URI))
    shared = {"gradient": "#00ff00"}
    writes = [{"virtual_id": SINGLE_V, "effect_type": "pulse", "config": shared},
              {"virtual_id": STRIP_V, "effect_type": "orbits1d", "config": shared}]
    out = f.overlay(writes, URI, 80_000)
    assert out[0]["config"] == {"gradient": "#00ff00",
                                **f.values(URI, 80_000)}
    assert out[1] is writes[1]
    assert shared == {"gradient": "#00ff00"}
    # no Pulse in the fire, or the song not known yet: unchanged
    power = [{"virtual_id": SINGLE_V, "effect_type": "power", "config": {}}]
    assert f.overlay(power, URI, 80_000) is power
    assert _feed().overlay(writes, URI, 80_000) is writes


def _scene(effect: str):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    return SceneV2(name=f"with {effect}", devices=[
        SceneDeviceConfig(target_kind="category", target="Strips",
                          effect_type="orbits1d", params={}),
        SceneDeviceConfig(target_kind="category", target="Singles",
                          effect_type=effect, params={})])


def _live_fire(monkeypatch, scene, card):
    from spectra.services import engine, fx_seam, scene_compiler
    sent: list = []

    async def apply_writes(writes, transition_ms=0):
        sent.extend(writes)
    monkeypatch.setattr(fx_seam, "apply_writes", apply_writes)
    monkeypatch.setattr(engine.bridge, "track_uri", lambda: URI)
    monkeypatch.setattr(engine.bridge, "effective_position_ms", lambda: 80_000)
    monkeypatch.setattr(engine.bridge, "track_genres", lambda: [])
    monkeypatch.setattr(engine, "on_scene_fired", lambda *a, **k: None)
    _run(scene_compiler.fire_scene(scene, color_set=card, dry_run=False))
    return {w["virtual_id"]: w for w in sent}


def test_a_fire_that_installs_pulse_starts_it_where_the_song_is(
        categories, song, monkeypatch):
    _run(pulse_feed.feed.prepare(URI))
    card = ColorSetCard(id="c", name="c", entries=[])
    sent = _live_fire(monkeypatch, _scene("pulse"), card)
    want = pulse_feed.feed.values(URI, 80_000)
    for vid in (SINGLE_V, HUES_V):
        assert sent[vid]["config"]["energy"] == want["energy"]
        assert sent[vid]["config"]["beat_ms"] == want["beat_ms"]
    assert "energy" not in sent[STRIP_V]["config"]


def test_a_power_fire_is_unchanged_by_the_feed(categories, song, monkeypatch):
    from spectra.services import scene_compiler
    _run(pulse_feed.feed.prepare(URI))
    card = _card(singles="#123456")
    sent = _live_fire(monkeypatch, _scene("power"), card)
    dry = _run(scene_compiler.fire_scene(_scene("power"), color_set=card,
                                         dry_run=True))
    assert [sent[w["virtual_id"]]["config"] for w in dry["writes"]] == [
        w["config"] for w in dry["writes"]]


# ── the colour ──────────────────────────────────────────────────────────────

STRIPS_GRADIENT = "linear-gradient(90deg, #0000ff 100.00%,#ff00b3 21.00%)"


def _card(*, singles=None, strips=STRIPS_GRADIENT, rainbow=False, **kw):
    entries = [ColorSetEntry(scope=SetScope(categories=["Strips"]),
                             color_kind="gradient", color_value=strips,
                             bg_color="#ff9940", brightness=1.0)]
    if singles is not None:
        entries.append(ColorSetEntry(
            scope=SetScope(categories=["Singles"]), color_kind="solid",
            color_value=singles, bg_color="#202020", brightness=0.8,
            background_brightness=0.3))
    return ColorSetCard(id="card", name="card", entries=entries,
                        is_rainbow=rainbow, **kw)


def test_a_set_with_no_singles_colour_gives_pulse_the_strips_first_colour(categories):
    from spectra.services import scene_compiler
    by_vid = scene_compiler.set_entries_for(
        _card(), {SINGLE_V: "pulse", HUES_V: "power", STRIP_V: "orbits1d"})
    # the first colour by POSITION (21%), not the first written
    assert by_vid[SINGLE_V].color_value == "#ff00b3"
    assert by_vid[SINGLE_V].bg_color is None and by_vid[SINGLE_V].brightness is None
    assert HUES_V not in by_vid                     # Power keeps what it wore


def test_his_own_singles_colour_is_kept(categories):
    from spectra.services import scene_compiler
    card = _card(singles="#00ff88")
    by_vid = scene_compiler.set_entries_for(card, {SINGLE_V: "pulse"})
    assert by_vid[SINGLE_V] == scene_compiler._set_entry_by_virtual(card)[SINGLE_V]


@pytest.mark.parametrize("card", [
    _card(singles="#800080", rainbow=True),
    _card(singles="#800080",
          strips="linear-gradient(90deg, #ff0000 0%,#00ff00 50%,#0000ff 100%)"),
])
def test_a_rainbow_set_gives_pulse_the_strips_gradient_but_keeps_his_brightness(
        categories, card):
    """Phase 3: in a rainbow set Pulse takes the strips' WHOLE gradient (it
    walks along it on hits — tests/test_pulse_rainbow_flares.py), not just
    its first colour; his own brightness stands."""
    from spectra.services import scene_compiler
    by_vid = scene_compiler.set_entries_for(card, {SINGLE_V: "pulse",
                                                   HUES_V: "power"})
    strips = card.entries[0].color_value
    assert by_vid[SINGLE_V].color_value == strips
    assert by_vid[SINGLE_V].color_kind == "gradient"
    assert by_vid[SINGLE_V].brightness == 0.8
    assert by_vid[HUES_V].color_value == "#800080"   # Power: his pick, as ever


def test_the_compiler_writes_the_fill_and_no_background(categories):
    from spectra.services import scene_compiler
    writes = {w["virtual_id"]: w for w in scene_compiler.compile_scene(
        _scene("pulse"), _card())}
    assert writes[SINGLE_V]["config"]["gradient"] == "#ff00b3"
    assert "background_color" not in writes[SINGLE_V]["config"]
    assert writes[STRIP_V]["config"]["gradient"] == STRIPS_GRADIENT


def test_a_power_scene_compiles_byte_identically(categories):
    from spectra.services import scene_compiler
    for card in (_card(), _card(singles="#00ff88"), _card(singles="#1", rainbow=True)):
        by_vid = scene_compiler._set_entry_by_virtual(card)
        assert scene_compiler.set_entries_for(
            card, {SINGLE_V: "power", HUES_V: "power", STRIP_V: "orbits1d"}) == by_vid


def test_a_set_landing_on_the_live_scene_fills_pulse_and_the_journey_turns_it(categories):
    c = _conductor({SINGLE_V: "pulse", STRIP_V: "orbits1d"})
    _run(c.apply_color_set(_card()))
    assert c.virtuals[SINGLE_V].gradient == "#ff00b3"
    assert c.virtuals[SINGLE_V].set_mode            # the journey rotates set-mode
    params = {w["virtual_id"]: w["params"] for w in c.executor.writes}
    assert params[SINGLE_V] == {"gradient": "#ff00b3"}


# ── the shared clock, on the real render pipeline ──────────────────────────

def _two_light_config(config_dir):
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    devices = [{"id": STRIP_DEV, "type": "dummy",
                "config": {"name": STRIP_DEV, "pixel_count": 30}},
               {"id": SINGLE_DEV, "type": "dummy",
                "config": {"name": SINGLE_DEV, "pixel_count": 1}}]
    virtuals = [{"id": vid, "is_device": False, "auto_generated": False,
                 "config": {"name": vid, "mapping": "span", "rows": 1},
                 "segments": [[dev, 0, n - 1, False]]}
                for vid, dev, n in ((STRIP_V, STRIP_DEV, 30),
                                    (SINGLE_V, SINGLE_DEV, 1))]
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": devices, "virtuals": virtuals}, fh)


class _Room:
    """A strip running orbits1d and one Single running Pulse on one real
    host, the production ResponseEngine on the FacadeExecutor, one clock."""

    def __init__(self, host, clock):
        from spectra.models.scene import SceneV2
        from spectra.services import color_journey as cj
        from spectra.services.drift_conductor import DriftConductor
        from spectra.services.fx_executor import FacadeExecutor
        from spectra.services.scene_response import ResponseEngine
        self.clock = clock
        self.host = host
        self.strip_v = host.virtuals.get(STRIP_V)
        self.single_v = host.virtuals.get(SINGLE_V)
        self.strip = headless.attach_effect(host, self.strip_v, "orbits1d", {})
        self.pulse = headless.attach_effect(
            host, self.single_v, "pulse",
            {"gradient": "#ff0000", "beat_ms": 500.0, "energy": 0.5})
        room = [cj.RoomColorState()]
        self.executor = FacadeExecutor(
            clock=lambda: clock.now,
            room_controls_load=lambda: rc.RoomControlState())
        self.conductor = DriftConductor(
            executor=self.executor, clock=lambda: clock.now,
            drift_profiles=lambda: {}, curve_profiles=lambda: {},
            room_load=lambda: room[0],
            room_save=lambda st: room.__setitem__(0, st), set_cards=lambda: [],
            gradient_profiles=lambda: {},
            room_controls=lambda: rc.RoomControlState(), rng=Random(3))
        self.responder = ResponseEngine(
            conductor=self.conductor, executor=self.executor, rng=Random(5),
            clock=lambda: clock.now, curve_profiles=lambda: {},
            room_load=lambda: room[0],
            room_save=lambda st: room.__setitem__(0, st))
        self.conductor.on_scene_fire(SceneV2(name="room"), [
            {"virtual_id": STRIP_V, "effect_type": "orbits1d", "config": {},
             "entry_id": "", "color_mode": "set"},
            {"virtual_id": SINGLE_V, "effect_type": "pulse",
             "config": {"energy": 0.5, "beat_ms": 500.0}, "entry_id": "",
             "color_mode": "set"}])
        self.single_frames: list[np.ndarray] = []

    def step(self, n=1):
        for _ in range(n):
            self.clock.advance(DT)
            for v in (self.strip_v, self.single_v):
                frame = v.assemble_frame()
                if frame is not None:
                    v.flush(frame)
                    if v is self.single_v:
                        self.single_frames.append(np.array(frame, copy=True))

    def strip_progress(self) -> float:
        return float(self.strip._config.get("phase_progress", 0.0))


def _with_room(tmp_path, script):
    async def main():
        config_dir = str(tmp_path / "fx-room")
        _two_light_config(config_dir)
        headless.silence_audio()
        from fx.host import FxHost
        host = FxHost(config_dir)
        await host.start()
        host.audio = headless.SyntheticAudioSource()
        facade.set_host(host)
        try:
            with headless.fake_clock() as clock:
                room = _Room(host, clock)
                room.step(30)
                return await script(room)
        finally:
            facade.set_host(None)
            await host.shutdown()
    return _run(main())


def test_a_lull_reaches_black_at_the_shared_lull_dark_point(tmp_path):
    """Pulse is pitch black from the lull's DARK POINT — the shared rule the
    crystal uses (fx/effects/lull_dark.py, 2026-10-07): dark for half the
    lull, never longer than lull_dark_max_s. A 3 s gap is short, so that is
    half way: black from 1.5 s, while the strip's own ramp (orbits1d, not a
    lull-dark effect) still runs to 90% of the gap, untouched. Before the
    rule Pulse went black on the frame the strips' ramp completed."""
    GAP_MS = 3_000                    # ramp = 90% = 2700 ms, the shared rule

    async def script(room):
        await room.responder.on_event("charge", 0.7, gap_ms=4_000)
        room.step(60)
        rec = await room.responder.on_event("lull", 0.5, gap_ms=GAP_MS)
        assert set(rec["phase"]["targets"]) == {STRIP_V, SINGLE_V}
        assert rec["phase"]["ramp_ms"] == 2_700
        assert rec["phase"]["lull_dark_s"] == pytest.approx(1.5)
        strip_done = pulse_black = None
        mid_level = None
        blacks = []
        for i in range(1, 260):
            room.step()
            if i == 45:
                mid_level = room.pulse.level
            if strip_done is None and room.strip_progress() >= 1.0 - 1e-9:
                strip_done = i
            if pulse_black is None and room.pulse.level <= 1e-9:
                pulse_black = i
            blacks.append(room.pulse.level <= 1e-9)
        return strip_done, pulse_black, mid_level, blacks, room

    strip_done, pulse_black, mid_level, blacks, room = _with_room(
        tmp_path, script)
    assert strip_done is not None and pulse_black is not None
    assert abs(pulse_black - 1.5 * FPS) <= 2         # half of the 3 s lull
    assert all(blacks[pulse_black - 1:])             # and it stays black
    assert abs(strip_done - 2_700 / 1000 * FPS) <= 2  # strip: 90% of the gap
    assert mid_level > 0.02                          # not black early
    assert np.all(room.single_frames[-1] == 0)       # true black at the light


def test_the_drop_bursts_on_the_first_frame_after_its_mark(tmp_path):
    async def script(room):
        await room.responder.on_event("lull", 0.5, gap_ms=2_000)
        room.step(150)
        before = room.pulse.level
        rec = await room.responder.on_event("drop", 0.9)
        assert SINGLE_V in rec["phase"]["targets"]
        room.step(1)
        return before, room.pulse.level, room.pulse.white, room.single_frames[-1]

    before, level, white, frame = _with_room(tmp_path, script)
    assert before <= 1e-9                            # black into the drop
    assert level == pytest.approx(1.0)               # full on its first frame
    assert white == pytest.approx(0.45)              # whitened
    assert frame[0] == pytest.approx([255.0, 0.45 * 255, 0.45 * 255], abs=1.0)


def test_a_push_eases_in_over_two_seconds_not_a_snap(tmp_path):
    async def script(room):
        await room.executor.jump(SINGLE_V, "pulse", {"energy": 0.9})
        room.step(1)
        first = room.pulse._energy_live
        room.step(2 * FPS - 1)
        return first, room.pulse._energy_live

    first, at_two_s = _with_room(tmp_path, script)
    assert first < 0.52                              # one frame: barely moved
    eased = 0.5 + 0.4 * (1 - np.exp(-1.0))           # one time constant
    assert at_two_s == pytest.approx(eased, abs=0.02)


# ── the house layer ─────────────────────────────────────────────────────────

def test_a_resting_house_look_withholds_the_lull_from_pulse_only(tmp_path, monkeypatch):
    from spectra.services import house

    async def script(room):
        monkeypatch.setattr(house, "scene_deferral",
                            lambda: "house mode 'Evening' is resting — it owns the scene")
        rec = await room.responder.on_event("lull", 0.5, gap_ms=1_000)
        room.step(120)
        return rec, room.pulse.level, room.strip._config.get("phase")

    rec, level, strip_phase = _with_room(tmp_path, script)
    assert rec["phase"]["targets"] == [STRIP_V]
    assert rec["phase"]["withheld"] == {
        "virtuals": [SINGLE_V],
        "reason": "house mode 'Evening' is resting — it owns the scene"}
    assert strip_phase == "lull"
    assert level > 0.2                               # not black: no music show


def test_the_house_levels_and_dark_apply_after_pulse(tmp_path):
    """Measured at the transport (the device's own flush): a house level
    halves Pulse's light, and a dark state wins over a bursting drop."""
    async def script(room):
        flushed: list = []
        device = room.host.devices.get(SINGLE_DEV)
        real = device.flush

        def flush(data):
            flushed.append(np.array(data, dtype=float, copy=True))
            return real(data)
        device.flush = flush
        try:
            room.step(10)
            full = float(flushed[-1].max())
            device_output.set_level(SINGLE_DEV, 0.5)
            room.step(5)
            half = float(flushed[-1].max())
            await room.responder.on_event("drop", 0.9)
            device_output.set_state(SINGLE_DEV, "dark")
            room.step(2)
            return full, half, float(flushed[-1].max()), room.pulse.level
        finally:
            device_output.clear_all()

    full, half, dark, level = _with_room(tmp_path, script)
    assert full > 0
    assert half == pytest.approx(full * 0.5, rel=0.03)
    assert level > 0.9                               # Pulse is bursting...
    assert dark == 0.0                               # ...the house says dark


# ── the test scene ──────────────────────────────────────────────────────────

def _store(tmp_path) -> Path:
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    scenes = {}
    for name in ("Orbits V2", "Black Hole V2"):
        sc = SceneV2(name=name, labels=["music"], devices=[
            SceneDeviceConfig(target_kind="category", target="Matrix",
                              effect_type="orbits", params={"spin": 0.3}),
            SceneDeviceConfig(target_kind="category", target="Singles",
                              effect_type="power",
                              params={"bass_decay_rate": 0.29, "blur": 1})])
        scenes[sc.id] = json.loads(sc.model_dump_json())
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps(scenes, indent=2))
    return path


def _seeder():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import seed_pulse_test_scene
    return seed_pulse_test_scene


def test_the_seeder_copies_one_scene_with_pulse_on_the_singles(tmp_path):
    seed = _seeder()
    path = _store(tmp_path)
    before = json.loads(path.read_text())
    seed.run(path, "Orbits V2", out=lambda *a: None)          # dry run
    assert json.loads(path.read_text()) == before
    result = seed.run(path, "Orbits V2", apply=True, out=lambda *a: None)
    after = json.loads(path.read_text())
    for sid, raw in before.items():                  # nothing else changed
        assert after[sid] == raw
    test = after[result["scene_id"]]
    assert test["name"] == "Pulse Test (Orbits V2)"
    assert "pulse-test" in test["labels"]
    singles = [d for d in test["devices"] if d["target"] == "Singles"]
    assert len(singles) == 1 and singles[0]["effect_type"] == "pulse"
    assert singles[0]["params"] == {}
    matrix = [d for d in test["devices"] if d["target"] == "Matrix"][0]
    assert matrix["effect_type"] == "orbits" and matrix["params"] == {"spin": 0.3}
    # re-running upserts the same scene; --remove takes exactly it away
    seed.run(path, "Orbits V2", apply=True, out=lambda *a: None)
    assert json.loads(path.read_text()) == after
    seed.run(path, "Orbits V2", apply=True, remove=True, out=lambda *a: None)
    assert json.loads(path.read_text()) == before


def test_the_test_scene_is_never_a_sequencer_candidate(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.models.sequencer import SelectorEntry
    from spectra.services import selection_kernel, sequencer_store

    seq_path = tmp_path / "sequencer.json"
    monkeypatch.setattr(scfg, "SEQUENCER_FILE", seq_path)

    seed = _seeder()
    scenes_path = _store(tmp_path)
    scenes = json.loads(scenes_path.read_text())
    source_ids = {raw["name"]: sid for sid, raw in scenes.items()}

    cfg = sequencer_store.load_config()
    cfg.entries = {source_ids["Orbits V2"]: SelectorEntry(),
                  source_ids["Black Hole V2"]: SelectorEntry()}
    sequencer_store.save_config(cfg)
    before = seq_path.read_bytes()

    result = seed.run(scenes_path, "Orbits V2", apply=True, out=lambda *a: None)

    assert seq_path.read_bytes() == before            # the store was never touched

    loaded = sequencer_store.load_config()
    candidates = selection_kernel.build_scene_candidates(
        loaded.entries, {}, loaded.affinity, genre_bucket=None, prev_id=None)
    assert result["scene_id"] not in {c.id for c in candidates}
