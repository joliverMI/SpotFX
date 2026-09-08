"""A CAPTURE RUN MUST NOT PERSIST A COPY-TARGET DEVICE-VIRTUAL active:true —
2026-09-08, the Living Room take that would not bring up tv-mapper.

WHAT HAPPENED. A per-fixture commission on the copy-mapped `tv-mapper`
carrier brings up the fixtures' own strips (`tv-backlight` and the two
kitchen sconces) for the capture and puts them back afterwards
(`activate_for_capture` / `deactivate_after_capture`). The LIVE restore is
correct and already proven (tests/test_capture_carrier_restore.py). The GAP
was on DISK: the transient activation persisted the substitutes
`active: true`, and a run interrupted in that window — a process kill, a
restart, a hard abort before the run's own deactivate — left that residue in
`fx-live/config.json`. On the next config load the substitutes activate and
evict the copy-mapped carrier, so the Living Room has zero active carriers
and the take rolls back to `released`.

THE FIX (fx/VENDOR.md #37): the transient activation is STORED INACTIVE —
`fx_seam.set_virtual_active(..., persist=False)` -> the facade's
`_virtual_put_active` raises the flag on the live virtual but writes an
EXPLICIT `active: false` to the stored config regardless. Explicit, not
skipped: the loader reads an ABSENT `active` key beside a stored effect as
"activate" (fx/virtuals.py create_from_config), and every device-virtual
the device layer creates omits the key — so a strip on its first-ever
capture, whose black lamp the effects POST persists, would still come up
and evict the carrier if the flag write were merely withheld. So even a
crash mid-capture leaves the substitutes stored `active: false`, whatever
their history, and the carrier survives the next load.

THE SAME DOOR EXISTS TWICE: a room effect (Dim Wave) brings an idle strip
up through `room_effects.production_deps().activate` exactly as the
capture does, and a wave interrupted mid-run is the identical residue.
Both doors are driven here.

THE BAR: this drives a REAL headless host with his copy-mapped shape and
reads the SAVED config.json — the durable state a cold load / take reads —
not just the live flags. It proves the persisted state is safe DURING the
capture window (the crash point), for a strip WITH and WITHOUT a
pre-existing `active` key, and that a cold load after both a full cycle
AND an interrupted one leaves tv-mapper ACTIVE and rendering. Each
persisted-state assertion goes RED against a control that reproduces the
defect through the same loader: the pre-fix persisting activation
(`_deps(persist_activation=True)`), and the effect-beside-no-key residue a
withheld flag write leaves behind (`_deps(lamp_only=True)`).
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

CARRIER = "tv-mapper"                       # copy-mapped, the room's carrier
DEVS = {"tv-backlight": 60,                 # fixture -> pixel count
        "sconce-kitchen-left": 30,
        "sconce-kitchen-right": 30}
SETTLE_S = 1.0


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
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


def _config_dir(tmp_path) -> str:
    return str(tmp_path / "fx")


def _write_config(config_dir: str, *, active_key: bool = True) -> None:
    """His shape: a copy-mapped carrier rendering across three fixtures, each
    fixture's own span virtual ASLEEP with NO stored effect (the clean
    original state, before any capture run touched it). `active_key=False`
    is the shape the device layer CREATES a device-virtual in — no `active`
    key at all — i.e. a strip that has never been through a capture; the
    loader reads that absence as "activate" once an effect is stored.

    ORDER MATTERS, and it mirrors his real config: the carrier is written
    BEFORE the device-virtuals, so a device-virtual stored active:true loads
    LATER and evicts the carrier — the exact eviction direction that strands
    tv-mapper. A test with the carrier last would let it win by load order
    and hide the residue entirely."""
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    virtuals = [{
        "id": CARRIER, "is_device": False, "auto_generated": False,
        "config": {"name": CARRIER, "mapping": "copy", "rows": 1},
        "segments": [[d, 0, pix - 1, False] for d, pix in DEVS.items()],
        "active": True,
        "effect": {"type": "singleColor",
                   "config": {"color": "#ff0000", "brightness": 1.0,
                              "background_brightness": 0.0}}}]
    for d, pix in DEVS.items():
        entry = {"id": d, "is_device": d, "auto_generated": False,
                 "config": {"name": d, "mapping": "span", "rows": 1},
                 "segments": [[d, 0, pix - 1, False]]}
        if active_key:
            entry["active"] = False
        virtuals.append(entry)
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": [{"id": d, "type": "dummy",
                                "config": {"name": d, "pixel_count": pix}}
                               for d, pix in DEVS.items()],
                   "virtuals": virtuals}, fh)


def _stored_active(config_dir: str) -> dict:
    with open(os.path.join(config_dir, "config.json")) as fh:
        cfg = json.load(fh)
    return {v["id"]: v.get("active") for v in cfg["virtuals"]}


@asynccontextmanager
async def _started(config_dir: str):
    """A real host with real render threads. Teardown is explicit: a virtual
    left rendering is a non-daemon thread that keeps the interpreter alive
    forever at exit (tests/test_capture_carrier_restore.py's own note)."""
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    try:
        yield host
    finally:
        facade.set_host(None)
        await host.shutdown()


def _renders(host, virtual_id: str) -> bool:
    virtual = host.virtuals.get(virtual_id)
    thread = getattr(virtual, "_thread", None)
    return bool(virtual and virtual.active
                and thread is not None and thread.is_alive())


def _plan():
    """The emitter shape a per-fixture commission produces: one emitter per
    fixture's own strip, all standing in for the copy-mapped carrier."""
    from spectra.services import emitters as em
    return em.Plan(
        emitters=[em.Emitter(emitter_id=d, carrier_id=CARRIER, label=d,
                             virtual_ids=[d]) for d in DEVS],
        granularity="whole", block_pixels=30)


async def _deps(persist_activation: bool = False, lamp_only: bool = False):
    """Production deps, optionally with one of two CONTROL activations that
    drive the harness red on the defect: the PRE-FIX activation
    (`persist_activation=True`, stores the transient flag), or the lamp
    POST alone (`lamp_only=True`) — which is exactly the on-disk residue a
    withheld flag write leaves on a strip with no `active` key: the black
    lamp persisted (the effects POST also activates the strip LIVE), and no
    key beside it."""
    from spectra.services import fx_seam, room_mapping
    deps = room_mapping.production_deps(session=None)
    if persist_activation or lamp_only:
        async def activate(vid: str) -> None:
            await fx_seam.set_virtual_effect(
                vid, room_mapping.MAP_EFFECT_TYPE,
                {"color": room_mapping.BLACK, "brightness": 0.0,
                 "background_brightness": 0.0})
            if persist_activation:
                await fx_seam.set_virtual_active(vid, True, persist=True)
        deps.activate = activate
    return deps


def test_a_transient_capture_activation_is_never_persisted_active(
        tmp_path, monkeypatch):
    """The direct proof of the fix: after `activate_for_capture`, the
    substitutes are LIVE-active but the SAVED config still stores them
    active:false — so a crash right here cannot strand the carrier."""
    _own(monkeypatch, tmp_path)
    from spectra.services import room_mapping
    config_dir = _config_dir(tmp_path)
    _write_config(config_dir)

    async def go():
        async with _started(config_dir) as host:
            deps = await _deps(persist_activation=False)
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            assert scope == [CARRIER]

            activation = await room_mapping.activate_for_capture(
                _plan(), scope, deps)
            assert sorted(activation.activated) == sorted(DEVS)
            assert activation.displaced == [CARRIER]

            # LIVE: the substitutes are up (the capture needs them lit).
            for d in DEVS:
                assert host.virtuals.get(d).active

            # PERSISTED: not one substitute is stored active:true — this is
            # the crash-window state, and it is safe. (RED pre-fix.)
            stored = _stored_active(config_dir)
            for d in DEVS:
                assert stored[d] is False, (
                    f"{d} persisted active={stored[d]!r} during the capture — "
                    f"a crash here would strand tv-mapper on the next load")
            assert stored[CARRIER] is True

            # put it back so teardown is clean
            await room_mapping.deactivate_after_capture(activation, deps)

    asyncio.run(go())


def _cold_reload_renders(config_dir: str) -> bool:
    """Load the SAVED config in a fresh host — the durable state a take reads
    — and report whether the carrier comes up and renders."""
    async def go():
        async with _started(config_dir) as host:
            await asyncio.sleep(0.3)                    # let threads spin up
            return _renders(host, CARRIER)
    return asyncio.run(go())


def test_a_take_after_a_full_commission_cycle_leaves_the_carrier_driving(
        tmp_path, monkeypatch):
    """A clean run + its own cleanup, then a cold load (the take): tv-mapper
    active and rendering, substitutes asleep."""
    _own(monkeypatch, tmp_path)
    from spectra.services import room_mapping
    config_dir = _config_dir(tmp_path)
    _write_config(config_dir)

    async def go():
        async with _started(config_dir) as host:
            deps = await _deps(persist_activation=False)
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            activation = await room_mapping.activate_for_capture(
                _plan(), scope, deps)
            restore = await room_mapping.deactivate_after_capture(
                activation, deps)
            assert restore.left_on == [] and restore.not_restored == []
            assert _renders(host, CARRIER)

    asyncio.run(go())

    stored = _stored_active(config_dir)
    assert stored[CARRIER] is True
    for d in DEVS:
        assert stored[d] is False
    assert _cold_reload_renders(config_dir), (
        "after a full commission cycle the take must bring up tv-mapper")


def test_a_take_after_an_interrupted_commission_leaves_the_carrier_driving(
        tmp_path, monkeypatch):
    """THE RECURRENCE CASE. The run brings up the substitutes and is then
    interrupted before `deactivate_after_capture` ever runs (the hard-abort /
    crash / restart window). With the fix the saved config still stores the
    substitutes active:false, so a cold load (the take) brings up tv-mapper.
    """
    _own(monkeypatch, tmp_path)
    from spectra.services import room_mapping
    config_dir = _config_dir(tmp_path)
    _write_config(config_dir)

    async def go():
        async with _started(config_dir) as host:
            deps = await _deps(persist_activation=False)
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            # activate, then simulate the crash: NO deactivate_after_capture.
            await room_mapping.activate_for_capture(_plan(), scope, deps)

    asyncio.run(go())

    stored = _stored_active(config_dir)
    for d in DEVS:
        assert stored[d] is False, (
            f"{d} persisted active={stored[d]!r} after an interrupted run")
    assert _cold_reload_renders(config_dir), (
        "an interrupted commission must not strand tv-mapper on the next take")


def test_the_pre_fix_persisting_activation_strands_the_carrier(tmp_path,
                                                               monkeypatch):
    """The RED control: with the PRE-FIX persisting activation, an interrupted
    run leaves the substitutes stored active:true and a cold load evicts
    tv-mapper — proving the harness above fails on the very defect it was
    written for, not by luck."""
    _own(monkeypatch, tmp_path)
    from spectra.services import room_mapping
    config_dir = _config_dir(tmp_path)
    _write_config(config_dir)

    async def go():
        async with _started(config_dir) as host:
            deps = await _deps(persist_activation=True)      # PRE-FIX path
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            await room_mapping.activate_for_capture(_plan(), scope, deps)

    asyncio.run(go())

    stored = _stored_active(config_dir)
    assert any(stored[d] is True for d in DEVS), (
        "pre-fix, the transient activation persisted active:true")
    assert not _cold_reload_renders(config_dir), (
        "pre-fix, the persisted residue evicts tv-mapper on the take")


def test_the_carrier_actually_shows_its_own_colour_after_the_take(tmp_path,
                                                                  monkeypatch):
    """Not just active — the light really reaches the fixture. After a cold
    load (the take), the carrier's own red is on tv-backlight's buffer."""
    _own(monkeypatch, tmp_path)
    from spectra.services import room_mapping
    config_dir = _config_dir(tmp_path)
    _write_config(config_dir)

    async def cycle():
        async with _started(config_dir) as host:
            deps = await _deps(persist_activation=False)
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            activation = await room_mapping.activate_for_capture(
                _plan(), scope, deps)
            await room_mapping.deactivate_after_capture(activation, deps)
    asyncio.run(cycle())

    async def take():
        async with _started(config_dir) as host:
            await asyncio.sleep(SETTLE_S)
            assert _renders(host, CARRIER)
            pixels = np.asarray(host.devices.get("tv-backlight").assemble_frame(),
                                dtype=float)
            assert pixels[:, 0].mean() > 200.0, (
                "the carrier's own red is not reaching the fixture after the take")
    asyncio.run(take())


@pytest.mark.parametrize("active_key", [True, False],
                         ids=["stored-active-false", "no-active-key"])
def test_a_strip_is_stored_inactive_during_the_capture_whatever_its_history(
        tmp_path, monkeypatch, active_key):
    """The crash-window state for BOTH shapes a substitute can start in —
    an explicit `active: false` (a strip that has been through a clean run)
    and NO key at all (a strip the device layer created and nothing has
    touched). After the transient activation the strip is LIVE-active and
    the saved config holds an EXPLICIT false; the run is then interrupted
    (no deactivate) and the take still brings tv-mapper up. The no-key half
    is RED with a withheld write instead of an explicit false — see the
    lamp-only control below."""
    _own(monkeypatch, tmp_path)
    from spectra.services import room_mapping
    config_dir = _config_dir(tmp_path)
    _write_config(config_dir, active_key=active_key)
    assert all((_stored_active(config_dir)[d] is False) is active_key
               for d in DEVS)

    async def go():
        async with _started(config_dir) as host:
            deps = await _deps()
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            activation = await room_mapping.activate_for_capture(
                _plan(), scope, deps)
            assert sorted(activation.activated) == sorted(DEVS)
            for d in DEVS:
                assert host.virtuals.get(d).active
            stored = _stored_active(config_dir)
            for d in DEVS:
                assert stored[d] is False, (
                    f"{d} stored active={stored[d]!r} during the capture "
                    f"(started {'with' if active_key else 'without'} a key)")
            assert stored[CARRIER] is True

    asyncio.run(go())                                # interrupted: no deactivate
    assert _cold_reload_renders(config_dir), (
        "an interrupted first capture on a strip with no stored `active` key "
        "must not strand tv-mapper on the next take")


def test_a_persisted_lamp_beside_no_active_key_strands_the_carrier(
        tmp_path, monkeypatch):
    """The RED control for the no-key half: the effects POST alone (the
    black lamp persisted, the strip activated live by `set_effect`, and NO
    `active` written) is the residue a merely-withheld flag write leaves on
    a first-ever capture. The loader reads the absent key as "activate", the
    strip evicts tv-mapper, and the take fails — proving the explicit false
    is load-bearing, not tidiness."""
    _own(monkeypatch, tmp_path)
    from spectra.services import room_mapping
    config_dir = _config_dir(tmp_path)
    _write_config(config_dir, active_key=False)

    async def go():
        async with _started(config_dir) as host:
            deps = await _deps(lamp_only=True)
            scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
            activation = await room_mapping.activate_for_capture(
                _plan(), scope, deps)
            assert sorted(activation.activated) == sorted(DEVS)
            for d in DEVS:
                assert host.virtuals.get(d).active

    asyncio.run(go())

    stored = _stored_active(config_dir)
    for d in DEVS:
        assert stored[d] is None, "the control must leave the key absent"
    assert not _cold_reload_renders(config_dir), (
        "a stored lamp beside no `active` key loads as active and evicts "
        "tv-mapper — the residue an explicit false exists to prevent")


@pytest.mark.parametrize("active_key", [True, False],
                         ids=["stored-active-false", "no-active-key"])
def test_a_room_effect_interrupted_mid_run_leaves_the_carrier_driving(
        tmp_path, monkeypatch, active_key):
    """THE OTHER DOOR. A Dim Wave brings an idle strip up through
    `room_effects.production_deps().activate` — the same lamp POST and flag
    raise the capture makes — and `stop()` is what puts it back. A wave
    interrupted mid-run (a crash, a restart) must leave the same safe
    stored state: the strip LIVE-active with an explicit `active: false` on
    disk, so the take after it still brings tv-mapper up."""
    _own(monkeypatch, tmp_path)
    from spectra.services import room_effects
    config_dir = _config_dir(tmp_path)
    _write_config(config_dir, active_key=active_key)

    async def go():
        async with _started(config_dir) as host:
            deps = room_effects.production_deps()
            for d in DEVS:
                await deps.activate(d)
                assert host.virtuals.get(d).active
            assert not _renders(host, CARRIER)      # evicted live, as measured
            stored = _stored_active(config_dir)
            for d in DEVS:
                assert stored[d] is False, (
                    f"{d} stored active={stored[d]!r} while the wave ran")
            assert stored[CARRIER] is True

    asyncio.run(go())                                # interrupted: no stop()
    assert _cold_reload_renders(config_dir), (
        "a room effect interrupted mid-run must not strand tv-mapper on the "
        "next take")


def test_the_facade_reports_the_live_and_the_stored_flag_separately(
        tmp_path, monkeypatch):
    """The wire truth of `persist=False`: the PUT answers `active: true`
    (live) beside `stored_active: false` (what the file now holds), and the
    file agrees; the default persist stores the live flag and says so."""
    _own(monkeypatch, tmp_path)
    from spectra.services import fx_seam, room_mapping
    config_dir = _config_dir(tmp_path)
    _write_config(config_dir, active_key=False)
    strip = next(iter(DEVS))

    async def go():
        async with _started(config_dir) as host:
            await fx_seam.set_virtual_effect(
                strip, room_mapping.MAP_EFFECT_TYPE,
                {"color": room_mapping.BLACK, "brightness": 0.0,
                 "background_brightness": 0.0})
            resp = await facade.handle(
                "PUT", f"/api/virtuals/{strip}",
                json={"active": True, "persist": False})
            body = resp.json()
            assert body["active"] is True
            assert body["stored_active"] is False
            assert host.virtuals.get(strip).active
            assert _stored_active(config_dir)[strip] is False

            resp = await facade.handle(
                "PUT", f"/api/virtuals/{strip}", json={"active": False})
            body = resp.json()
            assert body["active"] is False
            assert body["stored_active"] is False
            assert _stored_active(config_dir)[strip] is False

            resp = await facade.handle(
                "PUT", f"/api/virtuals/{strip}", json={"active": True})
            body = resp.json()
            assert body["active"] is True
            assert body["stored_active"] is True
            assert _stored_active(config_dir)[strip] is True
            await fx_seam.set_virtual_active(strip, False)

    asyncio.run(go())
