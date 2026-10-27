# Pre-drop storyboards (predrop plan steps 6-9)

Rendered by `scripts/render_predrop_storyboards.py` through the shipped effects, driven by the lull arm the real engine writes. Light: each real cell's brightest channel / 255, summed over the crystal's 976 real cells (cells at full), averaged over the lull before the pre-drop and from the pre-drop to the drop (for a "today" clip, the same stretches of its lull); the whole lull is cells at full x seconds.

## Fireworks

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 25.7 | 7.2 | 67 |  |
| spike_0.8s (lull 3.2 s) | 4.2 | 37.9 | 41 | -39% |
| spike_2s (lull 3.2 s) | 7.4 | 25.6 | 61 | -10% |
| today_6s (lull 6.0 s) | 15.0 | 2.4 | 80 |  |
| intro_3.3s (lull 6.0 s) | 3.7 | 17.7 | 69 | -14% |

Without a pre-drop, frame for frame against the module before the looks (34ce2b14): unchanged.

## Pulse

| Case | Peak in the gap | Dark before the drop | Black through the breath | Whole lull light (x today) |
|---|---:|---:|---|---:|
| Spike, Winny 627 ms | 1.00 | 150 ms | yes | 1.10 |
| Spike, his max 2000 ms | 1.00 | 483 ms | yes | 1.25 |
| Vocal intro, Dopamine 3295 ms | 0.30 | 483 ms | yes | 0.56 |

Without a pre-drop, level for level against the module before the looks: unchanged. Pulse's light is delivered light (level ^ gamma) summed over the lull; the spike's burst is the look he asked for, so it can add light where the lull is short.

## Orbits

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 9.3 | 1.1 | 23 |  |
| spike_0.8s (lull 3.2 s) | 6.7 | 6.0 | 21 | -9% |
| spike_2s (lull 3.2 s) | 8.9 | 6.2 | 23 | +1% |
| today_6s (lull 6.0 s) | 6.3 | 0.2 | 33 |  |
| intro_3.3s (lull 6.0 s) | 6.4 | 6.2 | 38 | +14% |

Without a pre-drop, frame for frame against the module before step 7 (29778cf3): unchanged.

## Black Hole

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 166.2 | 0.0 | 396 |  |
| spike_0.8s (lull 3.2 s) | 124.0 | 41.1 | 329 | -17% |
| spike_2s (lull 3.2 s) | 123.1 | 41.6 | 230 | -42% |
| today_6s (lull 6.0 s) | 144.4 | 0.0 | 748 |  |
| intro_3.3s (lull 6.0 s) | 124.1 | 41.8 | 472 | -37% |

Without a pre-drop, frame for frame against the module before step 7 (29778cf3): unchanged.

Orbits is back at full and growing for the whole gap, so a longer gap adds light: the plan's own prototype measured only the 0.8 s gap, where it is below today's; a 2 s spike and a 3.3 s vocal intro run above it (named, bounded at +20%).

## Fish

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 81.7 | 6.6 | 200 |  |
| spike_0.8s (lull 3.2 s) | 74.9 | 14.6 | 190 | -5% |
| spike_2s (lull 3.2 s) | 93.5 | 15.8 | 143 | -29% |
| today_6s (lull 6.0 s) | 44.8 | 6.3 | 237 |  |
| intro_3.3s (lull 6.0 s) | 70.1 | 14.7 | 237 | -0% |

Without a pre-drop, frame for frame against the module before step 8 (ed8b2008): unchanged.

## Star

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 267.1 | 0.0 | 637 |  |
| spike_0.8s (lull 3.2 s) | 219.8 | 21.3 | 541 | -15% |
| spike_2s (lull 3.2 s) | 226.9 | 21.4 | 312 | -51% |
| today_6s (lull 6.0 s) | 234.0 | 0.0 | 1213 |  |
| intro_3.3s (lull 6.0 s) | 210.9 | 21.4 | 637 | -47% |

Without a pre-drop, frame for frame against the module before step 8 (ed8b2008): unchanged.

star_spike_0.8s_newset: the set changes to a warm one at the pre-drop; the drop's pieces come back out in it (today they keep the colours they fell in with).

## Sauron

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 375.9 | 54.5 | 940 |  |
| spike_0.8s (lull 3.2 s) | 354.0 | 100.8 | 926 | -2% |
| spike_2s (lull 3.2 s) | 313.3 | 103.0 | 579 | -38% |
| today_6s (lull 6.0 s) | 238.2 | 54.4 | 1279 |  |
| intro_3.3s (lull 6.0 s) | 327.9 | 103.7 | 1224 | -4% |

Without a pre-drop, frame for frame against the module before step 8 (ed8b2008): unchanged.

The Fish takes no breath, so its lull is never dark; the plan's prototype measured it +4% (named), the build is at or below today's. Sauron ships at the plan's dimmer setting (the glare at 20% rising to 36%, the prototype's 35% to 60%).

## Melt

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 61.8 | 0.0 | 147 |  |
| spike_0.8s (lull 3.2 s) | 50.5 | 13.3 | 131 | -11% |
| spike_2s (lull 3.2 s) | 45.7 | 17.5 | 89 | -39% |
| today_6s (lull 6.0 s) | 48.7 | 0.0 | 253 |  |
| intro_3.3s (lull 6.0 s) | 49.0 | 17.9 | 191 | -24% |

Without a pre-drop, frame for frame against the strip and the shared layer before step 9 (619172e8): unchanged.

## Power

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 65.7 | 0.0 | 156 |  |
| spike_0.8s (lull 3.2 s) | 48.9 | 13.3 | 127 | -19% |
| spike_2s (lull 3.2 s) | 46.6 | 17.5 | 90 | -42% |
| today_6s (lull 6.0 s) | 56.8 | 0.0 | 295 |  |
| intro_3.3s (lull 6.0 s) | 49.0 | 17.9 | 191 | -35% |

Without a pre-drop, frame for frame against the strip and the shared layer before step 9 (619172e8): unchanged.

## Black Hole strip

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 25.8 | 0.0 | 62 |  |
| spike_0.8s (lull 3.2 s) | 19.3 | 13.3 | 57 | -8% |
| spike_2s (lull 3.2 s) | 19.4 | 17.5 | 58 | -6% |
| today_6s (lull 6.0 s) | 22.5 | 0.0 | 117 |  |
| intro_3.3s (lull 6.0 s) | 19.3 | 17.9 | 111 | -5% |

Without a pre-drop, frame for frame against the strip and the shared layer before step 9 (619172e8): unchanged.

## Orbits strip

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 57.0 | 0.3 | 136 |  |
| spike_0.8s (lull 3.2 s) | 46.0 | 13.5 | 121 | -11% |
| spike_2s (lull 3.2 s) | 53.3 | 18.0 | 99 | -27% |
| today_6s (lull 6.0 s) | 41.0 | 0.3 | 213 |  |
| intro_3.3s (lull 6.0 s) | 44.6 | 18.1 | 180 | -16% |

Without a pre-drop, frame for frame against the strip and the shared layer before step 9 (619172e8): unchanged.

## Fireworks strip

| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull | vs today |
|---|---:|---:|---:|---:|
| today_3s (lull 3.2 s) | 50.5 | 1.2 | 121 |  |
| spike_0.8s (lull 3.2 s) | 34.5 | 38.2 | 113 | -7% |
| spike_2s (lull 3.2 s) | 41.7 | 22.8 | 95 | -21% |
| today_6s (lull 6.0 s) | 35.7 | 0.9 | 186 |  |
| intro_3.3s (lull 6.0 s) | 33.1 | 15.5 | 140 | -25% |

Without a pre-drop, frame for frame against the strip and the shared layer before step 9 (619172e8): unchanged.

A strip's light is each pixel's brightest channel / 255, summed over the 300 pixels. The twinkle (Melt, Power, the Black Hole and Orbits strips) peaks at the effect's own brightness; only its sparseness keeps the light low (Melt's own blur softens a one-pixel twinkle's peak). The Fireworks strip is the crystal's idea: dark, black through the breath, then two rockets fire from the ends on the pre-drop and burst on the drop.
