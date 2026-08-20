"""Regression proof for the crash that reverted PR #142 (AGENTS.md's
light-mode-fix-import-crash entry, revert PR #145):

    File "spectra/services/drift_conductor.py", line 261, in __init__
        or room_controls.load_room_controls)
    AttributeError: 'NoneType' object has no attribute 'load_room_controls'

The feature itself (tests/test_light_mode_bg_clear.py) passed a full green
suite and a real-data proof script — and still could not start, because
DriftConductor.__init__ resolved `room_controls.load_room_controls` EAGERLY,
and spectra/services/engine.py constructs `conductor = DriftConductor(...)`
at MODULE IMPORT TIME. Every test and check script happened to import
modules in an order where `room_controls` was already resolved, so nothing
in the suite ever exercised the one path that matters: the service booting
the way systemd boots it (`python -m spectra`, i.e. import spectra.app
before spectra.services.engine's singletons have been constructed by
anyone else first).

A same-process test cannot prove this: by the time ANY test in this suite
runs, pytest has already collected dozens of other test modules that
themselves `import spectra.services.room_controls` (directly or via
spectra.services.engine) — sys.modules caches the result, so importing it
"first" from inside a normal test proves nothing about import ORDER. Each
check below runs spectra.app's import chain in a genuinely fresh
interpreter (subprocess), the same class of proof tests/test_process_split.py
already uses for the analogous "which interpreter pulls in what" question.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_engine_module_constructs_its_singletons_from_a_clean_interpreter():
    """The exact module the traceback named: spectra.services.engine builds
    `conductor = DriftConductor(...)` and `responses = ResponseEngine(...)`
    at import time. A fresh interpreter that imports ONLY this module, with
    nothing else having touched spectra.services.room_controls first, is
    the most direct reproduction of the original crash's import order."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import spectra.services.engine as e; "
         "assert e.conductor is not None; "
         "assert e.responses is not None; "
         "print('OK')"],
        cwd=REPO, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip().splitlines()[-1] == "OK"


def test_spectra_app_imports_cleanly_the_way_the_service_boots():
    """spectra/__main__.py (what `python -m spectra` runs) is exactly
    `from spectra.app import _standalone; _standalone()`. _standalone()
    itself starts a real uvicorn server, which a unit test must not do —
    but every module-level import spectra.app pulls in (including the
    whole spectra.services.engine chain the crash lived in) already runs
    before _standalone() is ever called, so importing spectra.app alone,
    from a clean interpreter, is the equivalent import chain the service
    boot goes through. This is the check that would have caught PR #142:
    it crashed on every real start, and this is the only kind of test in
    the whole suite that actually starts the service's import chain cold."""
    out = subprocess.run(
        [sys.executable, "-c", "import spectra.app; print('OK')"],
        cwd=REPO, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip().splitlines()[-1] == "OK"
