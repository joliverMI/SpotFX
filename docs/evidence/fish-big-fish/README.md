# Fish big fish flare — offline evidence

His word on the first build (PR 381): "the fish looks all wrong. it should
be the same as the other fish in the effect, just bigger, in the background,
and dimmer, with a dim but large ripple". Every view is SIDE BY SIDE: on the
left the big fish as PR 381 drew it (a bespoke silhouette with a forked tail
fin), on the right the rework (an ordinary fish's own body, bigger, behind,
dimmer, with its own large dim wake) — the same seed, the same ordinary fish
(identical on both sides), the same moment.

Rendered on his crystal-mapper's real cells through `fx.headless` (audio
silenced), his music Fish scene's Matrix entry wearing a blue gradient whose
centre is #00c8ff. Half scale, 10 fps copies of the full-size GIFs
`scripts/render_fish_big_fish.py --out DIR` writes.

- `fish_big_fish_low.gif` — fire intensity 0.2: turned 120° (#ff00c8),
  crossing in 5.2 s, a slow, gentle tail stroke.
- `fish_big_fish_high.gif` — fire intensity 0.8: turned 180° (#ff3700),
  crossing in 2.9 s.
- `fish_big_fish_still.png` — the middle of each crossing, low above high.

Measured (the script prints it): the big fish is 46 px long, 5.3x an
ordinary fish; its brightest pixel 127/255 at the default 60%; its own wake
peaks 27/255 (the ordinary fish's wakes peak 110) and spreads over 1,700-2,200
px of the panel. The ordinary fish swim in front of it (it is hidden wherever
they are lit). The GIF palette is shared by both panels, so a dim shade can
quantise slightly differently left and right. Offline only: his live look is
the real judgement.
