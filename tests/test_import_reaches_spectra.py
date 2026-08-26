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


def test_a_reimport_updates_in_place_and_deletes_nothing(monkeypatch):
    """OPTION C, the whole point of stable ids: re-importing a song UPDATES it.

    Before this, every imported MusicTrigger carried a fresh uuid4, so a
    re-import made 100% of the song's previously-synced rows read as
    absent-from-the-profile — the sync deleted the lot and re-inserted them
    under new ids. The row count came out right, which is why it went
    unnoticed. Now the same analyzed mark computed twice is the SAME trigger
    twice, and an automatic writer may never delete regardless.
    """
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
            first = {t.id for t in trigger_store.list_for_song(URI)}
            assert len(first) == 2

            # The identical analysis again: nothing added, nothing deleted,
            # and the SAME ids — the churn this feature exists to stop.
            result = await ai.generate_embedded(_request())
            assert result["spectra_sync"]["deleted"] == 0
            assert result["spectra_sync"]["written"] == 0      # already agree
            assert result["spectra_sync"]["unchanged"] == 2
            assert {t.id for t in trigger_store.list_for_song(URI)} == first

            # A NEW mark is added; the two existing ones are untouched.
            _stub_generation(monkeypatch, [
                {"timestamp_ms": 1000, "event_id": FLARE},
                {"timestamp_ms": 2000, "event_id": FLARE},
                {"timestamp_ms": 5000, "event_id": FLARE},
            ])
            result = await ai.generate_embedded(_request())
            assert result["spectra_sync"]["deleted"] == 0
            fired = trigger_store.list_for_song(URI)
            assert sorted(t.timestamp_ms for t in fired) == [1000, 2000, 5000]
            assert first <= {t.id for t in fired}
        finally:
            server.should_exit = True
            await task

    _run(scenario())


def test_an_automatic_import_can_never_delete_a_fired_row(monkeypatch):
    """THE GATE THAT HELD THIS BUILD: an unattended writer must not destroy.

    Even when the incoming analysis no longer produces a mark at all — the
    exact shape that used to trigger the planner's decision-3 delete — an
    import leaves the fired row standing and REPORTS having done so. His
    deliberate deletions still land, through an explicit Timeline save.
    """
    from config import settings
    import routers.ai_triggers_router as ai
    import routers.profiles as profiles_router
    from models.song_profile import MusicTrigger, SongProfile
    from services.trigger_identity import stable_trigger_id

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

            # An import whose analysis produces ONLY the first mark. Under the
            # old whole-song semantics the 2000ms row would be deleted.
            monkeypatch.setattr(settings, "trigger_import_policy", "replace")
            _stub_generation(monkeypatch, [{"timestamp_ms": 1000, "event_id": FLARE}])
            result = await ai.generate_embedded(_request())
            assert result["merge"]["dropped"] == 1          # gone from the PROFILE
            assert result["spectra_sync"]["deleted"] == 0   # but NOT from the show
            assert result["spectra_sync"]["retained_upsert_only"] == 1
            assert len(trigger_store.list_for_song(URI)) == 2

            # ...and his own deliberate deletion, through an explicit save,
            # still lands. Provenance survived the retention, which is what
            # makes this possible.
            kept_id = stable_trigger_id(FLARE, 1000)
            saved = await profiles_router.upsert_profile(SongProfile(
                spotify_uri=URI, title="t", artist="a", duration_ms=200_000,
                triggers=[MusicTrigger(id=kept_id, timestamp_ms=1000,
                                       event_id=FLARE)]))
            assert saved["spectra_sync"]["deleted"] == 1
            assert [t.id for t in trigger_store.list_for_song(URI)] == [kept_id]
        finally:
            server.should_exit = True
            await task

    _run(scenario())


def test_the_import_policy_switches_both_behaviours_without_a_rewrite(monkeypatch):
    """The one open trade is HIS, so both behaviours are live and switchable.

    Default "protect": a mark he has hand-edited since the last import keeps
    his edit. "replace": the fresh analysis wins. Same code either way.
    """
    from config import settings
    import routers.ai_triggers_router as ai
    from services import trigger_identity
    from services.profile_manager import load_profile_by_uri

    monkeypatch.setattr(settings, "spectra_port", free_port())   # sync half not under test
    suggestions = [{"timestamp_ms": 1000, "event_id": FLARE, "intensity": 0.4}]

    async def scenario():
        _stub_generation(monkeypatch, suggestions)
        await ai.generate_embedded(_request())

        # He retunes that mark on the timeline (same id, new intensity).
        profile = load_profile_by_uri(URI)
        assert len(profile.triggers) == 1
        profile.triggers[0].intensity = 0.95
        from services.profile_manager import save_profile
        save_profile(profile)

        # PROTECT (the shipped default): his 0.95 survives the re-import.
        monkeypatch.setattr(settings, "trigger_import_policy", "protect")
        result = await ai.generate_embedded(_request())
        assert result["import_policy"] == "protect"
        assert result["merge"] == {"added": 0, "kept": 1, "overwritten": 0, "dropped": 0}
        assert load_profile_by_uri(URI).triggers[0].intensity == pytest.approx(0.95)

        # REPLACE: the analysis wins, same code path, one setting.
        monkeypatch.setattr(settings, "trigger_import_policy", "replace")
        result = await ai.generate_embedded(_request())
        assert result["import_policy"] == "replace"
        assert result["merge"]["overwritten"] == 1
        assert load_profile_by_uri(URI).triggers[0].intensity == pytest.approx(0.4)

        # A mistyped policy falls back to the protective one rather than
        # silently overwriting his work.
        monkeypatch.setattr(settings, "trigger_import_policy", "REPLCAE")
        assert trigger_identity.import_policy() == "protect"

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
