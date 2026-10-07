"""scripts/fix_loft_ledge_bulb_scope.py — the one-time catch-up this repo's
own code-default fix (AGENTS.md's "THE FOUR BULBS ARE ORDINARY",
fx/hue_scope.py's module docstring) cannot itself apply to a room that
already ran the OLD scripts/seed_hue_scope.py / scripts/
seed_house_lighting.py defaults: the Loft Ceiling Uplight and the three
Ledge bulbs sitting in storage/spectra/hue_scope.json's "excluded" map
and named in HouseSettings.hue_excluded_lights.

Half (a) (hue_scope.json) is a plain backed-up file edit; half (b)
(HouseSettings.hue_excluded_lights) only ever goes through the live
service's own PUT /api/house/settings, proven here against a real
HTTP server standing in for it.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parent.parent / "scripts"
          / "fix_loft_ledge_bulb_scope.py")
_spec = importlib.util.spec_from_file_location(
    "fix_loft_ledge_bulb_scope", _SCRIPT)
fix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fix)


def _scope_with_four_excluded(**extra_excluded) -> dict:
    return {
        "lights": {"l-stand-1": "Standing Lamp 1",
                  "l-corner": "Living Room Corner"},
        "excluded": {
            "l-loft": "Loft Ceiling Uplight",
            "l-ledge-l": "Ledge Left",
            "l-ledge-r": "Ledge Right",
            "l-ledge-c": "Ledge Center",
            **extra_excluded,
        },
        "written_at": "2026-10-05T00:00:00",
        "source": "scripts/seed_hue_scope.py (read from the bridges)",
    }


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _run(monkeypatch, root: Path, *flags: str) -> int:
    monkeypatch.setattr(
        "sys.argv", [str(_SCRIPT), "--root", str(root), *flags])
    return fix.main()


@contextlib.contextmanager
def _fake_house_settings(initial_excluded, fail_get: bool = False,
                         fail_put: bool = False):
    """Stands in for spectra/api/house.py's GET/PUT /api/house/settings,
    mirroring spectra/services/house.py::apply_settings_patch's own
    partial-merge contract for hue_excluded_lights: only the posted key
    moves, everything else is untouched."""
    state = {"hue_excluded_lights": list(initial_excluded),
            "enabled": True}
    puts: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if fail_get:
                self.send_response(500)
                self.end_headers()
                return
            payload = json.dumps({"settings": state}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_PUT(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            puts.append(body)
            if fail_put:
                self.send_response(400)
                self.end_headers()
                return
            if "hue_excluded_lights" in body:
                state["hue_excluded_lights"] = list(body["hue_excluded_lights"])
            payload = json.dumps({"settings": state}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state, puts
    finally:
        server.shutdown()
        thread.join(timeout=5)


# ── pure helpers ─────────────────────────────────────────────────────────

def test_plan_scope_finds_only_his_four_names_in_excluded():
    scope = _scope_with_four_excluded(**{"l-other": "Someone Else's Bulb"})
    to_move = fix.plan_scope(scope)
    assert set(to_move) == {"l-loft", "l-ledge-l", "l-ledge-r", "l-ledge-c"}
    assert to_move["l-loft"] == "Loft Ceiling Uplight"


def test_plan_scope_is_case_insensitive_and_strips_whitespace():
    scope = {"excluded": {"x": " loft ceiling uplight "}}
    assert fix.plan_scope(scope) == {"x": " loft ceiling uplight "}


def test_plan_scope_handles_a_missing_or_malformed_excluded_map():
    assert fix.plan_scope({}) == {}
    assert fix.plan_scope({"excluded": None}) == {}
    assert fix.plan_scope({"excluded": "not-a-dict"}) == {}


def test_apply_scope_moves_only_the_planned_pairs():
    scope = _scope_with_four_excluded(**{"l-other": "Someone Else's Bulb"})
    to_move = fix.plan_scope(scope)
    out = fix.apply_scope(scope, to_move)
    assert out["lights"] == {
        "l-corner": "Living Room Corner",
        "l-ledge-c": "Ledge Center",
        "l-ledge-l": "Ledge Left",
        "l-ledge-r": "Ledge Right",
        "l-loft": "Loft Ceiling Uplight",
        "l-stand-1": "Standing Lamp 1",
    }
    assert out["excluded"] == {"l-other": "Someone Else's Bulb"}
    # untouched metadata survives
    assert out["written_at"] == scope["written_at"]
    assert out["source"] == scope["source"]


def test_plan_hue_excluded_lights_removes_his_four_case_insensitively():
    current = ["loft ceiling uplight", "Ledge Left", "Someone Else's Bulb",
              "LEDGE RIGHT", "Ledge Center"]
    assert fix.plan_hue_excluded_lights(current) == ["Someone Else's Bulb"]


def test_plan_hue_excluded_lights_is_a_no_op_when_none_of_his_four_present():
    current = ["Someone Else's Bulb"]
    assert fix.plan_hue_excluded_lights(current) == current


# ── full script: hue_scope.json half ────────────────────────────────────

def test_dry_run_writes_nothing_and_reports_the_plan(tmp_path, monkeypatch,
                                                      capsys):
    scope_path = tmp_path / "storage" / "spectra" / "hue_scope.json"
    _write(scope_path, _scope_with_four_excluded())
    raw = scope_path.read_bytes()
    assert _run(monkeypatch, tmp_path) == 0
    assert scope_path.read_bytes() == raw
    assert not (tmp_path / "storage" / "spectra" / "backups").exists()
    out = capsys.readouterr().out
    assert "4 bulb(s) to move" in out
    assert "Loft Ceiling Uplight" in out
    assert "dry run" in out


def test_apply_without_spectra_url_refuses_and_writes_nothing(tmp_path,
                                                               monkeypatch):
    scope_path = tmp_path / "storage" / "spectra" / "hue_scope.json"
    _write(scope_path, _scope_with_four_excluded())
    raw = scope_path.read_bytes()
    assert _run(monkeypatch, tmp_path, "--apply") == 2
    assert scope_path.read_bytes() == raw
    assert not (tmp_path / "storage" / "spectra" / "backups").exists()


def test_apply_with_spectra_url_moves_the_four_bulbs_and_backs_up(
        tmp_path, monkeypatch, capsys):
    scope_path = tmp_path / "storage" / "spectra" / "hue_scope.json"
    original = _scope_with_four_excluded()
    _write(scope_path, original)

    with _fake_house_settings(fix.BULB_NAMES) as (url, state, puts):
        assert _run(monkeypatch, tmp_path, "--spectra-url", url,
                   "--apply") == 0

    written = json.loads(scope_path.read_text())
    assert set(written["lights"]) >= {"l-loft", "l-ledge-l", "l-ledge-r",
                                      "l-ledge-c"}
    assert written["excluded"] == {}

    backups = list((tmp_path / "storage" / "spectra" / "backups").glob(
        "hue_scope-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == original

    assert state["hue_excluded_lights"] == []
    assert puts == [{"hue_excluded_lights": []}]

    out = capsys.readouterr().out
    assert "wrote" in out
    assert "PUT" in out


def test_apply_preserves_settings_names_outside_his_four(tmp_path,
                                                          monkeypatch):
    scope_path = tmp_path / "storage" / "spectra" / "hue_scope.json"
    _write(scope_path, _scope_with_four_excluded())
    initial = list(fix.BULB_NAMES) + ["Someone Else's Bulb"]
    with _fake_house_settings(initial) as (url, state, _puts):
        assert _run(monkeypatch, tmp_path, "--spectra-url", url,
                   "--apply") == 0
    assert state["hue_excluded_lights"] == ["Someone Else's Bulb"]


def test_the_fix_is_idempotent(tmp_path, monkeypatch, capsys):
    scope_path = tmp_path / "storage" / "spectra" / "hue_scope.json"
    _write(scope_path, _scope_with_four_excluded())

    with _fake_house_settings(fix.BULB_NAMES) as (url, state, puts):
        assert _run(monkeypatch, tmp_path, "--spectra-url", url,
                   "--apply") == 0
        first_scope = scope_path.read_bytes()
        capsys.readouterr()

        assert _run(monkeypatch, tmp_path, "--spectra-url", url,
                   "--apply") == 0
        out = capsys.readouterr().out

    assert scope_path.read_bytes() == first_scope
    backups = list((tmp_path / "storage" / "spectra" / "backups").glob(
        "*.json"))
    assert len(backups) == 1, "a second, no-op run must not back up again"
    assert "already correct" in out
    assert len(puts) == 1, "the second run must not PUT an unchanged list"


def test_a_scope_with_no_matching_bulbs_is_left_alone(tmp_path, monkeypatch,
                                                       capsys):
    scope_path = tmp_path / "storage" / "spectra" / "hue_scope.json"
    already_fixed = {
        "lights": {"l-loft": "Loft Ceiling Uplight",
                  "l-ledge-l": "Ledge Left",
                  "l-ledge-r": "Ledge Right",
                  "l-ledge-c": "Ledge Center"},
        "excluded": {},
    }
    _write(scope_path, already_fixed)
    raw = scope_path.read_bytes()

    with _fake_house_settings([]) as (url, state, puts):
        assert _run(monkeypatch, tmp_path, "--spectra-url", url,
                   "--apply") == 0

    assert scope_path.read_bytes() == raw
    assert not (tmp_path / "storage" / "spectra" / "backups").exists()
    assert puts == []
    out = capsys.readouterr().out
    assert "already correct" in out


def test_a_missing_hue_scope_file_is_reported_not_raised(tmp_path,
                                                          monkeypatch,
                                                          capsys):
    with _fake_house_settings([]) as (url, _state, puts):
        assert _run(monkeypatch, tmp_path, "--spectra-url", url,
                   "--apply") == 0
    out = capsys.readouterr().out
    assert "no " in out and "hue_scope.json" in out
    assert puts == []


# ── HTTP failure modes ───────────────────────────────────────────────────

def test_unreachable_spectra_url_is_a_stated_fatal(tmp_path, monkeypatch):
    scope_path = tmp_path / "storage" / "spectra" / "hue_scope.json"
    _write(scope_path, _scope_with_four_excluded())
    with pytest.raises(SystemExit, match="could not reach"):
        _run(monkeypatch, tmp_path, "--spectra-url",
            "http://127.0.0.1:1", "--apply")


def test_a_failing_get_is_a_stated_fatal(tmp_path, monkeypatch):
    scope_path = tmp_path / "storage" / "spectra" / "hue_scope.json"
    _write(scope_path, _scope_with_four_excluded())
    with _fake_house_settings(fix.BULB_NAMES, fail_get=True) as (
            url, _state, _puts):
        with pytest.raises(SystemExit, match="refused to report"):
            _run(monkeypatch, tmp_path, "--spectra-url", url, "--apply")


def test_a_failing_put_is_a_stated_fatal_and_the_file_half_already_landed(
        tmp_path, monkeypatch):
    """The two halves write independently — a PUT failure must not be
    allowed to look like nothing happened when the file half already
    landed."""
    scope_path = tmp_path / "storage" / "spectra" / "hue_scope.json"
    _write(scope_path, _scope_with_four_excluded())
    with _fake_house_settings(fix.BULB_NAMES, fail_put=True) as (
            url, _state, _puts):
        with pytest.raises(SystemExit, match="refused the settings update"):
            _run(monkeypatch, tmp_path, "--spectra-url", url, "--apply")
    written = json.loads(scope_path.read_text())
    assert written["excluded"] == {}
