"""The Home page's RMS bands use the same scale multipliers as the Timeline
page.

The Admiral, 2026-10-25: "I don't like the scalings of all the rms values
on the home page. Match it to what I have right now in the timeline
graph." `spectra/web/src/timeline/BuilderPage.tsx` seeds its sticky
`scales` state (Total/Bass/Mid/High RMS multipliers) from the SpotFX
settings `shape_scale_total`/`_bass`/`_mid`/`_high`, and persists hand
adjustments to the same `spotfx.builder.v1.scales` localStorage key.
`spectra/web/src/home/HomeTimeline.tsx` used to hardcode
`{ total: 1, bass: 1, mid: 1, high: 1 }`, so the same song's RMS bands
drew at a different height on the Home page than on the Timeline page.
`spectra/web/src/lib/shapeScales.ts` is the one seed function both pages'
`useSticky('scales', ...)` calls now share; `scripts/
check_home_rms_scaling.mjs` transpiles that pure module with esbuild and
drives it directly.

Skipped (not failed) when the frontend toolchain isn't installed — the
same posture as tests/test_timeline_follow_playhead.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_home_rms_scaling.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in spectra/web) not installed",
)
def test_home_rms_scale_seed_matches_the_timeline_pages_own_seed():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"check_home_rms_scaling.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "ALL OK" in result.stdout
