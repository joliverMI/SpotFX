"""THE CARRIER THE CAPTURE TOOK OFF THE AIR — 2026-09-06, his first real
sconce commissioning run.

WHAT HAPPENED. A per-fixture commission on the copy-mapped `tv-mapper`
carrier finished cleanly and left the carrier INACTIVE: it still held its
effect (blackhole1d) and ran no render thread, so every write to it landed
on nothing. SPECTRA liveness went `healthy=False` with
`activation_gaps {tv-mapper}`, the fixture behind it sat on the frame it
stopped on ("right portion white, staying"), and the lever self-test
reported "no carrier of this room is rendering". Release + take-back
cleared it, which is the tell: nothing was broken, something had simply not
been switched back on.

THE MECHANISM, and it is a property of the device layer, not of this run:
`fx/devices/__init__.py::Device.add_segments_batch` deactivates every
EXTERNAL virtual streaming to a device whose own device-virtual activates.
The capture brings up the fixture's own strip (`tv-backlight`) to light one
block of it — and that takes the carrier standing in front of it off the
air. `deactivate_after_capture` put the strip back to sleep and had no idea
the carrier was ever displaced.

THE BAR THIS TEST SETS, and why it is not a unit test of a flag: the whole
defect is a virtual that LOOKS configured and correct while nothing renders
through it. So this drives a REAL headless host with a real copy-mapped
carrier over a real device, and after the restore asserts all three of
active, a live render thread, and FRESH FRAMES actually arriving — read off
`VIRTUAL_UPDATE`, the event the render thread itself emits, and off the
device's own buffer. A test that asserted only `virtual.active` would pass
against a virtual whose thread had died, which is the neighbouring bug.

AND THE HALF THAT WAS FOUND BY BUILDING THAT PROOF: while the carrier was
still in the capture's write scope, the two virtuals traded the device on
every write. A black write to the displaced carrier takes `fx/facade.py`'s
own repair branch (`_verify_effect_took`, deviation #29), which activates it
to make the write real — and that knocks the substitute back off the air, so
the lit lamp lands on an inactive virtual and the DEVICE MEASURES ZERO on
every pass. Measured here on both sides.

Verified RED against the code as it stood on 2026-09-06: the carrier comes
back `active=False`, no thread, zero frames; and with the carrier left in
scope, the lamp never reaches the fixture at all.
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

DEV = "tv-backlight"        # the fixture, and its own splittable virtual
CARRIER = "tv-mapper"       # copy-mapped, standing in front of it
PIXELS = 60
RUN = 20                    # three runs of twenty — his wrap's shape
#: Longer than the virtual's own crossfade (the LedFX default this config
#: keeps), so a step is read settled rather than mid-transition.
SETTLE_S = 1.0


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Storage AND the category registry: `device_model.CATEGORIES_FILE` is
    a fixed repo-relative path that SPECTRA_STORAGE_DIR does not repoint."""
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_MAPS_FILE", tmp_path / "room_maps.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()


def _own(monkeypatch, tmp_path) -> None:
    from fx import light_ownership as lo
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", path)


def _write_config(config_dir: str) -> None:
    """His shape: one fixture, its own span virtual ASLEEP, and a
    copy-mapped carrier rendering across it."""
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
    """A real host with real render threads — which is the whole point here,
    and also why teardown is explicit: `attach_effect` (every other headless
    test's path) deliberately skips the thread, so nothing else in the suite
    has one to join. A virtual left rendering is a non-daemon thread that
    keeps the interpreter alive forever at exit."""
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


def _renders(host, virtual_id: str) -> bool:
    """Active AND a live render thread — the two halves the defect split
    apart (it held its effect and ran no thread)."""
    virtual = host.virtuals.get(virtual_id)
    thread = getattr(virtual, "_thread", None)
    return bool(virtual and virtual.active
                and thread is not None and thread.is_alive())


def _block_plan():
    """One block of the fixture's own strip — the emitter shape a
    per-fixture run produces once the substitution has happened."""
    from spectra.services import emitters as em
    return em.Plan(emitters=[em.Emitter(emitter_id=f"{DEV}:blk0[0-{RUN - 1}]",
                                        carrier_id=CARRIER, label="block 1",
                                        virtual_ids=[DEV])],
                   granularity="block", block_pixels=RUN)


def test_the_capture_puts_the_displaced_copy_mapped_carrier_back_on_the_air(
        tmp_path, monkeypatch):
    _own(monkeypatch, tmp_path)
    from spectra.services import room_mapping

    async def go():
        async with _started(tmp_path) as host:
            deps = room_mapping.production_deps(session=None)
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            assert scope == [CARRIER], (
                "the carrier is what is rendering; the fixture's own strip "
                "is asleep, which is why the run has to bring it up")
            assert _renders(host, CARRIER) and not _renders(host, DEV)

            activation = await room_mapping.activate_for_capture(
                _block_plan(), scope, deps)
            assert activation.activated == [DEV]
            assert activation.failed == []
            # MEASURED, not inferred: the run reads what stopped rendering.
            assert activation.displaced == [CARRIER]
            assert not _renders(host, CARRIER), (
                "mid-capture the carrier really is off the air — that is the "
                "device layer's own exclusion rule, and the reason this "
                "restore has to exist")

            restore = await room_mapping.deactivate_after_capture(
                activation, deps)
            assert restore.left_on == [], "the strip goes back to sleep"
            assert restore.not_restored == []

            # 1. the flag, 2. a live render thread, 3. FRESH FRAMES.
            assert _renders(host, CARRIER)
            assert not _renders(host, DEV)
            tap = headless.FrameTap(host, CARRIER)
            try:
                await asyncio.sleep(0.4)
            finally:
                tap.close()
            assert tap.frames, (
                "the carrier holds its effect but nothing renders through "
                "it — writes to it would land on nothing, which is exactly "
                "what he woke up to")

            # and the light really is reaching the fixture again
            pixels = np.asarray(host.devices.get(DEV).assemble_frame(),
                                dtype=float)
            assert pixels[:, 0].mean() > 200.0, (
                "the fixture is showing the carrier's own red again, not the "
                "black lamp the capture left on it")

            # the scope the liveness surface and the lever self-test read
            assert await room_mapping.live_virtual_ids(
                deps.get_virtuals) == [CARRIER]

    asyncio.run(go())


def test_a_run_that_displaces_nothing_re_activates_nothing(tmp_path,
                                                           monkeypatch):
    """The negative control. A restore that re-activated on a guess would
    put a virtual he had switched off back on the air — so nothing is
    re-activated unless it was OBSERVED to stop rendering during this run's
    own activation."""
    _own(monkeypatch, tmp_path)
    from spectra.services import emitters as em
    from spectra.services import room_mapping

    async def go():
        async with _started(tmp_path) as host:
            deps = room_mapping.production_deps(session=None)
            reactivated: list[str] = []
            real = deps.reactivate

            async def watched(vid):
                reactivated.append(vid)
                await real(vid)

            deps.reactivate = watched
            # a plan whose only emitter IS the carrier: nothing to bring up,
            # so nothing can be displaced
            plan = em.Plan(emitters=[em.Emitter(
                emitter_id=CARRIER, carrier_id=CARRIER, label=CARRIER,
                virtual_ids=[CARRIER])], granularity="whole", block_pixels=30)
            activation = await room_mapping.activate_for_capture(
                plan, [CARRIER], deps)
            assert activation.activated == []
            assert activation.displaced == []
            restore = await room_mapping.deactivate_after_capture(
                activation, deps)
            assert restore.left_on == [] and restore.not_restored == []
            assert reactivated == []
            assert _renders(host, CARRIER)
            assert not _renders(host, DEV), (
                "a virtual nobody asked for stays asleep")

    asyncio.run(go())


def test_a_carrier_that_cannot_be_put_back_is_named_not_only_logged(
        tmp_path, monkeypatch):
    """A room left in the broken state must SAY so. The sentence names the
    consequence (holds an effect, runs no render thread, writes land on
    nothing) and the one press that fixes it."""
    _own(monkeypatch, tmp_path)
    from spectra.services import mapping_refusals, room_mapping

    async def go():
        async with _started(tmp_path) as host:
            deps = room_mapping.production_deps(session=None)

            async def refuse(_vid):
                raise OSError("no route to host")

            deps.reactivate = refuse
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            activation = await room_mapping.activate_for_capture(
                _block_plan(), scope, deps)
            assert activation.displaced == [CARRIER]
            restore = await room_mapping.deactivate_after_capture(
                activation, deps)
            assert restore.not_restored and CARRIER in restore.not_restored[0]
            sentence = mapping_refusals.carrier_not_restored(
                restore.not_restored)
            assert CARRIER in sentence and "render thread" in sentence
            assert not _renders(host, CARRIER), "and it really is still down"

    asyncio.run(go())


def test_the_lamp_actually_reaches_the_fixture_for_the_whole_run(tmp_path,
                                                                 monkeypatch):
    """THE OTHER HALF, and the reason a displaced virtual leaves the write
    scope rather than merely being restored at the end.

    This drives the REAL `MappingProgram`'s own dark and lit payloads
    through the REAL write seam, twice — an emitter is two steps and a run
    is many emitters — and measures the DEVICE's own buffer, which is what
    the camera would see. With the displaced carrier still in scope the
    facade's repair reactivates it on the first write, the substitute goes
    down, and every later lamp lands on nothing: `lit == 0` on both passes.
    """
    _own(monkeypatch, tmp_path)
    from spectra.models.room_map import PixelRange
    from spectra.services import fx_seam, room_mapping

    async def go():
        async with _started(tmp_path) as host:
            deps = room_mapping.production_deps(session=None)
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            activation = await room_mapping.activate_for_capture(
                _block_plan(), scope, deps)
            assert activation.displaced == [CARRIER]
            assert activation.scope == [DEV], (
                "the displaced carrier is OUT of the write scope: it cannot "
                "render while the strip holds the device, and writing to it "
                "would take the facade's repair branch and hand the device "
                "straight back")

            program = room_mapping.MappingProgram(activation.scope)
            program.select([DEV], [PixelRange(virtual_id=DEV, start=0,
                                              end=RUN - 1)])
            device = host.devices.get(DEV)

            async def step(name: str) -> int:
                """One capture step, then read the DEVICE — nothing is
                hand-flushed here: the virtual's own render thread is what
                drives the fixture, which is the whole question. The settle
                outlasts the virtual's crossfade, exactly what
                DARK_SETTLE_S/LIT_SETTLE_S buy the real run."""
                await fx_seam.apply_writes(
                    program._writes(name == "lit"),
                    transition_ms=room_mapping.WRITE_TRANSITION_MS)
                await asyncio.sleep(SETTLE_S)
                pixels = np.asarray(device.assemble_frame(), dtype=float)
                assert _renders(host, DEV), (
                    f"the lamp's own virtual went off the air during the "
                    f"{name} step — the camera would photograph nothing")
                return int((pixels.max(axis=1) > 8.0).sum())

            for _emitter_pass in range(2):
                assert await step("dark") == 0, "the room really is dark"
                assert await step("lit") == RUN, (
                    "exactly the emitter's own block of the fixture is lit — "
                    "0 here is the run that maps nothing and cannot say why")

            restore = await room_mapping.deactivate_after_capture(
                activation, deps)
            assert restore.left_on == [] and restore.not_restored == []
            assert _renders(host, CARRIER) and not _renders(host, DEV)

    asyncio.run(go())
