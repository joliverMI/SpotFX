"""THE DESIGN-FIDELITY GATE, as an ordinary test — so it fires on every
full run rather than only when someone remembers it.

`scripts/check_ui_fidelity.py` renders the Admiral-approved mockup frames
beside the live chrome (the repo's own mocked harness page) at his named
widths and asserts the measurable parts. Its own module docstring says
why it exists; the short version is the audit's root cause, "nothing
compared a pixel to the mockup" — every acceptance check the UI declutter
PRs added passed on the build he called "much worse than I remember".

It SKIPS cleanly, saying why, when the machine cannot run it (no
Chromium, no `websockets`, no harness build). A skip here is a named hole,
never a false green: the script prints its reason and exits 0, and this
test surfaces that reason rather than swallowing it.

Output goes to a tmp dir, never the committed evidence folder — a test run
must not rewrite the images the PR links to.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_ui_fidelity.py"
HARNESS = REPO / "spectra" / "web" / "harness-dist" / "fidelity.html"


def test_the_live_chrome_still_matches_the_approved_mockups(tmp_path):
    if not HARNESS.is_file():
        # The harness is a build artefact (gitignored), exactly like
        # spectra/web/dist — see its own vite config. Name the one command
        # that produces it rather than failing on a missing build.
        import pytest
        pytest.skip(
            "spectra/web/harness-dist is not built — run:\n"
            "  cd spectra/web && npx vite build --config vite.harness.config.ts")
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--out", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    out = proc.stdout + proc.stderr
    if "skipping this check" in out:
        import pytest
        pytest.skip(out.strip().splitlines()[-1])
    assert proc.returncode == 0, out
    assert "PASS" in out, out
