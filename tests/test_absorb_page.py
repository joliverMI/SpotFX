"""The Absorb Music page (/absorb — spectra/web/src/absorb/, phase 4 of
data/absorb-music-plan/report.md).

`scripts/check_absorb_page.mjs` transpiles the page's own words
(absorbSummary.ts) and mounts the REAL page under jsdom against a recording
fake of SpotFX's /api/absorb routes: the three cards and their counts, the
head-success rate, force recapture's meaning, every control's route and
body (Start asks first; an album link writes nothing), and the six help
topics each linked from the page. This test runs it so the proof fires on
every full test run.

Skipped (not failed) when the frontend toolchain isn't installed — the
same posture as tests/test_timeline_touch_pan.py. The script itself skips
its mounted half (only) when the dev-only jsdom is absent.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_absorb_page.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in spectra/web) not installed",
)
def test_absorb_page_shows_the_run_and_every_control_reaches_its_route():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"check_absorb_page.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
