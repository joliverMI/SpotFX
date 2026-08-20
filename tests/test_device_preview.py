"""Device-preview strip — offline proof (data/spectra-device-preview-plan/
report.md + the pause requirement appended to it, 2026-08-15).

Sections:
  1. Store round-trip + the default-favourites population (room_topology's
     genuinely-driven ground truth, capped, sorted).
  2. Relay protocol, socket-free: frame throttling, _active_event wanting
     (or not wanting) an upstream connection under every paused/favourites
     combination.
  3. API surface (favorites GET/PUT, status, pause/resume) via TestClient.
  4. THE KEY PROOF — a real fake-LedFX WebSocket server on an ephemeral
     loopback port: pause() actually closes the socket (the fake server's
     own live-connection count drops to zero, not just the relay's local
     `connected` flag) and frames stop arriving; resume() reopens it and
     frames resume. This is "prove the feed stopped, not that the display
     blanked" — the owner's own bar for this feature.
  5. THE 2026-08-16 CORRECTION — the in-process facade source (his normal
     S3 operating state, where LedFX is deliberately stopped): ownership-
     routed source selection (_source_mode), real frames off a genuine
     fx.headless render thread with no websocket at all, and the SAME
     genuine-stop pause/auto-pause proofs as section 4 — re-established
     against this source, not assumed to carry over from it.

No LedFX I/O against anything but the ephemeral loopback server this file
starts itself; no audio (fx.headless.silence_audio, via start_headless_host),
no real spectra.service/ledfx.service ports, and section 5's ownership
record lives under an isolated tmp path, never this worktree's own
storage/spectra/ownership.json.
"""
from __future__ import annotations

import asyncio
import base64
import json
import socket

import numpy as np
import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect


def _run(coro):
    return asyncio.run(coro)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "DEVICE_PREVIEW_FILE", tmp_path / "device_preview.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")

    from fx import device_model
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.refresh()


@pytest.fixture(autouse=True)
def _reset_singleton_relay():
    """dp.relay (unlike everything else in this module) is a bare
    module-level singleton, same no-DI-seam shape conftest.py already
    flags for fire_history/ambient_music_gate — the one test that reaches
    it through the live API (test_api_favorites_status_pause_resume) would
    otherwise leak favourites/paused state into whichever test runs next."""
    from spectra.services import device_preview as dp

    def _reset():
        dp.relay.set_favorites([])
        dp.relay.paused = False
        dp.relay._sync()
        dp.relay.connected = False
        dp.relay.frames_received = 0
        dp.relay.frames_relayed = 0
    _reset()
    yield
    _reset()


def _write_categories(tmp_path, virtuals):
    from fx import device_model
    (tmp_path / "device_categories.json").write_text(json.dumps({
        "strips": {"name": "strips", "virtuals": list(virtuals), "effects": []},
    }))
    device_model.refresh()


# ── 1. store + default population ────────────────────────────────────────

def test_store_round_trips(tmp_path):
    from spectra.services import device_preview as dp

    assert dp.load_state() == dp.DevicePreviewState()
    state = dp.DevicePreviewState(favorite_virtual_ids=["a", "b"], paused=True)
    dp.save_state(state)
    assert dp.load_state() == state
    assert not list(tmp_path.glob("**/*.tmp")), "atomic write leaves no temp file behind"


def test_default_favorites_from_genuinely_driven_ground_truth_sorted_and_capped(tmp_path):
    from spectra.services import device_preview as dp

    _write_categories(tmp_path, ["zebra", "alpha", "mid", "delta", "echo", "foxtrot"])
    assert dp.default_favorite_ids() == ["alpha", "delta", "echo", "foxtrot"], \
        "sorted, capped at DEFAULT_FAVORITES_CAP (4)"


def test_effective_favorites_prefers_stored_over_default(tmp_path):
    from spectra.services import device_preview as dp

    _write_categories(tmp_path, ["a", "b", "c"])
    assert dp.effective_favorite_ids() == ["a", "b", "c"], "no stored favourites — falls back"

    dp.save_state(dp.DevicePreviewState(favorite_virtual_ids=["c"]))
    assert dp.effective_favorite_ids() == ["c"], "his explicit choice overrides the default"


def test_empty_ground_truth_yields_empty_default(tmp_path):
    from spectra.services import device_preview as dp
    assert dp.default_favorite_ids() == []
    assert dp.effective_favorite_ids() == []


# ── 2. relay protocol, socket-free ───────────────────────────────────────

def test_active_event_wants_upstream_only_when_unpaused_and_has_favorites():
    from spectra.services import device_preview as dp

    relay = dp.DevicePreviewRelay()
    assert not relay._active_event.is_set(), "no favourites yet — nothing to subscribe to"

    relay.set_favorites(["a"])
    assert relay._active_event.is_set(), "favourites present, not paused — wants upstream"

    relay.pause()
    assert not relay._active_event.is_set(), "paused — must not want upstream regardless of favourites"

    relay.resume()
    assert relay._active_event.is_set(), "resumed — wants upstream again"

    relay.set_favorites([])
    assert not relay._active_event.is_set(), "favourites cleared — nothing to subscribe to"


def test_active_event_requires_a_viewer_even_when_unpaused_with_favorites():
    """OQ-7's demand-driven auto-pause: unpaused + favourites present is
    NOT enough on its own — a connected downstream viewer is a third,
    independent requirement, gated so a hidden tab (zero viewers) can
    genuinely stop the upstream feed without touching the sticky
    `paused` flag at all."""
    from spectra.services import device_preview as dp

    has_viewer = {"v": False}
    relay = dp.DevicePreviewRelay(has_viewers=lambda: has_viewer["v"])
    relay.set_favorites(["a"])
    assert not relay._active_event.is_set(), "no viewer yet — must not want upstream"

    has_viewer["v"] = True
    relay.viewers_changed()
    assert relay._active_event.is_set(), "a viewer connected — wants upstream"

    has_viewer["v"] = False
    relay.viewers_changed()
    assert not relay._active_event.is_set(), "last viewer left — must not want upstream"
    assert relay.paused is False, "viewer-driven auto-pause never touches the sticky pause flag"


def test_handle_frame_throttles_per_vis_id_independently():
    from spectra.services import device_preview as dp

    clock = {"t": 0.0}
    received = []

    async def on_frame(payload):
        received.append(payload)

    relay = dp.DevicePreviewRelay(target_fps=10.0, on_frame=on_frame, clock=lambda: clock["t"])

    async def scenario():
        await relay._handle_frame({"event_type": "visualisation_update", "vis_id": "a",
                                   "pixels": "x", "shape": [1, 1]})
        clock["t"] += 0.05   # under the 0.1s min interval at 10fps
        await relay._handle_frame({"event_type": "visualisation_update", "vis_id": "a",
                                   "pixels": "y", "shape": [1, 1]})
        # A different vis_id is not throttled by "a"'s own last-sent clock.
        await relay._handle_frame({"event_type": "visualisation_update", "vis_id": "b",
                                   "pixels": "z", "shape": [1, 1]})
        clock["t"] += 0.1    # now past "a"'s min interval
        await relay._handle_frame({"event_type": "visualisation_update", "vis_id": "a",
                                   "pixels": "w", "shape": [1, 1]})

    _run(scenario())
    assert [r["vis_id"] for r in received] == ["a", "b", "a"]
    assert relay.frames_received == 4, "every arriving frame counts, even throttled ones"
    assert relay.frames_relayed == 3


def test_handle_frame_ignores_non_visualisation_events():
    from spectra.services import device_preview as dp

    received = []

    async def on_frame(payload):
        received.append(payload)

    relay = dp.DevicePreviewRelay(on_frame=on_frame)
    _run(relay._handle_frame({"event_type": "some_other_event", "vis_id": "a"}))
    assert received == []
    assert relay.frames_received == 0


# ── 3. API surface ────────────────────────────────────────────────────────

def test_api_favorites_status_pause_resume(tmp_path):
    _write_categories(tmp_path, ["a", "b"])

    from fastapi.testclient import TestClient
    from spectra.app import create_app
    from spectra.services import device_preview as dp

    client = TestClient(create_app())

    r = client.get("/api/device-preview/favorites")
    assert r.status_code == 200
    body = r.json()
    assert body["favorite_virtual_ids"] == []
    assert body["effective_virtual_ids"] == ["a", "b"]
    assert body["is_default"] is True

    r = client.put("/api/device-preview/favorites", json={"favorite_virtual_ids": ["b", "b", "a"]})
    assert r.status_code == 200
    body = r.json()
    assert body["favorite_virtual_ids"] == ["b", "a"], "de-duped, order preserved"
    assert body["is_default"] is False
    assert dp.relay._favorite_ids == ["b", "a"], "the live relay adopts the new list immediately"

    r = client.get("/api/device-preview/status")
    assert r.status_code == 200
    assert r.json()["paused"] is False

    r = client.post("/api/device-preview/pause")
    assert r.status_code == 200 and r.json()["paused"] is True
    assert dp.relay.paused is True
    assert dp.load_state().paused is True, "pause persists across a restart"

    r = client.post("/api/device-preview/resume")
    assert r.status_code == 200 and r.json()["paused"] is False
    assert dp.relay.paused is False


def test_ws_connect_and_disconnect_notify_the_relay_of_viewer_changes():
    """The /device-preview/ws endpoint IS the hidden-tab auto-pause signal
    (OQ-7) — connecting/disconnecting it must call relay.viewers_changed()
    so demand gets re-evaluated, not just fan the frame/status broadcast
    out. Spied rather than asserting on _active_event here, since the
    real upstream-drop proof lives in section 4 against a fake server."""
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    from spectra.services import device_preview as dp

    calls = []
    orig = dp.relay.viewers_changed
    dp.relay.viewers_changed = lambda: calls.append(True) or orig()
    try:
        client = TestClient(create_app())
        with client.websocket_connect("/api/device-preview/ws") as ws:
            ws.receive_json()  # the immediate status push on connect
            assert calls == [True], "connect notifies the relay"
        assert calls == [True, True], "disconnect notifies the relay too"
    finally:
        dp.relay.viewers_changed = orig


# ── 4. THE KEY PROOF — pause genuinely drops the upstream socket ─────────

def _fake_ledfx_app():
    """Stands in for LedFX's own /api/websocket (report §2's protocol):
    accepts a connection, honours subscribe_event, and streams a frame
    for every subscribed vis_id at a fast fake source rate — fast enough
    that the relay's own throttle (not the source) is what's normally
    limiting, and fast enough that "frames stopped" is easy to observe in
    a short test window. `state["active_connections"]` is incremented on
    accept and decremented in `finally` — the thing this test actually
    needs to prove pause against, since a relay-local flag alone can't
    tell a real close from a display that merely went dark."""
    app = FastAPI()
    state = {"active_connections": 0, "sent": {}}

    @app.websocket("/api/websocket")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        state["active_connections"] += 1
        subscribed: set[str] = set()
        send_task = None

        async def sender():
            while True:
                await asyncio.sleep(0.01)
                for vid in list(subscribed):
                    state["sent"][vid] = state["sent"].get(vid, 0) + 1
                    await websocket.send_text(json.dumps({
                        "id": f"device-preview:{vid}", "type": "event",
                        "event_type": "visualisation_update",
                        "is_device": False, "vis_id": vid,
                        "pixels": "AAAA", "shape": [1, 1],
                    }))

        try:
            while True:
                msg = json.loads(await websocket.receive_text())
                if msg.get("type") == "subscribe_event":
                    vid = msg["event_filter"]["vis_id"]
                    subscribed.add(vid)
                    if send_task is None:
                        send_task = asyncio.create_task(sender())
        except WebSocketDisconnect:
            pass
        finally:
            state["active_connections"] -= 1
            if send_task is not None:
                send_task.cancel()

    return app, state


async def _serve(app, port: int):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return server, task


async def _stop(server, task):
    server.should_exit = True
    await task


async def _wait_until(predicate, timeout=3.0, interval=0.02):
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(interval)
        elapsed += interval
        if elapsed >= timeout:
            raise AssertionError(f"condition not met within {timeout}s")


def test_pause_actually_closes_the_upstream_socket_not_just_the_display():
    from spectra.services import device_preview as dp

    async def scenario():
        app, fake_state = _fake_ledfx_app()
        port = free_port()
        server, task = await _serve(app, port)
        try:
            relay = dp.DevicePreviewRelay(
                ws_url=f"ws://127.0.0.1:{port}/api/websocket",
                favorite_ids=["alpha"], target_fps=100.0)
            relay.start()
            try:
                await _wait_until(lambda: relay.connected)
                assert fake_state["active_connections"] == 1, \
                    "the fake LedFX server itself sees exactly one live connection"
                await _wait_until(lambda: relay.frames_relayed >= 3)

                relay.pause()
                # Prove the SOCKET closed at the server, not merely a local flag.
                await _wait_until(lambda: fake_state["active_connections"] == 0)
                assert relay.connected is False

                frozen_received = relay.frames_received
                frozen_relayed = relay.frames_relayed
                await asyncio.sleep(0.3)
                assert relay.frames_received == frozen_received, \
                    "paused: no new frames arrive at all — the feed itself stopped"
                assert relay.frames_relayed == frozen_relayed
                assert fake_state["active_connections"] == 0, \
                    "still zero live connections at the server while paused"

                relay.resume()
                await _wait_until(lambda: relay.connected)
                assert fake_state["active_connections"] == 1, "resume reopens a real connection"
                await _wait_until(lambda: relay.frames_relayed > frozen_relayed)
            finally:
                await relay.stop()
        finally:
            await _stop(server, task)

    _run(scenario())


def test_last_viewer_leaving_closes_the_upstream_socket_and_a_viewer_returning_reopens_it():
    """OQ-7's own bar, held to the same standard as the sticky pause proof
    above: a hidden tab auto-pausing must be a REAL closed upstream
    connection at the server (the fake LedFX server's own live-connection
    count dropping to zero), not a local flag or a display that merely
    stopped rendering. Drives demand purely via has_viewers()/
    viewers_changed() — never touches paused/resume — proving auto-pause
    and the sticky pause are genuinely independent mechanisms."""
    from spectra.services import device_preview as dp

    async def scenario():
        app, fake_state = _fake_ledfx_app()
        port = free_port()
        server, task = await _serve(app, port)
        try:
            has_viewer = {"v": True}
            relay = dp.DevicePreviewRelay(
                ws_url=f"ws://127.0.0.1:{port}/api/websocket",
                favorite_ids=["alpha"], target_fps=100.0,
                has_viewers=lambda: has_viewer["v"])
            relay.start()
            try:
                await _wait_until(lambda: relay.connected)
                assert fake_state["active_connections"] == 1
                await _wait_until(lambda: relay.frames_relayed >= 3)

                # Tab hidden — the frontend closes its downstream socket,
                # the server notices the last viewer left.
                has_viewer["v"] = False
                relay.viewers_changed()
                await _wait_until(lambda: fake_state["active_connections"] == 0)
                assert relay.connected is False
                assert relay.paused is False, \
                    "auto-pause via zero viewers must not flip the sticky pause flag"

                frozen_relayed = relay.frames_relayed
                await asyncio.sleep(0.3)
                assert relay.frames_relayed == frozen_relayed, \
                    "no viewers: no new frames arrive at all — the feed itself stopped"
                assert fake_state["active_connections"] == 0

                # Tab visible again — reopens without touching pause/resume.
                has_viewer["v"] = True
                relay.viewers_changed()
                await _wait_until(lambda: relay.connected)
                assert fake_state["active_connections"] == 1, \
                    "a viewer returning reopens a real connection"
                await _wait_until(lambda: relay.frames_relayed > frozen_relayed)
            finally:
                await relay.stop()
        finally:
            await _stop(server, task)

    _run(scenario())


def test_status_change_broadcasts_on_every_connect_transition_not_just_explicit_pause_resume():
    """Regression proof for a real gap caught in a live smoke check
    (2026-08-15): the connect attempt after resume() is asynchronous, so a
    status broadcast fired only from the pause()/resume() API handlers can
    capture `connected: False` moments before the reconnect actually lands
    — an already-open frontend tab would then sit on "reconnecting…"
    forever despite the server being fully live again. _set_connected must
    push on every transition, including ones no explicit pause/resume call
    ever triggered."""
    from spectra.services import device_preview as dp

    async def scenario():
        app, fake_state = _fake_ledfx_app()
        port = free_port()
        server, task = await _serve(app, port)
        try:
            changes = []

            async def on_status_change():
                changes.append(True)

            relay = dp.DevicePreviewRelay(
                ws_url=f"ws://127.0.0.1:{port}/api/websocket",
                favorite_ids=["alpha"], target_fps=100.0,
                on_status_change=on_status_change)
            relay.start()
            try:
                # Nobody called pause()/resume() — the plain start-up
                # connect alone must still push a status change.
                await _wait_until(lambda: relay.connected)
                await _wait_until(lambda: len(changes) >= 1)
                assert changes == [True], "no duplicate push for an unchanged value"
            finally:
                await relay.stop()
        finally:
            await _stop(server, task)

    _run(scenario())


def test_favorites_change_while_connected_forces_a_resubscribe():
    from spectra.services import device_preview as dp

    async def scenario():
        app, fake_state = _fake_ledfx_app()
        port = free_port()
        server, task = await _serve(app, port)
        try:
            relay = dp.DevicePreviewRelay(
                ws_url=f"ws://127.0.0.1:{port}/api/websocket",
                favorite_ids=["alpha"], target_fps=100.0)
            relay.start()
            try:
                await _wait_until(lambda: relay.connected)
                await _wait_until(lambda: "alpha" in fake_state["sent"])

                relay.set_favorites(["beta"])
                await _wait_until(lambda: "beta" in fake_state["sent"])
                assert relay.connected, "reconnected under the new favourites, not left dark"
            finally:
                await relay.stop()
        finally:
            await _stop(server, task)

    _run(scenario())


# ── 5. THE 2026-08-16 CORRECTION — the in-process facade source ──────────
#
# The relay used to assume LedFX was always the writer. It isn't: whenever
# light ownership is "spectra" (his normal S3 operating state), the
# external LedFX process is deliberately stopped and SPECTRA's own
# in-process fx/ pipeline drives the devices instead — the original relay
# just sat on "reconnecting…" forever in that state. These tests build a
# REAL headless FxHost (fx.headless — a genuine render thread, not a mock)
# and prove the relay reads live frames off it with no websocket at all,
# held to the identical pause/genuine-stop bar as the LedFX path above.

from fx import headless as _headless
from fx import light_ownership as _lo
from fx.events import Event as _Event, VirtualUpdateEvent as _VirtualUpdateEvent

_ORIGINAL_OWNERSHIP_FILE = _lo.OWNERSHIP_FILE


@pytest.fixture
def _isolated_ownership(tmp_path):
    """Points fx.light_ownership at a tmp record so tests can set owner
    without touching this worktree's real storage/spectra/ownership.json —
    same pattern tests/test_spectra_activation_truth.py already uses."""
    _lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
    yield
    _lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


@pytest.fixture
def _restore_live_host():
    """dp._source_mode() reads spectra.services.live_host.live — a bare
    module-level singleton (same no-DI-seam shape as dp.relay itself,
    CLAUDE.md's documented pattern for fire_history/ambient_music_gate).
    These tests poke live.host directly rather than going through the full
    activate()/deactivate() handover machinery (irrelevant here — dummy
    devices need no ActivationGrant, fx/host.py's own docstring), but must
    still leave it exactly as found for every other test file sharing this
    process."""
    from spectra.services.live_host import live
    yield live
    live.host = None


async def _live_headless_host(tmp_path, *, virtual_id="preview-virtual",
                              pixel_count=12, rows=3):
    """A real FxHost with one dummy device/virtual running an actual
    render thread (fx.headless.start_headless_host + initial_effect —
    without it the virtual never activates and never fires
    Event.VIRTUAL_UPDATE at all)."""
    return await _headless.start_headless_host(
        str(tmp_path / "fx-live"),
        device_id=virtual_id, pixel_count=pixel_count, rows=rows,
        initial_effect={"type": "singleColor", "config": {"color": "#ff0000"}})


def test_source_mode_reads_the_ownership_record(tmp_path, _isolated_ownership, _restore_live_host):
    from spectra.services import device_preview as dp
    live = _restore_live_host

    assert dp._source_mode() == "ledfx", "missing record — the shipped default is spot-effects owns"

    _lo._save(_lo.OwnershipRecord(owner=_lo.SPECTRA))
    assert dp._source_mode() == "none", \
        "spectra owns on paper but her live stack isn't up — nothing to read frames off"

    live.host = object()  # stand-in: only `is not None` (live.active) matters here
    assert dp._source_mode() == "facade"

    live.host = None
    _lo._save(_lo.OwnershipRecord(owner=_lo.SPOT_EFFECTS))
    assert dp._source_mode() == "ledfx"


def test_facade_relay_receives_real_frames_with_no_websocket(tmp_path, _isolated_ownership, _restore_live_host):
    """The core positive proof: a real render thread's real pixels reach
    the relay via Event.VIRTUAL_UPDATE alone — no upstream socket, no
    ws_url ever consulted."""
    from spectra.services import device_preview as dp
    live = _restore_live_host

    async def scenario():
        host = await _live_headless_host(tmp_path)
        live.host = host
        _lo._save(_lo.OwnershipRecord(owner=_lo.SPECTRA))
        try:
            received = []

            async def on_frame(payload):
                received.append(payload)

            relay = dp.DevicePreviewRelay(
                favorite_ids=["preview-virtual"], target_fps=100.0, on_frame=on_frame)
            relay.start()
            try:
                await _wait_until(lambda: relay.connected)
                await _wait_until(lambda: relay.frames_relayed >= 3)
                assert received, "frames actually reached on_frame, not just the counter"
                frame = received[0]
                assert frame["vis_id"] == "preview-virtual"
                assert frame["shape"] == [3, 4], "rows from the virtual's own config (12 px / 3 rows)"
                assert isinstance(frame["pixels"], str), \
                    "base64 interleaved rgb bytes — same compact wire shape LedFX's own " \
                    "default (transmission_mode=compressed) uses, not a JSON int list"
                decoded = base64.b64decode(frame["pixels"])
                assert len(decoded) == 12 * 3, "12 pixels x 3 channels, full resolution — no downsampling"
            finally:
                await relay.stop()
        finally:
            live.host = None
            await host.shutdown()

    _run(scenario())


def test_facade_pause_removes_the_listener_not_just_a_local_flag(tmp_path, _isolated_ownership, _restore_live_host):
    """THE KEY PROOF, facade edition: pause must remove the event listener
    from the live host's own registry (the in-process equivalent of a
    closed socket), proven by firing a frame DIRECTLY at the host's event
    bus while paused and showing it never reaches the relay at all — not
    merely that `connected` reads False."""
    from spectra.services import device_preview as dp
    live = _restore_live_host

    async def scenario():
        host = await _live_headless_host(tmp_path)
        live.host = host
        _lo._save(_lo.OwnershipRecord(owner=_lo.SPECTRA))
        try:
            relay = dp.DevicePreviewRelay(favorite_ids=["preview-virtual"], target_fps=100.0)
            relay.start()
            try:
                await _wait_until(lambda: relay.connected)
                await _wait_until(lambda: relay.frames_relayed >= 2)
                before = len(host.events._listeners.get(_Event.VIRTUAL_UPDATE, []))
                assert before >= 1, "the relay's own listener is registered on the real host"

                relay.pause()
                await _wait_until(lambda: relay.connected is False)
                after = len(host.events._listeners.get(_Event.VIRTUAL_UPDATE, []))
                assert after == before - 1, \
                    "the listener itself is gone from the host's registry, not just flagged off"

                frozen_received = relay.frames_received
                # Fire directly at the real bus — proves the callback is
                # genuinely unreachable, not merely idle.
                host.events.fire_event(_VirtualUpdateEvent(
                    "preview-virtual", np.zeros((12, 3))))
                await asyncio.sleep(0.2)
                assert relay.frames_received == frozen_received, \
                    "paused: a frame fired directly at the bus never reaches the relay"

                relay.resume()
                await _wait_until(lambda: relay.connected)
                await _wait_until(lambda: relay.frames_relayed > frozen_received)
            finally:
                await relay.stop()
        finally:
            live.host = None
            await host.shutdown()

    _run(scenario())


def test_facade_last_viewer_leaving_removes_the_listener_too(tmp_path, _isolated_ownership, _restore_live_host):
    """OQ-7's hidden-tab auto-pause, re-proven against the facade source:
    zero viewers must genuinely unsubscribe, never just stop rendering
    locally, and must never touch the sticky `paused` flag."""
    from spectra.services import device_preview as dp
    live = _restore_live_host

    async def scenario():
        host = await _live_headless_host(tmp_path)
        live.host = host
        _lo._save(_lo.OwnershipRecord(owner=_lo.SPECTRA))
        try:
            has_viewer = {"v": True}
            relay = dp.DevicePreviewRelay(
                favorite_ids=["preview-virtual"], target_fps=100.0,
                has_viewers=lambda: has_viewer["v"])
            relay.start()
            try:
                await _wait_until(lambda: relay.connected)
                await _wait_until(lambda: relay.frames_relayed >= 2)

                has_viewer["v"] = False
                relay.viewers_changed()
                await _wait_until(lambda: relay.connected is False)
                assert relay.paused is False, "auto-pause via zero viewers must not touch the sticky flag"

                frozen = relay.frames_relayed
                await asyncio.sleep(0.2)
                assert relay.frames_relayed == frozen

                has_viewer["v"] = True
                relay.viewers_changed()
                await _wait_until(lambda: relay.connected)
                await _wait_until(lambda: relay.frames_relayed > frozen)
            finally:
                await relay.stop()
        finally:
            live.host = None
            await host.shutdown()

    _run(scenario())


def test_status_reports_source(tmp_path, _isolated_ownership, _restore_live_host):
    from spectra.services import device_preview as dp

    relay = dp.DevicePreviewRelay()
    assert relay.status()["source"] == "ledfx", "default record — spot-effects owns"

    _lo._save(_lo.OwnershipRecord(owner=_lo.SPECTRA))
    assert relay.status()["source"] == "none", "spectra owns but her live stack isn't up"
