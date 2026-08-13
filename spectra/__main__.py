"""python -m spectra — the standalone entry the S3 process split will use.
Until then production serves SPECTRA mounted at /spectra inside the
spot-effects process (main.py)."""
from spectra.app import _standalone

_standalone()
