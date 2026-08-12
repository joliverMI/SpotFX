# dancesmith — authoring dances for the native Dancer effect

The LedFX **Dancer** effect (`~/ledfx-src/ledfx/effects/dancer.py`) renders a
procedural stick figure that dances to the beat engine. Its entire dance
vocabulary lives in ONE data module:

    ~/ledfx-src/ledfx/effects/dancer_moves.py

This toolkit previews and validates that library headless. The GIF pipeline
(`tools/gifsmith`, keybeat2d assets) is a *different* dancer — don't confuse
them. Both share the same skeleton proportions and pose conventions, so poses
port between them.

## The pipeline (for future agents)

1. **Author poses** in `dancer_moves.py` → `POSES`. A pose is a flat dict of
   ABSOLUTE angles in degrees. Convention (same as gifsmith):
   - limb angles measure from straight-down (0°), rotating toward that
     side's OUTWARD direction: 90° = horizontal out, 180° = straight up,
     **negative = inward across the body**;
   - forearm/shin angles are absolute too (chained from the elbow/knee
     *position*, not relative to the parent bone);
   - `torso` measures from straight-up, positive leans right;
   - `dx`/`dy` shift the hip in figure heights (positive `dy` = down —
     author it for squats/jumps, the FK does not solve ground contact);
   - skeleton v2/v3 keys: `spine` bends the upper torso ON TOP of `torso`
     (S-curves, chest pops), `neck` tilts the head on top of both,
     `shoulders` tilts the shoulder bar (+ = right shoulder up: shrugs,
     shimmies, sass), and `yaw` turns the figure in 3D (0 = facing the
     viewer, 90 = profile; rendered as x-foreshortening about the hip).
     Arms hang from a real shoulder bar and legs from hip corners, so
     silhouettes have torso mass and collapse correctly during spins.
     Move-level `spin` / `partner_spin` are continuous yaw turns across
     the move (pirouettes, underarm turns); dance-level
     `hold: (lead_joint, partner_joint)` makes a "together" pair clasp
     hands (two-link IK) — moves opt out with `hold: False` for
     turns/leaps/swaps.

   Move-level `hits: [key indices]` marks big stretch poses: arriving
   at one normally flows through, but if the arrival lands inside a beat
   burst window (~0.45s after a loud-enough kick) the dancer HOLDS the
   pose (~0.2-0.5s, groove keeps it alive) as a synced flourish and the
   flame burst fires AMPLIFIED (1.6× count, boosted magnitude) from the
   stretched limb. Mark the wide/extended keys of every big move.

   **Never-slide rule (Javi):** bodies must walk/step to any new stage
   position — a locomotion gait overlay (in dancer.py `_dancer_joints`)
   automatically converts horizontal anchor velocity into alternating
   steps, so `travel`, slot changes and swaps read as walking. Dances
   whose signature IS a glide opt out with `locomotion: False`
   (moonwalk, worm).

   **Same-plane rule (Javi):** the second dancer always dances NEXT TO or
   WITH the lead on one stage plane — `travel` moves both dancers the
   same direction (never mirror-opposed drift), and nothing may make the
   pair overlap or read as foreground/background layers (only `swap`
   moves may briefly cross them).

2. **Author moves + the dance** in `DANCES`. A move is a list of key pose
   names (`"name!m"` mirrors); each key lands on a beat (or every `tempo`
   beats). Move extras: `accent` (burst joint), `flourish` (always burst at
   move end), `spin` (whole-figure rotation over the move), `tilt` (floor
   moves — per-key figure tilt, see the worm), `travel` (net drift),
   `swap` (partner slot exchange), `partner_keys` (explicit second-dancer
   poses for "together" dances), `next` (staged chaining — the worm must
   get down before it wiggles), `ease` override. Dance-level: `partner`
   mode (`mirror` / `sync` / `together`), `tempo`, `ease` (`cosine` /
   `sharp` / `linear`), `energy` tier, `idle` pose, `bounce`.

3. **Validate + eyeball** (from the SpotFX repo root; needs numpy+PIL, use
   the ledfx venv):

       /home/javi/ledfx/bin/python -m tools.dancesmith validate
       /home/javi/ledfx/bin/python -m tools.dancesmith list
       /home/javi/ledfx/bin/python -m tools.dancesmith preview \
           --dance my_dance --png build/dances/my_dance.png

   Then **Read the PNG** — every move is a row (key poses + midpoint
   tweens) rendered through the crystal-mapper hex mask exactly the way
   the effect draws (bone sampling + 1.5 px soft splat). `--ascii` prints
   frames inline, `--partner` renders the second dancer's poses,
   `--move X` isolates one move. Watch the LOW COVERAGE warnings
   (< 20 lit cells = the pose is invisible on the hex lattice). Hex rules
   of thumb: strokes ≥ 2 px (the effect clamps `blob_size` ≥ 1.5),
   crossing arms must poke PAST the torso or they vanish into it.

4. **Restart LedFX** (`systemctl --user restart ledfx` — the venv installs
   ledfx-src editable) and eyeball live:

       curl -X POST localhost:8888/api/virtuals/crystal-mapper/effects \
           -d '{"type":"dancer","config":{"dance_type":"my_dance"}}'

5. **Register the name in SpotFX** — `config/effect_params.json` →
   `effects.dancer.params.dance_type.options` (that list feeds the
   "Dance Type" label param used by scenes/morphs), then
   `systemctl --user restart spotfx`. If the dance should be picked by
   trigger intensity, add it to a band in
   `scripts/seed_dancers_scene.py` (`DANCE_BANDS`) and re-run the seeder.

6. Update `web/src/help/helpContent.ts` if anything user-facing changed
   (per CLAUDE.md).

## How the effect consumes the library

- The sequencer keeps ONE pose chain (`pose_from → pose_to`), advancing on
  beat-oscillator wraps (keybeat-style, with a wall-clock fallback when the
  tempo tracker stalls) — the partner derives from it (mirrored / synced /
  `partner_keys`), so the pair can never desynchronize.
- EVERYTHING blends: dance switches wait for the next beat and tween from
  the current body position; quiet passages ease into the dance's `idle`
  sway; config changes never cut.
- `reverse` = the partner toggle (2 dancers = "reversed"). Entry/exit
  choreography (Neo drop-in, catch, superman, spin-off), the rotation
  somersault, and effect-transition stunts live in `dancer.py`
  (`_update_stunts`) — dances don't need to care.
- A beat-locked groove layer (`_apply_groove` in dancer.py) adds pendulum
  arm swing, shoulder/hip counter-sway, head bob and a lift into every
  beat on top of the key poses — per-dance `groove` amplitude (robot is
  deliberately stiff at 0.3), scaled by the music. Fluid dances use the
  `flow` ease: limbs overshoot the pose ~7% and settle (follow-through).
- Flames are thrown by the motion itself: each frame the fastest-moving
  extremity (relative to the hip) is the "flourishing limb"; on beats
  above `burst_threshold` it fires mid-swing along its own velocity,
  inheriting momentum. A still body radiates from the chest. The move's
  `accent`/`flourish` flags now only guarantee the end-of-move payoff
  burst. Mirrored volleys collide at the midline and flare upward.
