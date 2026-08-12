---
name: led-gif-assets
description: Author, preview and publish GIF animations (dancing figures etc.) for LedFX matrices using the gifsmith toolkit. Use when asked to create/modify moving images, dancers, or GIF assets for the LED matrices, or to add new dance styles/poses.
---

# LED GIF assets (gifsmith)

Everything runs headless with `python3 -m tools.gifsmith <cmd>` from the
SpotFX repo root. LedFX runs at localhost:8888. Assets are beat-driven via
LedFX's `keybeat2d` effect: frames tagged in `beat_frames` land on musical
beats and LedFX interpolates between them.

## The hex matrix (crystal-mapper) — authoring rules

- Canvas is **72×37**, but only 976 of 2664 cells are real LEDs, in a hex
  lattice (every other column, alternating parity per row). Its profile is in
  `storage/device_profiles/crystal-mapper.json` (re-extract with
  `python3 -m tools.gifsmith profile crystal-mapper`).
- **Strokes must be ≥ 2 px wide** or they vanish on half the rows.
- **Author masters in white on black** — color is applied at runtime by the
  keybeat2d `tint` param (a local LedFX patch). Keep `--color '#ffffff'`.
- Figure height ~30 px (82% of canvas) is the sweet spot.
- 10 MB asset cap (ours are ~10 KB). `image_location` must be a path
  relative to LedFX's asset store (e.g. `spotfx/dancer/x.gif`) — never
  absolute.

## Workflow: description → dancing on the matrix

1. **Compose the dance.** Poses live in `tools/gifsmith/poses.json` (flat
   angle dicts — see its `_README` for the angle conventions; any pose name
   takes a `!mirror` suffix). Dance styles (ordered key-pose lists, one pose
   per beat) live in `tools/gifsmith/styles.py`. Add poses/styles by editing
   those files. `python3 -m tools.gifsmith poses --list` shows everything.
2. **Render**: `python3 -m tools.gifsmith render --style basic --energy normal`
   → writes `build/gifs/dancer_<style>.gif` + a `.meta.json` sidecar whose
   `beat_frames` is computed from the pose layout (never hand-write it).
   Normal dances: 8 key poses × 2 tweens (24 frames). Big (flare) variants:
   4 exaggerated poses × 3 tweens (16 frames).
3. **Preview headlessly** (always do this before publishing):
   - `... preview --gif build/gifs/X.gif --device crystal-mapper --ascii`
     — one frame as text through the real-pixel mask.
   - `... preview --gif ... --png build/gifs/sheet.png` — all-frames contact
     sheet through the mask; **Read the PNG** to check every pose is legible.
   - The coverage line warns if any frame lights < 20 real cells.
4. **Optional live eyeball** (physical matrix, no audio needed):
   `... push --gif build/gifs/X.gif --device crystal-mapper --fake-beat`,
   then `... restore --device crystal-mapper` to put back the prior effect.
5. **Publish**: `... publish --gif build/gifs/X.gif [--dest spotfx/dancer/]`
   — uploads to LedFX assets, round-trip-verifies the frame count, copies
   the master into `tools/gifsmith/masters/`, and updates the manifest
   `storage/gif_assets.json` (base assets auto-link a `<id>_big` variant).
   `... status` diffs manifest vs live LedFX.

## How SpotFX uses the manifest

`storage/gif_assets.json` feeds `GET /api/gif-assets`, the event seeder
(`scripts/seed_dancer_event.py`) and the web UI's asset dropdown. Per-asset
`device_overrides` carry the recommended keybeat2d config per matrix
(force_fit etc., from the device profile). `image_location` + `beat_frames`
must always be written to LedFX in the SAME patch — the seeder does this.

## Other formats / effects

- Non-beat ambient loops: publish the same way, drive with LedFX `gifplayer`
  (`gif_fps`, `bounce`) instead of keybeat2d.
- New matrix devices: run `profile <virtual_id>` first; renderers take the
  canvas size from the profile, so assets adapt automatically. If the layout
  is NOT a hex lattice the profile sets `min_stroke_px: 1`.
- The `tint` runtime-color param is a local patch in ~/ledfx-src
  (`ledfx/effects/keybeat2d.py`). On a stock LedFX install, pre-tint
  instead: `... tint --asset dancer_basic --color '#ff2080' --upload`.
