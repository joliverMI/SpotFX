"""Executable spec for THE ROOM-EFFECTS LAYER, measured on the REAL render
pipeline: two emitters with hand-built footprints at different axis
positions, one Dim Wave, and the phase lag between them read off the actual
rendered pixels.

WHY THE REAL PIPELINE. A gain that is right in a dict and never reaches a
light is the defect this project has shipped before (the flare preview that
"did not actually change anything on the lights"). So nothing here asserts
against room_effects' own gain dictionary: the measurement is
`virtual.assemble_frame()` — the literal pixel buffer the device driver
receives — stepped through fx.headless with fx.facade owning the room, which
is the same rig test_room_preview.py and test_dark_light.py use.

WHAT IS PROVEN
  1. the wave TRAVELS: two emitters whose footprints sit at different axis
     positions show a measured phase difference matching the wave's own
     travel time, read off rendered pixels, with a negative control
     (speed 0 -> no lag, depth 0 -> no modulation at all);
  2. it COMPOSES: the measured brightness is the SHOW's own brightness times
     the gain, never a replacement — halve the show's brightness and the
     whole measured wave halves with it;
  3. it is BOUNDED: the room is held through flare_preview_hold, and closing
     hands back exactly the pre-effect brightness;
  4. the WRITE COST is measured on two devices, on the real clock, because
     the plan named it as a risk rather than an assumption;
  5. all FOUR field kinds reduce through per_emitter_scalar, with the three
     unbuilt ones exercised as pure functions.

Run from repo root: .venv/bin/python scripts/check_room_effect_wave.py
Isolated: temp fx config + temp SPECTRA storage, dummy devices, audio
silenced. No LedFX, no network, no live storage.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print = __import__("functools").partial(print, flush=True)   # noqa: A001

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


td = Path(tempfile.mkdtemp(prefix="spectra-room-wave-"))

from fx import device_model                                   # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from spectra import config as scfg                            # noqa: E402
scfg.SPECTRA_STORAGE = td / "spectra"
for name in ("SCENES_FILE", "SEQUENCER_FILE", "DRIFT_PROFILES_FILE",
             "ROOM_COLOR_FILE", "ROOM_CONTROLS_FILE", "GRADIENT2D_FILE",
             "FIRE_HISTORY_FILE", "SHOW_LOG_FILE", "FLARE_PREVIEW_HOLD_FILE",
             "ROOM_MAPS_FILE", "ROOM_EFFECTS_FILE"):
    setattr(scfg, name, scfg.SPECTRA_STORAGE / f"{name.lower()}.json")
scfg.COLOR_SETS_FILE = td / "color_sets.json"

from fx import facade, headless, light_ownership              # noqa: E402
from fx.host import FxHost                                    # noqa: E402
from spectra.models.room_map import (GRID_H, GRID_W, AxisCalibration,  # noqa: E402
                                     EmitterFootprint, Point, RoomMap)
from spectra.services import (flare_preview_hold, fx_seam, light_field,  # noqa: E402
                              room_effects)
from spectra.services.light_field_fields import (KINDS, DimWave,       # noqa: E402
                                                 HueRotation, explode, implode)

LOW, HIGH = "emitter-low", "emitter-high"
PIXELS = 8
SHOW_BRIGHTNESS = 0.8
#: One full cycle across the axis at a quarter-cycle per second: a 4 s
#: period, comfortably resolved by a 15 Hz tick.
WAVELENGTH, SPEED, DEPTH = 1.0, 0.25, 0.9
TICK_S = 1.0 / room_effects.TICK_HZ

# axis bands the two footprints occupy — the ground truth the phase lag is
# predicted from, declared before the run
LOW_BAND = (0.05, 0.20)
HIGH_BAND = (0.75, 0.95)

light_ownership.OWNERSHIP_FILE = td / "ownership.json"
light_ownership.OWNERSHIP_FILE.write_text(json.dumps({"owner": "spectra"}))


def _write_two_device_config(config_dir: str) -> None:
    os.makedirs(config_dir, exist_ok=True)

    def entry(did):
        return ({"id": did, "type": "dummy",
                 "config": {"name": did, "pixel_count": PIXELS}},
                {"id": did, "is_device": did, "auto_generated": False,
                 "config": {"name": did, "mapping": "span", "rows": 1},
                 "segments": [[did, 0, PIXELS - 1, False]]})

    d1, v1 = entry(LOW)
    d2, v2 = entry(HIGH)
    from fx.consts import CONFIGURATION_VERSION
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": [d1, d2], "virtuals": [v1, v2]}, fh)


def _footprint(emitter_id: str, band: tuple[float, float]) -> EmitterFootprint:
    """A footprint occupying one horizontal band of the frame — the map's own
    storage shape, hand-built so the axis position is ground truth rather
    than something a capture happened to produce."""
    lo, hi = band
    grid = np.zeros((GRID_H, GRID_W))
    y0 = int(round((1.0 - hi) * GRID_H))
    y1 = max(y0 + 1, int(round((1.0 - lo) * GRID_H)))
    grid[y0:y1, :] = 1.0
    return EmitterFootprint(emitter_id=emitter_id, virtual_ids=[emitter_id],
                            grid=[float(v) for v in grid.reshape(-1)],
                            weight=float(grid.sum()))


AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


def _room() -> RoomMap:
    room = RoomMap(name="Wave rig", device_ids=[LOW, HIGH], axis=AXIS)
    room.put_footprint(_footprint(LOW, LOW_BAND))
    room.put_footprint(_footprint(HIGH, HIGH_BAND))
    return room


def mean_axis(emitter_id: str, band) -> float:
    s = light_field.samples_for(_footprint(emitter_id, band), AXIS)
    return float((s.axis * s.weight).sum() / s.weight.sum())


async def _start_host(tag: str):
    config_dir = str(td / f"fx-{tag}")
    _write_two_device_config(config_dir)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    effects = {}
    for vid in (LOW, HIGH):
        virtual = host.virtuals.get(vid)
        effects[vid] = headless.attach_effect(
            host, virtual, "singleColor",
            {"color": "#ffffff", "brightness": SHOW_BRIGHTNESS,
             "background_brightness": 0.0})
    return host, effects


async def _stop(host) -> None:
    """FxHost.stop() joins the per-virtual render threads, which this
    frame-stepped harness never started (headless.attach_effect is the
    no-thread path) — it can block. Nothing here needs a graceful shutdown:
    a dummy device holds no socket, and the process exits at the end."""
    # Deliberately does NOT call host.stop(): the vendored FxHost refuses it
    # ("refusing to stop the SpotFX process") and this harness never started
    # the render threads it would join. A dummy device holds no socket, and
    # the process _exit()s at the end.
    await asyncio.sleep(0)


def measure(host, vid) -> float:
    """The rendered brightness of one virtual RIGHT NOW, as a 0..1 fraction
    of full white, read off the assembled frame the device would receive."""
    virtual = host.virtuals.get(vid)
    frame = virtual.assemble_frame()
    if frame is None:
        return 0.0
    virtual.flush(frame)
    return float(np.asarray(frame).mean()) / 255.0


def circular_phase(times: list[float], values: list[float], omega: float) -> float:
    """The phase of a known-frequency sinusoid in a measured series, by
    projection onto cos/sin at that frequency — exact where an argmin is
    quantised by the sampling interval."""
    t = np.asarray(times)
    y = np.asarray(values, dtype=float)
    y = y - y.mean()
    c = float((y * np.cos(omega * t)).sum())
    s = float((y * np.sin(omega * t)).sum())
    return math.atan2(s, c)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


# ── ONE — the wave travels, measured on rendered pixels ───────────────────

async def section_one(depth: float = DEPTH, speed: float = SPEED,
                      show_brightness: float = SHOW_BRIGHTNESS,
                      periods: float = 2.0, tag: str = "travel"):
    host, _effects = await _start_host(tag)
    room = _room()
    spec = room_effects.RoomEffectSpec(room_id=room.id, kind="dim_wave",
                                       wavelength=WAVELENGTH, speed=speed,
                                       depth=depth)
    if show_brightness != SHOW_BRIGHTNESS:
        for vid in (LOW, HIGH):
            await fx_seam.apply_writes(
                [{"virtual_id": vid, "effect_type": "singleColor",
                  "config": {"brightness": show_brightness}}], transition_ms=1)
            host.virtuals.get(vid).assemble_frame()

    series: dict[str, list[float]] = {LOW: [], HIGH: []}
    times: list[float] = []
    now = {"t": 1000.0}
    total = periods / max(1e-9, speed) if speed else periods * 4.0
    ticks = int(total / TICK_S)

    def clock() -> float:
        return now["t"]

    async def step(period: float):
        now["t"] += period
        # let the 1 ms tween the write started land, then read the pixels
        for vid in (LOW, HIGH):
            host.virtuals.get(vid).assemble_frame()
        times.append(now["t"])
        for vid in (LOW, HIGH):
            series[vid].append(measure(host, vid))
        await asyncio.sleep(0)

    deps = room_effects.RunnerDeps(
        apply_writes=fx_seam.apply_writes, get_virtuals=fx_seam.get_virtuals,
        open_hold=flare_preview_hold.open_program_hold,
        close_hold=flare_preview_hold.close_hold,
        touch_hold=flare_preview_hold.touch,
        clock=clock, sleep=step)

    started = await room_effects.start(room, spec, deps)
    for _ in range(ticks):
        await asyncio.sleep(0)
        if len(times) >= ticks:
            break
    # drive the loop deterministically: the runner awaits our own `step`
    while len(times) < ticks:
        await asyncio.sleep(0)
    cost = room_effects.write_cost()
    await room_effects.stop(deps)
    return host, started, times, series, cost


async def run_travel():
    print("\n== 1. the wave travels: phase lag on rendered pixels ==")
    host, started, times, series, _cost = await section_one()
    check(started.get("running"), f"the effect started: {started.get('reason', '')}")
    check(sorted(started.get("emitters", [])) == sorted([HIGH, LOW]),
          "both mapped emitters are driven")

    omega = 2 * math.pi * SPEED
    phi_low = circular_phase(times, series[LOW], omega)
    phi_high = circular_phase(times, series[HIGH], omega)
    a_low, a_high = mean_axis(LOW, LOW_BAND), mean_axis(HIGH, HIGH_BAND)
    predicted = 2 * math.pi * (a_high - a_low) / WAVELENGTH
    measured = wrap(phi_high - phi_low)
    err = abs(wrap(measured - predicted))
    lag_s = wrap(predicted) / omega
    print(f"    axis: low {a_low:.3f}  high {a_high:.3f}   "
          f"predicted lag {(a_high - a_low) / (WAVELENGTH * SPEED):.2f}s "
          f"(= {wrap(predicted):+.3f} rad, {lag_s:+.2f}s modulo the period)")
    print(f"    measured phase difference {measured:+.3f} rad "
          f"(error {math.degrees(err):.1f}deg)")
    check(err < math.radians(12),
          f"the MEASURED phase lag matches the wave's own travel to within "
          f"12 degrees ({math.degrees(err):.1f}deg)")

    depths = {vid: (max(series[vid]) - min(series[vid])) for vid in (LOW, HIGH)}
    check(all(d > 0.5 * DEPTH * SHOW_BRIGHTNESS for d in depths.values()),
          f"both emitters genuinely modulate ({depths[LOW]:.3f}, {depths[HIGH]:.3f})")
    check(max(max(series[LOW]), max(series[HIGH])) <=
          SHOW_BRIGHTNESS + 0.02,
          "the crest never exceeds the show's own brightness — a dim wave "
          "only ever takes light away")
    await _stop(host)


async def run_negative_controls():
    print("\n== 2. negative controls ==")
    host, _s, times, series, _c = await section_one(depth=0.0, tag="depth0")
    flat = {vid: (max(series[vid]) - min(series[vid])) for vid in (LOW, HIGH)}
    check(max(flat.values()) < 1e-6,
          f"depth 0 renders an EXACTLY flat room ({max(flat.values()):.2e}) — "
          "the feature is a no-op when it is turned down, not approximately one")
    check(abs(series[LOW][-1] - SHOW_BRIGHTNESS) < 0.01,
          "and leaves the show's own brightness exactly where it was")
    await _stop(host)

    host, _s, times, series, _c = await section_one(speed=0.0, periods=1.0,
                                                    tag="speed0")
    spread = {vid: (max(series[vid]) - min(series[vid])) for vid in (LOW, HIGH)}
    check(max(spread.values()) < 1e-6,
          "speed 0 is a STANDING wave: each emitter holds one constant gain, "
          "so a lag measured at speed 0 would have been an artefact")
    check(abs(series[LOW][0] - series[HIGH][0]) > 0.05,
          "and the two emitters still sit at DIFFERENT points of it "
          f"({series[LOW][0]:.3f} vs {series[HIGH][0]:.3f}) — the axis is "
          "genuinely being read")
    await _stop(host)


async def run_composition():
    print("\n== 3. it composes with the show, never replaces it ==")
    host, _s, _t, full, _c = await section_one(show_brightness=0.8, tag="comp-full")
    await _stop(host)
    host, _s, _t, half, _c = await section_one(show_brightness=0.4, tag="comp-half")
    await _stop(host)
    ratio = max(full[LOW]) / max(max(half[LOW]), 1e-9)
    check(abs(ratio - 2.0) < 0.1,
          f"halving the SHOW's brightness halves the whole measured wave "
          f"(ratio {ratio:.2f}) — the gain multiplies onto the room's own "
          f"output rather than setting it")


async def run_bounded():
    print("\n== 4. bounded by the held-room seam ==")
    host, _effects = await _start_host("bounded")
    before = measure(host, LOW)
    room = _room()
    spec = room_effects.RoomEffectSpec(room_id=room.id, kind="dim_wave",
                                       wavelength=WAVELENGTH, speed=SPEED,
                                       depth=1.0)
    now = {"t": 500.0}
    seen = {"n": 0}

    async def step(period: float):
        now["t"] += period
        seen["n"] += 1
        for vid in (LOW, HIGH):
            host.virtuals.get(vid).assemble_frame()
        await asyncio.sleep(0)

    deps = room_effects.RunnerDeps(
        apply_writes=fx_seam.apply_writes, get_virtuals=fx_seam.get_virtuals,
        open_hold=flare_preview_hold.open_program_hold,
        close_hold=flare_preview_hold.close_hold,
        touch_hold=flare_preview_hold.touch,
        clock=lambda: now["t"], sleep=step)

    started = await room_effects.start(room, spec, deps)
    check(started.get("running"), "started")
    check(flare_preview_hold.active(),
          "a running room effect HOLDS the room — snapshot, deadline, sweep, "
          "ceiling and restart recovery all inherited, never a second hold")
    check(room_effects.holds() == {(LOW, "brightness"), (HIGH, "brightness")},
          "the param watchdog is told exactly which (virtual, param) keys the "
          "wave owns — per key, not a global stand-down")
    while seen["n"] < 20:
        await asyncio.sleep(0)
    mid = measure(host, LOW)
    check(abs(mid - before) > 0.02,
          f"the room is genuinely being driven mid-run ({before:.3f} -> {mid:.3f})")

    await room_effects.stop(deps)
    for vid in (LOW, HIGH):
        host.virtuals.get(vid).assemble_frame()
    after = measure(host, LOW)
    check(not flare_preview_hold.active(), "stopping releases the hold")
    check(room_effects.holds() == set(),
          "and the watchdog holder is released with it")
    check(abs(after - before) < 0.01,
          f"the room comes back to EXACTLY the pre-effect brightness "
          f"({before:.3f} -> {after:.3f})")
    check(not scfg.FLARE_PREVIEW_HOLD_FILE.exists(),
          "no stale hold snapshot is left on disk")
    await _stop(host)


async def run_cost():
    print("\n== 5. the measured write cost, on two devices, on the real clock ==")
    host, _effects = await _start_host("cost")
    room = _room()
    spec = room_effects.RoomEffectSpec(room_id=room.id, kind="dim_wave",
                                       wavelength=WAVELENGTH, speed=SPEED,
                                       depth=0.8)

    async def step(period: float):
        for vid in (LOW, HIGH):
            host.virtuals.get(vid).assemble_frame()
        await asyncio.sleep(period)

    deps = room_effects.RunnerDeps(
        apply_writes=fx_seam.apply_writes, get_virtuals=fx_seam.get_virtuals,
        open_hold=flare_preview_hold.open_program_hold,
        close_hold=flare_preview_hold.close_hold,
        touch_hold=flare_preview_hold.touch,
        clock=time.monotonic, sleep=step)
    await room_effects.start(room, spec, deps)
    await asyncio.sleep(2.0)
    cost = room_effects.write_cost()
    await room_effects.stop(deps)
    await _stop(host)
    print(f"    {json.dumps(cost, indent=6)}")
    check(cost["samples"] > 15, "enough ticks to say anything")
    check(cost["per_tick_ms"]["p95"] < 1000.0 / room_effects.TICK_HZ,
          f"one tick's whole seam call (2 virtuals) costs p95 "
          f"{cost['per_tick_ms']['p95']:.2f} ms against a "
          f"{1000.0 / room_effects.TICK_HZ:.0f} ms budget")
    check(cost["achieved_tick_hz"] > room_effects.TICK_HZ * 0.6,
          f"the loop keeps up ({cost['achieved_tick_hz']} Hz of a "
          f"{room_effects.TICK_HZ} Hz target)")
    return cost


def run_four_kinds():
    print("\n== 6. all four field kinds through the ONE interface ==")
    room = _room()
    samples = [light_field.samples_for(fp, AXIS) for fp in room.footprints]
    ids = {s.emitter_id for s in samples}

    wave = light_field.per_emitter_scalar(
        DimWave(wavelength=WAVELENGTH, speed=SPEED, depth=DEPTH), 0.7,
        samples=samples)
    check(set(wave) == ids and all(0.0 <= v <= 1.0 for v in wave.values()),
          "dim_wave (BUILT) -> a brightness gain per emitter")

    hue = light_field.per_emitter_scalar(
        HueRotation(wavelength=WAVELENGTH, speed=SPEED, span_deg=180.0), 0.7,
        samples=samples)
    check(set(hue) == ids and all(0.0 <= v <= 180.0 for v in hue.values()),
          "hue_rotation (not built) -> degrees, same interface, no new storage")

    out = light_field.per_emitter_scalar(
        explode(cx=0.5, cy=0.9, speed=1.0, width=0.2, depth=1.0), 0.3,
        samples=samples)
    inw = light_field.per_emitter_scalar(
        implode(cx=0.5, cy=0.9, speed=1.0, width=0.2, depth=1.0), 0.3,
        samples=samples)
    check(set(out) == set(inw) == ids and out != inw,
          "implode and explode (not built) -> gains from the 2-D footprint "
          "plane, which is WHY the whole 64x36 grid is stored")
    check([k for k, v in KINDS.items() if v["built"]] == ["dim_wave"],
          "and exactly ONE kind is declared BUILT — the other three drive "
          "nothing, by his own instruction")


async def main():
    await run_travel()
    await run_negative_controls()
    await run_composition()
    await run_bounded()
    await run_cost()
    run_four_kinds()
    print()
    if FAILURES:
        raise SystemExit(f"FAILED {len(FAILURES)} check(s):\n  " +
                         "\n  ".join(FAILURES))
    print("ALL ROOM-EFFECT WAVE CHECKS PASSED")


if __name__ == "__main__":
    # fx's TemporalEffect spawns non-daemon threads that this frame-stepped
    # harness never joins, so a plain return would leave the interpreter
    # alive. _exit unconditionally, carrying the real status.
    status = 0
    try:
        asyncio.run(main())
    except SystemExit as exc:
        print(exc)
        status = 1
    except BaseException:
        import traceback
        traceback.print_exc()
        status = 1
    os._exit(status)
