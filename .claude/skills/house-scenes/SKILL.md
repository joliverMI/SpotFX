---
name: house-scenes
description: >
  House lighting's STARTING CONTENT (phase 4): the "House Star" and "House
  Fish" scenes, the "Calm - Evening" group and its three copies, the "Night
  Light" colour set, and the seven modes (Standard, Evening, Dim, Night
  light, Away, TV, TV paused) — all written by scripts/
  seed_house_lighting.py. Load before editing any of them, re-running the
  seeder, adding a mode, or mapping a new Home Assistant lighting word.
---

# House scenes and modes (phase 4)

`scripts/seed_house_lighting.py`'s module docstring is the binding
statement: what it writes, where every number came from (Home Assistant's
own scenes and WLED presets, read 2026-10-05), and the four decisions the
data encodes. The short list of traps:

1. **"Calm - Evening" is a group of COPIES.** A set fired by its own id
   wears EVERY enclosing group's overrides, alphabetically-last winning — a
   second group over Calm's own members would turn Standard (and every
   music show naming a Calm set) red. Never add Calm's originals to it.
2. **The house scenes have NO sequencer entry and no flares** — that is
   what keeps the music engine from ever drawing them
   (`selection_kernel.build_scene_candidates` builds from entries only).
   Adding one in the Sequencing tab puts a calm scene into music shows.
3. **The new sets are `scene_v2_opt_out`** (like the Calm members) so they
   never join a music colour pool; the house journey still travels them
   because the mode names them (drift_conductor's house pool).
4. **Breathing targets the `single-color-effect` VIRTUAL**, never the
   Singles category — that also holds `hues`, and the Hue bulbs are held
   over the bridge, never breathed.

## The modes

| Mode | HA words | Scene / colours | Crystal | Strips | Singles | Hue | Music |
|---|---|---|---|---|---|---|---|
| Standard | Daytime, Party | House Star / Calm | 6% | 40% | 100% breathe | 3521 K full | show, Hue Hold switch |
| Evening | Evening | House Star / Calm - Evening | 13% | 30% | 100% | 2000 K / 2005 K full | show, switch |
| Dim | Dim | House Fish / Night Light | 3% | 12% | 50% | red-orange 50% / full | show, switch |
| Night light | Bedtime | House Fish / Night Light | 3% (fish only) | off | off | off | ignore |
| Away | Travel, Away | House Star / Calm | off | off | off | off | ignore |
| TV | TV | House Star / Calm - Evening | 1.2% | 15% (TV strip lent) | 30% | off | ignore |
| TV paused | TV paused | House Star / Calm - Evening | 6% | 35% | 60% | #ff9d31 29% / 2095 K 54% | ignore |

"unknown"/"unavailable" are deliberately unmapped (an HA restart keeps the
current mode). The seeder writes no Hue exclusion
(`HouseSettings.hue_excluded_lights` ships empty — every bulb, including
the Loft Ceiling Uplight and the three Ledge lights, is an ordinary
house-mode bulb; an earlier build seeded those four as excluded by
default, a wrong assumption corrected 2026-10-06). Seeding never switches
house lighting on (`HouseSettings.enabled`).

## Re-running the seeder

Dry run first (prints whole-file diffs). It upserts by deterministic id;
an entry he edited since it was seeded is KEPT and reported unless
`--overwrite`. Run it in the live checkout with `--root /home/javi/SpotFX`
only after the code it needs (the `gradient` registry entry, the skip
looks, the switch) is deployed. Backups land in `storage/spectra/backups/`.

## Executable proofs

`tests/test_seed_house_lighting.py` (synthetic storage shaped like his).
