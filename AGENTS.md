# SpotFX — agent notes

## Adding a new LedFX effect

Follow `docs/ADDING_EFFECTS.md` — the full checklist (LedFX effect →
smoke test → **tuning gate: Javi tunes defaults before any scene is
seeded** → registry/phase wiring → scene seeder → scene groups → Help
page). Don't improvise the order; the tuning gate is deliberate.

## In-app Help page (KEEP IT CURRENT)

The React app has a searchable help page at `/help`, rendered from
`web/src/help/helpContent.ts`. **Whenever you add or change a user-facing
feature — a page, keyboard shortcut, mouse/long-press gesture, filter
syntax, mode, or setting — update `helpContent.ts` in the same change.**
Treat it as part of the definition of done. The file header documents the
content schema and conventions (kbd tables, keywords, deep-link ids).

Deep links: `<HelpLink topic="<section-or-entry-id>" />` renders the small
circled-"?" used across the UI. Don't rename an id in `helpContent.ts`
without updating its `topic=` callers (grep `topic="`).

Prefer adding a `HelpLink` next to a complex control over embedding
instructional prose in the UI; short tooltips (`title=`) are fine.

## SPECTRA capability & decision spec (live — check here first)

Before touching anything under `spectra/`, read `docs/SPECTRA_SPEC.md`. It is
the live reconciliation surface: every SPECTRA-relevant capability's honest
state (built/agreed/gap/old-world/retired), the Admiral's standing decisions
(fidelity rule, the four-item day-one switchover bar, closed questions), and
every open question with what it blocks. It supersedes the one-time
capability audit it's built from wherever the two disagree — the code wins,
and the spec says so. It carries its own maintenance protocol, including how
to translate one of the Admiral's edits into the document rather than leaving
his sentence sitting unconverted next to the structured parts — follow that
protocol exactly if you're the one applying his edit.

## SPECTRA SceneV2 (side-by-side with legacy scenes)

SceneV2 is the future merged-program scene model: `models/scene_v2.py` (binding
design answers in its header; product decisions in
`/home/javi/fleet-spotfx/data/spectra-design-decisions.md`), store
`services/scene_v2_store.py` (`storage/scenes_v2.json`), compiler
`services/scene_v2_compiler.py` (dry-run default; live path goes through
`api/ledfx_client.py`), UI `web/src/scenes/`. Executable spec:
`.venv/bin/python scripts/check_scene_v2.py`. The legacy `scene_update` event
path is separate — don't couple the two during the migration.

Owner style rules: no settings-form sprawl for program behavior (settings are
declared name/type/range/default, driven by a future settings console); write
code for agents — no ceremony comments, keep explicit names, typed contracts,
and executable specs.

SPECTRA sequencer (DARK — `enabled: false` in `storage/sequencer.json`, its
own flag, not a settings.py field): `models/sequencer.py`,
`services/selection_kernel.py` (pure kernel: curve × genre × affinity, zero =
veto, fallback ladder), `services/scene_sequencer.py` (transition-only clock
— NO timer, by the owner's decision 5; a long mix holding one scene is
accepted, don't "fix" it), seeder `scripts/seed_sequencer_from_legacy.py`
(`--apply` idempotent). Binding decisions:
`/home/javi/fleet-spotfx/data/spectra-sequencing-design/decision-five-answers.md`.
Interface split: curves are edited graphically (Scenes page); genre/affinity/
dwell/enabled only via `PUT /api/sequencer/config` (tell the agent — no
forms). Spec: `.venv/bin/python scripts/check_sequencer.py`. Colour-set
selector (the kernel's third flavour, wired last): curve × genre ×
wheel-travel (a named curve over 0–180° of wheel movement), no dwell —
colours roll only when the sequencer fires a scene, scene + set land in one
`scene_v2_compiler.fire_scene(color_set=...)` compile, and the ladder's
terminal rung KEEPS the current colours (never forced churn). Rainbow sets:
neutral ×1.0 wheel factor, never move the room's wheel position.

Colour Set Groups (rotating/synced pools, day-one bar item — was the last
one not started, `docs/SPECTRA_SPEC.md` §10): `spectra/services/
color_set_groups.py` resolves a `ColorSetCard` with `kind="group"` to one
concrete member — cycle (wrap/bounce)/weighted+exclude_current picking,
Palette Sync anchored on `color_journey`'s own room state (not a parallel
tracker), the group's own `entries` merged on top as a per-virtual override
layer — ported from spot-effects' `trigger_engine._select_color_set_member`/
`_execute_set_color`, minus the retired dark/light mode-lane and scene-
group-ref machinery (§36/§42, zero real usage). Wired into every EXPLICIT
colour-set choke point (`scene_sequencer.fire_scene_by_id`, `trigger_engine.
_default_select_color_set`, `POST /room-color/apply`, the editor's baseline
endpoint) — deliberately NOT the sequencer/journey's own automatic
wheel-travel roll (`color_wheel.wheel_positions`), which stays set-only by
design: a Group has no chromatic wheel position of its own, and no real
group needs to be reached that way. Authoring UI: `spectra/web/src/
colorsets/ColorSetsPage.tsx` (`/colorsets`, nav "Colours") — writes go
straight through spot-effects' existing `/api/color-sets` (already general;
SPECTRA's own backend only ever reads this storage, same as before).

**Groups are now a tiered container in the UI (2026-08-17, PR
fm/spectra-colour-groups-as-overrides), the RESOLVE mechanism unchanged.**
His ask, verbatim: "in our color group list let's tier it, so that color
sets are listed under a color group that contained them. Now what color
groups are, are just overrides for the values of all the color sets below
it. this gives me a way to bulk edit groups of color sets." Verified before
building, not assumed: `resolve_for_fire`'s override overlay was ALREADY a
live, non-destructive layer (never rewrites a member Set's own stored
`entries` — confirmed in both this module and legacy's
`_execute_set_color`), so his "bulk edit" phrase names the EFFECT, not a
new mechanism to build. **The override has NEVER applied to a Set fired by
its own id** — in legacy OR here, only when the enclosing Group itself is
the resolved fire target (`_execute_set_color`'s `if card.kind == "group"`
gate, unchanged) — broadening that to every direct reference of a member
Set was considered and rejected: computed against his real 8
groups/58 cards, doing so would silently change rendered output for 27 of
28 (group, member) override pairs, with zero precedent in either codebase.
**Groups also stay real, working pools** — 0 of his ~21k SPECTRA
triggers/scenes target a Group id today (his "we're not really calling
color groups like we were in SpotFX" is literally true of SPECTRA, though
legacy's own `storage/events.json` shows 5 of his 8 groups WERE fired as
pools back there) — but `SpectraTriggerDialog.tsx`'s "select colour set"
action still lists Groups, `POST /room-color/apply`/`baseline/{id}` still
accept a Group id, and ColorSetsPage's own ▶ Preview still resolves one —
none of that was removed, only visually de-emphasized under a "Rotation"
heading with an honest note on when it actually fires. **A Set can sit
under more than one Group** — his real data has 4 that do (First Group ∩
Blues) — so the tiered list is a many-to-many index (a Set renders under
every Group listing it, cross-referenced by name), never a strict tree or
an invented "primary owner." No backend/storage change was needed or made
— the tiering and the reordered Overrides/Members/Rotation editor are
UI-only, computed client-side from the already-fetched card list.

This top-level copy predates the S3 process split and is genuinely dark/unused
in his real room today (`storage/sequencer.json` has `enabled: false`) —
`spectra/models/sequencer.py` + `spectra/services/{selection_kernel,
scene_sequencer}.py` + `storage/spectra/sequencer.json` (own `enabled: true`,
seeded from this one by `scripts/seed_spectra_from_v2.py`) is the live fork he
actually uses. Don't assume "sequencer" means the top-level module without
checking which storage file has `enabled: true` first. A scene's likelihood
curve (`SelectorEntry.curve_ref`/`inline_points`) can be a shared named
profile OR a scene-local one-off since the sequencer shipped — his real data
already mixes both. `spectra/web/src/scenes/tabs/SequencingTab.tsx` (the
live UI) has explicit "Detach — edit just this scene" (profile → scene-local
copy) and "⇪ Promote to shared profile…" (scene-local → new named profile)
actions alongside a pull-a-profile GRID (his ask: choose by shape, not name
alone — each tile is a `CurveThumbnail`, `spectra/web/src/components/
CurveThumbnail.tsx`, reusing `CurveEditor.tsx`'s own px/py/path scaling so a
thumbnail is a scaled render of the real curve, never a second
interpretation of it; reuse that component for any future read-only curve
preview rather than re-deriving the scaling math), so editing a curve never
has to silently retune a profile shared by other scenes. `web/src/scenes/
{SequencerPanel,CurveProfilesCard}.tsx` is the spot-effects `/app/` twin of
this same pattern (its own top-level sequencer, above) — `CurveProfilesCard`
still forces a `prompt()`-named profile before any edit and has no
Detach/Promote; left as-is since that Scenes page is frozen pending SPECTRA
superseding it.

## A scene's stored data is not proof he authored it

Found 2026-08-15 (`docs/spectra-star-edges-freeze.md`, `docs/SPECTRA_SPEC.md`
§54): his legacy STAR scene authored `edges` as a bare static `6`; the
SPECTRA rebuild silently replaced it with a random dice binding plus two
"patch" flare kinds that exist nowhere in his legacy data — he never asked
for any of it, and only noticed because his six-pointed star stopped being
six-pointed. He cannot edit `spectra/models/scene.py`'s storage layer
himself, so nothing catches this kind of drift but a human noticing the
room looks wrong.

**The rule this is evidence for: an artifact's presence in his scene data is
NOT evidence he authored it.** "His own tuning" is a claim that needs
provenance, not an inference from what's currently stored. Before arguing a
scene field reflects his intent, check his legacy data (spot-effects'
pre-rebuild source, not what SPECTRA currently stores) — and never treat
"migrated from legacy" alone as proof of authorship; it establishes only
that something is old, not that he put it there.

## SPECTRA trigger authoring (THE KEYSTONE — mid-song clock)

Binding decision: scene changes are driven by triggers
(`/home/javi/fleet-spotfx/data/spectra-gap-inventory/decision-mid-song-model.md`)
— the shipped transitions-only default and a heavily hand-tuned show are the
SAME mechanism (an ordinary trigger list) at different densities; a later
mid-song-generation stage seeds that list programmatically, it doesn't get a
separate schema or execution path. Model `spectra/models/trigger.py`
(`SpectraTrigger`: timestamp_ms + one discriminated `TriggerAction` —
`fire_scene` / `fire_response` / `select_color_set`); store
`spectra/services/trigger_store.py` (`storage/spectra/triggers.json`, keyed
by spotify_uri, per-trigger CRUD); engine
`spectra/services/trigger_engine.py` (`TriggerEngine`: fed by
`on_track_state(uri)` + `tick(position_ms)` from `services/engine.py`'s own
poll loop off the S2 bridge; edge-triggered on the forward-crossed
`(last_position, position]` window — fires once per crossing, rearms
silently on a song change or a rewind, never backfills). Every action kind
routes through SPECTRA's existing choke points, not a new write path:
`fire_scene` → `scene_sequencer.fire_scene_by_id` (the SAME function the
sequencer's own picks call — factored out for exactly this reuse),
`fire_response` → `services/engine.fire_response_event` (the same path the
bridge's classified trigger_fired events drive), `select_color_set` →
`drift_conductor.apply_set_directly` (the same surface
`POST /api/room-color/apply` uses). API `spectra/api/triggers.py`
(`GET/POST /api/triggers?uri=`, `DELETE /api/triggers/{id}?uri=`).
Authoring UI: `spectra/web/src/timeline/components/SpectraTrigger{Bar,Dialog,
sCard}.tsx`, mounted in `BuilderPage.tsx` as its own card below the ported
legacy timeline — a separate authoring surface from the legacy
MusicTrigger/SongProfile world (two worlds coexist; this surface only ever
calls `spectra/api/triggers.py`). Executable spec:
`.venv/bin/python scripts/check_triggers.py`; frame-level proof (a placed
trigger's action landing on the real render pipeline):
`tests/test_trigger_engine.py`.

**Front 3 — mid-song generation** (`spectra/services/midsong_generator.py`,
`generate_for_song(uri)` / `POST /api/triggers/generate?uri=`, UI's
"⟳ Generate" button): seeds `fire_scene` triggers at every LibrosaSection
boundary from `analysis_reader.sections_for_uri` (the S2 bridge's own
read-only reader — no spot-effects import), intensity = that section's
energy_rms, per-song minmax+floor renormalized (same convention as
`scripts/backfill_trigger_intensity.py`). Deterministic, idempotent,
edit-preserving: `SpectraTrigger.source` ("authored"/"generated") +
`generator_key` (`f"section:{start_ms}"`) track provenance;
`spectra/api/triggers.py`'s `upsert_trigger` stamps every human-facing write
back to `source="authored"` regardless of what's posted — the
ownership-transfer rule that keeps regeneration from ever clobbering an
edited trigger. A generated trigger's `FireSceneAction.scene_id` is `None`
by default (LibrosaSection carries no scene cue today) — resolved through
`selection_kernel.select` at FIRE TIME in `trigger_engine._default_select_scene`,
the same kernel the sequencer's own rolls use, at the trigger's own
intensity, no dwell/no cross-fire affinity tracking.

**Auto-generation on first play** (Admiral order 12, `trigger_engine.
maybe_auto_generate`, wired off `services/engine.py`'s `_on_track_uri` on
the same first-time-seeing-this-URI edge that resets `_last_track_uri`):
any song reaching ZERO stored triggers of either source gets
`generate_for_song` run for it automatically, fire-and-forget
(`asyncio.create_task`, never awaited, so a slow/unanalyzed song can't
delay the transition fire). This is reactive only — it fires the first
time a song is *played*, not proactively for the rest of the library.
`scripts/import_analysed_triggers.py` (`--apply`) is the proactive
counterpart: back-fills `generate_for_song` for every song that has usable
librosa analysis but zero authored triggers (recomputed fresh from
`storage/spectra/triggers.json` and `analysis_reader` on each run — never
a stale snapshot), so coverage doesn't wait on him happening to replay
each one. Both call the identical function, so a song either path already
touched is a no-op for the other. Dry-run by default, matching
`scripts/migrate_legacy_triggers.py`'s convention. **Write cost is real**:
`trigger_store.upsert` does a full read+rewrite of the whole
`triggers.json` per trigger (measured ~126ms/call against the live
~11k-trigger corpus) — fine for one human edit, not fine looped inside an
async request handler for a multi-song batch (blocks the SPECTRA process's
event loop, stalling bridge polls/ticks/WS broadcasts for the run's whole
duration). Run bulk generation as a separate offline process against
`storage/spectra/triggers.json` directly, the same shape
`migrate_legacy_triggers.py` already used for the authored corpus, never
through the live HTTP endpoint in a loop.

**Scene-change settings model** (the Admiral's binding three-tier control,
corr=c14a9bcee40e6df9, superseding front 3's plain `midsong_triggers_enabled`
bool): `RoomControlState.scene_change_mode` (`spectra/services/
room_controls.py`, default `"full"`) is `"transitions"` / `"analysed"` /
`"full"`, additive. Every tier fires an automatic scene change on genuine
song-to-song transitions — `trigger_engine._fire_transition`, driven
directly from `on_track_state` (mirrors `scene_sequencer.TransitionSource`'s
arm/fire semantics), NOT a stored trigger, because the tick()-based
edge-crossing window is unreliable at `timestamp_ms=0` (see the module
docstring). `"analysed"` additionally fires GENERATED mid-song triggers;
`"full"` additionally fires hand-authored triggers AND response-engine
flares (gated at `engine.fire_response_event`, the same choke point a
bridge-classified flare and a trigger's `fire_response` action both reach —
flares are the owner's authored scene material, same tier as authored
triggers). Gating lives in `trigger_engine._trigger_allowed` (tick()) and
`engine.fire_response_event`. A pre-existing `midsong_triggers_enabled`
value on disk migrates on load (`room_controls.load_room_controls`):
`True → "full"`, `False → "transitions"`. UI: the room bar's "Scene
changes" select (`RoomControlsBar.tsx`). Spec:
`scripts/check_triggers.py`; frame-level: `tests/test_trigger_engine.py`.

`_fire_transition` DEFERS UNCONDITIONALLY when `scene_sequencer`'s own dark
switch (`sequencer.json`'s `config.enabled`, separate from
`scene_change_mode`) is `True` — both it and `scene_sequencer.
on_track_state` are wired off the SAME URI broadcast
(`services/engine.py`'s `_on_track_uri`), so if the sequencer is live it's
already firing its own transition pick with richer dwell/affinity state; a
second independent kernel draw here would double-fire the room. Check
which is actually live before trusting either "transitions only" or the
sequencer's own status page in isolation — `GET /spectra/api/sequencer/
status`'s `enabled` field is the tell.

**xcorr sync (ported, 2026-08-15)**: `trigger_engine.tick()` fires against
`bridge.effective_position_ms()` (`spectra/services/bridge.py`), not the
raw bridge position — spot-effects' own xcorr `shape_offset_ms`, read off
the `timing` sibling field it already broadcasts on every WS "state"
message (previously parsed nowhere in SPECTRA), added exactly the way
spot-effects' own `trigger_engine.py`'s `effective_now = now_ms + offset`
does. The audio capture + correlation computation itself deliberately
stays in spot-effects — duplicating it into SPECTRA's process would
contend for the same PipeWire monitor `fx/audio_ingest.py`'s own
docstring already documents as a starvation problem within ONE process.
`ledfx_trigger_buffer_ms`/`ledfx_rtt_ms` (spot-effects' LedFX-HTTP
write-transport latency terms, folded into ITS `effective_offset_ms`) are
NOT ported — SPECTRA's executor doesn't share that transport, so there's
no equivalent to carry over. Root-level spot-effects also still has a full
parallel timing/debug diagnostic stack (`routers/timing_viz_router.py`,
`routers/debug_router.py`, `web/src/timingviz/`, `web/src/debug/`) ported
verbatim into `spectra/web/src/{timingviz,debug}/` — same-origin calls
into spot-effects' own live endpoints, no new backend. Useful precedent
for future ports: SPECTRA's ported builder canvas stack
(`spectra/web/src/timeline/{canvas,components,hooks}`) already diffs
byte-identical against spot-effects' own `web/src/builder/` modules, so
check there first before assuming a root-side frontend module needs
re-porting.

**Trigger-level scene pools** (2026-08-17, his ask: "triggers should be
able to carry some meta data that can say choose from only these scenes
and includes weights"): `FireSceneAction.scene_pool` (`spectra/models/
trigger.py`, `Optional[list[ScenePoolMember]]`, `ScenePoolMember =
{scene_id, weight}`), consulted only when `scene_id is None`. Absent
(every one of his 20,958 real `fire_scene` triggers as of this field's
introduction — his legacy hand-built scene pools did NOT survive the
migration to `storage/spectra/triggers.json` and cannot be reconstructed
from it) means unconstrained — the unchanged `_default_select_scene`
kernel draw. When present, `selection_kernel.select_from_scene_pool` is a
PURE weighted draw over the pool's own weights only — deliberately not
curve/genre/affinity-composed, porting legacy's `scene_group_mode=
"weighted"` (`storage/events.json`, 898 `"weight"` occurrences) and
mirroring `color_set_groups.py`'s own weighted branch, not the kernel's
`select()` ladder. Wired into `trigger_engine.TriggerEngine._fire` ahead
of the kernel draw. No UI built (data-and-test task by design) — two
authoring/display shapes proposed but undecided, see `docs/SPECTRA_SPEC.md`
§67 and OQ-11. Executable spec + real-song demonstration:
`scripts/check_trigger_scene_pools.py` (reads his live storage read-only,
`--song-uri` to pick which of his real songs to demonstrate against).

## SPECTRA per-song intensity scale (genre-anchored port + headroom reserve)

`spectra/services/intensity_scale.py` ports SpotFX's dropped-in-the-rebuild
mechanism (`services/intensity_scale_service.py`, genre slider →
`genre_to_song_scale` song-space base × a per-song bass-rank factor
0.9–1.1, calibrated 2026-07-29 against the Admiral's own reference songs —
these are SCALING FACTORS, not target intensities: Dopamine≈1.20,
Let It Be≈0.50, Soy Peor≈1.00 (100% = no adjustment, not "maximum" — a
2026-08-15 report conflated the two and retracted the conclusion drawn
from it; don't repeat that reasoning). Own SPECTRA-side feature cache
(`storage/spectra/intensity_scale_features.json`, never SpotFX's cache
file — see `_isolated_intensity_scale` in `tests/conftest.py` for why every
test repoints this). `song_scaling_factor()` is wired at RENDER choke
points only — `trigger_engine._fire`/`_fire_transition` and
`scene_sequencer._roll`'s fire call — never at `selection_kernel.select`'s
scene/flare/colour-set SELECTION, whose own `genre_mult` already factors
genre into the pick; scaling intensity there too would double-count genre.

2026-08-15 correction, his words, closed (not a curve-shape question): the
old plan (`final = measured * song_scaling_factor`) was "just a straight
multiplication of a factor" — replaced by `combine_measured_and_scale`,
the one seam: `final = measured_intensity * HEADROOM_RESERVE(0.6) *
song_scaling_factor`, clamped to `[0,1]` ONLY at the very end (clamping
the scale term early silently defeats the gate — see the constant's own
docstring for why 0.6 is deliberate, not a fudge factor, and must survive
any future edit).

**The 0.75 auto ceiling + the manual mark (his ruling, same day, BUILT)**:
0.75 STANDS as the automatic ceiling — `auto_scaling_factor()` (the
renamed, unchanged AUTO-only resolution) never exceeds `SCALE_MAX=1.25`,
so nothing automatic ever produces a `final` above `0.6*1.25=0.75`.
`spectra/services/intensity_scale_marks.py` is the release valve: a
per-track manual mark (`{uri: factor}`, clamped `[0, 2.0]` — SpotFX's own
manual-slider ceiling), checked FIRST by `song_scaling_factor()` and
**never** re-clamped into the auto range — "he marks the track; automatic
never does." API: `GET/PUT/DELETE /api/intensity-scale/mark?uri=`
(`spectra/api/intensity_scale.py`). UI: `IntensityMarkControl.tsx` on the
shared `TopBarStrip`, next to the live energy readout (help topic
`intensity-mark`).

Same-day edge-trim fix to `midsong_generator._normalized_intensities`
(the per-song min-max renormalization generated triggers' intensity uses):
the first/last `EDGE_TRIM_MS` (15s) no longer set the floor/ceiling (a
cold open/fade-out was dragging the floor down so genuinely quiet MIDDLE
passages never read as low), and those edge sections clamp to `[0,1]`
instead of being floored. A track under ~30s (no middle survives
trimming both ends) falls back to the pre-trim behaviour entirely for
that song — his stated edge case, resolved not guessed.

Regression tool carrying the calibration forward:
`scripts/check_intensity_scale_reference_songs.py` (read-only, reports
the three reference songs' current auto scale + final-at-peak against his
targets — run against real `storage/audio_shapes`).

## SPECTRA fire-history: counts + bounded show log

`spectra/services/fire_history.py` hooks the same four production choke
points named above (`scene_sequencer.fire_scene_by_id`,
`engine.fire_response_event`, `drift_conductor.apply_set_directly`,
`trigger_engine`'s own fires) to record durable per-key fire COUNTS
(`storage/spectra/fire_history.json`, `GET /api/fire-history`) and a
bounded, entry-capped per-fire SHOW LOG (`storage/spectra/show_log.json`,
`GET /api/show-log?uri=&since=`) — the foundation for reconstructing a
played show afterwards. No UI beyond those two endpoints, by design.

Unlike every other SPECTRA store, this one has NO constructor DI seam —
it's a plain module-level call inside each choke point, not an injectable
dependency the way `room_load`/`room_save`/`set_position` etc. are. That
means any test or executable spec that reaches a REAL choke point (not an
injected fake) writes through to `config.FIRE_HISTORY_FILE`/
`SHOW_LOG_FILE` whatever they're currently pointed at. `tests/conftest.py`'s
autouse `_isolated_fire_history` fixture repoints both for every pytest
test; `scripts/check_triggers.py` / `check_spectra.py` / `check_drift.py`
each explicitly reassign `scfg.FIRE_HISTORY_FILE`/`SHOW_LOG_FILE` next to
their other `scfg.*_FILE` repoints (the established per-script isolation
pattern) — a NEW check script that builds a temp `SPECTRA_STORAGE` and
reaches any of the four choke points for real needs the same two lines or
it will write into the real repo's `storage/spectra/`.

## SPECTRA feedback sessions (Stage 2: mark-then-nudge, batch send)

Binding requirements: `data/spectra-design-decisions.md` "Feedback-session
design requirements" (his words, two acceptance criteria — MARK-THEN-NUDGE,
BATCH QUEUE). Server: `spectra/services/feedback.py` (`capture_moment()` —
the MARK button's live-bridge read; `save_batch()`/`load_all_batches()`/
`load_entries()` — one Send press lands as one atomic durable record in
`storage/spectra/feedback.json`, bounded like the show log, oldest whole
batch evicted first, the just-sent batch never evicted) +
`spectra/api/feedback.py` (`GET /api/feedback/mark`, `POST
/api/feedback/batch`, `GET /api/feedback?uri=&since=` — the Stage 3 read
surface). Unlike fire_history.py this store IS only ever reached through
its own API router — no hidden production choke point — so no autouse
pytest fixture was needed; `tests/test_feedback.py` and
`scripts/check_feedback.py` each set `scfg.FEEDBACK_FILE` locally.

Frontend: `spectra/web/src/feedback/FeedbackPage.tsx` (`/feedback`, nav
link in `App.tsx`), phone-first. The mark-then-nudge queue itself — every
mark, nudge, note, reorder, delete — lives ENTIRELY client-side
(`useSticky`, localStorage) until Send; nudges correct only the captured
`position_ms`, never `wall_ms` (which is just record-keeping order). MARK
never round-trips before the entry appears: it pushes an optimistic entry
(from `useLivePosition`, below — not the raw poll) immediately, then
patches in the authoritative `GET /api/feedback/mark` capture in the
background. That patch always lands on `FeedbackEntry.position_ms` (the
anchor) regardless of `touched` — a defect fixed post-launch (his words:
"the faster he works, the more likely his note is filed up to 3 seconds
off"): a note edit alone used to block the correction from ever landing,
because note and nudge shared one `touched` guard. `position_ms` is the
raw anchor; `nudge_offset_ms` is the sum of his +/-1s/+/-5s taps applied
on top of it (`entryPosition()` combines them for display/send) — keeping
the offset in its own field is what lets a slow correction re-anchor
without clobbering a fast nudge. `touched` still flags "nudged or noted"
for the UI (the nudge highlight flash) but no longer gates anything.
`FeedbackPage.tsx`'s "Now:" line uses `spectra/web/src/lib/useLivePosition.ts`
to interpolate `useEngineStatus`'s 3s-polled position between polls, to a
tenth of a second, re-anchoring (and freezing while paused) on every fresh
poll — his words: it "needs to be tracking the actual time in the song
down to the 10th of a second," not the raw Spotify-pull value. This closes
the gap between Spotify's last report and now; it does NOT correct for
audio-path latency (what he actually hears vs. what Spotify reports) —
that residual is unmeasured, and only the legacy cross-correlation engine
(not built for SPECTRA) addresses it.
A failed Send leaves the queue untouched for a plain retry (proven by
killing the backend mid-send in the phone-viewport eye-check).

## SPECTRA feedback sessions (Stage 3: review view — notes pinned on the reconstructed show)

Server: `spectra/services/show_reconstruction.py` reads Stage 1's show log
(`fire_history.load_show_log`) and Stage 2's sent batches
(`feedback.load_all_batches`) — no new store. SESSION = one feedback batch
(one Send press); `list_sessions()` names the songs each has notes for,
newest first by REVERSING store order (not sorting by `received_ms` —
two batches sent in the same wall-clock millisecond would tie and
misorder). `reconstruct(session_id, uri)` windows the show log to that
song's note wall-times padded ±`SESSION_PAD_MS` (20s), then
`merge_timeline()` — the pure, spec-tested slice — orders events+notes by
song `position_ms` (missing-position entries, i.e. bridge-down captures,
sort last by `wall_ms`). API `spectra/api/show_review.py`:
`GET /api/review/sessions`, `GET /api/review/timeline?session_id=&uri=`.
Executable spec: `scripts/check_show_review.py`.

Frontend `spectra/web/src/review/ReviewPage.tsx` (`/review`) extends the
ported timeline surface family (BuilderPage's lane pattern, PR 29/44)
rather than inventing a parallel one: `ReviewLaneBar` is
SpectraTriggerBar's read-only twin (ticks = events, taller pins = notes),
`ReviewEntryList` is its phone-friendly vertical counterpart, and
`ReviewNoteDetail` shows a selected note with ±15s of surrounding
timeline plus Prev/Next note jump. Desk-review surface first but stays
phone-usable.

## SPECTRA app (her OWN process since the S3 split)

`spectra/` is the SPECTRA app (purple-on-black UI at `/spectra/`), running
as its OWN process: `python -m spectra` under `spectra.service`, port
`SPECTRA_PORT` (8010). The spot-effects app imports NOTHING under spectra/
(spec-enforced) and serves `/spectra/*` through a transparent reverse
proxy (`services/spectra_proxy.py`, target `settings.spectra_port`) so
every port-8000 address survives. Why: one shared interpreter let
spot-effects' 90 ms–5 s GIL bursts freeze the render threads (2026-08-13
frame-rate diagnosis); the standalone entry also applies
`sys.setswitchinterval(0.001)` (Stage-1 mitigation). Split spec:
`.venv/bin/python scripts/check_process_split.py` +
`tests/test_process_split.py` (frame-rate proof under a foreign GIL
burst). Deploy pair + one-pass apply: `docs/SPECTRA_PROCESS_SPLIT.md`.
Import discipline is load-bearing: nothing under
`spectra/` imports spot-effects runtime internals — only `fx/` (shared
library, incl. `fx/device_model.py`) and stdlib/third-party; music/state
inputs arrive via the S2 read-only bridge (below), which degrades to 0.5
neutral intensity when down (stated). Its scene model (`spectra/models/scene.py`) grows SceneV2
with value bindings (+`dice` correlation), intensity-stepped effect
selection (`effect_steps`: a device entry resolves to a DIFFERENT effect
at/above ⚡ thresholds, fire-time only, base = fallback — decision:
star-fold-entry-growth; deploy migration for STAR's strips:
`scripts/seed_star_strips.py --apply`, NEVER by re-running the v2 seeder).
An effect's "accent" param (`sparks_color` on power — `"accent": true` in
`config/effect_params.json`, looked up via `fx/device_model.
accent_param_for`) is force-written black by `scene_compiler._entry_config`
on every compile unless the scene entry itself authored a value — ported
from spot-effects' `services/trigger_engine.py` accent-defaults-to-black
rule (`services/morph_aspects.accent_param_for`); the un-ported gap (fixed
2026-08-15, STAR/Singles/power showed white sparks) is that
`services/scene_v2_compiler.py`'s own docstring already flags accent as
NOT YET carried by the fixed colour vocabulary — SPECTRA's descendant
compiler silently inherited that same gap with nothing downstream to catch
it, since only `gradient`/`background_color`/`brightness`/
`background_brightness` were ever written. Any future accent-capable
effect just needs `"accent": true` on its param in the registry — no
compiler change required.
NAMED FLARE KINDS (`FlareKind`: drift-jump / momentary spike-and-return /
permanent re-baseline; bands select+scale them; ALL legacy response fields —
flare_bands, param_patch, gain, reroll/colour flags — load unchanged as
auto-named kinds, spec-asserted). A momentary/permanent kind's params are
`ParamTarget` expressions, not bare floats (a bare number still coerces to
`mode="absolute"` on load — every pre-existing kind is untouched): absolute
(declared value verbatim) / offset (signed delta from the CARRIED baseline
at fire time — a creep's live wander position, not its static start) /
random (uniform draw in `[lo, hi]`, rolled once per kind execution and
broadcast like an absolute value). Intensity-driven strength stays the
band's own `×scale`, orthogonal to the target mode — it steers whichever
mode resolves. A momentary kind also carries an optional `hold_ms` (the
CHOSEN HOLD before release; `None` = the fixed `PULSE_HOLD_S` default,
250 ms) — `ResponseEngine.pending_hold_groups()` lets kinds with different
holds in the same fire release on independent schedules
(`services/engine.py`'s `fire_response_event` spawns one release task per
group); every release still glides to `_carried_value` AS CARRIED AT
RELEASE TIME regardless of hold length, so a creep that kept wandering
during the hold is honoured, never a stale spike-time snapshot. Drift
declarations, and
the colour journey (room-level walk, per-scene OVERRIDE with custody
semantics — `spectra/services/color_journey.py` docstring is the binding
statement). Storage: `storage/spectra/` (own scenes/sequencer/drift/room
files; seeder `scripts/seed_spectra_from_v2.py --apply`, idempotent, reads
spot-effects storage READ-ONLY). Executable spec:
`.venv/bin/python scripts/check_spectra.py`. Frontend: `spectra/web/`
(own vite app — `cd spectra/web && npx vite build`), help content in
`spectra/web/src/help/helpContent.ts` (same keep-it-current rule as the
spot-effects help). The spot-effects Scenes page stays as-is until
superseded; never point `fx/` at live hardware before the S3 handover.

`TopBarStrip.tsx` (`spectra/web/src/components/`, mounted once in
`App.tsx` next to `RoomControlsBar`) is the shared always-visible strip
for widgets that belong on every SPECTRA route, not just one page —
first occupant is `LiveEnergyReadout.tsx`, showing `bridge.intensity()`
(spectra/services/bridge.py: raw librosa section energy at the live
playback position, no smoothing) exactly as read from
`GET /api/engine/status`'s `bridge.intensity` field, already the
callable wired into the drift conductor, the sequencer's default scene
pick, and automatic transition fires — the one number this build found
feeding every automatic (non-authored) decision path. The planned
device-preview strip (`data/spectra-device-preview-plan/report.md`) is
designed to mount here too, as a sibling, when authorised — don't build
a second one-off top-of-app mount point for it.

## SPECTRA S2 evolution engine

The engine (`spectra/services/engine.py` wires it; start/stop is owned by
`spectra/app.py::_standalone_lifespan` — the SPECTRA process's own
lifespan, which also runs the frame watchdog and the startup resume):
drift conductor (`drift_conductor.py` — creep/follow legs +
the DESTINATION-DRIVEN room colour journey, ~20 s legs: the room always
heads for a destination set picked by the shipped selector, the
destination fixes its own pace from distance, arrival reselects — the
binding model is `spectra/services/color_journey.py`'s docstring; a room
is never set-less: bootstrap + `POST /spectra/api/room-color/apply`, and
fires with no explicit set wear the room's active set), response engine
(`scene_response.py` — the four classes execute each band's NAMED KINDS
at their scales: dice re-rolls, param moves, gain envelopes, flare colour
jump via the shipped selector with an intensity-scaled ramp-in (gentle
2500 ms → hard 150 ms, `color_jump_ramp_ms`); permanent kinds and drift
jumps CARRY — baselines move; momentary kinds return exactly to the
carried-now baseline; charge/lull/drop ALSO drive
the vendored phase machinery band-or-no-band — per-family grammar in
`docs/SPECTRA_RESPONSES.md`), read-only bridge
(`bridge.py` — WS client on spot-effects' /ws + `analysis_reader.py`;
classification: charge/lull/drop stay themselves, scene-family event
types are observations, everything else is a flare). Every glide/jump
goes through the ONE executor seam (`fx_executor.py`): production =
RecordingExecutor (DARK — records and models, never writes; the engine
must never call fx_seam), headless tests = FacadeExecutor driving the
fx/ tween engine. S3 goes live by swapping the executor — nothing else
changes. Specs: `scripts/check_drift.py` (conductor + journey),
check_spectra.py (responses/bridge/Mid Group),
`tests/test_spectra_engine.py` (frame-level proof on the dummy device).
Degeneracy floor/ceiling (owner defect fix, 2026-08-14): a drift declaration
is authored param-agnostic (a named profile is reused across effects), so
its lo/hi can be legal-looking but wrong for the param it lands on — e.g. a
[0,1]-ish default wandering Orbits' `blob_size` (legal [0.5, 6.0]), silently
rejected below 0.5 by the effect's own config schema while the conductor's
own position model kept wandering, stuck near the floor. `drift_conductor.
_registry_range()` intersects every creep's lo/hi (at Mechanism construction)
and every follow's resolved target (every leg) against the param's own
range in the shared `fx.device_model` registry (`config/effect_params.json`)
— a spec entirely outside that range falls back to the full registered
range rather than a zero-span window. `DriftSpec.motion` also carries
`"hold"` (parks at whichever bound it reaches and stops, no bounce-back)
alongside bounce/wrap. The Scenes → Drift tab's creep cards expose lo/hi/
motion directly (the one non-agent-edited piece of a drift card besides a
follow curve) — product judgement: limits/boundary are agent-tellable by
nature, but they're what the lights visibly do, so they get a compact
editable row instead. Spec: `scripts/check_drift.py`.

SPECTRA frontend notes: `/spectra/timeline` is the SpotFX Profile
Builder ported whole (`spectra/web/src/timeline/`, reads/writes the
SpotFX `/api` + `/ws` same-origin via `api/spotfx.ts` + `api/ws.ts`);
phone portrait (≤720px, `lib/useIsPhone.ts`) is a first-class layout —
Scenes goes single-pane with a drawer picker. The Fire button asks no
confirm BY OWNER ORDER (deliberate asymmetry: the global colour-set
opt-out confirm stays) — don't "tidy" either side.

### SPECTRA-kept legacy equivalents (routed build, four items)

Owner decision `data/spectra-gap-inventory/decision-legacy-retirement-picks.md`
KEPT four legacy capabilities needing SPECTRA equivalents (six others RETIRED,
retire-not-delete). Built:

- **Override Blend** — `models/scene.py` `PhaseBlend` (per-scene
  `charge_ramp_ms`/`lull_ramp_ms`, read by `scene_response._drive_phase`)
  and `SceneV2.entry_ramp_ms` (a scene-fire blend-in ramp, threaded through
  `fx_seam.apply_writes(transition_ms=...)`, hue-arc, same tween shape as
  `fx_executor`'s glides). A read-only live-storage study found real legacy
  usage is 265/269 triggers Charge/Lull phase builds, not scene selection —
  `phase_blend` is the dominant facet; `entry_ramp_ms` covers the thinner
  scene-entry one. Legacy's dynamic gap-to-next-trigger stretch has no
  analogue (S2 has no forward trigger schedule) — both fields are
  authored/configurable instead, the buildable half of the same grammar.
- **Energy gates/tilt** — PROVEN EQUIVALENT, nothing built: sequencer
  likelihood curves already express floor/ceiling/scale gating exactly
  (`scripts/seed_sequencer_from_legacy.gate_points`, zero=veto in
  `selection_kernel.py`, spec-proven in `scripts/check_sequencer.py` against
  the legacy formula at `services/trigger_engine.py:2338`); live usage was 1
  authored option, 0 fires. See help topic `energy-gates-equivalence`.
- **Brightness multiplier** + **ambient/global-transition** — new room
  surface `spectra/services/room_controls.py` + `spectra/api/room_controls.py`
  (`GET`/`PUT /api/room-controls`), UI `RoomControlsBar.tsx` (mounted next to
  the ownership bar in `App.tsx`). `brightness_multiplier` scales
  brightness/background_brightness uniformly at the write seams
  (`fx_executor` for engine glides/jumps, `scene_compiler.fire_scene` for
  scene-fire bytes) — never the conductor's carried baseline or the
  returned/dry-run writes, so dry-run/live preview parity holds.
  `global_transition_ms` is the room default `entry_ramp_ms` falls back to.
  `ambient_enabled`/`ambient_color` drive a real live takeover
  (`spectra/services/ambient.py`, reconciled from the PUT handler whenever
  those fields change): every live Hue device in the room (Hue-only,
  matching the legacy scope — WLED keeps running its normal show) freezes
  its entertainment stream (`fx/devices/hue.py HueDevice.set_frozen`,
  in-process, no LedFX HTTP hop) and is held at `ambient_color` via direct
  bridge REST. No device-category setting (every live Hue device IS the
  target) and no legacy "wake scene" on disable — a SPECTRA-owned Hue
  virtual never goes inactive while frozen, so unfreezing alone lets the
  room's already-running scene pick the stream back up. Release is a
  TWO-PHASE bridge-side ramp, still frozen for both: a brief dim fade, then
  a second ramp toward whatever the live effect is ACTUALLY rendering right
  now — read from the literal live pixel buffer
  (`Device.assemble_frame()`, the frame `HueDevice.flush()` already
  receives and drops while frozen), not a captured scene config — before
  finally unfreezing. This is SPECTRA's analogue of legacy's own two-phase
  release (`services/ambient_mode.py`: REST fade toward a wake scene, then
  an LedFX-side effect-config tween back to a captured pre-ambient look);
  the two aren't reproducible 1:1 because legacy's driving virtual actually
  goes dark and needs a wake scene fired, while SPECTRA's never stops
  rendering, so there's no separate wake config to capture and tween away
  from — see `spectra/services/ambient.py`'s module docstring for the full
  reasoning (fixed post-#56, PR fm/spectra-ambient-release-fidelity, after
  the shipped single-fade version read as an abrupt cut against the legacy
  behaviour it was compared to). State-only (status "dark") when SPECTRA
  doesn't own the live stack. Ambient's ON path READS EVERY LIGHT BACK from
  the bridge before counting it held — a 2xx PUT only means the bridge
  accepted the write, not that the physical bulb (over zigbee, which can
  silently drop a command under a write burst) took it (live defect,
  2026-08-15, PR fm/spectra-ambient-verify-per-light: `lights_set` is now a
  CONFIRMED count, stragglers get bounded+spaced retries, and any light
  still not holding after that is named in `unconfirmed`/status "partial"
  rather than folded into the total — see the module docstring). This same
  attempted-vs-confirmed gap does NOT exist on the release path (already
  reads real state back) or the scene-fire path (writes virtual effect
  configs, fails loud on HTTP errors) — checked, not assumed. Ambient/
  Dinner-Party as a full room-MODES build is still separate. Spec: the
  room-control section of `scripts/check_spectra.py` +
  `tests/test_room_controls.py` + `tests/test_ambient.py`.

  **The bridge gives ZERO signal on a silent drop** — measured live
  2026-08-16 (`docs/SPECTRA_SPEC.md` §60): every PUT, dropped or not,
  returns a clean `HTTP 200`/`{"errors":[]}`, no `429`, no `Retry-After`,
  no rate-limit header. A retry has nothing to react to but a read-back —
  don't design one around the response. `AMBIENT_WRITE_STAGGER_MS=300`
  (raised from 50) is margin inside a confirmed-safe band, not a measured
  cliff edge — 48 controlled sustained-burst trials across both real
  bridges independently found no drops from 0.08s–0.60s; a claimed sharp
  0.12s-fails/0.45s-works cliff in an earlier report did not reproduce and
  was most likely itself a target-tracking bug in whatever script
  gathered it (the same mistake this investigation's own first attempt
  made — always self-check a burst-measurement script against an
  unambiguously-safe pace before trusting a faster result).
  `ambient.repair_stragglers()` is the fix for "detects but does not
  repair": `ambient_music_gate.py`'s periodic verifier now actually
  re-writes an ON-but-wrong-colour straggler it finds (still never a
  light that reads OFF right now — checked fresh, immediately before
  writing). `_color_matches` (on+hue only) vs `_state_matches` (on+hue+
  brightness) is a deliberate split: the former is what `verify_held()`'s
  reporting surface uses, so a bulb dimmed out of band no longer reads as
  a false "unlit" — brightness only gates confirming OUR OWN write.

**Force Scene** — the Admiral's day-one ask, separate from the four-item
gap-inventory decision above but built on the same room-control surface:
`RoomControlState.force_scene_enabled`/`force_scene_scene_id`
(`spectra/services/room_controls.py`), UI in `RoomControlsBar.tsx`. Ported
verbatim from legacy Now Playing's Force Scene (`settings.force_scene_enabled`/
`force_scene_event_id`, `services/trigger_engine.py::_forced_scene_event`):
while enabled, whatever scene id was about to fire automatically is
redirected to the pinned scene instead — an unconditional reassert, not a
pause; the caller's own resolved colour set/intensity still applies. Ported
at `scene_sequencer.fire_scene_by_id`, the single choke point every
automatic SPECTRA scene pick (sequencer rolls, `trigger_engine`'s
`fire_scene` action, its automatic transition fire) already funnels
through — one interception point covers all of them, unlike legacy's several
call sites. Manual editor test-fires (`POST /scenes/{id}/fire`) bypass that
choke point by design and are never redirected. SPECTRA has no Scene Group
concept, so legacy's group-member-rotation half has nothing to port to.
Spec: the Force Scene section of `scripts/check_spectra.py` +
`tests/test_room_controls.py::test_force_scene_redirects_every_automatic_pick`.

**Ambient's mode precedence gate** — three settings, in the Admiral's own
language (`RoomControlState.ambient_mode: "off"|"always"|"auto"`,
`spectra/services/ambient_music_gate.py`, UI a `RoomControlsBar.tsx`
dropdown, not the old checkbox). Origin: found live 2026-08-15,
`ambient_enabled: true` (the old bool) + a real track playing + an active
scene + firing triggers = all 19 Hue bulbs sat frozen at ambient cream,
following none of it — a second, independent cause of his "no scene
changes" complaint on top of the `scene_change_mode` fix. First framed as
"music always wins"; the Admiral corrected that the SAME session: he
wants Hue held lit during music TOO, as a deliberate third setting, as
long as every other device keeps performing — so the fix became three
modes, not one rule. `"off"` never holds. `"always"` (mode 2, his own
request) holds Hue UNCONDITIONALLY, playback irrelevant — proven for free
to never affect other devices, since `selection_kernel.py`/
`scene_sequencer.py`/`sequencer.py`/`trigger_engine.py` have zero
functional references to ambient state (grep-confirmed) and the hold
itself lives at `fx/devices/hue.py`'s device-level `set_frozen()`, the
last step in the pipeline, strictly downstream of scene selection.
`"auto"` is the original precedence fix: holds only when playback is
CONFIRMED not-playing, releases the instant it's confirmed playing. Every
path that can change the live hold (a human PUT, every bridge state
broadcast, process startup/resume) funnels through the gate rather than
calling `services.ambient.reconcile()` directly, so the chosen mode can
never be bypassed. Under `"auto"`, a confirmed playback read always wins,
even over an existing hold; an UNKNOWN read never actively changes
anything (carries the current hold forward) — collapsing unknown onto
"release" was rejected because a transient bridge blip would otherwise
flicker-release an already-quiet held room. One-way migration: a stored
`ambient_enabled: true` maps to `"auto"`, `false` to `"off"`. Visible
always-live status (`off`/`holding`/`yielding`/`transitioning`, plus the
chosen `setting`) folds into `GET /spectra/api/engine/status`'s `ambient`
key and shows as a persistent badge on `RoomControlsBar.tsx`, separate
from the one-shot PUT-outcome badge. Full detail + room-proof status:
`docs/SPECTRA_SPEC.md` §52 and §53 (mode 2), both room-proven live
2026-08-15 — including the composition question, confirmed not just
architecturally but measured live: the drift conductor's own ~20s legs
kept firing on every non-Hue virtual across two full cycles while Hue
sat held under `"always"`, and the ease-back release re-measured at
~16.9s, unflattened against the §52 baseline. Spec: `tests/test_ambient_music_gate.py`,
`tests/test_bridge.py`.

**Ambient — Hue entertainment-area selection** (WHICH Hue devices Ambient
reaches, not just whether it holds — `docs/SPECTRA_SPEC.md` §5, ported
from legacy's own per-group picker on `web/src/nowplaying/AmbientButton.tsx`
after he asked twice): `RoomControlState.ambient_hue_group_ids` (`[]` =
every live Hue device, the unmodified default) is resolved and threaded
through `ambient.reconcile()`/`verify_held()`/`ambient_music_gate._apply()`
as an explicit `group_ids` parameter at every call site — a device outside
the resolved target is either left completely untouched (never frozen) or,
if it's frozen and just fell out of scope, released via the same
fade→catch-up→unfreeze sequence, gated on `fx/devices/hue.py`'s new
read-only `frozen` property (VENDOR.md deviation #11) specifically so an
already-unfrozen out-of-scope device never eats a spurious
`set_frozen(False)` stream reconnect. Whole-room OFF stays unconditional,
ignoring the current selection, unchanged from before this field existed.
`ambient_music_gate` tracks TWO separate group-id sets — `_held_group_ids`
(the raw selection input, compared only for the write short-circuit) and
`_held_resolved_groups` (the actual held device ids, sourced from the
reconcile result's own `devices` list, what `status()`'s `groups` reports)
— conflating the two makes `status()` report an empty hold under the
default `[]` selection even while genuinely holding everything.

**Reading real Hue bulb state — don't trust a raw CLIP light GET during a
live entertainment stream.** While a Hue entertainment session is
streaming (any active SPECTRA scene, not just Ambient), `GET
/clip/v2/resource/light` does NOT reflect the streamed colour — a bulb
being actively driven reads as static there, so a WORKING fix looks dead
and a genuinely frozen one looks fine; this nearly read as a fix failure
during §52's own live proof. To tell whether bulbs are actually following
the room, read `entertainment_configuration` status ACTIVE on each of his
bridges plus continuous glide writes for the relevant virtual in `GET
/spectra/api/engine/status`'s `executor.recent_writes` (`spectra/services/
engine.py::status`) — that combination, not the light resource, is what
"read it at the bridges" means for a streamed scene. The light resource
IS the right instrument for Ambient's own hold/release (`spectra/
services/ambient.py`) and the panic-release path (`spectra/services/
release.py`) — both write over plain REST, not the entertainment stream —
so the same GET that lies during a streamed scene is correct there. Pick
the wrong one for the case at hand and you get a confident wrong answer
either way.

**Even for the correct instrument, a CLIP v2 light GET during an active
`dynamics`-ramped transition reports the commanded/target state, not a
live-interpolating frame.** Found live 2026-08-16 room-proving §63
(Ambient's second colour): polling `GET /clip/v2/resource/light/{id}`
every 150ms across a `dynamics.duration=1500` colour swap showed a
strictly binary jump — the OLD xy exactly, for several seconds, then the
NEW xy exactly from the next sample on, with no intermediate value ever
observed. The physical bulb almost certainly does fade smoothly (the
whole point of setting `dynamics.duration` on the PUT), but that
animation lives on the bulb/zigbee mesh, not in the bridge's REST
resource model — polling cannot see it. Proving an eased-vs-snapped
transition therefore has two honest layers, not one: the CODE-level
guarantee (confirm `dynamics.duration` is actually on the wire, e.g. by
reading the deployed source) and the STRUCTURAL guarantee (server logs /
`status()` show a single continuous hold, never a release-then-reacquire
cycle) are both provable by instrument; the third layer — does it
actually *look* smooth — needs a person's eyes on the bulb. Don't let a
binary-jump polling result read as "it snapped;" it means the instrument
can't see the answer, which is a different finding.

**A write-time confirmation is a snapshot, not a standing guarantee —
status surfaces need their own independent re-verification.** Found live
2026-08-15, overnight: `ambient_music_gate.status()` reported
`held: true, mode: "holding"` while every one of his 36 bulbs was
physically off (he'd turned them off before bed). Cause: `_apply()`
short-circuits a repeated identical `desired` (deliberate — no redundant
Hue writes), so under `ambient_mode="always"` a genuinely held room never
gets written to, and therefore never re-confirmed, again — the write's
own honest read-back (`_hold_and_confirm`, on+colour+brightness) just kept
replaying as if live. Fixed by adding a SEPARATE, GET-only periodic task
(`ambient_music_gate.run_supervised()`, `VERIFY_TICK_S=30`, wired into
`spectra/app.py`'s lifespan next to `frame_watchdog`/
`ownership_reconciler`) that re-checks reality on its own clock,
independent of whatever triggers a write — and a `status()` that reports
the CONFIRMATION's age (`verified_age_s`) alongside the result, rather
than only the result, so staleness is visible instead of implicit. The
general pattern for any future "X believes it's holding state Y" status
surface in this codebase: a write's read-back proves the moment it was
taken, not the moment someone reads the status later — either give the
status its own independent recheck loop, or make the staleness visible
(report the confirmation's age) rather than presenting a stale claim as
live. See `spectra/services/ambient.py::verify_held` (never writes — a
device found off is reported, never re-lit) and
`spectra/services/ambient_music_gate.py`'s module docstring ("Status
honesty") for the full mechanism.

**A state that is only announced on user-initiated transitions will
eventually lie about a transition the user did not initiate.** Found live
2026-08-15 in the device-preview strip (`spectra/services/
device_preview.py`): a status push only fired from the explicit
pause()/resume() API handlers, but the actual LedFX reconnect after
resume() completes asynchronously — an already-open tab could sit on
"reconnecting…" forever despite the server being fully live again, because
nothing told it once the async reconnect landed. Fixed in
`DevicePreviewRelay._set_connected` (PR #85): every `connected` transition
broadcasts, not just the ones a human click triggered. This is the same
shape as the write-time-confirmation gap above (a status that only
refreshes on the actions that usually cause a change, not on the change
itself) and is directly relevant to any future auto-triggered transition
in this codebase (the hidden-tab auto-pause built on top of this same
module is one — see `spectra/api/device_preview.py`'s WS endpoint calling
`relay.viewers_changed()` on every connect/disconnect, not just on a
pause/resume click). Broadcast state on every change of the underlying
condition, not on the actions that usually cause it.

**Device preview is now sourced from whichever world actually owns the
lights, not always LedFX** (fixed 2026-08-16, PR fm/spectra-preview-facade-
source, correcting the 2026-08-16 gap found room-proving against his real
stack — history kept below for why the fix takes this shape).
`device_preview._source_mode()` reads the SAME light-ownership record
`spectra/services/fx_seam.py` routes writes by: `owner == "spot-effects"`
→ `_consume_ledfx` (the original LedFX-websocket relay, unchanged, correct
whenever the external process really is the writer); `owner == "spectra"`
→ `_consume_facade` — no websocket at all, a direct in-process
`fx.events.Event.VIRTUAL_UPDATE` subscription on the live
`spectra.services.live_host.live.host` (the SAME event the frame-freshness
tap already listens for, fired by the real render thread after
assemble+flush — this is the literal pixel buffer being written to the
device); anything else (handing-over/released/spectra-owns-but-not-yet-
active) → `"none"`, honestly `connected: false`, nothing to relay. Pause
and the hidden-tab auto-pause are re-proven against the facade source on
its own terms (removing the `Event.VIRTUAL_UPDATE` listener from the live
host's own registry is the in-process equivalent of closing a socket —
`tests/test_device_preview.py` section 5 fires a frame directly at the
real bus while paused and proves it never reaches the relay), not assumed
to carry over from the LedFX proof. Licence position re-examined fresh for
this source (module docstring): `fx/` is already GPL-3.0-vendored and
already imported throughout spectra/, so subscribing to its own event bus
is no new incorporation; what would NOT be safe — and isn't done — is
porting `ledfx/core.py`'s dropped-from-vendoring throttle/serialize logic,
so the facade payload encoder is an independent implementation reusing
this module's own pre-existing throttle bookkeeping instead.

History (found live 2026-08-16, room-proof attempt against his real
stack, now resolved by the above): the original build always relayed
`ledfx_ws_url()` (`ws://…/api/websocket`, LEDFX_HOST/PORT from `.env`,
the pre-S3 `ledfx.service`) regardless of who owned the lights. Once
ownership moves to `"spectra"` (his live default since the S3 handover),
`ledfx.service` is intentionally stopped and the ownership reconciler
alarms if it comes back (see the S3 section above) — so the strip sat on
"reconnecting…" forever in his normal operating state: not a relay defect,
a genuine missing listener at that address. Proving live frames / genuine
pause against the ORIGINAL LedFX-only relay in that state would have
required either a real handover back to the external service (never do
this to "test" the preview) or exactly the source correction above.

**Device preview's expanded view is shape-aware, not always one flat
line** (fixed 2026-08-16, PR fm/spectra-preview-phone-matrix, his own
report after using it once: "the preview stretches out in a line super
far... I don't see any Matrix for The Matrix previews"). The backend has
always emitted the real `shape: [rows, cols]` on every frame — this was a
frontend-only defect, not a payload gap; check the payload before
assuming otherwise if this area comes up again. `DevicePreviewStrip.tsx`
branches on `shape[0]` (rows > 1 → `device-preview-matrix`, one row →
`device-preview-pixel-strip`, both sized to the container via
`aspect-ratio`/`width:100%`, no JS measurement) so a real matrix (his
`crystal-mapper` favourite, 72×37) reads as a grid and short strips (his
other favourites: 17/10/7 pixels) read as clean lines regardless of
length. Expanded devices stack vertically, so expanding always grows the
page downward. Collapsed mode's separate overflow (`.device-preview-strip`
was `white-space: nowrap` with no `flex-wrap`) wraps instead of running
off a phone's right edge.

**Device preview render path is a `<canvas>` painted imperatively, not a
`<span>`-per-pixel React grid** (fixed 2026-08-17, PR #115
fm/spectra-preview-smoothness, his own report: "not anywhere near as
smooth as ledfx version... ledfx was very good, and should be the
standard. copy as much as makes sense"). Read LedFX's real frontend first
(`/home/javi/ledfx-src/frontend/src/components/PixelGraph/*.tsx` — the
audio-visualiser `VISUALISER_CONTEXT.md` is a different feature, not the
device-pixel preview) plus `ledfx/core.py`'s `setup_visualisation_events`
and `ledfx/api/websocket.py`'s dual-path sender: LedFX ships five preview
render variants and keeps the DOM-per-pixel one only as a slower legacy
fallback (`variants: 'original'`) behind a settings toggle — `'canvas'`
(a raw WS callback writing straight to a canvas ref via
`ctx.putImageData()`, no React state in the hot path) is the shipped
default. Measured all three layers before touching code, against his
real shapes (`crystal-mapper` 72×37/2664px + 17/10/7px strips, via an
offline `fx.headless` render thread): SOURCE ~62fps and TRANSPORT
~7.66fps (matching `RELAY_TARGET_FPS=8`) were never the bottleneck for
either device size; RENDER was — a real-React harness reproducing the old
JSX (2664 `<span>`s inside one shared `frames` state object that
re-rendered the WHOLE strip on ANY favourite's frame) cost avg 6.5–8.7ms
on desktop, climbing to avg 43–47ms / max 86–98ms under a phone-class (4x)
CPU-throttle proxy — a third to most of the 125ms/8fps budget — versus
0.04–1.2ms for the canvas equivalent in both conditions. Fix:
`DevicePreviewStrip.tsx` now paints every incoming frame straight into a
per-device `canvasRefs`/`swatchRefs` ref via `putImageData`
(`imageSmoothingEnabled=false` + CSS `image-rendering:pixelated`, matching
LedFX's own default look) — a frame never touches React state, so it
never triggers a re-render at all, closing the cross-device amplification
too. Deliberately did NOT carry LedFX's `visualisation_maxlen≈81`
downsample cap: measured JSON.parse+decode cost for the full 2664-pixel
payload was <1ms even throttled (no smoothness benefit once canvas
removes the render cost), and it would conflict with his own prior
explicit ask two rows up (see immediately above) to actually see the
matrix shape — a named incompatibility, not a silent gap. Did not change
`RELAY_TARGET_FPS` (still 8) either, since SOURCE/TRANSPORT measurements
show it was never the cause. Full measured numbers and reasoning:
`docs/SPECTRA_SPEC.md` §43.

Verified against a static harness reproducing his real favourite shapes
at 390×844 and 360×780 (headless Chromium via chrome-devtools-axi), plus
a live isolated instance (spare port, `fx.headless` multi-virtual host
built to his real device shapes) for the canvas rewrite specifically —
his live `:8010` instance was read-only and untouched throughout both.

**Global Dark/Light mode** — day-one bar item, SPECTRA_SPEC.md §9 (`AGREED`,
built, room-proof pending for the Light half — see below); NOT the same
feature as the retired per-node Light Mode Chooser/§36, which shares only a
field name (`spectra/web/src/timeline/types.ts`'s per-trigger
`display_mode`, still unread by any `spectra/*.py`).
`RoomControlState.display_mode` (`"default" | "dark" | "light"`, room bar
select) is ALL THREE of legacy's states, matching `services/
display_mode.py`'s own cycle — a 2026-08-16 rebuild off the original
`dark_mode_enabled` bool, whose `False` state was found to be a mislabelled
Default (nothing forced) presented as "Light"; real Light (a configurable,
forced background) never existed until this rebuild
(`data/spectra-display-mode-three-state/report.md`). **Migration is
load-bearing**: `dark_mode_enabled: true` → `"dark"`; `false` → `"default"`,
**never** `"light"` (the old field was named light but behaved as default —
mapping false→light would have silently forced a background on deploy).
"default" is his word "hybrid" (labelled "Hybrid" in the UI, kept
`"default"` on the wire/internally). Dark toggles the SAME LedFX-side
`dark_lock` clamp legacy's `services/display_mode.py` drives — vendored
into `fx/` verbatim (`fx/virtuals.py`'s CONFIG_SCHEMA, `fx/effects/
__init__.py`'s `_apply_config` hard clamp), reached over ownership-routed
primitives on `spectra/services/fx_seam.py` (`get_virtuals`/
`set_virtual_config`/`apply_writes`, same HTTP-pre-handover/
in-process-post-handover routing). Light writes `display_light_bg_color`/
`_brightness` (new `RoomControlState` fields, legacy defaults `#201830`/
`0.3`) as `background_color`/`background_brightness` onto every
non-shielded virtual's CURRENT live effect config via `fx_seam.
get_virtuals()`+`apply_writes()` — running effect type and every other
param untouched — **unconditionally**, not gated on `bridge.is_playing()`
(unlike the default-repaint below), because a fresh forced write is
authoritative the instant it lands and gating it would defeat the point:
watching it work while music plays. `spectra/services/dark_light.py` is
the reconcile logic and carries the full fidelity reasoning — read its
docstring before touching this. Transitioning to `"default"` restores from
a live pre-dark snapshot (captured via `fx_seam.get_virtuals()`, persisted
to survive a restart, replayed via `fx_seam.apply_writes()`) rather than
legacy's "re-fire the last Color Set" (that concept belongs to the same
retired authoring world); the snapshot is cleared on every transition away
from `"dark"` (to `"light"` or `"default"` alike), since Light's own write
makes it stale. Shielding
(`dark_light_shield_categories`/`_virtuals`, default `["Singles"]` —
legacy's own default) is ported verbatim via the shared read-only category
registry (`fx/device_model.get_virtuals_for_category`). **Composes with
`ambient_mode`'s three settings, not a boolean** (the two features never
reference each other's fields — composition is architectural, not
coordinated): whenever a Hue device is ACTUALLY frozen right now —
`ambient_mode="always"` unconditionally, or `"auto"` while playback reads
confirmed-not-playing — that device is driven by direct bridge REST
(`spectra/services/ambient.py`), bypassing LedFX entirely, so `dark_lock`
has no visible effect on it; the moment that device ISN'T frozen
(`ambient_mode="off"`, or `"auto"` while confirmed playing), it's
LedFX-rendered like any other virtual and responds to `dark_lock`
normally. Dark/light never reads `ambient_mode` to decide this — the
orthogonality is a property of the write path (a frozen device never
reaches LedFX's effect config), not a rule either feature encodes about
the other, the same "compose for free by construction" shape Ambient
mode 2 found for the selection kernel. The transition-to-`"default"` repaint
is ALSO gated on `bridge.is_playing()` (`spectra/services/bridge.py`) —
while music is actively playing, the stale pre-dark snapshot is
deliberately not forced back (`dark_lock` still clears;
`repaint_skipped: "music_playing"` in the result) so the room's own live
show repaints it instead of a frozen still-frame overriding what's
currently playing — the same class of mistake `ambient_music_gate.py`'s
three-mode fix above exists to prevent, reached independently rather than
by sharing code with it. Light's own write is deliberately NOT gated this
way (see above). Measurement note, same lesson as "Reading real
Hue bulb state" above: dark/light's own mechanism is LedFX-side
(`dark_lock` + effect config on `/api/virtuals`), never the Hue CLIP
light resource — that instrument is for Ambient's own REST-held bulbs, a
different subsystem; verifying dark/light at the bridges means reading
LedFX's per-virtual `dark_lock` + effect config back
(`fx_seam.get_virtuals()`, what `dark_light.py`'s own confirm step and
`scripts/verify_dark_light_fixtures.py` both do). Spec:
`tests/test_dark_light.py` (18 tests), incl. frame-level proofs against a
real headless dummy host (`fx/headless.py`) that the vendored clamp
actually engages, the Light write forces the configured background live
even while playing, the restore repaints the exact pre-dark background, and
the music-aware gate holds both ways. Live-fixture check (read-only,
GET-only, same pattern as `scripts/verify_release_fixtures.py`):
`scripts/verify_dark_light_fixtures.py` — `--spectra-url`/`--ledfx-url`
are REQUIRED, no default target (a disposable worktree isolates the
filesystem, never the network — 127.0.0.1:8010/:8000 reach the same live
instances from inside any worktree on the host; a verification script that
defaults to them is a trap, learned live 2026-08-15).

**An authored black `bg_color` on a colour set is LOAD-BEARING in Hybrid
mode — do not remove it as "redundant" next to a black effect colour.**
`storage/color_sets.json` has 30 such entries across 22 colour sets (Black
Hole/Orbit/`Line - *`, `docs/SPECTRA_SPEC.md` §72, `scripts/
check_redundant_black_backgrounds.py`). His own first instinct, on
learning Black Hole ignores Light mode, was to strip these as dead data —
"a redundant black background." **They are not redundant: in Hybrid mode
they're the only thing that resets a virtual's background to black on
every fire.** Remove them and a prior non-black background left by an
earlier write (another colour set's own authored colour, or a Light-mode
write not yet repainted away) bleeds through the next fire instead of
being cleared — colour bleed between scenes, proven in the harness below,
not a hypothetical. His proposed fix was investigated, found unsafe on
exactly this axis, and NOT applied (no data or code changed) — he has
since replaced the underlying idea with a different, per-scene
colour-set preference design instead.

An authored `bg_color` beats Light mode regardless of `bg_mode`, because
the stomp is gated on the value being truthy, not on additive-vs-overwrite.
`scene_compiler._apply_set_colors`/
`_entry_config` writes `config["background_color"]` whenever `entry.bg_color`
is truthy, and `fx/effects/__init__.py::Effect._apply_config` partial-MERGES
each write (`self._config = {**self._config, **config}`) — so any entry
that authors a `bg_color` re-asserts it on every fire and overwrites
whatever a previous write (e.g. Light mode's forced background) left there;
an entry that authors nothing never touches the key, so a prior write
survives. Confirmed empirically against the real vendored pipeline via
`fx.headless` (no live storage): `scripts/check_black_bg_light_mode_interaction.py`.
Separately, once `bg_color` actually is black, `Effect._refresh_bg_render_state`'s
`bg_color_use` gate (`(live_rgb*brightness > 0.5).any() or (target_rgb >
0.5).any()`) is `False` regardless of `bg_mode` or brightness — additive
and overwrite black are equally invisible on their OWN turn, but that
sameness does not carry over to the stomp question above; don't conflate
"is this a no-op once rendered" with "does this clear a previous write" —
they're gated by different code paths. Fixing this by deleting the
redundant black fields from data is not free: in Hybrid/Default mode
(where nothing else forces a background) it also removes the guarantee
that these entries reset a virtual's background to black on every fire,
so a leftover non-black background from an earlier write would persist
through their next fire instead. `scripts/check_redundant_black_backgrounds.py`
finds every affected entry (30 across 22 colour sets in his real data, not
just Black Hole).

## SPECTRA settings console (standing order 5: talk to the software)

`/settings` — a small Sonnet-class model, not a form, is the only thing
that changes anything here. Mechanism `spectra/services/settings_console.py`
(scope: the five RoomControlState fields already labelled "agent-tellable"
in `room_controls.py`'s own docstring — brightness, ambient enable/colour,
global transition, scene-change tier; `force_scene_*` deliberately
excluded, it names a scene by opaque id). `SETTINGS_REGISTRY` is an
explicit allowlist whose bounds/choices are READ off RoomControlState's own
`Field(ge=, le=)`/`Literal[...]` (`room_controls.field_bounds`/
`field_choices`) — never a second hand-typed copy of the range.
`apply_change()` is the only write path: re-validates the full candidate
through `RoomControlState.model_validate` (the same class GET/PUT
`/api/room-controls` binds to) and writes through `room_controls.
save_room_controls` + the (now-shared) `reconcile_ambient_if_changed` — the
identical two calls the human PUT handler makes, factored out so the agent
can't diverge from what a human save does. A bounded, visible change log
(`storage/spectra/settings_log.json`) plus `undo_last_change()` (reverts by
re-running `apply_change` with the old value — an undo is validated exactly
like any other change) is the mis-transcription safety net, not a
confirm-before-apply step — voice dictation mangles his product names
routinely (captain-shared.md), so the record + one-step undo answer that
without adding a round-trip to every spoken command.

THE AUTHORITY BOUNDARY IS STRUCTURAL, not prompt wording — read `settings_
agent.py`'s module docstring first if touching this. The model — now called
Sonic in the UI/prompt — is handed exactly the tools declared in
`settings_agent.ALL_OPERATIONS`, a dict of `spectra/services/sonic_ops.py`
`SonicOperation` entries merged from each domain module's own `OPERATIONS`
dict (originally just `get_settings`/`set_setting`; widened 2026-08-15 to
Sonic's scene/flare authority below — see that section). `_dispatch()` is
the complete, exhaustive name->handler mapping, so there is no third
branch to reach for a shell/file/HTTP/service-control/light-driving call,
whatever the prompt or transcript says, and the SAME `SonicOperation` dict
also IS the `list_operations` discovery catalogue Sonic queries at
runtime instead of the prompt trying to describe every capability — see
`sonic_ops.py`'s own docstring for why guard and catalogue are one
declaration. `tests/test_settings_console.py`/`tests/test_scene_console.py`
prove this without a network call (fabricated tool names/keys rejected,
nothing persists on rejection) plus one live-model smoke test skipped
without `ANTHROPIC_API_KEY`. Model id from `spectra.config.
settings_agent_model()` (env `SPECTRA_SETTINGS_AGENT_MODEL`, default
`claude-sonnet-5`); API key from `settings_agent_api_key()` (env
`ANTHROPIC_API_KEY`) — unset means a stated 503, never a silent no-op.

**Sonic's scene/flare authority (2026-08-15, his own ask: "manage flares
and the settings within the scenes and creating scenes")** — a SECOND
mechanism module, `spectra/services/scene_console.py`, zero import of
`settings_console.py`/`room_controls.py`, whose only write surface is
`scene_store.save()`. `SCENE_SETTINGS_REGISTRY` (8 scalar keys: entry
blend, charge/lull phase ramps, choreography timing, colour-journey pace,
colour-set acceptance) reads bounds off `SceneV2`/`PhaseBlend`/
`PhaseChoreography`/`SceneColorJourney`'s own `Field(ge=,le=)`, same
discipline as the room registry. Named `FlareKind` create/update/remove
(upsert by name) and `create_scene` (name + labels only — no device/effect
authoring, that stays the Initial Set tab) round out the original
enumerated set; device/effect editing is deliberately NOT in scope, still
true after the widening below. **The property that protects his authored
scenes**: `create_scene` only ever builds a fresh `SceneV2(name=...)` — id
is the model's own `default_factory=uuid4`, so a created scene can never
collide with, and therefore never overwrite, an existing one. Reachable by
chat from `/scenes` too, not just `/settings`: `spectra/web/src/
components/SonicChatPopover.tsx` is a floating 💬 button + panel mounted
on `ScenesPage.tsx`, talking to the same `POST /settings-console/message`
endpoint. Full detail, the four adversarial refusal proofs, and the
fabrication-hunt re-proof against the widened CLI tool manifest:
`docs/SPECTRA_SPEC.md` §55, `tests/test_scene_console.py`.

**Sonic's overwrite/backup/undo/preview/restore authority (same night,
his follow-up: "edit scenes and overwrite them, back them up ahead of
time, an easy undo-last-agent-change button, a preview and check-in,
restore the backup if it's not right")** — the delete/overwrite exclusion
above is now PARTIALLY reversed, deliberately, with a safety net that
makes it so: `overwrite_scene` wholesale-replaces an existing scene's
name/labels/settings/flare_kinds in one shot (still never `devices`).
Every write that touches an EXISTING scene — `set_scene_setting`,
`set_flare_kind`, `remove_flare_kind`, `overwrite_scene`,
`restore_scene_backup` — now runs through `scene_console.
_write_and_verify_backup()` FIRST: snapshots the scene's pre-edit state,
writes it to the per-scene backup ring, then RE-READS THE FILE FROM DISK
to confirm the write actually landed before allowing `scene_store.save()`
to run — a successful write call alone is never trusted. Retention: the
last `SCENE_BACKUP_RING_SIZE` (10) edits per scene (oldest evicted first,
so undo-of-an-undo works), PLUS a permanent, never-pruned genesis snapshot
per scene captured on its first-ever edit — the anchor his 9 real scenes
can always return to regardless of how many edits pile up after it.
`undo_last_scene_change()` (no scene_id — global, most-recent-first,
mirroring the settings console's own "Undo last") and
`restore_scene_backup(scene_id, backup_id | "genesis")` are both
themselves backed-up edits, which is what makes undoing an undo work.
Every edit's `preview` field, and the standalone `get_scene_preview()`
read op, are `_diff_scenes()` — a real field-level comparison of two
STORED SceneV2 snapshots, never the model's own account of what it did;
the frontend renders this in its own visually distinct message
(`.settings-console-msg-preview`, both `SonicChatPopover.tsx` and
`SettingsConsolePage.tsx`) so it can never blend with Sonic's prose. The
plain, model-free "↺ Undo last" button (`POST /api/settings-console/
scene-undo`, mirroring `/undo`'s existing settings-only pattern) needs no
live model call — undo is a deterministic restore from an
already-verified backup. **Deploy held on this one, by the captain's own
order**, pending an adversarial proof run against a REAL model (not just
tests) on the live instance: an out-of-set op, a bad argument, a
non-scene-setting reach, a shell/restart attempt, the unavailable-tool
fabrication case specifically, an overwrite refused because its backup
fails, a fabricated restore claim caught against stored data, and
`create_scene`'s fresh-id guarantee reconfirmed under the real model.
Full detail: `docs/SPECTRA_SPEC.md` §56, `tests/test_scene_console.py`
section 9 (backup/undo/preview/restore), `tests/test_settings_agent_cli.py`
section 5c (the CLI backend's fabrication guard re-proven a second time).

**Sonic's parameter discovery + the "did it work" line** (2026-08-17,
`docs/SPECTRA_SPEC.md` §72): `fx/device_model.py`'s `param_descriptions()`/
`param_catalogue()` read a param's "what it does" text LIVE off the
vendored effect's own `CONFIG_SCHEMA` (`cls.schema()`, same MRO-merge
`scripts/backfill_param_defaults.py` already uses) — never a second
hand-written copy that could drift from the real schema; type/range/
default still come from the existing `effect_params()` registry. Two new
scene-domain `SonicOperation`s (`list_scene_params`/`get_param_info`,
`spectra/services/scene_console.py`) expose this narrowly (names first,
one param's full detail per call) — remember `settings_mcp_server.py` is
hand-maintained (one wrapper per `ALL_OPERATIONS` entry, not generated),
so a new operation needs a wrapper added there too, and the CLI backend's
`tests/fixtures/cli_transcript_synthetic_*.json` manifests updated to
list it or `_verify_tool_manifest` refuses every one of them as stale.
Separately: every `scene_console.py`/`settings_console.py` write result
now carries a deterministic `summary` string (and a rejection's own
`reason` already served that role) — `run_turn()`/`settings_agent_cli.
_parse_transcript()` collect a `rejected` list alongside `changes` so a
refusal is structurally available too, not only in the model's prose.
`spectra/web/src/lib/sonicPreview.ts`'s `fmtValue()` must never
`JSON.stringify` a raw object/array — a nested field like `flare_kinds`
diffs wholesale on any edit (`_diff_scenes`'s documented whole-field
behaviour), so a naive stringify is a real, previously-shipped path for
dumping a JSON blob into his chat; summarize (count/names) instead.

**Subscription (CLI) backend — built, default OFF, not yet authorised
against his real account** (`data/spectra-console-subscription-backend/`:
scout report + the captain's ruling that provisioning an `ANTHROPIC_API_KEY`
is refused as an answer to "use my subscription, not credits"). `spectra/
services/settings_agent_cli.py` is a second `run_turn()` implementation
driving the real `claude` CLI headlessly (`-p`, non-interactive), authenticated
by `CLAUDE_CODE_OAUTH_TOKEN` (a `claude setup-token` long-lived token —
Anthropic's own documented mechanism for billing Claude Code automation to a
Pro/Max/Team/Enterprise subscription instead of API credits). `spectra/api/
settings_console.py`'s `POST /message` picks it over the API backend only
when `config.settings_agent_backend()` (env `SPECTRA_SETTINGS_AGENT_BACKEND`)
reads `"cli"` — default `"api"`, so this is inert until BOTH that env var is
set AND a token is provisioned; neither this file nor anything else in the
repo ever runs `claude setup-token` or reads an existing interactive `/login`
session itself. **THE WIDENED SURFACE IS STRUCTURAL, not a deploy note**: a
subprocess with its own working directory can auto-run project hooks and
auto-connect `.mcp.json` servers it finds there (non-bare `-p` mode — `--bare`
can't be used, it refuses to read the OAuth token at all), so every call
creates/verifies a dedicated, code-owned, empty working directory
(`config.settings_agent_cli_workdir()`, refuses if it ever contains a stray
`.claude/`, `.mcp.json`, or `CLAUDE.md`), passes `--strict-mcp-config` +
`--tools ""` + `--allowedTools` naming exactly the tools its own MCP
server (`spectra/services/settings_mcp_server.py`, a stdio wrapper around the
SAME `settings_agent._dispatch()` the API backend uses — no second authority;
one hand-written function per `ALL_OPERATIONS` entry, see that file's own
docstring for why it's not generated) exposes, and re-verifies the live
`system/init` tool manifest on every single response before trusting
anything in it. That last check exists because a live re-proof caught
`claude-haiku-4-5` fabricating tool-call output in plain prose, twice, when
the real tool manifest didn't contain what it claimed — `_parse_transcript()`
reads ONLY structured `tool_use`/`tool_result` blocks, never the model's
narrated text. Tests: `tests/test_settings_agent_cli.py` (offline, against
real captured transcripts in `tests/fixtures/cli_transcript_*.json` for the
original two-tool surface — now correctly refused as a stale manifest once
the tool set widened — plus hand-built, explicitly-labelled
`cli_transcript_synthetic_*.json` fixtures re-proving the same properties
against the current, wider surface) + a live smoke test skipped without
`CLAUDE_CODE_OAUTH_TOKEN`. **Enabling this against the captain's real account
is his call, not a deploy default** — flipping `SPECTRA_SETTINGS_AGENT_BACKEND`
and minting a token are both separate, deliberate, human actions.

Voice reaches text by the browser RECORDING (MediaRecorder) and POSTing the
clip to `POST /api/settings-console/transcribe`, not the browser's built-in
SpeechRecognition (which ships audio to a third-party cloud and forecloses
ever routing it to a local transcriber). `spectra/services/transcription.py`
is the one seam that reaches it — its module docstring is TWO stacked wire
contracts, read it before touching any of this:

- **Browser-facing (ours to publish):** `POST /api/settings-console/
  transcribe`, multipart, one file field named `audio`. The browser
  negotiates `audio/webm;codecs=opus` explicitly (`MediaRecorder.
  isTypeSupported` + `recorder.mimeType` on the Blob, never a hardcoded
  guess) — WAV is not something this client emits. Response:
  `{text, vocabulary_honored}`.
- **Bridge-facing (2026-08-15, published and proven by the ship building the
  local-Whisper bridge — SPECTRA CONFORMS, does not renegotiate it):**
  `POST {whisper_bridge_url()}/transcribe`, RAW audio bytes as the body
  (never multipart — that shape stops at the API layer above), `Content-
  Type` forwarded unchanged from the browser, `X-Vocabulary` = the
  server-computed `vocabulary_hint()` string percent-encoded as a header.
  Response JSON: `{text, vocabulary_applied, content_type_received}`.
  `whisper_bridge_url()` (`spectra/config.py`) defaults to
  `http://127.0.0.1:8090` (verified, mirrors the bridge's own
  `STT_BRIDGE_PORT` default) — still `SPECTRA_WHISPER_BRIDGE_URL`-
  overridable, not a literal; loopback only works because both processes
  are plain host units on the same machine (see that function's docstring
  for the containerisation caveat, written down on purpose).

Two easy-to-miss bridge facts, enforced not assumed: **Content-Length
required, chunked rejected** — `transcribe()` only accepts `audio: bytes`
and refuses anything else (a file/iterator would silently make httpx
chunk); **25MB body cap**, checked before the request goes out
(`BRIDGE_MAX_AUDIO_BYTES`) rather than leaving the bridge's own rejection
to surface as a confusing generic error.

**A non-empty vocabulary hint the bridge doesn't confirm using is a hard
502, enforced twice, on purpose:** `transcribe()` itself raises
`VocabularyNotHonored` the instant `vocabulary_applied` isn't literally
`True` on a non-empty request (never returns a "generic" result), and
`settings_console.py`'s `post_transcribe` independently re-checks the
returned `vocabulary_honored` as a backstop against any OTHER
implementation (a stub, a future swap) that returns normally without
confirming. Neither trusts the other. `TranscriptionUnavailable` (bridge
unconfigured/unreachable/malformed, incl. connection-refused) is the
separate 503 path — the real bridge was confirmed DOWN the night this
landed (its test container was torn down); that is handled as this exact
honest-unavailable state, proven with `httpx.MockTransport` only, never by
probing/scanning the host. This whole feature — including the bridge call
above — ships UNVERIFIED against a live transcriber and against his room;
see the PR.

Spec: `scripts/check_settings_console.py` (both domains) +
`tests/test_settings_console.py` (settings) + `tests/test_scene_console.py`
(scene/flare).

## SPECTRA per-item mode availability + Colour Set/Group Preview

Two owner asks (2026-08-17), same button row. **Mode availability**:
`display_availability: "default"|"dark"|"light"` on `SceneV2`
(`spectra/models/scene.py`) and `ColorSetCard` — gates AUTOMATIC selection
only (`spectra/services/mode_availability.py`'s pure rule), never a manual
Fire/Preview/Force Scene. **`ColorSetCard` is defined TWICE** — the root
`models/color_set.py` (spot-effects' authoring model) and SPECTRA's
own read-only projection `spectra/services/color_sets.py` (`extra="ignore"`)
— a field added to one and not the other is silently dropped on every
SPECTRA-side read; `display_availability` had to be added to both. Don't
confuse this field with `ColorSetCard.display_mode`, the retired dark/light
"mode lane" variant-swap field (§36) — same three-value vocabulary,
unrelated meaning. Enforcement funnels through `scene_sequencer.
fire_scene_by_id` (the one scene-fire choke point, gates scene + resolved
colour set, Force Scene exempted) and `color_set_groups.
resolve_for_fire_mode_gated`/`_mode_available_members` (gates a Group card
itself before member substitution, then filters the member pool).

**Preview** (`spectra/services/room_preview.py` + `preview_pause.py`,
`spectra/api/room_preview.py`) replaces the Colour Set/Group editor's old
permanent "Apply to room": tap pauses SPECTRA's automatic changes 5s while
applying, then reverts; hold ½s pauses up to 60s and stays until released
(second press / timer / navigating away — `ColorSetsPage.tsx`'s unmount
effect + a `beforeunload` `sendBeacon`). Snapshot-and-revert goes straight
through `fx_seam` (mirrors `dark_light.py`'s own pattern) — NOT through
`drift_conductor`/the engine executor, since a preview must never touch
`active_set_id`/wheel position/fire_history. `preview_pause` outranks every
existing deferral (pause/dinner_party/ambient/force_scene) at `bridge.
conductor_deferral`/`sequencer_deferral` and `engine.fire_response_event`/
`fire_scene_update_event`. Live-drag colour edits call `POST /room-preview/
update` with at most one request in flight (a tick that lands mid-request
coalesces into one follow-up with the latest state, never queues).

Docs: `docs/SPECTRA_SPEC.md` §67/§68 for the full acceptance-criteria
writeup. Known gap, not fixed by this work: `ColorSetsPage.tsx`'s outer
`260px 1fr` grid has no phone-responsive layout (unlike `ScenesPage.tsx`'s
`useIsPhone()` treatment) — its toolbar is cramped at a real phone width,
though every control works once reached.

## SPECTRA per-scene colour-set PREFERENCE — a second axis, not the same control as availability

`SceneV2.preferred_color_set_mode` (`"default"|"dark"|"light"`,
`spectra/models/scene.py`, owner ask 2026-08-17: "black hole would prefer
dark mode color sets... they don't run light mode color sets unless the
system is set to light mode"). This is the design `docs/SPECTRA_SPEC.md`
§72 says superseded his own proposed "remove the redundant black
backgrounds" data-edit fix — that edit was investigated, found unsafe
(colour bleed between scenes once a black `bg_color` no longer resets a
virtual), and retired in favour of this build; his authored colour-set
data was never touched by either investigation. Deliberately separate from
`display_availability` above: that field gates whether an item plays AT
ALL in the current room mode; this one gates WHICH colour sets a scene
draws from once it does play. Resolution:
`spectra/services/mode_availability.color_set_preferred(card_availability,
scene_preference, room_mode)` — no preference matches everything; a
declared preference matches every set marked the same way plus every
UNMARKED ("default") set (additive, matching his own "you don't have to
change any color sets"); it excludes only a set marked the opposite mode.
**Hybrid vs explicit, generalised from his one stated case**: he named only
system Light overriding a Dark preference — symmetrized here (explicit
Dark also overrides a Light preference) so neither direction can strand a
scene with zero eligible sets — preference is consulted ONLY while the
room is Hybrid; an explicit Dark or Light room mode uses the
availability-filtered pool as-is. Wired at the one choke point that
already applies availability to a colour-set pool,
`scene_sequencer._default_eligible_sets` — not `drift_conductor`'s
destination pool or `scene_response.py`'s flare colour-jump pool, neither
of which apply availability there either (checked, not assumed to be
covered).

**The fallback that must not go wrong**: his real `color_sets.json` had 0
of 50 sets carrying any dark/light marking at build time, so on deploy day
every scene's preference matches nothing marked — the fallback MUST be the
full unfiltered pool, never empty (an empty pool would go a preferring
scene dark the instant this ships). `color_set_preferred()` guarantees
this by treating an unmarked card as matching every preference;
`tests/test_color_set_preference.py::
test_preference_never_produces_an_empty_pool_when_nothing_is_marked` proves
it against a 50-set unmarked library rather than asserting it. No second
marking system was built — the existing Mode availability toggle on a
Colour Set (`ColorSetsPage.tsx`) is the one surface that marks a set dark
or light; `ColorSetsTab.tsx` shows each set's marking read-only so it's
visible while choosing a scene's preference.

**Editing an existing SceneV2 by script: never round-trip through
`scene_store.save()`/`model_dump_json()` for a single-field change.**
Loading a scene through `SceneV2` and writing it back re-serializes EVERY
field in current canonical form — in particular it runs
`_migrate_flare_kinds`, the legacy flare-band migration shim, and
permanently rewrites `param_patch`/`gain`/`reroll_dice`/`color_set_jump`
into the newer `flare_kinds`/`kinds` shape on every scene it touches, even
though the model asserts the two are behaviourally equivalent — caught
(before merge) doing exactly this in `scripts/set_scene_colorset_
preference.py`'s first draft while setting one unrelated field. The fix,
and the pattern for any future single-field scene migration script: load
the RAW JSON dict, use `SceneV2(**raw)` only to READ (validation, name
matching, diagnostics), and write back by mutating the raw dict's specific
key directly — `tests/test_set_scene_colorset_preference.py` diffs
before/after JSON to prove only the intended key ever changes.

Docs: `docs/SPECTRA_SPEC.md` §74. Spec: `tests/test_color_set_preference.py`
+ `tests/test_set_scene_colorset_preference.py`. Migration:
`scripts/set_scene_colorset_preference.py` (dry-run default, `--apply`,
backs up the whole store first) sets Black Hole V2 / Black Hole V2 UI /
Fireworks V2 / Dancers V2 to `"dark"` — not run against live storage by
this build, an operator/deploy step same as `seed_star_strips.py`'s own
convention.

## SPECTRA Sonic token-usage record (review page)

`spectra/services/sonic_usage.py` — durable per-call token usage, his ask:
last query / this day / this week, on the Review page (not settings
console — that's where he asked). Captured at the runtime response itself
(`settings_agent.py`'s Anthropic SDK `response.usage`, summed across a
turn's tool rounds; `settings_agent_cli.py`'s `claude -p` final `result`
event's own `usage`/`modelUsage`/`total_cost_usd`) — never estimated; a
call the runtime doesn't report usage for records nothing, no fabricated
zero. **Day/week are FIXED periods anchored Monday 22:00 America/New_York
(stdlib `zoneinfo`, DST-aware), NOT rolling 24h/7d** — his own overruling
ask, because that boundary is presumed aligned to his subscription's own
quota reset, so the figure reads as "how much is left," not just "how
much was spent." Bucketed at READ time against stored `wall_ms`
timestamps (`storage/spectra/sonic_usage.json`), never pre-assigned at
write time, so a future anchor correction re-buckets history correctly.
No DI seam (same class as `fire_history.py`) — `tests/conftest.py`'s
autouse `_isolated_sonic_usage` repoints `config.SONIC_USAGE_FILE`; a new
script reaching `record()`/`summary()` for real needs the same repoint.

## SPECTRA S3 light ownership + handover (BUILT AND PROVEN, GATED OFF)

Exactly one process owns the lights. The durable record is
`storage/spectra/ownership.json` via `fx/light_ownership.py` (shared library;
missing file = spot-effects owns — the shipped default). Enforced in the
write paths, not convention: `api/ledfx_client._request()` sheds every call
when not owner and the LedFX-restart watchdog goes dormant (never resurrect a
quiesced LedFX — merge-scout §4d trap); `spectra/services/fx_seam` routes
HTTP↔facade by owner and refuses mid-handover; `fx/host.py` refuses non-dummy
devices without a step-gated ActivationGrant. Two-step handover
`spectra/services/handover.py` (READINESS GATE first — the order-8 fix: a
missing/empty/unusable fx-live config, or a missing LedFX unit on the
reverse path, REFUSES with HTTP 412 before the record moves or anything
quiesces, naming the seeder; then quiesce → verify → activate → commit;
every failure lands single-owner), live stack `spectra/services/live_host.py`
(device layer + audio hub + frame-freshness tap). THE LIVENESS ENDPOINT
CONTRACT: `GET /spectra/api/liveness` (`spectra/api/ownership.py`) — never
delete or repoint without the Admiral's word. The handover API is inert until
`SPECTRA_HANDOVER_ARMED=1`; arming and running it is the owner's word —
procedure in `docs/SPECTRA_HANDOVER.md` (go-day seeder
`scripts/seed_spectra_fx_live.py`). Spec:
`.venv/bin/python scripts/check_ownership.py` + `tests/test_handover.py`.

A third owner state, `released` (`fx/light_ownership.RELEASED`), is the
owner's panic handle — `spectra/services/release.py`, `POST
/spectra/api/ownership/release`, the SPECTRA UI's red button
(`RoomOwnershipBar.tsx`). Unlike the handover above it is NOT armed-gated
(going to no-writer is always safe): one atomic step sheds both worlds'
write grants, then each device is told to let go explicitly rather than
left to time out — WLED gets the JSON API's `{"live": false}`
(`fx/utils.py WLED.release_realtime`, wired in `fx/devices/wled.py`; WLED's
own firmware then resumes its on-device show, unlike Hue below), Hue gets
BOTH a bridge-side dim-to-off fade over direct REST
(`spectra/services/release_fade.py`, run before the stream itself stops —
2026-08-14 fix: stopping the entertainment session alone left the bulb
holding SPECTRA's last streamed frame indefinitely, since Hue has no
on-device show to fall back to) and the entertainment session stop
(already explicit — `fx/devices/hue.py`), the external LedFX service's
active virtuals are deactivated over its API. The off write's own 2xx is
not trusted either (spectra-audit-2xx-proof, 2026-08-16, `docs/
SPECTRA_SPEC.md` §64): `release_fade.py` reads each light back after the
off write (one paced retry if still on) and returns any still-on light's
bridge name in `still_on` — his Hue bridge 2xx's a write whether or not
the physical bulb took it (D6), the same fact `ambient.py`'s own
`_hold_and_confirm` was built for, just never applied here until this
pass.
Cleanup runs against BOTH worlds on every press regardless of which one the
record said owned (a rogue writer the record doesn't know about, e.g.
systemd's `Wants=` resurrecting `ledfx.service` behind its back, is
tonight's-incident-shaped and must still be addressed) — see
`spectra/services/release.py`'s module docstring. The external-LedFX calls
go through `spectra/services/ledfx_release.py`, a direct httpx client (same
pattern as `handover.py`'s `SpotEffectsSide.verify_active()`), never through
`api.ledfx_client`: that module's ownership gate sheds every call once the
record has moved to `released` (which happens before cleanup runs), and
routing around it also keeps spectra/'s import discipline (nothing under
`spectra/` imports spot-effects runtime internals) — see
`check_process_split.py` §1b. `release_room()` also verifies afterward
(`_verify_released()`): SPECTRA's stack via `live.active`, the external
service via the same systemctl-is-active check `handover.py` uses, falling
back to a virtuals read-back when that unit is still running — PLUS, since
the §64 fix above, any `still_on` light `release_fade.py`'s own read-back
named. It returns a `ReleaseResult` (record/verified/problems) — the
record always lands `released`, but the API reports
`result="released-unverified"` (HTTP 207) with the specific `problems`
when a device (LedFX virtual or a Hue bulb by name) couldn't be confirmed
dark, instead of silently claiming success.
The way back is the SAME guarded handover, still armed- and readiness-gated
(`run_handover`'s `from_world=="released"` skips the vacuous quiesce step).
Spec: `tests/test_release.py` (+ `tests/test_release_fade.py` for the Hue
fade itself) + `check_ownership.py` §12. Live-fixture proof after a real
press (offline tests can't reach a bridge): `scripts/verify_release_fixtures.py`
— read-only, GET-only CLIP v2 + WLED `json/info`, no writes.

### Two-writers prevention build (2026-08-13 incident: `Wants=ledfx.service`
in the unit resurrected a deliberately-quiesced LedFX on a routine
`systemctl restart spotfx` while SPECTRA owned — see
`/home/javi/fleet-spotfx/data/spectra-two-writers/report.md`)

`deploy/spotfx.service` no longer `Wants=` ledfx (kept in `After=` for
ordering only) — the handover orchestrator is the only legitimate
starter/stopper of that unit. Two continuous reconcilers, one per process,
each periodically assert the ANTI-state (never their own health) rather
than trusting the ownership record forever once proven true at handover
time: `spectra/services/ownership_reconciler.py` (while spectra owns,
`ledfx.service` must be inactive and no foreign realtime source may hold
her WLEDs — read via each device's own `wled.get_state()` `live`/`lip`)
and `services/spectra_liveness_reconciler.py` (while spot-effects owns,
SPECTRA's own `/spectra/api/liveness` must not report `live`/`split-brain`).
Both alarm-only (CRITICAL log) by default; `SPECTRA_RECONCILER_ESCALATE=1`
arms a sustained-violation drop to `released` (the already-proven panic
handle) — same "gated until the owner's word" posture as
`SPECTRA_HANDOVER_ARMED`. `spectra/services/handover.py`'s `run_handover`
re-verifies `from_side.verify_quiesced()` immediately before `commit()`
(closes the verify→commit resurrect gap) and `api/ledfx_client.py`'s
LedFX-restart watchdog now requires a genuinely dead probe (not sustained
high RTT alone) plus a named veto (`_ledfx_restart_veto_reason`) checked
immediately before spawning `systemctl`. Spec:
`tests/test_ownership_reconciler.py`, `tests/test_ledfx_watchdog_veto.py`,
`tests/test_handover.py`.

The crystal lazy-activation class (a handover/resume brought up only SOME
config-declared virtuals and still reported success — a mapper-chain
virtual excluded from the old "every ACTIVE virtual" freshness check is
invisible to it, vacuously healthy): `spectra/services/live_host.py`'s
`LiveLights.activation_gaps()`/`wait_fully_active()`/`device_gaps()`
compare the fx-live config's declared-active virtuals (whatever a scene
fire or the seeded baseline persisted) against runtime reality — per-virtual
frame freshness AND, for WLED-backed virtuals, the device's own `live` flag,
never assumed from the host's in-memory state alone. A fresh handover
(`SpectraSide.verify_active()`) rolls back on ANY gap — there's a known-good
from-world to fall back to. `resume_own_room` (process restart while
already owner, no from-world to fall back to) instead reports every gap
loudly (CRITICAL + the liveness endpoint's `activation_gaps` field) and
leaves every other device driving — one failing device must never strand
the rest. Spec: `tests/test_crystal_activation_verify.py`.

The fresh-handover path's naming gap (SpectraSide.verify_active() used to
return a bare bool — a refused take-back couldn't say which light):
`live_host.describe_gaps()` builds a named detail from `activation_gaps()`/
`device_gaps()`, `verify_active()` logs it CRITICAL and stashes it on
`verification_detail()`, and `run_handover` folds that into the
`HandoverFailed` message the `/ownership/handover` API's `error` field
returns verbatim — read by `spectra/web/src/api/client.ts`'s `errorDetail()`
(which must check BOTH `detail` — FastAPI's default HTTPException shape —
and `error` — this route's own JSONResponse shape — or a named refusal is
silently dropped before it reaches the toast). `resume_own_room`'s own
naming (above) is untouched; both callers now name every gap, by design,
in the paths built for each.

`expected_active_ids` (what the gate above validates against) used to be
EVERY virtual fx-live/config.json declares active — that config is seeded
VERBATIM from the old LedFX world and inherits its dynamic tricks (mask/
foreground/background layer virtuals, gap-dummy placeholders, a full-span
duplicate of a mapper virtual, legacy contextual rooms SPECTRA's own scene
engine never addresses), so the gate could refuse forever on layers never
supposed to rise. `spectra/services/room_topology.py`'s
`genuinely_driven_virtual_ids()` — the SAME ground truth
`scene_compiler.compile_scene()` itself resolves real fires against
(`fx.device_model`'s imported category topology ∪ stored scenes' literal
`target_kind="virtual"` targets) — is intersected into `expected_active_ids`
at every activation; an ABSENT ground truth (no categories imported, no
scenes) falls back to the raw declared set rather than vacuously passing.
`scripts/check_spectra_expected_active.py` is the evidence-printing,
dry-run-by-default correction script (the `seed_spectra_fx_live.py`
pattern) for the PERSISTED config — diagnostic/belt-and-braces, since the
runtime intersection above is the actual fix. Spec:
`tests/test_spectra_activation_truth.py`.

## SPECTRA fx/ (vendored LedFX render pipeline, Stage 1)

`fx/` is the LedFX render pipeline vendored from the fork at commit
`149f4470` — provenance, inventory, and the complete deviation list live in
`fx/VENDOR.md` (keep vendored files verbatim; re-diff against that commit
when updating). The in-process switch is `settings.fx_in_process` (default
OFF; production runs HTTP) at the `api/ledfx_client._request()` choke point —
the public client functions are the seam; don't fork per-transport logic in
callers. Offline dummy-device harness: `fx/headless.py` +
`tests/test_fx_headless.py` (deterministic frame-stepping under a fake
clock; `silence_audio()` is mandatory in any fx test — fx must never open or
enumerate audio devices). Stage 2 shared audio ingest: `fx/audio_ingest.py`
(fan-out hub + hub-fed melbank source; design rationale in its docstring) +
`api/audio_ingest_adapters.py` + `tests/test_audio_ingest.py` — DARK, nothing
in main.py references it; production still runs its own capture streams until
a later wiring stage. The Hue-DTLS / DDP single-sender exclusivity with the
running LedFX service is resolved by the S3 ownership gate: the facade
reaches live hardware only through the handover (see the S3 section above).

## SPA `index.html` must revalidate every request — checking the server is not checking what the browser fetches

Found 2026-08-17: both SPA mounts (`main.py`'s `/app`, `spectra/app.py`'s
`/spectra` — each has its own `SPAStaticFiles(StaticFiles)` subclass, not
shared) served `index.html` with `last-modified`/`etag` but **no
Cache-Control at all**. With no Cache-Control, browsers apply heuristic
caching and can reuse a stale `index.html` for a while without
revalidating — and a stale `index.html` names the OLD content-hashed
bundle filename. His phone kept showing old behaviour on a page reported
finished, while `curl`ing the served bundle proved the new code WAS built
and deployed correctly. **The check itself was aimed one step short: proving
what the server serves is not proving what a given browser will fetch** —
a client sitting on a cached `index.html` never even asks whether it
changed. Verifying a frontend deploy landed for the person looking at it
needs the response's `Cache-Control` header checked, not just the bundle's
content.

Fix, both `SPAStaticFiles.get_response` overrides: `index.html` (and the
SPA-fallback response served for any unknown client route) →
`Cache-Control: no-cache` (revalidate every time via etag — not "never
store"); hashed files under `/assets/` → `Cache-Control: public,
max-age=31536000, immutable` (content-hashed, so a new build always
produces a new filename — safe to cache forever). `services/
spectra_proxy.py` passes all non-hop-by-hop response headers through
unchanged, so a header set on the SPECTRA process (`:8010`) reaches
clients through the spot-effects proxy (`:8000`) verbatim — confirmed by
reading the proxy's `_pass_headers`, not assumed. Regression coverage:
`tests/test_spa_cache_headers.py` (parametrized over both mounts; proven
red against the pre-fix code, green after).

## SPECTRA spec, rendered for a phone: `GET /spectra/spec`

He asked for a link three times and got a file path twice. `docs/
SPECTRA_SPEC.md` is ~150KB of dense, table-heavy markdown — a raw link to
it is technically a link, practically useless on a phone. `spectra/
services/spec_viewer.py` renders it server-side (python-markdown,
`tables`/`fenced_code`/`toc`/`sane_lists` extensions, no caching — reads
the file fresh every request since the spec is a living document) into a
phone-first HTML page reusing SPECTRA's own purple-on-black tokens
(`spectra/web/src/styles/tokens.css`'s values, hand-copied since this is a
server-rendered page outside the SPA bundle, not a React component).
Route: `spectra/api/spec.py` (`GET /spec`, deliberately outside `/api` —
this is a page a human opens in a browser tab, not a JSON endpoint),
registered in `spectra/app.py::create_app()` before the SPA's catch-all
static mount so the exact path wins (same precedent `/api/status` and
every other explicit route already relies on). No new server, no new port:
`/spectra/*` already reaches this process through spot-effects' reverse
proxy at `:8000`, the address he actually uses.

**Long tables are the hard part at phone width.** Every rendered `<table>`
is regex-wrapped in its own `.table-scroll` (`overflow-x: auto`) container
— the table itself is free to be wider than the viewport, but only that
container scrolls, never the page (`html`/`body` carry `overflow-x:
hidden` as a backstop) — same "contain the overflow, don't force content
narrower than it needs to be" shape as the device-preview strip's own
phone-matrix fix. Verified at a real 390×844 viewport (chrome-devtools-axi
via Playwright Chromium): `document.documentElement.scrollWidth ===
clientWidth` (no page-level horizontal scroll) while a real table's own
`.table-scroll` measured `scrollWidth` (1107px) well past its container's
`clientWidth` (349px) — the overflow is contained exactly where intended.

**Verify a route under `/spectra/*` by fetching it THROUGH the reverse
proxy, not only the standalone SPECTRA port** — the proxy is a real extra
hop that has silently broken things before (see the cache-header entry
above). Both mounts answer HTTP 200 for any unknown path by serving the
SPA's own `index.html` (~460 bytes) — a 200 alone proves nothing; check
size and content. Proven by running an isolated `main.py` (spot-effects
proxy) pointed at an isolated `python -m spectra` on spare ports (never the
live `:8000`/`:8010`): `GET /spectra/spec` returned byte-identical 240,106-byte
HTML through both the direct SPECTRA port and the proxied port, while `GET
/spectra/<unknown-path>` on the same proxied mount returned exactly the
460-byte shell — the two are verifiably different responses, not the same
200 read twice.

Two user systemd units since the S3 process split: **`spotfx.service`**
(`.venv/bin/python main.py`, port 8000) and **`spectra.service`**
(`.venv/bin/python -m spectra`, port 8010; reference units + one-pass
apply in `deploy/` and `docs/SPECTRA_PROCESS_SPLIT.md`). Backend changes:
restart the unit that owns the changed code (`systemctl --user restart
spotfx` / `spectra`; spectra restarts auto-resume the room if she owns
it). React UI (`/app/`) is served from `web/dist` — rebuild with
`cd web && npx vite build` (frontend-only changes need no restart; refresh
the browser).

## Tests

`pip install -r requirements-dev.txt && python -m pytest` (plain pytest, no
async plugin — tests drive their own loop; see `tests/conftest.py` for the
fake-LedFX harness). No live access from tests, ever.

**A fake FastAPI server built inside a test-helper function silently 403s
every WebSocket handshake if the file has `from __future__ import
annotations` (every file in this repo does) and the endpoint's own
`WebSocket`/`WebSocketDisconnect` names are imported locally inside that
function instead of at module level.** FastAPI resolves a stringified
annotation against the function's `__globals__` (module namespace), not an
enclosing function's locals, so it can't find a name that only exists
inside the helper — and fails by rejecting the handshake with HTTP 403,
not a clear error. `test_process_split.py`'s `_backend_app()` gets this
right (imports `WebSocket` etc. at module level, endpoint nested inside
the function); copy that shape, not a self-contained "import everything
inside the helper" one, for any new fake-server test fixture
(`tests/test_device_preview.py`'s `_fake_ledfx_app()` hit exactly this).

**A mock Hue bridge handler built with `_bridge_client(cfg)` returning a
FRESH `_hue_handler(calls)` (state closure and all) on every call, instead
of one handler built once and reused, silently resets the mocked bulb back
to its off/D65 default on every single `async with _bridge_client(cfg) as
client:` block.** Code under test (`ambient.py`) opens a new client per
operation — the hold, an out-of-band write, a later verify/repair — so a
per-call-fresh handler makes a later check unable to see an earlier
write's real effect; it just sees a coincidental default instead. Found
2026-08-16 (`tests/test_ambient_music_gate.py`'s `hue_room` fixture had
exactly this bug, `spectra-hue-burst-drop-and-false-unlit`): an "off bulb
stays off" test still passed, by coincidence, because the fresh handler's
default state IS off; a new "on-but-wrong-colour gets repaired" test
failed until the fixture built its handler ONCE outside the per-call
closure, matching `tests/test_ambient.py`'s own correct `bridge` fixture.
When writing any multi-step live-state test (write, then a later separate
check), verify the fixture shares ONE handler/state across every
`_bridge_client()` call the test will make, not one rebuilt per call.

**When a `check_*.py` spec script mutates a module-level constant to speed
itself up, restore it from a captured `_orig_*` variable, never a
hardcoded literal.** `scripts/check_spectra.py`'s ambient section captured
`_orig_confirm_settle`/`_orig_write_stagger`/`_orig_retry_spacing` before
zeroing them for the run, and restored from those — but
`AMBIENT_TRANSITION_MS` was restored to a bare `1500` instead, the one
constant of the four not following the pattern. It happened to be
harmless only because 1500 was still the real default; extending
`spectra/services/ambient.py`'s `AMBIENT_TRANSITION_MS` to 3000ms
(2026-08-16, `docs/SPECTRA_SPEC.md` §63) would have silently left the
module at the wrong value for the rest of that process's life had this
not been caught. Capture-then-restore, not hardcode-then-restore, for any
constant a script mutates.

## LedFX write plane: one gate, and its liveness signal

Every SpotFX→LedFX HTTP call goes through `api/ledfx_client._request()` —
semaphore + circuit breaker + a hard per-request deadline that also covers the
slot wait (load-bearing: the 2026-08-12 outage was 24 leaked slots parking
every later call forever, with zero failures logged — see
`tests/test_ledfx_gate.py`). When debugging "LedFX seems fine but nothing
changes": check `/api/debug/ledfx-health` — `last_completion_age_s` climbing
while the RTT probe is healthy is a wedged write plane, not a LedFX problem.
Effects self-animate in LedFX, so a dead write plane still *looks* like a
working light show.

Tripwire behind the self-heal: `services/write_plane_watchdog.py` (own
supervised task) evaluates `get_health()` every 30s and pings systemd's
watchdog only while the write plane is alive — breaker-open (LedFX-side
outage) counts as alive; predicate rationale is in its docstring. Inert until
the live unit gains `Type=notify`/`WatchdogSec` (`deploy/spotfx.service` is
the documented snippet; deploying it is an owner action).

## Editor Preview (per-level test fires)

`POST /api/events/preview` fires an UNSAVED payload: `{event: MusicEvent}`
(whole draft) or `{action: Action}` (subtree, wrapped in an in-memory
composite). Engine entry: `trigger_engine.fire_event_object_now()` (the body
of `fire_event_now`, which now resolves the id and delegates). Frontend
wrappers live in `web/src/lib/preview.ts` — group children (lanes / steps /
options / morph lanes) are re-wrapped in a single-child copy of their parent
group with delays/offsets/energy gates neutralized. UI: `PreviewButton`
(▶, sits between ⧉ Duplicate and ✕ Delete at every editor level).

## Shared TopBar

`web/src/components/TopBar.tsx`, mounted in `App.tsx` under the nav on every
page: engine play/pause (`/control/pause|resume`), Dinner Party 🍽️ and
Ambient 💡 icon toggles (AmbientButton has a `compact` prop), active Scene /
Color Set chips, sync-lock status (listens to `xcorr_monitor` WS), track
title/artist + position/duration, and a color-coded ⚡ intensity score for
the last fired trigger (`trigger_fired` WS now carries `intensity`; both
engine broadcast sites pass `trigger.intensity`). Now Playing no longer
shows these controls/info.

## `librosa_offset_ms` is unreliable — don't shift section/beat times by it

`LibrosaAnalysis.librosa_offset_ms` is meant to convert WAV-capture time to
song-relative time, but the stored values can't be trusted: nonzero on ~74% of
the 671 analyses, with outliers into the tens of thousands of seconds (one is
75,308,324 ms). The codebase is split on it —
`embedded_trigger_service` adds it, while `load_sections_for_uri()` and its
consumers (`signal_resolver._section_energy`, the `section_energy` binding,
`trigger_engine._section_intensity`) read section/beat ms **raw**.

**Follow the raw convention for anything that has to line up with playback
position at runtime**, so baked values agree with the live bindings. Evidence:
user-authored triggers in profiles with `offset == 0` snap exactly to librosa
beats (median distance 0 ms, 70% within 40 ms). On nonzero-offset songs a
per-song best-fit shift (voting over `beat_ms - trigger_ms`) matched the stored
offset in **0 of 126** files — the stored number is noise, not a real shift.

## Backfilling trigger intensity from section energy

`scripts/backfill_trigger_intensity.py` sets each `MusicTrigger.intensity` from
the librosa section energy at its timestamp; a trigger within 2 beats *before* a
section line takes the **next** section's energy (a build placed just ahead of
the drop should fire at the drop's level). Dry-run by default; `--apply` writes
and first copies `storage/profiles/` to `storage/backups/profiles-preintensity-<stamp>/`.
Idempotent. Current library state: `--curve minmax --floor 0.05`.

### Raw `energy_rms` skews high — renormalize it

`librosa_service._detect_sections` divides by the loudest section only
(`energy / max_e`) with **no floor subtraction**, so a song's quietest section
lands at `min/max` — median **0.33** library-wide, never near 0. It also works
in **linear RMS**, and modern masters are heavily limited (median song-wide
dynamic range only **~9.6 dB**), compressing real loudness differences into a
narrow band near the top. Raw trigger intensities came out p25=0.68, median=0.84.

`--curve` picks the mapping (all per-song):
- `minmax` (default) — linear min-max stretch. Fixes the missing floor, keeps
  relative magnitude. Gives p25=0.50, median=0.76, 25% below 0.5.
- `raw` — original behavior.
- `rank` — percentile rank. Uniform spread (p25=0.27, median=0.54, 45% below
  0.5) but discards magnitude; near-equal sections can land far apart.
- `dbstretch` — **counterintuitive: pushes values UP, not down.** Because energy
  is already max-normalized, linear 0.5 is only −6 dB, so dB mapping raises it.
  Does not help if the complaint is "everything reads too high".

`--gamma` post-shapes (>1 pushes down), `--floor` lifts the bottom. A floor is
worth keeping: under bare `minmax` the quietest section maps to exactly 0.0,
which hit **427 triggers (4.2%)** and makes any effect scaled by
`trigger_intensity` a no-op.

### Safe to run against a live app

`profile_manager` caches only a `{uri: filename}` index and re-parses each
profile from disk on every `load_profile_by_uri`, so there is no in-memory
profile object to clobber the edit (unlike the HA storage-file gotcha). Writes
are atomic (tmp + replace) and use `ensure_ascii=True` to match how the app
serializes profiles (`\uXXXX`).

`storage/audio_shapes/*.wav` writes (`services/audio_shape_service._save_wav_and_analyze`)
are also tmp+`os.replace` atomic, for the same live-safety reason: an offline
batch pass (`scripts/rerun_librosa.py`) can be reading a WAV from the same
path while a live re-capture of that song overwrites it — a direct in-place
`sf.write` truncates before streaming, so a concurrent reader can land on a
partial file (`soundfile`'s "System error"/"Format not recognised"). This was
the 2026-08-14 librosa-backfill failure root cause (19/500 songs); the same
race exists for anything else that writes into `audio_shapes/` — write atomically.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
