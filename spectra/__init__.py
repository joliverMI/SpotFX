"""SPECTRA — the merged-program app (separate from spot-effects by the
owner's architecture decision). Own scene model, tabbed editor, sequencer,
and (S2) parameter-evolution engine; shares the repo and the fx/ library.

Import discipline, load-bearing for the S3 process split: nothing under
spectra/ imports spot-effects runtime internals (models.state, services.*,
api.*, routers.*). Allowed imports: fx/ (the shared library), stdlib,
third-party. Music/state inputs arrive via the S2 read-only bridge; until
then SPECTRA degrades to neutral intensity 0.5 (stated behavior).
"""
