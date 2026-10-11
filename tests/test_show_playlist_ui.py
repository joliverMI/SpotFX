"""The Light Show's Playlists tab and playlist Run card
(spectra/web/src/lightshow/PlaylistView.tsx, PlaylistRunCard.tsx) — Show
Playlists, phase 1 (data/playlist-plan/report.md slice 1c).

`scripts/check_show_playlist_ui.mjs` mounts the REAL components under jsdom
(only window.fetch stood in) and drives Build (the Spotify playlist chips,
song cards, the four timing icons, copy / paste, the song search, Save,
Follow now, the Follow switch) and the Run card + banner (each step's
state, up next, Fire now / Skip / Stop); this test runs it so the proof
fires on every full run.

Skipped (not failed) when the frontend toolchain or the dev-only jsdom isn't
installed — the posture of tests/test_spectra_web_typecheck.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_show_playlist_ui.mjs"
NODE_MODULES = REPO / "spectra" / "web" / "node_modules"


@pytest.mark.skipif(
    not (NODE_MODULES / "esbuild").exists() or not (NODE_MODULES / "jsdom").exists()
    or shutil.which("node") is None,
    reason="frontend toolchain (node, esbuild, dev-only jsdom) not installed",
)
def test_show_playlists_tab_builds_and_the_run_card_follows():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"check_show_playlist_ui.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "all passed" in result.stdout
