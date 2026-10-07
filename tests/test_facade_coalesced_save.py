"""An effect write's config save is COALESCED, not inline (fx/facade.py,
fx/VENDOR.md deviation #56).

Why it exists: the preview stream shares SPECTRA's event loop with the
facade, and saving his ~1 MB fx config on every effect write held that loop
for the whole of a flare's write burst — the preview froze and jumped past
every flare and transition. scripts/check_preview_flare_skip.py measures the
preview itself (tests/test_preview_flare_skip.py runs it); this file pins the
persistence contract the fix rests on: one save per burst, landing after the
quiet period or the max wait, storing the LAST write, superseded by any
inline save, flushed when the host goes away, and inline when no loop runs.

Offline and hermetic: a tmp_path dummy host, no live storage.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless  # noqa: E402
from fx.host import FxHost  # noqa: E402

VID = headless.DEFAULT_VIRTUAL_ID


@pytest.fixture(autouse=True)
def _short_windows(monkeypatch):
    monkeypatch.setattr(facade, "PERSIST_QUIET_S", 0.15)
    monkeypatch.setattr(facade, "PERSIST_MAX_WAIT_S", 0.5)
    yield
    facade._pending_saves.clear()
    facade.set_host(None)


@pytest.fixture
def saves(monkeypatch):
    """Every save the facade makes, counted (the real save still runs)."""
    calls: list[float] = []
    real = facade.save_config

    def counting(**kwargs):
        calls.append(time.monotonic())
        return real(**kwargs)
    monkeypatch.setattr(facade, "save_config", counting)
    return calls


async def _host(tmp_path) -> FxHost:
    config_dir = str(tmp_path / "fx")
    headless.write_headless_config(
        config_dir, initial_effect={"type": "singleColor",
                                    "config": {"color": "#000080"}})
    headless.silence_audio()
    host = FxHost(config_dir)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    facade.set_host(host)
    return host


def _stored_color(host: FxHost) -> str:
    with open(Path(host.config_dir) / "config.json") as f:
        stored = json.load(f)
    virtual = next(v for v in stored["virtuals"] if v["id"] == VID)
    return virtual["effect"]["config"]["color"]


async def _put(color: str) -> None:
    resp = await facade.handle("PUT", f"/api/virtuals/{VID}/effects",
                               json={"type": "singleColor", "config": {"color": color}})
    resp.raise_for_status()


def test_a_burst_of_effect_writes_is_saved_once_after_the_quiet_period(tmp_path, saves):
    async def main():
        host = await _host(tmp_path)
        try:
            before = _stored_color(host)
            for i in range(10):
                await _put(f"#0000{i:02x}")
            assert saves == [], "an effect write saved inline — the burst blocks the loop again"
            assert facade.save_pending(host)
            assert _stored_color(host) == before
            await asyncio.sleep(facade.PERSIST_QUIET_S + 0.15)
            assert len(saves) == 1
            assert not facade.save_pending(host)
            assert _stored_color(host) == "#000009", "the save did not store the LAST write"
        finally:
            await host.shutdown()

    asyncio.run(main())


def test_writes_that_never_pause_still_save_by_the_max_wait(tmp_path, saves):
    async def main():
        host = await _host(tmp_path)
        try:
            start = time.monotonic()
            while time.monotonic() - start < facade.PERSIST_MAX_WAIT_S + 0.3:
                await _put("#00ff00")
                await asyncio.sleep(facade.PERSIST_QUIET_S / 3)
            assert saves, "continuous writes postponed the save forever"
            assert saves[0] - start <= facade.PERSIST_MAX_WAIT_S + 0.1
        finally:
            await host.shutdown()

    asyncio.run(main())


def test_an_inline_save_from_another_route_covers_and_cancels_the_pending_one(tmp_path, saves):
    async def main():
        host = await _host(tmp_path)
        try:
            await _put("#abcdef")
            assert facade.save_pending(host)
            # Every other route saves at once, as the fork does — and that
            # save writes the whole live config, the effect included.
            resp = await facade.handle("PUT", f"/api/virtuals/{VID}",
                                       json={"active": True})
            resp.raise_for_status()
            assert len(saves) == 1
            assert not facade.save_pending(host)
            assert _stored_color(host) == "#abcdef"
            await asyncio.sleep(facade.PERSIST_QUIET_S + 0.15)
            assert len(saves) == 1, "the superseded pending save still ran"
        finally:
            await host.shutdown()

    asyncio.run(main())


def test_shutting_the_host_down_lands_a_pending_save(tmp_path, saves):
    async def main():
        host = await _host(tmp_path)
        stopped = False
        try:
            await _put("#123456")
            assert facade.save_pending(host)
            facade.set_host(None)    # replacing the host flushes it...
            assert not facade.save_pending(host)
            assert _stored_color(host) == "#123456"
            facade.set_host(host)
            await _put("#654321")
            assert facade.save_pending(host)
            stopped = True
            await host.shutdown()    # ...and so does stopping it
            assert not facade.save_pending(host)
            assert _stored_color(host) == "#654321"
        finally:
            if not stopped:
                # an un-stopped host's render thread is non-daemon and would
                # hold the test process open at exit
                await host.shutdown()

    asyncio.run(main())


def test_with_no_running_loop_the_save_is_inline(tmp_path, saves):
    async def main():
        host = await _host(tmp_path)
        try:
            await asyncio.to_thread(facade._persist_soon, host)
            assert len(saves) == 1
            assert not facade.save_pending(host)
        finally:
            await host.shutdown()

    asyncio.run(main())


def test_a_zero_quiet_period_is_the_forks_save_on_every_write(tmp_path, saves, monkeypatch):
    monkeypatch.setattr(facade, "PERSIST_QUIET_S", 0)

    async def main():
        host = await _host(tmp_path)
        try:
            for color in ("#010101", "#020202", "#030303"):
                await _put(color)
            assert len(saves) == 3
            assert _stored_color(host) == "#030303"
        finally:
            await host.shutdown()

    asyncio.run(main())


def test_a_failed_coalesced_save_is_logged_and_never_raised(tmp_path, monkeypatch, caplog):
    async def main():
        host = await _host(tmp_path)
        real = facade.save_config
        try:
            await _put("#0f0f0f")

            def broken(**_kwargs):
                raise OSError("disk full")
            monkeypatch.setattr(facade, "save_config", broken)
            with caplog.at_level("ERROR"):
                facade.flush_pending_saves(host)
            assert not facade.save_pending(host)
            assert "coalesced config save" in caplog.text
        finally:
            monkeypatch.setattr(facade, "save_config", real)
            await host.shutdown()

    asyncio.run(main())


_ONE_SHOT = """
import asyncio, sys
sys.path.insert(0, {repo!r})
from fx import facade, headless
from fx.host import FxHost

async def main():
    headless.write_headless_config({config_dir!r})
    headless.silence_audio()
    host = FxHost({config_dir!r})
    await host.start()
    host.config["coalesced_marker"] = "landed"
    facade._persist_soon(host)
    assert facade.save_pending(host)
    # the loop ends here, before the timer can fire

asyncio.run(main())
"""


def test_a_one_shot_scripts_pending_save_lands_when_the_interpreter_exits(tmp_path):
    import subprocess
    config_dir = str(tmp_path / "fx")
    repo = str(Path(__file__).resolve().parent.parent)
    out = subprocess.run([sys.executable, "-c", _ONE_SHOT.format(repo=repo, config_dir=config_dir)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    with open(Path(config_dir) / "config.json") as f:
        assert json.load(f).get("coalesced_marker") == "landed"
