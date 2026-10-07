"""The device preview shows flares and transitions — his 2026-10-07 report,
"it seems to jump past them" — measured against the lights.

scripts/check_preview_flare_skip.py is the binding statement (what it runs,
the bar, and why the code before the fix is its own red control). It runs as
a SUBPROCESS, for the reason tests/test_light_field_checks.py gives: it
repoints the ownership record, the preview store and the fx host process-wide,
and starts real render threads, none of which may leak into this session.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_the_preview_shows_flares_and_transitions_the_lights_show():
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_preview_flare_skip.py")],
        cwd=REPO, capture_output=True, text=True, timeout=240)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "ALL PREVIEW FLARE/TRANSITION CHECKS PASSED" in out.stdout
