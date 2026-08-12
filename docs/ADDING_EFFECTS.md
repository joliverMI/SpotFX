# Protocol: adding a new LedFX effect + SpotFX integration

The repeatable checklist for taking a new visual from idea to "member of the
scene rotation". Model code on the newest completed effect (today: `eye`,
before it `dancer` — both cribbed from `blackhole`).

## Workflow gate (IMPORTANT)

The work splits around a **manual tuning gate**:

1. **Phase 1 — LedFX effect.** Build, register, smoke test. Leave it running
   on a matrix virtual, then **tell Javi it's ready to tune and STOP the
   LedFX work**.
2. **Phase 2 — SpotFX backend prep** (safe to do while waiting): registry
   entry, phase wiring, aliases, seeder script *written but not run*.
3. **Gate:** Javi tunes the defaults in the LedFX UI and says done.
4. **Phase 3 — finish:** absorb the tuned values into defaults + setter
   presets, run the seeder (scene + scene groups), update the Help page,
   verify live.

Scenes must NOT be seeded before the gate — the setter bakes shape/reactivity
presets, and pre-gate values would fossilize untuned guesses.

## Phase 1 — LedFX effect (`/home/javi/ledfx-src`)

New file `ledfx/effects/<type>.py`, class `<Name>2d(Twod, GradientEffect)`
with `NAME` / `CATEGORY = "Matrix"`. Effects are auto-discovered by the
registry's module scan — there is no registration table.

Conventions (see `blackhole.py`, `eye.py`):

- **State that must survive config patches goes in `__init__`, not
  `do_once`** — `do_once` re-runs on *every* config change; per-frame ramps
  would reset your world mid-song. `config_updated` runs during
  `super().__init__`, so lazily-created state there needs a `hasattr` guard.
- Audio: `frequency_range` (`POWER_FUNCS_MAPPING`) + `impulse_decay` filter;
  `data.bpm_beat_now()` sets a `_beat_pending` flag consumed in `draw()`.
- `HIDDEN_KEYS`: `gradient_roll` (superseded by your own spin), `color_blend`
  (colors must update in place — recreation kills live state).
  `ADVANCED_KEYS`: `phase`, `phase_progress` (advanced, not hidden, so the
  arc can be hand-scrubbed in the LedFX UI).
- Prefer float params over `integer` (the int-tween coercion gotcha is
  patched in `_apply_config` + SpotFX `ledfx_client`, but floats sidestep it).
- Shared shape-param names where they fit (`x_offset`, `y_offset`,
  `blob_size`, `radius_scale`, `reverse`…) — SpotFX morphs address these as
  cross-effect sub-fields (see Phase 2).

**Charge/Lull/Drop** (`phase` + `phase_progress` config pair): SpotFX writes
`{"phase": X, "phase_progress": 0.0}` instantly, then ramps `phase_progress`
0→1 over the event's ramp. In the effect:

- Edge-detect the phase key in `config_updated` (pending flag consumed in
  `draw`); a fresh instance must baseline to `"none"` so a stale persisted
  key can't edge-fire.
- Orphan watchdog via `particle_handoff.phase_release_due()` — a charge/lull
  whose drop never arrives self-releases as a silent drop.
- The drop payoff self-resets with
  `self._apply_config({"phase": "none", "phase_progress": 0.0},
  validate=False, fire_event=False)` so an identical later write edges again.

**Optional — particle handoff + phased transitions:** only if the effect
should adopt/donate on-screen particles across effect switches
(`_handoff_snapshot` / `_adopt_handoff` / `deactivate`, see `blackhole.py`).
If the switch choreography has a mid-crossfade payoff, also append a
`PhasedTransition` in SpotFX `services/transition_phases.py` with
`anchor_frac` matching the LedFX constant. Plain effects (eye) skip both —
LedFX crossfades handle the switch.

**Testing:**

1. Offline harness (scratchpad): instantiate with a mocked core/virtual,
   drive `draw()` through idle, beats, and the full charge→lull→drop arc;
   assert lit-pixel expectations, phase self-reset, and no NaNs.
2. `systemctl --user restart ledfx` → effect present in `/api/schema`
   (port 8888).
3. Set it live on a matrix virtual
   (`POST /api/virtuals/<vid>/effects {"type": ...}`), scrub
   `phase`/`phase_progress` via PUTs, then
   `journalctl --user -u ledfx` for tracebacks.
4. Leave it running on the matrix for the tuning gate.

## Phase 2 — SpotFX backend prep (while waiting)

- **`config/effect_params.json`** — the single registry driving morph
  aspects, label resolution, UI ranges, and setter defaults:
  - `effects.<type>.params`: every user-facing param with `label` (reuse
    shared labels: "X Offset", "Audio Band", "Gradient"…), `type`,
    `min`/`max`, `aspect` (`shape` / `reactivity` / `color` / `bg_color` /
    `brightness`), plus `aspect_scale` (how hard aspect-wide morphs drive
    it), `distribute: false` (exclude from aspect-wide distribution),
    `flip_sign`, `scale_offset` (x/y offsets), `accent` (the effect's
    third-color param), `note`.
  - `effects.<type>.defaults`: mirror the LedFX schema for now — replaced by
    tuned values in Phase 3.
  - Add the type to `morph.supported_effects`.
- **Shape sub-field aliases** — generic Shape morphs speak in shared
  sub-fields (`edges`, `twist`, `blob_size`, `radius_scale`, `swirl`…). If
  the effect's raw name differs, extend
  `_SHAPE_SUBFIELD_ALIASES` in `services/morph_compiler.py`
  (eye: `blob_size→pupil_size`, `radius_scale→iris_size`).
- **`services/trigger_engine.py` → `PHASE_EFFECTS`**: add the type if it
  implements `phase`/`phase_progress`, so Charge/Lull/Drop events reach it.
- `systemctl --user restart spotfx`, then check
  `GET :8000/api/morph/aspects` lists the effect + its params.
- **Write `scripts/seed_<name>_scene.py`** modeled on
  `seed_dancers_scene.py` — deterministic `uuid5` ids so re-running upserts.
  **Do not run it yet.**

## Phase 3 — after Javi tunes

1. Read the tuned config off the live virtual
   (`GET :8888/api/virtuals/<vid>`) and copy the values into BOTH
   `effect_params.json` defaults and the seeder's setter presets.
2. Run the seeder. It should create:
   - **"<Name> Scene Setter"** (composite): parallel nodes —
     Matrix (`morph_step`: effect switch + shape/reactivity presets, instant
     writes coalesce with the switch), Strips (the 1D sibling or designated
     1D effect), Singles, and a `set_color "__scene_group__"` node.
     Intensity-adaptive presets use `trigger_intensity` map bindings.
   - **"<Name>" scene** (`scene_update`) lanes: First = setter ref · Rest =
     `scene_morph` advance + Color Flare · Shape = random group of
     shape-morph options · Color = color-group cycle (preserve_effect) /
     ambient flip. Leave lanes 5–7 (Charge/Lull/Drop) EMPTY — the canonical
     phase events drive the effect's native choreography via
     `PHASE_EFFECTS`.
   - Group membership: insert into the target `scene_group` events by their
     EXACT live names — check `GET /api/events` first (it's "Drop Group",
     not "Drop"; a wrong name silently no-ops).
   - "Temporary bump that reverts" morphs (flares): `ledfx_effect_param`
     action with `fallback_s` — LedFX restores the prior config server-side.
3. **Help page** (definition of done): add the effect + scene to
   `web/src/help/helpContent.ts`, `cd web && npx vite build`.
4. Verify: fire the setter (`POST /api/events/preview`), confirm the LedFX
   live effect + params, fire Charge/Lull/Drop, watch both journals. Then
   ask Javi for the eyeball pass.
