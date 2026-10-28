"""ENERGY — the one number (spectra/services/energy.py; the Energy plan,
https://claude.ai/artifact/2Dy1SnUgNQ2fJQomhk4dkh, approved 2026-10-28).
The definition step by step, then the engine reading it: a trigger fires at
Energy at its own moment, never at its stored value (the plan's D4), and a
drop just before a louder section reads the louder section (D2)."""
from __future__ import annotations

import asyncio

import pytest

import drop_synth
from spectra.services import energy

URI = "spotify:track:energy1"


@pytest.fixture
def shapes(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    drop_synth.reset_index()
    yield scfg.AUDIO_SHAPES_DIR
    drop_synth.reset_index()


# ── the definition, pure ─────────────────────────────────────────────────────

def test_the_quietest_middle_section_is_0_and_the_loudest_is_1():
    # the 0-15 s intro and 85-100 s outro don't set the range; they clamp
    raws = [0.10, 0.40, 0.70, 1.00, 0.55, 0.20]
    starts = [0, 15_000, 30_000, 50_000, 70_000, 85_000]
    ends = [15_000, 30_000, 50_000, 70_000, 85_000, 100_000]
    out = energy.normalize(raws, starts, ends)
    assert out[1] == pytest.approx(0.0) and out[3] == pytest.approx(1.0)
    assert out[2] == pytest.approx(0.5)
    assert out[0] == 0.0 and out[5] == 0.0, "a quiet intro/outro clamps to 0"
    assert energy.normalize([0.6, 0.6], [0, 50_000], [50_000, 100_000]) == [1.0, 1.0]


def test_the_mark_math_is_point_eight_and_an_unmarked_song_stops_at_075():
    assert energy.HEADROOM == 0.8 and energy.AUTO_CEILING == 0.75
    assert energy.mark_math(0.5, 1.0, False) == pytest.approx(0.4)
    assert energy.mark_math(1.0, 1.25, False) == pytest.approx(0.75)
    assert energy.mark_math(1.0, 1.25, True) == pytest.approx(1.0)
    assert energy.mark_math(1.0, 0.5, True) == pytest.approx(0.4), \
        "his rule: at Mark 50% Energy never reaches 1.0"


def _tl(factor=1.0, marked=False, offset=0):
    sections = [{"start_ms": 0, "end_ms": 20_000, "energy_rms": 0.4},
                {"start_ms": 20_000, "end_ms": 40_000, "energy_rms": 1.0},
                {"start_ms": 40_000, "end_ms": 60_000, "energy_rms": 0.4}]
    return energy.build_timeline(URI, sections, offset, factor, marked)


def test_sections_are_placed_in_song_time_by_the_capture_offset():
    tl = _tl(offset=5_000)
    assert [s.start_ms for s in tl.sections] == [5_000, 25_000, 45_000]
    assert [s.wav_start_ms for s in tl.sections] == [0, 20_000, 40_000]
    assert tl.at(24_000) == tl.sections[0].energy
    assert tl.at(26_000) == tl.sections[1].energy


def test_the_look_ahead_reads_the_next_section_higher_or_lower():
    tl = _tl(marked=True)
    loud, quiet = tl.sections[1].energy, tl.sections[0].energy
    assert loud == pytest.approx(0.8) and quiet == pytest.approx(0.0)
    assert tl.at(18_500) == quiet
    assert tl.at(18_500, 2_000) == loud, "1.5 s before the loud section"
    assert tl.at(17_000, 2_000) == quiet, "3 s before: the present"
    assert tl.at(38_500, 2_000) == quiet, "a quieter next section is read too"
    assert tl.at_source(20_000) == loud and tl.at_source(12_345) is None


def test_which_moments_look_ahead():
    assert energy.looks_ahead("fire_scene")
    assert energy.looks_ahead("fire_response", "drop")
    assert not energy.looks_ahead("fire_response", "flare")
    assert not energy.looks_ahead("fire_response", "charge")
    assert energy.source_ms("section:20000") == 20_000 and energy.source_ms("x") is None


# ── the song's own analysis ──────────────────────────────────────────────────

def _song(shapes):
    drop_synth.one_drop_song(shapes, URI, energy_sections=[
        (0, 20, 0.3), (20, 43, 0.5), (43, 80, 0.9), (80, 100, 0.2)])


def test_energy_at_reads_his_song_and_a_mark_reaches_it_at_once(shapes):
    from spectra.services import intensity_scale_marks
    _song(shapes)
    tl = energy.timeline(URI)
    assert [s.normalized for s in tl.sections] == pytest.approx([0.0, 0.0, 1.0, 0.0])
    factor, marked = energy.song_factor(URI)
    assert not marked
    assert energy.energy_at(URI, 50_000) == pytest.approx(energy.mark_math(1.0, factor, False))
    assert energy.energy_at(URI, 42_000, look_ahead=True) == energy.energy_at(URI, 50_000)
    assert energy.energy_at(URI, 42_000) == pytest.approx(0.0)
    intensity_scale_marks.set_mark(URI, 0.5)
    assert energy.energy_at(URI, 50_000) == pytest.approx(0.4), \
        "Mark 50%: the loudest section reads 0.4, never 1.0"
    assert energy.energy_at("spotify:track:nothing-here", 1_000) is None


def test_a_generated_moment_reads_its_own_source_section(shapes):
    _song(shapes)
    loud = energy.energy_at(URI, 50_000)
    # placed 5 s early (beyond the look-ahead) but generated from the 43 s edge
    assert energy.energy_for_moment(URI, 38_000, "fire_scene", None, "section:43000") == loud
    assert energy.energy_for_moment(URI, 38_000, "fire_scene") == pytest.approx(0.0)


# ── the engine reads it ──────────────────────────────────────────────────────

def test_a_trigger_fires_at_energy_at_its_moment_never_its_stored_value(shapes):
    """D4: the stored ⚡ value is not read. RED against the old engine: it
    landed 0.95 x 0.6 x the scale here."""
    from spectra.models.trigger import FireResponseAction, SpectraTrigger
    from spectra.services.trigger_engine import TriggerEngine
    _song(shapes)
    fired: list = []

    async def fire_response(event_class, intensity, gap=None, **kw):
        fired.append((event_class, intensity))

    quiet = SpectraTrigger(timestamp_ms=30_000, source="authored",
                           action=FireResponseAction(event_class="flare", intensity=0.95))
    drop = SpectraTrigger(timestamp_ms=41_800, source="authored",
                          action=FireResponseAction(event_class="drop", intensity=0.05))

    async def main():
        te = TriggerEngine(list_triggers=lambda uri: [quiet, drop],
                           fire_response=fire_response,
                           scene_change_mode=lambda: "full",
                           sequencer_enabled=lambda: False,
                           lead_ms=lambda t: 0, response_offset_ms=lambda a: 0)
        await te.on_track_state(URI)
        for pos in (29_000, 30_100, 41_000, 41_900):
            await te.tick(pos)

    asyncio.run(main())
    loud = energy.energy_at(URI, 50_000)
    assert fired[0] == ("flare", pytest.approx(0.0)), "the quiet section's Energy, not 0.95"
    assert fired[1] == ("drop", pytest.approx(loud)), \
        "a drop 1.2 s before the loud section reads the loud section"


def test_the_live_reading_is_energy_at_the_show_clock(shapes, monkeypatch):
    from spectra.services import engine
    _song(shapes)
    monkeypatch.setattr(engine.bridge, "track_uri", lambda: URI)
    monkeypatch.setattr(engine, "current_show_clock_ms", lambda: 42_000)
    assert engine.bridge.intensity() == pytest.approx(0.0)
    assert engine.bridge.intensity(look_ahead=True) == energy.energy_at(URI, 50_000)
    assert engine.current_energy() == engine.bridge.intensity()
