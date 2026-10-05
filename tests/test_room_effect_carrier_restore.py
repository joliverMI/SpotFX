"""A ROOM EFFECT GIVES THE CARRIER BACK, AND WAVES THE SHOW (D2).

THE INCIDENT (Light Show room proof, 2026-10-04 20:56): a Dim Wave step
brought up the TV backlight's own strip (the mapped substitute). That took
the copy-mapped `tv-mapper` — the show's only renderer on that fixture —
OFF THE AIR (the device layer's exclusion, deviation #29), the wave then
multiplied the substitute's BLACK capture lamp so the TV sat black for 15 s,
and stop() put the substitute to sleep without bringing the carrier back:
liveness 503, the fixture on WLED's idle preset until a scene was re-fired.

MEASURED on a real FxHost with real render threads (the
test_capture_carrier_restore.py rig): during the wave the substitute
renders the CARRIER'S OWN effect (the show, not black); a show write to the
carrier lands on the substitute instead of evicting it; after stop the
carrier is active, has a live render thread and fresh frames, and carries
the newest show state.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

import numpy as np
import pytest

from fx import device_model, facade, headless
from fx.host import FxHost
from spectra.models.room_map import (GRID_H, GRID_W, AxisCalibration,
                                     EmitterFootprint, PixelRange, Point,
                                     RoomMap)
from spectra.services import fx_seam, room_effects

DEV, CARRIER = "tv-backlight", "tv-mapper"
PIXELS, RUN = 60, 20
AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from fx import light_ownership as lo
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    original = device_model.CATEGORIES_FILE
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", path)
    room_effects.reset()
    yield
    room_effects.reset()
    device_model.CATEGORIES_FILE = original
    device_model.refresh()


def _write_config(config_dir: str) -> None:
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({
            "configuration_version": CONFIGURATION_VERSION,
            "devices": [{"id": DEV, "type": "dummy",
                         "config": {"name": DEV, "pixel_count": PIXELS}}],
            "virtuals": [
                {"id": DEV, "is_device": DEV, "auto_generated": False,
                 "config": {"name": DEV, "mapping": "span", "rows": 1},
                 "segments": [[DEV, 0, PIXELS - 1, False]],
                 "active": False},
                {"id": CARRIER, "is_device": False, "auto_generated": False,
                 "config": {"name": CARRIER, "mapping": "copy", "rows": 1},
                 "segments": [[DEV, 0, RUN - 1, False],
                              [DEV, RUN, 2 * RUN - 1, False],
                              [DEV, 2 * RUN, PIXELS - 1, False]],
                 "active": True,
                 "effect": {"type": "singleColor",
                            "config": {"color": "#ff0000",
                                       "brightness": 1.0,
                                       "background_brightness": 0.0}}},
            ],
        }, fh)


@asynccontextmanager
async def _started(tmp_path):
    headless.silence_audio()
    _write_config(str(tmp_path / "fx"))
    host = FxHost(str(tmp_path / "fx"))
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    try:
        yield host
    finally:
        facade.set_host(None)
        await host.shutdown()


def _renders(host, vid) -> bool:
    v = host.virtuals.get(vid)
    t = getattr(v, "_thread", None)
    return bool(v and v.active and t is not None and t.is_alive())


def _fp(eid, lo, hi, start, end) -> EmitterFootprint:
    grid = np.zeros((GRID_H, GRID_W))
    y0 = int(round((1.0 - hi) * GRID_H))
    y1 = max(y0 + 1, int(round((1.0 - lo) * GRID_H)))
    grid[y0:y1, :] = 1.0
    return EmitterFootprint(
        emitter_id=eid, virtual_ids=[DEV], carrier_id=CARRIER,
        ranges=[PixelRange(virtual_id=DEV, start=start, end=end)],
        grid=[float(v) for v in grid.reshape(-1)], weight=float(grid.sum()))


def _room() -> RoomMap:
    room = RoomMap(name="Living Room", carrier_ids=[CARRIER], axis=AXIS)
    room.put_footprint(_fp(f"{DEV}:blk0[0-29]", 0.0, 0.4, 0, 29))
    room.put_footprint(_fp(f"{DEV}:blk1[30-59]", 0.6, 1.0, 30, 59))
    return room


def _deps():
    d = room_effects.production_deps()
    d.open_hold = d.close_hold = d.touch_hold = None
    return d


def _red(host) -> float:
    px = np.asarray(host.devices.get(DEV).assemble_frame(), dtype=float)
    return float(px[:, 0].mean())


def test_the_wave_renders_the_show_and_the_carrier_comes_back(tmp_path):
    async def go():
        async with _started(tmp_path) as host:
            assert _renders(host, CARRIER) and not _renders(host, DEV)
            deps = _deps()
            out = await room_effects.start(
                _room(), room_effects.RoomEffectSpec(room_id="r"), deps)
            assert out["running"], out
            assert _renders(host, DEV)
            eff = host.virtuals.get(DEV).active_effect
            assert eff.config["color"].lower().startswith("#ff0000"), (
                "the substitute renders the BLACK lamp — the wave would "
                "multiply black, which is what the TV showed for 15 s")
            assert out.get("displaced") == [CARRIER]

            # the show keeps playing through the substitute, not the carrier
            await fx_seam.apply_writes([{
                "virtual_id": CARRIER, "effect_type": "singleColor",
                "config": {"color": "#00ff00", "brightness": 1.0,
                           "background_brightness": 0.0}}])
            assert _renders(host, DEV), "a show write evicted the substitute"
            assert host.virtuals.get(DEV).active_effect.config[
                "color"].lower().startswith("#00ff00")

            stopped = await room_effects.stop(deps)
            assert _renders(host, CARRIER), "the carrier was left off the air"
            assert stopped.get("restored") == [CARRIER]
            assert stopped.get("not_restored") == []
            assert not _renders(host, DEV)
            assert host.virtuals.get(CARRIER).active_effect.config[
                "color"].lower().startswith("#00ff00"), (
                "the carrier came back on a stale show state")
            tap = headless.FrameTap(host, CARRIER)
            try:
                await asyncio.sleep(0.4)
            finally:
                tap.close()
            assert tap.frames
    asyncio.run(go())


def test_an_unreachable_substitute_is_not_brought_up(tmp_path):
    async def go():
        async with _started(tmp_path) as host:
            deps = _deps()
            deps.unreachable_devices = lambda: {DEV}
            out = await room_effects.start(
                _room(), room_effects.RoomEffectSpec(room_id="r"), deps)
            assert not out["running"]
            assert room_effects._state.skipped_unreachable == [DEV]
            assert _renders(host, CARRIER), "the show was evicted for nothing"
            assert not _renders(host, DEV)
    asyncio.run(go())
