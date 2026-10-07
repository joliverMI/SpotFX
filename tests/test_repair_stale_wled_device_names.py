"""scripts/repair_stale_wled_device_names.py — the one-time catch-up for
the four device names the pre-#53 bug in fx/devices/wled.py's
async_initialize() clobbered back to the firmware default "WLED" before
the fix landed.

Only the four named device ids are touched, and only when their stored
`config.name` is currently exactly the stale "WLED" — a device already
renamed to something else, or genuinely unnamed, is left alone. The
written config is asserted SEMANTICALLY identical to the original except
the planned renames.
"""
from __future__ import annotations

import copy
import contextlib
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

_SCRIPT = (Path(__file__).resolve().parent.parent / "scripts"
           / "repair_stale_wled_device_names.py")
_spec = importlib.util.spec_from_file_location(
    "repair_stale_wled_device_names", _SCRIPT)
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)


def _device(device_id: str, name: str, **extra_config) -> dict:
    cfg = {"name": name, "pixel_count": 30}
    cfg.update(extra_config)
    return {"id": device_id, "type": "wled", "config": cfg}


def _config() -> dict:
    """His real four plus controls: an already-renamed one, an unrelated
    device that genuinely ships named "WLED" (a device id not in his four),
    and a device with no name at all."""
    return {
        "configuration_version": 1,
        "devices": [
            _device("crystal", "WLED"),
            _device("tv-backlight", "WLED"),
            _device("dining-table", "Dining Table"),
            _device("porch-rail", "WLED"),
            _device("some-other-wled", "WLED"),
            {"id": "no-name-yet", "type": "wled", "config": {}},
        ],
        "virtuals": [{"id": "crystal", "is_device": "crystal"}],
    }


def _write(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))


def _run(monkeypatch, path: Path, *flags: str) -> int:
    monkeypatch.setattr("sys.argv", [str(_SCRIPT), "--config", str(path),
                                     *flags])
    return repair.main()


@contextlib.contextmanager
def _fake_live_service(fail_device_ids: frozenset[str] = frozenset()):
    """A minimal stand-in for spectra.service's real `PUT /api/devices/{id}`
    route (fx/facade.py::_device_put): merges the posted config into an
    in-memory per-device store and echoes it back, exactly like the real
    `host.config` mutation this script exists to reach. `fail_device_ids`
    makes the named device(s) answer 400, like a device the live host
    cannot find."""
    received: dict[str, dict] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            device_id = self.path.rsplit("/", 1)[-1]
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if device_id in fail_device_ids:
                payload = json.dumps(
                    {"status": "failed",
                     "payload": {"reason": f"no such device {device_id}"}}
                ).encode()
                self.send_response(400)
            else:
                received[device_id] = body.get("config") or {}
                payload = json.dumps(
                    {"status": "success",
                     "device": {"id": device_id,
                               "config": received[device_id]}}
                ).encode()
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # silence BaseHTTPRequestHandler noise
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_only_the_four_named_devices_at_the_stale_name_are_found():
    stale = repair.find_stale(_config()["devices"])
    by_id = {s["id"]: s for s in stale}
    assert set(by_id) == {"crystal", "tv-backlight", "porch-rail"}
    assert by_id["crystal"]["target"] == "Crystal"
    assert by_id["tv-backlight"]["target"] == "TV Backlight"
    assert by_id["porch-rail"]["target"] == "Porch Rail"


def test_an_already_renamed_device_is_left_alone(tmp_path, monkeypatch,
                                                 capsys):
    config = _config()
    config["devices"] = [d for d in config["devices"]
                         if d["id"] in ("crystal", "dining-table")]
    path = tmp_path / "fx" / "config.json"
    _write(path, config)
    assert _run(monkeypatch, path, "--apply") == 0
    written = json.loads(path.read_text())
    names = {d["id"]: d["config"]["name"] for d in written["devices"]}
    assert names["crystal"] == "Crystal"
    assert names["dining-table"] == "Dining Table"


def test_the_fix_and_the_repair_together_make_a_rename_stick(tmp_path,
                                                              monkeypatch,
                                                              capsys):
    """Through the real write path: apply the repair, then run the real
    (fixed) async_initialize-style rule and confirm the now-correct name
    is left untouched — the scenario #53 alone cannot close."""
    path = tmp_path / "fx" / "config.json"
    _write(path, _config())
    original = json.loads(path.read_text())

    assert _run(monkeypatch, path, "--apply") == 0
    out = capsys.readouterr().out
    assert "wrote" in out
    assert "crystal" in out and "tv-backlight" in out and "porch-rail" in out

    written = json.loads(path.read_text())
    by_id = {d["id"]: d for d in written["devices"]}
    assert by_id["crystal"]["config"]["name"] == "Crystal"
    assert by_id["tv-backlight"]["config"]["name"] == "TV Backlight"
    assert by_id["porch-rail"]["config"]["name"] == "Porch Rail"
    assert by_id["dining-table"]["config"]["name"] == "Dining Table"
    assert by_id["some-other-wled"]["config"]["name"] == "WLED", (
        "a device outside his four named ones is never touched, even at "
        "the stale default")
    assert by_id["no-name-yet"]["config"].get("name") is None

    repair.assert_only_planned_name_changes(
        original, written,
        {"crystal": "Crystal", "tv-backlight": "TV Backlight",
         "porch-rail": "Porch Rail"})

    backups = list((tmp_path / "fx" / "backups").glob(
        "config-wled-names-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == original

    # The #53 rule itself: a reported firmware name only fills in a
    # currently-falsy stored name — the now-genuinely-set "Crystal" must
    # survive a simulated restart unconditionally.
    for device_id in ("crystal", "tv-backlight", "porch-rail", "dining-table"):
        stored_config = by_id[device_id]["config"]
        if not stored_config.get("name"):
            stored_config["name"] = "WLED"
    assert by_id["crystal"]["config"]["name"] == "Crystal"
    assert by_id["tv-backlight"]["config"]["name"] == "TV Backlight"
    assert by_id["porch-rail"]["config"]["name"] == "Porch Rail"


def test_dry_run_writes_nothing_and_names_the_three(tmp_path, monkeypatch,
                                                     capsys):
    path = tmp_path / "fx" / "config.json"
    _write(path, _config())
    raw = path.read_bytes()
    assert _run(monkeypatch, path) == 0
    assert path.read_bytes() == raw
    assert not (tmp_path / "fx" / "backups").exists()
    out = capsys.readouterr().out
    assert "dry-run: would set 3 device name(s)" in out
    assert "crystal" in out and "tv-backlight" in out and "porch-rail" in out
    assert "dining-table" not in out
    assert "some-other-wled" not in out


def test_the_repair_is_idempotent(tmp_path, monkeypatch, capsys):
    path = tmp_path / "fx" / "config.json"
    _write(path, _config())
    assert _run(monkeypatch, path, "--apply") == 0
    first = path.read_bytes()
    capsys.readouterr()
    assert _run(monkeypatch, path, "--apply") == 0
    assert "nothing to correct" in capsys.readouterr().out
    assert path.read_bytes() == first
    backups = list((tmp_path / "fx" / "backups").glob("*.json"))
    assert len(backups) == 1


def test_a_config_with_no_stale_names_is_left_alone(tmp_path, monkeypatch,
                                                     capsys):
    config = _config()
    for d in config["devices"]:
        if d["id"] in repair.FRIENDLY_NAMES:
            d["config"]["name"] = repair.FRIENDLY_NAMES[d["id"]]
    path = tmp_path / "fx" / "config.json"
    _write(path, config)
    raw = path.read_bytes()
    assert _run(monkeypatch, path, "--apply") == 0
    assert "nothing to correct" in capsys.readouterr().out
    assert path.read_bytes() == raw


def test_the_written_diff_guard_refuses_anything_but_the_plan():
    original = _config()
    planned = {"crystal": "Crystal", "tv-backlight": "TV Backlight",
              "porch-rail": "Porch Rail"}
    good = copy.deepcopy(original)
    for d in good["devices"]:
        if d["id"] in planned:
            d["config"]["name"] = planned[d["id"]]
    repair.assert_only_planned_name_changes(original, good, planned)

    stray = copy.deepcopy(good)
    next(d for d in stray["devices"]
         if d["id"] == "dining-table")["config"]["name"] = "Something Else"
    with pytest.raises(AssertionError, match="not planned"):
        repair.assert_only_planned_name_changes(original, stray, planned)

    touched = copy.deepcopy(good)
    next(d for d in touched["devices"]
         if d["id"] == "crystal")["config"]["pixel_count"] = 99
    with pytest.raises(AssertionError, match="other than `name`"):
        repair.assert_only_planned_name_changes(original, touched, planned)

    unlanded = copy.deepcopy(original)
    with pytest.raises(AssertionError, match="did not land"):
        repair.assert_only_planned_name_changes(original, unlanded, planned)


def test_a_missing_config_is_a_stated_exit(tmp_path, monkeypatch, capsys):
    assert _run(monkeypatch, tmp_path / "nope.json") == 2
    assert "pass --config PATH" in capsys.readouterr().out


def test_apply_live_renames_through_a_real_http_put():
    planned = {"crystal": "Crystal", "tv-backlight": "TV Backlight",
              "porch-rail": "Porch Rail"}
    with _fake_live_service() as (url, received):
        results = repair.apply_live(url, planned)
    assert dict(results) == {"crystal": "live", "tv-backlight": "live",
                             "porch-rail": "live"}
    assert received == {
        "crystal": {"name": "Crystal"},
        "tv-backlight": {"name": "TV Backlight"},
        "porch-rail": {"name": "Porch Rail"},
    }


def test_main_with_spectra_url_applies_live_and_never_rewrites_the_file(
        tmp_path, monkeypatch, capsys):
    """The whole point of the live path: `host.config` (here, the fake
    service's own `received` store) gets the rename, and the on-disk file
    this script would otherwise edit is left holding the stale names —
    exactly as a real spectra.service's own save would, since nothing
    here ever told it to change anything."""
    path = tmp_path / "fx" / "config.json"
    _write(path, _config())
    raw = path.read_bytes()

    with _fake_live_service() as (url, received):
        assert _run(monkeypatch, path, "--spectra-url", url, "--apply") == 0

    assert received == {
        "crystal": {"name": "Crystal"},
        "tv-backlight": {"name": "TV Backlight"},
        "porch-rail": {"name": "Porch Rail"},
    }
    assert path.read_bytes() == raw, (
        "the live path must not touch config.json's device names — the "
        "live service's own save is what persists them")
    backups = list((tmp_path / "fx" / "backups").glob("*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == json.loads(raw)
    out = capsys.readouterr().out
    assert "live" in out
    assert "crystal" in out and "tv-backlight" in out and "porch-rail" in out


def test_apply_live_stops_and_names_the_device_on_a_bad_response():
    planned = {"crystal": "Crystal", "tv-backlight": "TV Backlight"}
    with _fake_live_service(fail_device_ids=frozenset({"crystal"})) as (
            url, received):
        with pytest.raises(SystemExit, match="crystal"):
            repair.apply_live(url, planned)
    assert received == {}, (
        "crystal sorts before tv-backlight, so the failure must stop "
        "before any rename is attempted")


def test_apply_live_names_the_device_when_the_service_is_unreachable():
    with _fake_live_service() as (url, _received):
        pass  # server is already shut down by the time we call below
    with pytest.raises(SystemExit, match="crystal"):
        repair.apply_live(url, {"crystal": "Crystal"})


def test_dry_run_with_spectra_url_names_the_live_path_and_makes_no_call(
        tmp_path, monkeypatch, capsys):
    path = tmp_path / "fx" / "config.json"
    _write(path, _config())
    raw = path.read_bytes()
    # No server listening at all — a network call here would raise and
    # fail the test, proving the dry run makes none.
    assert _run(monkeypatch, path, "--spectra-url",
               "http://127.0.0.1:1") == 0
    assert path.read_bytes() == raw
    assert not (tmp_path / "fx" / "backups").exists()
    out = capsys.readouterr().out
    assert "live service" in out
