"""Absorb-then-queue's screens (phase 4 PR 4.3 of data/jukebox-plan/report.md):
the Absorbing tab on /jukebox and the guest page's "learning" line.

`scripts/check_jukebox_absorbing.mjs` drives the words (jukeboxLearning.ts and
the guest page's logic.ts, pure) and mounts the REAL tab under jsdom against a
recording fake of SpotFX's /api/jukebox routes: the song being learned with
its progress, the waiting songs with the server's own estimates, the parked
one with the lane's reason, and the three buttons posting exactly the
engine's routes. Skipped (not failed) when the frontend toolchain isn't
installed; the script itself skips its mounted half when the dev-only jsdom
is absent.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_jukebox_absorbing.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in spectra/web) not installed",
)
def test_absorbing_tab_and_guest_learning_line():
    result = subprocess.run(["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True,
                            timeout=180)
    assert result.returncode == 0, (
        f"check_jukebox_absorbing.mjs failed:\n{result.stdout}\n{result.stderr}")
