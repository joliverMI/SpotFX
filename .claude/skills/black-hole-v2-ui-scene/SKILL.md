---
name: black-hole-v2-ui-scene
description: >
  The "Black Hole V2 UI" SPECTRA scene — a separate, structurally THINNER
  scene than Black Hole V2: its `blackhole` entry targets the Particles
  device category (not Matrix/crystal-mapper), with `blackhole1d` on
  Strips and `power` on Singles, and far fewer flare kinds. Load before
  editing this scene's own bands/kinds/colour preference; load the
  blackhole-effect skill first for the effect's code-level semantics.
---

# Black Hole V2 UI (scene)

A SEPARATE scene id from "Black Hole V2", and NOT a twin of it. Its real
shape, read live 2026-09-16 (verify against `GET /spectra/api/scenes` —
this drifts):

- Matrix-slot entry: `blackhole` targeting the **Particles** category,
  where Black Hole V2 targets **Matrix**;
- Strips: `blackhole1d`; Singles: `power`;
- flare kinds: Dice Re-roll, Colour Jump, two flare gains and Colour Rotate
  & Back — none of Black Hole V2's "Flare patch" kinds, no reverse kind,
  no blob rush.

`scripts/set_scene_colorset_preference.py`'s own docstring, verbatim:
"'Black Hole V2 UI' is structurally thinner than its sibling — worth
reading before assuming it's an equal, fired scene rather than a
work-in-progress: it targets a Particles device entry where 'Black Hole V2'
targets Matrix, it carries noticeably fewer flare kinds once loaded, and
nothing outside scenes.json (no scene id search anywhere else in storage)
references it." He was told this and still had its colour-set preference
set to `"dark"` alongside Black Hole V2, Fireworks V2 and Dancers V2.

## What carries over from the blackhole-effect skill, and what does not

- **Carries over — code-level param semantics.** They live in the effect
  module regardless of which device category runs it: `reverse`'s real-
  `bool` coercion for any toggle-targeting kind, the accent params
  (`blackhole.horizon_color`, `power.sparks_color` force-written black
  unless the entry authors them), the charge/lull/drop state machine and
  its orphan-crash rule.
- **Likely does NOT carry over — crystal-mapper geometry.** The hex-grid
  spawn radius, `HEX_FILL_RADIUS` and "measure darkness over real cells"
  notes are about the Matrix `crystal-mapper` virtual. Check which device
  actually backs the Particles category before applying any of them here.
- **Does not carry over — Black Hole V2's band notes.** A reverse-kind or
  "Flare patch" observation from the sibling scene has nothing to attach
  to here. Don't assume an edit to one scene's bands applies to the other.

The raw-JSON-dict rule for script edits still applies (load the raw dict,
mutate one key, never round-trip through `SceneV2`/`scene_store.save()` —
see the black-hole-v2-scene skill and AGENTS.md).

## Sonic reach

Scene settings and flare kinds only via the scene console — never the
device entries.

## Executable proofs

None scene-specific — a named gap, which is why this scene's manifest entry
lists no trigger files. The `check_blackhole_*.py`/`test_blackhole_*.py`
corpus measures the effect (mostly on crystal-mapper geometry) and belongs
to the blackhole-effect skill alone. If this scene ever needs its own
check or migration, register it under this scene's own key in
`EFFECT_SCENE_MAP.json`.
