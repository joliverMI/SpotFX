"""House lighting modes override the global Dark/Light display mode
(the Admiral, 2026-10-06, verbatim: "house lighting modes should override
dark mode").

The proofs:

  1. `house.house_overrides_display()` — the one predicate every gate below
     consults: True while a house mode governs the room's own look right
     now (the layer may act, not standby/off/refused, and the mode isn't
     currently handed to a music "show" phase); False the instant music
     takes over, the layer stops acting, or no mode is set. A "calm"/
     "ignore" mode counts as driving even while music plays (it keeps its
     look through music exactly as `scene_deferral` already treats it).

  2. `dark_light.reconcile()` withholds dark_lock/Light's forced write/the
     "default"-mode stale repaint on every virtual while
     `house_overrides_display()` reads True — proven against a REAL
     headless render host (fx.headless + fx.facade), the same frame-level
     proof shape tests/test_dark_light.py already uses. With it reading
     False, every one of those three writes lands exactly as before this
     feature (the regression bar: "music show plus Dark is dimmed as
     before").

  3. house.py's own `_enter`/`_hand_in`/`_go_inactive` hooks call
     `dark_light.reconcile()` again, with the room's CURRENT stored
     display_mode, every time the house layer's own driving state flips —
     which is what makes dark_lock reassert itself the instant music takes
     the room back from a resting mode with no PUT required ("switching
     from house to music re-applies Dark").

No live storage, no LedFX HTTP, no audio hardware.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from spectra.models.house_mode import HouseMode


def _run(coro):
    return asyncio.run(coro)


# ═══ 1. house_overrides_display() ═══════════════════════════════════════════

@pytest.fixture
def gate_open(monkeypatch):
    from spectra.services import house
    monkeypatch.setattr(house, "gate", lambda: (None, None))


def _set_mode(mode: HouseMode) -> None:
    from spectra.services import house_store
    saved = house_store.put_mode(mode)
    house_store.state().mode_id = saved.id


def test_resting_show_mode_not_playing_overrides_display(gate_open):
    from spectra.services import house
    _set_mode(HouseMode(name="Standard", music="show"))
    house.deps = house.Deps(playing=lambda: False)
    assert house.house_overrides_display() is True


def test_music_phase_show_mode_does_not_override_display(gate_open):
    from spectra.services import house
    _set_mode(HouseMode(name="Standard", music="show"))
    house.deps = house.Deps(playing=lambda: True)
    assert house.house_overrides_display() is False


def test_calm_mode_overrides_display_even_while_playing(gate_open):
    from spectra.services import house
    _set_mode(HouseMode(name="Chill", music="calm"))
    house.deps = house.Deps(playing=lambda: True)
    assert house.house_overrides_display() is True


def test_ignore_mode_overrides_display_even_while_playing(gate_open):
    from spectra.services import house
    _set_mode(HouseMode(name="Hands Off", music="ignore"))
    house.deps = house.Deps(playing=lambda: True)
    assert house.house_overrides_display() is True


def test_no_mode_set_never_overrides_display(gate_open):
    from spectra.services import house
    house.deps = house.Deps(playing=lambda: False)
    assert house.house_overrides_display() is False


def test_layer_not_active_never_overrides_display(monkeypatch):
    """Standby/off/refused — layer_active() is False — must NOT count as
    the house driving, even though a "show" mode not currently playing
    would otherwise read as resting. This is the one place
    house_overrides_display deliberately differs from scene_deferral
    (which also answers during standby, since a preview still judges its
    frozen look against it)."""
    from spectra.services import house
    monkeypatch.setattr(house, "gate", lambda: ("standby", "a capture holds the room"))
    _set_mode(HouseMode(name="Standard", music="show"))
    house.deps = house.Deps(playing=lambda: False)
    assert house.house_overrides_display() is False


def test_unreadable_house_state_never_overrides_display(monkeypatch):
    from spectra.services import house

    def boom():
        raise RuntimeError("boom")
    monkeypatch.setattr(house, "gate", boom)
    _set_mode(HouseMode(name="Standard", music="show"))
    assert house.house_overrides_display() is False


# ═══ 2. dark_light.reconcile() withholds while house drives ════════════════

from fx import headless as _headless_mod

VID = _headless_mod.DEFAULT_VIRTUAL_ID


def _categories(monkeypatch, tmp_path) -> None:
    from fx import device_model
    path = tmp_path / "device_categories.json"
    path.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]}}))
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", path)
    device_model.refresh()


def _own(monkeypatch, tmp_path) -> None:
    from fx import light_ownership as lo
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", path)


@pytest.fixture(autouse=True)
def _isolated_dark_light_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "DARK_LIGHT_SNAPSHOT_FILE", tmp_path / "dark_light_snapshot.json")


def test_reconcile_skips_dark_lock_and_light_write_while_house_drives(tmp_path, monkeypatch):
    from fx import facade, headless
    from spectra.services import dark_light, house

    _own(monkeypatch, tmp_path)
    _categories(monkeypatch, tmp_path)
    monkeypatch.setattr(house, "house_overrides_display", lambda: True)

    async def main():
        hosted = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(hosted)
        virtual = hosted.virtuals.get(VID)
        headless.attach_effect(hosted, virtual, "concentric",
                               {"background_color": "#ff0000",
                                "background_brightness": 1.0})

        dark_result = await dark_light.reconcile("dark", [], [])
        assert dark_result["status"] == "dark"
        assert dark_result["locked"] == []
        assert dark_result["house_overridden"] == [VID]
        # dark_lock stayed False — the house mode's own look is untouched.
        assert virtual.config["dark_lock"] is False
        assert virtual.active_effect.config["background_color"] == "#ff0000"

        light_result = await dark_light.reconcile("light", [], [], "#201830", 0.3)
        assert light_result["status"] == "light"
        assert light_result.get("lit", []) == []
        assert light_result["house_overridden"] == [VID]
        # the forced Light background never landed on it either.
        assert virtual.active_effect.config["background_color"] == "#ff0000"

        await hosted.shutdown()

    _run(main())


def test_reconcile_locks_normally_when_house_is_not_driving(tmp_path, monkeypatch):
    """Regression bar: "music show plus Dark is dimmed as before" —
    house_overrides_display() reading False changes nothing about the
    pre-existing mechanism."""
    from fx import facade, headless
    from spectra.services import dark_light, house

    _own(monkeypatch, tmp_path)
    _categories(monkeypatch, tmp_path)
    monkeypatch.setattr(house, "house_overrides_display", lambda: False)

    async def main():
        hosted = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(hosted)
        virtual = hosted.virtuals.get(VID)
        headless.attach_effect(hosted, virtual, "concentric",
                               {"background_color": "#ff0000",
                                "background_brightness": 1.0})

        dark_result = await dark_light.reconcile("dark", [], [])
        assert dark_result["status"] == "dark"
        assert dark_result["locked"] == [VID]
        assert "house_overridden" not in dark_result
        assert virtual.config["dark_lock"] is True
        assert virtual.active_effect.config["background_color"] == "#000000"

        await hosted.shutdown()

    _run(main())


def test_reconcile_default_skips_stale_repaint_while_house_drives(tmp_path, monkeypatch):
    """The "default"-mode snapshot restore must not stomp a house mode's
    current look with whatever showed before Dark was ever engaged —
    the same reasoning the music-playing gate already uses, named
    `repaint_skipped: "house_mode"`."""
    from fx import facade, headless
    from spectra.services import dark_light, house

    _own(monkeypatch, tmp_path)
    _categories(monkeypatch, tmp_path)

    async def main():
        hosted = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(hosted)
        virtual = hosted.virtuals.get(VID)
        headless.attach_effect(hosted, virtual, "concentric",
                               {"background_color": "#ff0000",
                                "background_brightness": 1.0})

        monkeypatch.setattr(house, "house_overrides_display", lambda: False)
        await dark_light.reconcile("dark", [], [])
        assert virtual.active_effect.config["background_color"] == "#000000"

        # the house mode now starts driving — the SAME resync _enter() calls
        # before it fires its own scene, clearing dark_lock first.
        monkeypatch.setattr(house, "house_overrides_display", lambda: True)
        await dark_light.reconcile("dark", [], [])
        assert virtual.config["dark_lock"] is False
        # the house mode's own fire then paints its authored colour.
        virtual.active_effect.update_config({"background_color": "#00aa00"})

        # he flips the STORED mode back to "default" while the house mode
        # is still driving — the stale pre-dark snapshot must not stomp it.
        default_result = await dark_light.reconcile("default", [], [])
        assert default_result["status"] == "default"
        assert default_result["repaint_skipped"] == "house_mode"
        assert default_result["restored"] == []
        # dark_lock cleared, but the house's own current colour survives —
        # the stale "#ff0000" snapshot was never forced back onto it.
        assert virtual.config["dark_lock"] is False
        assert virtual.active_effect.config["background_color"] == "#00aa00"

        await hosted.shutdown()

    _run(main())


# ═══ 3. the hooks: house.py re-syncs dark_light as its own state flips ═════

@pytest.fixture
def world(tmp_path, monkeypatch):
    """A minimal house world (fire_scene/apply_set faked, like
    tests/test_house_lighting.py's own fixture) plus a spy on
    dark_light.reconcile so the WIRING can be proven without a render
    host — proof 2 above already proves what reconcile() does once
    called."""
    from spectra import config as scfg
    from spectra.models.scene import SceneV2
    from spectra.services import dark_light, house, room_controls, scene_store

    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    scene = SceneV2(name="Star")
    scene_store.save(scene)

    calls: list = []

    async def fake_reconcile(mode, *a, **kw):
        calls.append(mode)
        return {"status": mode}
    monkeypatch.setattr(dark_light, "reconcile", fake_reconcile)

    clock = {"now": 1000.0}
    state = {"playing": False}

    async def fire_scene(scene_id, **kw):
        return {"dry_run": False}

    async def apply_set(card, glide_ms):
        return {"applied": card.id}

    async def sync_hue():
        return None
    house.deps = house.Deps(
        playing=lambda: state["playing"], fire_scene=fire_scene,
        apply_set=apply_set, sync_hue=sync_hue, clock=lambda: clock["now"])
    monkeypatch.setattr(house, "gate", lambda: (None, None))

    room_controls.save_room_controls(room_controls.RoomControlState(display_mode="dark"))

    class W:
        pass
    w = W()
    w.house, w.calls, w.state, w.clock, w.scene = house, calls, state, clock, scene
    return w


def _mode(name="Standard", **kw) -> HouseMode:
    from spectra.services import house_store
    base = dict(name=name, scenes=[])
    base.update(kw)
    return house_store.put_mode(HouseMode(**base))


def test_entering_resting_resyncs_dark_light_with_the_stored_mode(world):
    _mode("Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert world.calls[-1] == "dark"


def test_switching_from_house_to_music_resyncs_dark_light_again(world):
    _mode("Standard", transitions={"music_debounce_s": 1})
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    before = len(world.calls)
    world.state["playing"] = True
    _run(world.house.tick())
    assert world.house.status_dict()["phase"] == "music"
    assert len(world.calls) > before
    assert world.calls[-1] == "dark"


def test_clearing_the_mode_resyncs_dark_light_too(world):
    _mode("Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    before = len(world.calls)
    _run(world.house.set_mode(clear=True, source="spectra"))
    assert len(world.calls) > before
    assert world.calls[-1] == "dark"


def test_no_resync_call_when_the_stored_mode_is_default(world):
    from spectra.services import room_controls
    room_controls.save_room_controls(room_controls.RoomControlState(display_mode="default"))
    _mode("Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert world.calls == []
