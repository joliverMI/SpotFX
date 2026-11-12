# Visual comparisons — how the past explainers were built

The rule (SKILL.md step 4): a visual question is asked beside pictures of
the real look, today beside each proposal, never in words. This file is
the recipe record. Each past explainer lived in the fleet's data
directory (`data/<plan>/explainer.html`, outside this public repo); what
the repo keeps is the render scripts and harnesses below. Copy from the
nearest one rather than starting a rig from scratch — every rig trap
listed here cost a real session.

## Artifact constraints (every explainer, every round, the plan too)

He reviews on his tablet or phone via a published claude.ai Artifact, not
a local Lavish URL (STAR session, 2026-11-12 — see `learnings.md`). That
shapes what the scout hands to the publishing agent:

- One self-contained HTML page plus separate render PNG/GIF files —
  publish the renders as the Artifact's supporting files, not inlined as
  base64 inside the page. A multi-MB base64 page is the thing to avoid.
- Total size under 16 MB; keep individual renders small (the crystal-
  sprite recipe below already targets 50-160 KB per clip for this
  reason).
- Works at phone width: single column or wrapping tiles, no fixed-width
  layouts wider than a phone screen, touch-sized controls on any scrubber.
- No external fetches (fonts, scripts, images) — everything the page
  needs ships as a supporting file or is already inline JS/CSS.
- Stills and renders show the REAL fixture layout (crystal hex mask or
  the real strip length), labelled on the page (which fixture, which
  seed/song, today vs proposed) — never a label baked into the PNG
  itself, so the same renders can be relabelled or recombined.

A local Lavish session stays optional, for his desktop/laptop convenience
only; it is never the only copy he can open.

## Which recipe for which kind

| Kind of question | Recipe | Start from |
|---|---|---|
| A Matrix effect's motion/look on the crystal (new or changed) | Crystal sprites + inline JS hex renderer, scrubbable, today/proposed pair on one scrubber | `scripts/render_sauron.py` (several colour sets side by side, frozen "moments" PNG), `scripts/render_fish_lull_searcher.py` (before/after GIFs on the REAL 976 cells) |
| A transition / effect switch / transition program | Same switch rendered twice (merge-base vs this checkout, or today vs sketch), stacked before-over-after, same seed | `scripts/render_shoal_burst.py`, `scripts/render_transition_programs.py` (contact sheets) |
| A lull / pre-drop / drop sequence across effects | Storyboards: one frame per 0.2 s through charge → lull → drop, per effect, driven by the lull arm the REAL engine writes | `scripts/render_predrop_storyboards.py` + `tests/pre_drop_look_harness.py`; `scripts/render_fireworks_melds.py` for drop-switch melds |
| A strip effect or the strip phase layer | Time-down-the-page strip sheet (300-pixel strip, breath/pre-drop/drop marked in the margin) | `render_predrop_storyboards.py`'s `strip_*` output; `tests/strip_phase_harness.py` |
| The Singles / Pulse | Level-over-time curve on one light, today dashed vs proposed | `render_predrop_storyboards.py`'s `pulse_levels.png` |
| STAR / radial | Needs a hosted Melt strip (`radial-dummy`) or it renders black offline | `tests/star_harness.py` (`star_room`) |
| A UI-shaped choice (where a control sits, what a lane shows) | Screenshots of the REAL page as the base, options painted onto copies, side by side with the real one first | the word-effect-highlight-options session (real Home / Test Bed / Review screenshots, each option drawn on the true chrome); the ui-layout plan (`docs/design/spectra-ui-mockups.html`, `scripts/regenerate_ui_mockups.py`) |
| A gradient / colour-set question | Swatches of HIS colour sets (read-only from storage), the effect on six of them | `render_sauron.py`'s `sauron_sets.gif` |

## The crystal-sprite recipe (the transitions-drop, star, shoal-burst,
   fish, sauron explainers)

- Render through `fx.headless` (`fx/headless.py`): a dummy device, audio
  silenced, a fake clock at 60 fps. Use the crystal's REAL cell mask
  (`storage/device_profiles/crystal-mapper.json`, read-only) via
  `start_headless_host(..., real_mask=)`, never the full 72x37 rectangle
  when the question is "what will he see" — only 36.6 % of the rectangle
  is light (`crystal-hex-grid` skill).
- Capture only the 976 real cells per frame at 20 fps (every 3rd frame)
  into a PNG whose width is 976 and height is the frame count. The page's
  JS decodes each sprite once (`getImageData`) and draws cells as circles
  at `(col+0.5)/72, (row+0.5)/37`, radius `W/72`; the real cells are two
  columns apart so the hex lattice forms itself. 50-160 KB per clip,
  scrubbable; a GIF is 300-600 KB and cannot be scrubbed. A today /
  proposed pair shares one scrubber. Pause tiles outside the viewport
  (IntersectionObserver) or a phone chokes on forty canvases. One
  explainer carried 43 clips in 5.6 MB.
- Drive the music by hand: audio is silenced, so pulse `_beat_pending` /
  `impulse` yourself; a scripted "song" (120 BPM, ordinary hits, a few big
  hits, a bass swell, the flare pokes) with the SAME seed on every tile so
  the eye compares the same moment.
- A scene switch in the rig is `host.effects.create(...)` +
  `virtual.set_effect(new, activate=False, cut=...)`; the stored crossfade
  is `virtual._config["transition_mode"/"transition_time"]`; a program
  goes through the real `set_effect(program=)` hook.
- A proposal that hands particles to the REAL incoming effect
  (`particle_handoff.store`) beats a sketch that imitates it; for a moving
  form (Orbits, Fish) run that form's own kinematics during the sketch and
  hand its native state over.

### Rig traps that produce a WRONG render with no error

- `sauron.py`, `eye.py`, `orbits.py`, `fish.py` draw rng seeds from an
  unseeded `np.random.default_rng()` at construction: pin
  `np.random.default_rng` for any before/after pair (`np.random.seed` does
  not reach it).
- `particle_handoff._store` is module-level and keyed by the shared
  default virtual id; it LEAKS between runs in one interpreter. Clear it at
  the top of every run. A snapshot stamped under a scratch fake clock reads
  as stale to the next rig and is silently dropped.
- `morphs.handoff_cut`-style helpers are coroutines: un-awaited, the cut
  never happens and the "after" frames are the outgoing effect.
- Melt reads `time.time_ns()`, not the fake clock: two renders of the same
  STAR tile never match exactly. Treat sprites + measured numbers as one
  batch written from one `measure.json`; never hand-patch a number after a
  re-render.
- A 1-cell splat vanishes on alternate hex rows: draw pieces 2 cells wide.
- A per-cell gain that is 0 until pieces land and then eases globally POPS
  the whole picture in two frames (his "the star just appears"). Growing
  in reads as a radial front gating which cells may light at all.
- Effect locks are non-reentrant: never wrap `update_config` in
  `with eff.lock` inside a harness.
- A dot tracker on the sprites cannot measure velocity continuity; read
  the effect's own particle arrays per frame.

## Measuring instead of adjectives

Beside every pair put the numbers the claim rests on: lit-cell count per
frame, per-frame mean |Δ| per cell (abruptness), a perimeter-cell mean (a
ring "just appearing"), frames to settle, white fraction (the fish-swim
plan's "wash-out" was a measured white fraction before it was a question).
The build's acceptance checks reuse the SAME measurements, so the plan's
numbers and the proof's numbers are one thing.

## Page conventions he has accepted

- Dark page; each option a titled tile; the real/today tile first and
  visually marked; one shared scrubber per today/proposed pair; the
  question and its recommended answer under the tiles, in the round's
  numbering so his "Q3: A" lands unambiguously.
- He edits the page when he wants to (the UI-layout plan's edited
  `explainer-final.html` became the spec; the design-fidelity gate in
  `docs/agents/ui-timeline-and-tv.md` grew from that). Keep a copy before
  his edits.
- A numeric shape param gets a FULL-RANGE grid, not a 3-option row: the
  STAR session's `edges` grid across its whole -0.7..+0.7 range, 3-6 edges
  on the other axis, was what corrected his "0.5 is flat" assumption — a
  narrower row of hand-picked options would not have shown the part of
  the range that surprised him (STAR, 2026-11-12).
- Check the page in a headless browser before sending it (`chrome-devtools-axi`
  or raw CDP); a canvas that throws on a mock-shape gap shows him a blank
  tile, not an error. Do this before publishing the Artifact, not after —
  a blank tile on his tablet is harder to debug from than one caught here.

## Lessons from star-improve-plan (2026-11-12)

- **Embed the sprites as data URIs.** A page opened from `file://` cannot
  `getImageData` from a sibling PNG (tainted canvas): every tile stayed
  blank with no visible error. Inline the PNGs (a 7–10 MB page is fine)
  and check headless over raw CDP (`Runtime.exceptionThrown` + a count of
  decoded sprites) before sending.
- **He reviews on a tablet.** The local Lavish URL does not reach it.
  Publish the explainer as an artifact page he can open, and keep plain
  stills/GIFs beside it (`data/<plan>/tablet/`: a three-panel PNG per
  option at low/mid/high and a ~6 s, <3 MB GIF per option).
- **For a continuous param, render the FULL RANGE as a grid first** (his
  ask: −0.7..+0.7 in 0.1 steps × 3–6 edges = 60 stills at 240 px, no
  labels, plus a measure.json). He picks from the grid in one message;
  three hand-chosen options invited a wrong assumption ("0.5 is flat").
- **State the param's neutral value in the facts** (flat = `star` 0, the
  shaping formula) before any range question; render a frozen row of the
  shapes beside the waves.
- **Real device geometry, not an assumed one.** The TV tile was drawn on
  HyperHDR's own LED layout read off the strip's Pi (`config/
  tv_backlight_layout.json`); the assumed single loop would have mis-shown
  "today". Scripts: `scripts/render_star_improve_{crystal,strips,grid,
  tablet}.py`, `scripts/build_star_improve_explainer.py`.
