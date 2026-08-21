"""Flare-kind LANES — pick-one-per-lane pools (owner ask, 2026-08-21;
his words: "all lanes fire together, but pick one action within each
lane... more similar to spotfx... randomly pick one of them by some kind
of weighting. For now, just even weights" — the legacy MorphLane /
_pick_morph_lanes shape ported onto FlareBand attachments).

The proofs:
  1. MODEL — FlareBand.kind_lanes defaults to {} on every scene that
     predates the field, validates membership (an entry must reference an
     attached kind, a lane name must be non-empty), round-trips, and rides
     through the legacy flare-band migration untouched.
  2. resolve_lane_picks — a band with no pools returns EVERY kind in
     band.kinds' own insertion order (the blast-radius guarantee: 25 of
     his 28 real bands hold more than one kind, and all of them keep
     firing everything); a pool yields exactly one member; picked order is
     always kinds order (lanes decide WHO fires, never execution order);
     even weights over seeded draws.
  3. ZERO-CHANGE on the real render pipeline — a multi-kind band with no
     kind_lanes fires every kind, both in the fire record and as landed
     frame-level values.
  4. A pooled band fires exactly ONE member per fire, re-resolved fresh
     each fire (both members win across fires under the seeded rng), the
     loser's param provably untouched on the rendered effect, and the
     fire record names the pick (lane_picks) so a "why didn't my other
     colour flare run" is a log lookup.
  5. on_update (minimum dwell's placeholder double-intensity flare) runs
     the SAME pick — it shares _execute_band with on_event by design.

No LedFX service, no HTTP, no audio hardware (fx.headless.silence_audio).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless
from fx import device_model

VID = headless.DEFAULT_VIRTUAL_ID


def _run(coro):
    return asyncio.run(coro)


def _categories_fixture(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"], "role": None}}))


async def _host(tmp_path, sub: str):
    host = await headless.start_headless_host(str(tmp_path / sub))
    facade.set_host(host)
    return host, host.virtuals.get(VID)


def _engine(clock, *, rng_seed=7):
    """Conductor + response engine on the FacadeExecutor with an in-memory
    room — the same minimal wiring test_spectra_engine._engine uses."""
    from spectra.models.sequencer import SequencerConfig
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    room_box = [cj.RoomColorState()]
    executor = FacadeExecutor(
        clock=lambda: clock.now,
        room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 0.5,
        drift_profiles=lambda: {}, curve_profiles=lambda: {},
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st),
        set_position=lambda sid: None,
        set_cards=lambda: [],
        sequencer_config=lambda: SequencerConfig(),
        gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(),
        rng=Random(11))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(rng_seed),
        clock=lambda: clock.now,
        sequencer_config=lambda: SequencerConfig(),
        curve_profiles=lambda: {},
        eligible_sets=lambda sc: {},
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st))
    return executor, conductor, responder


def _fire(conductor, scene, config):
    dev = scene.devices[0]
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": dev.effect_type,
        "config": dict(config), "entry_id": dev.id,
        "color_mode": dev.color.mode}])


def _pooled_scene(kind_lanes):
    """Two permanent kinds on DIFFERENT params of the real concentric
    effect, so which one actually landed is frame-level readable."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    return SceneV2(
        name="Lanes",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="concentric",
            params={"gradient_scale": 1.0, "power_multiplier": 0.2})],
        flare_kinds=[
            FlareKind(name="PoolA", type="permanent",
                      params={"gradient_scale": 1.7}),
            FlareKind(name="PoolB", type="permanent",
                      params={"power_multiplier": 0.9}),
        ],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"PoolA": 1.0, "PoolB": 1.0},
                      kind_lanes=kind_lanes)])})


# ── 1. model ─────────────────────────────────────────────────────────────────

def test_kind_lanes_defaults_empty_on_legacy_scene_json():
    from spectra.models.scene import SceneV2
    scene = SceneV2.model_validate({
        "name": "Legacy",
        "flare_kinds": [{"name": "K", "type": "permanent",
                         "params": {"x": 0.5}}],
        "responses": {"flare": {"bands": [
            {"intensity_min": 0.0, "intensity_max": 1.0,
             "kinds": {"K": 1.0}}]}}})
    assert scene.responses["flare"].bands[0].kind_lanes == {}


def test_kind_lanes_round_trips_and_validates_membership():
    from pydantic import ValidationError
    from spectra.models.scene import FlareBand, SceneV2
    band = FlareBand(kinds={"A": 1.0, "B": 0.5},
                     kind_lanes={"A": "colour", "B": "colour"})
    assert FlareBand.model_validate(
        band.model_dump(mode="json")).kind_lanes == {"A": "colour",
                                                     "B": "colour"}
    with pytest.raises(ValidationError, match="not attached"):
        FlareBand(kinds={"A": 1.0}, kind_lanes={"Z": "colour"})
    with pytest.raises(ValidationError, match="empty lane name"):
        FlareBand(kinds={"A": 1.0}, kind_lanes={"A": "  "})
    # A one-member pool is valid (mid-edit saves must not refuse) and
    # behaviourally identical to no entry — the UI prunes it, the model
    # tolerates it.
    solo = FlareBand(kinds={"A": 1.0}, kind_lanes={"A": "colour"})
    assert solo.kind_lanes == {"A": "colour"}
    # Whole-scene validation still governs the band (kinds ⊆ declared,
    # and kind_lanes ⊆ kinds transitively).
    scene = _pooled_scene({"PoolA": "colour", "PoolB": "colour"})
    again = SceneV2.model_validate(scene.model_dump(mode="json"))
    assert again.responses["flare"].bands[0].kind_lanes \
        == {"PoolA": "colour", "PoolB": "colour"}


def test_kind_lanes_rides_through_the_legacy_migration():
    """_migrate_flare_kinds rebuilds every band dict ({**band, ...}) while
    auto-naming legacy param_patch/gain into kinds — an authored
    kind_lanes must survive that rebuild untouched."""
    from spectra.models.scene import SceneV2
    scene = SceneV2.model_validate({
        "name": "Mixed",
        "flare_kinds": [
            {"name": "A", "type": "permanent", "params": {"x": 1.0}},
            {"name": "B", "type": "permanent", "params": {"y": 1.0}}],
        "responses": {"flare": {"bands": [
            {"intensity_min": 0.0, "intensity_max": 1.0,
             "kinds": {"A": 1.0, "B": 1.0},
             "kind_lanes": {"A": "colour", "B": "colour"},
             "param_patch": {"z": 0.3}}]}}})
    band = scene.responses["flare"].bands[0]
    assert band.kind_lanes == {"A": "colour", "B": "colour"}
    assert band.param_patch == {}          # migrated into an auto-named kind
    assert "Flare patch 0–1" in band.kinds  # which joined the band unpooled


# ── 2. resolve_lane_picks ────────────────────────────────────────────────────

def test_no_pools_means_every_kind_fires_in_kinds_order():
    from spectra.models.scene import FlareBand
    from spectra.services.scene_response import resolve_lane_picks
    band = FlareBand(kinds={"A": 1.0, "B": 0.5, "C": 2.0})
    for seed in range(10):
        names, records = resolve_lane_picks(band, Random(seed))
        assert names == ["A", "B", "C"]
        assert records == []


def test_pool_picks_exactly_one_and_solos_always_fire():
    from spectra.models.scene import FlareBand
    from spectra.services.scene_response import resolve_lane_picks
    band = FlareBand(kinds={"A": 1.0, "B": 0.5, "C": 2.0},
                     kind_lanes={"B": "colour", "C": "colour"})
    seen = set()
    for seed in range(40):
        names, records = resolve_lane_picks(band, Random(seed))
        assert names[0] == "A" and len(names) == 2
        assert names[1] in ("B", "C")
        assert records == [{"lane": "colour", "picked": names[1],
                            "pool": ["B", "C"]}]
        seen.add(names[1])
    assert seen == {"B", "C"}


def test_picked_order_is_kinds_order_even_for_non_adjacent_pool_members():
    from spectra.models.scene import FlareBand
    from spectra.services.scene_response import resolve_lane_picks
    # A pooled with C around solo B — the winner keeps its OWN position in
    # kinds order (same-param precedence must not shift when a pool wins).
    band = FlareBand(kinds={"A": 1.0, "B": 1.0, "C": 1.0},
                     kind_lanes={"A": "colour", "C": "colour"})
    for seed in range(20):
        names, _ = resolve_lane_picks(band, Random(seed))
        assert names in (["A", "B"], ["B", "C"])


def test_even_weights_over_seeded_draws():
    from spectra.models.scene import FlareBand
    from spectra.services.scene_response import resolve_lane_picks
    band = FlareBand(kinds={"B": 1.0, "C": 1.0},
                     kind_lanes={"B": "colour", "C": "colour"})
    rng = Random(0)
    counts = {"B": 0, "C": 0}
    for _ in range(400):
        names, _ = resolve_lane_picks(band, rng)
        counts[names[0]] += 1
    # Deterministic under the fixed seed; the bounds prove even odds, not
    # a coincidence of one draw.
    assert 140 <= counts["B"] <= 260 and 140 <= counts["C"] <= 260


# ── 3. zero-change on the real render pipeline (the blast radius) ───────────

def test_band_without_pools_still_fires_every_kind_on_the_harness(tmp_path):
    from spectra.services.scene_response import DICE_REROLL_GLIDE_MS
    glide_frames = int(DICE_REROLL_GLIDE_MS / 1000 / (1 / 60)) + 2
    _categories_fixture(tmp_path)
    scene = _pooled_scene({})   # same two kinds, NO pools

    async def main():
        host, virtual = await _host(tmp_path, "nolanes")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                _, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)

                record = await responder.on_event("flare", 0.5)
                assert record["result"] == "applied"
                assert [k["name"] for k in record["kinds"]] \
                    == ["PoolA", "PoolB"]
                assert "lane_picks" not in record
                headless.render_frames(virtual, glide_frames,
                                       clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.7)
                assert effect._config["power_multiplier"] == pytest.approx(0.9)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 4. a pool fires ONE member, re-resolved per fire ─────────────────────────

def test_pooled_band_fires_exactly_one_member_per_fire(tmp_path):
    from spectra.services.scene_response import DICE_REROLL_GLIDE_MS
    glide_frames = int(DICE_REROLL_GLIDE_MS / 1000 / (1 / 60)) + 2
    _categories_fixture(tmp_path)
    scene = _pooled_scene({"PoolA": "colour", "PoolB": "colour"})

    async def main():
        host, virtual = await _host(tmp_path, "pooled")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                _, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)

                record = await responder.on_event("flare", 0.5)
                assert record["result"] == "applied"
                fired = [k["name"] for k in record["kinds"]]
                assert len(fired) == 1 and fired[0] in ("PoolA", "PoolB")
                assert record["lane_picks"] == [{
                    "lane": "colour", "picked": fired[0],
                    "pool": ["PoolA", "PoolB"]}]

                # Frame-level: the winner landed, the loser's param is
                # provably untouched on the rendered effect.
                headless.render_frames(virtual, glide_frames,
                                       clock=clock, dt=1 / 60)
                if fired[0] == "PoolA":
                    assert effect._config["gradient_scale"] \
                        == pytest.approx(1.7)
                    assert effect._config["power_multiplier"] \
                        == pytest.approx(0.2)
                else:
                    assert effect._config["power_multiplier"] \
                        == pytest.approx(0.9)
                    assert effect._config["gradient_scale"] \
                        == pytest.approx(1.0)

                # Re-resolved fresh on every fire: under the seeded rng both
                # members win within a handful of fires — the pick is never
                # baked into the scene.
                winners = {fired[0]}
                for _ in range(20):
                    rec = await responder.on_event("flare", 0.5)
                    (one,) = [k["name"] for k in rec["kinds"]]
                    winners.add(one)
                    if winners == {"PoolA", "PoolB"}:
                        break
                assert winners == {"PoolA", "PoolB"}
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 5. on_update shares the pick (minimum dwell's placeholder flare) ─────────

def test_on_update_runs_the_same_lane_pick(tmp_path):
    _categories_fixture(tmp_path)
    scene = _pooled_scene({"PoolA": "colour", "PoolB": "colour"})

    async def main():
        host, virtual = await _host(tmp_path, "update")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2}
                headless.attach_effect(host, virtual, "concentric", config)
                _, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)

                record = await responder.on_update(0.25)   # doubled → 0.5
                assert record["result"] == "applied"
                fired = [k["name"] for k in record["kinds"]]
                assert len(fired) == 1 and fired[0] in ("PoolA", "PoolB")
                assert record["lane_picks"][0]["pool"] == ["PoolA", "PoolB"]
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())
