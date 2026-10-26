"""Home's Drops panel, laid out (predrop plan step 1's acceptance: "a
headless-Chromium layout check at 390 / 800 / 1180 px — no sideways scroll,
three cards in a row at 1180, stacked on a phone, 44 px touch targets, the
toggle bar on one line at 390 px"). `scripts/check_home_drops_layout.py`
measures the REAL cards in the repo's own mocked harness page — with a
mouse and with a finger at each width, and in the wall kiosk's own 800 x
424 frame; this runs it so the proof fires on every full test run, with
its screenshots in a temp folder.

The harness is a build artefact (gitignored), exactly like the design-
fidelity gate's: with no build, no Chromium or no `websockets` the script
says SKIP and this test skips with the reason — a named hole, never a
silent pass.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_home_drops_layout.py"


def test_the_drops_panel_lays_out_at_390_800_and_1180(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--out", str(tmp_path)], cwd=REPO,
                            capture_output=True, text=True, timeout=300)
    if result.returncode == 0 and result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "PASS" in result.stdout
