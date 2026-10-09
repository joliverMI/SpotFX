# Fish big fish flare, phase 2 — the other fish get out of its way

His approval of the look (PR 386), then the ask: "Big fish looks right:
build step 2 - the other fish steer around the big fish while it crosses."
Every view is SIDE BY SIDE: on the left BEFORE (`big_fish_avoid` 0 — the
phase-1 crossing exactly), on the right AVOIDING (the shipped default) —
the same seed, the same big fish, the same moment.

Rendered on his crystal-mapper's real cells through `fx.headless` (audio
silenced), his music Fish scene's Matrix entry wearing a warm gradient (so
the big fish's 120–180° turn is a cool colour). Half scale, 10 fps copies of
the full-size GIFs `scripts/check_fish_big_fish_avoid.py --gifs DIR` writes.

- `fish_big_fish_avoid_low.gif` — fire intensity 0.2: the slow (~5 s)
  crossing.
- `fish_big_fish_avoid_high.gif` — fire intensity 0.8: the fast (~3 s)
  crossing.
- `fish_big_fish_avoid_still.png` — the middle of each crossing, low above
  high.

Measured (`scripts/check_fish_big_fish_avoid.py`, his music Fish on his
crystal, seeds 0–5, his real cells only):

| | quiet (0.2) before | quiet after | loud (0.8) before | loud after |
|---|---|---|---|---|
| frames with any overlap | 583 / 1848 | 369 / 1848 | 362 / 1032 | 141 / 1032 |
| overlap pixels, total | 4898 | 2393 | 3413 | 647 |
| worst frame, pixels | 30 | 13 | 29 | 12 |
| fish middles on it, middle columns | 103 | **0** | 139 | **0** |
| fish middles on it, the two points | 150 | 92 | 38 | 27 |
| furthest past the lit edge | 0 px | 0 px | 0 px | 0 px |
| turn faster than its turn circle | — | never | — | never |

"Overlap" is an ordinary fish's freshly drawn body lit at the level that
hides the big fish, on the big fish's own lit body (a quarter of its full
level or more). What is left is at the hexagon's two pointed ends, where the
big fish fills the whole lit height and the wall keeps a fish caught there
on the panel. Offline only: his live look is the real judgement.
