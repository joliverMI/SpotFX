"""The Light Show editor's pickers are the shared searchable SearchSelect —
the Admiral, 2026-10-08: "make the drop downs for things like color
set/group and scene, etc, in the lightshow edit be searchable and match the
other ui elements that do this."

`scripts/check_light_show_pickers.mjs` mounts the REAL LightShowPage.tsx
under jsdom (only the data layer stood in) and drives every scene / colour
set or group / gradient / house mode / category / fixture picker and "+ Add a
step…" by typing; this test runs it so the proof fires on every full run.

Skipped (not failed) when the frontend toolchain or the dev-only jsdom isn't
installed — the posture of tests/test_spectra_web_typecheck.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_light_show_pickers.mjs"
NODE_MODULES = REPO / "spectra" / "web" / "node_modules"


@pytest.mark.skipif(
    not (NODE_MODULES / "esbuild").exists() or not (NODE_MODULES / "jsdom").exists()
    or shutil.which("node") is None,
    reason="frontend toolchain (node, esbuild, dev-only jsdom) not installed",
)
def test_light_show_pickers_are_searchable():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"check_light_show_pickers.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "all passed" in result.stdout
