"""Burn-in safety for the TV app's Attract screen (spectra/web/src/tv/burnIn.ts,
data/tv-display-plan/plan.html PR 1.5, §2.4).

Runs scripts/check_tv_burnin.mjs, which transpiles the real module with
esbuild and samples the drift/QR/card-rotation arithmetic over simulated
time — no DOM, no browser.

Skipped (not failed) when the frontend toolchain isn't installed — the
same posture as tests/test_show_cue_flags.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_tv_burnin.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in spectra/web) not installed",
)
def test_tv_burnin_safety():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"check_tv_burnin.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "all checks passed" in result.stdout
