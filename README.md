# Fish wall glance — offline evidence (branch fm/fish-wall-glance)

His words, 2026-10-07: "The fish now get stuck in the middle. I still want
them to go right up to the edge of the wall, but i want them to start turning
so their bodies sides touch the walls, more than their heads. That should
improve how natural the motion looks. It's okay for light to bleed off the
fixture, I'm more interested in a natural look."

Everything here was rendered OFFLINE on the real vendored fish effect
(`fx.headless`) with his crystal's real hexagon shape and both scenes' live
params (read-only from `/home/javi/SpotFX/storage/spectra/scenes.json`). No
live lights were touched.

## Files

Each comparison stacks three fish, same seed, same frames: **OLD EDGE** (before
any wall, `wall_lookahead = 0`), **PR 361** (the first wall build, the "stuck
in the middle" he saw), **NEW GLANCE**. Faint squares outside the outline are
light past the panel's edge (no cells there; he said bleed is fine).

- `fish_wall_house.gif` — House Fish scene, 12 s.
- `fish_wall_music.gif` — music Fish scene, 12 s (its pond is his own
  `roam_scale 0.75`, so these fish glide along an invisible ellipse three
  quarters of the panel across).
- `fish_wall_tracks_house.png`, `fish_wall_tracks_music.png` — 20 s of each
  fish's track as a line, its body drawn every half second. Easiest single
  picture: the old edge orbits a ring, PR 361 is a ball in the middle, the new
  fish cross the panel and run along the walls.
- `fish_wall_approach.gif` — one House Fish swimming up at the top wall.
- `fish_solo_burst.gif` — House Fish solo bursts (rate raised to 20/min so
  several show).

## Numbers (`scripts/check_fish_wall.py` §2, 3 seeds x 30 s)

House Fish:

| | old edge | PR 361 | new |
|---|---|---|---|
| panel covered by fish | 85.5% | 22.9% | 82.9% |
| side (flank light) on the wall | 44.6% | 0% | 57.0% |
| touching: body along the wall (<20°) | 76% | — | 77% |
| touching: pointing into it (>45°) | 1.9% | — | 2.6% |
| time at its tightest turn (a pivot) | 13.6% | 21.5% | 2.8% |
| middle off the panel | 0.4% | 0% | 0% |

One House Fish meeting the top wall (§3): the new turn starts with its nose
7-18 px from the wall on steep approaches (old: ~2 px), never jolts (largest
one-frame curvature change 0.10-0.18 of its tightest; old ~0.8), and its side
reaches the wall every time.

Music Fish (his pond 0.75): covers 68% of the panel (PR 361: 42%, old: 48%);
its side never reaches the real wall because its pond stops it ~4 px short.
With the pond at 0.95 (not shipped — his value) it covers 86% and touches.

## The honest limit

A 21 px House Fish on a 37 px hexagon, with its head drawn straight along its
heading, cannot always put its side on the wall before its nose: the hex's
edges (top 34 px, slants ~24 px) are shorter than the arc a nose-safe turn
needs, so steep approaches land near a corner nose-first. Three stricter
designs (a look-along-the-arc planner, a nose barrier, glance + barrier) were
built and measured: they made every contact side-on but kept the fish ~2 px
off the wall (side on the wall 4-7% of the time, coverage back to 60-67%). The
shipped balance follows his weighting (reach + natural, bleed OK).
`wall_turn_strength` is the dial if he wants more side and less reach (lower)
or the reverse (higher); Sonic can set it per scene.
