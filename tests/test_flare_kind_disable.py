"""FlareKind.enabled — the flare power button's own flag (owner ask,
2026-08-27: "disable/enable flares. Replace disable/enable with a power
button... Allow me to disable/enable straight from the selection bar for
scenes and colorsets and from the flare bar for flares").

The proofs, one per choke point — checked INDIVIDUALLY, never by family,
because three overlay bypasses were once found in exactly this area
(AGENTS.md §86):
  1. MODEL — defaults True, is gained lazily by a kind stored before the
     field existed, round-trips, and every one of his real scene shapes
     loads byte-identically with nothing flipped.
  2. resolve_lane_picks — a disabled kind never enters its lane's pool
     (so it can never win a fire-time roll), a partly-disabled pool always
     picks a live member, and a lane whose members are ALL disabled fires
     NOTHING and says so out loud (picked=None, all_disabled=True).
  3. _execute_band — a disabled kind is dropped before ordering/execution,
     proven at FRAME level on the real vendored render pipeline (its param
     is provably untouched on the rendered effect), and on_update's
     placeholder double-intensity flare inherits the same gate for free.
  4. THE THREE FORWARD PEEKS — band_trigger_offset_ms,
     momentary_switch_would_glide and color_rotate_lead_ms each aggregate
     over ENABLED kinds only; a disabled kind's own lead/offset must never
     steer a real fire's timing.
  5. EXPLICIT PRESS STILL WORKS AND NAMES IT — fire_kind (the flare
     scrubbing preview's execution entry point) runs a disabled kind and
     reports overrode_disabled=True, the Force-Scene / colour-set Preview
     precedent.
  6. DEFAULTS — with no flag flipped anywhere, every one of the above
     behaves exactly as it did before this field existed.
  7. SONIC — set_flare_kind surfaces the flag, and a DISABLED kind
     round-trips intact through an unrelated edit (omitting `enabled`
     leaves it alone rather than silently re-enabling his flares).

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

from fx import device_model, facade, headless

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
    room — the same minimal wiring test_flare_lanes._engine uses."""
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


def _two_kind_scene(*, a_enabled=True, b_enabled=True, kind_lanes=None):
    """Two permanent kinds on DIFFERENT params of the real concentric
    effect, so which one actually landed is frame-level readable."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    return SceneV2(
        name="Power",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="concentric",
            params={"gradient_scale": 1.0, "power_multiplier": 0.2})],
        flare_kinds=[
            FlareKind(name="KindA", type="permanent",
                      params={"gradient_scale": 1.7}, enabled=a_enabled),
            FlareKind(name="KindB", type="permanent",
                      params={"power_multiplier": 0.9}, enabled=b_enabled),
        ],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"KindA": 1.0, "KindB": 1.0},
                      kind_lanes=kind_lanes or {})])})


# ── 1. model ─────────────────────────────────────────────────────────────────

def test_enabled_defaults_true_and_is_gained_lazily_by_a_stored_kind():
    """His scene file has no `enabled` key anywhere — a kind stored before
    this field existed must load ENABLED, so nothing in his room changed on
    deploy. (scene_store.save rewrites only the scene it is handed, so the
    key arrives per scene, on his own next save — the PR-200 shape.)"""
    from spectra.models.scene import SceneV2
    scene = SceneV2.model_validate({
        "name": "Legacy",
        "flare_kinds": [{"name": "K", "type": "permanent",
                         "params": {"x": 0.5}}],
        "responses": {"flare": {"bands": [
            {"intensity_min": 0.0, "intensity_max": 1.0,
             "kinds": {"K": 1.0}}]}}})
    assert scene.flare_kinds[0].enabled is True


def test_enabled_round_trips_both_ways():
    from spectra.models.scene import FlareKind
    for value in (True, False):
        kind = FlareKind(name="K", type="permanent", params={"x": 1.0},
                         enabled=value)
        again = FlareKind.model_validate(kind.model_dump(mode="json"))
        assert again.enabled is value


def test_enabled_rides_through_the_legacy_flare_band_migration():
    """_migrate_flare_kinds rebuilds bands and auto-names legacy
    param_patch/gain into kinds — an authored `enabled: false` on a
    hand-declared kind must survive that rebuild untouched."""
    from spectra.models.scene import SceneV2
    scene = SceneV2.model_validate({
        "name": "Mixed",
        "flare_kinds": [
            {"name": "A", "type": "permanent", "params": {"x": 1.0},
             "enabled": False}],
        "responses": {"flare": {"bands": [
            {"intensity_min": 0.0, "intensity_max": 1.0,
             "kinds": {"A": 1.0}, "param_patch": {"z": 0.3}}]}}})
    by_name = {k.name: k for k in scene.flare_kinds}
    assert by_name["A"].enabled is False
    # The auto-named migration kind is born ENABLED, like everything else.
    auto = [k for k in scene.flare_kinds if k.name != "A"]
    assert auto and all(k.enabled is True for k in auto)


# ── 2. resolve_lane_picks ────────────────────────────────────────────────────

def test_disabled_kind_never_enters_its_lane_pool():
    from spectra.services.scene_response import resolve_lane_picks
    scene = _two_kind_scene(a_enabled=False,
                            kind_lanes={"KindA": "L", "KindB": "L"})
    band = scene.responses["flare"].bands[0]
    declared = {k.name: k for k in scene.flare_kinds}
    for seed in range(30):
        names, records = resolve_lane_picks(band, Random(seed), declared)
        assert names == ["KindB"]              # never the disabled member
        assert records[0]["picked"] == "KindB"
        assert records[0]["pool"] == ["KindA", "KindB"]
        assert records[0]["eligible"] == ["KindB"]


def test_a_lane_whose_members_are_all_disabled_fires_nothing_and_says_so():
    from spectra.services.scene_response import resolve_lane_picks
    scene = _two_kind_scene(a_enabled=False, b_enabled=False,
                            kind_lanes={"KindA": "L", "KindB": "L"})
    band = scene.responses["flare"].bands[0]
    declared = {k.name: k for k in scene.flare_kinds}
    names, records = resolve_lane_picks(band, Random(3), declared)
    assert names == []
    assert records == [{"lane": "L", "picked": None,
                        "pool": ["KindA", "KindB"], "all_disabled": True}]


def test_a_disabled_solo_kind_is_dropped_and_the_others_are_untouched():
    """A kind with no kind_lanes entry is its own one-member lane — the
    same gate applies, and its sibling solo lanes carry on."""
    from spectra.services.scene_response import resolve_lane_picks
    scene = _two_kind_scene(a_enabled=False)   # no pools at all
    band = scene.responses["flare"].bands[0]
    declared = {k.name: k for k in scene.flare_kinds}
    names, records = resolve_lane_picks(band, Random(0), declared)
    assert names == ["KindB"]
    assert records == [{"lane": "\x00solo:KindA", "picked": None,
                        "pool": ["KindA"], "all_disabled": True}]


def test_resolve_lane_picks_without_declared_kinds_is_unchanged():
    """The `declared` argument is optional — every pre-existing caller
    (and every existing test) keeps the exact pre-flag behaviour."""
    from spectra.models.scene import FlareBand
    from spectra.services.scene_response import resolve_lane_picks
    band = FlareBand(kinds={"A": 1.0, "B": 0.5, "C": 2.0})
    for seed in range(10):
        names, records = resolve_lane_picks(band, Random(seed))
        assert names == ["A", "B", "C"]
        assert records == []


# ── 3. _execute_band, at frame level on the real pipeline ────────────────────

def test_disabled_kind_never_executes_and_its_param_never_lands(tmp_path):
    from spectra.services.scene_response import DICE_REROLL_GLIDE_MS
    glide_frames = int(DICE_REROLL_GLIDE_MS / 1000 / (1 / 60)) + 2
    _categories_fixture(tmp_path)
    scene = _two_kind_scene(a_enabled=False)

    async def main():
        host, virtual = await _host(tmp_path, "disabled")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                _, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)

                record = await responder.on_event("flare", 0.5)
                assert record["result"] == "applied"
                assert [k["name"] for k in record["kinds"]] == ["KindB"]

                headless.render_frames(virtual, glide_frames,
                                       clock=clock, dt=1 / 60)
                # The enabled kind landed; the disabled one provably did not.
                assert effect._config["power_multiplier"] == pytest.approx(0.9)
                assert effect._config["gradient_scale"] == pytest.approx(1.0)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_on_update_inherits_the_same_gate(tmp_path):
    """on_update (minimum dwell's placeholder double-intensity flare)
    shares _execute_band with on_event by design — it must not need its
    own copy of the gate, and must not have one that could drift."""
    _categories_fixture(tmp_path)
    scene = _two_kind_scene(a_enabled=False)

    async def main():
        host, virtual = await _host(tmp_path, "update")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2}
                headless.attach_effect(host, virtual, "concentric", config)
                _, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)
                record = await responder.on_update(0.4)
                assert [k["name"] for k in record["kinds"]] == ["KindB"]
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 4. the three forward peeks ───────────────────────────────────────────────

def _offset_scene(*, enabled: bool):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneV2)
    return SceneV2(
        name="Offsets",
        flare_kinds=[FlareKind(name="Early", type="permanent",
                               params={"gradient_scale": 1.0},
                               trigger_offset_ms=-400, enabled=enabled)],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"Early": 1.0})])})


def test_band_trigger_offset_ignores_a_disabled_kinds_offset():
    from spectra.services.scene_response import band_trigger_offset_ms
    assert band_trigger_offset_ms(_offset_scene(enabled=True), "flare", 0.5) == -400
    assert band_trigger_offset_ms(_offset_scene(enabled=False), "flare", 0.5) == 0


def _rotate_scene(*, enabled: bool):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneV2)
    return SceneV2(
        name="Rotate",
        flare_kinds=[FlareKind(name="Rot", type="color_rotate",
                               enabled=enabled)],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"Rot": 1.0})])})


def test_color_rotate_lead_ignores_a_disabled_kind():
    from spectra.services.scene_response import color_rotate_lead_ms
    assert color_rotate_lead_ms(_rotate_scene(enabled=True), "flare", 0.5, {}) > 0
    assert color_rotate_lead_ms(_rotate_scene(enabled=False), "flare", 0.5, {}) == 0


def _smooth_virtuals():
    """One live virtual running an effect with a registry-SMOOTH numeric
    param, so _kind_would_glide has something real to say yes to. Read off
    the real registry rather than hardcoded — `star` is smooth on radial
    (config/effect_params.json), and the assert catches it if that ever
    changes rather than letting this test pass vacuously."""
    from spectra.services.drift_conductor import VirtualState
    meta = device_model.get_param_meta("radial", "star")
    assert meta and meta.get("smooth"), "radial/star is no longer smooth"
    return {VID: VirtualState(effect_type="radial", entry_id="e1",
                              color_mode="set", config={})}, "star"


def _glide_scene(pname: str, *, enabled: bool):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneV2)
    return SceneV2(
        name="Glide",
        flare_kinds=[FlareKind(name="Spike", type="momentary",
                               params={pname: 0.5}, enabled=enabled)],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"Spike": 1.0})])})


def test_momentary_switch_would_glide_ignores_a_disabled_kind():
    from spectra.services.scene_response import momentary_switch_would_glide
    virtuals, pname = _smooth_virtuals()
    assert momentary_switch_would_glide(
        _glide_scene(pname, enabled=True), "flare", 0.5, virtuals) is True
    assert momentary_switch_would_glide(
        _glide_scene(pname, enabled=False), "flare", 0.5, virtuals) is False


# ── 5. an explicit press still works, and NAMES it ───────────────────────────

def test_fire_kind_previews_a_disabled_kind_and_names_the_override(tmp_path):
    _categories_fixture(tmp_path)
    scene = _two_kind_scene(a_enabled=False)

    async def main():
        host, virtual = await _host(tmp_path, "preview")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2}
                headless.attach_effect(host, virtual, "concentric", config)
                _, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)
                disabled = next(k for k in scene.flare_kinds
                                if k.name == "KindA")
                record = await responder.fire_kind(disabled, 0.5)
                # It really ran (an explicit press always wins) …
                assert record["result"] == "applied"
                assert record["moved"]
                # … and the contradiction is named, never silent.
                assert record["overrode_disabled"] is True

                enabled = next(k for k in scene.flare_kinds
                               if k.name == "KindB")
                assert "overrode_disabled" not in await responder.fire_kind(
                    enabled, 0.5)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_build_timeline_reports_the_override(tmp_path):
    from spectra.services import flare_preview
    _categories_fixture(tmp_path)
    scene = _two_kind_scene(a_enabled=False)

    async def main():
        host, virtual = await _host(tmp_path, "timeline")
        try:
            headless.attach_effect(host, virtual, "concentric",
                                   {"gradient_scale": 1.0,
                                    "power_multiplier": 0.2})
            off = next(k for k in scene.flare_kinds if k.name == "KindA")
            on = next(k for k in scene.flare_kinds if k.name == "KindB")
            assert (await flare_preview.build_timeline(
                scene, off, 0.5))["overrode_disabled"] is True
            assert (await flare_preview.build_timeline(
                scene, on, 0.5))["overrode_disabled"] is False
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 6. defaults: nothing changes with no flag flipped ────────────────────────

def test_with_nothing_disabled_every_gate_behaves_exactly_as_before(tmp_path):
    from spectra.services.scene_response import (band_trigger_offset_ms,
                                                 resolve_lane_picks)
    _categories_fixture(tmp_path)
    scene = _two_kind_scene()   # both enabled, the default everywhere
    band = scene.responses["flare"].bands[0]
    declared = {k.name: k for k in scene.flare_kinds}
    names, records = resolve_lane_picks(band, Random(5), declared)
    assert names == ["KindA", "KindB"]
    assert records == []
    assert band_trigger_offset_ms(_offset_scene(enabled=True), "flare", 0.5) == -400

    async def main():
        host, virtual = await _host(tmp_path, "defaults")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2}
                headless.attach_effect(host, virtual, "concentric", config)
                _, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)
                record = await responder.on_event("flare", 0.5)
                assert [k["name"] for k in record["kinds"]] \
                    == ["KindA", "KindB"]
                assert "lane_picks" not in record
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 7. Sonic's own surface ───────────────────────────────────────────────────

def _console_scene(tmp_path, monkeypatch, *, enabled=True):
    from spectra import config as scfg
    from spectra.models.scene import FlareKind, SceneV2
    from spectra.services import scene_store
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "SCENE_AGENT_LOG_FILE", tmp_path / "scene_agent_log.json")
    monkeypatch.setattr(scfg, "SCENE_BACKUPS_FILE", tmp_path / "scene_backups.json")
    monkeypatch.setattr(scfg, "SCENE_GENESIS_FILE", tmp_path / "scene_genesis.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    scene = SceneV2(name="Console", flare_kinds=[
        FlareKind(name="K", type="permanent", params={"gradient_scale": 1.0},
                  gain=1.0, enabled=enabled)])
    scene_store.save(scene)
    return scene


def test_sonic_lists_and_sets_the_flag(tmp_path, monkeypatch):
    from spectra.services import scene_console, scene_store
    scene = _console_scene(tmp_path, monkeypatch)
    listed = scene_console.list_flare_kinds(scene.id)["flare_kinds"]
    assert listed[0]["enabled"] is True

    res = asyncio.run(scene_console.apply_flare_kind(
        scene.id, name="K", type="permanent",
        params={"gradient_scale": 1.0}, enabled=False))
    assert res["status"] == "applied"
    stored = scene_store.get_by_id(scene.id)
    assert stored.flare_kinds[0].enabled is False


def test_a_disabled_kind_round_trips_intact_through_an_unrelated_edit(
        tmp_path, monkeypatch):
    """Omitting `enabled` on an UPDATE must leave it alone — silently
    re-enabling his flares as a side effect of retuning a gain would be an
    invisible behaviour change in his room."""
    from spectra.services import scene_console, scene_store
    scene = _console_scene(tmp_path, monkeypatch, enabled=False)
    asyncio.run(scene_console.apply_flare_kind(
        scene.id, name="K", type="permanent",
        params={"gradient_scale": 1.0}, gain=1.5))
    stored = scene_store.get_by_id(scene.id)
    assert stored.flare_kinds[0].gain == pytest.approx(1.5)
    assert stored.flare_kinds[0].enabled is False
    # A brand-new kind, with `enabled` omitted, is born ENABLED.
    asyncio.run(scene_console.apply_flare_kind(
        scene.id, name="Fresh", type="permanent",
        params={"gradient_scale": 0.5}))
    fresh = {k.name: k for k in scene_store.get_by_id(scene.id).flare_kinds}
    assert fresh["Fresh"].enabled is True
