---
name: dancers-v2-scene
description: >
  The "Dancers V2" SPECTRA scene — Matrix `dancer`, Strips `orbits1d`
  (not a Dancer-specific strip effect), Singles `power`. Load before
  editing this scene's flare bands/kinds, GIF pose/style selection, or
  flame-burst thresholds. Load the dancer-effect skill first (and
  led-gif-assets for asset authoring specifically).
---

# Dancers V2 (scene)

Load `dancer-effect` first (and `led-gif-assets` for GIF pose/style
authoring specifically — that skill covers the tooling side, this one
covers the scene's own bands/kinds).

`scripts/seed_dancers_scene.py` and `scripts/seed_dancer_event.py` are
this scene's own seed scripts. `scripts/smoke_dancer_params.py` is a
quick param-shape smoke test, not a behavioural proof.

## Its Strips entry is `orbits1d`, same as Squiggles V2 and Pacman V2

This scene has no Dancer-specific strip effect — check the orbits-effect
skill before assuming a Strips-side report is about the Dancer effect at
all.

## Colour-set preference

Set to `"dark"` by `scripts/set_scene_colorset_preference.py` alongside
Black Hole V2/UI and Fireworks V2 — see the additive-match rule in
AGENTS.md's "per-scene colour-set PREFERENCE" section before assuming a
preference change could ever leave this scene with zero eligible sets.

## The saturating-threshold flame defect is FIXED for this scene's beat-
   burst path, not for all four flame sources

`burst_threshold` (`dancer.py:1149`) is fixed; the flourish payoff burst
and the six `_impact_flames` stunt moments are ungated and no threshold
value silences them. See the dancer-effect skill's full note before
promising a flame-silencing fix will be complete.

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

Shares the dancer-effect skill's proof corpus
(`scripts/check_dancer_flames_off.py`, `tests/test_dancer_flames_off.py`)
plus `scripts/smoke_dancer_params.py`, `scripts/seed_dancer_event.py`.
Named gap: no check proves this scene's own band attachments end to end.
