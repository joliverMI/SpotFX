"""Shared test plumbing: a fake LedFX API server + per-test isolation of the
api.ledfx_client module globals.

No live access anywhere: every test talks to an in-process asyncio server on an
ephemeral loopback port. The topology payloads are recorded from the production
LedFX (2026-08-12) — the same shapes ambient-mode group discovery reads live.

The repo has no test infrastructure beyond this; tests are plain pytest
functions that drive their own event loop via asyncio.run(), so no
pytest-asyncio plugin is needed. Run with:  pip install -r requirements-dev.txt
&& python -m pytest
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Recorded from the live LedFX API (GET /api/virtuals, /api/devices/{id}) —
# trimmed to the fields ambient-mode discovery actually reads.
LIVE_VIRTUALS = {
    "hue-lights": {
        "active": False, "effect": {},
        "segments": [["hue-lights", 0, 9, False, 0]],
    },
    "dining-hues": {
        "active": False, "effect": {},
        "segments": [["dining-hues", 0, 6, False, 0]],
    },
    # The virtual that actually drives the bulbs during music: spans both Hue
    # devices per-pixel. Present so discovery must cope with segment refs.
    "hues": {
        "active": True, "effect": {"type": "power", "config": {}},
        "segments": [["hue-lights", 0, 0, False, 0], ["dining-hues", 0, 0, False, 0]],
    },
    "tv-mapper": {
        "active": True, "effect": {"type": "blackhole1d", "config": {}},
        "segments": [["tv-backlight", 0, 559, False, 0]],
    },
}

LIVE_DEVICES = {
    "hue-lights": {
        "type": "hue",
        "config": {
            "name": "Hue Lights", "ip_address": "192.168.40.201",
            "username": "test-app-key", "entertainment_id": "ent-1",
            "pixel_count": 10,
        },
    },
    "dining-hues": {
        "type": "hue",
        "config": {
            "name": "Dining Hues", "ip_address": "192.168.40.202",
            "username": "test-app-key", "entertainment_id": "ent-2",
            "pixel_count": 7,
        },
    },
    "tv-backlight": {
        "type": "wled",
        "config": {"name": "TV Backlight", "ip_address": "192.168.40.203"},
    },
}

# The live device-category record the ambient target points at.
LIVE_CATEGORY_ID = "2a86489e-1d99-43e6-b4cf-46756b027dc5"
LIVE_CATEGORIES = {
    LIVE_CATEGORY_ID: {
        "id": LIVE_CATEGORY_ID,
        "name": "Hue",
        "parent_id": None,
        "virtuals": ["hue-lights", "dining-hues"],
        "effects": ["power"],
        "sort_order": 3,
        "role": None,
    }
}


class FakeLedFX:
    """Minimal HTTP/1.1 LedFX stand-in. mode: 'ok' answers instantly;
    'stall' accepts + reads the request but never responds (the live outage's
    initiating LedFX behavior); 'lie' answers PUT /api/virtuals/{id} with
    {"status": "success"} WITHOUT actually flipping the virtual's active
    state — a command that claims success without it being true, the exact
    shape a read-back verification must catch."""

    def __init__(self, virtuals=None, devices=None):
        self.mode = "ok"
        self.virtuals = dict(LIVE_VIRTUALS if virtuals is None else virtuals)
        self.devices = dict(LIVE_DEVICES if devices is None else devices)
        self.requests: list[str] = []
        self.calls: list[tuple[str, str]] = []   # (method, path), method+state-aware
        self._server = None
        self.base_url = ""

    async def __aenter__(self):
        import asyncio
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc):
        # close() only; wait_closed() would block on stalled handler tasks
        # (3.12 waits for handlers) — asyncio.run() reaps them at loop teardown.
        self._server.close()

    def _route(self, method: str, path: str, body: bytes = b""):
        if path == "/api/virtuals":
            return {"virtuals": self.virtuals}
        if path.startswith("/api/devices/") and path.endswith("/freeze"):
            did = path.split("/")[3]
            return {"id": did, "frozen": False}
        if path.startswith("/api/devices/"):
            did = path.split("/")[3]
            return self.devices.get(did)
        if path.startswith("/api/virtuals/"):
            vid = path.split("/")[3]
            v = self.virtuals.get(vid)
            if v is None:
                return None
            if method == "PUT" and body:
                # Mutates real state (not just echoes the request) so a
                # caller's own follow-up GET proves the write actually
                # landed — the release-verification proof needs this.
                try:
                    data = json.loads(body)
                except ValueError:
                    data = {}
                if "active" in data and self.mode != "lie":
                    v["active"] = bool(data["active"])
                return {"status": "success"}
            return {vid: v}
        return {"status": "ok"}

    async def _handle(self, reader, writer):
        import asyncio
        try:
            while True:
                header = await reader.readuntil(b"\r\n\r\n")
                request_line = header.split(b"\r\n", 1)[0].decode()
                method, path = request_line.split(" ")[0], request_line.split(" ")[1]
                clen = 0
                for line in header.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        clen = int(line.split(b":", 1)[1])
                body = b""
                if clen:
                    body = await reader.readexactly(clen)
                self.requests.append(path)
                self.calls.append((method, path))
                if self.mode == "stall":
                    await asyncio.sleep(3600)
                    return
                payload = self._route(method, path, body)
                if payload is None:
                    writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                else:
                    body = json.dumps(payload).encode()
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
                    )
                await writer.drain()
        except Exception:
            try:
                writer.close()
            except Exception:
                pass


@pytest.fixture()
def fresh_ledfx_client():
    """Reload api.ledfx_client so each test gets pristine module globals
    (semaphore, client, counters) unbound from any previous test's event loop.
    Returns a `make(base_url)` callable."""

    def make(base_url: str):
        import api.ledfx_client as lc
        importlib.reload(lc)
        object.__setattr__(lc.settings, "ledfx_base_url", base_url)
        return lc

    yield make


@pytest.fixture(autouse=True)
def _isolated_fire_history(tmp_path, monkeypatch):
    """SPECTRA's fire-history counter/show-log (spectra/services/
    fire_history.py) is written from inside production choke points
    (scene_sequencer.fire_scene_by_id, engine.fire_response_event,
    drift_conductor.apply_set_directly, trigger_engine._fire) with no DI
    seam of its own — unlike every other SPECTRA store, tests that build
    those objects with fully injected/in-memory dependencies (e.g.
    test_trigger_engine.py's real DriftConductor with in-memory room
    load/save) would otherwise still hit real repo storage. Autouse so no
    individual test needs to know this store exists.
    """
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "FIRE_HISTORY_FILE", tmp_path / "fire_history.json")
    monkeypatch.setattr(scfg, "SHOW_LOG_FILE", tmp_path / "show_log.json")


@pytest.fixture(autouse=True)
def _isolated_dwell():
    """spectra/services/dwell.py (minimum dwell, 2026-08-20) tracks the
    active scene's own latched entry time/seconds as bare module globals —
    same no-DI-seam shape as _isolated_ambient_music_gate above, and fed
    from the same no-DI-seam choke point _isolated_fire_history exists
    for (scene_sequencer.fire_scene_by_id). Any test that fires a scene
    for real would otherwise leak a latched dwell window into the next
    test — a later fire in a DIFFERENT test can get silently deferred by
    a still-running "minimum hold" from a fire the previous test made.
    Autouse so no individual test needs to know this store exists."""
    from spectra.services import dwell
    dwell.reset()
    yield
    dwell.reset()


@pytest.fixture(autouse=True)
def _isolated_preview_pause():
    """spectra/services/preview_pause.py (the flare/colour-set preview's
    global pause deadline) is a bare module global (_until) with no DI
    seam — same no-DI-seam shape as dwell.py above. scene_sequencer.
    fire_scene_by_id now reads it too (2026-08-21,
    fm/preview-must-hold-scene-changes), on top of the pre-existing
    room_preview.py/flare_preview.py callers — a leaked active pause from
    one test would now silently defer a scene fire in a completely
    unrelated test that never touches preview_pause itself. Autouse so no
    individual test needs to know this store exists."""
    from spectra.services import preview_pause
    preview_pause.clear()
    yield
    preview_pause.clear()


@pytest.fixture(autouse=True)
def _isolated_param_watchdog():
    """spectra/services/param_watchdog.py (the param orphan watchdog,
    2026-08-21) keeps its suspicion clocks / restore counts / give-ups as
    bare module globals — same no-DI-seam shape as dwell.py / preview_pause
    above. A suspicion started by one test's sweep would otherwise age into
    a restore inside an unrelated later test that happens to build the
    same virtual id. Autouse so no individual test needs to know this
    store exists."""
    from spectra.services import param_watchdog
    param_watchdog.reset()
    yield
    param_watchdog.reset()


@pytest.fixture(autouse=True)
def _isolated_sonic_usage(tmp_path, monkeypatch):
    """spectra/services/sonic_usage.py (Sonic's durable per-call token-usage
    record, review page) is written from inside settings_agent.run_turn /
    settings_agent_cli.run_turn with no DI seam of its own — same class of
    risk as fire_history.py above. Autouse so no individual test needs to
    know this store exists."""
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SONIC_USAGE_FILE", tmp_path / "sonic_usage.json")


@pytest.fixture(autouse=True)
def _isolated_ambient_music_gate():
    """spectra/services/ambient_music_gate.py tracks the live Ambient hold
    (_held/_held_color/_last_result/_apply_lock, the status-honesty verify
    bookkeeping _verified_ok/_last_verified_ms/_last_verify added
    2026-08-15, and the Hue entertainment-area selection bookkeeping
    _held_group_ids/_held_resolved_groups added 2026-08-16) as bare module
    globals, same no-DI-seam shape as
    fire_history above — any test that reaches reconcile_ambient_if_changed
    / reconcile_now / verify_now (settings-console tests, room-controls PUT
    tests, the ambient verifier tests) would otherwise leak a held/failed/
    verified state into the next test. Autouse so no individual test needs
    to know this exists.
    """
    from spectra.services import ambient_music_gate as gate

    def _reset():
        gate._held = False
        gate._held_color = None
        gate._held_group_ids = frozenset()
        gate._held_resolved_groups = frozenset()
        gate._last_result = {}
        gate._apply_lock = None
        gate._verified_ok = None
        gate._last_verified_ms = None
        gate._last_verify = {}
    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _isolated_intensity_scale(tmp_path, monkeypatch):
    """spectra/services/intensity_scale.py (the per-song genre+bass render
    scale) has no DI seam either — its own module-level feature cache
    (_features) persists across tests, and its cache FILE
    (config.INTENSITY_SCALE_CACHE_FILE) is a real write path under
    storage/spectra/, same class of risk as fire_history above. Also
    repoints the read-only source dirs it (via analysis_reader) reads —
    AUDIO_SHAPES_DIR / TRAINING_PROFILES_FILE — to an empty tmp_path so a
    test exercising a production render_intensity default never sweeps the
    real (possibly very large) library, and repoints
    INTENSITY_SCALE_MARKS_FILE (intensity_scale_marks.py, the 2026-08-15
    per-track manual mark) — a real write path, same class of risk.
    Autouse so no individual test needs to know this exists."""
    from spectra import config as scfg
    from spectra.services import analysis_reader, intensity_scale
    monkeypatch.setattr(scfg, "INTENSITY_SCALE_CACHE_FILE",
                        tmp_path / "intensity_scale_features.json")
    monkeypatch.setattr(scfg, "INTENSITY_SCALE_MARKS_FILE",
                        tmp_path / "intensity_scale_marks.json")
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TRAINING_PROFILES_FILE",
                        tmp_path / "training_profiles.json")
    intensity_scale.invalidate_cache()
    analysis_reader._shape_index = {}
    analysis_reader._index_built = False
    yield
    intensity_scale.invalidate_cache()
    analysis_reader._shape_index = {}
    analysis_reader._index_built = False


@pytest.fixture()
def ambient_env(tmp_path, monkeypatch, fresh_ledfx_client):
    """Ambient discovery against the recorded live topology: category file on
    tmp disk, target category configured, ambient_mode module state reset."""
    import services.device_category_service as dcs
    import services.ambient_mode as am

    cat_file = tmp_path / "device_categories.json"
    cat_file.write_text(json.dumps(LIVE_CATEGORIES), encoding="utf-8")
    monkeypatch.setattr(dcs, "CATEGORIES_FILE", cat_file)
    monkeypatch.setattr(am, "_groups_cache", None)
    monkeypatch.setattr(am, "_lock", None)
    am._light_cache.clear()
    object.__setattr__(am.settings, "ambient_target_category", LIVE_CATEGORY_ID)
    return am
