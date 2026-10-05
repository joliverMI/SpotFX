"""A SCENE FIRE STAYS INSIDE A SCOPED TAKE (D4, 2026-10-04 live proof).

THE INCIDENT: the Light Show room proof took the Living Room only (a take
scoped to the TV backlight). A live `POST /scenes/{id}/fire` wrote every
virtual the scene targets; for the held-back ones (the house `hues`
virtual spanning both Hue entertainment areas) fx/facade.py's
activate-on-write repair (`_verify_effect_took`, deviation #29) ACTIVATED
them. Both Hue areas streamed the show for ~4 minutes and the release fade
then switched 25 house lights on and off. No one had handed those lights
over.

MEASURED ON THE REAL PIPELINE: a real FxHost (dummy devices) started with
`only_active`, the real `fx_seam.apply_writes` and the real facade. The
house device must never be activated (`Device.ever_activated`, the same
sticky flag the release fade reads) and the held-back virtual must stay
inactive, while the in-scope write still lands.

RED CONTROL: `test_red_control_the_unguarded_facade_activates_the_house`
removes the scope gate (`FxHost.virtual_in_scope` -> always True) and the
same scene fire activates the house — the shipped behaviour.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

import pytest

from fx import device_model, facade, headless
from fx.host import FxHost

TV, HOUSE = "tv-backlight", "house-hues"
CARRIER, HUES = "tv-mapper", "hues"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    original = device_model.CATEGORIES_FILE
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    from fx import light_ownership as lo
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", path)
    yield
    # The registry is a module-level CACHE: restore the path AND reload, or
    # every later test sees this one's empty category set.
    device_model.CATEGORIES_FILE = original
    device_model.refresh()


def _effect(color):
    return {"type": "singleColor",
            "config": {"color": color, "brightness": 1.0,
                       "background_brightness": 0.0}}


def _write_config(config_dir: str) -> None:
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({
            "configuration_version": CONFIGURATION_VERSION,
            "devices": [
                {"id": TV, "type": "dummy",
                 "config": {"name": TV, "pixel_count": 30}},
                {"id": HOUSE, "type": "dummy",
                 "config": {"name": HOUSE, "pixel_count": 17}}],
            "virtuals": [
                {"id": CARRIER, "is_device": False, "auto_generated": False,
                 "config": {"name": CARRIER, "mapping": "span", "rows": 1},
                 "segments": [[TV, 0, 29, False]], "active": True,
                 "effect": _effect("#ff0000")},
                {"id": HUES, "is_device": False, "auto_generated": False,
                 "config": {"name": HUES, "mapping": "span", "rows": 1},
                 "segments": [[HOUSE, 0, 16, False]], "active": True,
                 "effect": _effect("#00ff00")},
            ],
        }, fh)


@asynccontextmanager
async def _scoped(tmp_path, scope):
    headless.silence_audio()
    _write_config(str(tmp_path / "fx"))
    host = FxHost(str(tmp_path / "fx"))
    await host.start(only_active=scope)
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    try:
        yield host
    finally:
        facade.set_host(None)
        await host.shutdown()


def _scene_writes():
    return [{"virtual_id": CARRIER, "effect_type": "singleColor",
             "config": {"color": "#0000ff", "brightness": 1.0}},
            {"virtual_id": HUES, "effect_type": "singleColor",
             "config": {"color": "#0000ff", "brightness": 1.0}}]


def _house_touched(host) -> bool:
    return bool(getattr(host.devices.get(HOUSE), "ever_activated", False)
                or host.virtuals.get(HUES).active)


def test_a_scene_fire_never_activates_a_virtual_outside_the_take(tmp_path):
    from spectra.services import fx_seam

    async def go():
        async with _scoped(tmp_path, {CARRIER}) as host:
            assert not _house_touched(host), "the take itself held hues back"
            await fx_seam.apply_writes(_scene_writes())
            assert not _house_touched(host), (
                "a scene fire activated the house Hue virtual — the take "
                "was scoped to the TV backlight")
            cfg = host.virtuals.get(CARRIER).active_effect.config
            assert str(cfg["color"]).lower().startswith("#0000ff"), (
                "the in-scope write must still land")
            assert fx_seam.stats()["out_of_scope_skipped"] >= 1
    asyncio.run(go())


def test_red_control_the_unguarded_facade_activates_the_house(
        tmp_path, monkeypatch):
    """The shipped behaviour, reproduced: with the scope gate removed, the
    same scene fire repairs the held-back virtual into life."""
    from spectra.services import fx_seam
    monkeypatch.setattr(FxHost, "virtual_in_scope", lambda self, vid: True)

    async def go():
        async with _scoped(tmp_path, {CARRIER}) as host:
            await fx_seam.apply_writes(_scene_writes())
            assert _house_touched(host)
    asyncio.run(go())


def test_the_facade_refuses_an_out_of_scope_write_or_activation(tmp_path):
    async def go():
        async with _scoped(tmp_path, {CARRIER}) as host:
            put = await facade.handle(
                "PUT", f"/api/virtuals/{HUES}/effects",
                json={"type": "singleColor", "config": {"color": "#fff"}})
            assert put.status_code == 403
            act = await facade.handle("PUT", f"/api/virtuals/{HUES}",
                                      json={"active": True})
            assert act.status_code == 403
            assert not _house_touched(host)
            # deactivating and reading stay allowed
            off = await facade.handle("PUT", f"/api/virtuals/{HUES}",
                                      json={"active": False})
            assert off.status_code == 200
            get = await facade.handle("GET", f"/api/virtuals/{HUES}")
            assert get.status_code == 200
    asyncio.run(go())


def test_the_engine_executor_skips_an_out_of_scope_glide(tmp_path):
    from spectra.services.fx_executor import FacadeExecutor

    async def go():
        async with _scoped(tmp_path, {CARRIER}) as host:
            ex = FacadeExecutor()
            await ex.glide(HUES, "singleColor", {"brightness": 0.5}, 200)
            await ex.jump(HUES, "singleColor", {"brightness": 0.5})
            assert not _house_touched(host)
    asyncio.run(go())


def test_a_whole_room_take_is_unrestricted(tmp_path):
    from spectra.services import fx_seam

    async def go():
        async with _scoped(tmp_path, None) as host:
            assert host.virtual_in_scope(HUES)
            await fx_seam.apply_writes(_scene_writes())
            assert host.virtuals.get(HUES).active
    asyncio.run(go())


def test_light_show_targets_list_only_the_takes_fixtures(tmp_path,
                                                         monkeypatch):
    from spectra.services import show_output
    from spectra.services.live_host import live

    async def go():
        async with _scoped(tmp_path, {CARRIER}) as host:
            monkeypatch.setattr(live, "host", host)
            monkeypatch.setattr(live, "scope", {CARRIER})
            ids = [f["id"] for f in show_output.list_targets()["fixtures"]]
            assert ids == [TV]
            assert show_output.resolve_target({"kind": "everything"})[0] == [TV]
            devs, problems = show_output.resolve_target(
                {"kind": "fixture", "id": HOUSE})
            assert devs == [] and problems
            assert live.scope_device_ids() == {TV}
    asyncio.run(go())
