# Scenes, flares and the trigger/timing engine

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

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

**A Colour Set or Group can be DISABLED (2026-08-25, PR
fm/colorset-disable, his ask: "i want to be able to disable color sets like
i can scenes")** — `ColorSetCard.disabled`, deliberately the SAME model as
`SceneV2.disabled` (plain persistent bool, no timer, `False` default, so
nothing about his room changed on deploy; `color_set_store.save()` rewrites
only the card it is handed, so the field arrives lazily per card and his
`storage/color_sets.json` was never mass-rewritten). Added to BOTH
`ColorSetCard` definitions (the documented "defined twice" trap). Gated at
AUTOMATIC choice only, each choke point checked individually rather than by
family (§86's lesson): `scene_sequencer._default_eligible_sets`,
`color_set_groups._selectable_members` (renamed from
`_mode_available_members`) + `resolve_for_fire_mode_gated`,
`drift_conductor._destination_pool`, `scene_response._default_eligible_sets`.
**`scene_compiler.room_active_set` deliberately does NOT gate** — a disabled
set that is the room's live palette keeps painting until the next natural
change picks something else; re-checking there would drop the room to no
colour the instant he flipped the toggle. A disabled GROUP stops being
chosen as a POOL but keeps contributing its override entries AND its
likelihood curve to an enabled member fired by its own id (both are
authoring layers on a still-enabled set, not a choice). Explicit human use
(`POST /api/room-color/apply`, the editor's Preview) still works and NAMES
the contradiction (`overrode_disabled`), the Force-Scene precedent. Pool
exhaustion is safe AND loud: an empty eligible pool (easy above
`rainbow_select_limit` if he disables the rainbows) keeps the room's current
colours via the kernel's terminal rung and reports
`rung="pool_exhausted"` + a disabled count on the sequencer status strip,
never a silent keep. Spec: `tests/test_color_set_disable.py`.

**A FLARE KIND can be disabled too, and every enable/disable is now ONE
⏻ POWER BUTTON (2026-08-27, PR fm/flare-power-buttons)** — his ask:
"disable/enable flares. Replace disable/enable with a power button, and
light it green when it is on and dim when disabled. Allow me to disable/
enable straight from the selection bar for scenes and colorsets and from
the flare bar for flares." Two halves:

- `FlareKind.enabled` (`spectra/models/scene.py`, default `True`, gained
  lazily — `scene_store.save` rewrites only the scene it is handed, so his
  file was never mass-rewritten). NOTE THE POLARITY: a kind is `enabled`,
  a scene/set is `disabled` — deliberate, because the control is a power
  button, and every caller translates at the boundary. Gated at each
  choke point INDIVIDUALLY (the §86 lesson): `scene_response.
  resolve_lane_picks` (never enters its lane pool; a lane whose members
  are ALL disabled fires nothing and SAYS so — `picked: None`,
  `all_disabled: True` in the fire record, "⏻ lane off" in the rack),
  `_execute_band_locked`'s own attached list, and all three forward peeks
  (`band_trigger_offset_ms`, `momentary_switch_would_glide`,
  `color_rotate_lead_ms` — a disabled kind's lead/offset must never steer
  a real fire). An EXPLICIT press still works and NAMES it:
  `ResponseEngine.fire_kind` and `flare_preview.build_timeline` both
  report `overrode_disabled`, the Force-Scene precedent. Sonic's
  `set_flare_kind` takes `enabled` and OMITTING it leaves the stored value
  alone on an update (re-enabling his flares as a side effect of retuning
  a gain would be silent). Spec: `tests/test_flare_kind_disable.py`.
- `spectra/web/src/components/PowerButton.tsx` REPLACES
  `DisabledToggle.tsx` (deleted) everywhere: scene list rows + phone
  selector + scene toolbar, the tiered Colour Sets list rows + card
  toolbar, and each flare kind (palette card AND every lane cell in
  `FlareLaneRack`). Green (`--ok`, a new token) when on, dim when off,
  square, fixed size via the shared `fixedSizeToggleStyle.ts`. A press on
  a scene/colour-set LIST ROW saves immediately — unless that item already
  has other unsaved edits, in which case the flip lands in the draft
  (committing half-finished work as a side effect of a power toggle is
  not what he pressed). A flare kind's flip is an ordinary scene-draft
  edit. The list rows' "⛔ disabled" badge is now the ⛔ GLYPH ALONE
  (wording in its tooltip): measured at his real pane widths, the full
  badge plus the button squeezed a card NAME to zero px; editor headers
  and the phone selector keep the spelled-out badge. Help topics:
  `power-button`, `flare-disable` (both linked, not orphaned).

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
new mechanism to build. At the time, **the override had NEVER applied to a
Set fired by its own id** — in legacy OR here, only when the enclosing
Group itself was the resolved fire target — broadening that to every
direct reference of a member Set was considered and rejected as invented
behaviour, computed against his real data to silently change rendered
output for 27 of 28 (group, member) override pairs.

**He has since asked for exactly that broadening (2026-08-19, PR
fm/spectra-group-overrides-on-direct-call), and it is now built**: "[the
overrides] need to apply when the colour set is called. It still needs to
use the overrides from its parent group." `resolve_for_fire` on a `"set"`
card now chains every enclosing Group's override entries (via
`group_ids_by_set`'s reverse index) onto the Set's own — a Set in no
overriding Group is unaffected. A Set under >1 Group (his real data: 4
under both First Group and Blues) chains ALL of them, deterministic
ascending-by-name order, alphabetically-last wins a field conflict — never
picks one Group and discards the rest (would invent the exact
single-owner concept the tiering above rejected). Re-measured two days
later against live data: still 27 of 28 pairs change output — the 28th is
a stale member id in `Lines` that no longer exists, not a "no difference"
case. See `docs/SPECTRA_SPEC.md` §10's own dated note for the full
consequence writeup and `tests/test_color_set_groups.py` for the
multi-group chaining proofs. **Groups also stay real, working pools** — 0 of his ~21k SPECTRA
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

**The terminal fallback (`scene_compiler.room_active_set()`) was missing
`resolve_for_fire` entirely until 2026-08-19 (PR fm/spectra-active-set-
overlay-bypass, `docs/SPECTRA_SPEC.md` §86)** — every choke point above
resolves the overlay when it's handed an explicit set/group id, but a
`fire_scene_by_id(color_set_id=None)` call (100% of his real `fire_scene`
triggers) fell through to this function, which fetched the room's active
set RAW. Fixed there (overlay only, deliberately not mode-gated — see the
function's own docstring for why). The same audit found two more
overlay-missing choke points that also feed a real write:
`scene_response.py`'s flare colour-jump (`_default_set_card`) and
`drift_conductor.py`'s room colour bootstrap (`_bootstrap_room_color`,
first-ever pick on a genuinely set-less room) — both fixed the same way.
Before trusting a "this choke point already resolves the overlay"
belief, check the specific function, not just the family — three
separate ones in this one area didn't.

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

## TWO trigger copies — a Timeline save now lands in BOTH

A hand-authored trigger exists TWICE and the two stores drift silently:
the EDITOR copy `storage/profiles/*.json` (legacy `MusicTrigger`; the
Profile Builder timeline at `/spectra/timeline` — his "Timeline of
Spectra" — reads/writes it through the spot-effects root API, `routers/
profiles.py` + `services/profile_manager.py`) and the FIRED copy
`storage/spectra/triggers.json` (`spectra/services/trigger_store.py`),
the ONLY store `spectra/services/trigger_engine.py` ever fires from.
`spectra/services/legacy_trigger_migration.py` landed one into the other
ONCE; nothing kept them together, so by 2026-08-24 his corpus held 623
edited-since triggers across 11 songs that the room had never seen, plus
128 rows whose timestamp/intensity disagreed — his report: "the system
still fires on the old triggers, despite me being in My Triggers Only
mode." The engine was never wrong; the data never arrived.

`spectra/services/profile_trigger_sync.py` is now the reconciler (read
its docstring for the four standing decisions — profile-wins-at-save,
authored-only, provenance-gated deletes, unmappable-takes-its-row-with-
it) and `POST /api/triggers/sync-from-profile` is where it runs. Two
things to know before touching any of it:

- **The seam is HTTP because it MUST be.** The save happens in the
  spot-effects interpreter, which may not import anything under
  `spectra/` (asserted by `scripts/check_process_split.py` §1), so
  `services/spectra_trigger_sync_client.py` posts the whole song to
  SPECTRA — ONE call per save, never one per trigger, and best-effort:
  the profile is already on disk, so a SPECTRA outage reports
  `spectra_sync.status` in the save response (a ⚠ on the timeline's
  ModeBar) instead of failing his save. The receiving end runs on
  `asyncio.to_thread` because the batched write is a full ~9.5MB
  read+rewrite (`trigger_store.apply_batch`, the ONE batched write —
  don't loop `upsert`, ~126ms each).
- **Provenance is a SIDECAR, not a model field.** `spectra/services/
  profile_sync_ledger.py` (`storage/spectra/profile_sync_ledger.json`,
  `{uri: {trigger_id: legacy_event_id}}`) is what tells a
  profile-origin trigger from one born on SPECTRA's own card — the id
  link alone dies the moment he deletes the profile row. A fired-copy
  authored trigger the ledger has never seen is NEVER deleted (18 of his
  are card-born). The stored legacy `event_id` is also the only thing
  that makes the narrow reverse direction faithful, since the forward map
  is many-to-one (35 legacy event ids → 4 SPECTRA action shapes).

Deploy-time catch-up (dry-run default, `--apply`, backs up both worlds,
and asserts the written diff equals the PLANNED diff before claiming
success): `scripts/reconcile_profile_triggers.py` — still the manual
repair path, unchanged and not weakened by the build below.

**SYNC IS A PROPERTY OF WRITING HIS TRIGGERS, not a call each route
remembers (2026-08-25, his order: "let's make sure they do" — he must
never again ask whether his own work reached his show).** The
per-route hook shipped 2026-08-24 covered only `POST /api/profiles`, so
his analysed-trigger import (two songs, 238 triggers) wrote the editor
copy and stopped. Three things now hold, and all three matter:

- **The write marks; a supervised task lands.**
  `profile_manager.save_profile` calls
  `services/profile_trigger_sync_queue.mark_dirty()` on EVERY profile
  write (trivial, non-failing, no event loop needed — the async HTTP
  call cannot happen there); `run_supervised()` (wired in `main.py`'s
  lifespan) drains the marks. A route that reports the outcome in its
  own response syncs inline and calls `clear()`. So a NEW writer is
  synced because it wrote, not because its author remembered.
- **Automatic writers are UPSERT-ONLY; only an explicit save deletes.**
  `plan_song(..., delete_missing=False)` (the wire field on
  `POST /api/triggers/sync-from-profile`) reports what it declined to
  remove as `retained` and CARRIES ITS PROVENANCE FORWARD — dropping
  that would silently demote his deliberate deletions into `protected`
  and they would then survive every future save. Use
  `sync_profile_upsert_only`, never `sync_profile`, from anything
  unattended.
- **Machine-produced triggers carry STABLE IDS**
  (`services/trigger_identity.py`, `analyzed_{event_id}_{timestamp_ms}`
  — the shape the analyzed-trigger cache already used). `MusicTrigger.
  id` defaults to a fresh `uuid4`, so before this every re-import made
  100% of a song's rows read as absent-from-the-profile: the sync
  deleted the lot and re-inserted them under new ids, and the row count
  came out right, which is why nobody noticed. Whether a re-import
  overwrites a mark he has hand-edited since is HIS open trade, so it is
  parameterised (`settings.trigger_import_policy`, `"protect"` default /
  `"replace"`), applied identically server-side and in both
  `ImportDialog.tsx` copies from the one server-owned value.

OFFLINE SCRIPTS THAT WRITE PROFILE JSON DIRECTLY bypass all of this by
construction (no `save_profile`, nothing to mark, and often no SPECTRA
running to reach): `scripts/backfill_trigger_intensity.py` (changes
`intensity`, a field the fired copy carries — its docstring says so),
plus `migrate_quiet_scene_groups.py`, `migrate_sequence_wrappers.py`,
`migrate_remove_precmds_and_gb.py`, `migrate_intensity_scene.py`,
`dedup_ledfx_profiles.py` (event-ref rewrites). The reconcile script is
their catch-up — run it after any `--apply` pass.

`tests/test_legacy_trigger_migration.py::
test_migrate_real_corpus_lands_whole_in_one_pass` asserts hardcoded
counts against his LIVE, still-edited corpus and drifts as he authors —
verify against pristine master before chasing it.

## SPECTRA trigger authoring (THE KEYSTONE — mid-song clock)

This section and "SPECTRA transition-timing alignment" below carry the
lead/offset mechanics inline; `docs/SPECTRA_TIMING_CONVENTIONS.md` is where
they're collected against every OTHER timing quantity in the codebase
(including the predecessor's, and where the two sign conventions collide) —
read it before trusting a lead/offset number from just this section.

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
~11k-trigger corpus) — fine for one human edit, not fine looped inside a
request handler for a multi-song batch. Since 2026-09-09 every mutating
route hands that call to `asyncio.to_thread` and every writer serialises on
`trigger_store.write_lock` (that module's docstring is the binding
statement for both rules), so a batch no longer stalls bridge polls/ticks/
WS broadcasts — it holds the lock instead, starving every OTHER writer (his
Timeline saves included) for the run's whole duration. Run bulk generation
as a separate offline process against `storage/spectra/triggers.json`
directly, the same shape
`migrate_legacy_triggers.py` already used for the authored corpus, never
through the live HTTP endpoint in a loop.

**RE-ANALYSIS — stored analysed cues are stamped and re-planned
(2026-10-04, data/scene-change-ranking-plan/report.md §5).** Every
generated row carries `generator_stamp` (`midsong_generator.
generator_stamp`: GENERATOR_VERSION + the analysed room settings + the
song's own analysis inputs — read its RE-ANALYSIS docstring section). A
stale song is re-planned in one batched write on its next play
(`TriggerEngine.maybe_auto_generate` → `refresh_song_if_stale`); the whole
library is `spectra/services/analysed_refresh.py`, reached by Sonic's
`refresh_analysed_triggers` and `POST /api/triggers/refresh-analysed` —
dry run first STRUCTURALLY (the apply needs the dry run's `plan_id` and
applies exactly what it reported), backup, one write under `write_lock`,
before/after diff that restores anything outside the planned generated
rows. **Bump GENERATOR_VERSION whenever planning changes what an unchanged
song would store**, or nothing re-plans. Three rules every path obeys:
only `source="generated"` rows are touched; a song holding no generated
row is never seeded; a cue he edited or deleted through the trigger API is
CLAIMED (`spectra/services/analysed_claims.py`, a sidecar beside
triggers.json) and its moment is never planned again — before the claims
existed, regeneration seeded a duplicate beside his edit. The room bar
label "Total actions per minute" is the `transitions_per_minute` key
(renamed for him, not on the wire).

**Scene-change settings model** (the Admiral's binding control,
corr=c14a9bcee40e6df9, superseding front 3's plain `midsong_triggers_enabled`
bool): `RoomControlState.scene_change_mode` (`spectra/services/
room_controls.py`, default `"full"`) is `"transitions"` / `"analysed"` /
`"triggers_only"` / `"full"`. The first three form an additive ladder; every
tier fires an automatic scene change on genuine song-to-song transitions —
`trigger_engine._fire_transition`, driven directly from `on_track_state`
(mirrors `scene_sequencer.TransitionSource`'s arm/fire semantics), NOT a
stored trigger, because the tick()-based edge-crossing window is unreliable
at `timestamp_ms=0` (see the module docstring). `"analysed"` additionally
fires GENERATED mid-song triggers; `"full"` additionally fires hand-authored
triggers AND response-engine flares (gated at `engine.fire_response_event`,
the same choke point a bridge-classified flare and a trigger's
`fire_response` action both reach — flares are the owner's authored scene
material, same tier as authored triggers). Gating lives in
`trigger_engine._trigger_allowed` (tick()) and `engine.fire_response_event`.
A pre-existing `midsong_triggers_enabled` value on disk migrates on load
(`room_controls.load_room_controls`): `True → "full"`, `False →
"transitions"`. UI: the room bar's "Scene changes" select
(`RoomControlsBar.tsx`). Spec: `scripts/check_triggers.py`; frame-level:
`tests/test_trigger_engine.py`.

**`"triggers_only"` (2026-08-20, data/spectra-my-triggers-only-mode) is
NOT a fourth rung of that ladder — a PER-SONG PREFERENCE WITH A FALLBACK.**
Built to fix two things at once: (1) `"full"` was labelled "+ My triggers"
in the room bar and read by him as exclusive when the code was additive all
along — every label was reworded so none implies exclusivity/additivity it
doesn't have ("Transitions only" / "Transitions + analysed" / "My triggers
only" / "Everything"). (2) a real double-fire he reported on his own
charge/lull/drop marks, root-caused independently in
`data/charge-lull-drop-timing-blends-and-a-sus-7fm2/report.md` §1: root
spot-effects' legacy trigger engine broadcasts `trigger_fired` over the
shared `/ws` unconditionally (regardless of light ownership), and SPECTRA's
bridge classifies every one of those into `engine.fire_response_event` —
the SAME choke point a SPECTRA-native authored `fire_response` trigger
calls. `fire_response_event` grew an explicit `via_trigger` param
(default `False`, the bridge's unchanged call site, still gated at literal
`"full"`; `True`, trigger_engine's own call site, gated at `"full"` OR
`"triggers_only"`) to tell the two callers apart — this is what lets his
own trigger fire under `"triggers_only"` while the bridge-relayed duplicate
that caused the doubling stays silent, without touching that larger,
separate root-cause defect (root's own broadcast gating) at all.
`fire_scene_update_event` has only the one (trigger-driven) caller, so its
gate simply widened to `("full", "triggers_only")`, no `via_trigger` split
needed. On his own correction — verbatim, "if no triggers exist, use the
analyzed triggers" — this mode resolves PER SONG, not per-crossing/
per-region (a region-level fallback would reintroduce the same doubling
wherever a generated and authored trigger landed close together):
`trigger_engine._effective_mode_for_song` (the stored-trigger gate) and
`_fire_transition`'s own check (the automatic transition fire) each ask
`_song_has_authored_triggers(uri)` independently. **The exact rule, so it
can't be misread: "no triggers exist" means zero triggers with
`source=="authored"` currently stored for the song's own URI — checked
fresh every tick, independent of each trigger's own `enabled` flag.** A
song with ≥1 authored trigger fires ONLY his own (transitions, generated
triggers, and flares all silenced for that song); a song with none behaves
exactly like `"analysed"` for that song. Verified against his real data
before building, not assumed: of 853 songs with any stored trigger record,
only 313 (37%) have any authored one — the fallback is the COMMON path
(540 songs, 63%), not an edge case; of those 313, median 29 authored
triggers and only 4 songs with 1-5, so the "only his" half rarely leaves a
real gap. Deliberately NOT touched by this build: `scene_response.py`'s
charge/lull ramp not scaling with the actual gap — a separate,
independently authorised piece of work (fixed 2026-08-20,
`fm/spectra-lull-ramp-does-not-scale`, see the Override Blend entry
below); bundling the two would have let a fault in one hold up the
other. That fix's own gap computation (`TriggerEngine.
_phase_partner_gap_ms`) resolves the SAME per-song effective mode this
mode introduces (`_effective_mode_for_song`) before deciding what counts
as "next" — a trigger `"triggers_only"` mode-gates out must not count as
the next moment to stretch a ramp toward either.

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

**The legacy engine (root `services/trigger_engine.py`) is retired,
2026-08-20 (his ask: "retire the old engine, but make sure i can bring it
back")** — `settings.legacy_trigger_engine_enabled` (default `False`,
`PATCH /api/settings` or the checkbox on the Settings page, no restart —
checked fresh every tick) gates only the back half of its `run()` tick:
firing from `storage/profiles/` data, the `trigger_fired`/
`pre_scheduled_fired` broadcasts, preview, pre-ramp, scene-override prep.
This is what was double-firing his marks — the bridge classified every
`trigger_fired` broadcast into a flare on top of his own SPECTRA trigger,
regardless of `scene_change_mode`; stopping the broadcast at its source
closes that for good, not just the `"full"`-mode consumption gate above.
**`state.timing` — the sibling field `effective_position_ms()` above reads
`shape_offset_ms` off — is written NOWHERE else in the codebase**
(grep-confirmed): the gate sits *after* that assignment in `run()`
specifically so the retired loop keeps refreshing it every tick regardless
of the flag. Forgetting this and gating earlier in the tick would silently
starve SPECTRA's own xcorr sync — `bridge.py`'s documented "no timing yet"
fallback (raw position, no correction) would go permanently live instead
of being the down-bridge-only case it's meant for. The `TriggerEngine`
object and everything it does OUTSIDE that loop — `load_profile`,
`apply_save`, `reload_shape_offset`, `demote_play_best` (what
`auto_offset_service`'s eight call sites actually use) — is untouched by
the flag either way; proven, not assumed, in
`tests/test_legacy_engine_retirement.py`. Named, not silently lost:
Guest/AirPlay playback (`services/guest_source.py`) drove its light show
through this same loop and goes quiet with it retired — see that file's
own docstring.

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

## SPECTRA transition-timing alignment (intensity-scaled duration + fire-early lead)

`spectra/services/transition_phases.py` is a near-verbatim port of legacy
`services/transition_phases.py` (fx/'s vendored particle-effect
choreography is the same fork, same `BLOOM_START`/`PACMAN_MORPH_START =
0.45`) — a registry of effect-pair `anchor_frac`s plus `lead_ms()`. One
deliberate departure from legacy, kept OUT of the ported module and
applied by the caller instead: legacy's own `anchor_frac()` returns 0.0
(no lead) for an unregistered pair; his ask generalizes that to a plain
0.5 MID-POINT fallback for every other scene transition — see
`trigger_engine._scene_transition_lead_ms`'s own docstring for why that
split keeps the port byte-diffable against legacy.

Two new `RoomControlState` fields, `scene_transition_ms_gentle`
(300ms @ intensity 0.0) / `_hard` (200ms @ intensity 1.0) — his named
"max"/"min" 200/300 are backwards for magnitude, so they're named for what
they represent instead (same shape as `scene_response.py`'s pre-existing
`COLOR_JUMP_RAMP_MS_GENTLE`/`_HARD`). `room_controls.scene_transition_ms()`
linearly interpolates between them; `scene_compiler.fire_scene` consults it
as a NEW third tier under `scene.entry_ramp_ms` and `room.
global_transition_ms` (an explicit flat override still wins over the new
default when he's set one) — applies to EVERY scene fire, not just
trigger-driven ones, since it lives inside `fire_scene` itself. Both
settings are in `settings_console.SETTINGS_REGISTRY` (Sonic-editable) and
have their own numeric fields in `RoomControlsBar.tsx`'s Scenes panel.

`trigger_engine.TriggerEngine.tick()` fires a stored trigger up to
`lead_ms` EARLY (`fire_at = trig.timestamp_ms - lead_ms`) so a transition's
anchor point — a scene's mid-point (or a registered phased pair's own
0.45), a momentary flare's FIRST SWITCH completing (fixed
`DICE_REROLL_GLIDE_MS`, only when the switch actually glides — a
non-smooth param or a momentary gain's spike is always an instant jump and
needs no lead) — lands on the trigger instead of starting there. The
crossing check always ALSO checks the trigger's own unshifted timestamp as
a safety net: `lead_ms` is recomputed fresh every tick from LIVE state (a
registry match against whatever effect is currently on the target
virtual), so it is not guaranteed monotonic tick-to-tick — don't remove
that OR clause when touching this code, it's what keeps a trigger from
silently never firing if an earlier tick's early-fire window gets missed.
Conservative like legacy: an unresolved scene pick (`scene_id=None` — the
kernel/pool decides at fire time) got NO lead under the plain rule above —
**dead on arrival for him: 0 of his 22,013 `fire_scene` triggers ever
resolve a `scene_id`.** LOOKAHEAD (2026-08-19, PR fm/spectra-trigger-
lookahead-lead) fixes this by moving the DECISION earlier instead of
predicting it: `TriggerEngine._pin_for` draws the scene from the same
kernel/pool functions `_fire()` would otherwise call, once, the first time
a trigger enters `LOOKAHEAD_HORIZON_MS` (named constant, = `transition_
phases.MAX_LEAD_MS` — no lead this feature can ever need exceeds that
cap, so it's both necessary and sufficient, not a second tuned number).
That pick is cached (`_PinnedPick`) and `_fire()` reuses it VERBATIM —
there is no second draw to disagree with the first, so a mispredicted
scene is structurally impossible, not just unlikely. The one real risk —
the world moving between commit and fire — is caught by `_pin_still_
valid` (mirrors `fire_scene_by_id`'s own disabled/mode-availability gate,
plus a Force Scene check that's timing-quality only, since `fire_scene_
by_id` always applies the current redirect regardless of which id it's
handed): any of those failing throws the pin away and falls through to
exactly today's behaviour — a fresh draw at the trigger's own nominal
timestamp, zero lead, late but never wrong. A rewind or song change clears
every pin outright. Scoped to stored-trigger fires only — NOT the
automatic transition fire (no forward notice of a song change) and NOT
the sequencer's own dwell-driven rolls (no trigger timestamp to land on).
No live instrument yet proves a real scene-entry ramp lands where
predicted at an actual fire (rendered frame averages and `executor.
recent_writes` are both blind to it) — see `docs/SPECTRA_SPEC.md` §84 for
what building that would take.

Deliberately NOT touched: `SceneV2.choreography` (`PhaseChoreography` —
`enabled`/`transition_ms`/`anchor_frac` default 0.45/`transition_mode`) is
a SEPARATE, still-unwired per-scene field predating this build (see
`docs/SPECTRA_SPEC.md` §28's own note) — this feature does not reach into
or repurpose it; don't conflate the two. Spec: `docs/SPECTRA_SPEC.md` §82.
Tests: `tests/test_lead_time_alignment.py`, `tests/test_trigger_engine.py`
(frame-level proofs 9/10), `scripts/check_triggers.py` §8.

**The hue-arc blend this transition timing rides on had a real
desaturation defect from an achromatic endpoint — FIXED** (`docs/
SPECTRA_SPEC.md` §83, his report 2026-08-19: "goes from black to a gray or
a white and then changes color", PR fm/spectra-achromatic-saturation-fix).
`fx/effects/__init__.py::hue_tween_fields` — requested as
`transition_blend="hue"` by every real scene fire (`fx_seam`/`fx_executor`
both hardcode it whenever `transition_ms>0`, which his real
`global_transition_ms==0` never prevents, since `scene_compiler.fire_scene`'s
`or`-chain fallback treats falsy `0` as unset) — adopted the far end's hue
immediately for an achromatic (black, at minimum) endpoint but interpolated
SATURATION and VALUE as independent linear scalars from 0, i.e.
`sat(t) = t × target_sat`. Fix: adopt the far end's SATURATION too, the
same way hue already was, so only value ramps — proven byte-identical to
the plain RGB path (`mix_colors`) in both directions (fade in from black,
fade out to black), and proven to leave colour-to-colour crossings
(neither endpoint achromatic, e.g. the separately-filed muddy cream→blue
crossing, `data/spectra-grey-midpoint-transition/brief.md`) bit-identical
to before — that pair's own dip lives in `mix_colors`, a different
function, still open as its own backlog item. `fx/VENDOR.md` deviation
#13. Real numbers, before/after: `scripts/check_hue_blend_achromatic_
desaturation.py`, `tests/test_hue_tween_achromatic_saturation.py`.

**A genuine effect-type switch also had a real brightness-coverage gap —
FIXED** (`data/spectra-transition-brightness-flash/report.md`, PR
fm/spectra-brightness-carry-forward, his authorisation: "do it and ride it
with the squiggles deploy"). A type switch builds a FRESH effect instance
(`fx/effects/__init__.py::_apply_config`'s `self._config != {}` branch), so
any base `Effect.CONFIG_SCHEMA` field the outgoing write doesn't set (valid
on any effect type, unlike an effect-specific param) fell back to LedFX's
schema default (`1.0`, full) instead of whatever was actually showing —
real and visible, since 28/50 of his real colour sets never author
`background_brightness` for `crystal-mapper` (27/50 never author
`brightness`), confirmed both offline and live in his room (1216ms/2936ms
at full). Fixed by carrying the previous effect's value forward instead of
a fixed default or fallback — no data-authoring judgment needed, closes the
gap for every under-covered set and any future one at once. Both write
seams already did the GET to detect a type switch and threw the response
away; `fx_seam._current_effect`/`_carry_forward_brightness` and
`fx_executor.FacadeExecutor._current_effect`/module-level
`_carry_forward_brightness` (independent, mirrored copies — the two
modules deliberately don't share code, see fx_executor.py's own docstring)
now reuse that same GET to fill in `background_brightness`/`brightness`
only when the outgoing write doesn't already set them; an authored value
always still wins outright. Bootstrap (no prior effect on that virtual,
e.g. process start before any fire has ever touched it) has nothing to
carry, so today's implicit schema default is unchanged there — LedFX's own
`/effects` PUT handler 400s on a virtual with no active effect at all, so
that case can only be proven at the pure-function unit, not through a live
PUT. Deliberately scoped to exactly these two base fields, not a full
config merge — an effect-specific param (e.g. `particle_count`) genuinely
shouldn't leak from the old effect into the new one. Tests:
`tests/test_fx_write_seam.py`. Real-data proof (his actual
`storage/color_sets.json` + `storage/spectra/scenes.json`, read-only,
driving the unmodified production compiler + an in-process headless fx
host): `scripts/check_brightness_carry_forward.py`.

**THREE anchors, not two — a DROP/explosion anchors its START to the
trigger mark, settled 2026-08-20** (`data/drops-still-fire-early-star-
does-not-explode/`). Black Hole was tried as a "known-good" drop-timing
reference (his original complaint was Orbits reading too early against
it) and then WITHDRAWN when he found Black Hole early too — his resolution
generalizes to three anchor families, each deliberately different, and
none more "correct" than the others: a momentary flare anchors its first
switch's END to the mark (`trigger_engine._response_switch_lead_ms`,
unchanged); a scene transition anchors its MIDDLE
(`_scene_transition_lead_ms`, unchanged); a drop/explosion anchors its
START — begins ON the mark, never before it. `_response_switch_lead_ms`
now short-circuits to `lead=0` for `event_class=="drop"` UNCONDITIONALLY,
ahead of the momentary-glide check the other two classes still use —
proven a STRUCTURAL guarantee, not an accident of his current scene data
(his four real scenes' own drop bands never happened to carry a
qualifying momentary+params kind anyway — `scripts/check_triggers.py`
proves both the real-data case and a synthetic one that WOULD have
qualified under the old, unconditional rule).

Settling the write's own lead didn't fix the visible defect by itself —
the write already landed with zero lead before this change, on every real
scene. The actual visible-onset gap lived downstream, inside each
phase-capable effect's own choreography:
`fx/effects/{blackhole,blackhole1d,squiggles}.py`'s drop payoff (the
particle burst) used to be GATED on `phase_progress` reaching ~0.995 —
anchoring the explosion to the RAMP'S END (~400ms after the mark), not
its start. That gate is now removed in all three — the burst fires
unconditionally on the phase's first rendered frame, matching
`orbits.py`'s own drop branch, which never had the gate (its `burst_done`
flag already fired immediately). Squiggles' end-anchored gate was itself
a deliberate, previously-shipped fix (PR fm/spectra-squiggles-drop-
timing-and-a-much-bigger-explosion, mirroring Black Hole's THEN-good
timing) — this reverses that one specific mechanism while keeping its
other two asks (burst count, burst speed/lingering) untouched; don't read
the reversal as a flip-flop, the REFERENCE it was built against was
withdrawn, not the ask itself. `DROP_FALLBACK_S` (the wall-clock fallback
for a dropped/lost progress ramp) is now dead in all three modules and
removed — nothing waits on `phase_progress` reaching anything any more,
so there's nothing left to fall back from.

`radial.py` (STAR) has no discrete burst — its drop payoff is a
CONTINUOUS smoothstep reveal (`_phase_warp`'s own `e = s²(3-2s)`, gating
the bloom-out warp scale AND the background fade), left unchanged by this
pass. `scripts/check_drop_visible_onset.py` instruments the real
`_phase_warp` and measures where that curve crosses a 5%-revealed
threshold: ~50ms after the mark under the fixed 400ms drop ramp — not
asserted pass/fail (unlike the three burst effects, which ARE asserted at
"within one frame"), because whether a continuous ease-in reads as
"begins on the mark" to the eye is a live-room judgment this offline
instrument can measure but not settle by itself. **Firstmate's own
standing order on this: the onset investigation does not close when the
anchor rule ships — keep measuring the visible onset per effect, in case
the anchor fix and the perceived "still early" report turn out to be two
separate things with only one actually fixed.** Executable specs:
`scripts/check_triggers.py` (the lead-time structural guarantee),
`scripts/check_drop_visible_onset.py` +
`tests/test_drop_visible_onset.py` (per-effect visible onset, all four),
`scripts/check_squiggles_drop_timing.py` +
`tests/test_squiggles_drop_timing.py` (Squiggles' own reversal),
`tests/test_trigger_engine.py` (proof 12, frame-level: a drop's switch is
still IN FLIGHT at the mark, the opposite of proof 10's momentary flare).

**The above shipped a real crash the same night, fixed same-day (PR
fm/blackhole-horizon-none-crash): `blackhole.py`/`blackhole1d.py`'s orphan
watchdog (`_phase_step`, releasing a charge/lull whose drop trigger never
arrived) set `self._drop = {"burst_t": None, "silent": True}` and
`return`ed immediately — skipping the SAME method's own "drop" branch that
resolves `burst_t` out of that `None` sentinel, which every OTHER entry
path (a normal `_enter_phase("drop")`) falls through into within one call.
`draw()` reads `burst_t` via `_horizon_radius()`/`_phase_halo()`
(the 1d strip's own `_phase_post()` read it the same way until it was
retired 2026-10-11 when the strip joined the shared strip phase layer —
see "THE STRIP PHASE LAYER" below) immediately after `_phase_step()`
returns, every frame, with no chance for a next call to self-heal first —
so `None / DROP_RESET_S` raised inside the render thread, killing it
silently (the service kept reporting healthy until the render-plane
dead-man watchdog noticed frames had stopped and restarted the whole
process). Fixed by removing the early `return` so the watchdog path falls
through to the same resolution the normal path already uses — `burst_t` is
now never externally observable as `None`. If you touch a charge/lull/drop
state machine anywhere in `fx/effects/` (`squiggles.py`, `eye.py`, and the
1d siblings all use the same shape), check that every `return` inside
`_phase_step` happens AFTER any sentinel it just set has been resolved to
a real value, not before — `eye.py`'s watchdog path got this right by
never using a `None` sentinel in the first place (it sets a concrete `t:
0.0` directly), which is the simpler pattern to prefer in new code.
Regression: `tests/test_blackhole_orphan_drop_none_crash.py`.

## TRANSITION PROGRAMS — a Matrix effect switch between the main effects is not a crossfade (2026-10-11)

`fx/effects/transition_program.py`'s docstring is the binding statement
for the clock and the registry (transitions-drop plan phase 3, `/home/
javi/fleet-spotfx/data/transitions-drop-plan/report.md`; `fx/VENDOR.md`
#70), `fx/effects/transition_cloud.py`'s for phase 4's programs (#75). A
registered (outgoing, incoming) Matrix switch — INFALL / ERUPTION (Black
Hole <-> Orbits / Fish / Squiggles), LENSING / FOUNTAIN (Fireworks <->
Black Hole), FLAME LICK / IGNITION (Sauron or Eye <-> those five), SHOAL
BREAK / SHOALING (Fish <-> Orbits / Squiggles), UNRAVEL (Squiggles <->
Orbits / Fish) — runs a program with its own clock (room
`transition_program_ms`, 1.4 s) instead of the virtual's stored 0.5 s
crossfade. Eight things:

- **THE REQUEST IS EXPLICIT, end to end.** `scene_compiler.fire_scene` asks
  (`transition_program_for`, against the conductor's current effect types)
  and passes `program=` to `fx_seam.apply_writes` ONLY when a pair applies,
  so every other fire — and every test double of `apply_writes` — keeps the
  old call shape. The facade honours `"program"` only for a registered
  pair against the virtual's REAL active effect. House glides (an explicit
  `transition_ms`) never take one. Previews ask through
  `flare_preview_hold.PreviewContext.apply_scene(program=True)`.
- **ONE PICTURE, BY MAX.** The program composes onto the incoming effect's
  matrix in `Twod.render` (`_transition_program`); never an add, set
  colours only (a `_step` may return a per-cell gain — IGNITION's reveal).
  The incoming effect runs its own kinematics underneath the whole time,
  which is what a cloud implodes onto (`_formation_points()`) — never a
  mirror of its physics.
- **VELOCITY IS CARRIED, NOT RESET.** Snapshots carry `vx`/`vy` + `gesture`
  (Orbits also `om`, its turning rate, which Fish's PEEL continues);
  Black Hole's cross-type adopt continues an inherited velocity, Fish's
  keeps heading/speed/turn rate, Fireworks' `_import_sparks` keeps sparks
  flying. A new effect joining needs `vx`/`vy` in its snapshot and
  `_formation_points()` to be formed onto.
- **FORM IS CHOSEN BY THE INCOMING EFFECT** (`transition_cloud._make_former`:
  Field / Target / Spark / Fade); RELEASE and FLIGHT by the program. An
  outgoing effect's palette is sampled at `capture` (`out_palette`) — a
  deactivated effect cannot size its own gradient.
- **THE LEAD READS THE PROGRAM** (`scene_transition_lead.program_lead_ms`,
  replacing the crossfade lead when a program applies; UNRAVEL's anchor
  depends on direction, so callers pass the pair). A DROP-led cut on a
  program pair (`drop_switch.HANDOFF_PROGRAM`) runs it `on_mark` (anchor 0).
- **THE PREVIEWS DRAW THE STAGES**: `transition_program.stages()` (the
  classes' own `stage_fracs`), placed by `transition_preview.
  _program_on_ruler` on the transition preview and from the cut on the
  drop-sequence preview (`phase_preview._switch_program`).
  Spec: `tests/test_transition_programs.py`, `tests/test_transition_
  programs_phase4.py`; help `transition-programs`; contact sheets
  `scripts/render_transition_programs.py` ->
  `docs/evidence/transition-programs/`.
- **OUT OF STAR (2026-10-13, the star plan)**: Star releases its bands
  through `Radial2d._program_snapshot` (a program asks it before
  `_handoff_snapshot`, which stays empty so crossfade adoptions are
  unchanged) into `transition_program.STAR_OUT` (INFALL / FOUNTAIN /
  IGNITION / UNRAVEL reused, UNWIND / CLUSTER new). Star's own lull B /
  drop D3 / shape morph: the radial-effect skill.
- **INTO STAR (2026-10-14, "Do rec on transitions")**: `transition_program.
  STAR_IN` — every partner's own release (FOUNTAIN / SHOAL BREAK / SPARK
  RINGS / FLAME LICK / UNRAVEL, and WIND = UNWIND with time inverted) with
  Star's FORM, `transition_cloud.RingFormer`: from `STAR_FORM_AT` the pieces
  glide onto Star's bands (staggered, velocity-continuous) while a front
  PACED BY STAR'S CELLS (a steady radial speed lit the crowded middle in
  one go) grows the star from the core; the last frame is the plain star.
  A new former keyed on an incoming effect goes in `CloudProgram.
  _make_former` (and FOUNTAIN's override). Measure a reveal against the
  same frame's raw picture — Melt breathes. Proof: `tests/
  test_star_into_programs.py`.

### THE SHOALING FAMILY RIDES A HOST — a piece is an offset, not a particle (2026-10-17)

The shoal-burst plan (`/home/javi/fleet-spotfx/data/shoal-burst-plan/
report.md`; the Admiral: "The burst particles continue generally moving as
if the original object were still moving, like nothing happened, except it
burst into particles ... Then, the new effect object matches initial
conditions, and starts doing it's own motion, so it smoothly flows, and the
particles recombine into the new object ... 3 fish turn into 3 orbits").
**`fx/effects/transition_cloud.py`'s `HostFormer` docstring is the binding
statement**; `fx/VENDOR.md` #82 lists every hook. Six things:

- **THE ONE IDEA.** `piece_i(t) = host_j(i)(t) + (shape_i + u_i·R·E_burst(t))
  · E_land(t)`. The host is the incoming object this piece's own parent
  BECAME, read live every frame; `shape_i` is where the piece sat inside its
  parent; the burst opens from rest and the gather closes it. A piece's
  motion RELATIVE to what it is joining is the derivative of that bracket —
  bounded by `transition_burst_px` and the envelopes, with **no term that
  grows with distance**, which is exactly what a Hermite to a stranger has.
  MEASURED before/after on the real pipeline, this branch against its own
  merge-base: the new objects are born 13.0/19.2/13.3 px from the released
  ones → 0.47/0.58/0.65 px (fish→orbits, squiggles→orbits, squiggles→fish;
  two unrelated point sets on this panel sit ~11.4 px apart), and into
  Squiggles there was nothing to be born on AT ALL on the program's first
  frame → 0.40-0.56 px. orbits → fish was already 0.77 px and is unchanged
  by it — the Fish's own adopt always did this; what that pair gains is the
  burst it never had (his D1). A piece's speed against the object it joins
  is 0.5-1.5 px/s (the plan measured 39.3 before, 1.36x the parent's own
  speed), and the cloud turns 104-178° where it used to turn exactly 0.
- **ASSIGNMENT IS INHERITED, NEVER SEARCHED** (`object_of` → pid), which is
  also what stops two pieces of one fish being sent to opposite sides of the
  panel. A piece whose host retired continues on the constant-turn model its
  parent published (`transition_program.turn_integrate`) and fades — never a
  flight to a stranger.
- **THE BIRTH IS AN OPT-IN CAPABILITY AND IS NOT `_adopt_handoff`.** An
  incoming form joins by answering `_program_birth(snap)` (born matched,
  returns one pid per released object) and `_program_hosts(pids)` (where they
  are now, NaN for a retired one); without both, the pair keeps today's
  former exactly. The crossfade adoption path is byte-identical, deliberately.
  The snapshot is handed over in `begin()` and consumed on the incoming
  effect's FIRST DRAW, where its geometry is known — except the eruption's,
  which is deferred to its own bloom (`_birth_now`).
- **ORBITS GETS THE VELOCITY GRAFT, FISH NEEDS NOTHING, SQUIGGLES GETS A
  SMOOTH HEAD.** Orbits is position-driven, so
  `drawn(t) = model(t) + v_res·t·e^(−t/τ)` leaves it on the velocity it
  inherited and erases itself (nothing solved backwards). Fish's heading and
  speed ARE its state and `PEEL_S` already eases an inherited turn rate —
  what it was missing is that it computed `omega` every frame and threw it
  away; it is published now. A squiggle's head walks a lattice whose six
  directions sit 45/45/90 apart, so its published heading is averaged over a
  whole segment pair (the Admiral's own correction: "the bursts ... look like
  they go the opposite direction") and anything that RIDES a chain reads
  `_smooth_head`, not the jumping lattice head.
- **THE COUNT RULE (his D3)**: matched on the way in, the scene's own
  authored count a moment (`transition_count_hold_ms`) after the program ENDS
  — never during it; each effect's own population manager flies the
  difference in or out as it does for any live change. The eruption is the
  stated not-applicable case (its ring collapses to a point). A clamp bite
  merges the surplus objects' pieces into the nearest born host.
- **SCOPE IS TIER A, and tier B is held byte-identical.** The 8 shoaling
  pairs plus orbits → fish (his D1, which had no burst at all). His ruling
  was "for scope, dont do B", so the 39 tier-B pairs are proven unchanged
  against a `git archive` of the branch's merge-base — EVERY one of them,
  the four out of Squiggles included: the walk direction he asked to
  correct rides its own `walk_vx`/`walk_vy`/`walk_om` snapshot keys, which
  ONLY `_program_objects` (the host frame's object set) reads, so `vx`/`vy`
  still carry the last lattice move for the four programs that release from
  them and the three effects that adopt them on an ordinary crossfade.
  `transition_burst_px = 0` reproduces today's orbits → fish AND today's
  eruption frame for frame. Specs: `tests/test_shoal_burst.py`,
  `tests/shoal_burst_harness.py` (the rig — read its two determinism traps
  before writing another), `tests/shoal_tier_b_driver.py`; the six room
  settings are Sonic-editable and sit on Settings → "Scenes & drops"; help
  topic `shoaling-burst`. **Unverified against his live room.**

## THE KNOWN AUDIO BUFFER — SPECTRA MIRRORS River's number, never shortens it

**`spectra/services/known_buffer.py`'s module docstring is the binding
statement** (card 1ylu, 2026-09-17; Admiral order 30). River publishes how
far his sound is running behind on its own loopback surface and SPECTRA
subscribes. Six things:

- **THE NAME IS THE INSTRUCTION and is never shortened**:
  `effects_fire_later_by_ms`, River's field name verbatim, everywhere —
  the setting names, the status key, the help topic. A LARGER value means
  the sound is FURTHER behind, so effects fire that many ms LATER. Applied
  as published, never negated. **Order 30: the audio lag is HIS HEADROOM**
  — nothing on this path touches audio, shortens a delay, or reads or
  writes `av_sync_lead_ms`.
- **TWO FEEDS, ONE RECORD, AND NO INBOUND ROUTE.** River pushes nothing
  into SPECTRA: the slow ramp is POLLED (`GET {url}/offset`, every
  `known_buffer_update_period_s`) and a STEP — a drain — arrives on ONE SSE
  subscriber (`GET {url}/events`, current value on connect, reconnect with
  backoff). Both call `record()`. A `POST` here was in the first plan and
  was dropped once River's surface was known; a second way in is a second
  thing that can disagree about the current reading, and
  `tests/test_known_buffer_api.py` holds that structurally. **A step is
  applied AT ONCE and never smoothed across an epoch change.**
- **ZERO IS FORBIDDEN, AND SO IS EVERY SYNONYM FOR IT.** Zero asserts his
  speakers are in sync with the source, the one thing known to be false;
  "uncorrected" and "no correction" are the SAME forbidden thing. The
  missing case falls back to `known_buffer_floor_ms` — a SETTING (500
  default, he proposed it with a question mark), not a constant, and his
  headroom rather than a tuning parameter. `known_buffer_ceiling_ms` is a
  setting and **NOT a clamp**: over it is flagged and passes.
- **STALE IS NOT A FAULT AND IS HALF OF NORMAL.** River re-measures on its
  own 15 s period, so a reading is already up to a period old when
  fetched (measured: `age_ms` 14591 straight off `/offset`), while our
  FRESH window is one period. The ratified ladder is implemented as
  ratified rather than widened; STALE holds the value, changes nothing,
  and surfaces its age. Anything rendering it must say so. River's own
  `stale`/`source` sit beside ours because they answer a different
  question and can honestly disagree.
- **THE APPLICATION GATE — nothing reaches the show while
  `floor_clamped`.** With River's bounding half off it can only see the
  parec buffer, so the number is the contractual FLOOR, not a delay;
  applying it would push his lights 300-500 ms BEHIND the sound.
  `compensation_ms` is reference-based (`effective - reference`, the
  reference anchored on the first reading the GATE ACCEPTS and re-based
  whenever `av_sync_lead_ms` is applied), so going live changes nothing in
  his room.
- **THE SEAM IS THE SHOW CLOCK, LOCK-GATED (ruled 2026-09-17).** MEASURED,
  not inferred: his live `AUDIO_INPUT_DEVICE=pulse` resolves to default
  source `snapcast.monitor`, and `pactl list sink-inputs` shows
  `snapclient-0.35.0` writing INTO that sink — so both the root xcorr lock
  and SPECTRA's own audio hub tap SPEAKER TIME, downstream of the
  snapserver buffer, the network, the snapclient, and River's own
  source-side segment. So `show_clock_ms = effective_position_ms +
  av_sync_lead_ms − known_buffer_ms`, and `known_buffer.compensation()` is
  the ONE definition of that last term, with three answers, two of them
  zero: `gate` (the apply gate is shut), `lock` (`bridge.shape_offset_ms()`
  is not None — the lock already tracks this buffer, and a delta on top
  would correct the same milliseconds twice; an UNKNOWABLE lock counts as
  present, the safe direction), `applied` (no lock, so the
  reference-based delta is real). **IT SUBTRACTS because the families are
  opposite** — `av_sync_lead_ms` is LEAD family (positive = earlier) and
  this is positive = LATER; the two sit on ONE line in
  `av_sync_lead.show_clock_ms`, still the single application point, and
  the new argument defaults to 0 so every pre-existing caller is
  byte-identical. No smoothing at either lock transition or across an
  epoch change. **KNOWN FOLLOW-UP, not done:** on a LOCKED song a drain is
  corrected only as fast as the lock's own chase (2 s × 3 confirms, max 2
  recoveries/play) — see `docs/SPECTRA_TIMING_CONVENTIONS.md`'s own note.

## ENERGY — the one number the engine acts on and every screen shows (2026-10-28)

The Admiral's Energy plan (https://claude.ai/artifact/2Dy1SnUgNQ2fJQomhk4dkh,
"I approve the energy changes"). **`spectra/services/energy.py`'s module
docstring is the binding statement** — read it before touching anything that
reads an "intensity" or "energy". Before it there were six numbers: raw
section loudness (the top bar), a stretched copy (generated cues), his
triggers' stored ⚡, the drop detector's jump size, and the fire value
(any of those × 0.6 × the scale). Now:

- **Energy(t) = clamp(normalized section × 0.8 × the song's scale, 0, cap)**,
  sections in SONG time (+ the capture offset), normalized per song (quietest
  middle section 0, loudest 1; the first/last 15 s don't set the range), cap
  0.75 for a song with no manual Mark (his 15 Aug ruling) and 1.0 for a marked
  one. **The Mark is applied once, inside Energy**: `TriggerEngine.
  _default_render_intensity` and the sequencer's are the identity now — a new
  caller that multiplies by the scale again applies it twice. `intensity_scale.
  combine_measured_and_scale` delegates to `energy.mark_math`.
- **Read at the show clock** (`engine.current_energy`, which `bridge.
  intensity()` now is) — never the raw Spotify position. Drops and scene
  changes **look ahead** `RoomControlState.energy_lookahead_s` (2 s) to the
  next section edge; a generated moment reads its own source section
  (`generator_key` `section:<WAV ms>`); flares and the top bar read the present.
- **The trigger clock resolves Energy per trigger** (`_energized` before the
  lead peek and the fire; `_sequence_energy` for drop sequences; the colour
  journey's `NextCue`) through the `energy_for` injectable — a spec that drives
  a fire at a known value passes `energy_for=lambda uri, t: t.action.intensity`.
- **Nothing reads a trigger's stored `intensity` any more** (his D4). TO REMOVE
  LATER, on his list: that field (profile and fired copies), `scripts/
  backfill_trigger_intensity.py`, and the dialogs' Intensity field and the list
  value (already hidden). The Timeline's "trigger values" background is gone
  from the chip; a saved choice of it draws Energy.
- **Screens**: `GET /api/energy/timeline` (`spectra/api/energy.py`) is what the
  top bar (`LiveEnergyReadout`, every frame at `getShowClockMs`, `lib/
  energyAt.ts`), the audio-shape 'section' background and the song strip's
  terrain draw — full height (0 empty, 1.0 to the top, markers over it), song
  time, Mark included. A Mark edit calls `energy.forget()`, so it lands at once.
- **THE GATES AND CURVES WERE SET ON THE OLD SCALE**: Shockwave 0.7, Pulse flash
  0.8, rainbow 0.9, the drop floor and the Fireworks meld's big-hit strength
  (0.6, which now compares a flare's Energy) rarely pass on Energy (an unmarked
  song tops out at 0.8 × its scale, 0.75 at most). `scripts/energy_parity.py`
  (dry run by default; `--apply --spectra-url` backs up first, `--restore
  <dir>` puts it back) re-sets the five gates and the scene/colour-set
  likelihood curves so the same share of moments passes as before. A NEW gate
  compared with Energy that was tuned on an old number belongs in its `GATES`. The drop-detection stamp deliberately does not carry the
  Energy definition: stored detections stay until the floor itself changes.
  Planner holds read Energy too (`GENERATOR_VERSION` "4", re-plans on play).

Specs: `tests/test_energy.py`, `tests/test_energy_parity.py`,
`tests/test_energy_screens.py` (→ `scripts/check_energy_screens.mjs`); help
`live-energy`, `energy-lookahead`, `intensity-mark`.

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
test repoints this). **Since the 2026-10-28 Energy build (see "ENERGY"
above), `song_scaling_factor()` is no longer called directly from
`trigger_engine`/`scene_sequencer`** — it feeds `spectra/services/
energy.py`'s own `song_factor()`/`mark_math`, the ONE place the Mark
math is applied, read once at the show clock for both SELECTION
(`selection_kernel.select`'s scene/flare/colour-set pick) and the FIRE —
the kernel's own `genre_mult` is a per-candidate weight on the pick, not
a second scaling of Energy, so this is not a double count.

2026-08-15 correction, his words, closed (not a curve-shape question): the
old plan (`final = measured * song_scaling_factor`) was "just a straight
multiplication of a factor" — replaced by `combine_measured_and_scale`,
the one seam: `final = measured_intensity * HEADROOM_RESERVE *
song_scaling_factor`. Since the 2026-10-28 Energy build the constant is
0.8 (his own comment on the Energy plan, "Make it 0.8 instead of 0.6" —
see HEADROOM_RESERVE's own docstring for why it's deliberate, not a fudge
factor, and must survive any future edit) and the whole seam delegates to
`energy.mark_math`, which clamps to an EXPLICIT ceiling — `AUTO_CEILING`
(0.75) with no manual mark, 1.0 with one — rather than the old plain
`[0,1]` clamp on the raw product.

**The 0.75 auto ceiling + the manual mark (his ruling, same day, BUILT;
0.75 itself unchanged by the 0.8 move)**: 0.75 STANDS as the automatic
ceiling — `auto_scaling_factor()` (the renamed, unchanged AUTO-only
resolution) never exceeds `SCALE_MAX=1.25`, and `energy.mark_math` caps
an unmarked song at `AUTO_CEILING=0.75` outright (no longer the emergent
`0.6*1.25` arithmetic the original 0.6 constant produced).
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

