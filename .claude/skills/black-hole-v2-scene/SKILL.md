---
name: black-hole-v2-scene
description: >
  The "Black Hole V2" SPECTRA scene — Matrix `blackhole`, Strips
  `blackhole1d`, Singles `power`. Load before editing this scene's flare
  bands/kinds, colour-set preference, or dwell curve. For the underlying
  effect's own params/invariants, load the blackhole-effect skill first —
  this skill is scene-level (bands, kinds, colour behaviour), not effect
  internals.
---

# Black Hole V2 (scene)

Load `blackhole-effect` first for the effect module itself. This skill is
about how THIS scene wires it: bands, flare kinds, colour preference.

**No scene-specific seed script exists** for this scene (predates the
`seed_<scene>_scene.py` convention) — its authored data lives only in the
live/gitignored `storage/spectra/scenes.json`. **Verify against the live
process (`GET /spectra/api/scenes`), never a worktree's local copy** — a
worktree's `storage/spectra/*.json` is whatever was copied in when it was
created, not proof of current state (AGENTS.md's own warning, with a real
2026-08-17 incident where a stale copy made an already-shipped fix look
regressed).

## Known invariants from this scene's edit history

- **Reverse-flare toggle**: `reverse` on `blackhole`/`blackhole1d` needs
  the real-`bool` coercion (see blackhole-effect skill) — a momentary/
  permanent kind targeting it silently did nothing before that fix.
- **`preferred_color_set_mode`**: Black Hole V2 and Black Hole V2 UI were
  both set to `"dark"` preference by `scripts/
  set_scene_colorset_preference.py` (his ask: "black hole would prefer
  dark mode color sets"). If you touch this field with a script, load the
  RAW JSON dict and mutate only the one key — never round-trip through
  `SceneV2`/`scene_store.save()`, which silently re-migrates
  `param_patch`/`gain`/`reroll_dice`/`color_set_jump` into the newer
  `flare_kinds` shape on every scene it touches (AGENTS.md's "Editing an
  existing SceneV2 by script" rule — this bit a real draft of that exact
  script).
- **Accent param**: `blackhole.horizon_color` and `power.sparks_color`
  (Singles) are both accent params — see each effect's own skill for the
  force-black-unless-authored rule before treating a stored colour value
  as his tuning.
- **The `reverse`/`spin_sign` distinction on this scene's bands**: check
  which kind (`Reverse Direction` permanent vs. a momentary reverse) is
  attached before assuming a "stuck reversed" report is a bug — a
  PERMANENT reverse kind moves the carried baseline, so a scene that
  attaches one to a mid/high-intensity band gets STUCK reversed by
  construction after the first flare, which is by design unless he says
  otherwise (this exact shape was found on STAR, not Black Hole — check
  this scene's own band attachments live before assuming either way).

## Sonic reach

Sonic can create/rename/edit `FlareKind`s on this scene and its scalar
scene settings (entry blend, colour-journey pace, colour-set acceptance)
via the scene console — never the Matrix/Strips device entries themselves
(out of scope by design). See AGENTS.md's "Sonic's scene/flare authority"
section for the full boundary.

## Executable proofs

Shares the blackhole-effect skill's proof corpus
(`scripts/check_blackhole_*.py`, `tests/test_blackhole_*.py`) since no
scene-specific script exists yet — a named gap. If you add a scene-level
migration/seed script for this scene, add it to
`EFFECT_SCENE_MAP.json`'s `scenes.black-hole-v2-scene.files` (and the UI
twin's) in the same change.
