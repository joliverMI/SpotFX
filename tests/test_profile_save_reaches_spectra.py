"""THE REGRESSION THAT MATTERS: pressing Save on his Timeline reaches the
copy the room fires from.

The two halves live in two processes on purpose (the S3 split — the
spot-effects interpreter may not import anything under spectra/), so this
proves the seam over a REAL loopback socket rather than by calling the
planner twice:

  routers.profiles.upsert_profile   (spot-effects side, the real handler the
                                     Timeline's POST /api/profiles hits)
    -> services.spectra_trigger_sync_client.sync_song   (real httpx call)
      -> POST /spectra/api/triggers/sync-from-profile   (real SPECTRA router)
        -> spectra.services.profile_trigger_sync        (real planner)
          -> storage/spectra/triggers.json              (real store)

Only the SPECTRA app's own lifespan is left out (frame watchdog, bridge,
ownership resume) — the router, the handler, the encoder and the socket are
all the production ones.
"""
from __future__ import annotations

import asyncio
import socket

import pytest
from fastapi import FastAPI

from spectra import config as scfg
from spectra.services import profile_sync_ledger, trigger_store

URI = "spotify:track:save-reaches-spectra"
FLARE = "fixed-shape-flare"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "PROFILE_SYNC_LEDGER_FILE",
                        tmp_path / "profile_sync_ledger.json")
    import config as root_config
    import services.profile_manager as pm
    monkeypatch.setattr(root_config, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(pm, "PROFILES_DIR", tmp_path / "profiles")


def _spectra_app() -> FastAPI:
    """The real SPECTRA trigger router at its real mount point."""
    from spectra.api import triggers
    app = FastAPI()
    app.include_router(triggers.router, prefix="/spectra")
    return app


async def _serve(app, port: int):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return server, task


def _profile(triggers: list[dict]):
    from models.song_profile import MusicTrigger, SongProfile
    return SongProfile(spotify_uri=URI, title="Save Test", artist="Fixture",
                       duration_ms=200_000,
                       triggers=[MusicTrigger(**t) for t in triggers])


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_profile_save_lands_his_edits_in_the_copy_spectra_fires_from(monkeypatch):
    from config import settings
    import routers.profiles as profiles_router

    async def scenario():
        port = free_port()
        server, task = await _serve(_spectra_app(), port)
        monkeypatch.setattr(settings, "spectra_port", port)
        try:
            # 1. first save — two hand-placed triggers
            saved = await profiles_router.upsert_profile(_profile([
                {"id": "t1", "timestamp_ms": 1000, "event_id": FLARE, "intensity": 0.4},
                {"id": "t2", "timestamp_ms": 2000, "event_id": FLARE, "intensity": 0.6},
            ]))
            assert saved["spectra_sync"]["status"] == "ok", saved
            assert saved["spectra_sync"]["written"] == 2
            fired = {t.id: t for t in trigger_store.list_for_song(URI)}
            assert set(fired) == {"t1", "t2"}
            assert fired["t2"].action.intensity == pytest.approx(0.6)

            # 2. he edits t2 and saves again — the fired copy follows
            saved = await profiles_router.upsert_profile(_profile([
                {"id": "t1", "timestamp_ms": 1000, "event_id": FLARE, "intensity": 0.4},
                {"id": "t2", "timestamp_ms": 9500, "event_id": FLARE, "intensity": 0.95},
            ]))
            assert saved["spectra_sync"]["written"] == 1        # only the edited one
            assert saved["spectra_sync"]["unchanged"] == 1
            fired = {t.id: t for t in trigger_store.list_for_song(URI)}
            assert fired["t2"].timestamp_ms == 9500
            assert fired["t2"].action.intensity == pytest.approx(0.95)

            # 3. a trigger born on SPECTRA's own card survives his next save
            from spectra.models.trigger import SpectraTrigger
            trigger_store.upsert(URI, SpectraTrigger(
                id="card-1", timestamp_ms=7000,
                action={"kind": "fire_response", "event_class": "drop"}))
            saved = await profiles_router.upsert_profile(_profile([
                {"id": "t1", "timestamp_ms": 1000, "event_id": FLARE, "intensity": 0.4},
            ]))
            # t2 deleted in the editor -> gone; card-1 untouched
            assert saved["spectra_sync"]["deleted"] == 1
            assert saved["spectra_sync"]["protected_spectra_authored"] == 1
            assert {t.id for t in trigger_store.list_for_song(URI)} == {"t1", "card-1"}
            assert "card-1" not in profile_sync_ledger.for_song(
                profile_sync_ledger.load(), URI)
        finally:
            server.should_exit = True
            await task

    _run(scenario())


def test_a_save_still_succeeds_when_spectra_is_down(monkeypatch):
    """His profile is already on disk by the time the sync runs — a SPECTRA
    outage must report itself, never fail or delay his save."""
    from config import settings
    import routers.profiles as profiles_router
    from services.profile_manager import load_profile_by_uri

    monkeypatch.setattr(settings, "spectra_port", free_port())   # nothing listening

    async def scenario():
        saved = await profiles_router.upsert_profile(_profile([
            {"id": "t1", "timestamp_ms": 1000, "event_id": FLARE}]))
        assert saved["status"] == "saved"
        assert saved["spectra_sync"]["status"] == "unreachable"
        assert load_profile_by_uri(URI) is not None      # the edit is safe on disk

    _run(scenario())
