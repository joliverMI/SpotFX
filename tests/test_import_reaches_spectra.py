"""THE REGRESSION HIS 2026-08-25 IMPORT PROVED MISSING: an analyzed-trigger
IMPORT must reach the copy the room fires from, exactly like a Timeline save.

He imported analyzed triggers for two songs (121 and 117 of them) and none
of them ever fired: routers/ai_triggers_router.py's import handler wrote the
EDITOR copy (storage/profiles/*.json) and stopped there, while
routers/profiles.py's save path had been running the sync hook since
2026-08-24. Same seam, same proof shape as
tests/test_profile_save_reaches_spectra.py — a REAL loopback socket through
the real SPECTRA router, planner and store, never the planner called twice:

  routers.ai_triggers_router.generate_embedded
    -> services.spectra_trigger_sync_client.sync_profile   (real httpx call)
      -> POST /spectra/api/triggers/sync-from-profile      (real SPECTRA router)
        -> spectra.services.profile_trigger_sync           (real planner)
          -> storage/spectra/triggers.json                 (real store)
"""
from __future__ import annotations

import asyncio
import socket

import pytest
from fastapi import FastAPI

from spectra import config as scfg
from spectra.services import trigger_store

URI = "spotify:track:import-reaches-spectra"
FLARE = "fixed-shape-flare"          # LEDGER: response bucket -> fire_response


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


def _stub_generation(monkeypatch, suggestions: list[dict]):
    """Stand in for the KNN engine and the audio-shape metadata so the test
    exercises the SAVE+SYNC half of the handler, which is what regressed."""
    import services.embedded_trigger_service as ets
    import services.audio_analyzer as aa
    import services.profile_manager as pm

    monkeypatch.setattr(ets, "suggest_triggers",
                        lambda *a, **k: list(suggestions))
    monkeypatch.setattr(aa, "load_audio_shape_meta", lambda uri: None)
    monkeypatch.setattr(pm, "get_event_map", lambda: {FLARE: object()})


def _request():
    from routers.ai_triggers_router import EmbeddedGenerateRequest
    return EmbeddedGenerateRequest(target_uri=URI, training_uris=["spotify:track:train"])


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_an_import_lands_its_triggers_in_the_copy_spectra_fires_from(monkeypatch):
    from config import settings
    import routers.ai_triggers_router as ai

    _stub_generation(monkeypatch, [
        {"timestamp_ms": 1000, "event_id": FLARE},
        {"timestamp_ms": 2000, "event_id": FLARE},
        {"timestamp_ms": 3000, "event_id": FLARE},
    ])

    async def scenario():
        port = free_port()
        server, task = await _serve(_spectra_app(), port)
        monkeypatch.setattr(settings, "spectra_port", port)
        try:
            assert trigger_store.list_for_song(URI) == []
            result = await ai.generate_embedded(_request())
            assert result["applied"] == 3
            assert result["spectra_sync"]["status"] == "ok", result
            assert result["spectra_sync"]["written"] == 3
            fired = trigger_store.list_for_song(URI)
            assert len(fired) == 3
            assert sorted(t.timestamp_ms for t in fired) == [1000, 2000, 3000]
            assert {t.source for t in fired} == {"authored"}
        finally:
            server.should_exit = True
            await task

    _run(scenario())


def test_a_reimport_replaces_the_fired_copy_rather_than_stacking(monkeypatch):
    """An import REPLACES the song's trigger list, so the fired copy must end
    up holding the new list, not the old one plus the new one."""
    from config import settings
    import routers.ai_triggers_router as ai

    async def scenario():
        port = free_port()
        server, task = await _serve(_spectra_app(), port)
        monkeypatch.setattr(settings, "spectra_port", port)
        try:
            _stub_generation(monkeypatch, [
                {"timestamp_ms": 1000, "event_id": FLARE},
                {"timestamp_ms": 2000, "event_id": FLARE},
            ])
            await ai.generate_embedded(_request())
            assert len(trigger_store.list_for_song(URI)) == 2

            _stub_generation(monkeypatch, [{"timestamp_ms": 5000, "event_id": FLARE}])
            result = await ai.generate_embedded(_request())
            assert result["spectra_sync"]["deleted"] == 2
            fired = trigger_store.list_for_song(URI)
            assert [t.timestamp_ms for t in fired] == [5000]
        finally:
            server.should_exit = True
            await task

    _run(scenario())


def test_an_import_reports_a_failed_sync_rather_than_claiming_success(monkeypatch):
    """Failure honesty, the same contract routers/profiles.py established: the
    profile is already on disk so the import does not fail, but the response
    NAMES the unreached sync instead of reading as a clean success."""
    from config import settings
    import routers.ai_triggers_router as ai
    from services.profile_manager import load_profile_by_uri

    _stub_generation(monkeypatch, [{"timestamp_ms": 1000, "event_id": FLARE}])
    monkeypatch.setattr(settings, "spectra_port", free_port())   # nothing listening

    async def scenario():
        result = await ai.generate_embedded(_request())
        assert result["applied"] == 1
        assert result["spectra_sync"]["status"] == "unreachable"
        assert load_profile_by_uri(URI) is not None      # the import is safe on disk

    _run(scenario())
