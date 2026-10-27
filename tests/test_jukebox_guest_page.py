"""The Jukebox's guest page (spectra/web/src/guest/, the plan's PR 2.1).

Two proofs, run here so they fire on every full test run:
  * `scripts/check_jukebox_guest_logic.mjs` — the page's pure rules (the
    strip's words, the banner once per change, Android-only buzzing after a
    tap, the Home Screen hint on iPhones and iPads, the tabs);
  * `scripts/render_jukebox_guest.py` — the BUILT page through the real
    guest app into SpotFX's real guest routes, on iPhone SE / 15 / Pro Max
    and Galaxy S25+ with their safe areas: no sideways scroll or clipped
    text, every target ≥ 44 px, the votes and the strip on screen without
    scrolling, first visit to a vote in two taps, no page or CSP error. It
    plants a problem first and fails if its own checks miss it.

Skipped (not failed) when the frontend toolchain or Chromium isn't here —
the same posture as tests/test_jukebox_editor.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "spectra" / "web"
ESBUILD = WEB / "node_modules" / ".bin" / "esbuild"
VITE = WEB / "node_modules" / ".bin" / "vite"
TOOLCHAIN = pytest.mark.skipif(not ESBUILD.exists() or shutil.which("node") is None,
                               reason="frontend toolchain (node + esbuild in spectra/web) not installed")


@TOOLCHAIN
def test_guest_page_rules():
    r = subprocess.run(["node", str(REPO / "scripts" / "check_jukebox_guest_logic.mjs")], cwd=REPO,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


@TOOLCHAIN
def test_guest_page_renders_on_four_phones():
    sys.path.insert(0, str(REPO / "scripts"))
    from check_ui_fidelity import find_chrome
    if find_chrome() is None:
        pytest.skip("no Chromium to render with")
    build = subprocess.run([str(VITE), "build", "--config", "vite.guest.config.ts", "--logLevel", "error"],
                           cwd=WEB, capture_output=True, text=True, timeout=180)
    assert build.returncode == 0, f"the guest page didn't build:\n{build.stdout}\n{build.stderr}"
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "render_jukebox_guest.py")], cwd=REPO,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0 and "PASS" in r.stdout and "SKIP" not in r.stdout, f"{r.stdout}\n{r.stderr}"
