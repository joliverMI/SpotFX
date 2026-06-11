"""SpotFX offline xcorr replay & benchmark harness.

Drives the EXACT production math (services.xcorr_core) and decision logic
(services.xcorr_sweep.SweepEvaluator) against frames synthesized from the
full-song WAVs retained in storage/audio_shapes/, with known injected
offsets/cuts/degradations — so algorithm changes can be measured instead of
guessed at.
"""
