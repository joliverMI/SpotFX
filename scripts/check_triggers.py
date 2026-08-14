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
scfg.ROOM_CONTROLS_FILE = scfg.SPECTRA_STORAGE / "room_controls.json"
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
check(t_scene.source == "authored" and t_scene.generator_key is None,
      "a plain SpectraTrigger defaults to source=authored, no generator_key")

# front 3: scene_id=None is a legal fire_scene action (kernel-routed at fire time)
t_kernel = SpectraTrigger(timestamp_ms=1200,
                          action=FireSceneAction(scene_id=None, intensity=0.6),
                          source="generated", generator_key="section:1200")
check(t_kernel.action.scene_id is None, "fire_scene accepts scene_id=None")
round_trip_k = SpectraTrigger(**json.loads(t_kernel.model_dump_json()))
check(round_trip_k.action.scene_id is None and round_trip_k.source == "generated"
      and round_trip_k.generator_key == "section:1200",
      "a generated, kernel-routed trigger round-trips its provenance and None scene_id")
expect_invalid(lambda: FireSceneAction(scene_id="   "),
              "blank (whitespace-only) scene_id")

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

# front 3: scene_id=None (kernel-routed) is accepted, no 422
kernel_routed = json.loads(SpectraTrigger(
    timestamp_ms=300, action=FireSceneAction(scene_id=None)).model_dump_json())
r = client.post("/api/triggers", params={"uri": URI_B}, json=kernel_routed)
check(r.status_code == 200, "POST with scene_id=None (kernel-routed) is accepted")

# front 3: the editing API always stamps source=authored — ownership transfer
posing_as_generated = json.loads(SpectraTrigger(
    timestamp_ms=400, action=FireSceneAction(scene_id=scene.id),
    source="generated", generator_key="section:400").model_dump_json())
r = client.post("/api/triggers", params={"uri": URI_B}, json=posing_as_generated)
saved_id = r.json()["id"]
saved = next(t for t in client.get("/api/triggers", params={"uri": URI_B}).json()
            if t["id"] == saved_id)
check(saved["source"] == "authored" and saved["generator_key"] is None,
      "the authoring API always stamps source=authored (generator_key cleared), "
      "even when the posted body claims source=generated — editing a generated "
      "trigger through this endpoint IS the ownership-transfer edit")

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

# front 3: scene_id=None resolves through the injected select_scene at fire time
song["kernel"] = [SpectraTrigger(timestamp_ms=100,
                                 action=FireSceneAction(scene_id=None, intensity=0.42),
                                 source="generated", generator_key="section:100")]
select_calls: list[float] = []


def fake_select_scene(intensity):
    select_calls.append(intensity)
    return "kernel-picked-scene"


engine7 = TriggerEngine(list_triggers=lambda uri: song.get(uri, []),
                        fire_scene=fake_fire_scene, select_scene=fake_select_scene)
asyncio.run(engine7.on_track_state("kernel"))
fired7 = asyncio.run(engine7.tick(100))
check(len(fired7) == 1 and select_calls == [0.42]
      and fired_scene[-1] == ("kernel-picked-scene", None, 0.42),
      "a scene_id=None fire_scene action resolves through select_scene at the "
      "TRIGGER's own intensity, then fires the picked scene through the same "
      "fire_scene choke point a baked scene_id uses")

# scene_id=None + the kernel ladder terminating at STAY (picked_id=None) fires nothing
song["kernel_stay"] = [SpectraTrigger(timestamp_ms=100,
                                      action=FireSceneAction(scene_id=None),
                                      source="generated", generator_key="section:100")]
fire_scene_calls_before = len(fired_scene)
engine8 = TriggerEngine(list_triggers=lambda uri: song.get(uri, []),
                        fire_scene=fake_fire_scene, select_scene=lambda i: None)
asyncio.run(engine8.on_track_state("kernel_stay"))
fired8 = asyncio.run(engine8.tick(100))
check(len(fired8) == 1 and len(fired_scene) == fire_scene_calls_before
      and engine8.last_fire == {"id": song["kernel_stay"][0].id, "kind": "fire_scene",
                                "ok": True, "picked": None},
      "select_scene returning None (the kernel's terminal STAY) fires nothing, "
      "but the crossing still counts as handled — not a failure")

# the settings model: scene_change_mode gates GENERATED and AUTHORED
# triggers differently at each of the three tiers
song["gated"] = [
    SpectraTrigger(timestamp_ms=100, action=FireSceneAction(scene_id="s"),
                  source="generated"),
    SpectraTrigger(timestamp_ms=100, action=FireResponseAction(event_class="flare"),
                  source="authored"),
]


def _gated_run(mode):
    fire_scene_calls, fire_resp_calls = [], []

    async def fs(*a):
        fire_scene_calls.append(a)

    async def fr(*a):
        fire_resp_calls.append(a)

    eng = TriggerEngine(list_triggers=lambda uri: song.get(uri, []),
                        fire_scene=fs, fire_response=fr,
                        scene_change_mode=lambda: mode)
    asyncio.run(eng.on_track_state("gated"))
    fired = asyncio.run(eng.tick(100))
    return len(fired), len(fire_scene_calls), len(fire_resp_calls)

fired_t, scene_t, resp_t = _gated_run("transitions")
check((fired_t, scene_t, resp_t) == (0, 0, 0),
      "scene_change_mode=transitions skips BOTH the generated and the "
      "authored trigger's crossing — only the automatic transition fire "
      "happens in this tier, and it isn't a stored trigger")

fired_a, scene_a, resp_a = _gated_run("analysed")
check((fired_a, scene_a, resp_a) == (1, 1, 0),
      "scene_change_mode=analysed fires the GENERATED trigger's crossing "
      "but still skips the AUTHORED one")

fired_f, scene_f, resp_f = _gated_run("full")
check((fired_f, scene_f, resp_f) == (2, 1, 1),
      "scene_change_mode=full fires both the generated and the authored "
      "trigger's crossing")

# the automatic transition fire: a genuine song-to-song change (armed after
# the first URI ever seen) fires through select_scene + fire_scene, in
# EVERY mode — it's the floor all three tiers share, and it isn't gated by
# _trigger_allowed at all since it's never a stored trigger
transition_fires: list = []


async def transition_fire_scene(scene_id, color_set_id, intensity):
    transition_fires.append((scene_id, color_set_id, intensity))


engine_t = TriggerEngine(list_triggers=lambda uri: [], fire_scene=transition_fire_scene,
                         select_scene=lambda i: "auto-picked", scene_change_mode=lambda: "transitions",
                         transition_intensity=lambda: 0.33)
asyncio.run(engine_t.on_track_state("song-x"))   # first URI ever: only arms, no fire
check(transition_fires == [], "the FIRST song ever seen only arms the transition "
                              "clock — it isn't itself a transition")
asyncio.run(engine_t.on_track_state("song-y"))   # a genuine song-to-song change
check(transition_fires == [("auto-picked", None, 0.33)],
      "a genuine song change fires the automatic transition scene change, "
      "using the injected select_scene + the transition's own intensity, "
      "through the SAME fire_scene choke point every trigger uses")
asyncio.run(engine_t.on_track_state(None))       # stop: not a transition
check(len(transition_fires) == 1, "playback stopping (URI -> None) is not a "
                                  "transition and doesn't fire")
asyncio.run(engine_t.on_track_state("song-y"))   # resume the SAME song: not a transition
check(len(transition_fires) == 1, "resuming the SAME song after a stop is not "
                                  "a transition (mirrors scene_sequencer."
                                  "TransitionSource's own arm/fire semantics)")
asyncio.run(engine_t.on_track_state("song-z"))   # a real new song again
check(len(transition_fires) == 2, "a real new song after a stop fires again")

# select_scene returning None (the kernel's terminal STAY) fires nothing for
# a transition either, same as a stored fire_scene action
engine_stay = TriggerEngine(list_triggers=lambda uri: [], fire_scene=transition_fire_scene,
                            select_scene=lambda i: None, scene_change_mode=lambda: "full")
asyncio.run(engine_stay.on_track_state("stay-a"))
before_stay = len(transition_fires)
asyncio.run(engine_stay.on_track_state("stay-b"))
check(len(transition_fires) == before_stay,
      "the kernel's terminal STAY (select_scene -> None) fires nothing on a "
      "transition, same as a stored fire_scene action would")

# settings-model correction: when scene_sequencer is the live transition
# authority (its own config.enabled=True), the automatic transition fire
# defers entirely — no select_scene draw, no fire_scene call
engine_defer = TriggerEngine(list_triggers=lambda uri: [], fire_scene=transition_fire_scene,
                             select_scene=lambda i: "would-have-picked",
                             sequencer_enabled=lambda: True)
asyncio.run(engine_defer.on_track_state("defer-a"))   # arms
before_defer = len(transition_fires)
asyncio.run(engine_defer.on_track_state("defer-b"))   # a genuine transition
check(len(transition_fires) == before_defer,
      "sequencer_enabled=True: the automatic transition fire is a no-op — "
      "the sequencer remains the sole transition authority")

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

# front 3: the production _default_select_scene reaches the REAL selection
# kernel (build_scene_candidates + select), not just an injected fake.
from spectra.models.sequencer import SelectorEntry, SequencerConfig
from spectra.services import sequencer_store

kernel_scene = SceneV2(name="Kernel Pick", devices=[
    SceneDeviceConfig(target_kind="category", target="Matrix", effect_type="radial")])
scene_store.save(kernel_scene)
sequencer_store.save_config(SequencerConfig(entries={
    kernel_scene.id: SelectorEntry(inline_points=[{"x": 0.0, "y": 1.0}])}))
picked = prod_engine._select_scene(0.5)
check(picked == kernel_scene.id,
      "_default_select_scene reached the real sequencer_store config + "
      "selection_kernel.select — the sole configured, existing scene is "
      "the only positive-score candidate, so it wins the draw")

# settings-model correction (live reality: scene_sequencer was enabled on
# the running system): scene_sequencer and trigger_engine both fire off the
# SAME URI feed (services/engine.py's _on_track_uri calls both, in order,
# on every broadcast) — prove EXACTLY ONE of them actually fires a scene
# change per genuine transition, whichever the sequencer's own dark switch
# (config.enabled) says is live.
from spectra.services.scene_sequencer import SceneSequencer


def _coordination_run(seq_enabled):
    sequencer_store.save_config(SequencerConfig(enabled=seq_enabled, entries={
        kernel_scene.id: SelectorEntry(inline_points=[{"x": 0.0, "y": 1.0}])}))
    seq_fires: list = []
    trig_fires: list = []

    async def seq_fire(sid, cset, inten):
        seq_fires.append(sid)

    async def trig_fire(sid, cset, inten):
        trig_fires.append(sid)

    sequencer = SceneSequencer(
        fire=seq_fire, intensity=lambda: 0.7, wheel_get=lambda: None,
        wheel_set=lambda d: None, list_scene_ids=lambda: {kernel_scene.id},
        eligible_sets=lambda sid: {})
    trig = TriggerEngine(list_triggers=lambda uri: [], fire_scene=trig_fire)

    async def run():
        # arm both (first URI ever seen), then one genuine transition —
        # the exact call order+pairing services/engine.py's _on_track_uri
        # makes for every real broadcast.
        await sequencer.on_track_state("coord:1")
        await trig.on_track_state("coord:1")
        await sequencer.on_track_state("coord:2")
        await trig.on_track_state("coord:2")

    asyncio.run(run())
    return seq_fires, trig_fires


seq_on, trig_on = _coordination_run(True)
check(len(seq_on) == 1 and len(trig_on) == 0,
      "scene_sequencer.config.enabled=True: the sequencer fires the "
      "transition pick (its own dwell/affinity state), trigger_engine's "
      "automatic transition fire defers to it — exactly one scene change "
      "per transition, never two")

seq_off, trig_off = _coordination_run(False)
check(len(seq_off) == 0 and len(trig_off) == 1,
      "scene_sequencer.config.enabled=False (its shipped default): "
      "trigger_engine's automatic transition fire is the sole authority — "
      "exactly one scene change per transition")

# restore the state section 5's other checks below expect (enabled=False)
sequencer_store.save_config(SequencerConfig(entries={
    kernel_scene.id: SelectorEntry(inline_points=[{"x": 0.0, "y": 1.0}])}))

check(prod_engine._default_sequencer_enabled() is False,
      "the production sequencer-enabled default reads the real "
      "sequencer_store and reflects its state immediately")
sequencer_store.save_config(SequencerConfig(enabled=True, entries={
    kernel_scene.id: SelectorEntry(inline_points=[{"x": 0.0, "y": 1.0}])}))
check(prod_engine._default_sequencer_enabled() is True,
      "flipping sequencer_store's own enabled switch is the production "
      "default's live source of truth")
sequencer_store.save_config(SequencerConfig(entries={
    kernel_scene.id: SelectorEntry(inline_points=[{"x": 0.0, "y": 1.0}])}))  # restore

check(prod_engine._default_scene_change_mode() == "full",
      "the production scene_change_mode default reads the real room_controls "
      "store and reports its documented default (full)")
from spectra.services import room_controls as rc
rc.save_room_controls(rc.RoomControlState(scene_change_mode="transitions"))
check(prod_engine._default_scene_change_mode() == "transitions",
      "the room bar's tick is the production default's live source of "
      "truth — flipping it takes effect immediately")

# migration: a pre-existing room_controls.json written by the OLD
# midsong_triggers_enabled bool (pre this settings model) is read correctly
scfg.ROOM_CONTROLS_FILE.write_text(json.dumps({"midsong_triggers_enabled": True}))
check(rc.load_room_controls().scene_change_mode == "full",
      "migrating an old midsong_triggers_enabled=True room_controls.json "
      "maps to scene_change_mode=full — the closest match, since generated "
      "triggers were on and authored triggers/flares always fired anyway")
scfg.ROOM_CONTROLS_FILE.write_text(json.dumps({"midsong_triggers_enabled": False}))
check(rc.load_room_controls().scene_change_mode == "transitions",
      "migrating an old midsong_triggers_enabled=False room_controls.json "
      "maps to scene_change_mode=transitions — the owner had deliberately "
      "dialed generated triggers off, so the pure baseline is the most "
      "faithful read of that intent")
rc.save_room_controls(rc.RoomControlState(scene_change_mode="full"))  # restore

# the settings model's flare gate: engine.fire_response_event (both the
# bridge's own always-classifying path and a trigger's fire_response
# action) only reaches the real response engine in scene_change_mode=full —
# proven above at the default (full); now prove it's actually gated
rc.save_room_controls(rc.RoomControlState(scene_change_mode="analysed"))
before_gated = len(spectra_engine.responses.surges)
asyncio.run(spectra_engine.fire_response_event("flare", 0.8))
check(len(spectra_engine.responses.surges) == before_gated,
      "fire_response_event is a no-op outside scene_change_mode=full — "
      "flares are the owner's authored scene material (response bands "
      "tuned per scene), gated the same as hand-authored triggers")
rc.save_room_controls(rc.RoomControlState(scene_change_mode="full"))  # restore

# ═══ 6. mid-song generation (front 3) ════════════════════════════════════

from spectra.services import midsong_generator

GEN_URI = "spotify:track:midsong-gen"
shapes_dir = scfg.AUDIO_SHAPES_DIR
shapes_dir.mkdir(parents=True, exist_ok=True)
(shapes_dir / "gensong.json").write_text(json.dumps({"spotify_uri": GEN_URI}))
sections_v1 = [
    {"start_ms": 0, "end_ms": 10000, "label": "intro", "energy_rms": 0.1},
    {"start_ms": 10000, "end_ms": 30000, "label": "verse", "energy_rms": 0.4},
    {"start_ms": 30000, "end_ms": 45000, "label": "drop", "energy_rms": 0.9},
]
(shapes_dir / "gensong.librosa.json").write_text(json.dumps({"sections": sections_v1}))

moments = midsong_generator.candidate_moments(GEN_URI)
check([m[0] for m in moments] == [10000, 30000],
      "candidate_moments skips ms<=0 (the song's own start) and returns the "
      "remaining section boundaries in analysis order")
check(moments[0][1] < moments[1][1],
      "the quieter (verse) boundary seeds a lower intensity than the louder "
      "(drop) boundary — per-song minmax renormalization keeps relative "
      "magnitude, same convention as scripts/backfill_trigger_intensity.py")
check(all(0.0 <= m[1] <= 1.0 for m in moments), "seeded intensities stay in [0,1]")

summary1 = midsong_generator.generate_for_song(GEN_URI)
check(summary1 == {"moments": 2, "added": 2, "updated": 0, "deleted": 0,
                   "skipped_authored": 0},
      "first generation adds one trigger per candidate moment")
gen_triggers = trigger_store.list_for_song(GEN_URI)
check(len(gen_triggers) == 2 and all(t.source == "generated" for t in gen_triggers)
      and all(t.action.scene_id is None for t in gen_triggers),
      "generated triggers carry source=generated and no baked scene_id "
      "(kernel-routed at fire time)")
check({t.generator_key for t in gen_triggers} == {"section:10000", "section:30000"},
      "generator_key ties each generated trigger back to its analysis moment")

summary2 = midsong_generator.generate_for_song(GEN_URI)
check(summary2 == {"moments": 2, "added": 0, "updated": 0, "deleted": 0,
                   "skipped_authored": 0},
      "regenerating against an UNCHANGED analysis is a pure no-op")
check({t.id for t in trigger_store.list_for_song(GEN_URI)}
      == {t.id for t in gen_triggers},
      "regeneration reuses the same trigger ids — no churn")

# edit preservation: touching a generated trigger through the API claims it
edited_id = gen_triggers[0].id
touched = json.loads(SpectraTrigger(
    id=edited_id, timestamp_ms=gen_triggers[0].timestamp_ms + 500,
    action=FireSceneAction(scene_id=kernel_scene.id),
    source="generated", generator_key=gen_triggers[0].generator_key,
).model_dump_json())
r = client.post("/api/triggers", params={"uri": GEN_URI}, json=touched)
check(r.status_code == 200, "editing a generated trigger through the API succeeds")
check(trigger_store.get(GEN_URI, edited_id).source == "authored",
      "the editing API flipped the touched trigger to authored")

summary3 = midsong_generator.generate_for_song(GEN_URI)
edited_after = trigger_store.get(GEN_URI, edited_id)
check(edited_after.timestamp_ms == gen_triggers[0].timestamp_ms + 500
      and edited_after.action.scene_id == kernel_scene.id,
      "regeneration left the edited (now-authored) trigger completely alone")
check(summary3["skipped_authored"] == 1 and summary3["added"] == 1,
      "the edited trigger's generator_key is no longer claimed by a generated "
      "trigger, so regeneration seeds a FRESH generated trigger for that same "
      "analysis moment — the owner's edit and the reseed coexist")

# a changed analysis deletes stale generated triggers, spares authored ones
sections_v2 = [
    {"start_ms": 0, "end_ms": 15000, "label": "intro", "energy_rms": 0.1},
    {"start_ms": 15000, "end_ms": 40000, "label": "verse", "energy_rms": 0.5},
    {"start_ms": 40000, "end_ms": 50000, "label": "drop", "energy_rms": 0.95},
]
(shapes_dir / "gensong.librosa.json").write_text(json.dumps({"sections": sections_v2}))
summary4 = midsong_generator.generate_for_song(GEN_URI)
check(summary4 == {"moments": 2, "added": 2, "updated": 0, "deleted": 2,
                   "skipped_authored": 1},
      "a changed analysis deletes generated triggers tied to boundaries that "
      "no longer exist and seeds fresh ones for the new boundaries")
after4 = trigger_store.list_for_song(GEN_URI)
still_edited = trigger_store.get(GEN_URI, edited_id)
check(still_edited is not None and still_edited.source == "authored"
      and still_edited.action.scene_id == kernel_scene.id,
      "the owner's authored/edited trigger survives an analysis change untouched")
check({t.generator_key for t in after4 if t.source == "generated"}
      == {"section:15000", "section:40000"},
      "the surviving generated triggers match only the NEW analysis's boundaries")

# unanalyzed song: a clean no-op, not an error
NO_ANALYSIS_URI = "spotify:track:no-analysis-yet"
check(midsong_generator.candidate_moments(NO_ANALYSIS_URI) == [],
      "no analysis on disk → no candidate moments")
check(midsong_generator.generate_for_song(NO_ANALYSIS_URI)
      == {"moments": 0, "added": 0, "updated": 0, "deleted": 0, "skipped_authored": 0},
      "generation for an unanalyzed song is a clean no-op")

# flat-energy sections (zero span) fall back to 0.5, not a divide-by-zero
FLAT_URI = "spotify:track:flat-energy"
(shapes_dir / "flatsong.json").write_text(json.dumps({"spotify_uri": FLAT_URI}))
(shapes_dir / "flatsong.librosa.json").write_text(json.dumps({"sections": [
    {"start_ms": 0, "end_ms": 5000, "energy_rms": 0.5},
    {"start_ms": 5000, "end_ms": 10000, "energy_rms": 0.5},
]}))
flat_moments = midsong_generator.candidate_moments(FLAT_URI)
check(len(flat_moments) == 1 and flat_moments[0][1] == 0.5,
      "equal-energy sections (zero span) fall back to a flat 0.5 intensity")

print("\nALL CHECKS PASSED")
