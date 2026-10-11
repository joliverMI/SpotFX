# Sauron tune-up 1 — before / after

Rendered by `scripts/render_sauron_tuneup.py` (2026-10-11) on the real
render pipeline (`fx.headless`, audio silenced, a fake clock) onto the
crystal's real 976 cells — not his room. BEFORE is the effect as merged
(PR #394, read out of git at `e1d92f7`); AFTER is this branch. Both run
the same scripted song with the same seed, so the eye looks at the same
place in both columns, and it MOVES: big hits dart the gaze at 1.75 /
4.25 / 6.25 s, a bass swell 2.5-4.0 s lengthens the flames, surges at
3.4 s and 5.8 s, and a charge builds 5.2-6.4 s (the slit narrows to its
floor). Settings are his tuned Sauron scene's own values (each signal
binding at its fallback).

- `sauron_tuneup_compare.gif` — rows Hype 1 (a rainbow set: auto is now
  the radial mapping), Mid - Fire and Orbit - Red (warm sets: the thicker
  perimeter ring fading into the flames, the slit floor); columns
  before | after.
- `sauron_tuneup_moments.png` — frozen moments (rest, a dart, full bass, a
  surge, a full charge) for Hype 1 and Mid - Fire, before | after.

The numbers behind them are `scripts/check_sauron.py` sections 1b, 2b and
7b.
