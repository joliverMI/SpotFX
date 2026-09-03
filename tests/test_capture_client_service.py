"""THE CAMERA HOST AS A SERVICE — the offline half.

The end-to-end proof (the real unit, the real provisioning script, the real
client started by the unit's own ExecStart against a real server) is
`scripts/check_capture_client_service.py`, run from
`tests/test_light_field_checks.py`. This file holds what is better proven
deterministically and in-process: the configuration's own rules, the camera
host's presence record, and two STRUCTURAL properties that no behavioural
test can state as well — that the client cannot acquire room authority, and
that the shipped unit still says the things it has to say.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from spectra import config as scfg
from spectra.capture_client import config as client_config
from spectra.services import capture_health, mapping_refusals

REPO = Path(__file__).resolve().parent.parent
UNIT = REPO / "deploy" / "spectra-capture-client.service"
INSTALLER = REPO / "scripts" / "install_capture_client.sh"
CLIENT_PKG = REPO / "spectra" / "capture_client"


# ── the configuration ──────────────────────────────────────────────────────

def test_environment_declares_every_option_the_command_line_takes():
    """One env file is the whole configuration of a boot service, so a
    variable that exists only on the command line would be a setting nobody
    can declare in the file the unit reads."""
    got = client_config.from_environment({
        "SPECTRA_CAPTURE_URL": "http://spectra:8000/spectra",
        "SPECTRA_CAPTURE_DEVICE": "/dev/video2",
        "SPECTRA_CAPTURE_POSE": "the north shelf",
        "SPECTRA_CAPTURE_FPS": "3",
    })
    assert got == {"url": "http://spectra:8000/spectra",
                   "device": "/dev/video2",
                   "pose_name": "the north shelf", "fps": 3.0}


def test_an_empty_variable_is_unset_not_a_value():
    """A commented-out line and an empty one must mean the same thing, or a
    half-edited env file makes a camera try to open the device ''."""
    assert client_config.from_environment({"SPECTRA_CAPTURE_DEVICE": "  "}) == {}


def test_a_malformed_number_refuses_by_name_rather_than_defaulting():
    with pytest.raises(client_config.ConfigError) as exc:
        client_config.from_environment({"SPECTRA_CAPTURE_FPS": "fivve"})
    assert "SPECTRA_CAPTURE_FPS" in str(exc.value) and "fivve" in str(exc.value)


def test_the_synthetic_switch_is_a_boolean_and_defaults_off():
    assert client_config.from_environment({}) == {}
    assert client_config.from_environment(
        {"SPECTRA_CAPTURE_SYNTHETIC": "1"}) == {"synthetic": True}
    assert client_config.from_environment(
        {"SPECTRA_CAPTURE_SYNTHETIC": "no"}) == {"synthetic": False}


def test_help_names_every_variable_so_the_program_is_the_reference():
    text = client_config.env_help()
    for var, _dest, _help in client_config.ENV_VARS:
        assert var in text


# ── the camera host's presence record ──────────────────────────────────────

class _FakeLock:
    def __init__(self, locked=True, camera_error=""):
        self.locked = locked
        self.camera_error = camera_error


class _FakeVerdict:
    def __init__(self, verdict="ok"):
        self._v = verdict

    def as_dict(self):
        return {"verdict": self._v, "detail": "measured"}


class _FakeSession:
    def __init__(self, host="camera-pi", pose_name="the north shelf",
                 version="1.0", verdict=None, locked=True, camera_error=""):
        self.id = "sess-1"
        self.pose_id = "pose-1"
        self.hello = {"client": "spectra-capture-client", "host": host,
                      "client_version": version, "pose_name": pose_name,
                      "platform": {"system": "Linux", "machine": "aarch64"},
                      "camera": {"kind": "v4l2", "device": "/dev/video0"}}
        self.lock = _FakeLock(locked, camera_error)
        self.lever_verdict = verdict


def test_never_seen_is_a_different_answer_from_absent(tmp_path):
    scfg.CAPTURE_HEALTH_FILE = tmp_path / "h.json"
    got = capture_health.health(None)
    assert got["state"] == "never" and got["present"] is False
    assert "has ever connected" in got["sentence"]
    assert got["client"] is None


def test_absence_names_the_machine_its_build_and_how_long(tmp_path):
    """THE WHOLE POINT. A camera host that is off and one that never existed
    used to produce the identical silence."""
    scfg.CAPTURE_HEALTH_FILE = tmp_path / "h.json"
    sess = _FakeSession()
    capture_health.note_session(sess, event="hello", now_ms=1_000_000.0)
    got = capture_health.health(None, now_ms=1_000_000.0 + 7200_000.0)
    assert got["state"] == "absent" and got["present"] is False
    assert got["absent_for_s"] == pytest.approx(7200.0)
    for word in ("camera-pi", "the north shelf", "1.0", "hours ago"):
        assert word in got["sentence"], got["sentence"]


def test_presence_reads_the_live_session_not_the_record(tmp_path):
    scfg.CAPTURE_HEALTH_FILE = tmp_path / "h.json"
    sess = _FakeSession()
    capture_health.note_session(sess, event="hello")
    live = capture_health.health(sess)
    assert live["present"] is True and live["state"] == "present"
    assert live["client"]["host"] == "camera-pi"
    assert live["client"]["version"] == "1.0"
    assert live["client"]["platform"]["machine"] == "aarch64"


def test_one_row_per_machine_however_many_connections(tmp_path):
    scfg.CAPTURE_HEALTH_FILE = tmp_path / "h.json"
    for i in range(5):
        capture_health.note_session(_FakeSession(), event="hello",
                                    now_ms=1000.0 * i)
    rows = capture_health.load()
    assert len(rows) == 1
    assert rows[0]["sessions"] == 5


def test_a_lever_verdict_outlives_the_connection_that_earned_it(tmp_path):
    """A morning reader wants what this camera last proved about its own
    lever. The verdict's cache is the session object, deliberately, so a
    fresh connection carries none — the record has to hold it."""
    scfg.CAPTURE_HEALTH_FILE = tmp_path / "h.json"
    capture_health.note_session(
        _FakeSession(verdict=_FakeVerdict("no_response")), event="lever",
        now_ms=1000.0)
    capture_health.note_session(_FakeSession(verdict=None), event="hello",
                               now_ms=2000.0)
    row = capture_health.load()[0]
    assert row["lever"]["verdict"] == "no_response"
    assert row["lever_seen_ms"] == 1000.0, "and it keeps its OWN stamp"


def test_the_record_is_bounded(tmp_path):
    scfg.CAPTURE_HEALTH_FILE = tmp_path / "h.json"
    for i in range(capture_health.MAX_CLIENTS + 6):
        capture_health.note_session(_FakeSession(host=f"host-{i}"),
                                    event="hello", now_ms=1000.0 * i)
    assert len(capture_health.load()) == capture_health.MAX_CLIENTS


def test_a_camera_error_is_carried_into_the_morning(tmp_path):
    scfg.CAPTURE_HEALTH_FILE = tmp_path / "h.json"
    capture_health.note_session(
        _FakeSession(locked=False, camera_error="/dev/video0 does not exist"),
        event="hello")
    assert capture_health.load()[0]["camera_error"] == \
        "/dev/video0 does not exist"


def test_an_unwritable_record_never_takes_a_session_down(tmp_path):
    """Reporting must not be able to break the thing it reports on."""
    scfg.CAPTURE_HEALTH_FILE = tmp_path / "no-such-dir" / "\0bad" / "h.json"
    capture_health.note_session(_FakeSession(), event="hello")   # must not raise


def test_health_gates_nothing():
    """It reports; the run's refusal is `mapping_session.lock_refusal`'s and
    `NO_SESSION`, unchanged. A reporting surface that could refuse a run
    would be a second implementation of the exposure gate — so neither
    public entry point may raise, and the module may not reach a run's
    machinery at all."""
    import ast
    src = (REPO / "spectra" / "services" / "capture_health.py").read_text()
    tree = ast.parse(src)
    for fn in ("note_session", "health"):
        node = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == fn)
        assert not [n for n in ast.walk(node) if isinstance(n, ast.Raise)], \
            f"{fn} can raise into the thing it reports on"
    # The docstring NAMES the gate it is not (`lock_refusal`, `NO_SESSION`)
    # on purpose, so the scan below is over executable code only.
    code = "\n".join(ast.unparse(n) for n in tree.body
                     if not (isinstance(n, ast.Expr)
                             and isinstance(n.value, ast.Constant)))
    for forbidden in ("run_abort", "fx_seam", "lock_refusal", "NO_SESSION",
                      "light_ownership", "capture_runs", "room_mapping"):
        assert forbidden not in code, forbidden
    assert "gates nothing" in src or "It gates nothing" in src or \
        "it does not gate" in src, \
        "and the module says so where somebody editing it will read it"


# ── the client acquires no room authority, structurally ────────────────────

def test_the_capture_client_cannot_take_the_room():
    """NEVER-TAKES-HIS-ROOM, as a property of what the package imports
    rather than a promise in a docstring. The client is a camera process: a
    device, a WebSocket, frames and lock read-backs. Nothing in it can reach
    a light, an ownership record, or a handover — and making it a boot
    service changed none of that."""
    forbidden = ("fx_seam", "light_ownership", "handover", "fx.devices",
                 "flare_preview_hold", "room_effects", "scene_compiler",
                 "drift_conductor", "ledfx")
    for path in sorted(CLIENT_PKG.glob("*.py")):
        body = path.read_text()
        for name in forbidden:
            assert name not in body, f"{path.name} mentions {name}"


def test_the_client_imports_nothing_from_the_server_side_of_spectra():
    """It ships to a machine that has only the client. An import of
    `spectra.services.*` would drag the server's whole dependency set onto a
    camera host — see requirements-capture-client.txt."""
    for path in sorted(CLIENT_PKG.glob("*.py")):
        for m in re.finditer(r"^\s*(?:from|import)\s+(spectra[\w.]*)",
                             path.read_text(), re.M):
            assert m.group(1).startswith("spectra.capture_client"), \
                f"{path.name} imports {m.group(1)}"


# ── the shipped unit still says what it has to say ─────────────────────────

def _unit_directives() -> dict:
    out = {}
    for line in UNIT.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def test_the_unit_restarts_always_and_never_gives_up():
    d = _unit_directives()
    assert d["Restart"] == "always"
    # A camera unplugged for an hour must find the session again when it is
    # plugged back in; a rate-limited unit would sit dead until a human ran
    # systemctl.
    assert d["StartLimitIntervalSec"] == "0"


def test_the_unit_starts_at_boot_and_reads_one_config_file():
    d = _unit_directives()
    assert d["WantedBy"] == "default.target"
    assert d["EnvironmentFile"].endswith("client.env")
    # NO `-` PREFIX: a missing configuration must stop the unit and name
    # itself, not start a client that guesses where SPECTRA lives.
    assert not d["EnvironmentFile"].startswith("-")


def test_the_unit_takes_no_arguments():
    """The environment file is the whole configuration. An argument in
    ExecStart would be a setting that lives in a file nobody edits."""
    assert _unit_directives()["ExecStart"].split() == \
        ["%h/.local/bin/spectra-capture-client"]


def test_the_unit_reaches_the_camera_and_nothing_else():
    d = _unit_directives()
    assert d["SupplementaryGroups"] == "video"
    assert d["DeviceAllow"] == "char-video4linux rw"
    assert d["ProtectSystem"] == "strict"
    assert d["NoNewPrivileges"] == "yes"


def test_the_unit_names_no_host_specific_path():
    """It ships verbatim to every machine, which is what makes
    `systemd-analyze verify` a check on the bytes that get installed. Paths
    that differ per host live in the launcher the installer writes."""
    text = UNIT.read_text()
    body = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
    assert "/home/" not in body and "/usr/local" not in body


# ── the provisioning script's refusals ─────────────────────────────────────

def test_every_prerequisite_has_a_named_refusal_with_its_fix():
    """The once-ever ledger items became one script's named checks; a check
    that refuses without saying how to fix it sends somebody searching."""
    text = INSTALLER.read_text()
    for prerequisite, fix in (("ffmpeg", "apt install ffmpeg"),
                              ("v4l2-ctl", "v4l-utils"),
                              ("python3", "python3-venv"),
                              ("video", "usermod -aG video"),
                              ("linger", "enable-linger")):
        assert prerequisite in text and fix in text, prerequisite


def test_provisioning_never_installs_the_servers_requirements():
    """`requirements.txt` carries compiled wheels a camera host has no use
    for and, on ARM, may have to build from source."""
    text = INSTALLER.read_text()
    assert "requirements-capture-client.txt" in text
    assert not re.search(r"-r\s+\S*(?<!-client)/requirements\.txt", text)


def test_the_client_requirements_are_exactly_two():
    lines = [l.split("#")[0].strip()
             for l in (REPO / "requirements-capture-client.txt").read_text()
             .splitlines()]
    names = {re.split(r"[<>=!~\[]", l)[0].strip().lower() for l in lines if l}
    assert names == {"httpx", "websockets"}


def test_absence_wording_distinguishes_never_from_gone():
    """`mapping_refusals` owns both sentences, so no surface composes a
    second one — and neither of them is a refusal."""
    never = mapping_refusals.client_never_seen()
    gone = mapping_refusals.client_absent("camera-pi", version="1.0",
                                          absent_for_s=45.0)
    assert never != gone
    assert "has ever connected" in never and "camera-pi" in gone
    assert "45s ago" in gone


# ── the pip predicate: a Debian-shaped refusal, before any write ───────────
# The failure this is written for: `import venv` succeeds on Debian while
# `ensurepip` (python3-venv) is absent, so the old check passed and the run
# died with a raw `No module named pip` INSIDE the freshly built venv.

import os
import subprocess
import sys

APT_FIX = "sudo apt install -y python3-venv python3-pip"


def _shim(path: Path, refuse_arg: str) -> Path:
    """A python that behaves exactly like this one except for one module."""
    path.write_text(
        "#!/bin/sh\n"
        f'for a in "$@"; do [ "$a" = "{refuse_arg}" ] && exit 1; done\n'
        f'exec {sys.executable} "$@"\n'
    )
    path.chmod(0o755)
    return path


def _run_installer(tmp_path: Path, *args: str):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"))
    env.pop("SPECTRA_CAPTURE_VENV", None)
    env.pop("SPECTRA_CAPTURE_PYTHON", None)
    proc = subprocess.run(["bash", str(INSTALLER), "--check", *args],
                          capture_output=True, text=True, env=env)
    return proc, home


def test_a_python_that_cannot_seed_pip_refuses_by_name_before_any_write(tmp_path):
    py = _shim(tmp_path / "python-no-ensurepip", "ensurepip")
    proc, home = _run_installer(tmp_path, "--python", str(py),
                                "--url", "http://spectra:8000/spectra")
    assert proc.returncode == 1
    assert "ensurepip" in proc.stdout and APT_FIX in proc.stdout
    # NOTHING WAS WRITTEN: the refusal is collected before the install half.
    assert not list(home.rglob("*"))


def test_a_pipless_venv_is_refused_by_name_and_never_reused(tmp_path):
    venv = tmp_path / "half-made-venv"
    (venv / "bin").mkdir(parents=True)
    _shim(venv / "bin" / "python", "pip")
    proc, home = _run_installer(tmp_path, "--venv", str(venv),
                                "--url", "http://spectra:8000/spectra")
    assert proc.returncode == 1
    assert "has no pip in it" in proc.stdout
    # It NAMES the two-step fix and removes nothing itself.
    assert APT_FIX in proc.stdout and f"rm -rf {venv}" in proc.stdout
    assert (venv / "bin" / "python").exists()


def test_a_whole_python_passes_the_pip_checks(tmp_path):
    proc, _ = _run_installer(tmp_path, "--python", sys.executable,
                             "--url", "http://spectra:8000/spectra")
    assert "ensurepip" not in proc.stdout
    assert "has no pip in it" not in proc.stdout
