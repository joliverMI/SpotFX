"""Executable spec + real-song demonstration for trigger-level SCENE POOLS
(models/trigger.py's SCENE POOLS section, 2026-08-17, his own ask:
"triggers should be able to carry some meta data that can say choose from
only these scenes and includes weights").

Part A verifies the measured facts the design was built from, against his
REAL live storage (read-only, never written — see --live-storage):
  - storage/spectra/triggers.json's song/action-kind counts
  - every fire_scene trigger's scene_id is null today (the "absent must
    mean unconstrained" premise Part 1's design decision rests on)
  - legacy storage/events.json really does carry a weighted scene-pool
    precedent (scene_group_members + scene_group_mode="weighted",
    898 "weight" occurrences) — this is a PORT of a proven shape, not an
    invention; see models/trigger.py's SCENE POOLS docstring for exactly
    what was and wasn't carried over

Part B is the pure kernel/model spec: select_from_scene_pool's weighted
draw, its zero-veto, its existing-scene filtering, backward-compatible
parsing of his real (scene_pool-less) triggers, the API's new scene_pool
reference validation, and the production TriggerEngine wiring
(_fire's scene_pool-over-kernel precedence).

Part C is THE DEMONSTRATION Part 3 of the brief asked for: one of his own
heaviest scene-change songs, real trigger timestamps/intensities, three
things placed side by side —
  1. what it does TODAY (every fire_scene trigger's stored scene_id: null)
  2. what it does under the sequencer with NO scene_pool (his real 9-scene
     sequencer config, unconstrained kernel draw — the baseline)
  3. what it does WITH an example weighted subset (3 of his 9 real scenes)
— proving the subset both CONFINES (nothing outside the named scenes ever
fires) and still shows real variety (doesn't collapse to one scene).

Isolated: a temp SPECTRA_STORAGE seeded from a READ-ONLY copy of his real
scenes.json/sequencer.json (never written back). His triggers.json is only
ever opened for reading. No LedFX I/O, no audio, no network, no writes to
/home/javi/SpotFX ever.

Run from repo root: .venv/bin/python scripts/check_trigger_scene_pools.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from random import Random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_LIVE_STORAGE = Path("/home/javi/SpotFX/storage/spectra")

# The three heaviest scene-change songs the brief named, with titles read
# from storage/profiles/*.json's own spotify_uri field (confirmed exact
# match, not a filename guess) — see the PR description for how these were
# looked up.
SONG_TITLES = {
    "spotify:track:0KpvMmpUFIMVpY14ypSdBB": "Lift Me Up — Yes",
    "spotify:track:3PQWdLxl8mzu5Ukt7rxHuv":
        "Starship Trooper: a. Life Seeker, b. Disillusion, c. Würm — Yes",
    "spotify:track:76mh0rcSJpNhoCCqazptWm": "Xpander — Sasha",
}


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


def fmt_ms(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live-storage", type=Path, default=DEFAULT_LIVE_STORAGE,
                   help="Read-only source of his real scenes/sequencer config "
                        "and trigger data — this script only ever reads from "
                        "here, never writes.")
    p.add_argument("--song-uri", default="spotify:track:0KpvMmpUFIMVpY14ypSdBB",
                   help="Real spotify URI to demonstrate against (default: "
                        "'Lift Me Up' by Yes, his heaviest scene-change song).")
    p.add_argument("--seed", type=int, default=20260817,
                   help="RNG seed for the reproducible demo draws.")
    return p.parse_args()


args = parse_args()
LIVE = args.live_storage
LIVE_TRIGGERS = LIVE / "triggers.json"
if not (LIVE / "scenes.json").exists() or not (LIVE / "sequencer.json").exists() \
        or not LIVE_TRIGGERS.exists():
    raise SystemExit(
        f"FAIL: expected his real scenes.json/sequencer.json/triggers.json "
        f"under {LIVE} — pass --live-storage to point elsewhere. Per the "
        f"task's own instruction this is NOT a synthetic fixture; refusing "
        f"to fabricate one.")

td = Path(tempfile.mkdtemp(prefix="spectra-trigger-scene-pools-spec-"))

from fx import device_model
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from fx import light_ownership
light_ownership.OWNERSHIP_FILE = td / "ownership.json"

from spectra import config as scfg
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SPECTRA_STORAGE.mkdir(parents=True, exist_ok=True)
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.SEQUENCER_FILE = scfg.SPECTRA_STORAGE / "sequencer.json"
scfg.DRIFT_PROFILES_FILE = scfg.SPECTRA_STORAGE / "drift_profiles.json"
scfg.SCENE_BACKUPS_FILE = scfg.SPECTRA_STORAGE / "scene_backups.json"
scfg.SCENE_GENESIS_FILE = scfg.SPECTRA_STORAGE / "scene_genesis.json"
scfg.TRIGGERS_FILE = scfg.SPECTRA_STORAGE / "triggers.json"
scfg.FIRE_HISTORY_FILE = scfg.SPECTRA_STORAGE / "fire_history.json"
scfg.SHOW_LOG_FILE = scfg.SPECTRA_STORAGE / "show_log.json"
scfg.ROOM_COLOR_FILE = scfg.SPECTRA_STORAGE / "room_color.json"
scfg.ROOM_CONTROLS_FILE = scfg.SPECTRA_STORAGE / "room_controls.json"
scfg.COLOR_SETS_FILE = td / "color_sets.json"
scfg.PROFILES_DIR = td / "profiles"
scfg.AUDIO_SHAPES_DIR = td / "audio_shapes"
scfg.TRAINING_PROFILES_FILE = td / "training_profiles.json"


def _reseed_real_scenes_and_sequencer() -> None:
    """(Re-)copy his REAL live scenes/sequencer config into the temp
    storage — a read-only COPY; the source files under LIVE are never
    opened for writing. Called again before Part C since Part B's B9
    deliberately overwrites the sequencer config to rig a precedence test."""
    scfg.SCENES_FILE.write_text((LIVE / "scenes.json").read_text(encoding="utf-8"))
    scfg.SEQUENCER_FILE.write_text((LIVE / "sequencer.json").read_text(encoding="utf-8"))


_reseed_real_scenes_and_sequencer()

from pydantic import ValidationError

from spectra.models.scene import SceneDeviceConfig, SceneV2
from spectra.models.trigger import (FireSceneAction, ScenePoolMember,
                                    SpectraTrigger)
from spectra.services import scene_store, selection_kernel as kernel
from spectra.services import sequencer_store, trigger_store

# ═══ Part A — verify the brief's measured facts against his real data ═════

raw_triggers = json.loads(LIVE_TRIGGERS.read_text(encoding="utf-8"))
print(f"\n--- Part A: measured facts, read fresh from {LIVE_TRIGGERS} ---")
print(f"info: {len(raw_triggers)} songs in his real triggers.json")

kind_counts = Counter()
fire_scene_non_null = 0
for uri, trigs in raw_triggers.items():
    for t in trigs:
        kind = t["action"]["kind"]
        kind_counts[kind] += 1
        if kind == "fire_scene" and t["action"].get("scene_id") is not None:
            fire_scene_non_null += 1
print(f"info: action kind counts: {dict(kind_counts)}")
check(fire_scene_non_null == 0,
      f"every one of his {kind_counts['fire_scene']} fire_scene triggers has "
      f"scene_id=null — Part 1's 'absent must mean unconstrained' design "
      f"premise holds for 100% of his existing migrated data, confirmed "
      f"fresh (not assumed from the brief)")

legacy_events = LIVE.parent / "events.json"
if legacy_events.exists():
    raw_legacy = legacy_events.read_text(encoding="utf-8")
    weight_occurrences = raw_legacy.count('"weight"')
    print(f"info: legacy {legacy_events} has {weight_occurrences} "
          f'"weight" occurrences (the strong lead the brief named)')
    legacy_data = json.loads(raw_legacy)
    weighted_groups = [
        ev for ev in legacy_data.values()
        if ev.get("event_type") == "scene_group"
        and ev.get("scene_group_mode") == "weighted"
    ]
    any_groups = [ev for ev in legacy_data.values()
                 if ev.get("event_type") == "scene_group"]
    print(f"info: {len(any_groups)} legacy scene_group events, "
          f"{len(weighted_groups)} using scene_group_mode='weighted'")
    check(any(ev.get("scene_group_members") for ev in any_groups),
          "legacy scene_group events carry scene_group_members: "
          "[{event_id, weight}] — this IS the shape scene_pool ports "
          "(narrowed to inline-per-trigger, per Part 1's design decision; "
          "see models/trigger.py's SCENE POOLS docstring for what a named, "
          "shared Scene Group entity would additionally require — still "
          "SPECTRA_SPEC.md §2, a GAP, not built by this change)")
else:
    print(f"info: legacy events.json not found at {legacy_events} — skipping "
          f"the legacy-precedent check (informational only)")

# ═══ Part B — pure kernel/model spec ═══════════════════════════════════════

print("\n--- Part B: kernel + model spec ---")

# B1: backward compatibility — a REAL trigger from his corpus (scene_pool-
# less) parses unchanged, defaults to scene_pool=None.
sample_uri, sample_trigs = next(iter(raw_triggers.items()))
sample_raw = next(t for t in sample_trigs if t["action"]["kind"] == "fire_scene")
sample_trig = SpectraTrigger(**sample_raw)
check(sample_trig.action.scene_pool is None,
      "a real fire_scene trigger from his corpus (no scene_pool key in "
      "storage) parses with scene_pool=None — nothing on disk needs to "
      "change for this field to exist")
check(SpectraTrigger(**json.loads(sample_trig.model_dump_json())).action.scene_id
      == sample_trig.action.scene_id,
      "round-trips unchanged through JSON")

# B2: model validation
expect_invalid_calls = [
    (lambda: ScenePoolMember(scene_id="s", weight=-1.0), "negative pool weight"),
    (lambda: ScenePoolMember(scene_id=""), "empty pool scene_id"),
]
for fn, label in expect_invalid_calls:
    try:
        fn()
        raise SystemExit(f"FAIL: {label} — accepted")
    except ValidationError:
        print(f"ok: {label} rejected")

# B3: two real scenes on disk (seeded from his live scenes.json above).
all_scenes = scene_store.list_all()
check(len(all_scenes) >= 3,
      f"his real (seeded) scenes.json has {len(all_scenes)} scenes to test "
      f"against")
by_name = {s.name: s.id for s in all_scenes}
scene_ids = [s.id for s in all_scenes]
a, b, c = scene_ids[0], scene_ids[1], scene_ids[2]

# B4: weighted draw favors higher weight, both still appear (statistical).
rng = Random(1)
pool_ab = [ScenePoolMember(scene_id=a, weight=3.0),
          ScenePoolMember(scene_id=b, weight=1.0)]
draws = [kernel.select_from_scene_pool(pool_ab, rng) for _ in range(400)]
counts = Counter(draws)
check(set(counts) == {a, b},
      f"both pool members drawn at least once across 400 draws: {counts}")
check(counts[a] > counts[b],
      f"the 3x-weighted member drew more often ({counts[a]} vs {counts[b]}) "
      f"— a real bias, not a coin flip")

# B5: zero weight is a hard veto within the pool.
pool_veto = [ScenePoolMember(scene_id=a, weight=0.0),
            ScenePoolMember(scene_id=b, weight=5.0)]
veto_draws = {kernel.select_from_scene_pool(pool_veto, rng) for _ in range(50)}
check(veto_draws == {b},
      "a weight=0 pool member never draws, even across 50 draws — the "
      "kernel's zero-veto convention holds inside a scene_pool too")

# B6: all-zero pool draws nothing (never silently falls back to uniform
# across the WHOLE room — "only these scenes" stays "only these scenes").
pool_allzero = [ScenePoolMember(scene_id=a, weight=0.0),
               ScenePoolMember(scene_id=b, weight=0.0)]
check(kernel.select_from_scene_pool(pool_allzero, rng) is None,
      "an all-zero-weight pool draws None — nothing fires this crossing, "
      "it does NOT expand back out to the unconstrained kernel draw")

# B7: a pool member naming a scene that no longer exists is filtered out.
gone_id = "scene-id-that-was-deleted"
pool_gone = [ScenePoolMember(scene_id=gone_id, weight=10.0),
            ScenePoolMember(scene_id=c, weight=1.0)]
existing = {s.id for s in all_scenes}
gone_draws = {kernel.select_from_scene_pool(pool_gone, rng, existing_ids=existing)
             for _ in range(50)}
check(gone_draws == {c},
      "a deleted scene named in a pool is filtered out before drawing — "
      "the surviving member draws every time despite the huge weight on "
      "the gone one")
check(kernel.select_from_scene_pool(
    [ScenePoolMember(scene_id=gone_id, weight=10.0)], rng, existing_ids=existing) is None,
      "a pool whose ONLY member is gone draws None, same terminal "
      "convention as B6")

# B8: production TriggerEngine wiring — the real singleton, not a fake.
from spectra.services.trigger_engine import trigger_engine as prod_engine

pool_prod = [ScenePoolMember(scene_id=a, weight=1.0)]
check(prod_engine._select_scene_from_pool(pool_prod) == a,
      "_default_select_scene_from_pool reaches the real scene_store + "
      "selection_kernel.select_from_scene_pool")

# B9: _fire() prefers scene_pool over the kernel draw when both scene_id=None
# and scene_pool are present (frame-level proof of the same property lives
# in tests/test_trigger_engine.py — this is the lighter store-level check).
# Rig the sequencer config so the UNCONSTRAINED kernel draw could ONLY ever
# pick b (the sole configured entry) — a's fire below can only have come
# from the scene_pool override.
from spectra.models.sequencer import SelectorEntry, SequencerConfig

sequencer_store.save_config(SequencerConfig(
    entries={b: SelectorEntry(inline_points=[{"x": 0.0, "y": 1.0}])}))
import asyncio

fired_scene_ids = []


async def fake_fire_scene(scene_id, color_set_id, intensity):
    fired_scene_ids.append(scene_id)

from spectra.services.trigger_engine import TriggerEngine

trig_pool = SpectraTrigger(timestamp_ms=1000, action=FireSceneAction(
    scene_id=None, intensity=0.5,
    scene_pool=[ScenePoolMember(scene_id=a, weight=1.0)]))
engine = TriggerEngine(list_triggers=lambda uri: [trig_pool],
                       fire_scene=fake_fire_scene,
                       render_intensity=lambda x: x, rng=Random(2))
asyncio.run(engine.on_track_state("spec:pool-precedence"))
asyncio.run(engine.tick(1000))
check(fired_scene_ids == [a],
      "_fire() picked the scene_pool's own member (a), not the kernel's "
      "config-favoured scene (b), when a trigger carries both scene_id=None "
      "and a non-empty scene_pool")

# B10: API validation — an unknown scene_pool member id is rejected 422,
# same discipline as the existing scene_id/color_set_id checks.
from fastapi.testclient import TestClient

from spectra.app import create_app

client = TestClient(create_app())
bad_pool_trigger = json.loads(SpectraTrigger(
    timestamp_ms=100, action=FireSceneAction(
        scene_id=None, scene_pool=[ScenePoolMember(scene_id="no-such-scene",
                                                    weight=1.0)])).model_dump_json())
r = client.post("/api/triggers", params={"uri": "spec:api-validate"},
                json=bad_pool_trigger)
check(r.status_code == 422, "unknown scene_pool member scene_id → 422")

good_pool_trigger = json.loads(SpectraTrigger(
    timestamp_ms=100, action=FireSceneAction(
        scene_id=None, scene_pool=[ScenePoolMember(scene_id=a, weight=1.0)]),
    ).model_dump_json())
r = client.post("/api/triggers", params={"uri": "spec:api-validate"},
                json=good_pool_trigger)
check(r.status_code == 200, "a scene_pool naming only real scenes is accepted")
saved = client.get("/api/triggers", params={"uri": "spec:api-validate"}).json()
check(saved[0]["action"]["scene_pool"] == [{"scene_id": a, "weight": 1.0}],
      "the saved trigger round-trips its scene_pool through the store")

print("\nPart B: ALL CHECKS PASSED")

# ═══ Part C — the demonstration, on one of his own real songs ═════════════

# B9 deliberately rigged the sequencer config down to one entry to prove
# scene_pool precedence — restore his REAL (seeded) 9-scene config before
# demonstrating "under the sequencer, no metadata".
_reseed_real_scenes_and_sequencer()
all_scenes = scene_store.list_all()

song_uri = args.song_uri
song_title = SONG_TITLES.get(song_uri, song_uri)
song_raw = raw_triggers.get(song_uri)
check(song_raw is not None, f"'{song_title}' ({song_uri}) present in his real "
      f"triggers.json")

fire_scene_trigs = sorted(
    (t for t in song_raw if t["action"]["kind"] == "fire_scene"),
    key=lambda t: t["timestamp_ms"])

print(f"\n--- Part C: {song_title} — {len(fire_scene_trigs)} fire_scene "
      f"triggers ---")

print("\n1. WHAT ITS TRIGGERS DO TODAY (stored scene_id, first 8 of "
      f"{len(fire_scene_trigs)}):")
for t in fire_scene_trigs[:8]:
    print(f"   {fmt_ms(t['timestamp_ms']):>6}  intensity={t['action']['intensity']:.3f}"
          f"  scene_id={t['action']['scene_id']!r}")
check(all(t["action"]["scene_id"] is None for t in fire_scene_trigs),
      f"all {len(fire_scene_trigs)} of this song's fire_scene triggers store "
      f"scene_id=null today — nothing to compare against but 'the sequencer "
      f"picks something at fire time', which is exactly scenario 2 below")

scene_names = {s.id: s.name for s in all_scenes}
prod_engine._rng = Random(args.seed)
picks_unconstrained = [prod_engine._select_scene(t["action"]["intensity"])
                       for t in fire_scene_trigs]
hist_unconstrained = Counter(scene_names.get(p, p) for p in picks_unconstrained)
print(f"\n2. UNDER THE SEQUENCER, NO METADATA (his real "
      f"{len(sequencer_store.load_config().entries)}-scene sequencer config, "
      f"unconstrained kernel draw):")
print(f"   first 8 picks: "
      f"{[scene_names.get(p, p) for p in picks_unconstrained[:8]]}")
print(f"   distribution across all {len(picks_unconstrained)} triggers: "
      f"{dict(hist_unconstrained)}")
distinct_unconstrained = {p for p in picks_unconstrained if p}
check(len(distinct_unconstrained) >= 2,
      f"the unconstrained draw already spans {len(distinct_unconstrained)} "
      f"distinct scenes across this song — the baseline variety a weighted "
      f"subset needs to preserve, not flatten")

# An ILLUSTRATIVE example pool — three of his nine real scenes with
# different weights. NOT a recovered version of any hand-built pool: per
# the brief's own finding, his legacy scene_group pools are not present in
# storage/spectra/triggers.json and cannot be reconstructed from it.
pool_ids_weights = [(s.id, w) for s, w in zip(all_scenes[:3], [3.0, 2.0, 1.0])]
example_pool = [ScenePoolMember(scene_id=sid, weight=w)
               for sid, w in pool_ids_weights]
prod_engine._rng = Random(args.seed)
picks_pool = [prod_engine._select_scene_from_pool(example_pool)
             for _ in fire_scene_trigs]
hist_pool = Counter(scene_names.get(p, p) for p in picks_pool)
print(f"\n3. WITH A WEIGHTED SUBSET (example: "
      f"{[(scene_names[sid], w) for sid, w in pool_ids_weights]}):")
print(f"   first 8 picks: {[scene_names.get(p, p) for p in picks_pool[:8]]}")
print(f"   distribution across all {len(picks_pool)} triggers: "
      f"{dict(hist_pool)}")

pool_scene_ids = {sid for sid, _ in pool_ids_weights}
check(all(p in pool_scene_ids for p in picks_pool),
      "every single weighted-subset pick landed inside the named 3-scene "
      "pool — never one of the other 6 real scenes on the room")
check(len(set(picks_pool)) >= 2,
      f"the weighted subset still produced {len(set(picks_pool))} distinct "
      f"scenes across the song, not a collapse to one repeated scene — his "
      f"variety survived, just narrowed and biased as asked")
ranked = hist_pool.most_common()
check(ranked[0][0] == scene_names[pool_ids_weights[0][0]],
      f"the highest-weighted pool member ({scene_names[pool_ids_weights[0][0]]}, "
      f"weight={pool_ids_weights[0][1]}) drew most often: {ranked}")

print(f"\nSIDE BY SIDE, first 8 of {len(fire_scene_trigs)} triggers "
      f"('{song_title}'):")
print(f"   {'time':>6}  {'intensity':>9}  {'today':<10}  "
      f"{'no metadata':<16}  {'weighted subset':<16}")
for i, t in enumerate(fire_scene_trigs[:8]):
    today = "null"
    no_meta = scene_names.get(picks_unconstrained[i], str(picks_unconstrained[i]))
    weighted = scene_names.get(picks_pool[i], str(picks_pool[i]))
    print(f"   {fmt_ms(t['timestamp_ms']):>6}  {t['action']['intensity']:>9.3f}  "
          f"{today:<10}  {no_meta:<16}  {weighted:<16}")

print("\nPart C: ALL CHECKS PASSED")
print("\nALL CHECKS PASSED")
