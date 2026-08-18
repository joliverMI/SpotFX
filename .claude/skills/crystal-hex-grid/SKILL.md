---
name: crystal-hex-grid
description: >
  The geometry of his live `crystal-mapper` Matrix virtual — a hex-lattice
  panel where only 36.6% of the addressable 72x37 rectangle is real light,
  arranged in a hexagon, not a checkerboard-everywhere or a simple gap
  border. Explains how a coordinate maps to a physical pixel, which regions
  are permanently dark, and why any spawn/travel/coverage math done against
  the full rectangle is wrong by roughly 3x here.
  TRIGGER — load BEFORE touching any effect whose CATEGORY is "Matrix"
  (config/effect_params.json: radial, noise, concentric, equalizer2d,
  blender, keybeat2d, gifplayer, blackhole, orbits, fireworks, pacman) or
  anything else that renders to crystal-mapper: tuning a spawn/kill radius,
  a coverage/brightness/"is this visible" measurement, a new GradientEffect/
  Twod effect, or a bug report shaped like "X is invisible / too small /
  spawns in the wrong place on the crystal / hex panel". Also load before
  writing anything that reads storage/device_profiles/crystal-mapper.json.
  SKIP if the change is GIF/dancer asset authoring specifically (poses,
  styles, keybeat2d tint) — use the led-gif-assets skill for that; it covers
  the same device from the authoring-tool side.
---

# The crystal-mapper hex grid

**Read this before changing anything that renders to `crystal-mapper` (the
Matrix category), or before trusting any measurement made against its full
addressable rectangle.** This was written after fixing a real bug
(fm/spectra-blackhole-hex-spawn, 2026-08-17: Blackhole's spawn radius put
new blobs almost entirely on dead cells) — the surprises below are what
actually went wrong while doing that, not a spec written in advance.

## The one fact everything else follows from

`crystal-mapper` addresses a **72 x 37 rectangle (2,664 cells)**. Only
**976 of those cells (36.6%) are real light** — 1,688 (63.4%) are wired to
a dummy `gap-crystal-mapper` device that has no physical output at all.
Ground truth: `storage/device_profiles/crystal-mapper.json`
(`real_pixel_count`/`pixel_count`; re-extract with
`python3 -m tools.gifsmith profile crystal-mapper` if it's ever stale
against the live LedFX segment list — it's a build artifact, not
hand-authored).

**The surprise: the real cells are not scattered or checkerboarded evenly
across the whole rectangle — they form a hexagon.** Decode `mask_rle`
(RLE of a row-major bool mask — `tools/gifsmith/device_profiles.rle_to_mask`,
or 20 lines of Python, see below) and print it per row and the shape is
obvious:

```
row  0 (tip):    10 real cells, columns 17-51, in widely-spaced PAIRS
row  1-16:       real column span widens roughly linearly, 20 -> 34 cells
row 17-19 (equator): 36 real cells, spanning columns 0-71 — the FULL width
row 20-35:       narrows back down symmetrically, 34 -> 20 cells
row 36 (tip):    10 real cells, columns 17-51, mirroring row 0
```

Within any non-tip row, real cells sit at **every other column** — but
**which parity (even/odd) is real flips from row to row** (row 1's real
columns are even-ish, row 2's are odd-ish, ...). That per-row parity flip is
what makes this a hex lattice instead of a plain half-populated grid, and
it's also why **a 1px-wide vertical stroke vanishes on every other row** —
the device profile encodes this as `min_stroke_px: 2`, `hex_lattice: true`.

## How a coordinate maps to a physical pixel

- **Pixel index**: row-major, `index = row * 72 + col`, exactly like any
  other matrix virtual. Nothing about addressing is hex-specific.
- **Effect-layer `r_width`/`r_height`** (`fx/effects/twod.py`, every
  `GradientEffect`/`Twod` subclass): always the FULL rectangle — `72, 37`
  for crystal-mapper. The effect never sees `36` (the hex's own
  `effective_width`) or `976` (the real count) — see the next section.
- **Real vs. gap**: NOT decidable from inside an effect at runtime (see
  below). Only decidable offline, from `storage/device_profiles/
  crystal-mapper.json`'s `mask_rle`, or by reading `fx/virtuals.py`'s
  segment list and checking which segments point at a `gap-*`/dummy device
  (`tools/gifsmith/device_profiles.py::is_real` is the reference
  implementation).
- **Normalized-radius effects** (Blackhole and anything else built on the
  same `cx/cy/sx/sy` convention — `do_once()` in `fx/effects/blackhole.py`
  is a representative example): `cx = (r_width-1)*x_offset`,
  `sx = radius_scale * (r_width-1)/2` (same shape for `cy`/`sy`), then
  `r = sqrt(((x-cx)/sx)^2 + ((y-cy)/sy)^2)`. At the defaults (`x_offset=
  y_offset=0.5`, `radius_scale=1.0`), **`r=1` lands exactly on the
  rectangle's own edge** (an ellipse touching all four edge midpoints); the
  rectangle's corners are at `r=sqrt(2) ≈ 1.41`.

## Which regions are dark, precisely

Real-pixel density by normalized radius (r=1 = panel edge), measured
against the live device profile — reproduce with
`.venv/bin/python scripts/check_blackhole_hex_spawn.py`:

| r range     | real-pixel density |
|-------------|---------------------|
| 0.00 – 0.85 | a flat **50%** (the checkerboard interior) |
| 0.90        | 44% |
| 1.00        | 19% |
| 1.10        | 7% |
| ≥ 1.20      | **0%** — pure gap, the rectangle's corners |

**It is a cliff, not a gradient.** Density is exactly 50% everywhere inside
the hexagon's own boundary (r ≲ 0.85-0.9, and it's not perfectly circular —
the equator rows reach real cells out to r≈1.0-1.03 at their extreme
columns, while the tip rows only reach real cells near r≈1.0 close to the
vertical axis) and falls off sharply outside it, reaching exactly 0% by
r≈1.2. There is no code anywhere that computes this boundary for you at
runtime — it only exists as measured data against the stored profile.

## What this means for anything that spawns, travels, or measures coverage

1. **Spawning or placing something at/near `r≈1` (the rectangle's rim) will
   land on a dead cell most of the time.** This was the actual bug: Black
   Hole's infall-mode spawn annulus was `(0.90, 1.05)` — a 26% real-pixel
   hit rate. Pulling it to `(0.70, 0.85)` (inside the flat 50% interior)
   raised that to 50%, without changing anything else about the effect —
   see `fx/effects/blackhole.py`'s `SPAWN_ANNULUS_MIN/MAX` and
   `fx/VENDOR.md` deviation #12 for the fix and its reasoning.
2. **A coverage or brightness measurement taken over the full rectangle is
   wrong by roughly a factor of 2664/976 ≈ 2.73** on this device — "40% of
   the panel is lit" measured against all 2,664 cells means something
   different from "40% of the panel is lit" measured against the 976 real
   ones. Any such measurement needs to either mask to the real cells first
   or explicitly say which denominator it used.
3. **Motion/travel is fine anywhere** — a particle CAN cross gap cells
   (kill_radius, horizon radius, r_max/corner-exit checks etc. all still
   work in the full normalized space) — the problem is only ever about
   *where something becomes visible*, not where it's allowed to exist or
   move.
4. **This is a Matrix-category-wide risk, not a Blackhole-only one.**
   Eleven effects target crystal-mapper (`config/effect_params.json`
   `categories.Matrix.effects`: radial, noise, concentric, equalizer2d,
   blender, keybeat2d, gifplayer, blackhole, orbits, fireworks, pacman) and
   every one of them renders through the same blind `r_width x r_height`
   rectangle. Any of them that place/measure things in absolute panel
   coordinates (not just Blackhole's polar spawn) are worth checking against
   this same density table before assuming a "too big/too small/invisible"
   report is a tuning-number problem rather than a geometry one.

## Mistakes that are easy to make (all made once, while fixing this)

- **Confusing a config field's *name* with what it actually controls.**
  Blackhole's `radius_scale` is literally documented as `"Spawn radius as a
  fraction of the panel edge"` — but it actually scales `sx`/`sy`, which
  drive EVERYTHING (spawn, travel, kill radius, the rendered disc, corner
  exit) uniformly. Turning it down "fixes" the spawn-too-far-out symptom by
  shrinking the whole effect and abandoning most of the crystal's real
  reach — exactly the wrong fix. The right lever was a *different*,
  previously-unexposed radius (the spawn annulus specifically), left
  `radius_scale` untouched.
- **Assuming the real/gap pattern is a simple half-populated grid.** It
  isn't "every other column, always the same column" — the parity flips
  per row (that's what makes it a hex lattice), AND the row's own real span
  narrows toward the top/bottom tips. A fix that only accounts for "half
  the cells are gap" (e.g., a uniform 50%-everywhere assumption) misses
  that the outer ~15% of the radius is *entirely* gap, not just thinned.
- **Assuming the effect pipeline knows any of this.** It doesn't, anywhere.
  `r_width`/`r_height` in `fx/effects/twod.py` are always the full
  rectangle; nothing under `fx/` reads `storage/device_profiles/` (grep
  confirms — only `tools/gifsmith/` and `tools/dancesmith/` do, both
  offline asset tools). An effect cannot ask "is this cell real?" at
  runtime; you can only design defaults that are statistically informed by
  the shape (as the spawn-annulus fix does) or consult the profile file
  *offline* when choosing those defaults.
- **A 1px feature "should" be visible somewhere.** It vanishes on whichever
  rows its column lands on the gap parity — always test rendered output
  against the mask (`tools/gifsmith preview --ascii`, or decode
  `mask_rle` directly), never eyeball raw coordinates.

## Reproducing any of the numbers above

```python
import json
prof = json.load(open("storage/device_profiles/crystal-mapper.json"))
mask, v = [], False
for run in prof["mask_rle"]:
    mask.extend([v] * run); v = not v
rows, cols = prof["rows"], prof["cols"]
grid = [mask[r*cols:(r+1)*cols] for r in range(rows)]
```

Or run `.venv/bin/python scripts/check_blackhole_hex_spawn.py` (read-only,
never writes) for the full density-by-radius table plus a live comparison
of the old vs. new Blackhole spawn annulus against this exact data.

## Related

- `.claude/skills/led-gif-assets/SKILL.md` — the same device from the GIF/
  dancer asset-authoring side (gifsmith poses/styles/preview workflow);
  load that one instead if the task is authoring a moving image asset, not
  tuning a procedural effect.
- `tools/gifsmith/device_profiles.py` — the extractor + `rle_to_mask`/
  `profile_mask` helpers this skill's numbers came from.
- `fx/VENDOR.md` deviation #12 — the Blackhole spawn-annulus fix this skill
  documents the reasoning behind.
