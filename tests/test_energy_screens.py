"""The screens draw ENERGY the way the Admiral asked (2026-10-28, the Energy
plan; spectra/services/energy.py is the binding statement): the top bar's
lookup, the song strip's terrain at full height, and the audio shape's
Energy background filling the plot to its top. `scripts/
check_energy_screens.mjs` bundles the real modules with esbuild and drives
them with no browser.

Skipped (not failed) when the frontend toolchain isn't installed — the same
posture as tests/test_home_rms_scaling.py."""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_energy_screens.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in spectra/web) not installed",
)
def test_the_screens_draw_energy_full_height_in_song_time():
    result = subprocess.run(["node", str(SCRIPT)], cwd=REPO, capture_output=True,
                            text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL OK" in result.stdout
