"""The Light Show BUILDER upgrade (spectra/web/src/lightshow/: SortableList,
StepCard, builderOps) — the Admiral, 2026-10-11: the legacy SpotFX editor's
drag-and-drop ordering, collapsibility and copy, plus sets that run other
sets.

`scripts/check_light_show_builder.mjs` mounts the REAL LightShowPage.tsx
under jsdom (only fetch and ../queries stood in) and drives collapse/expand,
a finger drag, duplicate, copy/paste across sets, Copy set → Paste as new
set, the "Run another set" picker's cycle exclusion, the called-steps view
and the delete warning; this test runs it so the proof fires on every full
run.

Skipped (not failed) when the frontend toolchain or the dev-only jsdom isn't
installed — the posture of tests/test_spectra_web_typecheck.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_light_show_builder.mjs"
NODE_MODULES = REPO / "spectra" / "web" / "node_modules"


@pytest.mark.skipif(
    not (NODE_MODULES / "esbuild").exists() or not (NODE_MODULES / "jsdom").exists()
    or shutil.which("node") is None,
    reason="frontend toolchain (node, esbuild, dev-only jsdom) not installed",
)
def test_light_show_builder_drags_collapses_copies_and_references():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"check_light_show_builder.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "all passed" in result.stdout
