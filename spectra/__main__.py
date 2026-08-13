"""python -m spectra — SPECTRA's own process (the S3 process split, live).
Production runs this under spectra.service; the spot-effects app reverse-
proxies /spectra/* here so the port-8000 addresses survive verbatim."""
from spectra.app import _standalone

_standalone()
