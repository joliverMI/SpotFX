"""SpotFX stub for the fork's ledfx/sendspin package (not vendored).

Sendspin is LedFX's network audio-sync integration. SpotFX feeds audio
in-process, so the whole subsystem is stubbed to "unavailable" — the guarded
paths in fx/effects/audio.py then never activate.
"""

SENDSPIN_AVAILABLE = False
