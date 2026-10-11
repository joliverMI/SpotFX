"""The live background FADES, round the colour wheel (fx/background_fade.py,
fx/VENDOR.md #68; the Admiral, 2026-10-11: "when the live background changes
due to a turning on or off of the light/dark mode, it should fade ... default
1s, but when I do it from a light show, i should be able to set the timing in
the step ... This fade should also apply for when we are in hybrid and the
background changes ... colors should fade by rotation around wheel").

Proven on the real `fx.headless` render pipeline (the assembled frame, not a
config read), plus the plumbing from the room setting and the Light Show
step down to the fade length a switch actually uses.
"""
from __future__ import annotations

import asyncio
import colorsys
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fx import background_fade, facade, headless  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

VID = headless.DEFAULT_VIRTUAL_ID
DT = 1 / 60


def _run(coro):
    return asyncio.run(coro)


def _hsv(rgb):
    r, g, b = (float(c) / 255.0 for c in rgb)
    return colorsys.rgb_to_hsv(r, g, b)


# ── 1. the colour path itself ───────────────────────────────────────────────

def test_red_to_blue_rotates_through_magenta_never_grey():
    start, delta = background_fade.path([255, 0, 0], [0, 0, 255])
    for t in np.linspace(0, 1, 21):
        rgb = background_fade.at(start, delta, t)
        h, s, v = _hsv(rgb)
        assert s > 0.99 and v > 0.99, f"left the wheel's rim at t={t}: {rgb}"
        assert rgb[1] < 1, f"went the long way round (through green) at t={t}"
    mid = background_fade.at(start, delta, 0.5)
    assert mid[0] > 250 and mid[2] > 250, f"midpoint is not magenta: {mid}"
    # the straight RGB line it replaces sits at half value — the muddy dip
    rgb_mid = (np.array([255, 0, 0]) + np.array([0, 0, 255])) / 2
    assert _hsv(rgb_mid)[2] < 0.51


def test_hue_takes_the_short_way_round():
    # red (0) -> yellow-green (~0.25): straight up, never through blue
    start, delta = background_fade.path([255, 0, 0], [128, 255, 0])
    assert 0 < delta[0] < 0.5
    for t in np.linspace(0, 1, 11):
        assert background_fade.at(start, delta, t)[2] < 1


def test_to_and_from_black_is_a_brightness_ramp_in_its_own_hue():
    color = [32, 24, 48]                     # Light's #201830, a deep violet
    h0 = _hsv(color)[0]
    for a, b in ((color, [0, 0, 0]), ([0, 0, 0], color)):
        start, delta = background_fade.path(a, b)
        for t in np.linspace(0.05, 0.95, 10):
            rgb = background_fade.at(start, delta, t)
            h, s, _v = _hsv(rgb)
            assert abs(h - h0) < 0.02 and s > 0.4, \
                f"{a}->{b} drifted off its hue / greyed at t={t}: {rgb}"


def test_white_to_a_colour_passes_through_its_paler_self():
    start, delta = background_fade.path([255, 255, 255], [255, 0, 0])
    mid = background_fade.at(start, delta, 0.5)
    h, s, v = _hsv(mid)
    assert h < 0.01 or h > 0.99, f"white->red took another hue: {mid}"
    assert 0.3 < s < 0.7 and v > 0.99, f"not a pale red midway: {mid}"
    # NOT fx.effects.hue_tween_fields' rule, which adopts the colour's full
    # saturation for every achromatic end and jumps straight to red here.
    assert background_fade.at(start, delta, 0.0)[1] > 250


def test_fading_override_is_scoped_and_restored():
    background_fade.set_default_s(1.0)
    assert background_fade.duration_s() == 1.0
    with background_fade.fading(2.5):
        assert background_fade.duration_s() == 2.5
        with background_fade.fading(None):
            assert background_fade.duration_s() == 2.5
    assert background_fade.duration_s() == 1.0
    with background_fade.fading(0):
        assert background_fade.duration_s() == 0.0
    background_fade.set_default_s(99)
    assert background_fade.default_s() == background_fade.MAX_S


# ── 2. on the real render pipeline ──────────────────────────────────────────

async def _host(tmp_path, config):
    host = await headless.start_headless_host(str(tmp_path / "host"))
    virtual = host.virtuals.get(VID)
    effect = headless.attach_effect(
        host, virtual, "singleColor", {"color": "#000000", **config})
    return host, virtual, effect


def _frames(virtual, clock, seconds):
    return headless.render_frames(virtual, max(1, round(seconds / DT)),
                                  clock=clock, dt=DT)


def test_an_instant_background_change_fades_over_the_default_second(tmp_path):
    async def main():
        host, virtual, effect = await _host(
            tmp_path, {"background_color": "#ff0000", "background_brightness": 1.0})
        with headless.fake_clock() as clock:
            _frames(virtual, clock, 0.1)
            effect.update_config({"background_color": "#0000ff"})
            half = _frames(virtual, clock, 0.5)[-1][0]
            h, s, v = _hsv(half)
            assert s > 0.95 and v > 0.95 and half[1] < 1, \
                f"halfway is not on the wheel's rim: {half}"
            assert 0.75 < h < 0.95, f"halfway is not magenta-ish: {half}"
            late = _frames(virtual, clock, 0.6)[-1][0]
            assert list(late) == [0, 0, 255]
        await host.shutdown()

    _run(main())


def test_zero_seconds_is_instant(tmp_path):
    async def main():
        background_fade.set_default_s(0)
        host, virtual, effect = await _host(
            tmp_path, {"background_color": "#ff0000", "background_brightness": 1.0})
        with headless.fake_clock() as clock:
            _frames(virtual, clock, 0.1)
            effect.update_config({"background_color": "#0000ff"})
            assert list(_frames(virtual, clock, DT)[-1][0]) == [0, 0, 255]
        await host.shutdown()

    _run(main())


def test_a_change_mid_fade_starts_from_the_colour_showing_now(tmp_path):
    async def main():
        host, virtual, effect = await _host(
            tmp_path, {"background_color": "#ff0000", "background_brightness": 1.0})
        with headless.fake_clock() as clock:
            _frames(virtual, clock, 0.1)
            effect.update_config({"background_color": "#0000ff"})
            before = _frames(virtual, clock, 0.4)[-1][0].astype(float)
            effect.update_config({"background_color": "#00ff00"})
            after = _frames(virtual, clock, DT)[-1][0].astype(float)
            assert np.abs(after - before).max() < 20, \
                f"the retarget jumped: {before} -> {after}"
            # ...and the new fade runs its full length from there
            assert list(_frames(virtual, clock, 0.8)[-1][0]) != [0, 255, 0]
            assert list(_frames(virtual, clock, 0.3)[-1][0]) == [0, 255, 0]
        await host.shutdown()

    _run(main())


def test_a_repeated_identical_write_never_restarts_a_fade(tmp_path):
    async def main():
        host, virtual, effect = await _host(
            tmp_path, {"background_color": "#ff0000", "background_brightness": 1.0})
        with headless.fake_clock() as clock:
            _frames(virtual, clock, 0.1)
            effect.update_config({"background_color": "#0000ff"})
            for _ in range(10):
                _frames(virtual, clock, 0.1)
                effect.update_config({"background_color": "#0000ff"})
            assert list(_frames(virtual, clock, DT)[-1][0]) == [0, 0, 255]
        await host.shutdown()

    _run(main())


def test_brightness_fades_too_not_just_colour(tmp_path):
    """The old behaviour this replaces: colour eased, brightness CUT — the
    abrupt Dark switch he saw (the clamp drops brightness to 0)."""
    async def main():
        host, virtual, effect = await _host(
            tmp_path, {"background_color": "#ff0000", "background_brightness": 1.0})
        with headless.fake_clock() as clock:
            _frames(virtual, clock, 0.1)
            effect.update_config({"background_brightness": 0.0})
            mid = _frames(virtual, clock, 0.5)[-1][0]
            assert 100 < mid[0] < 155 and mid[1] == 0 and mid[2] == 0, mid
            assert list(_frames(virtual, clock, 0.6)[-1][0]) == [0, 0, 0]
        await host.shutdown()

    _run(main())


def test_an_authored_glide_keeps_its_own_timing(tmp_path):
    """A scene crossfade / flare colour ramp (a tween >= FOLLOW_MIN_S) is a
    fade of its own: the live background follows it exactly and lands when
    IT lands — not a further second later."""
    async def main():
        host, virtual, effect = await _host(
            tmp_path, {"background_color": "#ff0000", "background_brightness": 1.0})
        with headless.fake_clock() as clock:
            _frames(virtual, clock, 0.1)
            effect.start_param_transitions(
                {"background_color": "#0000ff"}, 300, blend="hue")
            _frames(virtual, clock, 0.15)
            assert effect._bg_fade is None
            assert list(_frames(virtual, clock, 0.2)[-1][0]) == [0, 0, 255]
        await host.shutdown()

    _run(main())


def test_a_jump_tween_fades_like_an_instant_write(tmp_path):
    """The engine's jumps are 1 ms tweens (fx_executor.JUMP_MS) — one
    frame, i.e. a cut. They take the background fade."""
    async def main():
        host, virtual, effect = await _host(
            tmp_path, {"background_color": "#ff0000", "background_brightness": 1.0})
        with headless.fake_clock() as clock:
            _frames(virtual, clock, 0.1)
            effect.start_param_transitions({"background_color": "#0000ff"}, 1)
            assert list(_frames(virtual, clock, 0.3)[-1][0]) != [0, 0, 255]
            assert list(_frames(virtual, clock, 0.8)[-1][0]) == [0, 0, 255]
        await host.shutdown()

    _run(main())


# ── 3. dark / light, end to end through dark_light.reconcile ────────────────

@pytest.fixture
def spectra_room(tmp_path, monkeypatch):
    from fx import device_model
    from fx import light_ownership as lo
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "DARK_LIGHT_SNAPSHOT_FILE",
                        tmp_path / "dark_light_snapshot.json")
    own = tmp_path / "ownership.json"
    own.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", own)
    cats = tmp_path / "device_categories.json"
    cats.write_text(json.dumps({"c1": {"id": "c1", "name": "Main", "parent_id": None,
                                       "virtuals": [VID], "effects": ["singleColor"]}}))
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", cats)
    device_model.refresh()
    return tmp_path


def test_dark_and_light_switches_fade_and_a_step_fade_overrides(spectra_room):
    from spectra.services import dark_light

    async def main():
        host, virtual, effect = await _host(
            spectra_room, {"background_color": "#ff0000", "background_brightness": 1.0})
        facade.set_host(host)
        with headless.fake_clock() as clock:
            _frames(virtual, clock, 0.1)

            res = await dark_light.reconcile("dark", [], [])
            assert res["status"] == "dark" and res["fade_s"] == 1.0
            mid = _frames(virtual, clock, 0.5)[-1][0]
            assert 100 < mid[0] < 155 and mid[1] == mid[2] == 0, \
                f"Dark cut instead of dimming in its own red: {mid}"
            assert list(_frames(virtual, clock, 0.6)[-1][0]) == [0, 0, 0]

            # Light with a Light Show step's own 2 s fade
            res = await dark_light.reconcile("light", [], [], "#ff0000", 1.0,
                                             fade_s=2.0)
            assert res["status"] == "light" and res["fade_s"] == 2.0
            mid = _frames(virtual, clock, 1.0)[-1][0]
            assert 100 < mid[0] < 155, f"2 s fade not half way at 1 s: {mid}"
            assert list(_frames(virtual, clock, 1.1)[-1][0]) == [255, 0, 0]

            # back to Hybrid, instant (a step's 0)
            res = await dark_light.reconcile("default", [], [], fade_s=0)
            assert res["status"] == "default"
            # the room's default is untouched by a step's own length
            assert background_fade.default_s() == 1.0
        await host.shutdown()

    _run(main())


def test_light_writes_only_the_background_so_the_effect_is_not_recreated(spectra_room):
    """A write naming the effect's other colour keys recreates it on the
    facade (the colour-key crossfade) — which would swap the wheel fade for
    the virtual's stored crossfade."""
    from spectra.services import dark_light

    async def main():
        host, virtual, effect = await _host(
            spectra_room, {"background_color": "#000000", "background_brightness": 1.0})
        facade.set_host(host)
        await dark_light.reconcile("light", [], [], "#201830", 0.3)
        assert virtual.active_effect is effect
        await host.shutdown()

    _run(main())


# ── 4. the room setting and the Light Show step ─────────────────────────────

def test_saving_the_room_setting_pushes_it_to_the_render_layer(spectra_room):
    from spectra.services import room_controls

    async def main():
        await room_controls.apply_patch({"background_fade_s": 2.5})
        assert background_fade.default_s() == 2.5
        assert room_controls.load_room_controls().background_fade_s == 2.5
        room_controls.push_background_fade(room_controls.RoomControlState())
        assert background_fade.default_s() == 1.0

    _run(main())


def test_the_room_setting_is_bounded_and_sonic_editable():
    from spectra.services import room_controls as rc
    from spectra.services import settings_console as sc
    assert rc.RoomControlState().background_fade_s == 1.0
    assert rc.field_bounds("background_fade_s") == (0.0, 10.0)
    assert sc.SETTINGS_REGISTRY["background_fade_s"].unit.startswith("seconds")


def test_a_display_mode_step_takes_its_own_fade(spectra_room, monkeypatch):
    from spectra.services import dark_light, room_controls, show_actions

    p = show_actions.validate("display_mode", {"mode": "dark", "fade_s": 2})
    assert p == {"mode": "dark", "fade_s": 2.0}
    assert show_actions.validate("display_mode", {"mode": "dark"})["fade_s"] is None
    with pytest.raises(show_actions.ActionError):
        show_actions.validate("display_mode", {"mode": "dark", "fade_s": 11})

    seen = []

    async def fake_reconcile(mode, cats, vids, color, bright, **kw):
        seen.append((mode, kw))
        return {"status": mode}

    monkeypatch.setattr(dark_light, "reconcile", fake_reconcile)

    async def main():
        await room_controls.apply_patch({"display_mode": "dark"}, display_fade_s=3.0)
        await room_controls.apply_patch({"display_mode": "light"})

    _run(main())
    assert seen == [("dark", {"fade_s": 3.0}), ("light", {})]


def test_the_light_show_passes_the_steps_fade_only_when_authored(monkeypatch):
    from spectra.services import room_controls, show_actions, show_store
    from spectra.models.light_show import ShowAction

    calls = []

    async def fake_apply_patch(patch, **kw):
        calls.append((patch, kw))
        return {"status": "saved"}

    monkeypatch.setattr(room_controls, "apply_patch", fake_apply_patch)
    monkeypatch.setattr(show_store, "save_state", lambda: None)
    monkeypatch.setattr(show_actions, "_baseline", lambda *a, **k: None)

    def step(params):
        a = ShowAction(kind="display_mode", params=params)
        return (0, a, show_actions.validate("display_mode", params))

    run = show_actions.Run(id="r", name="t", set_id=None, source="test",
                           started_ms=0, steps=[{"label": "x", "kind": "display_mode"}])
    _run(show_actions._run_room_group(run, [step({"mode": "dark", "fade_s": 4})]))
    _run(show_actions._run_room_group(run, [step({"mode": "light"})]))
    assert calls[0] == ({"display_mode": "dark"},
                        {"ambient_snap": False, "display_fade_s": 4.0})
    assert calls[1] == ({"display_mode": "light"}, {"ambient_snap": False})
