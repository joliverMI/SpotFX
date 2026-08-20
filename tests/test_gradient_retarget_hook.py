"""The two-dimensional drift gradient's retarget hook wiring (owner ask
2026-08-20): trigger_engine.TriggerEngine calls its intensity_event
injectable at exactly the two moments his proposal named — a trigger
firing (_fire) and an analysed song transition firing (_fire_transition).
Default is a safe no-op (see TriggerEngine.__init__'s own comment for why
this one injectable's default deliberately does NOT lazy-import the
production conductor the way fire_scene/fire_response do) — production
wiring is asserted separately, by inspecting services/engine.py's module
source rather than importing it (importing it would construct real
singletons against live config)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services.trigger_engine import TriggerEngine


def _run(coro):
    return asyncio.run(coro)


def _trig(ts_ms):
    return SpectraTrigger(timestamp_ms=ts_ms,
                          action=FireSceneAction(scene_id="s1", intensity=0.5))


def test_default_intensity_event_is_a_safe_noop():
    engine = TriggerEngine(list_triggers=lambda uri: [_trig(1000)],
                           fire_scene=lambda *a, **kw: asyncio.sleep(0))
    _run(engine.on_track_state("song:1"))
    # Must not raise even though nothing was ever wired.
    _run(engine.tick(1000))


def test_fire_calls_intensity_event():
    calls = []
    engine = TriggerEngine(list_triggers=lambda uri: [_trig(1000)],
                           fire_scene=lambda *a, **kw: asyncio.sleep(0),
                           intensity_event=lambda: calls.append(True))
    _run(engine.on_track_state("song:1"))
    fired = _run(engine.tick(1000))
    assert len(fired) == 1
    assert calls == [True]


def test_fire_transition_calls_intensity_event():
    calls = []
    engine = TriggerEngine(list_triggers=lambda uri: [],
                           fire_scene=lambda *a, **kw: asyncio.sleep(0),
                           select_scene=lambda intensity: "s1",
                           intensity_event=lambda: calls.append(True))
    _run(engine.on_track_state("song:1"))
    _run(engine.on_track_state("song:2"))   # armed transition -> fires
    assert calls == [True]


def test_intensity_event_failure_does_not_break_the_fire():
    def boom():
        raise RuntimeError("storage down")

    fired_scenes = []

    async def fire_scene(scene_id, color_set_id, intensity):
        fired_scenes.append(scene_id)

    engine = TriggerEngine(list_triggers=lambda uri: [_trig(1000)],
                           fire_scene=fire_scene,
                           intensity_event=boom)
    _run(engine.on_track_state("song:1"))
    fired = _run(engine.tick(1000))
    assert len(fired) == 1
    assert fired_scenes == ["s1"]   # the real fire still happened


def test_production_wiring_present_in_engine_source():
    """Asserts the wiring exists WITHOUT importing services/engine.py
    (which would construct real bridge/conductor/responses singletons
    against live config, unsafe for a test process) — read the source and
    confirm the one-line explicit wire is present."""
    src = (Path(__file__).resolve().parent.parent
           / "spectra" / "services" / "engine.py").read_text(encoding="utf-8")
    assert "trigger_engine._intensity_event = conductor.on_intensity_event" in src
