"""THE ROUND TRIP HE ASKED FOR, offline: import a song's triggers, edit some,
and watch the store SPECTRA fires from serve the edited rows — with nobody
having run anything by hand in between.

His question (2026-08-25), which this file exists to answer with a proof
rather than a claim: "so if i import triggers for a new song and edit them,
do we need to manually sync them or do they automatically work in spectra?"

Everything below the test harness is production: the real spot-effects
routes over ASGI, the real HTTP sync client over a real loopback socket, the
real SPECTRA router, the real planner, the real store, and the real
GET /api/triggers the engine itself reads from. The only stand-in is the KNN
suggestion engine, because what regressed was the WRITE half, not the
analysis.
"""
from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
from fastapi import FastAPI

from spectra import config as scfg

URI = "spotify:track:round-trip"
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
    from services import profile_trigger_sync_queue as q
    q.pending().clear()
    q._dirty.clear()


def _spectra_app() -> FastAPI:
    from spectra.api import triggers
    app = FastAPI()
    app.include_router(triggers.router, prefix="/spectra")
    return app


def _spotfx_app() -> FastAPI:
    """The real spot-effects routes his timeline and import dialog call."""
    import routers.ai_triggers_router as ai
    import routers.profiles as profiles
    app = FastAPI()
    app.include_router(profiles.router)
    app.include_router(ai.router)
    return app


async def _serve(app, port: int):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return server, task


def _stub_engine(monkeypatch, suggestions):
    import services.audio_analyzer as aa
    import services.embedded_trigger_service as ets
    import services.profile_manager as pm
    monkeypatch.setattr(ets, "suggest_triggers", lambda *a, **k: list(suggestions))
    monkeypatch.setattr(aa, "load_audio_shape_meta", lambda uri: None)
    monkeypatch.setattr(pm, "get_event_map", lambda: {FLARE: object()})


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_import_then_edit_reaches_the_store_spectra_fires_from(monkeypatch):
    from config import settings

    _stub_engine(monkeypatch, [
        {"timestamp_ms": 10_000, "event_id": FLARE, "intensity": 0.3},
        {"timestamp_ms": 20_000, "event_id": FLARE, "intensity": 0.5},
        {"timestamp_ms": 30_000, "event_id": FLARE, "intensity": 0.7},
    ])

    async def scenario():
        port = free_port()
        server, task = await _serve(_spectra_app(), port)
        monkeypatch.setattr(settings, "spectra_port", port)
        transport = httpx.ASGITransport(app=_spotfx_app())
        try:
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://spotfx") as app:
                # ── 1. HE IMPORTS ────────────────────────────────────────────
                r = await app.post("/api/ai-triggers/generate-embedded", json={
                    "target_uri": URI, "training_uris": ["spotify:track:train"]})
                r.raise_for_status()
                assert r.json()["spectra_sync"]["status"] == "ok"

                # The fired store is serving them already — no manual step.
                async with httpx.AsyncClient() as spectra:
                    fired = (await spectra.get(
                        f"http://127.0.0.1:{port}/spectra/api/triggers",
                        params={"uri": URI})).json()
                assert sorted(t["timestamp_ms"] for t in fired) == [10_000, 20_000, 30_000]

                # ── 2. HE EDITS ──────────────────────────────────────────────
                profile = (await app.get("/api/profiles/by-uri",
                                         params={"uri": URI})).json()
                assert len(profile["triggers"]) == 3
                moved_id = profile["triggers"][1]["id"]
                profile["triggers"][1]["timestamp_ms"] = 25_500
                profile["triggers"][1]["intensity"] = 0.95
                profile["triggers"][2]["enabled"] = False
                r = await app.post("/api/profiles", json=profile)
                r.raise_for_status()
                assert r.json()["spectra_sync"]["status"] == "ok"

                # ── 3. THE SHOW IS SERVING HIS EDITS ─────────────────────────
                async with httpx.AsyncClient() as spectra:
                    fired = (await spectra.get(
                        f"http://127.0.0.1:{port}/spectra/api/triggers",
                        params={"uri": URI})).json()
                by_id = {t["id"]: t for t in fired}
                assert by_id[moved_id]["timestamp_ms"] == 25_500
                assert by_id[moved_id]["action"]["intensity"] == pytest.approx(0.95)
                assert [t for t in fired if not t["enabled"]], "disable never crossed"

                # ── 4. AND A RE-IMPORT LEAVES HIS EDITS ALONE ────────────────
                r = await app.post("/api/ai-triggers/generate-embedded", json={
                    "target_uri": URI, "training_uris": ["spotify:track:train"]})
                r.raise_for_status()
                body = r.json()
                assert body["import_policy"] == "protect"
                assert body["spectra_sync"]["deleted"] == 0
                async with httpx.AsyncClient() as spectra:
                    fired = (await spectra.get(
                        f"http://127.0.0.1:{port}/spectra/api/triggers",
                        params={"uri": URI})).json()
                by_id = {t["id"]: t for t in fired}
                assert by_id[moved_id]["timestamp_ms"] == 25_500, "re-import clobbered his edit"
                assert by_id[moved_id]["action"]["intensity"] == pytest.approx(0.95)
        finally:
            server.should_exit = True
            await task

    _run(scenario())


def test_a_writer_nobody_hooked_still_reaches_his_show(monkeypatch):
    """SYNC AS A PROPERTY OF WRITING: the structural half.

    This test deliberately calls profile_manager.save_profile DIRECTLY — the
    shape of every un-hooked writer past and future, including the ones this
    build did not touch. Nothing calls the sync client; the write's own mark
    plus the supervised drain land it anyway.
    """
    from config import settings
    from models.song_profile import MusicTrigger, SongProfile
    from services import profile_trigger_sync_queue as queue
    from services.profile_manager import save_profile

    async def scenario():
        port = free_port()
        server, task = await _serve(_spectra_app(), port)
        monkeypatch.setattr(settings, "spectra_port", port)
        try:
            save_profile(SongProfile(
                spotify_uri=URI, title="t", artist="a", duration_ms=100_000,
                triggers=[MusicTrigger(id="unhooked-1", timestamp_ms=4000,
                                       event_id=FLARE)]))
            assert URI in queue.pending(), "the write did not mark the song"

            outcome = await queue.drain_once()
            assert outcome["synced"] == [URI]
            assert queue.pending() == set(), "a landed song stayed marked"

            async with httpx.AsyncClient() as spectra:
                fired = (await spectra.get(
                    f"http://127.0.0.1:{port}/spectra/api/triggers",
                    params={"uri": URI})).json()
            assert [t["id"] for t in fired] == ["unhooked-1"]
        finally:
            server.should_exit = True
            await task

    _run(scenario())


def test_the_drain_never_deletes_and_retries_a_song_spectra_missed(monkeypatch):
    """The drain is upsert-only, and a SPECTRA outage costs a retry — never
    his edit, and never a deletion."""
    from config import settings
    from models.song_profile import MusicTrigger, SongProfile
    from services import profile_trigger_sync_queue as queue
    from services.profile_manager import save_profile

    async def scenario():
        # 1. SPECTRA is down: the song stays marked for a later attempt.
        monkeypatch.setattr(settings, "spectra_port", free_port())
        save_profile(SongProfile(
            spotify_uri=URI, title="t", artist="a", duration_ms=100_000,
            triggers=[MusicTrigger(id="r-1", timestamp_ms=1000, event_id=FLARE),
                      MusicTrigger(id="r-2", timestamp_ms=2000, event_id=FLARE)]))
        outcome = await queue.drain_once()
        assert outcome["failed"] == [URI]
        assert URI in queue.pending(), "a missed sync must be retried, not dropped"

        # 2. SPECTRA comes back: the retry lands, unprompted.
        port = free_port()
        server, task = await _serve(_spectra_app(), port)
        monkeypatch.setattr(settings, "spectra_port", port)
        try:
            assert (await queue.drain_once())["synced"] == [URI]

            # 3. A later write carrying FEWER triggers deletes nothing.
            save_profile(SongProfile(
                spotify_uri=URI, title="t", artist="a", duration_ms=100_000,
                triggers=[MusicTrigger(id="r-1", timestamp_ms=1000,
                                       event_id=FLARE)]))
            await queue.drain_once()
            async with httpx.AsyncClient() as spectra:
                fired = (await spectra.get(
                    f"http://127.0.0.1:{port}/spectra/api/triggers",
                    params={"uri": URI})).json()
            assert {t["id"] for t in fired} == {"r-1", "r-2"}
        finally:
            server.should_exit = True
            await task

    _run(scenario())
