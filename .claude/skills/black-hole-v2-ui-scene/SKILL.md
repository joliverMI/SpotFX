---
name: black-hole-v2-ui-scene
description: >
  The "Black Hole V2 UI" SPECTRA scene — a second, distinct scene id
  binding the same blackhole/blackhole1d/power effect shape as Black Hole
  V2. Load before editing this scene's own bands/kinds/colour preference;
  load the blackhole-effect skill first for the underlying effect, and
  the black-hole-v2-scene skill for the sibling scene's own notes (most
  of what's known applies to both, since they can't be structurally told
  apart by the tooling that exists today).
---

# Black Hole V2 UI (scene)

A SEPARATE scene id from "Black Hole V2" — same effect shapes
(`blackhole` on Matrix, `blackhole1d` on Strips, `power` on Singles), but
its own bands/kinds/curves live independently in
`storage/spectra/scenes.json`. Treat it as its own scene: don't assume an
edit to one scene's bands also applies to the other.

**Everything in the `black-hole-v2-scene` skill's "Known invariants" list
applies here too** (reverse-kind coercion, accent params on
`horizon_color`/`sparks_color`, the raw-JSON-dict script-editing rule, the
permanent-reverse-sticks-baseline shape) — read that skill in full; this
one exists only because it is a genuinely separate scene id in his room,
not because the mechanics differ.

## The known imprecision, named

No script or test in this repo can currently tell "Black Hole V2" changes
from "Black Hole V2 UI" changes apart — both are attributed to the same
`check_blackhole_*.py`/`test_blackhole_*.py` trigger set in
`EFFECT_SCENE_MAP.json`. If a future change is genuinely scoped to only
one of the two scenes, verify against the live `GET /spectra/api/scenes`
(never a worktree's stale local copy) and update ONLY the scene skill that
actually changed — don't assume the manifest's duplication means both
always need touching, only that the CHECK can't tell them apart yet.

## Sonic reach

Same boundary as Black Hole V2 — scene settings and flare kinds only,
never the device entries.

## Executable proofs

Shares the blackhole-effect skill's proof corpus — a named gap for a
scene-specific script/test. Add one and register it under this scene's
own key in `EFFECT_SCENE_MAP.json` (not just the sibling's) if this scene
ever needs a distinguishing check.
