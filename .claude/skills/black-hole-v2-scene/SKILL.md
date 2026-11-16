---
name: black-hole-v2-scene
description: >
  The "Black Hole V2" SPECTRA scene — Matrix `blackhole`, Strips
  `blackhole1d`, Singles `power` (`pulse` once
  scripts/migrate_singles_to_pulse.py runs). Load before editing this scene's
  flare bands/kinds, colour-set preference, or dwell curve. For the underlying
  effect's own params/invariants, load the blackhole-effect skill first — this
  skill is scene-level (bands, kinds, colour behaviour), not effect internals.
---

# Black Hole V2 (scene)

Load `blackhole-effect` first for the effect module itself. This skill is
about how THIS scene wires it: bands, flare kinds, colour preference.

**No scene-specific seed script exists** for this scene (predates the
`seed_<scene>_scene.py` convention) — its authored data lives only in the
live/gitignored `storage/spectra/scenes.json`. **Verify against the live
process (`GET /spectra/api/scenes`), never a worktree's local copy** — a
worktree's `storage/spectra/*.json` is whatever was copied in when it was
created, not proof of current state (docs/agents/spectra-engine-core.md's own warning, with a real
2026-08-17 incident where a stale copy made an already-shipped fix look
regressed).

## Known invariants from this scene's edit history

- **The strip's phase look is the shared strip phase layer's** (since
  2026-10-11, strip phase plan phase 2 — blackhole-effect skill, "The
  STRIP"): a tinted palette build with more blobs, black at the room's dark
  point, a drop that is bright on its mark with an intensity-sized burst.
  A report of "the strip goes white on the build" or "a grey dot in the
  lull" means the old module is running, not his tuning. Its strip-phase
  tunables live on this scene's Strips entry (Sonic:
  `set_scene_entry_param`).

- **Reverse-flare toggle**: `reverse` on `blackhole`/`blackhole1d` needs
  the real-`bool` coercion (see blackhole-effect skill) — a momentary/
  permanent kind targeting it silently did nothing before that fix. This
  scene attaches "Reverse Momentarily (500ms)"; Black Hole V2 UI does not
  (check live — kinds drift).
- **`preferred_color_set_mode`**: Black Hole V2 and Black Hole V2 UI were
  both set to `"dark"` preference by `scripts/
  set_scene_colorset_preference.py` (his ask: "black hole would prefer
  dark mode color sets"). If you touch this field with a script, load the
  RAW JSON dict and mutate only the one key — never round-trip through
  `SceneV2`/`scene_store.save()`, which silently re-migrates
  `param_patch`/`gain`/`reroll_dice`/`color_set_jump` into the newer
  `flare_kinds` shape on every scene it touches (docs/agents/sonic-and-colour.md's "Editing an
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

## Drops can switch INTO or OUT OF this scene (2026-10-08)

This scene is drop-switch-ready (its Matrix effect is in
`fx.device_model.CENTRE_BURST_EFFECTS`): once a scene has grown stale, a drop sequence
may hard-cut into this one ON the drop, with this scene's own drop firing
on the mark and adopting the outgoing pieces — or cut out of it the same
way. Nothing in this scene's data opts in or out; `spectra/services/
drop_switch.py` (and the drop-detection skill) is where the rule lives,
including the hand-off table row for this effect.

## Sonic reach

Sonic can create/rename/edit `FlareKind`s on this scene and its scalar
scene settings (entry blend, colour-journey pace, colour-set acceptance)
via the scene console — never the Matrix/Strips device entries themselves
(out of scope by design). See docs/agents/sonic-and-colour.md's "Sonic's scene/flare authority"
section for the full boundary.

## Executable proofs

`scripts/add_word_shapes.py` + `tests/test_add_word_shapes.py` (the Words
band below) are this scene's FIRST manifest trigger files — nothing else
scene-specific exists, which is the named gap this entry used to record in
full. The blackhole-effect skill's
proof corpus (`scripts/check_blackhole_*.py`, `tests/test_blackhole_*.py`)
measures the EFFECT, not this scene's data, and belongs to that skill alone.
If you add a scene-level migration/seed script for this scene, add it to
`EFFECT_SCENE_MAP.json`'s `scenes.black-hole-v2-scene.files` in the same
change. It does NOT automatically belong to Black Hole V2 UI as well: that
is a structurally different, thinner scene (a Particles-category
`blackhole` entry, far fewer flare kinds), so a script scoped to this
scene's data does not apply there without checking.

## Words band — one `Word Shape` kind, full range (Word Shapes W2.5)

`scripts/add_word_shapes.py` is the one thing that turns Word Shapes on in
his room. On this scene it writes exactly two keys:

- `flare_kinds` gains ONE entry, `{"name": "Word Shape", "type":
  "word_shape", ...}` — offset 0, no minimum intensity, enabled. The type
  carries no jump/params/gain/hold_ms of its own: the five timings are ROOM
  settings (`word_shape_form_slow_s` / `_form_fast_s` / `_hold_min_s` /
  `_hold_max_s` / `_release_ratio`, Sonic-tellable), Energy-paced per word,
  and the shape itself is the sung label's.
- `responses["word"]` is CREATED as ONE full-range band `[0.0, 1.0)`
  attaching that kind at ×1.0 in its own implicit lane (`kind_lanes`
  empty), every other field at the model's default.

**THE BAND IS THE SWITCH** (his Q6 A: shapes are on "for every song once a
scene's Words band has a Word Shape kind attached"). A scene with no Words
section is `no_class` and writes nothing. FULL RANGE because
`scene_response.words_band_draws` is asked at PLAN time whether the showing
scene's Words section covers THIS Energy with an enabled `word_shape` kind
— a band stopping short of 1.0 would silently hand the loudest words back
to the colour path. **No colour kind is pooled beside it**: his Q5 A allows
one and a Words band is an ordinary `ResponseSpec`, but he did not ask for
one and it is his to add from the Scenes page.

**UNDO, and why a re-run is not one.** Plan §7: the kind's power button
switches it off on this scene, detaching it from the band does the same,
and `--revert` removes both from all six. Each of the first two leaves data
the script did not write, so a re-run REFUSES rather than undoing his undo
— an existing `Word Shape` kind is left exactly as authored (a switched-off
one is never re-enabled) and a Words section that differs aborts with the
difference printed. Raw-dict patch, never `scene_store.save()`; dry-run by
default; `--apply` backs the store up to
`storage/spectra/backups/scenes-word-shapes-<stamp>.json` first and
re-reads the written file to verify nothing else moved.

**WHO RUNS IT, AND WHEN:** DJ, at W3, only after the W1 code is deployed
and `spectra.service` restarted (an older process cannot load a `word`
response class). The tuning gate (`docs/ADDING_EFFECTS.md`) puts his eye
before a shape is live in a song, and his first look is the Words preview,
which needs the kind declared. Proof: `tests/test_add_word_shapes.py`
(fixture store only — never live storage). The shape library, the told keys
and the engine contract are the `word-shapes` skill.
