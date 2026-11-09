# The Light Show (/show)

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## THE LIGHT SHOW (`/show`) — named sets of actions, fired now or ARMED (all three phases shipped)

Plan: `/home/javi/fleet-spotfx/data/light-show-plan/report.md` (his spec in
its `brief.md`; his answers: ONE High + ONE Low trigger per song, "non-
reactive" = a steady colour). Phase 1 shipped the catalogue, sets, End show
and the per-fixture output layer; phase 2 added arming (next scene change,
High/Low); phase 3 (below, this section's own tail) added the phone-first
Run view, drag reorder on the Build view, Sonic, and the expected-scene-
change countdown. Read the module docstrings
before touching any of it — `spectra/services/show_actions.py` (catalogue,
executor, baselines, End show), `show_output.py` (targets, holds, levels,
the gate), `fx/device_output.py` (the frame-level layer, `fx/VENDOR.md`
#41), `spectra/models/light_show.py` (why two stores, and the phase-2/4
slots already in the schema). Six things:

- **THE REGISTRY IS THE EXTENSION POINT.** One `show_actions.register()`
  per action kind declares params, apply and put-back; the Build view
  renders the SERVED catalogue, so a new kind needs no frontend change.
  Room-setting kinds supply `room_patch` and go through
  `room_controls.apply_patch` — **the ONE room-controls writer**, factored
  out of `PUT /api/room-controls` so the show and the room bar run the
  identical reconcilers (consecutive setting steps coalesce into one save).
- **ROOM EFFECTS ARE A FIRST-CLASS ACTION** through `room_effects.start()`
  and its held-room program (`show_actions.RoomEffectRunner` is the seam);
  the show only heartbeats the hold for the step's duration. A future room
  effect authored in the Room FX store is armable/triggerable with no
  Light Show change — `tests/test_light_show.py` proves it with a stub kind.
- **THE OUTPUT LAYER SITS AT THE DEVICE FLUSH and composes, never fights**:
  Level/Dark multiply a frame that already carries the dimmer and any
  room-effect gain; Steady is scaled by `show_output.steady_scale` (dimmer
  × room-effect gain). The show keeps rendering underneath every hold, so
  "back to Show" lands in step. Idle path is one dict check, byte-identical
  (`tests/test_device_output_landing.py`, real pipeline, neighbour-on-the-
  same-virtual untouched, red with the seam bypassed).
- **THE GATE (`show_output.refusal()`)**: acts only while SPECTRA owns,
  the stack is up and the engine is live; stands down (fires refused by
  name) while a preview, colour preview, camera run or night run holds
  the room. A room effect's OWN preview hold does NOT count as a preview.
  It never takes or releases the room; `release.release_room` calls
  `show_output.on_release()` BEFORE the fade.
  **Suspension is `show_output.suspension_reason()`, narrower than
  `refusal()` by one case: a COLOUR-SET preview alone keeps the output
  layer in force** (2026-10-07, his "previewing a colour set pushes to
  100%": suspension dropped the house mode's base levels, so Standard's
  12% crystal ran at full and mode-off fixtures were streamed). It still
  stands down — fires refused, house on standby. Anything that must see
  raw frames, or a scene/flare preview, still suspends. Spec:
  `tests/test_colour_preview_brightness.py`.
- **PUT BACK**: device holds structurally (let go = fade into the live
  show); settings from a BASELINE — End show restores only while the value
  still equals what the show wrote, otherwise leaves it and NAMES it.
  Scene on/off is a raw single-key patch (`scene_store.set_disabled`);
  colour-set on/off goes through SpotFX's `/api/color-sets`
  (`show_actions.color_set_writer`, faked in tests).
- **Ambient's per-press snap** (`ambient_music_gate.reconcile_now(snap=)`)
  is passed only when asked, so every existing caller/test double keeps
  the old call shape. Stores are isolated per test by conftest's
  `_isolated_light_show`. Help: section `light-show` (topics linked from
  the page, the strip and the served catalogue's `help_topic`s).

**PHASE 2 — ARMS AND THE HIGH/LOW TRIGGERS (2026-10-04).** Read
`spectra/services/show_arms.py` (triggers, replace-not-stack, one-shot/
repeat, this-song-only, finish-on-the-mark, expiry, the gate that never
consumes) and `show_cues.py` (derivation, edges, drop seeding, overrides)
first. Five things:

- **CUES ARE DERIVED AT PLAY TIME, NEVER STORED AS TRIGGERS** — only his
  dragged positions (`storage/spectra/show_cues.json`). A stored cue row
  would stamp the song "authored" (silencing its analysed show under My
  triggers only) and block auto-generation. The score is
  `midsong_generator.section_energy_shift` — the SIGNED form of the
  planner's rank, `section_energy_change` is now its `abs()` — and the time
  is the planner's own placed time, so a High sits on its scene change.
- **THE TRIGGER CLOCK OWNS THE CROSSING**: `TriggerEngine.tick()` runs
  `_tick_show_cues` BEFORE stored triggers (two no-op hooks wired in
  `engine.py`), exactly once per approach via `_fired`; a cue jumped over
  by a seek further than `SHOW_CUE_SEEK_SKIP_MS` is skipped, never late.
  Cues are independent of `scene_change_mode`.
- **"NEXT SCENE CHANGE" IS READ IN `engine.on_scene_fired` BEFORE the
  conductor takes the new scene** (a re-fire is not a change), and
  `show_actions.executing()` excludes a change the show itself caused.
- **FORCE SCENE DOES NOT STARVE A SCENE-CHANGE ARM (2026-10-09, his report:
  an arm armed on "next scene change" kept resetting its "Scene change at
  least: xx" countdown and never fired).** Force Scene reasserts the SAME
  pinned scene on every automatic pick (`scene_sequencer.fire_scene_by_id`),
  so the scene `engine.on_scene_fired` saw never moved and the bullet
  above's own comparison never saw a "real" change — even though that same
  re-fire's `dwell.note_fired()` call was what kept resetting the readout
  the whole time. His ruling: "do 1" — the arm still releases at the moment
  a scene change would have happened; the room keeps wearing the pinned
  scene. `fire_scene_by_id` now captures the scene id a caller actually
  asked for BEFORE the pin substitutes, and threads it through
  `scene_compiler.fire_scene`'s `requested_scene_id` kwarg (passed only
  when it differs from the fired scene, so every pre-existing test double
  of `fire_scene`/`on_scene_fired` keeps its old call shape) to
  `engine.on_scene_fired`, which uses it — not the pinned `scene.id` — for
  the comparison above and for `_tell_sequence`, so a Show Sequence's "wait
  N scene changes" counts the suppressed moment too. Spec:
  `tests/test_scene_arm_under_force.py`.
- **FINISH ON THE MARK**: the clock fires a cue at the largest lead any
  armed set needs; each set waits the difference to its own
  (`show_arms.lead_ms`, longest fade before the first pause). The whole set
  moves early — stated on the arm card.
- Phase 1 shipped two defects the room proof found, both fixed here: the
  supervisor crashed every tick on the real `Virtuals` registry (no
  `.items()` — the test fakes now have the real registry shape), and
  `fire_history` had no `show` bucket, so the show log never recorded.
  Spec: `tests/test_light_show_arms.py`, `scripts/check_show_cue_flags.mjs`.

**A SET CAN ALSO BE ARMED ON THE NEXT DROP, LULL OR CHARGE — ONE BUTTON
THAT CYCLES (2026-10-19, the Admiral: "on the light show events, add a
button for next drop, lull, and charge. make it one button that cycles
through those to reduce clutter. use thr icons and colors from the
timeline for those events").** `show_arms.TRIGGERS` is six now, not three
(`PHASE_TRIGGERS = ("drop", "lull", "charge")`); `MARK_TRIGGERS` is the
five that sit at a KNOWN song-time moment, so a countdown and the
finish-on-the-mark lead apply to a phase exactly as to a High. The
moments are `drop_firing.phase_moments(view)` — the ONE pure rule, the
same drop-sequence data the Timeline draws as gold/sky/magenta shapes.
Six things:

- **THE SOURCE: every firing sequence's DECLARED members plus his own
  authored charge/lull/drop triggers**, his winning a collision within
  two beats (otherwise a detection matching one of his marks yields the
  same drop twice). A SUGGESTED detection is not a moment (it waits for
  his confirm, and the room ignores it) and neither is a dismissed one.
  Several of each per song is normal — his real EDM songs carry a dozen
  drops — so `cue_plan` returns one entry per moment and a one-shot arm
  takes the FIRST its clock crosses, which is what "the next drop" means.
- **MODE-INDEPENDENT, AND ON THE MARK.** A phase cue is a moment in the
  MUSIC, the High/Low precedent (`show_cues.py`'s "a cue exists on every
  analysed song, his own triggers or not"), so it is not narrowed by
  `scene_change_mode` and `phase_moments` takes no mode at all. It is
  also NOT relocated by `drop_timing`'s offset (default -400 ms): that is
  resolved per fire from the room AND the SHOWING scene, so it is neither
  constant nor knowable without I/O on the tick path, and an arm landing
  on the mark the Timeline draws is the honest reading. Both arguments
  live in that function's own docstring — don't re-derive them.
- **NOTHING NEW FIRES IT.** The phases ride the EXISTING High/Low path
  unchanged: the same `cue_plan`/`on_cue` pair, the same
  exactly-once-per-crossing memory in `trigger_engine._tick_show_cues`
  (its key is `(f"show-cue:{level}", cue_ms)`, already distinct per
  moment), the same show clock (`av_sync_lead` + `known_buffer` — **this
  build touches no audio offset, order 30**), the same gate that never
  consumes an arm, and the same `house.confirmed_wrong_device()` gate in
  `services/engine._show_cue`.
- **THE ENGINE PUBLISHES THE MOMENTS OFF ITS OWN PER-TICK MEMO.**
  `TriggerEngine._drop_state` returns a third element and
  `_sequence_triggers` stores `(uri, moments)`; `phase_cue_moments(uri)`
  reads it, and `show_arms.phase_moments` is the seam whose default asks
  it. That ordering matters: `drop_sequences.view` costs a full
  ~9.5MB `triggers.json` parse and `cue_plan` is asked EVERY tick, so
  never read the view from `show_arms`. **`None` from that seam means
  "not worked out for this song yet" and is a different answer from
  `[]`** ("this song genuinely has no drop") — `status()["song"]["phases"]`
  carries both (`known`, per-class `next`/`counts`, a `reason`) so the
  armed board can say "none on this song" without guessing. It is one
  tick stale on a brand-new song (`_tick_show_cues` runs before tick()
  resolves the triggers the view needs), which costs nothing beyond the
  1 ms rearm window at the first observed position — `phase_cue_moments`'
  own docstring has the arithmetic.
- **THE UI IS ONE BUTTON, and `spectra/web/src/lightshow/phaseArmCycle.ts`
  is the whole rule** (cycle order off → drop → lull → charge → off, what
  one tap arms AND disarms, the look, the words). Cycling is
  disarm-then-arm because `show_arms`' replace rule is "the same set on
  the SAME trigger" — arming drop→lull without cancelling the drop leaves
  the set armed on both. The glyph is `iconRegistry`'s `pulse` (the
  generic drop-sequence phase glyph) and the colour is IMPORTED from
  `timeline/dropSequences`' own `PHASE_COLOR`; a hex literal in that
  module is what its check script forbids. Mounted on `RunView.tsx` and
  Home's `HomeQuickRuns.tsx`; state comes from live `arms`, never a click
  flag. A phase arm is deliberately NOT drawn as a Light Show marker on
  the Timeline (the phases already have their own shapes there) — the
  drop-sequence legend names it in words instead, in that phase's colour.
- **A SEQUENCE STEP AND A PLAYLIST STEP STILL CANNOT.**
  `SEQUENCE_ARMS`/`WAIT_TRIGGERS`/`PLAYLIST_STEP_TIMINGS` stay the named
  triggers only, each with the reason on its own constant: a Wait counts
  NAMED triggers, where "2 drops" means something quite different from
  "2 High Triggers". Sonic DOES reach every phase — `show_console.
  TRIGGER_CHOICES` is `show_arms.TRIGGERS` itself, read not re-typed, so
  the MCP wrapper's `_ArmTriggerEnum` widened for free.

Spec: `tests/test_light_show_arms.py` section 5 (the real trigger clock:
the right phase fires, a one-shot takes the first, a repeat takes every
one, disarming cancels, a drop-less song keeps the arm, the gate never
consumes it — verified RED against both halves removed),
`tests/test_phase_arm_cycle.py` → `scripts/check_phase_arm_cycle.mjs` +
`check_light_show_run_icon_buttons.mjs` §SIX. Help: `show-phase-arming`.

**PHASE 3 — THE RUN VIEW, DRAG REORDER, SONIC, AND THE SCENE-CHANGE
COUNTDOWN (2026-10-04).** Read `spectra/services/show_console.py`'s module
docstring first (Sonic's authority boundary here, the same shape
`room_effect_console.py` draws). Four things:

- **A NEW SONIC DOMAIN, `"show"`** (`spectra/services/show_console.py`,
  merged into `settings_agent.ALL_OPERATIONS` alongside the other domain
  modules — same discipline, same trap: a new operation needs its wrapper
  in `settings_mcp_server.py` AND the CLI's own `TOOL_NAMES` manifest, or
  `_verify_tool_manifest()`/`test_settings_mcp_server_starts_from_a_clean_
  cwd` refuse it). Covers exactly his ask: fire/arm/disarm/disarm-all/
  show_status/hold_device/dim_device/create_show_set/move_high_low/
  end_show. `hold_device`/`dim_device` build an ad-hoc `device_state`/
  `level` `ShowAction` and run it through the SAME `show_actions.fire()`
  the Build view's buttons call — no second write path. Every name (a set,
  an arm, a fixture, a category) is resolved by `show_console._resolve_*`:
  an exact id/case-insensitive-name match succeeds, anything else is
  REJECTED with `difflib.get_close_matches` candidates — never guessed.
  `create_show_set` mints a fresh id but set NAMES are unique
  (`show_store.put_set`'s `SetNameTaken`), so a name clash is rejected,
  not silently overwritten — the one place this domain's "never overwrite"
  rule differs from `scene_console.create_scene`'s pure fresh-id version.
  Editing an EXISTING set's steps and starting/stopping a room effect
  directly are deliberately excluded (authoring stays the Build view's
  job; a room-effect step still fires/arms through the ordinary set
  operations with no special case). Reachable from the Light Show page's
  own floating 💬 (`SonicChatPopover`, now taking an optional `helpTopic`
  prop so each mount points its "?" at its own domain's help topic rather
  than always `sonic-scenes`).
- **THE RUN VIEW IS A SEPARATE COMPONENT OVER THE SAME POLLED STATE**
  (`spectra/web/src/lightshow/RunView.tsx`) — a Build/Run tap toggle in the
  page head (`isPhone` only labels the Run tab "(recommended)" now; the
  tab that actually SHOWS on open is the Sequence tab's own Run view,
  unconditionally — see "THE LIGHT SHOW TAB DEFAULTS TO SEQUENCE → RUN"
  below). Run reuses `ArmBoard` and the exported `ShowNowPanel` verbatim
  (one countdown source, one Holding-list source — never a second copy
  that could disagree), and big Disarm all / End show buttons. Run never
  edits a set. **Each set's own row is ONE TAP PER TIMING, no menu
  (reworked 2026-10-08, his ask verbatim: "make each row instead have
  buttons for each thing with an icon ... i just tap it and it happens")**
  — the original tap-to-open-sheet (name button → a second screen of four
  labeled buttons → Cancel) is gone; a row now shows the set's name plus
  four inline-SVG icon buttons (`iconRegistry.ts`: ⚡ bolt = fire now,
  🐇 bunny = arm on the next scene change, ▲ up arrow = arm on the next
  High Trigger, ▼ down arrow = arm on the next Low Trigger), each already
  the complete action for one of the four timings the backend has always
  supported — no new backend semantics. A set armed for more than one
  trigger at once shows an "Armed for the …" tag, with its own Cancel
  button, for EVERY active arm, not just the first.
- **DRAG REORDER ON THE BUILD VIEW** — this phase's native HTML5 DnD
  (`dataTransfer`, plus ↑/↓ buttons for keyboard/no-pointer use) is
  SUPERSEDED, 2026-10-11, by `@dnd-kit` (`SortableList.tsx`) — the ↑/↓
  buttons are gone, replaced by the same ⠿ handle's own keyboard-sortable
  drag. See "SETS THAT RUN SETS, AND THE BUILDER V2" below.
- **THE EXPECTED-SCENE-CHANGE COUNTDOWN IS A FLOOR, NAMED AS ONE** —
  `show_arms.status()`'s `song.expected_scene_change_s` is `dwell.
  status()["remaining_s"]`: the showing scene's own minimum-hold floor,
  `None` when nothing is tracked. It is NOT a prediction of when the next
  change actually happens (nothing in this codebase predicts that), and
  `song.expected_scene_change_is_floor: True` plus the frontend's own
  `sceneChangeLine()` wording ("at least …") keep that honest rather than
  implying precision the number doesn't have.

Spec: `tests/test_show_console.py` (every op, the close-match refusals, the
room-effect compatibility proof), `tests/test_light_show_arms.py`'s own
dwell-floor test, `tests/test_scene_console.py`'s widened operation-set
proof, `scripts/check_light_show_run_icon_buttons.mjs` (the Run view's
icon-button row: four real inline-SVG buttons, each a one-tap complete
action, and every active arm on a set shown, not just the first).

**EFFECT MODIFIERS — Pulse reactivity, Pulse brightness floor/ceiling,
flares on/off (2026-10-08).** `spectra/services/show_mods.py`'s docstring
is the binding statement. Four things:

- **THEY HOLD PER VIRTUAL, NOT PER FIXTURE** — Pulse is an effect on a
  virtual and a flare is a write to one. A fixture target takes every
  fixture sharing its virtual (one Hue fixture = all of `hues`), and the
  step's outcome names them. Holds live in `LightShowState.pulse_mods`/
  `flare_blocks`; show_output's tick/repush/release_all/on_scene_change/
  on_release/reset carry them, so End show and a room release end them.
- **PULSE IS MODULATED THROUGH `fx/pulse_modulation.py`, never a config
  write** (VENDOR #66) — a config write would fight scene fires, the Pulse
  feed and the param watchdog. Reactivity scales only the live-audio hit
  term and the rainbow hit-step (the Admiral's option A). **A lull's dark
  beats a brightness FLOOR** (2026-10-13, his "goes dark at the end of the
  lull ... like it used to"): a held floor once kept the Hues at a glow
  through every lull — before reasoning about "Pulse won't go dark", read
  the held `pulse_mods` (engine status `light_show`). `pulse-effect` skill;
  `tests/test_pulse_lull_dark_floor.py`.
- **FLARES OFF IS `ResponseEngine._flare_states()`** (wired as
  `flare_blocked` in engine.py; scratch preview engines are unfiltered):
  every flare kind's loop AND `_drive_phase`/`rearm_phase` read it, so a
  flares-off target gets no flare and no charge climb / lull darkness /
  drop burst (his ruling). Releases and the analysed scene-cue colour
  moment (`_color_jump(flare=False)`) are deliberately NOT filtered. A NEW
  flare kind or phase path must iterate `_flare_states()`, not
  `conductor.virtuals`, or it leaks onto the Hues.
- **Every entity picker in the editor is `SearchSelect`**, labelled by
  `spectra/web/src/lib/pickerOptions.ts` (shared with the top bar's Force
  Scene/Colour); only short fixed enums stay `<select>`. Proofs:
  `tests/test_show_flares_off.py` (real headless pipeline, red control),
  `tests/test_pulse_modulation.py`, `node scripts/check_light_show_pickers.mjs`
  (needs the dev-only jsdom). Help: `show-pulse`, `show-flares`.

**RE-FIRING THE SAME HOLD KIND ON THE SAME TARGETS RESTARTS IT, NEVER
STACKS A DUPLICATE (2026-10-08, his report: two "Flares off until
released" entries from firing the same set twice, and it "should just
restart, not queue").** `show_mods.add_pulse_mod`/`add_flare_block` and
`show_output.add_level` each remove any existing hold whose virtual/
device id SET is an EXACT match (and, for Pulse, the same DIMENSION —
`reactivity` vs `floor`/`ceiling`, since those genuinely compose on one
target) before appending — so the newest fire wins outright (fresh
timer/until) instead of a second, visually duplicate entry. A hold on a
genuinely DIFFERENT target set, or the OTHER Pulse dimension on the same
target, still composes exactly as before (`PulseModHold`/`LevelHold`'s
own "several stack" docstrings, narrowed to say so). Spec: `tests/
test_light_show.py::test_a_level_on_the_same_target_restarts_instead_of_
stacking`, `tests/test_show_flares_off.py`'s `test_refiring_*`/
`test_pulse_*` tests.

**THE RUN VIEW'S ARMED ICON HIGHLIGHTS FROM LIVE `arms` STATUS, NEVER A
LOCAL CLICK FLAG (2026-10-08).** Each of the four per-set icon buttons in
`RunView.tsx` (bolt/bunny/up/down) computes its own `armed` class from
`arms.armed.filter(a => a.set_id === s.id)`'s `on` values on every
render — so a refresh, or an arm placed from Sonic/the Build view,
lights the right icon with no click of this component's own involved.
Spec: `check_light_show_run_icon_buttons.mjs` §FIVE.

**"+ ADD A STEP…" IS A DIALOG, NOT AN INLINE PICKER (2026-10-08, his
report: "it's so low on the page I can't see the options well, and it
doesn't expand anywhere").** `SearchSelect`'s dropdown is `position:
absolute` under its own input with nothing below it to clamp against but
the viewport (see that component's own docstring) — on a set with
several steps the "+ Add a step…" control used to sit inline at the
BOTTOM of the steps list, so its dropdown opened with only
`DROPDOWN_MIN_HEIGHT` (80px) of room, sometimes entirely below the fold.
`LightShowPage.tsx`'s `AddStep` is now a plain button opening
`AddStepDialog` — the same `position: fixed; inset: 0` centered-card
shape every other dialog here uses (`SpectraTriggerDialog.tsx`,
`FlareKindEditDialog.tsx`) — with its `SearchSelect` given a new
`autoFocus` prop (`SearchSelect.tsx`) so the picker is already open the
instant the dialog mounts, no second click. Reuse `autoFocus` for any
future picker that IS a dialog's own content rather than re-deriving
"open immediately" another way. Spec: `check_light_show_add_step_dialog.mjs`.

**A SET HAS A DUPLICATE BUTTON, PLACED RIGHT AFTER THE ORIGINAL
(2026-10-08, his ask; the button's own label moved from the "⧉ Duplicate"
text glyph to an SVG icon + word in the 2026-10-11 Builder V2 rework, same
as every other editor-head button).** `show_store.put_set` grew `after_id` (a
brand-new set only — ignored on an update of an existing one): `POST
/api/light-show/sets` accepts it on `SetBody`, and the frontend's
`duplicate()` (`LightShowPage.tsx`) posts a fresh, independent copy
(every step given a NEW id) named `"<name> copy"`, uniqued against the
loaded sets (`"<name> copy 2"`, …) if that's taken too, with `after_id`
set to the original — landing it immediately after the original in his
list rather than appended at the end, and switching the editor to the
already-saved copy. Spec: `tests/test_light_show.py::
test_after_id_places_a_new_set_right_after_the_named_one` +
`test_duplicate_set_via_the_api_is_independent_saves_fires_and_is_placed_
right_after`, `check_light_show_duplicate_set.mjs`.

**SHOW SEQUENCES — the Sequence tab (2026-10-09, his ask: "a sequence of
pre-armed sets ... goes in order ... never skipping ahead").**
`spectra/services/show_sequence.py`'s docstring is the binding statement.
Four things:

- **A SET ITEM ARMS THROUGH `show_arms.arm()`** (the Run view's own call),
  `source="sequence:<run id>"`, and completes when that arm fires
  (`show_arms._fire` → `show_sequence.on_arm_fired`); an instant item fires
  through `show_actions.fire_set`. A sequence arm never expires on the
  board's own clocks and never replaces (or is replaced by) a hand arm —
  `show_arms.is_sequence_arm_source` is the one test.
- **ONE TRIGGER, ONE STEP**: `show_arms.on_scene_change`/`on_cue` pick the
  arms a trigger fires BEFORE telling the sequence (`_tell_sequence`), so a
  Wait it completes cannot also fire the set armed after it; and the Wait
  is told before those arms fire, so the trigger that completed a set never
  counts for the Wait after it. Keep that order.
- **THE RUN LIVES IN `LightShowState.sequence_run`** (a snapshot of the
  items, so an edit never shifts a running position) and resumes at its
  current item on the first supervisor tick of a new process
  (`show_sequence.tick`); `last_uri` stops the still-playing song counting
  as a new start. Songs are counted from `engine._on_track_uri`; a room
  release PAUSES the run (`show_output.on_release`, before the arms expire).
- **Song-list Waits search his profile library** (`spectra/services/
  song_library.py`, `GET /api/light-show/songs`, `spotify:track:` URIs
  only). Sonic: `show_console.SEQUENCE_OPERATIONS` (read + start/stop/
  pause/resume/next/previous/fire by name; authoring excluded). Specs:
  `tests/test_show_sequence.py`, `node scripts/check_show_sequence_ui.mjs`.

**SETS THAT RUN SETS, AND THE BUILDER V2 (2026-10-11, his ask: "reference
other sets within sets ... set a bunch of default values ... and call them on
several sets"; "the UI for building events/actions in spotfx was really good
... the drag and drop ordering, the collapsability, the copy ability").**
`spectra/services/show_refs.py`'s docstring is the binding statement. Four
things:

- **A `call_set` step is EXPANDED, never applied**: `show_actions.fire()`
  replaces it with the called set's steps (`show_refs.expand`) before
  anything runs, so it is inline in every sense — a pause inside pauses the
  caller, room-setting steps coalesce across the boundary, a later step
  wins. Anything that reads a set's steps to decide something (preview,
  conflicts, problems, an arm's `lead_ms`) must read the EXPANSION, not
  `set.actions`. Run steps carry `via` (the set names they came through)
  and a path id (`<call id>/<step id>`, unique when a set is called twice);
  the show log carries `via` too.
- **A reference, not a copy; no cycles**: `show_store.put_set` refuses a
  save that would make a set call itself (`SetReferenceCycle` → 409
  `reason: cycle`), and `expand` refuses one at run time too (a failed step,
  never recursion). `DELETE /api/light-show/sets/{id}` answers 409
  `in_use` with `used_by`/`used_in_sequences` unless `?force=true`; a call
  to a deleted set then fails by name. Sonic reads references
  (`list_show_sets`) but adding a call is step authoring, excluded.
- **The builders use `@dnd-kit` (a spectra/web dependency since this
  build — a deploy needs `npm ci` there)** through
  `spectra/web/src/lightshow/SortableList.tsx`: only the ⠿ handle drags
  (`touch-action: none`), so a finger elsewhere still scrolls; 6 px to
  start; keyboard sortable. Cards are collapsed by default with a one-line
  summary (`builderOps.stepSummary`/`itemSummary`); copy/paste is a
  localStorage clipboard shared across tabs (`builderOps` CLIP_KEY), every
  paste regenerating only the pasted step/item's OWN id
  (`builderOps.cloneFresh`) — a nested reference (`set_id`, `params.set`, a
  `target`'s own `{kind, id}`) is left untouched, or a paste would silently
  retarget a different fixture/category/set. A new action kind's param
  `type` renders in `StepCard.ParamField`; type `set` is the call picker,
  which leaves out any set that would loop (`builderOps.callableSets`).
  The Add-a-step dialog lists any catalogue `group` it does not know
  (e.g. Home Assistant kinds) under its own heading.
- Specs: `tests/test_show_set_references.py` (inline order, nesting,
  pauses, coalescing, cycles, deletes, preview, arms, Sonic) and
  `node scripts/check_light_show_builder.mjs` (via
  `tests/test_light_show_builder.py`; collapse, a finger drag, copy/paste,
  the cycle-free picker, the delete warning). The other Light Show UI
  checks expand the cards first. Screenshots at 390/820:
  `docs/evidence/lightshow-builder/`. Help: `show-builder-editing`,
  `show-set-references`.

**SHOW PLAYLISTS — the Playlists tab (2026-10-11, phases 0-1 of
`/home/javi/fleet-spotfx/data/playlist-plan/report.md`).**
`spectra/services/show_playlists.py`'s docstring is the binding statement. A
program is keyed to the Spotify context he plays (`ShowPlaylist.contexts`,
one context per program) and maps song -> steps (set + `song_start` /
`scene_change` / `high` / `low`). Four things:

- **FOLLOW, NEVER DRIVE.** Nothing here starts, queues or skips playback
  (Play-on-Serenity is phase 3, behind his word and a sleeping gate). The
  context comes off the bridge (`bridge.context_uri()` / `next_track()` /
  `context_name()` read fields SpotFX already broadcast); a name for any
  other context is SpotFX's read-only `GET /api/spotify/context-name`
  (`spectra/services/spotify_context.py`).
- **A SONG'S ARMS EXIST BEFORE ITS OPENING SCENE CHANGE** (his answer to
  Q2: a "next scene change" step counts the opening change).
  `show_playlists.on_state` is the FIRST thing `engine._on_track_uri` does,
  before any await; `song_start` fires are queued and spawned by
  `after_track_state()` after `trigger_engine.on_track_state`, because a
  set firing while the transition lands makes `show_actions.executing()`
  true and the transition would not count. Keep both placements.
- **PROGRAM ARMS ARE SCRIPTED** (`source="playlist:<run>"`,
  `show_arms.is_scripted_arm_source`): no 12 h / idle expiry, never replace
  or get replaced (`_replace_class` -> None), but song-scoped, so they go
  MISSED at song end (the runner first, `show_arms.tick` as backstop).
  Step outcomes are read back from the arms (`_sync`), never kept twice.
- The run lives in `LightShowState.playlist_run`; the library in
  `light_show_playlists.json` (conftest isolates it). Home Assistant starts
  one with `POST /api/light-show/playlist-run/start {"name": ...}`. Sonic
  reach is phase 3a (not built). Specs: `tests/test_show_playlists.py`
  (incl. the opening-change proof through the real bridge -> engine ->
  TriggerEngine, with a red control), `node scripts/check_show_playlist_ui.mjs`.

### THE LIGHT SHOW TAB DEFAULTS TO SEQUENCE → RUN, WITH A QUICK-START ROW (2026-10-13)

The Admiral, verbatim: "make the sequence running page the default for the
lightshow tab. add quick start buttons for recently used sequences."
`LightShowPage.tsx`'s top-level `mode` now defaults to `'sequence'`
unconditionally, and `SequenceView.tsx`'s own `sub` defaults to `'run'` the
same way — so opening `/show` on any screen size lands on
`SequenceRunView`, never Build. Both replace the pre-existing phone-vs-
desktop `matchMedia` default with a flat literal; `isPhone` now only
labels the Run tab "(recommended)" and no longer chooses which tab shows
on open. Neither default is persisted or deep-linkable; there was no such
mechanism to preserve.

**Quick start reads the durable show log back, it keeps no history of its
own.** `show_sequence.start()` now threads `sequence_id=r.sequence_id` into
its `_log(r, "started", ...)` call, so the durable `fire_history` show-log
entry for `key="sequence_started"` carries it in `detail` (previously only
`sequence`/`run`, where `run` is the SequenceRun INSTANCE id, not the
`ShowSequence` id — useless for this). `show_sequence.recent_runs(limit=6)`
walks that log newest-first, dedupes by `sequence_id` (keeping the newest
start), and resolves each id against the LIVE store
(`show_store.get_sequence`) — a deleted sequence drops off, a renamed one
shows its current name, an old log entry with no `sequence_id` (pre-this-PR)
is skipped rather than guessed at. Route: `GET /api/light-show/sequences/
recent?limit=`. Frontend: `SequenceRunView`'s "Quick start" card, one button
per entry (name + "last ran Xh/d ago", its own local day-aware `fmtAgo`),
one tap calls the same `start()` the picker's own Start button uses — same
confirm-before-replacing-a-running-sequence safety.

**`SequenceView.reload()` now falls back to `r.sequences ?? []`** — a
defensive hardening with zero production effect (the real endpoint always
returns the field) that was needed because `SequenceRunView` now mounts on
first paint: four `.mjs` check scripts that mount the whole `LightShowPage`
for unrelated Build-view features (`check_light_show_add_step_dialog`,
`check_light_show_pickers`, `check_light_show_duplicate_set`,
`check_light_show_builder`) had no fake-fetch handlers for the Sequence
tab's endpoints and crashed on mount once Sequence became the default; each
now also clicks the top-level "Build" tab right after `mount()`, mirroring
how they already had to stub `catalogue`/`targets`/`arms`/`status` for
endpoints their own test doesn't care about — **any future script that
mounts `LightShowPage.tsx` whole must do the same** (stub the Sequence
tab's three GETs, or switch tabs before asserting on Build/Run content) or
it will crash on the new default landing view. Specs:
`tests/test_show_sequence.py` (recent_runs: dedup/newest-first, delete
hides it, rename shows current name, limit clamps both ways, an entry with
no `sequence_id` is skipped, the route round-trips), `scripts/
check_show_sequence_ui.mjs` §ONE-B (Run selected with no click, Quick start
renders name+age, one tap posts `sequence-run/start`, a recent entry for a
sequence the loaded list doesn't know about is left out).

### THE OUTBOUND HOME ASSISTANT CLIENT + Light Show "ha" actions (2026-10-11)

`spectra/services/ha_client.py` is SPECTRA's FIRST outbound path to Home
Assistant — every other HA seam in this codebase is HA pushing IN
(`house.py`'s own "THE HA SEAM"). `ha_client.call_service(domain, service,
data)` POSTs to `{SPECTRA_HA_URL}/api/services/<domain>/<service>` with
`Authorization: Bearer {SPECTRA_HA_TOKEN}` — both read from the
environment only (`spectra/config.py`'s `ha_url()`/`ha_token()`,
`pretake_url()`'s own posture), never committed, never logged. Unset URL
is the shipped state and means INERT: every caller gets back
`HAResult(status="unconfigured")` and reports "Home Assistant is not
configured" rather than failing silently or raising. Deploy contract
(firstmate/River, 2026-10-11): on serenity the two env vars come from
`/home/javi/.config/spectra/ha.env`, loaded by a systemd drop-in
(`deploy/spectra.service`'s own comment has the exact `EnvironmentFile=`
line) — never inlined into the checked-in unit file.

Four Light Show action kinds (`spectra/services/show_actions.py`'s "ha"
group), all `needs_room=False` (they have nothing to do with who owns the
lights, so they still fire from a released or dark room — AND they never
consult `house.py`: a resting house mode must never block or defer an HA
action, his own explicit ruling, 2026-10-11, held by a test that actively
simulates a resting house mode and fires anyway):
`ha_volume_absolute` (`script.music_volume_set`, field `volume` 0-100 —
River's `input_number.snap_volume` has its own step of 4, but that only
shapes HA's dashboard slider, never enforced on a write), `ha_volume_relative`
(the entity named in the new `RoomControlState.ha_volume_relative_entity`
setting, default `script.music_volume_step`, field `delta`, signed,
default step 8 — split into `domain.service` on its first "."),
`ha_activate_scene` (`scene.
turn_on` with `entity_id` — **GENERIC, no allow-list**: his own
correction the same day, "I want to be able to customize the scene in HA
and trigger it as part of the light show" — ANY `scene.*` entity, typed
by its full id or picked from `ha_client.list_scenes()`'s live
`GET /api/states` fetch, `GET /api/light-show/ha-scenes` the route that
serves it; `scene.music_mode` is only the step's own suggested default,
never a stored list), and `ha_put_on_tv` (opens the dedicated TV app —
"THE ONE TAP" section, below, is the binding statement; its Sonic reach is
`jukebox_console.put_on_tv`, not a `show_console` op, since "one tap" is
SPECTRA-native end to end rather than an ad-hoc `show_actions.fire()`
call). **Both volume steps EASE** (`ease_s`, default 1 s, 0 = the old single
call; the Admiral, 2026-10-11, widened 2026-10-13 after he asked how
smooth the ramp was and whether it could be smoother) — SPECTRA writes
snap_volume ONE WHOLE PERCENT at a time (never a fraction, never
quantised to the entity's own step of 4 — that step is cosmetic, HA's own
history already holds non-multiples of 4), at up to ~5 writes/s (River's
own ceiling — each write fans out to 5 Snapcast clients), coarsening to
bigger whole-number steps rather than writing faster when a span needs
more. Not a ramping HA script: neither HA script has a transition of its
own (River confirmed, 2026-10-13 — Snapcast sets volume instantly), and
`music_volume_set` is `mode: single` and would drop a newer call mid-ramp.
`spectra/services/ha_volume_ease.py` is the binding statement: one ramp
at a time, a newer volume step stops it between writes and wins, a
relative step carries the stopped ramp's unfinished part (two quick +8s
= +16), the first write is inline (the step's outcome), and a restart
mid-ramp leaves a real whole-percent level between start and target. Spec:
`tests/test_ha_volume_ease.py`. Sonic reach:
`show_console._op_set_ha_volume_absolute`/`_op_set_ha_volume_relative`/
`_op_activate_ha_scene` (ad-hoc one-step fires through `show_actions.
fire()`, the `hold_device`/`dim_device` pattern; `_resolve_ha_scene` uses
a full entity id verbatim with NO fetch, or resolves a bare name against
the live list, fuzzy-matched). Tests (mocked HA, no live calls, ever):
`tests/test_ha_client.py`, `tests/test_show_ha_actions.py`.

