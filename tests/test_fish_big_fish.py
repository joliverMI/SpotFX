"""The BIG FISH flare (2026-10-08, phase 1 — the look; the ordinary fish
steering out of its way, phase 2, is tests/test_fish_big_fish_avoid.py).

His ask, verbatim: "add a flare to fish, where a really large fish swims
directly across the screen, in the background of the others, and at 60%
brightness (tuneable). ... The speed it goes at is dependant on intensity.
the color should be the 120 to 180 degree rotation of the central color of
the scene, so it contrasts. at .5 intensity or higher 180 degrees, scale
linearly to .2 insesity = 120 degrees (either direction)."

Proven on the real vendored pipeline (fx.headless, his crystal's 72x37
shape) for the effect, on a recording engine for the flare write, and on a
temp store for the migration script. fx/effects/fish.py's BIG FISH block is
the binding statement.
"""
from __future__ import annotations

import asyncio
import colorsys
import json
import sys
from pathlib import Path
from random import Random

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx import device_model  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from test_fish import HIS_MATRIX, _close, _room  # noqa: E402

DT = 1.0 / 60.0
RED = "#ff0000"


def _run(coro):
    return asyncio.run(coro)


# ── the two curves he named ─────────────────────────────────────────────────

@pytest.mark.parametrize("intensity,degrees", [
    (0.0, 120.0), (0.1, 120.0), (0.2, 120.0), (0.35, 150.0), (0.5, 180.0),
    (0.75, 180.0), (1.0, 180.0)])
def test_the_colour_turn_is_120_at_0_2_and_180_from_0_5(intensity, degrees):
    assert FX.big_fish_hue_degrees(intensity) == pytest.approx(degrees)


def test_the_crossing_is_faster_at_higher_intensity_speed_linear():
    slow, fast = 7.0, 2.5
    assert FX.big_fish_cross_s(0.0, slow, fast) == pytest.approx(slow)
    assert FX.big_fish_cross_s(1.0, slow, fast) == pytest.approx(fast)
    times = [FX.big_fish_cross_s(i / 10, slow, fast) for i in range(11)]
    assert all(a > b for a, b in zip(times, times[1:]))
    speeds = [1.0 / t for t in times]
    steps = np.diff(speeds)
    assert np.allclose(steps, steps[0])        # the SPEED is linear


def test_rotate_hue_keeps_saturation_and_value():
    out = FX.rotate_hue(np.array([255.0, 0.0, 0.0]), 180.0)
    assert out == pytest.approx([0.0, 255.0, 255.0], abs=1e-3)
    out = FX.rotate_hue(np.array([200.0, 100.0, 50.0]), 120.0)
    h0, s0, v0 = colorsys.rgb_to_hsv(200 / 255, 100 / 255, 50 / 255)
    h1, s1, v1 = colorsys.rgb_to_hsv(*(out / 255.0))
    assert (s1, v1) == pytest.approx((s0, v0), abs=1e-4)
    assert (h1 - h0) % 1.0 == pytest.approx(1 / 3, abs=1e-4)


# ── the effect, on the real pipeline ────────────────────────────────────────

def _cfg(**over):
    # his Orbits-copied Matrix entry, solid red, no wake: every pixel the
    # ordinary fish light is pure red, so green/blue belong to the big fish
    return {**HIS_MATRIX, "gradient": RED, "ripple_amount": 0.0, **over}


_RUNS = [0]


def _cross(tmp_path, intensity, seed=5, linger=False, **cfg):
    """Fire one big fish and render until it has crossed (with `linger`,
    on until its smear has gone too); returns the effect, its record and
    every frame (H, W, 3 float) of the crossing. `eff.crossed_frames` is
    how many frames the fish itself was swimming."""
    # every run its OWN virtual id: the fish store a particle-handoff
    # snapshot under it when they shut down, and a later run reusing the id
    # would adopt the previous run's shoal (so two runs compared frame for
    # frame would not even swim the same fish). The prefix is this file's
    # own: the snapshot store is process-wide, and a bare "m3" collided with
    # test_fish_camera.py's own "m3" virtual whenever the two files ran in
    # one session (its seed-3 run adopted this file's shoal)
    _RUNS[0] += 1
    name = f"bigfish{_RUNS[0]}"

    async def main():
        room = await _room(tmp_path, name, _cfg(**cfg), seed=seed)
        try:
            room.step(30)
            eff = room.effect
            # as the engine writes it: floored so a fire at 0 still edges
            eff.update_config(
                {"big_fish": max(intensity, FX.BIG_FISH_POKE_FLOOR)})
            frames = []
            eff.crossed_frames = None
            for _ in range(60 * 40):
                room.step(1)
                frames.append(np.asarray(eff.matrix, dtype=np.float32).copy())
                if not eff._big and eff.crossed_frames is None:
                    eff.crossed_frames = len(frames)
                    if not linger:
                        break
                if not eff._big and eff._big_trail is None:
                    break
            return eff, dict(eff.big_fish_last), frames, dict(eff._config)
        finally:
            await _close(room)
    return _run(main())


def test_a_poke_sends_one_big_fish_across_and_self_resets(tmp_path):
    eff, fish, frames, config = _cross(tmp_path, 0.6, linger=True)
    assert eff.big_fish_spawned == 1 and config["big_fish"] == 0.0
    big = [float(f[..., 1:].max()) for f in frames]
    # it ENTERS from off the panel and LEAVES off the other side: nothing of
    # it on the first frame, nothing once its smear has faded (the ordinary
    # fish's own trail_decay), the panel crossed between
    assert big[0] < 5.0 and big[-1] < 5.0 and max(big) > 100.0
    # and it took its own crossing time to do it
    assert eff.crossed_frames * DT == pytest.approx(fish["cross_s"],
                                                    abs=3 * DT)
    # ... and its layer is let go of entirely once it has
    assert eff._big_trail is None
    # really large: two thirds of the panel long, near the middle
    assert fish["length"] == pytest.approx(0.65 * 71, rel=1e-3)
    assert abs(fish["y"] - 18.0) <= FX.BIG_FISH_Y_SPREAD * 37 + 1e-6


def test_it_crosses_straight_through_the_middle(tmp_path):
    _eff, fish, frames, _ = _cross(tmp_path, 0.6)
    mid = frames[len(frames) // 2][..., 1]
    rows = np.flatnonzero(mid.max(axis=1) > 50)
    cols = np.flatnonzero(mid.max(axis=0) > 50)
    assert rows.size and cols.size > 20            # a long body across
    assert abs(rows.mean() - fish["y"]) < 3.0      # centred on its row


@pytest.mark.parametrize("intensity", [0.0, 0.5, 1.0])
def test_the_speed_follows_the_intensity(tmp_path, intensity):
    _eff, fish, frames, _ = _cross(tmp_path, intensity)
    expect = FX.big_fish_cross_s(max(intensity, FX.BIG_FISH_POKE_FLOOR), 7.0, 2.5)
    assert fish["cross_s"] == pytest.approx(expect)
    assert len(frames) * DT == pytest.approx(expect, abs=3 * DT)


def _peak_gb(frames):
    """The big fish's brightest pixel (green, blue — the ordinary fish here
    are pure red, so those two channels are the big fish's alone)."""
    gb = np.concatenate([f[..., 1:].reshape(-1, 2) for f in frames])
    return gb[np.argmax(gb.sum(axis=1))]


@pytest.mark.parametrize("intensity,degrees", [(0.2, 120.0), (0.35, 150.0),
                                               (0.5, 180.0)])
def test_its_colour_is_the_centre_turned(tmp_path, intensity, degrees):
    for seed in (5, 6, 7, 8):
        eff, fish, frames, _ = _cross(tmp_path / str(seed), intensity, seed=seed)
        assert fish["degrees"] == pytest.approx(degrees)
        expect = FX.rotate_hue(np.array([255.0, 0.0, 0.0]),
                               fish["turn"] * degrees)
        # its brightest pixel IS the turned colour: an ordinary fish's body
        # is drawn at a level, and the 255 ceiling keeps the colour, so the
        # green:blue balance of his rotation survives the bright middle
        peak = _peak_gb(frames)
        assert peak.max() > 60.0
        assert peak / peak.max() == pytest.approx(
            expect[1:] / expect[1:].max(), abs=0.02)


def test_it_is_60_percent_of_the_same_fish_at_full(tmp_path):
    """"at 60% brightness": the same crossing (same seed, same fish) at
    big_fish_brightness 1 and at the default 0.6 — every pixel of it at
    60%, its brightest included."""
    _e, _f, full, _ = _cross(tmp_path / "a", 0.6, big_fish_brightness=1.0)
    _e, _f, dim, _ = _cross(tmp_path / "b", 0.6)
    assert len(full) == len(dim)
    # (both frames are whole 0..255 levels, truncated: 1.6 is that rounding)
    assert _peak_gb(dim) == pytest.approx(_peak_gb(full) * 0.6, abs=1.6)
    for a, b in zip(full, dim):
        assert np.allclose(b[..., 1:], a[..., 1:] * 0.6, atol=1.6)


def test_it_is_dimmer_than_the_ordinary_fish(tmp_path):
    """Drawn at an ordinary fish's own level and then at 60%, its brightest
    pixel is under the ordinary fish's brightest."""
    eff, _f, frames, _ = _cross(tmp_path, 0.6)
    ordinary = max(float(f[..., 0].max()) for f in frames)
    assert _peak_gb(frames).max() < 0.75 * ordinary


def test_either_direction_both_ways_turn_up(tmp_path):
    turns = set()
    sides = set()
    for seed in range(12):
        _eff, fish, _f, _ = _cross(tmp_path / str(seed), 0.3, seed=seed,
                                   big_fish_cross_fast_s=0.5,
                                   big_fish_cross_slow_s=0.5)
        turns.add(fish["turn"])
        sides.add(fish["travel"])
    assert turns == {-1.0, 1.0} and sides == {-1.0, 1.0}


def test_the_brightness_is_tunable(tmp_path):
    _eff, fish, frames, _ = _cross(tmp_path / "a", 0.6, big_fish_brightness=0.3)
    _eff, fish, ref, _ = _cross(tmp_path / "b", 0.6)
    assert _peak_gb(frames).max() == pytest.approx(
        _peak_gb(ref).max() / 2.0, abs=1.0)


def test_it_swims_behind_the_ordinary_fish(tmp_path):
    """Wherever an ordinary fish is fully lit, the big fish is hidden —
    it reads as BEHIND. And it never hides one: red stays red."""
    _eff, _fish, frames, _ = _cross(tmp_path, 0.3, particle_count=8,
                                    blob_size=3.0)
    overlaps = 0
    for f in frames:
        over = f[..., 0] >= FX.BIG_FISH_OCCLUDE_AT
        overlaps += int(np.count_nonzero(over))
        assert np.all(f[..., 1:][over] < 1e-3)
    assert overlaps > 0


def test_the_ordinary_fish_render_is_untouched_without_a_poke(tmp_path):
    """No poke, no big fish: the layer is never even built, so every frame
    is exactly the frame the effect drew before this flare existed."""
    async def main():
        room = await _room(tmp_path, "m", _cfg())
        try:
            room.step(240)
            assert room.effect._big == []
            assert room.effect._big_fish_layer(DT, None) is None
        finally:
            await _close(room)
    _run(main())


# the commit carrying PR 381's big fish (this rework's merge-base), pinned:
# with no poke, the ordinary fish render is byte-identical to it — the
# refactor that lets the big fish share the ordinary body drawing changed no
# ordinary pixel
PR381_REF = "34719fd452aa1a2758efa4648e039a054220f405"


def _load_pr381():
    import importlib.util
    import subprocess
    import tempfile
    name = "fish_pr381_bigfish_test"
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{PR381_REF}:fx/effects/fish.py"], cwd=ROOT,
            capture_output=True, text=True, check=True).stdout
    except Exception as exc:                       # noqa: BLE001
        pytest.fail(f"cannot read {PR381_REF}:fx/effects/fish.py — {exc}")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


def test_without_a_poke_every_frame_is_pr381s_exactly(tmp_path):
    """The ordinary fish's body drawing was factored into `_spine_wave` /
    `_splat_spines` so the big fish could be drawn by it; with no poke every
    frame is bit for bit the frame PR 381's module drew, through a charge,
    a lull and a drop."""
    from fx import headless
    old = _load_pr381()
    cfg = dict(HIS_MATRIX, ripple_amount=0.35, lull_keep=0)

    async def frames(effect_type, tag):
        host = await headless.start_headless_host(
            str(tmp_path / tag), pixel_count=72 * 37, rows=37, device_id=tag)
        virtual = host.virtuals.get(tag)
        cm = headless.fake_clock()
        clock = cm.__enter__()
        try:
            eff = headless.attach_effect(host, virtual, effect_type, dict(cfg))
            eff._rng = np.random.default_rng(5)
            out = []
            script = [(None, 120), ("charge", 120), ("lull", 90), ("drop", 120)]
            for phase, n in script:
                if phase:
                    eff.update_config({"phase": phase, "phase_progress": 0.0})
                for i in range(n):
                    if phase in ("charge", "lull"):
                        eff.update_config({"phase_progress": (i + 1) / n})
                    clock.advance(DT)
                    frame = virtual.assemble_frame()
                    if frame is not None:
                        virtual.flush(frame)
                    out.append(np.asarray(eff.matrix, dtype=np.uint8).copy())
            return out
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    a = _run(frames(old, "old"))
    b = _run(frames("fish", "new"))
    assert len(a) == len(b) == 450
    for i, (x, y) in enumerate(zip(a, b)):
        assert np.array_equal(x, y), f"frame {i} differs"


def test_it_is_drawn_by_the_ordinary_fish_body(tmp_path, monkeypatch):
    """No bespoke silhouette: the big fish goes through the same spine wave
    and splat path every ordinary fish does."""
    calls = {"wave": 0, "splat": 0}
    wave, splat = FX.Fish2d._spine_wave, FX.Fish2d._splat_spines

    def spy_wave(self, *a, **k):
        if "u" in k:
            calls["wave"] += 1
        return wave(self, *a, **k)

    def spy_splat(self, *a, **k):
        if k.get("node_w") is not None:
            calls["splat"] += 1
        return splat(self, *a, **k)
    monkeypatch.setattr(FX.Fish2d, "_spine_wave", spy_wave)
    monkeypatch.setattr(FX.Fish2d, "_splat_spines", spy_splat)
    eff, _f, frames, _ = _cross(tmp_path, 0.9)
    assert calls["wave"] == calls["splat"] == eff.crossed_frames - 1
    for gone in ("_big_fish_nodes", "_big_fish_coverage"):
        assert not hasattr(FX.Fish2d, gone)


def test_its_body_is_one_continuous_fish_not_beads(tmp_path):
    """Along its spine, from just behind the head to just before the tail,
    the body never dips: an ordinary fish's six splats magnified five times
    would fall apart into six beads."""
    _e, fish, frames, _ = _cross(tmp_path, 0.3)
    mid = frames[len(frames) // 2]
    level = mid[..., 1:].max(axis=2)
    row = level[int(round(fish["y"]))]
    lit = np.flatnonzero(row > 0.25 * row.max())
    span = row[lit[0]:lit[-1] + 1]
    assert lit[-1] - lit[0] > 0.6 * fish["length"]
    inner = span[len(span) // 6: -len(span) // 6]
    # nothing in the middle two thirds dips below its neighbours by more
    # than a sliver
    run_max = np.maximum.accumulate(inner)
    back_max = np.maximum.accumulate(inner[::-1])[::-1]
    dip = np.minimum(run_max, back_max) - inner
    assert float(dip.max()) < 0.06 * float(row.max())


def test_it_flaps_its_tail_like_an_ordinary_fish(tmp_path):
    """The tail half swings across the run; the head barely does."""
    _e, fish, frames, _ = _cross(tmp_path, 0.3)
    head_y, tail_y = [], []
    for f in frames[len(frames) // 3: 2 * len(frames) // 3]:
        level = f[..., 1:].max(axis=2)
        cols = np.flatnonzero(level.max(axis=0) > 20.0)
        if cols.size < 20:
            continue
        lead = cols[-1] if fish["travel"] > 0 else cols[0]
        trail = cols[0] if fish["travel"] > 0 else cols[-1]
        step = -1 if fish["travel"] > 0 else 1
        for col, out in ((lead + step * 4, head_y), (trail - step * 4, tail_y)):
            c = level[:, col]
            out.append(float((c * np.arange(c.size)).sum() / max(c.sum(), 1e-6)))
    assert np.ptp(tail_y) > 1.0
    assert np.ptp(tail_y) > 2.0 * np.ptp(head_y)


def test_it_lays_a_large_dim_wake_of_its_own(tmp_path):
    """With the scene's wake on, the big fish lays one: wider than an
    ordinary fish's deposit, in its own colour, and dim — under half its
    body. big_fish_ripple 0 lays none; the scene's own wake off lays none."""
    def wake_of(**over):
        eff, _f, frames, _ = _cross(tmp_path / str(len(over)) / str(over),
                                    0.4, ripple_amount=0.35, **over)
        return eff, frames

    with_wake, frames = wake_of()
    without, _ = wake_of(big_fish_ripple=0.0)
    added = with_wake.wake - without.wake
    gb = added[..., 1:].max(axis=2)
    assert gb.max() > 5.0                       # it is there ...
    assert np.count_nonzero(gb > 1.0) > 150     # ... large ...
    body = _peak_gb(frames).max()
    assert gb.max() < 0.5 * body                # ... and dim
    # in the big fish's own colour: the ordinary fish here are pure red
    assert added[..., 1:].max() > 0.0
    louder, _ = wake_of(big_fish_ripple=2.0)
    assert (louder.wake - without.wake)[..., 1:].max() > 1.5 * gb.max()
    wider, _ = wake_of(big_fish_ripple_size=0.4)
    assert np.count_nonzero(
        (wider.wake - without.wake)[..., 1:].max(axis=2) > 1.0
    ) < np.count_nonzero(gb > 1.0)
    off, _f, _fr, _ = _cross(tmp_path / "off", 0.4, ripple_amount=0.0)
    assert off.wake[..., 1:].max() == 0.0


def test_a_stale_persisted_poke_never_swims(tmp_path):
    async def main():
        room = await _room(tmp_path, "m", _cfg(big_fish=0.8))
        try:
            room.step(60)
            assert room.effect.big_fish_spawned == 0
        finally:
            await _close(room)
    _run(main())


def test_at_most_three_cross_at_once(tmp_path):
    async def main():
        room = await _room(tmp_path, "m", _cfg())
        try:
            eff = room.effect
            for i in range(5):
                eff.update_config({"big_fish": 0.5 + i * 0.01})
                room.step(1)
            assert len(eff._big) == FX.BIG_FISH_MAX
            assert eff.big_fish_spawned == 3 and eff.big_fish_dropped == 2
            # an identical later poke edges again once the key has reset
            for _ in range(60 * 10):
                room.step(1)
            assert eff._big == []
            eff.update_config({"big_fish": 0.5})
            room.step(1)
            assert eff.big_fish_spawned == 4
        finally:
            await _close(room)
    _run(main())


def test_the_lull_darkness_darkens_it_too(tmp_path):
    async def main():
        room = await _room(tmp_path, "m", _cfg(big_fish_cross_slow_s=30.0,
                                               big_fish_cross_fast_s=30.0))
        try:
            eff = room.effect
            eff.update_config({"lull_keep": 0})
            eff.update_config({"phase": "lull", "phase_progress": 0.0})
            frames = 240
            for i in range(1, frames + 1):
                eff.update_config({"phase_progress": i / frames})
                room.step(1)
            eff.update_config({"big_fish": 0.5})
            room.step(30)
            assert eff._big and eff._lull_state.get("dark", 1.0) == 0.0
            assert np.asarray(eff.matrix, dtype=np.float32)[..., 1:].max() == 0.0
        finally:
            await _close(room)
    _run(main())


# ── the flare kind and the engine write ─────────────────────────────────────

def test_the_kind_carries_no_knobs():
    from spectra.models.scene import FlareKind
    kind = FlareKind(name="Big Fish", type="big_fish")
    assert kind.min_intensity is None
    for bad in ({"gain": 0.5}, {"hold_ms": 200}, {"jump": "dice"},
                {"params": {"big_fish_size": 0.9}}):
        with pytest.raises(Exception):
            FlareKind(name="bad", type="big_fish", **bad)


MATRIX = "crystal-mapper"
STRIP = "strip-1"


def _scene():
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Big Fish", type="big_fish")]
    return SceneV2(
        name="Fishy",
        devices=[SceneDeviceConfig(target_kind="virtual", target=MATRIX,
                                   effect_type="fish"),
                 SceneDeviceConfig(target_kind="virtual", target=STRIP,
                                   effect_type="orbits1d")],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"Big Fish": 1.0})])})


def _recording_engine(scene):
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor
    from spectra.services.scene_response import ResponseEngine
    executor = RecordingExecutor(clock=lambda: 0.0,
                                 room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: 0.0, leg_s=20.0,
        intensity=lambda: 1.0, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(3))
    responder = ResponseEngine(conductor=conductor, executor=executor,
                               rng=Random(5), clock=lambda: 0.0,
                               curve_profiles=lambda: {})
    conductor.on_scene_fire(scene, [
        {"virtual_id": MATRIX, "effect_type": "fish", "config": {},
         "entry_id": scene.devices[0].id, "color_mode": "set"},
        {"virtual_id": STRIP, "effect_type": "orbits1d", "config": {},
         "entry_id": scene.devices[1].id, "color_mode": "set"}])
    return executor, responder


@pytest.mark.parametrize("intensity,written", [
    (0.0, FX.BIG_FISH_POKE_FLOOR), (0.3, 0.3), (1.0, 1.0)])
def test_the_flare_pokes_fish_only_with_its_intensity(intensity, written):
    assert device_model.BIG_FISH_EFFECTS == frozenset({"fish"})
    executor, responder = _recording_engine(_scene())
    record = _run(responder.on_event("flare", intensity))
    pokes = [w for w in executor.writes if "big_fish" in w["params"]]
    assert len(pokes) == 1 and pokes[0]["virtual_id"] == MATRIX
    assert pokes[0]["kind"] == "jump"
    assert pokes[0]["params"]["big_fish"] == pytest.approx(written)
    assert record["big_fish"] == {"intensity": pytest.approx(written),
                                  "virtuals": 1}
    # nothing carries and nothing releases
    assert responder.pending_hold_groups() == []
    assert responder.pending_color_rotate_holds() == []


def test_the_explicit_preview_fires_it_and_the_ruler_shows_the_crossing():
    from spectra.models.scene import FlareKind
    from spectra.services import flare_preview
    kind = FlareKind(name="Big Fish", type="big_fish")
    executor, responder = _recording_engine(_scene())
    rec = _run(responder.fire_kind(kind, 0.7))
    assert rec["result"] == "applied" and rec["big_fish"]["virtuals"] == 1
    for intensity in (0.0, 1.0):
        timeline = _run(flare_preview.build_timeline(_scene(), kind, intensity))
        expect = 1000.0 * FX.big_fish_cross_s(
            max(intensity, FX.BIG_FISH_POKE_FLOOR), 7.0, 2.5)
        assert timeline["effect_animation_ms"] == pytest.approx(expect, abs=0.1)
        assert timeline["animation_end_s"] == pytest.approx(expect / 1000.0,
                                                            abs=1e-3)
        assert timeline["lead_ms"] == 0


def test_the_six_settings_are_registered_for_sonic_and_the_editor():
    params = device_model.effect_params("fish") if hasattr(
        device_model, "effect_params") else None
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    fish = registry["effects"]["fish"]
    schema = FX.Fish2d.schema()({})
    for key in ("big_fish_brightness", "big_fish_size",
                "big_fish_cross_slow_s", "big_fish_cross_fast_s",
                "big_fish_ripple", "big_fish_ripple_size"):
        assert fish["params"][key]["default"] == schema[key]
        assert fish["defaults"][key] == schema[key]
        assert fish["params"][key]["help_topic"] == "fish-big-fish"
    assert schema["big_fish_brightness"] == 0.6
    # the poke key rides only the flare write, never an editor surface
    assert "big_fish" not in fish["params"]
    assert params is None or "big_fish" not in params


def test_sonic_can_make_the_kind():
    from spectra.services import scene_console
    schema = scene_console.OPERATIONS["set_flare_kind"].input_schema["properties"]
    assert "big_fish" in schema["type"]["enum"]


# ── the migration script ────────────────────────────────────────────────────

def _fish_scene(*, shape_lane=True, effect="fish"):
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Fish Swim Burst", type="momentary",
                       params={"swim_burst": ParamTarget(mode="absolute",
                                                         value=1.0)},
                       hold_ms=300),
             FlareKind(name="Reverse Momentarily (500ms)", type="momentary",
                       params={"reverse": ParamTarget(mode="absolute",
                                                      value=1.0)},
                       hold_ms=500),
             FlareKind(name="Colour Jump", type="drift_jump", jump="color_set")]
    lanes = ({"Fish Swim Burst": "Shape",
              "Reverse Momentarily (500ms)": "Shape"} if shape_lane else {})
    bands = [FlareBand(intensity_min=lo, intensity_max=hi,
                       kinds={k.name: 1.0 for k in kinds}, kind_lanes=lanes)
             for lo, hi in ((0.0, 0.35), (0.35, 0.7), (0.7, 1.0))]
    return SceneV2(
        name="Fish",
        devices=[SceneDeviceConfig(target_kind="category", target="Matrix",
                                   effect_type=effect)],
        flare_kinds=kinds, responses={"flare": ResponseSpec(bands=bands)})


def _store(tmp_path, *scenes):
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps(
        {s.id: s.model_dump(mode="json") for s in scenes}, indent=2))
    return path


def _script():
    sys.path.insert(0, str(ROOT / "scripts"))
    import add_fish_big_fish_flare as script
    return script


def test_the_script_pools_it_in_the_shape_lane_and_reverts_exactly(tmp_path):
    from spectra.models.scene import SceneV2
    script = _script()
    scene = _fish_scene()
    other = _fish_scene()
    other.name = "Not Fish"
    path = _store(tmp_path, scene, other)
    original = path.read_text()
    assert script.main(["--scenes-file", str(path)]) == 0       # dry run
    assert path.read_text() == original
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    stored = json.loads(path.read_text())
    written = SceneV2(**stored[scene.id])
    big = [k for k in written.flare_kinds if k.type == "big_fish"]
    assert [k.name for k in big] == ["Big Fish", "Big Fish 2"]
    assert all(k.trigger_offset_ms == 0 for k in big)
    for band in written.responses["flare"].bands:
        assert band.kinds["Big Fish"] == band.kinds["Big Fish 2"] == 1.0
        pool = sorted(k for k, lane in band.kind_lanes.items()
                      if lane == "Shape")
        assert pool == ["Big Fish", "Big Fish 2", "Fish Swim Burst",
                        "Reverse Momentarily (500ms)"]
    assert stored[other.id] == json.loads(original)[other.id]
    # idempotent
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    assert json.loads(path.read_text()) == stored
    assert script.main(["--scenes-file", str(path), "--apply", "--revert"]) == 0
    assert json.loads(path.read_text()) == json.loads(original)


def test_after_the_script_a_big_fish_is_as_often_as_the_others_combined(
        tmp_path):
    from spectra.models.scene import SceneV2
    from spectra.services.scene_response import resolve_lane_picks
    script = _script()
    scene = _fish_scene()
    path = _store(tmp_path, scene)
    script.main(["--scenes-file", str(path), "--apply"])
    written = SceneV2(**json.loads(path.read_text())[scene.id])
    band = written.responses["flare"].bands[1]
    declared = {k.name: k for k in written.flare_kinds}
    rng = Random(0)
    counts = {"big": 0, "Fish Swim Burst": 0,
              "Reverse Momentarily (500ms)": 0}
    n = 4000
    for _ in range(n):
        picked, _rec = resolve_lane_picks(band, rng, declared, 0.5)
        assert "Colour Jump" in picked       # an unpooled kind still fires
        shape = [p for p in picked
                 if p in counts or p.startswith("Big Fish")]
        assert len(shape) == 1               # exactly one shape flare
        counts["big" if shape[0].startswith("Big Fish") else shape[0]] += 1
    assert counts["big"] / n == pytest.approx(0.5, abs=0.03)
    for name in ("Fish Swim Burst", "Reverse Momentarily (500ms)"):
        assert counts[name] / n == pytest.approx(0.25, abs=0.03), name


def test_the_script_refuses_a_band_with_no_shape_lane(tmp_path):
    script = _script()
    path = _store(tmp_path, _fish_scene(shape_lane=False))
    original = path.read_text()
    with pytest.raises(SystemExit, match="no 'Shape' lane"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text() == original


def test_the_script_refuses_a_scene_that_does_not_run_fish(tmp_path):
    script = _script()
    path = _store(tmp_path, _fish_scene(effect="orbits"))
    original = path.read_text()
    with pytest.raises(SystemExit, match="no Fish entry"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text() == original


def test_the_script_never_overwrites_a_kind_of_another_type(tmp_path):
    from spectra.models.scene import FlareKind
    script = _script()
    scene = _fish_scene()
    scene.flare_kinds.append(FlareKind(name="Big Fish", type="momentary",
                                       gain=1.5))
    path = _store(tmp_path, scene)
    original = path.read_text()
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text() == original
