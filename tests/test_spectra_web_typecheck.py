"""Guard: spectra/web must type-check.

Born 2026-10-07 — a help-content edit (PR #368) landed unescaped
apostrophes inside single-quoted TypeScript string literals in
spectra/web/src/help/helpContent.ts, which `tsc` rejects as a syntax
error. Nothing in the repo's own test run caught it before this: there
was no pytest exercising the frontend's type-check at all, only
developer-run `.mjs` check scripts for individual features. This test
closes that gap directly rather than adding a feature-specific one.

Skipped (not failed) when `spectra/web/node_modules` hasn't been
installed — the same posture every `.mjs` check script in this repo
already takes toward an un-provisioned frontend toolchain — so this
never blocks a backend-only environment, but fires in the ordinary dev
and CI environment where `npm install` has already run.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB_DIR = REPO / "spectra" / "web"
TSC = WEB_DIR / "node_modules" / ".bin" / "tsc"


@pytest.mark.skipif(not TSC.exists(), reason="spectra/web/node_modules not installed")
def test_spectra_web_type_checks_cleanly():
    result = subprocess.run(
        [str(TSC), "--noEmit"],
        cwd=WEB_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "spectra/web failed to type-check (tsc --noEmit):\n"
        f"{result.stdout}\n{result.stderr}"
    )
