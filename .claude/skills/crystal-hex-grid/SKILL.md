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
new blobs almost entirely on dead cells) and extended after a follow-up bug
in the SAME fix (fm/spectra-blackhole-spawn-at-edge, 2026-08-18: the
hit-rate-maximizing spawn ring from the first fix pulled blobs too far
inside the visible silhouette — see "The boundary is direction-dependent"
below) — the surprises below are what actually went wrong while doing this
work, not a spec written in advance.

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

## The boundary is direction-dependent — there is no single "the edge" radius

The density table above answers "how far out is dark", collapsed across all
directions. That collapse hides the actual shape: **the true boundary's
distance from center depends on which way you look.** Measured directly off
`crystal-mapper.json`'s real-cell extents (`fx/effects/blackhole.py`'s
`HEX_SPAWN_VERTS`, six vertices in the same normalized `(gx, gy)` space
`do_once()` projects into):

| direction                          | boundary distance (normalized r) |
|-------------------------------------|-----------------------------------|
| tightest — a flat edge's own midpoint-normal | ≈ **0.87** |
| loosest — a corner vertex            | ≈ **1.13** |

That's a ~30% swing. **Any single scalar radius is therefore wrong almost
everywhere it's used** — it can coincide with the true boundary at a handful
of angles at best, and will sit either well inside it (most directions, if
you pick a number near the tight end) or well outside it (most directions,
if you pick a number near the loose end). This is exactly how the original
spawn-annulus bug happened, and exactly how the fix that followed it
(pulling the annulus in to maximize hit-rate) overshot: `r≈0.85` sits right
at the tight end, so it's a strong hit-rate number and *also* still deep
inside the silhouette at every angle that isn't near the tight directions —
"hit rate" and "sits at the boundary" are different objectives that only
agree at the tightest point.

**If a task needs something to sit at, or just outside, the visible edge in
every direction it can fire — not maximize how often it lands on a lit
pixel — the fix has to compute the boundary per angle, not pick a scalar.**
`_hex_spawn_edge_radius(theta)` in `fx/effects/blackhole.py` does this: it's
the convex hexagon's own support function (for each direction, the nearest
of the 6 measured edge-lines actually facing that direction), evaluated in
closed form — no lookup table, no runtime device-profile read. It's checked
against the boundary measured directly off the device profile (max real-cell
radius per 5° angular bin) to within ±0.06 normalized-r — lattice/
quantization noise, not formula error — by
`scripts/check_blackhole_hex_spawn.py`.

**The inradius is not "tangent to the edge and outside near the corners" —
it is *inside* the polygon everywhere except at the tangent points.** It is
tempting to reach for "hexagon inradius" (apothem — perpendicular distance
from center to an edge, ≈0.866× the circumradius for a *regular* hexagon)
as a single number that's "tangent to the edge." A circle at that radius
*is* tangent to each edge, but only at that edge's own midpoint — everywhere
else, including toward every corner, the true boundary is *farther out*
(up to the circumradius at the vertices themselves), so the inradius circle
sits strictly inside the polygon there, never outside it. This is basic
convex geometry (the incircle of any convex polygon is, by definition,
contained in the polygon), and it's also empirically visible above: the
"tightest" boundary distance (≈0.87, the inradius-like quantity for this
irregular hex) is barely past the already-too-far-in 0.70–0.85 annulus — an
inradius scalar would not meaningfully fix a "spawns too far inside" report,
because it's still a single scalar with the same failure mode as any other:
correct at a few angles, wrong (here, still too far in) everywhere else. If
a task or a request describes wanting a "tangent to the edge" radius that's
supposed to poke outside near the corners, that description is internally
inconsistent — either it means "sits inside at the tangent points, further
inside elsewhere" (the true behavior of an inradius scalar), or it actually
means the per-angle boundary-following fix above, not a single number at
all. This exact confusion showed up live once already (a request insisting
on an inradius scalar with the "pokes outside near corners" justification,
fm/spectra-blackhole-spawn-at-edge, 2026-08-18) — check the polygon
geometry yourself (`scripts/check_blackhole_hex_spawn.py` or the reference
ray-cast in `tests/test_blackhole_spawn_radius.py`) before trusting a claim
shaped like this again, whatever its source.

## What this means for anything that spawns, travels, or measures coverage

1. **Spawning or placing something at/near `r≈1` (the rectangle's rim) will
   land on a dead cell most of the time.** This was the actual bug: Black
   Hole's infall-mode spawn annulus was `(0.90, 1.05)` — a 26% real-pixel
   hit rate. Pulling it to `(0.70, 0.85)` (inside the flat 50% interior)
   raised that to 50%. But that fix optimized the wrong objective — see the
   next section — and was superseded by a direction-dependent boundary in
   `fx/effects/blackhole.py`'s `HEX_SPAWN_VERTS`/`_hex_spawn_edge_radius`;
   `fx/VENDOR.md` deviation #12 has the full history.
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
never writes) for the full density-by-radius table, the closed-form
per-angle boundary formula checked against the measured boundary, and a
comparison across all three historical Blackhole spawn mechanisms against
this exact data.

## Related

- `.claude/skills/led-gif-assets/SKILL.md` — the same device from the GIF/
  dancer asset-authoring side (gifsmith poses/styles/preview workflow);
  load that one instead if the task is authoring a moving image asset, not
  tuning a procedural effect.
- `tools/gifsmith/device_profiles.py` — the extractor + `rle_to_mask`/
  `profile_mask` helpers this skill's numbers came from.
- `fx/VENDOR.md` deviation #12 — the Blackhole spawn-boundary fix (both
  rounds) this skill documents the reasoning behind.
- `fx/effects/blackhole.py`'s `HEX_SPAWN_VERTS`/`_hex_spawn_edge_radius` —
  the per-angle boundary formula itself, and its own long comment, for the
  full derivation.
