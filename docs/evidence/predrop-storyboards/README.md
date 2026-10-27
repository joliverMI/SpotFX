# Pre-drop storyboards (predrop plan step 6)

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
