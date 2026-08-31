"""Executable spec for THE PER-VIRTUAL GAIN MASK — his own correction,
measured on the REAL render pipeline: "A single device that spans the
direction of the wave should be able to show the effect. the tv mapper is
wrapped around a tv. It should be able to run a dimness wave vertically."

ONE synthetic device, wrapped round a television in three runs of twenty
pixels, mapped at SUB-DEVICE granularity so each run has its own measured
footprint at its own place on the room's floor-to-ceiling axis. A single
Dim Wave then runs over it and the phase lag between the strip's BOTTOM
pixels and its TOP pixels is read off the assembled frame — the literal
pixel buffer the device driver receives, stepped through fx.headless with
fx.facade owning the room, the same rig scripts/check_room_effect_wave.py
and tests/test_room_preview.py use.

WHY THE REAL PIPELINE, AND WHY THE FRAME. A gain that is right in a dict
and never reaches a light is the defect this project has shipped before
(the flare preview that "did not actually change anything on the lights").
A per-pixel gain has a second way to be wrong that a scalar one does not:
it can reach the light at the wrong PIXELS. So nothing here asserts against
room_effects' own mask dictionary; every number comes from
`virtual.assemble_frame()`.

WHAT IS PROVEN
  1. the wave travels ALONG ONE DEVICE: the measured phase difference
     between its bottom and top pixel ranges matches the wave's own travel
     between those ranges' measured axis positions;
  2. NEGATIVE CONTROLS — depth 0 renders an exactly flat strip, speed 0 is
     a standing wave whose two ends sit at different constant levels;
  3. BIT-IDENTITY when no sub-device emitter is driven: a whole-device room
     installs no mask at any tick, so fx/virtuals.py's multiply is never
     reached — and an explicitly installed all-ones mask renders a frame
     byte-identical to no mask at all, so the branch is the identity even
     when it IS reached;
  4. the mask comes OUT before the room is handed back: after stop() the
     strip is uniform again at exactly the show's own brightness;
  5. WRITE COST re-measured at the new granularity, whole-device and masked
     side by side, against the 15 Hz tick budget.

Run from repo root: .venv/bin/python scripts/check_room_effect_mask.py
Isolated: temp fx config + temp SPECTRA storage, one dummy device, audio
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


td = Path(tempfile.mkdtemp(prefix="spectra-mask-"))

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

from fx import facade, headless, light_ownership, virtual_gain_mask  # noqa: E402
from fx.host import FxHost                                    # noqa: E402
from spectra.models.room_map import (GRID_H, GRID_W, AxisCalibration,  # noqa: E402
                                     EmitterFootprint, PixelRange, Point,
                                     RoomMap)
from spectra.services import (flare_preview_hold, fx_seam, light_field,  # noqa: E402
                              room_effects)

light_ownership.OWNERSHIP_FILE = td / "ownership.json"
light_ownership.OWNERSHIP_FILE.write_text(json.dumps({"owner": "spectra"}))

DEVICE = "tv-mapper"
VIRTUAL = "tv-mapper"          # a device-virtual: same id, the ordinary case
PIXELS = 60
RUN = 20
SHOW_BRIGHTNESS = 0.8
WAVELENGTH, SPEED, DEPTH = 1.0, 0.25, 0.9
TICK_S = 1.0 / room_effects.TICK_HZ

#: The three runs of the wrap, and the axis band each one's light was
#: MEASURED to land in. Declared before the run: the phase lag is predicted
#: from these and then measured off rendered pixels.
RUNS = (
    ("bottom", (0, RUN - 1), (0.05, 0.20)),
    ("middle", (RUN, 2 * RUN - 1), (0.45, 0.55)),
    ("top", (2 * RUN, PIXELS - 1), (0.78, 0.95)),
)

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


def _write_config(config_dir: str) -> None:
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": [{"id": DEVICE, "type": "dummy",
                                "config": {"name": DEVICE,
                                           "pixel_count": PIXELS}}],
                   "virtuals": [{"id": VIRTUAL, "is_device": DEVICE,
                                 "auto_generated": False,
                                 "config": {"name": VIRTUAL, "mapping": "span",
                                            "rows": 1},
                                 "segments": [
                                     [DEVICE, 0, RUN - 1, False],
                                     [DEVICE, RUN, 2 * RUN - 1, False],
                                     [DEVICE, 2 * RUN, PIXELS - 1, False]]}]},
                  fh)


def _footprint(emitter_id: str, band, ranges) -> EmitterFootprint:
    """A footprint occupying one horizontal band of the camera frame — the
    map's own storage shape, hand-built so the axis position is ground truth
    rather than something a capture happened to produce."""
    lo, hi = band
    grid = np.zeros((GRID_H, GRID_W))
    y0 = int(round((1.0 - hi) * GRID_H))
    y1 = max(y0 + 1, int(round((1.0 - lo) * GRID_H)))
    grid[y0:y1, :] = 1.0
    return EmitterFootprint(emitter_id=emitter_id, device_id=DEVICE,
                            virtual_ids=[VIRTUAL],
                            ranges=ranges,
                            grid=[float(v) for v in grid.reshape(-1)],
                            weight=float(grid.sum()))


def sub_device_room() -> RoomMap:
    """The television, mapped per run: three emitters, one device."""
    room = RoomMap(name="TV wrap", device_ids=[DEVICE], axis=AXIS,
                   granularity="segment")
    for name, (lo, hi), band in RUNS:
        room.put_footprint(_footprint(
            f"{DEVICE}:seg{name}[{lo}-{hi}]", band,
            [PixelRange(virtual_id=VIRTUAL, start=lo, end=hi)]))
    return room


def whole_device_room() -> RoomMap:
    """The SAME television, mapped the shipped way: one emitter, no ranges.

    Its footprint is the UNION of the three runs' bands — which is exactly
    what a device-granularity capture of this fixture produces
    (scripts/check_light_field_granularity.py proves that merge cell for
    cell), so the control is the same television seen the old way, not a
    different fixture."""
    grid = np.zeros((GRID_H, GRID_W))
    for _n, _s, (lo, hi) in RUNS:
        y0 = int(round((1.0 - hi) * GRID_H))
        y1 = max(y0 + 1, int(round((1.0 - lo) * GRID_H)))
        grid[y0:y1, :] = 1.0
    room = RoomMap(name="TV whole", device_ids=[DEVICE], axis=AXIS)
    room.put_footprint(EmitterFootprint(
        emitter_id=DEVICE, device_id=DEVICE, virtual_ids=[VIRTUAL], ranges=[],
        grid=[float(v) for v in grid.reshape(-1)], weight=float(grid.sum())))
    return room


def many_ranges_room(block: int = 3) -> RoomMap:
    """The same television at BLOCK granularity — 20 emitters on one virtual.

    The cost stress. Twenty emitters is the shape a real 560-pixel TV wrap
    takes at the shipped default block size of 30, and the term that
    dominates a tick is the per-emitter reduction over each footprint's
    2304 cells, not the length of the mask array — so this measures the
    same work on a smaller strip."""
    room = RoomMap(name="TV blocks", device_ids=[DEVICE], axis=AXIS,
                   granularity="block", block_pixels=block)
    for lo in range(0, PIXELS, block):
        hi = min(PIXELS - 1, lo + block - 1)
        band_lo = 0.05 + 0.9 * (lo / PIXELS)
        room.put_footprint(_footprint(
            f"{DEVICE}:seg[{lo}-{hi}]", (band_lo, band_lo + 0.06),
            [PixelRange(virtual_id=VIRTUAL, start=lo, end=hi)]))
    return room


#: Filled in by section one, read by section three: the swing ONE run of the
#: wrap achieves when the device is mapped per range. The whole-device
#: control is compared against it rather than against a fixed number,
#: because "how much less" is the measurement his correction is about.
SUB_DEVICE_SWING = {"value": 0.0}


def mean_axis(band) -> float:
    fp = _footprint("x", band, [])
    s = light_field.samples_for(fp, AXIS)
    return float((s.axis * s.weight).sum() / s.weight.sum())


async def start_host(tag: str):
    config_dir = str(td / f"fx-{tag}")
    _write_config(config_dir)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    virtual = host.virtuals.get(VIRTUAL)
    headless.attach_effect(host, virtual, "singleColor",
                           {"color": "#ffffff", "brightness": SHOW_BRIGHTNESS,
                            "background_brightness": 0.0})
    return host


def frame_of(host) -> np.ndarray:
    virtual = host.virtuals.get(VIRTUAL)
    frame = virtual.assemble_frame()
    if frame is None:
        return np.zeros((PIXELS, 3))
    virtual.flush(frame)
    return np.asarray(frame, dtype=float)


def run_level(frame: np.ndarray, span) -> float:
    lo, hi = span
    return float(frame[lo:hi + 1].mean()) / 255.0


def circular_phase(times, values, omega) -> float:
    t = np.asarray(times)
    y = np.asarray(values, dtype=float)
    y = y - y.mean()
    c = float((y * np.cos(omega * t)).sum())
    s = float((y * np.sin(omega * t)).sum())
    return math.atan2(s, c)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def deps_for(clock, step) -> room_effects.RunnerDeps:
    return room_effects.RunnerDeps(
        apply_writes=fx_seam.apply_writes, get_virtuals=fx_seam.get_virtuals,
        open_hold=flare_preview_hold.open_program_hold,
        close_hold=flare_preview_hold.close_hold,
        touch_hold=flare_preview_hold.touch,
        spectra_owns=lambda: True,
        clock=clock, sleep=step)


async def drive(room: RoomMap, tag: str, *, depth=DEPTH, speed=SPEED,
                periods=2.0):
    """Run the wave for `periods` of it, sampling the rendered frame once per
    tick. Returns (host, start-result, times, per-run series, mask sightings)."""
    host = await start_host(tag)
    spec = room_effects.RoomEffectSpec(room_id=room.id, kind="dim_wave",
                                       wavelength=WAVELENGTH, speed=speed,
                                       depth=depth)
    times: list[float] = []
    series: dict[str, list[float]] = {n: [] for n, _s, _b in RUNS}
    masked_seen: list[int] = []
    holds_seen: list[tuple] = []
    now = {"t": 1000.0}
    total = periods / max(1e-9, speed) if speed else periods * 4.0
    ticks = int(total / TICK_S)

    async def step(period: float):
        now["t"] += period
        frame = frame_of(host)
        times.append(now["t"])
        for name, span, _band in RUNS:
            series[name].append(run_level(frame, span))
        masked_seen.append(len(virtual_gain_mask.stats()["masked_virtuals"]))
        holds_seen.append(tuple(sorted(room_effects.holds())))
        await asyncio.sleep(0)

    deps = deps_for(lambda: now["t"], step)
    started = await room_effects.start(room, spec, deps)
    while len(times) < ticks:
        await asyncio.sleep(0)
        if not started.get("running"):
            break
    cost = room_effects.write_cost()
    await room_effects.stop(deps)
    return host, started, times, series, masked_seen, holds_seen, cost


async def stop_host(_host) -> None:
    # Deliberately does NOT call host.stop(): the vendored FxHost refuses it
    # and this harness never started the render threads it would join.
    await asyncio.sleep(0)


# ── ONE — the wave travels ALONG one device ───────────────────────────────

async def section_one():
    print("\n== 1. a vertical wave ALONG one wrapped device, measured on "
          "rendered pixels ==")
    room = sub_device_room()
    host, started, times, series, masked_seen, holds_seen, _cost = await drive(
        room, "travel")
    check(started.get("running"), f"the effect started: {started.get('reason', '')}")
    check(len(started.get("emitters", [])) == 3,
          f"three emitters on ONE device drive it ({started.get('emitters')})")
    check(started.get("masked_virtuals") == [VIRTUAL]
          and started.get("scalar_virtuals") == [],
          "the virtual is driven by a per-pixel MASK, not a single "
          "brightness number")
    check(started.get("mask_pixels", {}).get(VIRTUAL) == PIXELS,
          f"the mask is one value per effect pixel "
          f"({started.get('mask_pixels')})")
    check(min(masked_seen) == 1,
          "a mask is genuinely installed in the render path on every tick")
    check(set(holds_seen) == {()},
          "and NO watchdog holder is claimed at any tick: a mask never "
          "enters the effect config the watchdog compares against")

    omega = 2 * math.pi * SPEED
    a_bottom = mean_axis(RUNS[0][2])
    a_top = mean_axis(RUNS[2][2])
    phi_bottom = circular_phase(times, series["bottom"], omega)
    phi_top = circular_phase(times, series["top"], omega)
    predicted = 2 * math.pi * (a_top - a_bottom) / WAVELENGTH
    measured = wrap(phi_top - phi_bottom)
    err = abs(wrap(measured - predicted))
    print(f"    axis: bottom {a_bottom:.3f}  top {a_top:.3f}   "
          f"predicted lag {(a_top - a_bottom) / (WAVELENGTH * SPEED):.2f}s "
          f"(= {wrap(predicted):+.3f} rad)")
    print(f"    measured phase difference {measured:+.3f} rad "
          f"(error {math.degrees(err):.1f}deg)")
    check(err < math.radians(12),
          f"the MEASURED phase lag between the strip's BOTTOM and TOP pixels "
          f"matches the wave's own travel to within 12 degrees "
          f"({math.degrees(err):.1f}deg) — one device, a wave running along "
          f"it, which is exactly what he asked for")

    swings = {n: (max(series[n]) - min(series[n])) for n, _s, _b in RUNS}
    SUB_DEVICE_SWING["value"] = min(swings.values())
    check(all(v > 0.5 * DEPTH * SHOW_BRIGHTNESS for v in swings.values()),
          f"all three runs genuinely modulate "
          f"({', '.join(f'{k} {v:.3f}' for k, v in swings.items())})")
    check(max(max(series[n]) for n, _s, _b in RUNS) <= SHOW_BRIGHTNESS + 0.02,
          "the crest never exceeds the show's own brightness — a dim wave "
          "only ever takes light away")

    # the thing a whole-device map structurally cannot do
    spread = [abs(series[n][i] - series["bottom"][i])
              for n, _s, _b in RUNS[1:] for i in range(len(times))]
    check(max(spread) > 0.15,
          f"and at some instant the two ends of ONE device are at genuinely "
          f"different brightnesses ({max(spread):.3f}) — the whole point, and "
          f"impossible with one gain per fixture")
    await stop_host(host)


# ── TWO — negative controls ───────────────────────────────────────────────

async def section_two():
    print("\n== 2. negative controls ==")
    room = sub_device_room()
    host, _s, times, series, _m, _h, _c = await drive(room, "depth0", depth=0.0)
    flat = {n: (max(series[n]) - min(series[n])) for n, _sp, _b in RUNS}
    check(max(flat.values()) < 1e-9,
          f"depth 0 renders an EXACTLY flat strip ({max(flat.values()):.2e}) — "
          f"the feature is a no-op when it is turned down, not approximately "
          f"one")
    check(abs(series["bottom"][-1] - SHOW_BRIGHTNESS) < 0.01,
          "and leaves the show's own brightness exactly where it was")
    await stop_host(host)

    room = sub_device_room()
    host, _s, times, series, _m, _h, _c = await drive(room, "speed0", speed=0.0,
                                                      periods=1.0)
    spread = {n: (max(series[n]) - min(series[n])) for n, _sp, _b in RUNS}
    check(max(spread.values()) < 1e-9,
          "speed 0 is a STANDING wave: every pixel range holds one constant "
          "level, so a lag measured at speed 0 would have been an artefact")
    first = {n: series[n][0] for n, _sp, _b in RUNS}
    check(max(first.values()) - min(first.values()) > 0.2,
          f"and the three runs sit at genuinely DIFFERENT points of it "
          f"({', '.join(f'{k} {v:.3f}' for k, v in first.items())}) — the "
          f"axis is being read through the ranges, not applied uniformly")
    await stop_host(host)


# ── THREE — bit-identity with no sub-device emitters ──────────────────────

async def section_three():
    print("\n== 3. NO sub-device emitters: the render path is untouched ==")
    room = whole_device_room()
    host, started, times, series, masked_seen, holds_seen, _c = await drive(
        room, "whole")
    check(started.get("running"), "the whole-device wave still runs")
    check(started.get("masked_virtuals") == []
          and started.get("scalar_virtuals") == [VIRTUAL],
          "it drives ONE scalar gain, the shipped path, with no mask")
    check(max(masked_seen) == 0,
          f"NO mask is installed at ANY tick ({max(masked_seen)}) — so "
          f"fx/virtuals.py's multiply is never reached and the assembled "
          f"frame is the fork's own, byte for byte")
    check(set(holds_seen) == {((VIRTUAL, "brightness"),)},
          "it DOES claim a watchdog holder at every tick, because on this "
          "path it really is moving the virtual's brightness param — the "
          "shipped behaviour, unchanged")
    swing = max(series["bottom"]) - min(series["bottom"])
    check(swing > 0.01,
          f"the whole device still modulates as one ({swing:.3f}) — the "
          f"shipped path still works")
    check(swing < 0.4 * SUB_DEVICE_SWING["value"],
          f"but it modulates FAR LESS ({swing:.3f} against {SUB_DEVICE_SWING['value']:.3f} "
          f"for one run of the same fixture mapped per range): a footprint "
          f"spanning the wave AVERAGES it away, which is the measurement his "
          f"correction is about")
    ends = max(abs(series["bottom"][i] - series["top"][i])
               for i in range(len(times)))
    check(ends < 1e-9,
          f"with its two ends ALWAYS identical ({ends:.2e}) — which is the "
          f"limitation his correction was about, reproduced here as the "
          f"control")

    # and the branch is the identity even when it IS reached
    virtual = host.virtuals.get(VIRTUAL)
    bare = np.array(virtual.assemble_frame(), copy=True)
    virtual_gain_mask.apply_masks({VIRTUAL: np.ones(PIXELS)})
    ones = np.array(virtual.assemble_frame(), copy=True)
    virtual_gain_mask.clear()
    check(np.array_equal(bare, ones),
          "an explicitly installed all-ones mask renders a BYTE-IDENTICAL "
          "frame — the multiply is the exact identity at 1.0, not an "
          "approximate one")

    # a wrong-length mask is skipped, never resampled
    virtual_gain_mask.apply_masks({VIRTUAL: np.full(PIXELS // 2, 0.25)})
    before = virtual_gain_mask.stats()["skipped_length_mismatch"]
    short = np.array(virtual.assemble_frame(), copy=True)
    after = virtual_gain_mask.stats()["skipped_length_mismatch"]
    virtual_gain_mask.clear()
    check(np.array_equal(bare, short) and after > before,
          "a mask of the wrong length is SKIPPED and COUNTED, never "
          "resampled — a stretched gain is a wave at the wrong wavelength, "
          "which is worse than no wave")
    await stop_host(host)


# ── FOUR — the mask comes out with the room ───────────────────────────────

async def section_four():
    print("\n== 4. bounded: the mask comes OUT before the room is handed back ==")
    host = await start_host("bounded")
    before = frame_of(host)
    room = sub_device_room()
    spec = room_effects.RoomEffectSpec(room_id=room.id, kind="dim_wave",
                                       wavelength=WAVELENGTH, speed=SPEED,
                                       depth=1.0)
    now = {"t": 500.0}
    seen = {"n": 0}

    async def step(period: float):
        now["t"] += period
        seen["n"] += 1
        frame_of(host)
        await asyncio.sleep(0)

    deps = deps_for(lambda: now["t"], step)
    started = await room_effects.start(room, spec, deps)
    check(started.get("running"), "started")
    check(flare_preview_hold.active(),
          "a masked room effect HOLDS the room on the SAME one hold — "
          "snapshot, deadline, sweep, 3-minute ceiling and restart recovery "
          "all inherited, never a second hold system")
    check(room_effects.holds() == set(),
          "and registers NO watchdog holder: a mask never enters the effect "
          "config the watchdog compares against, so a holder there would be "
          "a claim about a param this layer is not moving")
    while seen["n"] < 20:
        await asyncio.sleep(0)
    mid = frame_of(host)
    ends = abs(float(mid[:RUN].mean()) - float(mid[-RUN:].mean())) / 255.0
    check(ends > 0.05,
          f"the strip is genuinely non-uniform mid-run ({ends:.3f})")

    await room_effects.stop(deps)
    after = frame_of(host)
    check(not flare_preview_hold.active(), "stopping releases the hold")
    check(virtual_gain_mask.stats()["masked_virtuals"] == [],
          "and every mask is out of the render path")
    check(np.array_equal(before, after),
          "the strip comes back BYTE-IDENTICAL to before the effect ran — a "
          "mask left installed for even one frame after the revert would "
          "hand the room back dimmed in a way no write could correct")
    check(not scfg.FLARE_PREVIEW_HOLD_FILE.exists(),
          "no stale hold snapshot is left on disk")
    await stop_host(host)


# ── FIVE — write cost at the new granularity ──────────────────────────────

async def section_five():
    print("\n== 5. the measured write cost at the NEW granularity, on the "
          "real clock ==")
    out = {}
    for tag, room, label in (("cost-whole", whole_device_room(),
                              "whole device (1 scalar write/tick)"),
                             ("cost-mask", sub_device_room(),
                              "3 ranges masked (0 writes/tick)"),
                             ("cost-mask-20", many_ranges_room(),
                              "20 ranges masked — a real TV wrap's shape")):
        host = await start_host(tag)
        spec = room_effects.RoomEffectSpec(room_id=room.id, kind="dim_wave",
                                           wavelength=WAVELENGTH, speed=SPEED,
                                           depth=0.8)

        async def step(period: float):
            frame_of(host)
            await asyncio.sleep(period)

        deps = deps_for(time.monotonic, step)
        started = await room_effects.start(room, spec, deps)
        if not started.get("running"):
            check(False, f"{label}: {started.get('reason')}")
            continue
        await asyncio.sleep(2.0)
        cost = room_effects.write_cost()
        await room_effects.stop(deps)
        await stop_host(host)
        out[tag] = cost
        print(f"    {label}: p50 {cost['per_tick_ms']['p50']:.3f} ms, "
              f"p95 {cost['per_tick_ms']['p95']:.3f} ms, "
              f"max {cost['per_tick_ms']['max']:.3f} ms, "
              f"{cost['achieved_tick_hz']} Hz of {room_effects.TICK_HZ}, "
              f"{cost['writes_per_s']} writes/s")

    budget = 1000.0 / room_effects.TICK_HZ
    for tag, cost in out.items():
        check(cost["samples"] > 15, f"{tag}: enough ticks to say anything")
        check(cost["per_tick_ms"]["p95"] < budget,
              f"{tag}: one tick costs p95 {cost['per_tick_ms']['p95']:.3f} ms "
              f"against a {budget:.0f} ms budget")
        check(cost["achieved_tick_hz"] > room_effects.TICK_HZ * 0.6,
              f"{tag}: the loop keeps up ({cost['achieved_tick_hz']} Hz)")
    if "cost-mask" in out and "cost-whole" in out:
        check(out["cost-mask"]["per_tick_ms"]["p50"]
              <= out["cost-whole"]["per_tick_ms"]["p50"] + 1.0,
              f"the FINER granularity is not more expensive per tick "
              f"({out['cost-mask']['per_tick_ms']['p50']:.3f} ms masked vs "
              f"{out['cost-whole']['per_tick_ms']['p50']:.3f} ms whole-device) "
              f"— a masked virtual costs no seam write at all, which is the "
              f"opposite of the plan's named risk")
        check(out["cost-mask"]["writes_per_s"] == 0.0,
              "a fully masked room makes ZERO seam writes per second")
    if "cost-mask-20" in out:
        big = out["cost-mask-20"]
        check(big["masked_per_tick"] == 1 and big["mask_pixels_per_tick"] == PIXELS,
              "twenty emitters resolve into ONE mask over the virtual they "
              "share, so the render path sees one multiply however fine the "
              "granularity gets")
        check(big["per_tick_ms"]["p95"] < budget,
              f"twenty ranges cost p95 {big['per_tick_ms']['p95']:.3f} ms of "
              f"the {budget:.0f} ms tick — the granularity his television "
              f"needs holds the 15 Hz target with room to spare")


async def main():
    await section_one()
    await section_two()
    await section_three()
    await section_four()
    await section_five()
    print()
    if FAILURES:
        raise SystemExit(f"FAILED {len(FAILURES)} check(s):\n  " +
                         "\n  ".join(FAILURES))
    print("ALL ROOM-EFFECT MASK CHECKS PASSED")


if __name__ == "__main__":
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
