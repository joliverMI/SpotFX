"""THE ONE PHASE-ARM BUTTON (the Admiral, 2026-10-19: "add a button for
next drop, lull, and charge. make it one button that cycles through those
to reduce clutter. use thr icons and colors from the timeline for those
events").

Two executable specs, run here so both fire on every full test run:

  scripts/check_phase_arm_cycle.mjs            the pure rule — the cycle
      order, what one tap arms and disarms, and the fact the glyph and the
      three colours come from the Timeline's own definitions by IMPORT
      (no hex literal in the module), transpiled from the real
      spectra/web/src/lightshow/phaseArmCycle.ts.

  scripts/check_light_show_run_icon_buttons.mjs  the real RunView.tsx
      under jsdom: five icon buttons per set row, and the phase button
      genuinely cycling off → drop → lull → charge → off against canned
      /api/light-show answers (its own section SIX).

  scripts/check_timeline_light_show_markers.mjs  a phase arm is named in
      words for the drop-sequence legend and never drawn as a second
      marker on a moment that already has a shape (its own section SIX).
      That script had no pytest wrapper before this change; it gets one
      here so the section added to it actually fires on a full run — and
      its pre-existing High/Low sections come along for free.

The backend half — the arm kinds themselves firing on the right phase
start and disarming — is tests/test_light_show_arms.py section 5.

Skipped (not failed) when the frontend toolchain or the dev-only jsdom is
not installed — the posture of tests/test_light_show_pickers.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
NODE_MODULES = REPO / "spectra" / "web" / "node_modules"

_no_node = pytest.mark.skipif(
    not (NODE_MODULES / "esbuild").exists() or shutil.which("node") is None,
    reason="frontend toolchain (node, esbuild) not installed",
)
_no_jsdom = pytest.mark.skipif(
    not (NODE_MODULES / "esbuild").exists() or not (NODE_MODULES / "jsdom").exists()
    or shutil.which("node") is None,
    reason="frontend toolchain (node, esbuild, dev-only jsdom) not installed",
)


def _run(name: str, marker: str = "all passed") -> None:
    result = subprocess.run(
        ["node", str(REPO / "scripts" / name)], cwd=REPO,
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, f"{name} failed:\n{result.stdout}\n{result.stderr}"
    # a zero exit alone is not the proof — the script must say it ran
    assert marker in result.stdout, f"{name} did not report success:\n{result.stdout}"


@_no_node
def test_the_phase_cycle_rule_and_its_timeline_look():
    _run("check_phase_arm_cycle.mjs")


@_no_jsdom
def test_the_run_views_one_phase_button_cycles_through_all_three():
    _run("check_light_show_run_icon_buttons.mjs")


@_no_node
def test_a_phase_arm_is_named_for_the_legend_never_drawn_as_a_marker():
    _run("check_timeline_light_show_markers.mjs", marker="ALL CHECKS PASSED")
