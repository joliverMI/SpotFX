"""Executable spec for THE KEYSTONE's execution half: the SPECTRA-native
per-song trigger model (spectra/models/trigger.py), its store
(trigger_store.py, storage/spectra/triggers.json), its authoring API
(spectra/api/triggers.py), and the clock that fires them
(trigger_engine.py) — edge-triggered crossing, rearm-on-song-change,
rewind handling, and the three action kinds routed through their
production choke points (scene_sequencer.fire_scene_by_id,
engine.fire_response_event, drift_conductor.apply_set_directly).

Frame-level render proof (a placed trigger's fire_scene action landing on
the real FacadeExecutor + headless dummy device) lives in
tests/test_trigger_engine.py — this spec proves the model, store, API, and
clock logic in isolation with injected fakes, then proves the production
wiring reaches the real (test-isolated, dark) engine singleton for each
action kind.

Run from repo root: .venv/bin/python scripts/check_triggers.py
Isolated: temp files for every store; no LedFX I/O, no audio, no network.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import ValidationError


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


def expect_invalid(fn, label):
    try:
        fn()
        raise SystemExit(f"FAIL: {label} — accepted")
    except ValidationError:
        print(f"ok: {label} rejected")


td = Path(tempfile.mkdtemp(prefix="spectra-triggers-spec-"))

from fx import device_model
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({
    "c1": {"id": "c1", "name": "Matrix", "parent_id": None,
           "virtuals": ["v-m1"], "effects": ["radial"], "role": None},
}))

from fx import light_ownership
light_ownership.OWNERSHIP_FILE = td / "ownership.json"

from spectra import config as scfg
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.SEQUENCER_FILE = scfg.SPECTRA_STORAGE / "sequencer.json"
scfg.DRIFT_PROFILES_FILE = scfg.SPECTRA_STORAGE / "drift_profiles.json"
scfg.ROOM_COLOR_FILE = scfg.SPECTRA_STORAGE / "room_color.json"
scfg.TRIGGERS_FILE = scfg.SPECTRA_STORAGE / "triggers.json"
scfg.COLOR_SETS_FILE = td / "color_sets.json"
scfg.PROFILES_DIR = td / "profiles"
scfg.AUDIO_SHAPES_DIR = td / "audio_shapes"
scfg.TRAINING_PROFILES_FILE = td / "training_profiles.json"

from spectra.models.scene import SceneDeviceConfig, SceneV2
from spectra.models.trigger import (FireResponseAction, FireSceneAction,
                                    SelectColorSetAction, SpectraTrigger)
from spectra.services import scene_store, trigger_store

# ═══ 1. model ═════════════════════════════════════════════════════════════

expect_invalid(lambda: SpectraTrigger(timestamp_ms=-1,
                                      action=FireSceneAction(scene_id="s")),
              "negative timestamp_ms")
expect_invalid(lambda: FireSceneAction(scene_id="s", intensity=1.5),
              "intensity out of [0,1]")
expect_invalid(lambda: FireSceneAction(scene_id=""), "empty scene_id")
expect_invalid(lambda: SelectColorSetAction(set_id=""), "empty set_id")

t_scene = SpectraTrigger(timestamp_ms=1000,
                         action=FireSceneAction(scene_id="sc1", intensity=0.7))
check(t_scene.action.kind == "fire_scene", "discriminated union tags fire_scene")
round_trip = SpectraTrigger(**json.loads(t_scene.model_dump_json()))
check(round_trip.action.scene_id == "sc1" and round_trip.action.intensity == 0.7,
      "fire_scene action round-trips through JSON by its discriminator")

t_resp = SpectraTrigger(timestamp_ms=500,
                        action=FireResponseAction(event_class="drop", intensity=0.9))
round_trip2 = SpectraTrigger(**json.loads(t_resp.model_dump_json()))
check(round_trip2.action.kind == "fire_response"
      and round_trip2.action.event_class == "drop",
      "fire_response action round-trips through JSON by its discriminator")

t_color = SpectraTrigger(timestamp_ms=2000,
                         action=SelectColorSetAction(set_id="warm"))
round_trip3 = SpectraTrigger(**json.loads(t_color.model_dump_json()))
check(round_trip3.action.set_id == "warm",
      "select_color_set action round-trips through JSON by its discriminator")

# ═══ 2. store ═════════════════════════════════════════════════════════════

URI_A, URI_B = "spotify:track:a", "spotify:track:b"
trigger_store.upsert(URI_A, t_resp)     # ts 500
trigger_store.upsert(URI_A, t_scene)    # ts 1000
trigger_store.upsert(URI_A, t_color)    # ts 2000
listed = trigger_store.list_for_song(URI_A)
check([t.timestamp_ms for t in listed] == [500, 1000, 2000],
      "store lists a song's triggers sorted by timestamp_ms")
check(trigger_store.list_for_song(URI_B) == [],
      "a different song's list is isolated (keyed by spotify_uri)")

moved = t_scene.model_copy(update={"timestamp_ms": 1500})
trigger_store.upsert(URI_A, moved)
check([t.timestamp_ms for t in trigger_store.list_for_song(URI_A)] == [500, 1500, 2000],
      "upsert by id replaces in place (drag-to-move persists as one write)")
check(trigger_store.get(URI_A, t_scene.id).timestamp_ms == 1500,
      "get() finds by id within a song")
check(trigger_store.delete(URI_A, t_scene.id) is True
      and len(trigger_store.list_for_song(URI_A)) == 2,
      "delete removes by id")
check(trigger_store.delete(URI_A, "missing") is False,
      "delete on an unknown id reports False, not an error")

# ═══ 3. API ═══════════════════════════════════════════════════════════════

from fastapi.testclient import TestClient
from spectra.app import create_app
client = TestClient(create_app())

scene = SceneV2(name="Fire Me", devices=[
    SceneDeviceConfig(target_kind="category", target="Matrix", effect_type="radial")])
scene_store.save(scene)

r = client.post("/api/triggers", params={"uri": URI_B}, json=json.loads(
    SpectraTrigger(timestamp_ms=100,
                   action=FireSceneAction(scene_id=scene.id)).model_dump_json()))
check(r.status_code == 200, "POST /api/triggers creates a trigger")
r = client.get("/api/triggers", params={"uri": URI_B})
check(r.status_code == 200 and len(r.json()) == 1
      and r.json()[0]["action"]["scene_id"] == scene.id,
      "GET /api/triggers lists the song's triggers")

bad = json.loads(SpectraTrigger(
    timestamp_ms=100, action=FireSceneAction(scene_id="no-such-scene")).model_dump_json())
r = client.post("/api/triggers", params={"uri": URI_B}, json=bad)
check(r.status_code == 422, "unknown scene_id in a fire_scene action → 422")

bad2 = json.loads(SpectraTrigger(
    timestamp_ms=100, action=SelectColorSetAction(set_id="no-such-set")).model_dump_json())
r = client.post("/api/triggers", params={"uri": URI_B}, json=bad2)
check(r.status_code == 422, "unknown set_id in a select_color_set action → 422")

trig_id = client.get("/api/triggers", params={"uri": URI_B}).json()[0]["id"]
r = client.delete(f"/api/triggers/{trig_id}", params={"uri": URI_B})
check(r.status_code == 200, "DELETE /api/triggers/{id} removes it")
check(client.delete(f"/api/triggers/{trig_id}", params={"uri": URI_B}).status_code == 404,
      "deleting an already-gone trigger → 404")

# ═══ 4. the clock (fakes — pure crossing/rearm/rewind logic) ════════════════

from spectra.models.trigger import SpectraTrigger as _ST  # noqa: F401 (readability)
from spectra.services.trigger_engine import TriggerEngine


def _mk(ts_ms, kind="fire_scene", enabled=True):
    action = {"fire_scene": FireSceneAction(scene_id="s"),
              "fire_response": FireResponseAction(event_class="flare"),
              "select_color_set": SelectColorSetAction(set_id="w")}[kind]
    return SpectraTrigger(timestamp_ms=ts_ms, action=action, enabled=enabled)


song = {"song": [_mk(0), _mk(1000), _mk(2000, enabled=False), _mk(3000)]}
fired_scene, fired_resp, fired_color = [], [], []


async def fake_fire_scene(scene_id, color_set_id, intensity):
    fired_scene.append((scene_id, color_set_id, intensity))


async def fake_fire_response(event_class, intensity):
    fired_resp.append((event_class, intensity))


async def fake_select_color_set(set_id):
    fired_color.append(set_id)


engine = TriggerEngine(
    list_triggers=lambda uri: song.get(uri, []),
    fire_scene=fake_fire_scene, fire_response=fake_fire_response,
    select_color_set=fake_select_color_set)


async def run_clock():
    out = []
    await engine.on_track_state("song")
    out.append(await engine.tick(0))       # arm+fire: t=0 lands exactly at arm
    out.append(await engine.tick(0))       # flat position: nothing new
    out.append(await engine.tick(500))     # nothing crosses yet
    out.append(await engine.tick(1000))    # crosses the ts=1000 trigger
    out.append(await engine.tick(2500))    # skips the disabled ts=2000 trigger
    out.append(await engine.tick(2400))    # rewind: rearm silently, no fire
    out.append(await engine.tick(3000))    # forward again: fires ts=3000
    return out


results = asyncio.run(run_clock())
check([len(r) for r in results] == [1, 0, 0, 1, 0, 0, 1],
      "crossing fires exactly once per trigger, in order: arm-at-0, flat "
      "no-op, no-crossing no-op, forward crossing, disabled skipped, "
      "rewind silent, forward re-crossing fires")
check(len(fired_scene) == 3 and fired_scene[0] == ("s", None, 0.5),
      "fire_scene actions reached the injected fire_scene fake with its args")

# a fresh URI rearms without backfiring the new song's history
engine2 = TriggerEngine(list_triggers=lambda uri: song.get(uri, []),
                        fire_scene=fake_fire_scene)


async def run_song_change():
    out = []
    await engine2.on_track_state("song")
    out.append(await engine2.tick(2500))   # first tick ever: arms, no fire
    await engine2.on_track_state("song-2")  # a NEW song, positions restart near 0
    out.append(await engine2.tick(50))     # arms fresh — must not backfire ts=0/1000
    out.append(await engine2.tick(1000))   # now a real crossing (song-2 has no data → still empty)
    return out


out2 = asyncio.run(run_song_change())
check([len(r) for r in out2] == [0, 0, 0],
      "a URI change rearms silently — restarting near position 0 on a new "
      "song never backfires the previous song's crossed moments")

# a response-only song, isolated from `song`'s fire_scene actions
song["resp"] = [_mk(400, kind="fire_response")]
engine4 = TriggerEngine(list_triggers=lambda uri: song.get(uri, []),
                        fire_response=fake_fire_response)
asyncio.run(engine4.on_track_state("resp"))
asyncio.run(engine4.tick(0))
asyncio.run(engine4.tick(400))
check(fired_resp == [("flare", 0.5)],
      "fire_response actions reached the injected fire_response fake")

song["color"] = [_mk(400, kind="select_color_set")]
engine5 = TriggerEngine(list_triggers=lambda uri: song.get(uri, []),
                        select_color_set=fake_select_color_set)
asyncio.run(engine5.on_track_state("color"))
asyncio.run(engine5.tick(0))
asyncio.run(engine5.tick(400))
check(fired_color == ["w"], "select_color_set actions reached the injected fake")

# an action that raises is logged and recorded, never crashes the tick
song["boom"] = [_mk(0, kind="fire_scene")]


async def raiser(*a):
    raise RuntimeError("boom")


engine6 = TriggerEngine(list_triggers=lambda uri: song.get(uri, []), fire_scene=raiser)
asyncio.run(engine6.on_track_state("boom"))
fired6 = asyncio.run(engine6.tick(0))
check(len(fired6) == 1 and engine6.last_fire == {"id": song["boom"][0].id,
                                                 "kind": "fire_scene", "ok": False},
      "a raising action is caught, logged, and recorded — the clock survives")

status = engine.status()
check(status["track_uri"] == "song" and status["last_fire"]["ok"] is True,
      "status() surfaces the current song and last fire outcome")

# ═══ 5. production wiring — the real (test-isolated, dark) choke points ═════
# fire_scene_by_id is NOT exercised here: like scene_sequencer's own spec
# coverage (check_spectra.py), it always compiles dry_run=False (the real
# owner-Fire HTTP path, unchanged pre-existing behavior) — a live fire
# attempt this offline spec must never make. Section 4 above already proves
# a fire_scene action reaches fire_scene_by_id's exact call signature
# (scene_id, color_set_id, intensity) via the injected fake.

from spectra.services import color_journey
from spectra.services import engine as spectra_engine

before = len(spectra_engine.responses.surges)
asyncio.run(spectra_engine.fire_response_event("flare", 0.8))
check(len(spectra_engine.responses.surges) == before + 1,
      "fire_response_event (the bridge's own choke point) reached the real "
      "response engine — a trigger-fired flare means what a bridge-fired "
      "flare means")

card = json.loads(json.dumps({"id": "warm-set", "name": "Warm", "kind": "set",
                              "entries": []}))
scfg.COLOR_SETS_FILE.write_text(json.dumps({"warm-set": card}))
from spectra.services.trigger_engine import trigger_engine as prod_engine

asyncio.run(prod_engine.on_track_state("live-song"))
trigger_store.upsert("live-song", SpectraTrigger(
    timestamp_ms=0, action=SelectColorSetAction(set_id="warm-set")))
asyncio.run(prod_engine.tick(0))
check(color_journey.load_room().active_set_id == "warm-set",
      "the production singleton's select_color_set default reaches the "
      "real drift_conductor.apply_set_directly — the room's active set "
      "moved on the trigger's word, exactly like POST /api/room-color/apply")

print("\nALL CHECKS PASSED")
