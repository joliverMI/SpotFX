# SpotFX — agent notes

## Timing and offset-direction conventions — READ BEFORE TOUCHING ANY TIMING CODE

`docs/SPECTRA_TIMING_CONVENTIONS.md` is the canonical, file:line-cited record
of every timing/offset/lead/delay quantity in this codebase — its unit, its
sign convention in plain words, which engine owns it, and whether it's live
in SPECTRA or dark/inherited from the predecessor. **Two families of timing
quantity use OPPOSITE sign conventions for "earlier"** (a `lead_ms` family,
positive=earlier; an `offset_ms` family, negative=earlier) and both are live
simultaneously in `spectra/services/trigger_engine.py`'s `tick()` — mixing
them up is silent and has cost real time more than once. Five real failures
this week (arguing an audio delay in the wrong direction; treating a
wandering `shape_offset_ms` reading as a measurement; reading the
**predecessor's** composite timing offset while SPECTRA's own, narrower one
actually governed the room; diagnosing a trigger-store divergence by
inference instead of reading both stores; asserting a flare offset was
consulted by the firing path without checking) all trace to knowledge that
was already written down in this repo and not read. Check that document
before writing, measuring, or reasoning about anything time-related — it is
also where new timing quantities get recorded, not here.

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

**A topic isn't done when it's written — it's done when something in the UI
links to it.** Found 2026-08-21 (`fm/help-context-sensitive-question-mark`):
65 of SPECTRA's 117 help topics had real, written content and were never
`topic=`'d from any component — reachable only by guessing a search term.
Audit method (cheap, run it after any content pass): extract every `id:
'...'` from `helpContent.ts`, then for each id grep the app's `.tsx`/`.ts`
files (excluding `helpContent.ts` itself) for that id as a quoted string —
zero hits means orphaned. Also watch for a topic nested under the wrong parent
section/subsection in the content tree (one was found filed as a
subsection of the Timeline builder page while describing SPECTRA process
restarts entirely unrelated to it) — that kind of misfiling makes a topic
functionally unreachable from any sane UI location even before anyone
tries to link it.

SPECTRA's global "?" (`spectra/web/src/App.tsx`'s NavBar) is
context-sensitive: `spectra/web/src/help/routeTopics.ts` maps the current
route to the page's own help topic, so it opens Help already scrolled to
the current page instead of always landing on the bare index. Add a route
there when adding a new top-level SPECTRA route; a route with no entry
falls back to the plain index rather than guessing. It's route-level only,
not tab-level (a page's internal tabs are local component state, not part
of the URL).

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
~11k-trigger corpus) — fine for one human edit, not fine looped inside an
async request handler for a multi-song batch (blocks the SPECTRA process's
event loop, stalling bridge polls/ticks/WS broadcasts for the run's whole
duration). Run bulk generation as a separate offline process against
`storage/spectra/triggers.json` directly, the same shape
`migrate_legacy_triggers.py` already used for the authored corpus, never
through the live HTTP endpoint in a loop.

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
_next_trigger_gap_ms`) resolves the SAME per-song effective mode this
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
(`_phase_post()` in the 1d strip) immediately after `_phase_step()`
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
star-fold-entry-growth; deploy migration for STAR's strips was
`scripts/seed_star_strips.py --apply`, NEVER the v2 seeder — but that one is
SUPERSEDED as of 2026-08-25 and must not be re-run: his ruling "always do
melt" removed STAR's Strips power step via
`scripts/star_strips_always_melt.py`, and the seeder would silently put it
back. The mechanism itself is unchanged and still used elsewhere).
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
spot-effects storage READ-ONLY). **A worktree's own `storage/spectra/*.json`
is gitignored and untracked — it is whatever was copied in when the
worktree was created, not proof of current live scene/room state** (found
2026-08-17: a stale Aug-13 copy of `scenes.json` in a task worktree made an
already-shipped fix look regressed). The worktree isolates the filesystem,
not the network — read `GET /spectra/api/scenes`/`.../engine/status` on the
live `:8010` process for ground truth, or copy fresh read-only from the
live app dir's `storage/spectra/` (never `storage/scenes_v2.json` — that
one is the S1 seeder's own built-in-fixture offline path, not a live
snapshot to copy in) before trusting a local snapshot for anything dated.
Executable spec:
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
`docs/SPECTRA_RESPONSES.md`. A dice re-roll (`_reroll`, the "Dice
Re-roll" kind) lands via `executor.glide(..., DICE_REROLL_GLIDE_MS=220)`
when the re-rolled param is registry `"smooth": true` (a genuine
continuous numeric — STAR's `star`), else `executor.jump()` as before
(toggle/string/integer, e.g. STAR's `edges` — can't be meaningfully
interpolated); an explicit param-patch kind (a permanent/momentary
`FlareKind`'s own `params`, executed via `_move_params`/
`_compute_param_moves`) on the same event still wins over a same-event
dice re-roll, and — since a 2026-08-17 follow-up fix — glides too when
its target is registry-smooth, not an unconditional jump; the two paths
share one smooth-gate now, so precedence (patch wins) falls out of plain
dict-update ordering rather than an explicit jump/glide split. Fixed
2026-08-17: his STAR scene re-rolls `star` on every ordinary flare (its
flare bands carry Dice Re-roll end to end), measured live at ~0.6–1.2s
apart, each landing as an instant jump — read as a strobe, not a defect
in `star`'s own binding. `config/effect_params.json`'s per-param
`"smooth"` flag existed before this and was previously dead metadata
(grep-confirmed unread anywhere in `spectra/`/`fx/` Python) — it is now
load-bearing for BOTH gates (`_reroll`'s dice glide and `_move_params`'s
patch glide, added in the follow-up below); check it before assuming a
param's smoothness is unhandled elsewhere. **Follow-up, same STAR scene,
2026-08-17**: he reported it "still snaps" after the fix above — real,
because `_move_params` never checked `smooth` at all, so STAR's own
"Flare/Drop patch 0.7–1" kinds (permanent, pin `star` to `0.0` on every
high-intensity flare) kept jumping regardless of the tag; `check_spectra.py`'s
own prior assertion had documented this exact gap as "unchanged by the
smoothing fix" rather than missing it. Fixed by extending the same
smooth-gate into `_move_params`. Radial's `spin` (direction+speed,
signed, `[-1,1]` in the real vendored `CONFIG_SCHEMA` though the registry
still declares `[0,1]`) was separately retagged `smooth: true` in the
same pass — verified from source (`fx/utils.py::nonlinear_log` is
continuous through a sign change), not from his ask alone, and provably
inert against `_reroll` since no live scene binds `spin` via
`signal="random"`. **`spin_sign` ("Flip", `maps_to: spin`,
`sign_control: true`) — INERT under SPECTRA until 2026-08-20, PORTED
since**: originally that translation existed only in legacy
`services/morph_compiler.py::_sign_control_patch`, never ported to
`spectra/`/`fx/`, and `fx/effects/radial.py`'s real schema has no
`spin_sign` key at all — a raw write targeting it would land as an inert,
unread key (voluptuous `extra=ALLOW_EXTRA`). Two new named kinds on STAR
built that same pass, declared but not band-attached (matching Fireworks
V2's own "Reverse Direction" precedent — a human attaches via the Scenes
page's band-strip chip, not an agent): "Reverse Direction" (permanent)
and "Reverse Momentarily (500ms)" (momentary, `hold_ms: 500`) both then
targeted `spin` directly with a signed absolute value (`-0.55`, negating
his own already-authored spin-patch magnitude) — which worked, but
GLIDED (spin is registry smooth=true) from +0.55 to -0.55, visibly
crossing a real zero-speed moment: his report, precisely, "star is
freezing on every flare... but then it continues smoothly."

**PR fm/star-reverse-flare-use-flip (2026-08-20), his ask: "use the flip
control for star"** — told the trade and taking it knowingly (no pause,
but the turn is instant and more jarring) — is what actually ports
`spin_sign`, rather than routing around its inertness: both kinds now
target `spin_sign` (value 0/1), and `scene_response._compute_param_moves`
gained a `sign_control` branch that redirects the write onto the REAL
param (`meta["maps_to"]`, i.e. `spin`) with only its sign flipped,
MAGNITUDE PRESERVED from `spin`'s own current carried value (never a
fixed `-0.55` — proven against a 0.2 baseline too, not just this scene's
coincidental 0.55) — and, critically, forces that write through
`executor.jump()`, never `.glide()`, on BOTH the departure and the
momentary kind's release (`_pending_releases` grew a 4th `instant: bool`
field; `flush_releases` now splits jump/glide by it, same shape
`_move_params` already used for the departure split). A sign flip can
never be allowed to glide regardless of the real param's own `smooth`
tag — that's the whole point: no continuous crossing, either direction.
**The collision question this required answering before shipping**: a
sign-control write and a plain absolute `spin` write (e.g. STAR's own
untouched "Flare/Drop patch" kinds) land in the exact SAME `(vid,
"spin")` carry slot — there is no second, independently-tracked "flip
bit" anywhere that could disagree with `spin`'s own value and strand
STAR reversed; the two compose by ordinary last-write-wins carry
semantics, the same as any other two permanent kinds sharing a target
param (`scripts/check_spectra.py`'s own collision section proves this
directly). `config/effect_params.json`'s notes on both `spin`/`spin_sign`
are updated in the same PR — check those, not this paragraph, for the
current mechanism detail. Migration:
`scripts/switch_star_reverse_flares_to_flip.py` (raw-dict patch — NOT
`scene_console.apply_flare_kind`'s model round-trip, since this is a
single-field edit on two ALREADY-EXISTING kinds, and a round-trip write
of that shape silently added unwanted flare kinds to Squiggles the same
night this PR was built; dry-run default, `--apply`, `--revert` for the
exact one-field-back inverse). Original migration (creating the two
kinds in the first place, still accurate for that history):
`scripts/add_star_reverse_flares.py` (dry-run default, `--apply`,
idempotent, goes through `scene_console.apply_flare_kind` — Sonic's own
write path, backed up automatically — not a raw-JSON patch, since adding
a FlareKind is exactly what that function is for). Full writeup:
`docs/SPECTRA_SPEC.md` §78. **"The Scenes page's band-strip chip" above is
now the LANE RACK** (`spectra/web/src/components/FlareLaneRack.tsx`, §81,
PR fm/spectra-flare-lanes-and-edit): a band attaches kinds by drag, not a
click-toggle chip row. **Since 2026-08-21 (§88, PR fm/flare-lanes-pick-one
— his own reversal of the §81-addendum decision that declined this) a lane
is a stored PICK-ONE POOL, not just a position**: `FlareBand.kind_lanes`
(kind name → lane name; empty default) pools attached kinds, and
`scene_response.resolve_lane_picks` rolls ONE member per pool per fire
(even weights — curve weighting deliberately deferred, his words), every
lane's pick firing together, the legacy MorphLane shape. A kind with no
entry is its own one-member lane, so every pre-§88 band fires all of its
kinds unchanged — the empty default is the whole safety of that change;
zero scene files were rewritten. Execution order stays `FlareBand.kinds`'
own insertion order regardless of pooling — the engine reads it as a
tie-break when two same-type kinds (e.g. two permanent param moves) target
the same param: the later one in that order wins (`scene_response.py`'s
fixed dice→permanent→momentary→gain→colour execution order, generalized —
see that module's own docstring before assuming "combine" means additive;
dice re-rolls and colour jumps are each a SINGLETON pick per fire
regardless of how many actually fire, only param moves/gains compose). The
lead/offset forward peeks (`band_trigger_offset_ms` etc.) aggregate over
ALL pool members — the possibility-set bound, documented in each
docstring, since the fire-time pick can't be known early. Rename/
delete/copy got a direct edit box (`FlareKindEditDialog.tsx`, tap or
double-click) — deliberately narrower than the no-settings-forms rule
above, since those three are identity ops on the kind's NAME, not its
type/params/gain/hold (still agent-only). A flare kind is scoped to ONE
scene's `flare_kinds` list — no cross-scene id — so paste
(`lib/flareClipboard.ts`) is a genuine PORT (a fresh, deduped-by-name
entry, never attached to a band), not a live link back to the original.
Full writeup, including the intensity-bucket-management proposal (options,
not built): `docs/SPECTRA_SPEC.md` §81, OQ-13.), read-only bridge
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

**A momentary/permanent kind targeting a TOGGLE-type param (e.g. `reverse`
on blackhole/orbits/squiggles) needs a real Python `bool` to reach the
effect, not the float `ParamTarget.value` naturally produces — fixed
2026-08-20, PR fm/momentary-reverse-flare-on-black-hole-orbits-squiggles.**
`ParamTarget.value` is a plain float field (`spectra/models/scene.py`), so
an authored `true`/`false` silently coerces to `1.0`/`0.0`; the real
effect's `CONFIG_SCHEMA` validates a toggle param against bare `bool`
(voluptuous, no coercion — `fx/effects/__init__.py::_apply_config`,
`validate=True` LOGS a warning and drops the whole write on mismatch,
never raises), so before this fix a toggle-targeting kind looked declared
and attached but silently did nothing on fire. `scene_response.
_compute_param_moves` now coerces a `KIND_TOGGLE` param's resolved target
to a real bool (verbatim at scale 1, else a 0.5-threshold blend against
the bool baseline). The release side needed its own fix: `drift_conductor.
VirtualState.param_baseline` and `scene_response._carried_value` used to
explicitly EXCLUDE bool values ("NUMERIC baselines" by design) — a
toggle's pre-flare state was never tracked, so a momentary release could
never resolve where to return to and silently skipped. Both now carry a
toggle baseline as a real bool alongside the numeric ones. `reverse` means
something different per effect — chain retrace (squiggles), spin
direction (orbits), infall vs. outward (blackhole, the most dramatic, and
worth a beat's thought against the charge/lull/drop implosion choreography
already on that scene — flagged, not resolved, in the migration script's
own docstring) — see `scripts/add_momentary_reverse_flares.py` for the
full trace and for why a fixed absolute target (not a true invert) is the
only expressible form given ParamTarget's float-only `value`/`offset`
fields. Proof on the real vendored pipeline: `tests/test_spectra_engine.py::
test_momentary_toggle_param_flare_lands_a_real_bool_and_releases`.

**A fourth `FlareKind` type, `color_rotate` — the COLOUR ROTATE-AND-BACK
flare (owner ask, 2026-08-20, PR fm/rotate-and-back-colour-flare)**: rotates
a set-mode virtual's live foreground colour (`VirtualState.gradient`, via
the same `spectra/services/color_rotate.rotate_color_value` the room's own
colour-journey rotation already uses) by an intensity-scaled amount, ramps
in to land the full rotation ON the trigger mark, dwells, then fades back
to the exact original — his four numbers, exact:
`scene_response.color_rotate_{degrees,ramp_ms,dwell_ms,fade_ms}` (60°→180°,
1000ms→250ms ramp, 1000ms→400ms dwell, fade = 1.5× the ramp). Unlike every
other kind, it carries NO authored params/gain/hold_ms — all four
quantities are computed from the fire's own intensity, never a fifth knob
(`FlareKind._shape` rejects any). It's a genuinely new mechanism, not a
`_move_params` reuse: `gradient` is a scene colour assignment, never a
`device_model` registry param, so it can't flow through the param/gain
machinery every other momentary/permanent kind shares — this is *why* it
composes for free alongside a shape-targeting kind in the same band (his
"concur with some shape flares" requirement): it never touches the
`jumps`/`glides` dicts those kinds build. Its own release queue
(`ResponseEngine._pending_color_rotates` / `pending_color_rotate_holds` /
`flush_color_rotates`) is separate from `_pending_releases`/
`flush_releases` because its fade-back duration is itself intensity-scaled,
where every other momentary release shares one fixed `PULSE_RELEASE_S` —
wired into `engine.py`'s `fire_response_event` the same way, as a second,
parallel scheduling loop. ANCHORING (the flare rule — ramp ends on the
mark, not the drop rule): `trigger_engine._response_switch_lead_ms` now
takes `max()` of the existing dice-glide lead
(`momentary_switch_would_glide`, unchanged) and the new
`scene_response.color_rotate_lead_ms` — a separate function because this
kind's ramp has a real, intensity-scaled duration, so it can't share
`momentary_switch_would_glide`'s single fixed `DICE_REROLL_GLIDE_MS`
boolean-then-constant shape. `flare_preview.build_timeline` drains the new
release queue too, so the scrubbing preview shows a `color_rotate` kind's
full ramp/dwell/fade shape like any other. **A new ResponseEngine release
queue must be scheduled at every drain point, not just `engine.py`** —
there are four (`engine.fire_response_event`, `engine.
fire_scene_update_event`, `flare_preview.build_timeline`, and
`flare_preview_hold.open_hold`, the live preview's per-lap fire): this
queue was missed at `open_hold` when it shipped, so a live-previewed
rotation never faded back — the gradient sat parked rotated between laps
and every crossing after the first showed nothing (his 2026-08-21 report,
fixed PR fm/rotate-preview-stops-on-intensity-change; the intensity
slider was the moment he noticed, not the cause — the client's fire
schedule was proven sound, `scripts/check_flare_preview_frontend_loop.mjs`
§FIVE/SIX). Declared on every scene (not
effect-scoped like `reverse` — `gradient` exists on every set-mode virtual
regardless of effect type — `scripts/add_color_rotate_flares.py`, dry-run
default, never attaches to a band, his data is his to attach). Executable
spec + real-async-timing dwell measurement + the anchoring arithmetic
identity (`fire_at + ramp_ms == trigger mark`) + the colour/shape
concurrency proof: `scripts/check_color_rotate.py`. Fast deterministic
pytest coverage of the same mechanism (ramp/dwell/fade sequence on the
real vendored blackhole effect, the two release queues' independence, the
concurrency proof, the model's rejected-fifth-knob cases):
`tests/test_color_rotate.py`.

**A fifth `FlareKind` type, `firework_burst` (owner ask, 2026-08-21, PR
fm/fireworks-burst-flare)**: explodes an intensity-scaled count of payoff
rockets (3 at intensity 0 → 6 at 1, `scene_response.
firework_burst_rockets`) IMMEDIATELY on every live fireworks effect —
`docs/SPECTRA_SPEC.md` §89 has the full writeup. Two things worth knowing
before touching it: (1) it is deliberately NOT `beat_burst` — that param
only launches on the NEXT beat, so it can't line up with a trigger; the
engine instead jumps the effects' own `burst_rockets` key (edge-detected,
self-resetting, the phase-key pattern — `fx/VENDOR.md` deviation #15;
gated by `fx.device_model.FIREWORK_BURST_EFFECTS`, and like the phase
keys deliberately absent from the param registry). (2) unlike
`color_rotate` it has NO release queue — nothing to schedule at the four
drain points; the particles age out inside the effect. Migration
(declares AND band-attaches on Fireworks V2, his explicit placement,
run only AFTER the code deploys): `scripts/add_fireworks_burst_flare.py`.
Specs: `scripts/check_firework_burst.py`, `tests/test_firework_burst.py`.

**Fireworks "drop tail" (2026-08-21, PR fm/fireworks-drop-tail, `fx/VENDOR.md`
#17) — two facts worth knowing before touching fireworks spawn pacing:
(1) his real Fireworks V2 entries (both effects) run `spawn_rate: 0` —
beat bursts are their ONLY ordinary launch source, so any `_pspawn`-style
spawn_rate multiplier (incl. the charge's `CHARGE_SPAWN_X`) is inert on
his scene; anything that must visibly add launches there has to be a
launch RATE or touch beat bursts. (2) particles spawned past the density
cap (payoff, burst flare, tail, rockets) are flagged `p_nocap`/`f_nocap`
and don't occupy `max_blobs` — before that flag, a payoff held the cap
full for `PAYOFF_LIFE × burst_life` (~2.6 s on his crystal) and silenced
every beat burst, which was the "big burst then nothing" cliff. Measure
with `scripts/check_fireworks_drop_tail.py` (has a his-real-config
variant) before reasoning about post-drop density.

**The reverse flare's ~2x dwell overrun (967-1905ms measured live against
an authored 500ms, median 1160) — ROOT CAUSE FOUND AND FIXED 2026-08-21
(PR fm/reverse-flare-glide-and-stuck), after nine eliminations: the
release timer started at the END of the fire's own serial write burst,
not at the spike.** `engine.fire_response_event` used to create its
`asyncio.sleep(hold_s)` release tasks only AFTER `await
responses.on_event(...)` returned — and `on_event` lands every write of a
fire serially through the facade (~30ms each on his live room: seq
spacing in `executor.recent_writes`). A Black Hole V2 flare is 13 writes
(spike jumps ×5, gain jumps ×5, colour-jump glides ×5 — his live log,
seq 163-175, ~400ms), so "sleep 500ms" began ~0.4-0.5s late and the
reverse release landed 1.02s after its spike (seq 164 → seq 181, read
straight off `GET /spectra/api/engine/status`). The earlier offline
reproductions (509-638ms, one headless virtual, near-zero write cost)
were CORRECT measurements of a burst that barely existed there — the
overrun scales with the fire's write burst, which is why it only ever
showed on his live room. It was never the tween (both tween engines,
vendored `fx/` and the external fork, classify a bool target as instant —
a toggle never glided on the light), never `record_fire`, never the lead
system (toggle-only kinds compute lead=0 — still true). Fix:
`scene_response.PendingRelease` entries are ARMED (`armed_at`/`due_at`
stamped) right after each virtual's spike write lands, and
`engine._release_group` sleeps until that ABSOLUTE due time
(`responses.take_release_schedule()` / `seconds_until()`), so the hold is
measured from the spike regardless of how long the rest of the fire
takes. Measured on the real pipeline: `tests/test_reverse_flare_release.py`
(real effect: 536ms for a 500ms hold at 30ms/write; five virtuals, old
shape 806ms vs new 532-563ms; two flares 250ms apart: 773ms, i.e. the
LATER hold's full length). **Three more things that shipped with it, all
in `scene_response.py`'s "RELEASE OWNERSHIP" docstring — read that before
touching `_pending_releases`/`flush_releases`:** (1) every release is
OWNED by the fire that created it (`fire_seq`) — the old by-hold_s drain
let the FIRST of two 500ms flares release the SECOND one mid-hold — and a
later spike on the same (virtual, param) SUPERSEDES the earlier release
(holds extend, never cut short); (2) a TOGGLE param's release is forced
instant (`executor.jump`, never a PULSE_RELEASE_S glide), the rule
sign-control already had — the light never glided a bool anyway, but the
executor log and the scrubbing preview's ruler used to describe a 1.5s
glide-back that never happened (`scripts/check_flare_preview.py`'s
polygon case was updated from "no release" to "jump back at hold"); (3) a
momentary spike on a param the scene entry NEVER AUTHORED used to land and
never release — `flush_releases` skipped a `None` target — stranded until
an effect-TYPE switch rebuilt the instance: **his Orbits V2 and Squiggles
V2 both have this shape on their Strips (`orbits1d` registers `reverse`,
neither entry sets it), a genuine "stuck in Reverse" on the strips from
the FIRST flare, regardless of spacing.** Every entry now carries a
`return_to` resolved at spike time (`_resting_value`: the carried
baseline, else `fx.device_model.resting_default` — the effect's own schema
default, registry default as fallback — coerced to the registry kind),
used only when nothing carries a baseline at flush. PR #186's param
orphan watchdog (`release_target`/`pending_release_keys`, kept and adapted
to the new entry shape in the same commit) deliberately keeps no opinion
on never-authored params, so that fix is prevention-only; the two share
ONE definition of baseline (`_carried_value`). **And the "stuck in
Reverse" he most likely SEES is STAR's own data shape, reported, not
changed**: read live off `:8010`, STAR attaches the PERMANENT "Reverse
Direction" kind to its 0.35-0.7 and 0.7-1.0 flare bands and the momentary
one to 0-0.35 — a permanent kind's carry moves `param_baseline`
(`conductor.on_surge`), so after ONE mid/high flare reversed IS the
baseline and every later momentary reverse lands -|spin| and releases
back to -|spin|: stuck by construction, not by a race; the watchdog
rightly sees nothing to restore (`test_star_permanent_reverse_makes_every_
later_momentary_reverse_stick`, on the real radial effect). Fireworks V2's
"Reverse Direction" is, despite its name, MOMENTARY (hold 500) — fine.
Whether STAR's permanent attachment is intended is his call; the scene
backups (`/home/javi/SpotFX/storage/spectra/scene_backups.json`) show the
two kinds declared-but-unattached by script, so the band attachments were
a later UI save. **A ninth
elimination, 2026-08-21 (PR fm/engine-reads-flare-trigger-offset, checked
at firstmate's direction when that PR found a REAL double-fire in
`tick()`'s safety-net OR clause)**: that double-fire DOES hit
`fire_response` triggers in general (pre-fix, empirically: lead=220 → two
fires 200ms apart; lead=450 → 400ms apart — spacing = the lead, rounded
up to tick cadence), but it structurally requires lead > one 200ms tick,
and every one of the 9 real bands attaching "Reverse Momentarily (500ms)"
(Black Hole V2 / Orbits V2 / Squiggles V2 × 3 flare bands each, read from
the live process) computes lead = 0 — toggle-only, no registry-smooth
momentary param, no attached color_rotate — so `fire_at == target`, the
two OR clauses collapse to one predicate on one tick, and the pre-fix
engine fires exactly ONCE on that path (proven by running the pre-fix
module, not argued). UNRELATED to the overrun (now explained above).

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

**`PUT /api/room-controls` IS A TRUE PARTIAL UPDATE — only the keys a
caller SENT are overlaid onto the current stored state; everything else is
byte-preserved (2026-08-30, PR fm/room-controls-partial-merge).** Before
that it bound the body to the full `RoomControlState`, so a partial body
silently reset every unnamed field to its model default and saved it — his
`av_sync_lead_ms` calibration and `force_scene_scene_id` pin were both
confirmed wiped in his real file that way. The merge, not a per-key patch,
is the fix: the reverse-proxy hop makes the caller list structurally
unknowable, so only a merge protects callers nobody has enumerated. The
contract and the retired-`ambient_mode` compatibility alias (PUT path only,
never stored; `"auto"` maps to `ambient_on_music_pause=True`, unlike the
one-time disk migration — and a body carrying both dialects lets the NEW key
win) live in `room_controls.merge_room_controls`/`AMBIENT_MODE_ALIAS`.
Reconcilers still receive `(previous, merged)`. Spec:
`tests/test_room_controls_partial_put.py`.

- **Override Blend** — `SceneV2.entry_ramp_ms` (a scene-fire blend-in ramp,
  threaded through `fx_seam.apply_writes(transition_ms=...)`, hue-arc, same
  tween shape as `fx_executor`'s glides) covers the thinner scene-entry
  facet. A read-only live-storage study found real legacy usage is 265/269
  triggers Charge/Lull phase builds, not scene selection — that dominant
  facet is `scene_response._phase_ramp_ms`'s dynamic gap-to-next-trigger
  stretch (below), not `entry_ramp_ms`.

  **The dominant Charge/Lull facet dynamically stretches to the real gap
  now (2026-08-20, `fm/spectra-lull-ramp-does-not-scale`, Admiral order
  "fix the lull ramp")** — a PORTING GAP fixed, not a design reversal:
  legacy's own dynamic ramp-to-next-trigger stretch had no analogue when
  this was first built (S2 had no forward trigger schedule to compute a
  gap against), so `models/scene.py` `PhaseBlend` shipped only the
  buildable static half — a per-scene `charge_ramp_ms`/`lull_ramp_ms`
  number, unset on every one of his real scenes. `trigger_store` now
  supplies exactly that schedule, so `PhaseBlend` is **retired** (removed
  from `SceneV2`, Sonic's `SCENE_SETTINGS_REGISTRY`, and the Scenes UI) and
  `scene_response._phase_ramp_ms` computes the real stretch instead — no
  per-scene knob was rebuilt alongside it: his own two real lull gaps on
  one song (Dopamine, `data/charge-lull-drop-timing-blends-and-a-sus-
  7fm2/report.md`: 6040ms and 900ms) prove a single constant can't fit
  both, so a hand-tuned number would just hand the problem back to him.
  His spec, verbatim: "the single blob waiting in lull should reach the
  center just and hang for just a moment, maybe 10% of the lull time,
  before the explosion" — charge/lull ramp to ~90% of the real gap
  (`TriggerEngine._next_trigger_gap_ms`, honoring the same
  `scene_change_mode` gate `tick()` itself applies), hanging the remaining
  ~10% at `phase_progress=1.0` for free (nothing writes it again before
  the next phase event); drop is never stretched. An UNKNOWABLE gap (no
  trigger-schedule context — a bridge-classified legacy flare, or a
  manual `/api/engine/event` test-fire) is a documented fallback to the
  flat tuned default, never a silent guess. Spec:
  `scripts/check_triggers.py` (gap computation, incl. a disabled/mode-
  gated trigger never counting as "next") + `scripts/check_spectra.py` +
  `tests/test_spectra_engine.py` (frame-level, his real Dopamine pair).
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

**The redirect above is passive — it only fires when something else was
already about to pick a scene, and enabling Force Scene also sets
`bridge.sequencer_deferral()` to defer the sequencer's own rolls; on a
song with no triggers/analysis, nothing was ever going to fire, so the
pin sat there doing nothing and looked broken (his live report,
2026-08-18).** `room_controls.reconcile_force_scene_if_changed`
(same one-choke-point PUT-triggered shape as `reconcile_ambient_if_changed`/
`reconcile_dark_light_if_changed`, called from `PUT /api/room-controls`)
fires the pin immediately on the edit that enables it or repins a
different scene while already enabled — never on an unrelated field
re-save with the pin unchanged. Always returns a stated
fired/skipped/error reason (`force_scene_result` in the PUT response,
`ForceSceneResult` in `types.ts`, surfaced as a badge in
`RoomControlsBar.tsx`) — never a silent no-op.

**Force Colour** — Force Scene's twin ONE AXIS OVER (2026-08-27, his ask:
"Add an ability to force a color set or color group, similar to force
scene, so the color does not change and stays on a specific set. Put the
tool in the top bar and focus on fucntion and we will work on UI later").
Force Scene pins WHICH SCENE plays; this pins WHICH COLOURS it wears.
`RoomControlState.force_color_enabled`/`force_color_target_id` (a colour
SET **or** GROUP card id), default off/None so its arrival changed
nothing. **`spectra/services/force_color.py`'s module docstring is the
binding statement** — every gate, both precedence rulings, and the
side-effect rule below live there; read it before touching any colour
selection path. The short list:

- **Gated at SEVEN choke points, each checked individually** (§86's
  lesson, again): `scene_sequencer.fire_scene_by_id` (replaces the
  caller's own colour set, result carries `forced_color`), its
  `_roll_color_set` (short-circuits with its own `FORCED_COLOR` rung so
  the roll never re-anchors the wheel for a pick that is about to be
  overridden), `scene_compiler.room_active_set` (the TERMINAL fallback —
  the path 100% of his real `fire_scene` triggers take), `drift_conductor.
  tick`'s journey hold + `_bootstrap_room_color` + `on_drop_event`,
  `scene_response._color_jump`, and `trigger_engine.
  _default_select_color_set` (names the redirect via
  `apply_set_directly(forced_from=...)`).
- **`active()`/`pinned_id()` are side-effect-free; `pinned_card()` is
  NOT.** Resolving a pinned GROUP advances that group's rotation cursor
  (`color_set_groups._pick_member`), so `pinned_card()` is called exactly
  ONCE per real fire, at the choke point about to use it — never from a
  per-leg hold check or a status poll, which would roll his colours on
  nothing but someone looking at the page. Proven directly in
  `tests/test_force_color.py`.
- **SET pin = static; GROUP pin = the POOL, rotation still live** (that is
  what a Group is). Stated as a reading, his to tune.
- **Precedence, named**: it WINS over an active 2D gradient (which also
  replaces the journey) — the gradient is untouched and resumes on
  release; it composes for free with Ambient (device-level, downstream —
  verified, not assumed, the same orthogonality Dark/Light already has).
  `preview_pause` still outranks everything, unchanged.
- His EXPLICIT actions still work and NAME the override
  (`overrode_force_color` on `POST /room-color/apply` and the editor
  Preview); a disabled pin APPLIES and is named (`overrode_disabled`),
  never silently refused. Sonic excluded from the registry on
  `force_scene_*`'s own opaque-id precedent.

Immediate apply on enable/repin: `room_controls.
reconcile_force_color_if_changed`, `force_color_result` in the PUT
response — the passive-redirect trap immediately above is documented, so
it is not repeated. Help topic `force-color`, linked from the top bar's
own "Colour" group button. Spec: `tests/test_force_color.py`.

**Temporary scene disable** (2026-08-18, his ask: "add an ability to
disable a scene temporarily") — `SceneV2.disabled: bool` (default False),
a manual reversible toggle, no timer/expiry. STRONGER than mode
availability above (checked first, wins the reported reason when both
apply) — gated at the same three choke points: `scene_sequencer.
fire_scene_by_id` (the hard gate; `skipped="disabled"`), `SceneSequencer.
_roll`'s candidate pool (new `_scene_enabled`/`_default_scene_enabled`,
kept separate from `_scene_mode_available` rather than folded in),
and `trigger_engine._default_select_scene`'s generated-trigger draw. A
manual Fire/test-fire bypasses it, same as it already bypasses mode
availability. Force Scene still fires a disabled pinned scene (an
explicit press always wins) but NAMES the contradiction rather than
applying it silently: `fire_scene_by_id` returns `overrode_disabled=True`,
threaded through `reconcile_force_scene_if_changed` into
`force_scene_result.overrode_disabled`, surfaced as a second badge ("⚠
overriding disabled scene") on `RoomControlsBar.tsx`. Visible everywhere a
scene's status is shown, not just a detail panel: a red "⛔ disabled"
badge on the scene-list row and the phone header's compact selector
(`ScenesPage.tsx`), a `DisabledToggle.tsx` toolbar control next to Mode
availability, and the disabled marker on Force Scene's own scene picker.

Fixed 2026-08-19 (his report: "the enable/disable button gets taller and it
makes the entire row look bad"): `DisabledToggle.tsx` shipped with a fixed
pixel WIDTH but no `white-space: nowrap`, so the bold "⛔ Disabled" label
wrapped onto a second line at that width, growing the button (and the
toolbar row it sits in) 17px taller only while disabled.
`ModeAvailabilityToggle.tsx` — same row, one control over — was built with
the identical hard requirement ("must not change size as it cycles") and
had the identical gap, just never triggered because its own labels
("Hybrid"/"Light"/"Dark") happen to be short enough not to wrap. Both now
build their `style` via the shared `fixedSizeToggleStyle.ts` (fixed width +
`white-space: nowrap`), so this is closed for both, not patched once per
control. Measured via a real render of both toggles at 390×844 (isolated
instance, no live storage touched): fixed, an enabled-at-load scene and a
disabled-at-load scene render pixel-identical toolbar rows (88×31 toggle,
321×154 row); pre-fix, the disabled-at-load scene's toggle/row measured
88×48 / 321×171.
Deliberately did NOT extend the same naming treatment to Force Scene's
pre-existing SILENT bypass of mode availability (§9/§31 above) — a
different, already-shipped behaviour this task wasn't asked to touch.

**AMBIENT IS ONE BINARY TOGGLE (2026-08-30, PR fm/ambient-binary-clarity;
`docs/SPECTRA_SPEC.md` §96) — read `spectra/services/ambient_music_gate.py`'s
module docstring before touching anything here, it is the binding
statement.** His ruling: "let's only ever toggle between Off and On."
`RoomControlState.ambient_mode` (`"off"|"always"|"auto"`) is RETIRED for
`ambient_enabled: bool` + `ambient_on_music_pause: bool`. Migration on load:
`"always"` → enabled True, `"off"`/`"auto"` → enabled False, and
`ambient_on_music_pause` **False in every case** (his explicit "set it to
false for now"), every other key byte-preserved. The "auto" BEHAVIOUR is
preserved verbatim in `_desired_hold` and gated behind the new switch —
disabled, not removed. Four things ride with it, and all four have bitten
before:

- **THE PHASE CONTRACT IS FROZEN** — another captain builds Home Assistant
  against it. The `ambient` key on `GET /api/engine/status` and on the
  SPECTRA websocket (`{"type": "ambient_status", ...}`) carries
  `intent: "on"|"off"` and `phase: "on"|"off"|"turning_on"|"turning_off"|
  "unavailable"`. Do not rename or extend those value sets without going
  back to him. `phase` updates within 1s because the gate PUSHES at every
  transition start/end/cancel; the 3s poll is the backstop, not the
  mechanism (`spectra/web/src/api/spectraWs.ts` folds the push into the
  SAME react-query cache entry the poll writes — never a second source of
  truth). `phase` reports the TRANSITION's outcome, not the bulbs': a hold
  broken out of band still reads `on`, and the pre-existing `held`/`mode`/
  `verify`/`verified_age_s` keys keep carrying that honesty.
- **INTERRUPTION SNAPS, and the boundary matters.** Measured live before
  the rework: turn-OFF 22.6s, turn-ON ~15s across his 17 bulbs, and a press
  MID-transition took **38s** to win because it queued behind
  `services.ambient`'s own I/O lock. Now at most ONE generation-stamped
  transition task exists; a new intent cancels the in-flight one at its next
  safe write boundary (never mid-write to one bulb — `ambient.CancelToken`
  owns where those are, and its interruptible `sleep` is what lets a RAMP be
  abandoned instead of waited out) and applies the new end state with every
  ramp DROPPED (`snap=True`). **The 300ms write stagger STAYS — that is
  zigbee physics; the ramps are choreography.** A superseded run never
  writes again and never touches the landed-state bookkeeping (guarded on
  `_transition is tr`), or a slow cancelled turn-off would flip `_held` back
  while the room is genuinely lit. An UNINTERRUPTED turn-off keeps its full
  two-phase ease — his complaint was the interruption, not the fade.
- **The press does not block.** `reconcile_ambient_if_changed` STARTS the
  transition and returns `{"status": "turning_on"/"turning_off", intent,
  phase}`; the PUT blocking for the whole sequence is where "I don't know if
  it has started" began. Every automatic caller still uses `wait=True`.
- **A press while the room is not ours is never a silent nothing**: it
  starts no transition and records NOTHING as landed (recording it is what
  would make the take-back short-circuit and swallow his intent), returns
  `{"status": "dark", "phase": "unavailable", "stored": true}`, and applies
  on the next take-back — app.py's startup/resume, and now
  `handover.run_handover`'s own commit when SPECTRA becomes owner.

Spec: `tests/test_ambient_transition.py` (a timestamping mock bridge at his
real bulb count, pacing scaled 1/20th so a sequence still has real duration
to interrupt — the 38s shape is reproduced RED against the pre-rework call
shape before the new owner is proven green) +
`tests/test_room_controls.py::test_ambient_mode_migrates_to_the_binary_toggle`.

Everything below this paragraph is the history of the retired three-setting
gate, kept because its reasoning still governs the music-pause branch and
because the composition facts it establishes are unchanged.

Origin: found live 2026-08-15,
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

**"Still" bad 2026-08-20, over his real remote link — TRANSPORT bytes-per-
frame, ruled out above by a LOCAL-only measurement, was the actual
remaining cause** (`data/preview-frame-rate-is-still-bad-over-rem-dhvp/`,
his words: "the frame rate on the preview is still terrible... I'm always
on a remote computer, but LEDFx previews were really good"). The §43
"payload size was never load-bearing" finding measured `JSON.parse`+decode
CPU cost only, never bytes actually crossing a bandwidth-constrained link
— his stated permanent condition. Root cause: `_facade_frame_payload`
(his live default source since the S3 split) emitted pixels as a JSON
list-of-three-channel-lists ("uncompressed"); the LedFX-relay path forwards
whatever LedFX itself sent, which defaults to `transmission_mode=
"compressed"` — base64 of interleaved rgb bytes (`ledfx/config.py`'s own
default, confirmed in `/home/javi/ledfx-src`) — so LedFX being "really
good" on the exact same link was never about downsampling alone, it was
also sending far fewer bytes per point. Fix: `_facade_frame_payload` now
emits the same base64 encoding — no frontend change needed, since
`decodePixels()` (api/devicePreviewWs.ts) already parsed both shapes, just
never received the compact one from this path. Deliberately NOT
reintroducing LedFX's `visualisation_maxlen≈81` downsample cap — same
still-standing reason as before (his matrix-shape ask) — this changes only
the encoding, not the point count. Measured, not asserted:
`scripts/check_device_preview_remote_transport.py` — exact bytes/frame
from the real serialization code (crystal-mapper 36,624B → 10,758B, 3.4x)
plus a real throttled-loopback-socket delivery test at two representative
constrained-link profiles (2 Mbps/60ms: 4.76fps → 9.59fps; 768kbps/120ms:
1.96fps → 4.27fps) — labeled a remote-EQUIVALENT proxy, not his actual
connection, which this task never touched.

Verified against a static harness reproducing his real favourite shapes
at 390×844 and 360×780 (headless Chromium via chrome-devtools-axi), plus
a live isolated instance (spare port, `fx.headless` multi-virtual host
built to his real device shapes) for the canvas rewrite specifically —
his live `:8010` instance was read-only and untouched throughout both.

**Still skipping under fast motion after the bytes fix, 2026-08-20 — the
DELIVERY path, not payload size, was the remaining cause**
(`data/preview-skips-under-fast-motion/`, his second "LedFX was better"
report). Read LedFX's client fan-out (`ledfx/api/websocket.py
WebsocketConnection.send()`/`_sender()`) a second time, this time for what
happens AFTER encoding: it never queues a vis frame — a per-vis_id
single-slot mailbox unconditionally overwrites whatever hasn't been sent
yet, and exactly ONE sender task per connection drains it, one message at
a time. SPECTRA's relay did neither: the facade source fired a bare
`asyncio.create_task` per accepted frame into `WSManager.broadcast`
(`spectra/services/ws.py`), which wraps each client's send in
`asyncio.wait_for(..., timeout=SEND_DEADLINE_S=0.25s)`. Whenever one send
takes longer than a 125ms frame interval — ordinary on a real remote
link, no motion required — the next frame's task starts before the
previous one finishes, so two+ coroutines can be mid-write on the SAME
WebSocket at once (undefined behaviour); whenever a send exceeds 250ms,
the timeout fires and `broadcast()` calls `self.disconnect(ws)` — which
only removes the connection from its list, NEVER calls `ws.close()`. The
browser's socket is left fully open (`devicePreviewWs.ts`'s `onclose`,
its only reconnect trigger, never fires) while the server has silently
stopped sending it anything, forever — a permanent, invisible stall, not
jitter, and it never self-heals. Fix: `spectra/services/
device_preview.py`'s `PreviewFrameHub`/`_PreviewFrameSender` — one
single-slot mailbox + one dedicated sender task per connection, ported
from LedFX's shape, wired into the `/device-preview/ws` endpoint
alongside (not replacing) `preview_ws_manager`, which still carries only
the low-frequency status pushes. A frame send that genuinely fails now
gets a real `ws.close()` before giving up. Status messages are unaffected
and unchanged. Measured, not asserted:
`scripts/check_device_preview_frame_pacing.py` (delay-injected fake
socket bracketing the old 125ms/250ms thresholds — reproduces the OLD
path's concurrent-send overlap and its false eviction-without-close
side by side with the NEW path showing neither) + `tests/
test_device_preview.py` section 6. This is a delivery-TIMING fix, not a
second bytes fix — `_facade_frame_payload`'s encoding above is untouched.

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

**A sparse/black-canvas Matrix effect can opt out of `background_color`
writes entirely** — `config/effect_params.json`'s per-effect
`no_background_color` flag (`fx.device_model.bg_color_blocked()`, checked
by every colour-set-driven write path: `scene_compiler.py` ×2,
`drift_conductor.py`, `scene_response.py`) makes those paths skip writing
a fired set's `bg_color` onto that effect's config at all, regardless of
which set fires. Still set on `radial` ("a non-black background washes
the panel") and `pacman` (both paint thin/sparse content onto a canvas
that starts as `np.zeros(...)`, unlike the denser particle effects that
read their own `self._bg_color`/pre-filled `self.matrix`, e.g.
`blackhole.py`). §85 also set it on `squiggles` after a real headless
render proved a bright authored background floods ~100% of its frame —
**removed again, §87, his own ruling: "keep the backgrounds, i want to
control them with overrides."** He was told the legibility tradeoff and
chose to manage it himself with colour-group overrides (§10) instead of
having the capability suppressed — made possible once §86 proved a group
override actually reaches the wire (three choke points were silently
discarding it before that fix). If a Matrix scene's colour-set accept
list looks suspiciously narrow, check this flag before assuming the
narrowing is arbitrary or before widening it — verify from the effect's
real render output (`fx.headless`), not from set metadata; squiggles'
widened accept list (§85, `accept_all_sets=True`) itself never depended
on the flag and is untouched by its removal. `pacman` carries the
identical byte-for-byte accept list to squiggles' pre-widen state and
still carries the flag — not part of either his §85 widen ask or his §87
background ruling, deliberately left alone as his call, not tidied in
passing.

**In "light" mode, an authored `#000000` background clears to the room's
own Light background instead of literal black** (`room_controls.
resolve_authored_bg_color`, his ruling "do option three": Light paints its
forced background ONCE and never re-asserts it, so a later colour-set fire
authoring literal black — 30 entries across 22 of his real sets — cleared
it and it never came back). Threaded into all five places a colour-set/
scene-entry background reaches the wire: `scene_compiler._entry_config`/
`_apply_set_colors`, `scene_response.ResponseEngine._color_jump`,
`drift_conductor.DriftConductor.apply_color_set`/`_journey_leg`. Real-data
proof: `scripts/check_light_mode_bg_clear.py`. Tests:
`tests/test_light_mode_bg_clear.py`.

**This feature shipped once (PR #142), crashed the service on every start,
and was reverted (PR #145) — the rebuild (PR fm/spectra-light-mode-fix-
import-crash) kept the feature identical and fixed only the construction
pattern.** `DriftConductor`/`ResponseEngine` are both built as singletons
at `spectra/services/engine.py`'s MODULE IMPORT TIME (`conductor =
DriftConductor(...)`, `responses = ResponseEngine(...)`) — never inside a
function, never lazily. PR #142 gave each of them a
`room_controls_load: ... = None` constructor param whose fallback,
evaluated **inside `__init__`**, did `room_controls.load_room_controls`
— a real attribute access on the module-level `room_controls` imported at
the top of the file. That module-level name was ALSO reused as a plain
constructor **parameter** name (`room_controls: Callable[[], Any] | None
= None`, added independently by PR #144 for the drift-gradient feature,
already merged to master by the time #142 was reverted) — inside
`__init__`, any bare reference to `room_controls` binds to the parameter,
not the module import, so the fallback silently read `None.
load_room_controls` and threw `AttributeError` on every process start
(`spectra/services/drift_conductor.py:261`), a two-minute room outage
before revert. Reproduced exactly by re-applying PR #142's diff on top of
current master and running `python -c "import spectra.app"` — a plain
in-process pytest run never catches this, because pytest has already
imported `spectra.services.room_controls` via some earlier-collected test
file by the time any one test runs, which is exactly what masked it the
first time.

**The rule, going forward: nothing that can be constructed at import time
may touch `room_controls` (or any similarly singleton-adjacent service
module) eagerly — inside `__init__`, as a bare default expression, or via
a module-level `from spectra.services import ... room_controls` import in
a file whose class gets built at another module's import time.** Resolve
it lazily instead, the pattern `DriftConductor` already used correctly
before #142 (and which the rebuild copied into `ResponseEngine`): a
constructor param `room_controls: Callable[[], Any] | None = None`, stored
as `self._room_controls = room_controls or self._default_room_controls`
where `_default_room_controls` is a `@staticmethod` doing the real `from
spectra.services.room_controls import load_room_controls` **inside its own
body** — nothing is imported or called until `self._room_controls()` is
actually invoked at runtime. Every OTHER call site that needs
`resolve_authored_bg_color` imports it locally, inside the function that
uses it, for the same reason. Before adding ANY new constructor parameter
to `DriftConductor`/`ResponseEngine` (or introducing a new class
constructed at `engine.py`'s module scope), grep the class for an existing
parameter of the same name — a second, differently-scoped meaning for
one identifier inside one `__init__` is exactly how this broke, and it
will not raise at review time, only at the next process start. Regression
proof that a fresh interpreter's cold start still succeeds (the ONLY kind
of check that would have caught this — a green pytest suite says nothing
about import order): `tests/test_light_mode_cold_start.py`, which spawns
`sys.executable -c "import spectra.app"` in a genuinely new subprocess
rather than relying on whatever's already in `sys.modules` inside the test
runner.

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
`scene_store.save()`. `SCENE_SETTINGS_REGISTRY` (6 scalar keys: entry
blend, choreography timing, colour-journey pace, colour-set acceptance —
charge/lull phase ramps REMOVED 2026-08-20, see the Override Blend entry
above; the ramp is a computed dynamic stretch now, not a scene setting)
reads bounds off `SceneV2`/`PhaseChoreography`/`SceneColorJourney`'s own
`Field(ge=,le=)`, same discipline as the room registry. Named `FlareKind`
create/update/remove
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

## SPECTRA colour-set / colour-group likelihood curves

His ask: colour Sets get a likelihood curve reusing the scene sequencer's
own structure; Groups get one too, default flat, that MULTIPLIES onto a
member Set's own curve rather than overwriting it. Sets already had this —
`SequencerConfig.color_set_entries` (`spectra/models/sequencer.py`) is
keyed generically by any `ColorSetCard` id and was already read by
`selection_kernel.select_color_set` (curve × genre × wheel-travel) — so a
Group's curve needed no new storage shape: it lives in the SAME dict, keyed
by the Group's own id. A Group never becomes its own selector candidate
(still `kind=="set"`-only, unchanged from §10); its curve instead
multiplies onto every member Set's score as a fourth factor
(`selection_kernel.group_curve_mult`, `Candidate.group_points`), resolved
via the reverse lookup `spectra/services/color_set_groups.
group_ids_by_set()`. A Set under more than one group (real data: 4 sets
under both "First Group" and "Blues") CHAINS every enclosing group's curve
by further multiplication — never "one wins". Flat/no entry is an exact
float `1.0` identity. The colour ladder gained its own rung,
`RUNG_NO_GROUP` (dropped before wheel-travel, before genre) so a set zeroed
only by an enclosing group's curve recovers the same way a wheel/genre veto
already did — only a set's OWN curve hitting zero stays ladder-proof.
`Pick.factors` carries the resolved `group` multiplier per candidate,
surfaced in `SequencerStatusStrip.tsx`'s "last colour pick" breakdown, so a
starved set is explainable by looking, not a silent mystery. The curve
preview-button/picker/window/Detach/Revert/Save-as-named-curve editor
(`SequencingTab.tsx`'s original inline implementation) was extracted
verbatim into `spectra/web/src/components/CurveAttachmentEditor.tsx` and is
now mounted on both a Set's and a Group's card in `ColorSetsPage.tsx`
("Likelihood" section) — same component, same safety rule, not a parallel
editor. **Reworked 2026-08-19** (card reopened, his words: no
expanded/collapsed selector sitting in the window — a button showing a
live `CurveThumbnail` of the curve in effect, pressing it opens the picker
— and an edit is an immediate one-off, "the status change IS the apply",
no separate Apply step): every edit (drag/add/remove point) writes
straight to the entry's own `inline_points` on the first touch, coalesced
like `ColorSetsPage`'s own live-drag preview updates, and is structurally
incapable of touching a shared `curves[id]` — only the explicit "Save as
named curve…" can, gated behind its overwrite warning as before. "↺ Revert
to original" undoes an edit session back to exactly what was attached
before it started. Full detail: `docs/SPECTRA_SPEC.md` §65/§76. Spec:
`tests/test_color_set_group_curves.py`.

## SPECTRA minimum dwell (rebuilt 2026-08-20 — read before touching "dwell" anywhere)

Dwell was rebuilt under the real definition of a "song transition" (his
words: it means transitions *within* a song, or scene trigger calls — not
between songs). The OLD mechanism — `SelectorEntry.dwell_weight`
(`spectra/models/sequencer.py`), resolved to a SONG COUNT
(`resolve_dwell_songs`, now removed) and gated only inside
`SceneSequencer._on_change_moment`'s own song-transition roll — is
RETIRED. It never touched the path he actually uses: SPECTRA-native
triggers (`trigger_engine._fire`'s `fire_scene` action) went through
`fire_scene_by_id` with zero dwell awareness of any kind, on ~22,000 real
fires.

New mechanism, `spectra/services/dwell.py` — read its own docstring before
touching this. A per-scene MINIMUM HOLD TIME, a curve over intensity (y =
SECONDS, not a likelihood), reusing the SAME `CurvePoint`/named-profile
curve-selector shape and `CurveAttachmentEditor.tsx` component the
sequencer's likelihood curves already use — `SceneV2.dwell_curve`
(`spectra/models/scene.py`, a `CurveAttachment` — the same curve_ref/
inline_points pair minus `SelectorEntry`'s genre_mult/dwell_weight).
`None` = his exact default, `dwell.DEFAULT_DWELL_CURVE` (16s @ intensity
0, 4s @ intensity 1, linear). Gated ENTIRELY at `scene_sequencer.
fire_scene_by_id` — the one choke point every automatic scene-change path
(sequencer roll, trigger `fire_scene`, automatic transition) already
funnels through — so it covers all of them uniformly for free, and fixes
a second bug as a side effect: the OLD mechanism's "current scene" belief
(`SceneSequencer._active_id`) went stale the instant a SPECTRA-native
trigger fired a different scene (it only updated from the sequencer's own
rolls or an OBSERVED legacy bridge fire); `dwell.py`'s state is
process-global, fed by the one function every real fire passes through,
so it structurally cannot have that staleness.

His four answers (binding, `data/plan-make-dwell-meaningful-under-the-
rea-4p73/HIS-DECISION.md` — "do all your recs"): **(A)** no clock reset on
an update effect — a minimum is a floor; only a REAL fire calls
`dwell.note_fired`, never a deferral. **(B)** intensity LATCHES at
entry — `dwell_seconds` is computed once, from the intensity the scene
actually fired at (the render intensity `fire_scene_by_id` was called
with), never re-evaluated while the hold is running. **(C)** every
AUTOMATIC path is gated; the manual editor Fire button is exempt (it
already bypasses `fire_scene_by_id`, same as disabled/mode-availability);
Force Scene still wins but the result NAMES the override
(`overrode_dwell=True`, forwarded through `room_controls.
reconcile_force_scene_if_changed` — same pattern as `overrode_disabled`).
**(D)** a deferred scene change fires the current scene's own UPDATE
EFFECT instead — `engine.fire_scene_update_event` (`scene_response.py`'s
`on_update`), called from dwell's deferral branch, which returns the
`on_update` record (not `None`) so the caller can log what happened.
Originally this meant the scene's own named, type="permanent"
`SceneV2.update_kind` (bypassing band selection entirely) — but 8 of his
9 real scenes had no `update_kind` authored, so most deferred dwells held
with nothing visible happening. **Replaced same-day (2026-08-20, his ask:
"make update scene act like a double intensity flare until we build it
out specifically")**: `on_update` now doubles the given intensity (clamped
to 1.0 — his accepted ceiling, so "double" and "full" read identical from
intensity 0.5 up) and runs it through the scene's own ordinary "flare"
ResponseClass — the SAME band-selection + kind-execution `on_event` runs
for a genuine flare (`_execute_band`, shared by both). No permanent-only
restriction, nothing new to author: every one of his real scenes already
has a "flare" response, so a deferred dwell now visibly flares on all of
them, not just the one (STAR) with an authored `update_kind`.
`SceneV2.update_kind` is untouched (still authorable, still validated) but
simply unread by this path now — reserved for whenever a real, purpose-
built update effect gets designed; don't repurpose it for that without a
fresh ask. Because `on_update` can now land a momentary kind, a dice
re-roll, or a colour rotate — none of which the original permanent-only
design ever produced — `fire_scene_update_event` also schedules their
releases the same way `fire_response_event` already does
(`pending_hold_groups`/`pending_color_rotate_holds`), which it never
needed to before.

**The interim hold is NEVER SILENT either way**: `fire_scene_by_id`
records every deferral to `fire_history`'s `"deferred"` bucket
(`{scene_name, remaining_dwell_s, update_result}`, both the durable count
and the show-log timeline, visible on the Review page), so "why didn't
the room change" is a log lookup, not a mystery indistinguishable from
triggers having stopped working — now doubly true since a scene with no
"flare" response at all (the only remaining no-op case) is rare to begin
with. Real-fixture proof against his actual scene library (not just a
synthetic harness): `scripts/check_update_effect_double_intensity.py`.

Frontend: `SequencingTab.tsx` mounts a SECOND `CurveAttachmentEditor`
below the likelihood one, `attachField="dwell_curve"` — a THIRD storage
path the shared component didn't have before (round-trips `POST /scenes`
via `useAttachCurve`, not `PUT /sequencer/config`), plus two small
additive props (`defaultPoints`/`noneLabel`) so "no override" previews his
real 16s/4s default instead of a misleading flat-1.0 line — never a
parallel control, the same component every other curve in this app uses.
**Those props only engage when the caller passes NO entry for an unset
item** — `CurveAttachmentEditor`'s 'none' state is keyed on `entries[id]`
being `undefined`; an entry present with both curve fields null reads as
'flat'. `SequencingTab`'s dwellEntries shipped fabricating a both-null
entry for every scene, so every unset scene (all nine of his — stored
`dwell_curve: null`, correct data) displayed "Flat 1.0" and clicking the
Default tile looked dead (it wrote null over null and the display lied
again after refetch) — his 2026-08-21 report, fixed by filtering unset
scenes out of the entries record, display-only, no data touched
(`scripts/check_dwell_curve_display.mjs` reproduces both sides). Any
future caller adapting a nullable single-field attachment into this
component must map "unset" to entry-absent, never to a both-null entry.
Spec: `tests/test_dwell.py`, `scripts/check_spectra.py`'s own MINIMUM
DWELL section (mirrors the Force Scene proof immediately above it).

**Rebased past #148 (My-triggers-only mode) and #150 (charge/lull ramp
scales to the real gap to the next trigger) — both landed on master the
same week and both touch this area; checked, not assumed, that they
compose.** `engine.fire_scene_update_event` gained a second caller (this
module's deferral) the same week #148 widened its own internal gate from
literal `"full"` to `("full", "triggers_only")` — the merged function
keeps BOTH: the widened gate AND the `Optional[dict]` return this module
needs to log what the update seam actually did
(`tests/test_dwell.py::test_fire_scene_update_event_runs_under_triggers_only`
proves the merge, all four tiers). The dwell gate itself never reads
`scene_change_mode` — it applies uniformly regardless (his decision C),
proven directly under `"triggers_only"` (his room's real live mode) in
`test_dwell_defers_correctly_regardless_of_scene_change_mode`, not just
the `"full"` default every other test here runs under. #150 removed
`SceneV2.phase_blend`/`PhaseBlend` entirely — unrelated to `dwell_curve`,
which sits lower in the same model and rebased clean. **The one real
interaction, named not silently accepted**: #150's charge/lull ramp
stretches toward the NEXT trigger's timestamp (`_next_trigger_gap_ms`, a
FORWARD-looking gap read off the trigger schedule) — if that next trigger
is a `fire_scene` action and dwell's minimum hasn't cleared, the dramatic
build lands on an update effect instead of the scene switch it visually
promised. `dwell.py` and `_phase_ramp_ms`'s own docstrings both spell out
why these are genuinely different gaps (not a shared formula that could
drift) and why predicting the other side isn't attempted — see either.

## SPECTRA scrubbing previews — flares, TRANSITIONS and the DROP SEQUENCE

Owner ask 2026-08-20, `data/timeline-preview-scrub-flares-and-drop-
sequences/HIS-VERBATIM-WORDS.md`, his own sequencing: "start with the
flares, then we will do lull charge drop". **The second half is now built
(2026-08-27, fm/flare-preview-offsets-everywhere, his order: "get it
finished and tested, then push it to transitions and to the drop
sequence") — see "THE OTHER TWO PREVIEWS" at the end of this section.**
The flare design below is still scoped to a single isolated `FlareKind`;
the other two are separate programs over the SAME hold, never second
holds.

`ResponseEngine.fire_kind(kind, intensity)` (`spectra/services/
scene_response.py`) fires ONE declared kind in isolation, bypassing band
selection — mirrors `on_event`'s fixed dice→moves→gain→colour order at
scale=1.0. `spectra/services/flare_preview.build_timeline(scene, kind,
intensity)` drives it against a SCRATCH `DriftConductor`/`ResponseEngine`
pair (real `scene_compiler.resolve_scene`/`compile_scene` resolution —
same reads a dry-run scene test-fire already makes — but `room_save=
lambda _st: None` on both, so nothing is ever persisted) wired to a
`RecordingExecutor` and a controllable fake clock: every write's real
relative timing (glide duration, hold_s before a momentary release,
`PULSE_RELEASE_S`) is computed in one synchronous burst, never actually
waited. This is his pre-authorised "catch-up" path ("ideally live, but
catch-up is fine if substantially easier") — and a better instrument for
his stated purpose than a live capture would be, since a live poll can
itself lie about a fast transition (see the CLIP v2 `dynamics.duration`
polling entry above); the returned `animation_start_s`/`animation_end_s`
are read straight off the real production constants, not sampled.
**One easy-to-repeat mistake, caught building this**: `conductor.
on_scene_fire` must be called with the scene's ORIGINAL `flare_kinds`/
`devices` (bindings intact), not the `resolve_scene`-resolved copy — the
resolved copy has already replaced every `ValueBinding` with a scalar, so
a dice-reroll kind previewed against it re-rolls nothing (zero writes).
`scene_compiler.fire_scene` itself gets this right by calling
`engine.on_scene_fired(scene, writes, ...)` with the pre-resolution
`scene`, not `resolved` — mirror that, not the resolved copy, in any
future code that seeds a conductor this way.

API: `spectra/api/flare_preview.py` — `POST /open` (computes the
timeline, arms `preview_pause` — see that module's docstring, now a
second caller alongside `room_preview.py` — does NOT fire live, see the
TRUE SIMULATION entry below), `POST /fire` (the live half — the ONLY
caller of `flare_preview_hold.open_hold`, called once per loop cycle by
the frontend), `POST /heartbeat` (re-arms; the frontend pings this every
5s while the overlay is open), `POST /close`. "Automatically pauses the
trigger engine" is this pause, kept alive only by the heartbeat — no
fixed-duration timer covers "however long he leaves the overlay open."

Frontend: `spectra/web/src/scenes/tabs/FlarePreviewOverlay.tsx`, opened
from a "▶ Preview" button on each flare-kind card in `ResponseTab.tsx`.
Two independently-positioned marker kinds, per his brief ("I would see
the marker for where the trigger should align, as well as some markers
showing start and end of animation" — deliberately not the same line):
the TRIGGER mark is draggable and DEFAULTS to coincident with the
computed animation start; the START/END markers are fixed, computed,
never dragged. Dragging the trigger mark writes `FlareKind.
trigger_offset_ms` (`spectra/models/scene.py`, signed ms, default 0,
**HIS sign convention** — negative = fire earlier, positive = fire
later, see the TRUE SIMULATION entry below for the full ruling and the
inverted-sign defect it corrects) via `setScene` — a real scene-DRAFT
edit, saved by the page's own Save button like any other field, not a
preview-only value discarded on close. **No longer descriptive only as
of 2026-08-21 — this field is what the live preview's own fire loop
schedules from** (see below), **and since the same day's follow-up (PR
fm/engine-reads-flare-trigger-offset, his ask: "make the engine read the
offset and work with the offset like we had in spot FX") THE REAL FIRING
PATH READS IT TOO**: `trigger_engine.tick()` relocates a `fire_response`
trigger's target by the fired band's authored kind offset
(`scene_response.band_trigger_offset_ms` — its docstring carries the
multi-kind aggregation rule: min over the NONZERO offsets, a kind at the
untouched default 0 never vetoes a sibling's authored ask, because a band
fires atomically), read LIVE off the ACTIVE scene at render intensity,
composed with the automatic lead exactly as #172 composes the
trigger-level sibling field (`target = timestamp + his_offset`, then
`fire_at = target - lead` — never the same sign added/subtracted). All 61
of his real flare kinds carried offset 0 when this shipped (re-verified
live), so it changed nothing stored. Two structural guards ride with it
in `tick()`, both needed because this target is LIVE (the active scene
changes between ticks): a fired-keys memory — `(trigger_id,
timestamp_ms)`, cleared with `_pins` on song change/rewind — that ALSO
fixes a pre-existing double-fire in the safety-net OR clause (any trigger
fired more than one tick early used to fire AGAIN when its nominal
target crossed the window — reproduced red pre-fix; the module
docstring's "fires once per crossing" was emergent, now explicit), and a
stranded-target net (a target relocated behind the window uncrossed
fires late-not-never, only while the raw mark is still ahead and
playback advanced). Scoped like the lead system: stored triggers only —
a bridge-classified flare has no forward notice, nothing to relocate.
Specs: `scripts/check_triggers.py` §11,
`tests/test_flare_kind_trigger_offset.py`.

Help: `spectra/web/src/help/helpContent.ts` id `flare-preview-timeline`
(under the `scenes-page` section, next to `flare-kind-edit-box`),
deep-linked from the overlay's own `<HelpLink topic="flare-preview-
timeline" />`.

Executable spec: `scripts/check_flare_preview.py` (dry-run-only, no live
storage write — asserts against the real `scene_response.py` timing
constants, not re-derived approximations; also proves a momentary
kind's release is silently skipped when its param has no resolvable
baseline, e.g. a boolean, matching real production behaviour rather than
being a gap this feature introduces).

**Correction, same day (2026-08-20): the preview above touched nothing
real, and his own live test caught it** ("i have tested some of the
flares and they do not actually change anything on the lights"). His
words on opening one, verbatim: "previewing a flare should temporarily
call the scene, and hold it while the preview window is open. then
release when it is closed" (his transcription drops letters — "hold" is
the only reading that fits). `spectra/services/flare_preview_hold.py` is
the live half, built ALONGSIDE `flare_preview.build_timeline` above,
which stays exactly as documented (a pure, hardware-free computation for
the browser's scrub/markers — unchanged). `open_hold(scene, kind,
intensity)` calls `flare_preview._scratch_engine` (now taking a
caller-supplied `executor`/`clock` rather than always building its own
`RecordingExecutor`, so the timeline model and the live fire can never
silently diverge in what they resolve) wired to `_SeamExecutor` — an
adapter onto `fx_seam.apply_writes`, the SAME ownership-routed seam
`room_preview.py`/`dark_light.py`/`ambient.py` already use for their own
explicit-owner writes, never a bespoke live-write path or the PRODUCTION
`engine.conductor`/`engine.responses` singletons (using those would make
"release" require deep-copying and restoring live engine-internal state —
the exact trap `room_preview.py`'s own docstring names for
`active_set_id`/wheel position). The scene's own compiled writes land via
`fx_seam.apply_writes` directly (skipping `scene_compiler.fire_scene`'s
`engine.on_scene_fired` call for the same reason), then `kind` fires for
real against the scratch pair via `ResponseEngine.fire_kind` — so a real
momentary/permanent/dice/gain/colour-jump write reaches his fixtures,
with real relative timing (`PULSE_HOLD_S`/`PULSE_RELEASE_S`/
`DICE_REROLL_GLIDE_MS`), not a `RecordingExecutor` entry.

**A facade PUT with `transition_ms>0` does not update `effect.config`
synchronously** — `fx/effects/__init__.py`'s `start_param_transitions`
stores a per-param tween, advanced once per RENDERED FRAME, not per PUT.
This bit the revert specifically: `transition_ms=0` (room_preview's own
convention, safe there because that module never creates a tween in the
first place) calls `_apply_config` directly WITHOUT clearing any
already-in-flight tween on the same key — a still-glide-ing flare param
would silently resume overwriting the "reverted" value on the very next
rendered frame, landing on the flare's own target instead of the true
baseline. Fixed with `REVERT_TRANSITION_MS=1` (mirrors `fx_executor.py`'s
own `JUMP_MS` convention): a positive duration always takes the
tween-RETARGET branch, replacing any dangling tween for that key from
wherever it currently sits — no snap, and no way for an old glide to fight
a revert. Any future revert/instant-write code in this codebase that
might race a param this same module (or the production engine) is
mid-tweening needs the same 1ms convention, not `transition_ms=0`.

**Release is deadline-driven, not close-driven — the same shape as
`spectra/services/preview_pause.py`'s own `_until`, not a bespoke
per-session `asyncio` task.** `_deadline` is a plain monotonic timestamp;
`open_hold`/`touch` only ever write it (a trivial operation that can't
itself fail); `run_supervised()` — started once from `spectra/app.py`'s
lifespan alongside `frame_watchdog`/`ownership_reconciler`/
`ambient_music_gate`'s own — independently checks every
`SWEEP_INTERVAL_S` (2s) whether a held hold's deadline has lapsed and
reverts it if so, exactly the "a write-time confirmation proves only the
moment it was taken" lesson `ambient_music_gate.py`'s own status-honesty
fix already established in this codebase. This is what makes a lapsed
heartbeat (browser closed rather than the tab's own unmount handler
firing, a dropped connection, a wedged tab) self-heal with NO dependency
on an explicit `/close` ever arriving: worst case `HEARTBEAT_TIMEOUT_S`
(15s, owned by this module, reused verbatim by `spectra/api/
flare_preview.py`'s `preview_pause` window rather than a second,
separately-tuned number) + `SWEEP_INTERVAL_S` (2s) = **17s** after the
last heartbeat. `active()` is itself a pure deadline read (mirrors
`preview_pause.active()`), so a caller never sees "active" reported past
the deadline just because the sweep hasn't ticked yet — reporting and
reverting are deliberately separate concerns.

**A service restart is the one case the deadline can't cover** — it's
in-memory only, same as `preview_pause`'s own `_until`, so it (and the
sweep's ability to know a hold was ever open) is wiped along with
everything else, while the light bytes a restart leaves behind are real.
Handled the same SHAPE as `fx/light_ownership.py`'s own
`recover_stale_handover()`: the pre-fire snapshot is persisted
(`FLARE_PREVIEW_HOLD_FILE`, tmp+`os.replace` atomic, mirroring
`dark_light.py`'s own pre-dark snapshot survival) the instant a hold
starts; `recover_stale_hold()`, called once from `spectra/app.py`'s
startup lifespan (after `handover.resume_own_room()` re-activates the
live stack — reverting is itself a real `fx_seam` write), lands any
snapshot still on disk before anything else touches the lights.
Deliberately NOT age-gated the way `recover_stale_handover()` is: that
gate exists because a young handing-over record might be a LIVE
orchestrator in the OTHER process, still legitimately mid-transition —
there is no second process that could legitimately hold a flare preview
open, so a leftover snapshot found at startup is unconditionally stale
and always gets landed back.

Snapshotting happens once per session (the first live fire — see the
TRUE SIMULATION rebuild below for what "first" means now): every
subsequent live fire in the same session re-fires scene+kind at the
current value without re-snapshotting, so a later revert always restores
the ORIGINAL pre-preview state, never a mid-session one. Help
(`spectra/web/src/help/helpContent.ts` id `flare-preview-timeline`) leads
with what opening a preview does to the room (real lights, paused live
show, ~17s worst-case abandonment revert AND a 3-minute absolute ceiling —
see "MAXIMUM HOLD CEILING" below, they are two different claims) before
any control explanation — Order 20: a feature whose help contradicts what
it now does has not shipped. Proof bar: a real headless render pipeline
(`fx.headless` +
`fx.facade`, ownership=spectra — the same rig `test_room_preview.py`
already uses), reading a written value off a live
`virtual.active_effect.config`, never a `RecordingExecutor`'s own write
log. Tests: `tests/test_flare_preview_hold.py` (fire+release, mid-session
re-fire, deadline lapse + sweep, `run_supervised()` end-to-end, restart
recovery) — `open_hold()` itself is unchanged by the rebuild below, only
who calls it and when.

**TRUE SIMULATION — loop + fire-on-the-mark (2026-08-21, PR
fm/preview-loops-and-fires-on-the-trigger, his report: "the preview only
happens once, it should happen every time, and it should fire with the
same timing as if the playhead was crossing a trigger").** Before this,
`/open` did two things in one call — computed the (hardware-free) ruler
timeline AND fired live, INSTANTLY, regardless of where the drawn trigger
mark sat: the drawing knew about the mark, the firing didn't.
`spectra/api/flare_preview.py` now splits this: `POST /open` computes the
timeline only (still arms `preview_pause`, no live write) and `POST
/fire` is the sole caller of `flare_preview_hold.open_hold`. The frontend
(`FlarePreviewOverlay.tsx`) calls `/fire` once per loop, timed by its
existing RAF playhead loop to land exactly when the playhead crosses
`animation_anchor_s` — a new field in `build_timeline`'s response
(`spectra/services/flare_preview.animation_anchor_s`/`trigger_mark_s`,
computed server-side so the ruler draw and the fire schedule are
ONE source of truth, never two independently-derived numbers). Firing at
the anchor every cycle is definitionally "lead `offset_ms`
early/late relative to the trigger mark's own crossing," since
`trigger_mark_s` is DEFINED from the anchor via the offset — there is no
second lead-time computation to keep in sync.

**The sign-convention fix this exposed, HIS RULING (same PR, corrected a
genuine inversion in the 2026-08-20 original build):** negative
`trigger_offset_ms` = fire earlier, positive = fire later, 0 =
coincident; dragging the trigger marker RIGHT makes the offset MORE
NEGATIVE. The original build had `trigger_mark_s = anchor + offset/1000`
(the opposite sign) — caught before any real value existed to migrate:
all 61 of his real flare kinds carried 0 at the time, confirmed by a
parallel live-data audit before the fix shipped, so nothing of his was
flipped. `FlareKind.trigger_offset_ms` is NO LONGER descriptive-only — it
is what the live preview loop schedules its fires from now. If you touch
this area again: `trigger_mark_s = animation_anchor_s -
trigger_offset_ms/1000` is the ONE formula (spectra/services/
flare_preview.py) — never re-derive it independently in the frontend or
you will reintroduce exactly this class of bug. Tests:
`scripts/check_flare_preview.py` (the sign proof, both directions),
`tests/test_flare_preview_api.py` (the open/fire route split),
`tests/test_spectra_trigger_offset_field.py` (the trigger-model field
shape).

**His scene-change/trigger-level equivalent, `SpectraTrigger.
trigger_offset_ms` (`spectra/models/trigger.py`, same field/units/sign),
is HONOURED too now (2026-08-21, PR fm/scene-changes-honour-trigger-
offset)** — and since 2026-08-27 (fm/flare-preview-offsets-everywhere) on
EVERY action kind, not just `fire_scene`. A silently-inert field is a
trap, and an OFFSET has no action-kind-specific meaning to justify one: it
only RELOCATES the moment, where a LEAD has to know what payoff it aligns
and how long that payoff takes, so an offset composes with an instant
apply (`select_color_set`, `fire_scene_update`) exactly as with a
crossfade. **Where the fired CONTENT also carries an authored offset, the
two ADD** — `SceneV2.trigger_offset_ms` for `fire_scene`,
`band_trigger_offset_ms` for `fire_response` — legal because both are
OFFSET family (same unit, same sign); it is only the oppositely-signed
LEAD that must never be added to either. An override rule was rejected: it
would silently discard whichever he authored second. Both default 0, so
this is provably inert against everything on disk. The care here: `tick()` already had
a lead-time system (`_lead_ms`, the three-anchor alignment above) whose
sign is the OPPOSITE of his — there, a POSITIVE lead means fire EARLIER
(`fire_at = target - lead`); his offset is NEGATIVE for earlier. The two
never combine by adding/subtracting the same sign — that would silently
invert one of them. They compose by each acting in its own native
direction against a shared, relocated base: `target_ms = trig.timestamp_ms
+ trig.trigger_offset_ms` (his convention, applied first), then
`fire_at = target_ms - lead_ms` (the existing lead system, unchanged) —
net `fire_at = trig.timestamp_ms + trig.trigger_offset_ms - lead_ms`,
which is byte-identical to the pre-existing formula whenever offset=0
(every one of his real fire_scene triggers, as of this field's
introduction — no stored data was touched). `tick()`'s own inline comment
has the full reasoning, including why the crossing-check's safety-net OR
clause must compare against `target_ms`, not the raw `trig.timestamp_ms`
— using the raw timestamp there would silently discard a positive
("later") offset by firing at the old mark anyway. Proof is offline only
(both sign extremes plus the composed case): `scripts/check_triggers.py`
§10, `tests/test_trigger_engine.py`. No live fixture proof exists for
this — his room is released (panic release taken back), so nothing can be
proven against real hardware right now.

**The preview's own live-fire loop honours the SAME automatic lead a real
trigger fire would apply (2026-08-21, PR fm/preview-must-hold-scene-
changes), and separately, opening a preview now genuinely holds SCENE
CHANGES too, not just flares/responses — a real live regression, not a
design gap.** His report, verbatim: "I was using spectra, playing music,
and tried to preview. now it won't even hold... The music show is playing
regardless of the fact that I have the preview window open and it says
'deferred by preview.'" Root cause: `bridge.py`'s `conductor_deferral`/
`sequencer_deferral` (the "deferred by preview" string he saw) already
checked `preview_pause.active()` — true, correctly gating the sequencer's
own rolls and drift — but `scene_sequencer.fire_scene_by_id`, the ONE
choke point every scene change funnels through INCLUDING his authored
`fire_scene` triggers (`trigger_engine._fire`/`_fire_transition`), never
consulted it at all; `preview_pause.py`'s own docstring had named that
function as gated since it was written — the documentation described a
gate that was never built. Fixed by gating `fire_scene_by_id` on
`preview_pause.active()` FIRST, ahead of even Force Scene — the one gate
in that function Force Scene does NOT override, matching `bridge.py`'s own
precedence (preview already outranked force_scene there too) — because a
hand-held preview is the most explicit, momentary override a room can be
under. Recorded to `fire_history`'s `"deferred"` bucket like the dwell
gate (never silent) but, unlike dwell, does NOT fire an update effect on a
skip: dwell's placeholder flare exists to make an otherwise-invisible hold
visible; a preview's whole point is an isolated, motionless room, so an
update effect would put motion into the exact thing he opened the preview
to judge. Self-heals on abandonment with no code beyond the existing
deadline: `preview_pause.active()` is a plain `time.monotonic()`
comparison, not a flag anyone must remember to clear, so a browser
close/dropped connection/wedged tab (heartbeats simply stop arriving)
resumes his show on its own within `HEARTBEAT_TIMEOUT_S` — proven directly
in `tests/test_preview_scene_hold.py` by letting a started pause's
deadline lapse and firing again WITHOUT ever calling `preview_pause.clear()`,
not just by testing the clean-close path.

Separately (same PR, his ask: "the preview must use the app's own
delay/offset setting when it fires... the same lead the real show applies
must apply here, or the preview lies about when his flare lands"): before
this, the live fire was scheduled at `animation_anchor_s` unconditionally
— an authored/manual ruler position with no reference to the AUTOMATIC
lead `trigger_engine._response_switch_lead_ms` computes for a real
trigger fire (`DICE_REROLL_GLIDE_MS` for a registry-smooth momentary
glide, or the intensity-scaled `color_rotate_ramp_ms` for a colour-rotate
kind). `scene_response.kind_lead_ms` is the per-KIND extraction of that
same computation (`_kind_would_glide` factored out of
`momentary_switch_would_glide`'s own band loop so the two can never
silently diverge) — reused, not reapproximated, since `ResponseEngine.
fire_kind` previews ONE kind in isolation, bypassing band selection
entirely, so there's no band for the band-scoped functions to loop over.
`spectra/services/flare_preview.fire_at_s(anchor_s, lead_ms)` composes it
with his own `trigger_offset_ms` EXACTLY the way #172 above composes
`SpectraTrigger.trigger_offset_ms` with `_lead_ms` — proven algebraically
in `build_timeline`'s own docstring and in `scripts/check_flare_preview.py`
§1c: since `trigger_mark_s = animation_anchor_s - offset_ms/1000` already
means `trigger_mark_s + offset_ms/1000 == animation_anchor_s` for ANY
offset, his authored offset is already baked into `animation_anchor_s` by
construction — so `target ≡ animation_anchor_s` and `fire_at_s = target -
lead_ms/1000` is the whole composition, with nothing left to add.
`trigger_mark_s`'s own formula/meaning is UNCHANGED — the drawn mark still
reflects only his authored offset; only WHEN THE WRITE ACTUALLY HAPPENS
moves, earlier by however long this kind's own switch/ramp needs. Frontend
(`FlarePreviewOverlay.tsx`) schedules its `/fire` loop against the new
`fire_at_s` field instead of `animation_anchor_s`, and the accent
"start"/"end" ruler markers move with it too (they represent when the
write lands, which is now `fire_at_s`, not the old fixed anchor).

His other two asks in the same brief were AUDITED, not rebuilt — both were
already correct as of PR #170/#172, verified rather than assumed: (1)
"fires every time the playhead crosses the trigger line, every lap" — the
RAF loop's own catch-up-avoiding `while (nextFireAt <= now) nextFireAt +=
durationS * 1000` shape was already sound; (2) "dragging the trigger mark
changes the flare's offset" — `dragTrigger`'s pointerup already called
`onTriggerOffsetChange` → `setKindTriggerOffset`, a real scene-draft edit.
Both audited with `scripts/check_flare_preview_frontend_loop.mjs` — a
plain Node script (no framework; this repo has no JS test tooling) that
extracts the exact scheduling/offset formulas VERBATIM from
`FlarePreviewOverlay.tsx`/`flareKindOps.ts` and drives them with a fake
clock: zero network, zero browser, so it can prove multi-lap firing
cadence and the lead-vs-no-lead schedule delta without ever risking a
real `/fire` HTTP call. **This offline-only proof was a deliberate
choice, not a shortcut**: a live isolated `python -m spectra` instance on
a spare port was tried first and aborted immediately after its bridge
connected to a real `ws://127.0.0.1:8000/ws` (a live, in-use service,
consistent with his room being in active use at the time) — `SPECTRA_
STORAGE_DIR` repoints scene/room storage but NOT `fx/light_ownership.py`'s
`OWNERSHIP_FILE` (a fixed, worktree-relative path) or the bridge's WS
target (`SPECTRA_BRIDGE_WS_URL`, not set by default), so an isolated
instance's flare-preview live-fire path is not automatically network-safe
by construction. If a future task needs a truly live-isolated proof, set
BOTH env vars explicitly and confirm nothing is reachable at the
`fx_seam` HTTP fallback target (`config.ledfx_url()`, `LEDFX_HOST`/
`LEDFX_PORT`) before opening any preview against it — don't assume
`SPECTRA_STORAGE_DIR` alone isolates the write path.

**MAXIMUM HOLD CEILING (2026-08-21, PR fm/preview-hold-needs-a-ceiling) —
his room was held 13m54s in one continuous window by a client that never
stopped heartbeating (a headless browser left running by mistake),
refusing 85 scene changes.** `HEARTBEAT_TIMEOUT_S`/`SWEEP_INTERVAL_S`
above only bound ABANDONMENT (how long a hold survives once heartbeats
STOP) — they say nothing about a client that keeps heartbeating forever,
which is exactly what happened: a bound a live client can push out
forever is not a bound. `flare_preview_hold.MAX_HOLD_DURATION_S` (180s,
3 minutes — long enough for a real unhurried look, several loops, an
intensity nudge; short enough that a forgotten tab is a brief nuisance,
not a lost show) is an ABSOLUTE ceiling on one continuous hold, counted
from the session's first real fire (`_session_started_at`) and enforced
by capping every `_rearm()` call against it — no number of heartbeats
moves it. Reaching it locks the session (`_locked_until_reopen`) so a
client that keeps calling `/fire`/`/heartbeat` afterward (the reported
failure mode — no further `/open` ever arrives) cannot silently
re-establish a new hold; only a genuine fresh `POST /open` (a real mount,
or him moving the intensity slider — never a bare heartbeat) calls
`clear_ceiling_lock()` and lets a new session begin. `preview_pause` —
armed independently by `spectra/api/flare_preview.py`, the thing that
actually refuses his scene changes — is capped to the SAME ceiling via
`flare_preview_hold.capped_pause_s()`, so it can never outlive the light
hold's own deadline; without this the scene gate could stay refused for
up to another `HEARTBEAT_TIMEOUT_S` after the lights already reverted.
The frontend (`FlarePreviewOverlay.tsx`) surfaces the ceiling firing as a
visible banner and stops its own loop, rather than silently continuing to
poll a room that already let go. Proof that the ceiling actually holds
while a client keeps heartbeating THE WHOLE TIME (never letting the
heartbeat lapse — a test where heartbeats stop only proves the
pre-existing abandonment bound, not this one):
`tests/test_flare_preview_hold.py` (real headless fixture) +
`tests/test_flare_preview_api.py` (the `preview_pause` capping, route
wiring).

**THE OTHER TWO PREVIEWS (2026-08-27, fm/flare-preview-offsets-everywhere;
`docs/SPECTRA_SPEC.md` §95).** Both live on the Scenes page's Phase
Choreography tab — the tab that already describes in words exactly what
they show — and both run on the ONE hold above, never a second one.

- **ONE HOLD, MANY PROGRAMS.** `flare_preview_hold.PreviewProgram` is the
  seam: a program supplies its held scene, any EXTRA virtuals it may touch
  (a transition's incoming scene can reach virtuals the outgoing one never
  does — leave them out of the snapshot and `close()` hands some back and
  silently keeps the rest), and what each named STEP does.
  `open_program_hold(program, intensity, step=...)` is the general entry;
  `open_hold(scene, kind, ...)` is now the thinnest program
  (`FlareKindProgram`) over it and is unchanged in behaviour. Everything
  hard — snapshot, deadline, sweep, 3-minute ceiling, restart recovery,
  both release queues, the 1ms tween-safe revert — stays in one place. A
  new preview supplies a program; **it never supplies a second hold.**
  `heartbeat`/`close` moved to `spectra/api/preview.py` (`/api/preview`)
  with the flare paths as thin aliases: the hold is shared, so its
  keep-alive is too.
- **TRANSITIONS** — `spectra/services/transition_preview.py`,
  `POST /api/preview/transition/{open,fire}`, `TransitionPreviewOverlay.tsx`.
  A scene transition anchors its MIDDLE (the settled family). The
  crossfade, the anchor fraction and the lead all come from
  `spectra/services/scene_transition_lead.py` — a NEW module that
  `trigger_engine._scene_transition_lead_ms_for` now CALLS, so the preview
  asks production's own function instead of re-deriving it. **The drag
  writes `SceneV2.trigger_offset_ms`** (new field, same family/clamp/sign
  as `FlareKind.trigger_offset_ms`), read on the firing path by
  `tick()`'s `_scene_offset_ms`. Its one honest bound, recorded rather
  than discovered: for an UNRESOLVED `fire_scene` pick (100% of his real
  triggers) the scene isn't known until the LOOKAHEAD pin commits
  `LOOKAHEAD_HORIZON_MS` (5s) ahead, so an offset inside that window lands
  and a larger negative one degrades to the un-relocated mark — late,
  never wrong. Forcing the pin earlier from the wider offset gate was
  considered and rejected: it would widen the window a pin's validity can
  drift, the exact risk `_pin_still_valid` exists to contain.
- **THE DROP SEQUENCE** — `spectra/services/phase_preview.py`,
  `POST /api/preview/sequence/{open,fire}`, `SequencePreviewOverlay.tsx`.
  Every ramp is `scene_response._phase_ramp_ms` (the show's own function),
  so the dynamic stretch to ~90% of the real gap is what the ruler draws,
  with the remaining ~10% as a separate HANG band — his spec verbatim, and
  the reason two gap sliders exist: the hang is a thing to SEE, not a
  number to set. Drop is never stretched and BEGINS on its mark. **Marks
  are deliberately not draggable** — a band's offset is an aggregate over
  its attached kinds (`band_trigger_offset_ms`, min over nonzero), so a
  drag would have to pick one; the per-kind flare preview already authors
  it and the panel says so. `release_phases()` gained `force=` for the
  per-lap release (each step runs on a FRESH scratch pair, and a drop arms
  nothing by production's own rule — exactly when a sequence ends); every
  production call site keeps the guard.
- **Server computes every anchor and fire moment**; the frontend schedules
  against `cues[].at_s` and draws against returned markers.
  `PreviewRuler.tsx`/`usePreviewLoop.ts` are shared so all three previews
  draw one instrument. Offline proof of the multi-cue scheduling (formulas
  extracted VERBATIM, fake clock, no network):
  `scripts/check_preview_cue_loop.mjs`.

**PROVE EVERY HOLD FROM THE SHOW SIDE, not the preview side.** The
founding defect of this whole system was a hold that REPORTED itself as
set — the UI even said "deferred by preview" — while his triggers kept
firing underneath, because `fire_scene_by_id` never consulted
`preview_pause`; every test that existed asked the preview side and passed
throughout. `tests/test_preview_holds_the_show.py` is the standing bar for
any hold, new ones included: drive the REAL trigger engine over a real
position feed with a four-action-kind corpus while the hold is open and
measure THE ENGINE'S output — zero writes at `fx_seam` (the one seam a
light byte leaves SPECTRA through), zero response surges, and the
deferrals present and NAMED in `fire_history` (a held room and a broken
room must not look the same in the log) — then replay the same sweep after
release to prove the corpus was live. It includes a test that re-creates
the ungated pre-fix world and proves the harness goes RED on it: a proof
bar that cannot fail on the defect it was written for is decoration.

**§84's missing instrument is BUILT, offline** —
`scripts/check_scene_entry_ramp_landing.py` +
`tests/test_scene_entry_ramp_landing.py`. It runs the whole production
chain and then WATCHES the ramp with the mechanism the light itself is
driven by (`Effect._advance_tweens`, one step per rendered frame through
`fx.headless`'s real pipeline), with song position and wall clock 1:1.
Measured: the crossfade's midpoint lands +16.7 ms (one frame) of a 4000 ms
mark, for a named scene AND for the LOOKAHEAD-pinned shape all his real
triggers have; with the lead disabled it misses by +616.7 ms, exactly half
the crossfade. Not a room proof and not claimed as one. **Note for anyone
writing a similar instrument: `dwell` is process-global by design, so each
observation must reset it the way a song change would — otherwise the
second fire in one process is legitimately deferred by the first one's
dwell floor and renders nothing at all.**

## The room LIGHT-FIELD map (`/rooms`) + room effects (`/room-effects`)

**THE ONE IDEA, his own sentence, and the thing this whole area exists to
protect: the map records WHERE EACH EMITTER'S LIGHT LANDS AND HOW MUCH — a
measured light field — NEVER where the LEDs are.** `spectra/models/
room_map.py`'s docstring is the binding statement. There are no coordinates,
no metres and no room drawing anywhere in this feature, deliberately: a
sconce's spill onto the ceiling and the floor is captured for free by
photographing what it lights, and a fixture-position model would throw
exactly that away. If a change here starts solving for where a strip
physically is, it has left the plan (`/home/javi/fleet-spotfx/.lavish/
room-light-field-plan.html`, §1's own exclusion fence).

Modules, each with a job: `light_field.py` (derivation + store +
`per_emitter_scalar`), `light_field_fields.py` (the four field kinds),
`emitters.py` (WHAT counts as an emitter, at the granularity chosen for one
run), `mapping_session.py` (the phone's server half), `room_mapping.py` (the
protocol as a held-room program), `room_effects.py` (the bounded writer).

**AN EMITTER IS A CARRIER *OR* A PIXEL RANGE OF ONE (2026-08-31, PRs
fm/lightfield-segment-granularity then fm/rooms-picker-light-emitters),
his own correction: "A single device that spans the direction of the wave
should be able to show the effect. the tv mapper is wrapped around a tv. It
should be able to run a dimness wave vertically."** The first slice fenced
an emitter to a whole device, so a wave over a strip wrapped round a
television could only dim the whole television at once.
`spectra/services/emitters.py` is the binding statement for the enumeration
and the id shape. Five things to know:

- **A ROOM IS KEYED BY CARRIER, NOT BY DEVICE**, on his own clarification:
  "i want to be able to work with the devices that i directly use in
  spectra even if they have layers of virtuals before shining... spectra
  can delayer it if easier." A CARRIER is a genuinely-driven virtual
  (`room_topology.genuinely_driven_virtual_ids`) whose segment chain
  reaches at least one light-emitting fixture; `spectra/services/
  carriers.py` is the binding statement. Four of his seven fan out to
  several fixtures (tv-mapper → backlight + both sconces), so a
  device-keyed picker could not name what he calibrates. The chain was
  ALREADY resolved everywhere it mattered — the capture lamp writes to
  virtuals and the gain mask is per-virtual — so this re-key made the list
  agree with the layer beneath it rather than adding a delayering step.
  **The /devices page is untouched**: `device_usage.in_use` answers "does
  this back something driven", a different question, and still lists every
  fixture including the dummies. `emitters.emits_light` is the chain-level
  sub-check and the ONE place a new non-physical type joins the decision.
- **GRANULARITY IS A PER-CAPTURE CHOICE, never a global.** `auto` (default,
  resolved PER CARRIER: `segment` for a strip, `whole` for an all-Hue
  chain) / `whole` (`device` is accepted as the pre-carrier wire word) /
  `segment` (the carrier's own configured segments) / `block`-of-N pixels,
  all in the CARRIER's own effect-pixel space. The Rooms page passes it to
  `POST /rooms/{id}/map`; `GET /rooms/{id}/plan` is the read that says how
  many emitters and how many dark seconds BEFORE he presses.
- **A sub-carrier emitter id is `tv-mapper:blk3[90-119]`** (or `seg`) — the
  NEW ID SHAPE `room_map.py`'s docstring always anticipated — plus a
  STRUCTURED `EmitterFootprint.ranges` and `carrier_id`. Use
  `RoomMap.mapped_carriers()` (not `mapped_ids()`) wherever a CARRIER is
  what a caller selects — `mapped_ids()` returns EMITTER ids, and
  conflating the two silently rejects every legitimate selection (a real
  bug this found in `room_effect_console`). A pre-re-key room on disk
  (`device_ids`) is RESET by `RoomMap`'s own before-validator with a stated
  `migration_note`, never reinterpreted: a device id is not a carrier id
  and a per-device footprint is not a carrier's.
- **"AUTO" GIVES A SINGLE-SEGMENT STRIP *BLOCKS*, and a one-piece map
  WARNS** (2026-08-31, third commit of PR fm/rooms-picker-light-emitters,
  from his own first real run). "Segments for a strip" collapses to ONE
  emitter whenever the strip is configured as a single segment — which his
  TV wrap is — i.e. exactly the outcome this whole feature exists to avoid.
  `emitters.resolve_granularity` now resolves a splittable, multi-pixel
  carrier with `usable_segments(...) < 2` to `block`; an explicit choice is
  still never overridden. Independently, any plan or run yielding one
  emitter for a multi-pixel carrier carries `warnings` (Plan AND
  MappingResult, both on the wire) saying the map cannot show a wave
  travelling and how many pieces Blocks would give —
  `mapping_refusals.one_piece_warning`. A WARNING is not a refusal: the run
  happens and the map is worth keeping, which is why they are separate
  lists.
- **A COPY-MAPPED CARRIER IS NOT A WAVE SURFACE, and the run maps THROUGH
  the fixture's own strip** (2026-08-31, fourth commit of PR
  fm/rooms-picker-light-emitters, from his second failed run). MEASURED
  FIRST, on rendered device pixels: the per-pixel gain mask multiplies the
  effect buffer BEFORE a copy-mapped virtual expands it into each segment,
  so a wave's phase is identical in every segment at every instant —
  `scripts/check_copy_carrier_wave.py`, and do not re-reason this from the
  source. His `tv-mapper` is copy-mapped in front of `tv-backlight` (560 px,
  span, INACTIVE), so `emitters.substitutes_for` prefers the splittable
  DIRECT virtual, footprints keep the carrier's own name, and the SAME
  substitution happens at both ends (capture and wave) for the same reason.
  `room_mapping.activate_for_capture` brings an idle substitute up and puts
  it back; the hold snapshot covers the EFFECT but never an `active` flag it
  did not observe, so the flag is the run's own to restore
  (`tests/test_capture_activation.py` reads it back). `room_effects.start`
  does the same and `stop()` puts it back AFTER the hold's revert.
- **AN EMITTER THE CAMERA NEVER SAW IS A RECORD, NOT AN ABSENCE** (2026-08-31,
  PR fm/mapping-unseen-emitter-note). His first real map ran 22 emitters and
  stored 14; the missing 8 (far-side TV blocks, sconce spill outside the
  frame) produced ~zero lit-minus-dark and simply did not appear in
  `room_maps.json` — correct physics, silent record, with nothing to
  separate "never ran" from "ran, and not in shot". A capture landing under
  `light_field.UNSEEN_WEIGHT` is now STORED footprint-less
  (`EmitterFootprint.unseen`/`note`, empty `grid`/`axis_profile`, so every
  reader already gating on `mapped` skips it exactly as it skipped the
  absence), reported on `MappingResult` (`unseen`, `unseen_count`,
  `summary` — "14 mapped, 8 unseen from this pose"), carried on the room's
  API payload (`unseen`/`note` per footprint, `unseen_ids`) and rendered as
  such by the Rooms page. **The wording is a FACT, not a warning**
  (`mapping_refusals.unseen_note`): a second pose can see the piece later,
  so nothing about it reads as an error and no retry machinery exists.
  SECONDARY HARDENING, never the fix: an emitter measuring ~zero gets ONE
  automatic re-capture later in the same run with a `RETRY_DARK_SETTLE_X`
  (3x) dark settle, and the note then distinguishes the two findings. It was
  built when a neighbour's fade contaminating the next dark reference was
  the leading hypothesis; that was RETIRED in favour of the firmware
  brightness above, and the retry ships as cheap insurance against a
  genuinely contaminated reference, not as an explanation of anything.
  `dark_settle_s`/`lit_settle_s` are per-run, bounded body params
  (`clamp_settle`) — groundwork for quality levels, defaults unchanged.
  Spec: `tests/test_mapping_unseen_emitter.py`.
- **A MAP TAKEN AT 10% FIRMWARE BRIGHTNESS MEASURES THE DIMMER, NOT THE ROOM**
  (2026-08-31, PR fm/mapping-unseen-emitter-note; the captain's verdict on
  his first real map). Every footprint in it came out ~10x dim — five blocks
  at 0.1 or less, i.e. the unseen threshold's own tail — because his fixture
  sat at ten percent FIRMWARE brightness (WLED's `bri`, which scales
  everything the fixture emits including a realtime stream) for the whole
  run, and nothing said so. **`spectra/services/fixture_brightness.py` is
  the binding statement.** Two acts, deliberately separate: the PLAN reads
  it and warns loudly BEFORE the cost (a warning after a four-minute dark
  run has arrived too late to act on — `mapping_refusals.one_piece_warning`'s
  own discipline), and the CAPTURE takes each fixture to full and puts HIS
  level back, restore in a `finally` so it survives the failure path — the
  own-the-flag pattern `activate_for_capture` already uses. A non-WLED
  fixture is `not_applicable` and a fixture that would not answer is
  `unreadable`; NEITHER is ever given a fabricated 255, because a made-up
  full reading makes an unguarded fixture look guarded. **The vendored
  `WLED.set_brightness` had to be fixed first** (`fx/VENDOR.md` #27): it had
  no caller anywhere in the fork and forced every input to 255 via a double
  `max`, so a RESTORE would have silently set full. Spec:
  `tests/test_fixture_brightness.py`.
- **A NORMALISED THUMBNAIL IS BLIND TO THE MAGNITUDE IT NORMALISED AWAY.**
  `light_field.thumbnail` scales each footprint to its OWN peak, so one
  holding a hundredth of its neighbour's light draws an equally convincing
  shape — which is how a whole 10%-brightness map looked fine. A thumbnail
  is therefore NEVER shown without its weight beside it, and
  `light_field.faint_ids` names the footprints under `FAINT_FRACTION` (5%)
  of the strongest in the SAME room. A FRACTION, not an absolute number:
  a footprint is relative luminance in one camera's scale, and the only
  comparison the model permits is within one pose.
- **THE DEVICE LAYER OVERWRITES, IT NEVER BLENDS** — established
  2026-08-31 when a second active virtual on one fixture was suspected of
  attenuating a substituted capture. `fx/devices/__init__.py`'s
  `Device.update_pixels` scatters every active virtual's segments into ONE
  shared `self._pixels` with no alpha or priority, and `assemble_frame`
  returns it unchanged (its own docstring says merging "will eventually" be
  handled). So overlapping writes are LAST WRITE WINS between the
  per-virtual render threads (`fx/virtuals.py::Virtual.activate`) —
  order-dependent, full-or-nothing, and therefore incapable of producing a
  steady fractional dimming. That ruled it out as the dim-map cause; it is
  still a real property worth knowing before lighting one virtual while a
  neighbour covers the same pixels. Proof:
  `tests/test_device_output_composition.py`.
- **A REASON THAT NEVER REACHES A HUMAN IS A SILENT FAILURE — worse, it
  lets us believe we handled the case** (the captain's ruling, same
  commit). `Emitter.note` was written correctly and died in the
  whole-granularity branch. Everything on this path that WRITES a reason now
  leaves for the page: notes → `problems`, a failed activation, a virtual
  left rendering, an unreadable device list (which silently disables the
  emits-light backstop), the substitution itself → `notes`, and the mask
  engine's `skipped_length_mismatch` (a virtual silently not driven) is
  rendered on the room-effects page. Before adding a `reason=`/`note=`
  anywhere here, name the surface it reaches, or do not write it.
- **A RANGE IS AN ADDRESSING FACT, NOT A POSITION** — indices into the
  virtual's own EFFECT pixel space, read out of the segment configuration,
  the same kind of fact `virtual_ids` already was. That is the SAME space
  `fx/effects/pixelRange.py` lights during capture and
  `fx/virtual_gain_mask.py`'s mask indexes at render, so the two address the
  identical pixels with nothing to convert. The map still records where
  light LANDS and nothing else; if a change here starts storing where a
  segment IS, stop.
- **Sub-device capture AND a sub-device wave both need SPECTRA to own the
  lights** — the range lamp is a vendored effect in this process and the
  mask is applied in this process's own frame assembly, so neither reaches
  an external LedFX. Both refuse BY NAME with nothing written. Whole-device
  work is unaffected either way. Re-mapping a carrier drops its previous
  footprints first (`RoomMap.drop_carrier_footprints`), so it carries
  exactly one granularity and is never driven twice.

- **EVERY EXPECTED CONDITION ON THIS PATH IS A SENTENCE, NOT A 500**
  (2026-08-31, second commit of PR fm/rooms-picker-light-emitters). His
  first real run raised `fx_seam.RoomReleased` out of
  `room_mapping.live_virtual_ids` and reached him as a bare 500 with a
  stack trace — for a state the ownership bar fixes in one press.
  `spectra/services/mapping_refusals.py` is the one wording per condition
  (released / handover / mid-run loss / hold ceiling / a dead fixture), so
  the route, the run and the page cannot describe his room differently.
  Matched on the exception CLASS, never message text. **A genuine bug still
  raises** — a sentence invented for one would be a lie. A mid-run
  ownership loss ends the run as a stated PARTIAL (`refusal`/`partial` on
  the result) that KEEPS what it measured, and the refused revert write in
  the `finally` is swallowed so the partial cannot turn back into a 500.
  Spec: `tests/test_mapping_refusals.py`. If you add a seam to this path,
  give its expected conditions a sentence there or confirm one exists —
  the exposure lock's own named refusal is the bar.
- **THE EXPOSURE LOCK IS A HARD REFUSAL, not a warning, and it is the whole
  instrument's honesty.** A footprint is `lit − dark` in the camera's own
  byte scale and every footprint in a room is compared against every other
  one; if auto-exposure re-scales between the dark reference and the lit
  capture, every comparison is wrong by an unknown factor and NOTHING
  downstream can detect it — the grids still look like plausible
  footprints. So a run cannot start unless the browser CONFIRMED both
  exposure and white balance locked (what `getSettings()` returned, never
  what the page asked for), a lock lost mid-run aborts by name, and the
  refusal names the phone and the capability. `mapping_session.lock_refusal`
  is the ONE wording, so the run gate, the mid-run abort and the status
  surface can never disagree.
- **NO AUDIO BY CONSTRUCTION, not by a flag** (his own requirement). This is
  a SECOND session type rather than a mode on `av_sync_session.Session` —
  that class opens an `AudioReference` in its own `open()`. There is no
  audio code here to switch off; `tests/test_mapping_session.py` asserts the
  module body contains none. It DOES reuse `av_sync_session.FrameRing` and
  `ClockMap` by import (the vision seam built naming this stage as its
  consumer), and speaks the same WS message shapes.
- **Pixels are `image/grey8`, never JPEG** — a lossy codec's quantisation
  lands in the difference this instrument measures, and decoding one would
  put an image library in a path that needs none. 320x180 divides the stored
  64x36 grid exactly (5x5 box mean, no interpolation to explain).
- **A mapping run is ONE CONTINUOUS DARK HOLD for the whole capture
  sequence** on `flare_preview_hold.open_program_hold` — snapshot,
  deadline, sweep, ceiling and restart recovery all INHERITED, never a
  second hold system. The dark step covers EVERY live virtual, because
  that is what "the room is dark" means to a camera.
  **It was a CHAIN of short per-emitter holds until 2026-08-31 (PR
  fm/mapping-one-dark-hold) — do not restore that out of loyalty to its
  reasoning.** The chain existed to stay inside `MAX_HOLD_DURATION_S`
  (3 min) and did give a genuinely-restored room between emitters, but the
  owner watched a 22-emitter run and said "just stay dark between tests":
  his show flooded back through the fixtures 22 times, and every dark
  reference after the first was taken moments after a restore, so the show
  fading back out landed IN the dark frame and subtracted the next
  emitter's own light away. **That contamination path is now closed by
  construction** — between two captures the room has been dark all along,
  so `DARK_SETTLE_S` only has to outlast the PREVIOUS EMITTER's own fade,
  which is what it was always for. Restorable-at-any-instant was never the
  chain's property, it is the HOLD's (his Stop, heartbeat lapse, sweep,
  restart recovery all unchanged); what changed is that STOPPING IS HIS
  ACT. `room_mapping.py`'s module docstring is the binding statement.
  Two things ride with it:
  - **THE CEILING IS PER SESSION NOW.** `MAX_HOLD_DURATION_S` is untouched
    and still governs every preview; a session may declare its own on the
    hold's FIRST open (`open_program_hold(max_duration_s=...)`, read once,
    never raisable later), and `flare_preview_hold.session_ceiling_at()` is
    the ONE place anything reads which number a session is held to. A run's
    is `room_mapping.run_ceiling_s(estimate)` — margin ×1.5, floor 180 s
    (= the preview's own), hard cap 900 s — computed at PLAN time, carried
    on the plan response (`hold_ceiling_seconds`) beside the emitter count,
    and handed to the hold so the number he was shown is the one enforced.
    A plan past the hard cap REFUSES by name (`too_long`), never truncates,
    and **never adjusts his granularity/block_pixels to make itself fit** —
    those are his decisions and the plan line's job is to price them.
  - **ALL FOUR protocol waits are bounded per-run params** on
    `POST /rooms/{id}/map` (`dark_settle_s`/`lit_settle_s` plus
    `dark_capture_s`/`lit_capture_s`, added for the overnight speed sweep).
    At the phone's fixed ~5 fps, **lit dwell and frames-averaged are ONE
    knob, not two** — `lit_capture_s` buys frames at ~5/s and nothing else,
    with `MIN_FRAMES=2` the floor — so a sweep must not count them as
    independent variables. `run_estimate_s` is the ONE pricing function
    (the plan quotes it at the shipped defaults; the run re-prices with its
    own four values before deriving the ceiling).
- **THE PER-PIXEL GAIN MASK is `fx/virtual_gain_mask.py` + ONE multiply in
  `Virtual.assemble_frame`** (`fx/VENDOR.md` deviation #25), right after the
  two the fork already does — the layer the driver reads AND the layer the
  device preview taps. Pushed, never pulled (`fx/` may not import
  `spectra/`), and general by construction: a float array per virtual, which
  is what implode/explode will need too, not a wave-shaped thing. With no
  mask installed anywhere — a room with no sub-device emitters driven, and
  every room before this feature — `mask_for()` short-circuits on an empty
  dict and the branch is never reached: byte-identical, asserted in
  `scripts/check_room_effect_mask.py`. A wrong-length mask is SKIPPED and
  counted, never resampled. `room_effects.compute_gains` returns
  `(scalar_gains, masks)`: a masked virtual gets NO brightness write and NO
  `compose()` scaling (the mask multiplies a frame that already carries the
  show's brightness — scaling the write too would square it) and NO watchdog
  holder (nothing it moves is in the effect config). `_release_masks()` runs
  BEFORE the hold closes, same load-bearing ordering as `running = False`.
- **`per_emitter_scalar(field_fn)` is the effect interface, and it serves
  FOUR kinds from day one** (his instruction) — `gain = Σ w·field / Σ w`
  over the emitter's own footprint cells. Only Dim Wave drives lights;
  hue rotation / implode / explode exist as pure fields with tests and
  nothing that writes. **That is WHY the full 64x36 grid is stored and not
  just the axis profile**: the two radial kinds read x/y, and
  `tests/test_light_field.py` has a test that cannot pass against a 1-D map.
  A broad emitter AVERAGES the field over everything it lights — the
  softness is physics falling out of the measurement, not a smoothing hack.
- **A room effect COMPOSES, it never replaces.** `room_effects.compose()` is
  called from inside `fx_seam.apply_writes` (the one write seam) and returns
  the caller's own dict object when nothing is running, so the seam's normal
  path is byte-identical to before the feature existed. The ticker's own
  writes carry `room_effect: True` so they are never scaled twice.
  `stop()` clears `running` BEFORE closing the hold — order is load-bearing,
  or the hold's revert write would be scaled by the gain and hand the room
  back dimmed.
- **Holder 4 on the param watchdog** (`Deps.room_effect_holds`): per (virtual,
  "brightness") KEY, never a global stand-down. Today `_production_gate()`
  already skips the whole sweep while any hold is active, so this is
  belt-and-braces in production — it is proven against a deliberately-open
  gate, which is the shape a narrowed gate would take.
- **Measured, not assumed** (the plan's own named risk): one tick's whole
  seam call for two virtuals costs p50 ~11.6 ms / p95 ~15.5 ms in-process,
  at an achieved 14.99 Hz of a 15 Hz target — `scripts/check_room_effect_wave.py`
  reports it from the instrument. **Finer granularity is CHEAPER, not
  dearer**: a masked virtual needs no seam write at all, so a twenty-range
  TV wrap measures p50 ~0.01 ms / p95 ~0.02 ms and 0 writes/s against the
  same 66.7 ms tick (`scripts/check_room_effect_mask.py` §5). Twenty
  emitters also resolve into ONE mask, so the render sees one multiply
  however fine it gets.
- **The honest bound, stated rather than hidden**: a running room effect
  cannot outlive the hold's 3-minute ceiling. Right for a slice whose whole
  safety story is that seam; "leave the wave on all evening" needs its own
  lifetime story, not a bigger number.
- Sonic parity is `room_effect_console.py` (4 ops, `domain="room"`).
  Its `carrier_ids` name CARRIERS, not fixtures.
  Excluded BY NAME with reasons in its docstring: starting/stopping an
  effect (a light-driving call — `settings_agent.py`'s whole boundary
  argument is that none exists), running a mapping sync (needs a phone in
  someone's hand) and with it the GRANULARITY that run uses (an argument to
  that same act, not a setting anything reads later — how finely each device
  HAS been mapped IS reported by `list_rooms`), the axis calibration (two
  taps, a visual act — `force_scene_*`'s own precedent), creating/deleting a
  ROOM.
- Proofs: `scripts/check_light_field.py` (a fake emitter painting a known
  region must yield that region's grid, cell by cell, on top of a
  deliberately non-black dark room; ONE snapshot and ONE restore for N
  emitters, with nothing handed back mid-run — §2 was rewritten to go RED
  against the per-emitter chain it replaced; five negative controls),
  `tests/test_mapping_one_dark_hold.py` (the same bar in pytest, plus the
  run-scoped ceiling, the plan-time too-long refusal, and the stop/abandon
  paths), `scripts/check_room_effect_wave.py` (the wave on the
  REAL render pipeline through `fx.headless` — measured phase lag between
  two emitters at different axis positions matched the wave's own travel to
  0.0°, with depth-0 and speed-0 negative controls), `scripts/
  check_mapping_capture_e2e.py` (the whole session over a real uvicorn
  server and a real WebSocket), `scripts/check_light_field_granularity.py`
  (the range lamp on the real pipeline; a synthetic three-segment TV wrap
  captured at segment granularity yielding three footprints, each equal
  cell-for-cell to its own segment's painted region and pairwise DISJOINT,
  with device granularity's single merged footprint as the negative
  control), `scripts/check_room_effect_mask.py` (a vertical wave along ONE
  wrapped device, phase lag between its bottom and top pixel ranges measured
  off `assemble_frame()`, plus the depth-0/speed-0 and no-mask
  bit-identity controls). All five run as subprocesses from
  `tests/test_light_field_checks.py` — **never import one into pytest**: each
  repoints `spectra.config`'s store paths, `device_model.CATEGORIES_FILE`,
  `fx.light_ownership.OWNERSHIP_FILE` (to "spectra owns") and the `fx_seam`
  primitives, and leaking that into a shared interpreter is exactly how
  another test starts passing or failing for a reason nobody can find.

## The COMMISSIONING ground-truth test (`POST /api/rooms/{id}/commission`)

The plan's §8 (`/home/javi/fleet-spotfx/.lavish/room-light-field-plan.html`),
built 2026-08-31. Gray-code his stored `tv-mapper` composition, decode where
every pixel is, and judge a comparison **frozen in the plan before any run**.
Six things to know before touching any of it:

- **THE READ NOW HAPPENS AT 1920x1080, NOT 320x180 (2026-09-01,
  owner-approved).** Everything in the next bullet about "no pose fixes
  that at the current frame size" was TRUE OF THE OLD WIRE and is what the
  raise addressed — see "THE WIRE FRAME AND THE TWO CAMERA LEVERS" above
  for the arithmetic, the never-upscale rule and the levers. A refusal
  after the raise is a REAL pose problem, no longer an arithmetic
  impossibility.
- **ITS FIRST TWO FIELD RUNS FAILED TOTALLY, AND THE CAUSE IS RESOLUTION,
  NOT TIMING AND NOT HIS ROOM (2026-09-01, PR fm/commissioning-decode-
  failure, `docs/SPECTRA_SPEC.md` §98).** Both runs were mechanically clean
  — 22 captures, ~42 s, substitution right, room restored — and decoded 0
  of 736 with ~3,165 lit camera pixels ALL undecodable and 0 out of range.
  The raw frame kept from that pose (`data/commissioning-field-evidence/`)
  says why in one number: 66 of 57,600 camera pixels are non-zero, so his
  whole composition arrives as THREE compact glows and every pattern lands
  on the same camera pixels as its inverse and cancels. **The arithmetic
  that governs this whole instrument, and it is not a tuning knob:** gray
  bit 0 alternates in runs of TWO indices, so the camera needs about
  `gray_code.MIN_CAMERA_PX_PER_INDEX` (2) pixels per composition index
  along the imaged strip — 736 pixels need ~1,472, and the entire border
  of the 320x180 frame the phone sent BEFORE THE RAISE is ~1,000. **No
  pose could fix that at THAT frame size** — which is exactly what the
  2026-09-01 raise addressed (the read now asks for 1920x1080, ~6,000;
  see the section above). The "full-resolution ring" is still full
  relative to the 64x36 MAP GRID, not to the camera. Before proposing a cause for
  any future decode failure here, read `Decode.bit_contrast` in the run's
  own response: a mistimed stack compares two DIFFERENT patterns and keeps
  real low-bit contrast while decoding CONFIDENTLY to wrong indices
  (out-of-range > 0); an unresolvable one has zero confident bits with the
  HIGH bits near 1.0. They are opposite signatures and the response now
  carries both. The run refuses BY NAME two captures in
  (`gray_code.resolution_report` →
  `mapping_refusals.unresolvable_composition`) rather than spending the
  room's dark time, and `scripts/check_commissioning.py` §3c reproduces the
  whole field failure on demand.
- **SO IT RUNS PER FIXTURE (or per segment), NEVER THE STITCHED WHOLE
  (2026-09-01, PR fm/per-fixture-commissioning, the captain's ruling).**
  `POST /api/rooms/{id}/commission` takes `targets` — `["fixtures"]` (or
  `per_fixture: true`), `["segments"]`, or explicit `"device:<id>"` /
  `"segment:<n>"`; omitting it still commissions the whole composition, and
  on his tv-mapper that still refuses in four seconds with the arithmetic.
  `commissioning.slice_composition` is the binding statement. The
  re-addressing IS the point: a slice keeps the mapper's own segments,
  their stored numbers and their stored order, and remembers where each
  pixel sits in the whole (`global_indices`), but the gray code addresses
  0..N-1 — so one sconce is 88 pixels, 7 patterns and ~176 camera pixels
  where the stitched whole is 736, 10 patterns and ~1,472. The stored
  layout is always derived at the COMPOSITION's own size and sliced after
  (`slice_layout`); deriving it at a slice's size would fold the mapper's
  rows against the wrong pixel count and invent an arrangement. Every
  target is judged by the SAME frozen table and the set folds back into
  one table of the same five rows (`commission_compare.aggregate`): a
  field is as bad as its worst target, and a target that produced no
  decode contributes UNMEASURED to every row rather than shrinking the
  denominator to the pieces that happened to work. A target the camera
  cannot read ends that TARGET, not the run.
- **MARGINAL REFUSES, and the refusal says WHICH — the captain's words,
  "marginal is the state that produces a confident wrong answer".**
  `gray_code.RESOLUTION_SAFETY_FACTOR` (1.25) sits on top of
  MIN_CAMERA_PX_PER_INDEX, and `resolution_report` reports three states:
  `ok`, `marginal` (above Nyquist, inside the margin) and `impossible`
  (below it). BOTH refusing states refuse; `resolvable` follows
  `verdict == ok`, so every caller inherits the conservative boundary
  rather than opting in. The reason a margin is needed at all is gray
  code's own guarantee working against you: a low bit flipped by a
  fraction of a camera pixel decodes to a NEIGHBOUR, so a marginal pose
  produces a confident, plausible, WRONG arrangement rather than a visible
  failure. His ring alone (560 px, ~1,120 needed and ~1,400 to be trusted,
  against the ~1,000 the whole border of a 320x180 frame holds) is the
  case it exists to refuse. **It is not a knob for getting a run to pass**
  — lowering it does not make a marginal pose readable, only silent. The
  wire's 320x180 frame contract is deliberately UNTOUCHED; changing it
  goes back to the captain.
- **THE ROOM'S OWN LIGHT IS NOW MEASURED, AND A MOVING WINDOW REFUSES BY
  NAME (2026-09-01, PR fm/ambient-stability-gate).** His first per-fixture
  run had a WINDOW IN VIEW in daylight with cloud moving: the resolution
  gate passed honestly (5.375 camera px/index, peak 49.3), and the decode
  still came back 34 of 88 with `out_of_range_pixels=30` — §98's
  CONFIDENT-WRONG signature, which only happens when the stack compared two
  different scenes. `spectra/services/ambient_stability.py` is the binding
  statement; four things it settles:
  - **The gate never looks at the composition.** It fixes a background set
    ONCE — the dimmer half of `full - dark`, a QUANTILE not a threshold, so
    an ambient step between the two references cannot collapse it — and
    measures the SAME camera pixels in every later capture.
  - **ONLY LAMP-FREE COMPARISONS ARE GATED**, and this took a redesign:
    the PAIR delta (a pattern against its own inverse — complementary
    halves, so the fixture's spill cancels exactly, and it is also the
    quantity that lands in the bit's arithmetic) and DARK-AGAINST-DARK (a
    CLOSING dark capture, now the 23rd capture of every pass). A lamp-ON
    capture's distance from the opening dark carries the fixture's own
    spill and is reported but NEVER gated — gating it refuses a room whose
    fixture lights the walls, which is a wall, not a gate.
  - **The bound is `max(2.0 grey levels, 0.10 x peak)`** — half
    `gray_code.BIT_CONFIDENCE`, so drift alone reaches half the bar a bit
    must clear and cannot manufacture a confident wrong bit. Proven on BOTH
    sides (0.7x passes through to a judged table, 1.6x refuses), the same
    bar the marginal resolution boundary is held to.
  - **A moving change refuses EARLY (the first bad pair); a change that
    arrives and STAYS is invisible to every pair — correctly, it cancels in
    the bit too — and is caught by the closing dark.** That asymmetry is
    the design, not a gap. `gray_code.confident_wrong_signature` is the
    cheap cross-check: it CONFIRMS an ambient refusal that already stands
    on its own measurement, and when the ambient is measured STEADY and the
    signature appears anyway the frozen table's own fail stands unchanged
    with a note saying ambient is ruled out. Deferred, stated: mapping runs
    do not use it (their per-emitter pairs are a different shape).
  - **IT IS THE SAME GATE AT EVERY WIRE RUNG AND UNDER EITHER LEVER**
    (`capture_settings`, the same day): nothing is expressed in the camera
    pixels of one frame — the background set is a quantile (half the frame
    at any rung), the tile minimum is a FRACTION of a tile, and the bound is
    a fraction of a measured `peak`. What IS bounded is how many pixels a
    level is taken over (`SAMPLE_PX`, the same pixels every capture so the
    sampling error is common-mode and cancels): measured, a full-set median
    costs 1.9 ms a capture at 320x180 and 45 ms at 1920x1080 — a second of
    the event loop across a pass, in 45 ms blocks — against ~1.6 ms at every
    rung bounded. A long integration time widens every capture window, so
    **both dark references must be averaged over the SAME widened window**
    or the comparison measures the run's own settings instead of the room.
  Spec: `tests/test_ambient_stability.py` (today's cloud reproduced through
  the real decoder, the gate red on it, and a monkeypatched no-gate run
  proving the harness fails on the defect it was written for) and
  `tests/test_ambient_stability_rungs.py` (the composition with #231: every
  rung, a raised and an honestly-downgraded read through the real run, the
  widened window, and the precedence — a refused lever stops the run before
  the ambient gate has any frames to have an opinion about).
- **THE FIVE TOLERANCES ARE PRE-REGISTERED, NOT TUNING KNOBS.**
  `spectra/services/commission_compare.py` quotes the plan's table verbatim
  in its docstring and owns 0.98 / 2% / 5% / 5% / +/-15 ms. Moving one has
  left the pre-registration; the honest act is a NEW pre-registration
  published before the next run, not an edit. Four verdicts, not two:
  `pass`, `findings` (the table's own his-data outcomes — dead pixels, the
  hand-built mapper off — reported as findings, NEVER as a commissioning
  failure), `incomplete` (a row that could not be measured never passes
  silently), `fail`. Precedence fail > incomplete > findings > pass. Every
  attribution is a rule computed from the numbers, decided in advance —
  there is no judgment call at runtime, which is what makes the route
  unattended-safe.
- **TWO ROWS ARE UNMEASURABLE ON HIS ROOM TODAY, and they say so.** His
  `tv-mapper` is `mapping: copy` with `rows: 1` and no device profile: it
  stores a pixel ORDER and no geometry, so rows 3 and 4 (2-D arrangement,
  cross-device stitch) have no stored layout to fit against and report
  UNMEASURED with what would make them judgeable (a device profile with
  real rows/cols, the shape `storage/device_profiles/crystal-mapper.json`
  already uses). Deriving a rectangle from "it is wrapped around a
  television" would be precisely the plausible-looking answer this test
  exists to refuse. Row 5 is unmeasured for a different stated reason: the
  mapping tap runs at 5 fps and a 15 ms tolerance needs ~67.
- **A GATE ANCHORED ON A PERCENTILE ASSUMES HOW MUCH OF THE FRAME THE
  THING COVERS.** The decode's lit gate took its bright end from
  `percentile(full - dark, 99)` — fine for a synthetic room whose blobs
  cover the frame, meaningless for a composition covering 0.11% of it: the
  percentile landed in the read noise, the gate collapsed to "anything
  above the dark reference", and it reported 3,165 lit pixels in one run
  (averaging noise) and 0 in the next. It is now the mean of the brightest
  `gray_code.PEAK_SAMPLE` pixels plus a one-grey-level floor — the sensor's
  own quantisation, which is NOT the scene-brightness assumption the
  inverse capture exists to avoid. Watch for the same shape anywhere else a
  small bright thing is measured against a whole frame.
- **ONE CONTINUOUS HOLD per pass, where the MAP's run is a chain of short
  ones** — different acts, not a change of mind: a map's emitters are
  independent measurements; a gray-code STACK is ONE measurement against
  one dark and one full reference, so the room coming back to life halfway
  through would put the show's own light into the middle of it. ~35 s,
  inside the hold's own 3-minute ceiling.

Everything else is reused rather than rebuilt: the mapping session (frames,
exposure lock, refusals — plus a full-resolution ring it turns on for the
run and off in a `finally`, because 736 pixels cannot be resolved by 2304
map-grid cells), `flare_preview_hold.open_program_hold`, the copy-carrier
substitution, `activate_for_capture`/`deactivate_after_capture`,
`fixture_brightness.owned`, and `mapping_refusals`. The lamp is
`fx/effects/pixelPattern.py` (`fx/VENDOR.md` #28, registry-exempt); all the
gray-code arithmetic is `spectra/services/gray_code.py`, pure, so the lamp
and the decoder cannot drift into two ideas of which pixel is which.
Proofs: `scripts/check_commissioning.py` (real render pipeline for the
lamp, then a declared arrangement recovered end to end, then SABOTAGE —
each corrupted stack failing its own row with the table's own attribution;
§7 is the per-target half, including the marginal boundary proven on both
sides against a box-integrating camera whose reported
`camera_px_per_index` IS the number under test),
`tests/test_commissioning.py`, `tests/test_commissioning_per_fixture.py`,
`tests/test_gray_code.py`.

## THE WIRE FRAME AND THE FOUR PINNED CAMERA LEVERS (`capture_settings.py`)

**`spectra/services/capture_settings.py` is the binding statement** — the
ladder of declared frame sizes, the arithmetic that chose them, the four
pinned levers (`LEVER_BOUNDS`: integration time, gain, white balance
temperature, focus — the last two added 2026-09-01, NATIVE CLIENT ONLY,
since the browser can reach neither), and the frame-rate coupling. Read it
before touching anything that sends, sizes or exposes a capture frame. Six
things:

- **THE WIRE FRAME IS PER RUN, NOT ONE NUMBER (2026-09-01, owner-approved:
  "raise video frame size and tweak whatever settings help").** A MAP still
  sends 320x180 — a footprint is a 64x36 grid and more pixels buy nothing,
  so night runs stay cheap. The COMMISSIONING read asks for **1920x1080**,
  by arithmetic and not by picking the maximum: a decode needs ~2 camera px
  per composition index, so his 736 need ~1,472 of imaged strip (~1,840
  with the safety factor), and a strip wrapped round a screen images as a
  PERIMETER — the whole perimeter of a 320x180 frame is 2x(320+180)=**1,000**,
  so **no pose could ever have worked**. `commission_profile_for()` derives
  the rung (smallest clearing 736 with 2x pose margin at a 77%-fill pose);
  1920x1080 carries ~1,848. **THE STORED 64x36 MAP GRID IS UNCHANGED** —
  every rung is 16:9 and an exact whole multiple of it (5x/10x/15x/20x/30x),
  so `light_field.downsample` stays a box mean and a grid from a 1080p frame
  is directly comparable with one from 320x180. **grey8, uncompressed, at
  every rung** — a lossy stage's noise lands inside the measured difference.
- **A CLIENT NEVER UPSCALES, and the server asserts it independently.**
  `capture_settings.choose` picks the largest rung no bigger than BOTH the
  request and the camera's own image; every frame carries `source_width`/
  `source_height`; a frame bigger than its source is dropped and NAMED
  (`mapping_refusals.upscaled_frame`). Interpolated pixels would inflate
  `gray_code.resolution_report`'s camera-pixel count and let an unreadable
  target report that it is readable — the MARGINAL confident-wrong-answer
  through a side door. A camera that tops out at 720p **still runs**, at
  720p, and the run says which rung it got (an honest downgrade is a
  RESULT, never a refusal).
- **THE TWO LEVERS ARE PER-RUN AND DEFAULT TO TODAY'S BEHAVIOUR.**
  `exposure_time` is in **100-MICROSECOND UNITS on both paths** (V4L2
  `exposure_time_absolute`, W3C `exposureTime`) so **nothing converts**;
  `gain` is the device's own scale (V4L2 `gain` / the browser's `iso`),
  passed through verbatim — converting it would be an invention. Asking for
  neither is converge-then-freeze exactly as before. **Both are READ BACK
  from the device**, and a lever the camera did not take refuses BY NAME
  before any light (`manual_camera_unavailable`) — measuring under whatever
  the camera chose while reporting the asked-for numbers is the one thing
  this path must never do.
- **A LONG INTEGRATION TIME IS NOT FREE, and it is not silent.** A sensor
  integrating for E seconds gives at most 1/E fps, and a capture averages
  whatever ARRIVED in its window — so `room_mapping.capture_windows` /
  `commissioning.capture_window` widen the CAPTURE windows to still buy
  `MIN_FRAMES`, `run_estimate_s` prices the widened run, and an exposure no
  legal window can average refuses by name (`exposure_too_long`). **With no
  manual exposure asked for both are an EXACT pass-through** — the shipped
  protocol, byte for byte.
- **`capture_settings.CameraNegotiation` IS THE ONE IMPLEMENTATION**, and
  `MappingSession` plus **every test double** (`SessionCameraDouble`)
  inherits it. Seven fake sessions live across `tests/` and `scripts/`; a
  gate they MODEL is a gate no proof exercises — the founding defect of
  this whole area was a hold that reported itself set while the show fired
  underneath. Add a session capability there, not in seven places.
- **THE EXPOSURE COMPARISON** (`spectra/services/exposure_test.py`,
  `POST /api/rooms/{id}/exposure-test`, the Rooms page's own panel) answers
  "is it the room, or the camera settings?": one emitter, one pose, two
  regimes back to back, `better`/`ratio`/`summary`. It **stores nothing**
  (throwaway room copy, no `save_room`) and puts the camera back in a
  `finally`. The two weights are deliberately on different byte scales —
  each is `lit - dark` WITHIN its own regime, so both are honest about how
  much signal that regime produced and **neither is comparable with any
  other footprint in the room**; the summary says so. A default regime that
  saw NOTHING is a RESULT, not a failure.

- **THE LEVERS TRAVEL THROUGH THE QUEUE, AND THE NIGHT PRICES THEM.**
  `QueueItem` carries `exposure_time`/`gain` because its own contract is
  "the SAME arguments the route takes" and both run routes take them — an
  unattended run must not be the one place his camera cannot be told what to
  do. And `night_run.price_items` prices a map item at the windows
  `capture_windows` will WIDEN it to, not the ones it declared: a long
  integration genuinely takes longer, and pricing the declared windows would
  price short against the 05:30 planned-end bound, which is the one bound
  that must not be over-run. Both were found composing #230 and #231 at the
  same choke points; `tests/test_camera_levers_and_night.py` is the proof
  that neither build swallowed the other.

**KNOWN, OPEN, NOT FIXED BY THE RAISE:** `gray_code.resolution_report`
counts lit **AREA**, so a strip thick enough for its LEDs' images to
overlap sideways reports more camera pixels per index than it linearly
resolves — measured at 5.7 where the perimeter supports ~1.4
(`scripts/check_commissioning.py` §3d prints it). The gate can therefore
pass a pose that decodes to NEIGHBOURS. His own field frames were thin
glows so the gate was right about them. Measuring linear extent from the
reference pair alone is separate work; inventing a boundary for it in
passing is exactly what a pre-registered instrument must not do.

Proofs: `scripts/check_commissioning.py` §3d (his own composition at a
77%-fill pose — 320x180 decodes CONFIDENTLY WRONG at ~0.76 LED spacings,
1920x1080 lands at 0.12, and accuracy rather than a count is what is
asserted), `tests/test_capture_settings.py`, `tests/test_camera_levers_in_runs.py`
(the runs actually negotiate and actually restore), `tests/test_exposure_test.py`,
`scripts/check_capture_queue_e2e.py` §5 (the negotiation over the REAL
client, WebSocket and server), `tests/test_camera_levers_and_night.py` (this
build and the night run composing). Help: `camera-settings`,
`exposure-comparison`.

## "THE SETTING IS NOT THE LIGHT" — the lever self-test (`lever_selftest.py`)

**`spectra/services/lever_selftest.py` is the binding statement.** Read it
before touching anything that decides whether a camera can be trusted.

THE EVENING IT EXISTS FOR (2026-09-01): the browser path commanded three
integration times — 10 ms, 60 ms, 200 ms, a factor of twenty end to end —
every one was accepted, every read-back agreed, and the measured light did
not move (footprint weights 0.0, 0.0014, 0.0051 against
`light_field.UNSEEN_WEIGHT` = 1.0), while the camera's own converged regime
wandered 0.23 -> 0.01 between two runs of the same thing. **A read-back
proves the DRIVER holds a value. It cannot prove the SENSOR obeys it.** The
two checks both run and neither substitutes for the other. Six things:

- **THREE CAPTURES, and the order is the design**: A (dim), B (= A x
  `COMMANDED_FACTOR`), B' (the SAME command again). A->B answers "does more
  commanded time put more light in the frame"; B->B' answers "does this
  camera hold still when nothing was asked to change". The repeat is at the
  BRIGHT regime because a ratio between two near-noise readings measures
  nothing.
- **SIGNAL IS CHECKED BEFORE RESPONSE, and that ordering IS the fix.**
  His three real weights are proportional to two significant figures and
  every one of them is noise — a response check run first would have
  PASSED them. So the bright regime must clear `UNSEEN_WEIGHT` before any
  ratio is quoted, and the no-signal wording names the honest ambiguity (a
  pose that sees nothing and a dead lever look identical, and neither can
  be calibrated through).
- **The measurement is the MAP'S OWN** — `room_mapping._map_one` against a
  throwaway room with no `save_room`, `exposure_test.py`'s own precedent.
  Never a second idea of "how much light".
- **`unprovable`/`unproven` NEVER REFUSE** (`mapping_refusals.
  LEVER_REFUSING` is the list of the four that do, and every one of them is
  a MEASUREMENT). "We could not check" is not "we checked and it is
  broken" — the same distinction `night_exit` draws between DARK and
  UNKNOWN and `witness` between contaminated and witness_unavailable.
  Refusing on a check that could not be made would invent a fault.
- **WIRED AT `capture_runs`, the one seam**, before a map / commissioning
  pass / exposure comparison whose session is the NATIVE client, inside
  the run lock (it drives a light, so it takes the same held room and the
  same camera every capture takes — it acquires nothing new). **The verdict
  is cached ON THE SESSION OBJECT**, which is what makes "at establishment,
  and after any reconnect" structural rather than remembered:
  `mapping_session.open_session` builds a NEW session per WebSocket, so a
  reconnect cannot inherit one, and the fingerprint carries the pose id so
  a camera reopen inside one connection cannot either.
- **BROWSER SESSIONS ARE NEVER SELF-TESTED** — and since the demotion (see
  "THE BROWSER IS A VIEWFINDER" below) that is because a calibration-grade
  run on one is refused EARLIER and for the broader reason: a browser cannot
  pin the camera at all, so there is nothing here to measure. The order
  matters — a browser failing THIS test would say "your camera is not
  obeying its exposure control", which is true of the browser and would send
  him to look at the camera. `capture_runs.session_view()['native']` is
  still the tell.

**PERSISTENCE IS SOFTWARE, on the other half of this.** Whatever a session
pins is re-asserted by `camera.open()` (a reboot, a re-plug, a dead capture
pipe, a scaler restart) and by the client at every reconnect
(`session._reassert`, counted in `state.reasserts`), then READ BACK.
Nothing is written to disk and nothing about the camera's own memory is
relied on. A `config` message naming one lever does not un-pin the others;
un-pinning is saying so explicitly (`null`).

Proofs: `tests/test_lever_selftest.py` (the pure judgement red/green/drift,
the whole run, and a test that goes RED on the defect it was written for —
with the preflight removed, tonight's camera runs a whole map and reports a
ROOM-shaped failure, sending him to move a camera that was standing in
exactly the right place), `tests/test_camera_pinned_settings.py` (four
controls written, read back, and each one's stuck-driver refusal), and
`scripts/check_lever_selftest.py` — both directions over a real server, a
real WebSocket, the REAL capture client and the real map route, run from
`tests/test_light_field_checks.py`.

### A STAMP IS NOT A PHOTON — the stale-stream defect (2026-09-02)

The self-test above met a REAL camera for the first time and refused his
laptop with readings that made no sense: commanded 500 x100 us measured
0.000; commanded 2000 measured 444.282; commanded 2000 AGAIN measured
0.043 — two IDENTICAL commands ten-thousand-fold apart, with every driver
read-back holding Manual throughout. **Nothing was wrong with the lever and
nothing was wrong with the judgement. The frames were OLD.**
`spectra/capture_client/camera.py`'s "FRESH FRAMES" block is the binding
statement. Five things, and the first three generalize well past cameras:

- **A TRANSPORT THAT QUEUES WHOLE FRAMES BREAKS A `lit - dark` INSTRUMENT
  SILENTLY, and no server-side window can see it.** The client reads pixels
  out of an ffmpeg pipe; MEASURED in the exact construction `_open_at`
  builds (OS pipe + `StreamReader(limit=frame*8)`), that path holds up to
  **19 whole 320x180 frames — 3.8 s at 5 fps — and it SATURATES there**. It
  fills the first time the client stops reading for a moment (`open()`
  sleeps `SETTLE_BEFORE_LOCK_S` then runs `apply_lock`; `apply_lock` and
  the paced `read_lock` are BLOCKING `v4l2-ctl` subprocesses on the event
  loop) and is never given back, because the frame loop paces itself at
  exactly the camera's own rate. 3.8 s is longer than a whole capture phase
  (settle 0.7 + window 1.5), so a LIT window lands entirely on frames whose
  photons predate the lamp — and a slightly shallower queue catches it in
  full. That is not noise between two readings; it is the two sides of one
  boundary.
- **A CAPTURE STAMP IS HONEST ABOUT ITSELF AND SAYS NOTHING ABOUT THE
  WORLD.** `captured_at_ms` is stamped when the client READ the frame out
  of its transport. `MappingSession.gather` windows correctly against that
  stamp through the paired clock, and its floor is already the phase's own
  write plus settle — **a second `not_before` floor was considered and is
  decoration; the docstring says so, so it is not re-added.** The whole
  defect lives in the gap between the stamp and the photons, which only the
  client can close.
- **TWO LAGS, TWO FIXES, and each is proven with the other turned off.**
  TRANSPORT: `camera.newest_of` — a frame is returned only when nothing
  newer is already waiting (`DRAIN_PROBE_S` 20 ms, an order of magnitude
  above the ~1 ms an already-buffered frame costs and below a 30 fps frame
  period). Draining the measured 19-frame saturation costs **23 ms**, so
  freshness is free. SENSOR: `camera.SENSOR_APPLY_FRAMES` (3) discarded
  after a control actually MOVES — the frame in flight and the frame
  already integrating were exposed under the old regime, and no drain can
  reach those; the server states the same bound independently as
  `capture_settings.regime_settle_s`, paid ONCE per commanded regime, so an
  ordinary map (whose exposure never moves mid-run) pays nothing. Without
  it a reading's DARK REFERENCE straddles the change and is subtracted from
  a lit capture taken in a different regime.
- **THE SYNTHETIC CAMERA IS FRESH BY CONSTRUCTION, WHICH IS WHY NOTHING
  CAUGHT THIS.** `SyntheticCamera` is a function: no transport, no queue, a
  control change visible in the very next frame. Every proof of this path
  used it. **Any rig that must speak about timing has to model the queue**
  — `tests/test_stream_freshness.py` does, and drives the REAL
  `run_selftest`/`_map_one`/`light_field`/`judge` through it, swept across
  the whole measured band rather than sampled at one depth.
- **A CLIENT DECLARES FRESHNESS AND THE THREE ANSWERS ARE NOT TWO.**
  `hello.fresh_frames` -> `capture_source.serves_fresh_frames`: True,
  False, or **None for a build that did not say** (and a browser, which
  cannot). Nothing REFUSES on it — it is a build's silence, not a
  measurement — but a lever verdict whose readings disagree carries
  `mapping_refusals.STALE_STREAM_FIRST_CHECK` as the NAMED FIRST CHECK, the
  `SCONCE_MAINS_FIRST_CHECK` discipline: two identical commands orders
  apart is what a queued transport looks like, and sending someone to look
  at a working camera instead is the hour that sentence exists to save.

**THE FIX IS CLIENT-SIDE AND SERVER-SIDE, so `spectra.service` must be
deployed for `regime_settle_s`/the freshness note, and the camera host must
pull for the drain.** Until it pulls, its readings are refused-or-noted,
never silently trusted. Proofs: `tests/test_stream_freshness.py` (the
judgement, modelled transport, red and green, swept) and
`scripts/check_stream_freshness.py` (the transport MEASURED against a real
subprocess pipe, the real `V4L2Camera.frame()` beside the read it replaced,
and the whole thing over a real server, WebSocket and capture client —
0.15 s from capture to stamp where the shipped read served 2.2 s of queued
frames).

## THE BROWSER IS A VIEWFINDER — a calibration-grade run refuses it BY NAME

**`spectra/services/capture_source.py` is the binding statement** for which
client may source a measurement; `mapping_refusals.browser_not_calibration_
grade` owns the sentence. Read both before touching anything that decides
who is holding the camera. Six things:

- **THE GATE IS ONE `if`, AT THE ONE SEAM.** `capture_runs._gate` refuses a
  browser-established session for any `kind in CALIBRATION_GRADE` (map,
  commissioning, exposure comparison, pose fingerprint), before the room is
  asked for, `refusal="browser_session"`. The button, the unattended queue
  and a calibration re-running itself are callers of equal standing through
  that function, so all three inherit it and none can be the one that
  forgot. **Do not add a second copy of this decision anywhere** — that is
  what `capture_source.calibration_grade` exists to prevent, and it is the
  one line that changes the day a second client kind can hold a camera
  honestly.
- **THE DEMOTED THING IS THE BROWSER'S STANDING, NOT THE TRANSPORT.** The
  native client speaks the SAME `mapping_session` protocol, so none of that
  machinery moved or forked. A browser still connects, streams frames,
  reports its lock and serves the preview — and AIMING stays first-class,
  because pointing a camera does not care whether the sensor obeys its
  exposure control. `tests/test_browser_demotion.py` proves the aiming path
  end to end on the real session and the real routes, and would go red if
  "demote" had been built as "refuse".
- **NEVER A DEAD BUTTON.** The Rooms page keeps every run control and
  executes them against whatever NATIVE session is established (he presses
  it here, that machine measures it), so the buttons are enabled whenever
  ANY camera holds the room. A press with only a browser present comes back
  with the sentence and the one next step. `session_view()` carries
  `source`/`calibration_grade`/`calibration_refusal`/`measured_by`/`aiming`
  — the refusal text arrives from the SAME function the gate calls, so the
  page cannot promise what the gate will not honour.
- **THREE ANSWERS THAT CAN DISAGREE, and collapsing them lies**: `refusal`
  is why the CAMERA is not trusted (the exposure lock), `calibration_refusal`
  is why this CLIENT may not measure (this), and `measured_by` names whose
  camera a run would use. A browser session is present, locked, healthy AND
  unable to run a single item — that is not a broken session.
- **`PREFLIGHT_REFUSALS`** (`capture_runs`) is the set every route answers
  409-with-the-sentence to. Add a pre-light gate at the seam and add its word
  there, or it reaches him as a 200 with an empty result.
- **`SessionCameraDouble` DECLARES ITSELF NATIVE** (`capture_settings`), one
  place for the seven fakes — a spec about a RUN must not refuse for a
  reason it is not about. A spec about the browser sets `hello =
  {"user_agent": ...}` explicitly, which is how the gate gets exercised
  rather than modelled. A session that says nothing is NEVER native.

`capture_queue.wait_for_session` waits for present + locked + CALIBRATION-
GRADE, and at the deadline reports the browser's own sentence rather than
`NO_SESSION` — a queue log saying "no capture session" would send a reader
to look for a machine that was plugged in the whole time.

**This closes the fourth of his 2026-09-01 failures** (a cached tab silently
running old capture code) with no machinery of its own: calibration cannot
ride stale browser code because it cannot ride the browser at all. Help:
`browser-is-a-viewfinder`, linked from the Rooms page and the unattended
card. Spec: `tests/test_browser_demotion.py`.

## THE CALIBRATION RECORD, and the POSE FINGERPRINT that gates it

A calibration stops being a ritual and becomes a durable, named,
re-runnable artefact — step two of `/home/javi/fleet-spotfx/data/
calibration-practice-plan/plan.md` §3. **`spectra/models/calibration.py` is
the binding statement for what a calibration IS; `spectra/services/
pose_fingerprint.py` is the binding statement for what the pose check can
and cannot tell apart.** Read both before touching anything here. Five
things:

- **STORAGE IS A DIRECTORY, not a bounded file** — `storage/spectra/
  calibrations/<id>.json`, one file per calibration (`calibration_store.py`,
  atomic tmp+replace, `config.CALIBRATIONS_DIR`, repointed by
  `tests/conftest.py`'s `_isolated_calibrations`). Every other store here
  holds a HISTORY that ages out and a bound is right for it; a calibration's
  LINEAGE is the one thing that must never be pruned, so a single-file store
  would have to choose between capping it and growing unbounded in a file
  every read parses whole.
- **THE TAG REGISTRY IS STORAGE ONLY, and its one number is MEASURED.**
  `Calibration.tags` (`TagRegistration`: ArUco `tag_id`, `measured_side_mm`,
  `mount`) is empty by default, so its arrival changed nothing. **Nothing in
  this build reads it and there is no tag-detection code anywhere here** —
  it is carried from day one so the later vision step lands into a record
  that already holds his measured truth instead of going back to ask for it
  (`tests/test_calibration_record.py` asserts against the SOURCE that
  `pose_fingerprint`/`calibration_runs` never name it, so the day it starts
  being read is a deliberate edit rather than something that quietly became
  true). **MEASURED, never nominal, and that is the whole point**: a printed
  tag whose real side differs from its nominal one SILENTLY SCALES every
  pose it anchors — a driver told "100 mm" when it is 97 reports a camera 3%
  further away and every distance from it is wrong by that factor with
  nothing to notice, the firmware-brightness failure arriving through
  another door. So one physical tag has one size: a non-positive side is
  refused at the model and a duplicate id is refused by name at the route.
  **An ArUco id is only unique WITHIN a dictionary** and the dictionary is
  deliberately NOT invented here — named in `TagRegistration`'s docstring as
  an open question for whoever knows which one he printed, not left as an
  oversight.
- **RUNS GO THROUGH `capture_runs` — the one seam — and acquire nothing.**
  `calibration_runs.run_calibration` checks the pose, then drives the
  declared items through `capture_queue.run_queue`, so the exposure lock,
  the lever self-test, the ambient gate, the witness, the hold ceiling and
  the ownership boundary all apply exactly as they do to a button press.
  `capture_runs.KIND_FINGERPRINT` is a FOURTH run kind and is
  calibration-grade like the other three. **The declared items are validated
  by `capture_queue.parse_items` — the ONE validator**; a second dialect
  that read almost the same would be the drift this codebase keeps learning
  about. **THE NEVER-TAKES-HIS-ROOM BOUNDARY IS UNMOVED** and no piece of
  the design needed an exception to it.
- **THE FINGERPRINT IS ANCHORED ON WHAT CAMERA GEOMETRY ALONE DETERMINES** —
  where a handful of KNOWN FIXTURES land their own light in the frame,
  measured by briefly driving them through `room_mapping._map_one` against a
  throwaway room (the `lever_selftest`/`exposure_test` precedent: nothing
  stored). **Deliberately NOT the ambient scene**, which is the room's to
  change: a fingerprint made of a reference image fires on a moved chair,
  which is the exact failure this exists to avoid. A camera move shifts
  every fixture's image by one vector; a room change moves one and leaves
  the rest put. That asymmetry is the whole discriminator.
- **FOUR VERDICTS, AND EXACTLY ONE REFUSES.**
  `mapping_refusals.POSE_REFUSING` is `(POSE_CAMERA_MOVED,)` — the plan
  requires a moved camera be a named refusal rather than silently
  incomparable data. **`POSE_ROOM_CHANGED` and `POSE_CANNOT_TELL` RUN**, on
  the captain's binding requirement: "he rearranges his own house; a
  calibration refusing because he moved a chair is a system that expires for
  reasons he cannot see." What is withheld in those two cases is the
  COMPARABILITY CLAIM (`CalibrationRun.comparable`), gated on the
  fingerprint matching AND the pinned regime being identical — two
  independent halves that fail for different reasons and are reported
  separately. An explicit press still wins past a camera move and NAMES it
  (`overrode_camera_moved`, the Force Scene precedent) and never re-anchors
  the pose as a side effect.
- **THE SIX TOLERANCES ARE PRE-REGISTERED** (`commission_compare.py`'s own
  discipline): each is DERIVED from something the instrument already
  measures — `CENTROID_TOLERANCE` is two of the 64-wide grid's cells and is
  proven above the instrument's own repeat wobble (measured at ~11% of it)
  rather than asserted. Moving one is a decision about what this instrument
  claims, not a tweak. **`COHERENCE_FRACTION` is a FRACTION of the shared
  shift and not a fixed band, and that was FOUND BY SWEEPING**
  (`scripts/check_pose_fingerprint.py` §1, which is in the suite via
  `tests/test_light_field_checks.py`): a big camera move pushes anchors near
  the frame edge partly out of shot, so their centroids shift LESS than the
  ones in the middle, and judged against a fixed band the most obvious
  camera move there is fell to `cannot_tell` while a small one was named.
  Sweep a boundary before trusting it here; sampling it once passes.

**THE HONEST LIMITS, stated rather than hidden, and every one of them falls
to "cannot tell" and never to a confident wrong answer:** a camera
TRANSLATION produces parallax (near fixtures shift more than far ones), so
it has no shared vector and reads `cannot_tell`; an anchor set that is too
few (`MIN_DISCRIMINATING` = 3) or too clustered (`MIN_ANCHOR_SPREAD`) cannot
discriminate at all and **SAYS SO AT ESTABLISHMENT**, so the weaker answer
months later is a known property of the pose rather than a surprise; and a
whole-frame brightness change (his firmware-brightness trap, one axis over)
is deliberately not attributed to either. The fingerprint takes each fixture
to full firmware brightness for the pass (`fixture_brightness.owned`,
`run_mapping`'s own guard) precisely because that class of change would
otherwise make every re-check unreadable.

**PROVENANCE IS A READ, NEVER A COPY.** A run records the emitter ids it
produced; the footprints stay in `room_maps.json`, which remains the live
store. `calibration_store.provenance` resolves them against it AS IT IS NOW
— `present` / `superseded` / `missing` — so a calibration pointing at
footprints that no longer exist REPORTS that rather than implying they are
there. **ABSENCE IS A READ** too: a calibration that never ran says so, and
so does a pose that was never taken. The LINEAGE is append-only —
`Calibration.append_run` is the only mutator and there is no counterpart,
and `POST/GET/PUT` are the only routes (**there is deliberately no
DELETE**). A REFUSED run is an entry, `night_run`'s declined-night precedent.

**NOT BUILT HERE, by design:** night-seam integration (step four), the
browser demotion (step six), and any UI, which is why there is no help
topic: an unlinked topic is an orphan by this file's own rule. Spec:
`docs/SPECTRA_SPEC.md` §102; tests `tests/test_pose_fingerprint.py`,
`tests/test_calibration_record.py`, `tests/test_calibration_api.py`.

### AMENDING ONE FIXTURE without spending the evening

Step three (`plan.md` §4, `docs/SPECTRA_SPEC.md` §103).
**`spectra/services/amendment.py`'s module docstring is the binding
statement for when a partly re-measured carrier is honest** — read it before
touching anything that scopes a capture run or replaces a footprint. Six
things:

- **AN AMENDMENT IS AN ORDINARY RUN OF A SMALLER DECLARATION.**
  `calibration_runs.run_amendment` / `POST /api/calibrations/{id}/amend`
  names DECLARED items by his own labels (`GET` publishes them as
  `item_names`) and shares ONE body — `_run_declared` — with
  `run_calibration`, so a gate added there is added to both. Overrides
  (`amendment.OVERRIDABLE`) change CAPTURE parameters for that run only;
  changing `kind` or `room_id` is an EDIT, refused here. A name this
  calibration does not declare is refused BY NAME, never skipped.
- **SUPERSESSION IS PER EMITTER.** `room_mapping.scope_plan` narrows a
  resolved plan (`carrier_ids` / `emitter_ids`, both threaded through
  `capture_runs.run_map` and `capture_queue.QueueItem`, both defaulting to
  None = the whole room and byte-identical to before). A carrier only PARTLY
  re-measured is no longer dropped wholesale; `put_footprint` replaces
  exactly the amended ids and the siblings keep the run that took them.
  A CARRIER-SCOPED item still re-takes its carrier WHOLE, which is what lets
  an amendment change a carrier's granularity without stranding the old
  shape beside the new one.
- **THE GATE, and it is the whole point:** two readings of one carrier may
  sit side by side only when the pose fingerprint **MATCHED** and the pinned
  regime is **IDENTICAL** to the run that took the kept ones. Stricter than
  what stops a full run, deliberately — a full run replaces the whole
  carrier so only its claim against earlier runs is withheld, where a mixed
  carrier's inconsistency is INSIDE its own footprints and nothing
  downstream could notice. Either half failing refuses by name with nothing
  driven, naming the two ways out (`whole_carrier`, or re-anchor the pose).
  **There is deliberately no force flag for it** — `force` runs past a
  measured camera move exactly as for a full run and never past this.
  UNKNOWN PROVENANCE fails it too (a carrier mapped from the Rooms page
  button carries no pose or regime this record knows). When it passes,
  mixing is still never silent (`mixed_carriers` + `amendment_mixed_note`).
- **TWO GRANULARITIES ON ONE CARRIER ARE REFUSED** one level down
  (`amendment_granularity_conflict`) — `RoomMap.drop_carrier_footprints`'
  own invariant: driving both would dim that fixture twice.
- **THE DECLARATION IS APPEND-ONLY TOO.** A `declaration` entry carries the
  WHOLE PRIOR DECLARATION (`CalibrationRun.previous_declaration`, built by
  `calibration.declaration_snapshot` BEFORE the edit): the change sentences
  say what moved and could never rebuild what was there. An edit still
  touches no measurement.
- **THE DIFF** (`spectra/services/calibration_diff.py`,
  `GET /api/calibrations/{id}/diff`) reads THE LINEAGE, not the room map —
  which is why `ItemOutcomeRecord.measurements` exists: the map holds only
  the LATEST footprint, so a diff against it could compare the newest
  reading only with itself. `NOISE_FRACTION` **IS** `exposure_test.
  TIE_FRACTION` (one instrument, one idea of its own noise) and is
  pre-registered, not tuned. It never treats absence as a change and never
  claims a comparison the record does not support.

- **A CUT-SHORT AMENDMENT APPLIES NOTHING** (Admiral's ruling, 2026-09-01,
  §104). What it measured is KEPT in the lineage; the room map is PUT BACK
  exactly as it was (`amendment.Rollback`, `calibration_runs.
  _land_unapplied`, `CalibrationRun.applied=False`). His reason: a partial
  that applies itself leaves his lighting neither the old calibration nor
  the new one but a mixture **assembled by where the clock fell**. It is a
  ROLLBACK on the ONE store (footprints are written per emitter as they are
  measured, so there is no unwritten moment to withhold), it applies to
  EVERY partial amendment day or night, and **a cut-short FULL RUN is
  unchanged and still keeps its partials** — a full run makes no
  kept/taking split claim. `emitter_origin` skips an unapplied entry and
  provenance reports its emitters `unapplied`, never superseded/missing.

**`RUN_KINDS` (`spectra/models/calibration.py`) is a constant for a
reason**: an amendment produces footprints exactly as a run does, so every
provenance/origin/comparability read uses it — a reader still testing
`kind == "run"` reports his newest measurement as belonging to nobody.

Spec: `docs/SPECTRA_SPEC.md` §103; tests
`tests/test_calibration_amendment.py` (both directions, plus a test that
goes RED on the defect it was written for) and
`tests/test_calibration_diff.py`.

## THE NIGHT RUN — HA pushes, we answer (and, ARMED, it takes the room)

His `Sleeping` helper is a better signal than a person: when it has been on
for thirty continuous minutes Home Assistant PUSHES one event and the
declared capture queue works through the night. `spectra/services/
night_run.py`'s module docstring is the binding statement; the seam contract
both captains agreed is `/home/javi/fleet-seam/river-dj-night-run-seam.md`.
`POST /api/night-run/{start,abort}` (Bearer, `SPECTRA_NIGHT_RUN_TOKEN`, read
at request time, absent-or-wrong is the same 401), `GET /api/night-run/
{would-start,fixtures,morning}` (open reads), `GET/PUT /api/night-run/queue`
(the declaration). **NO POLLING anywhere on our side, on any cadence** — he
pushes, we answer reads. Eight things, and each one has cost something
already:

- **ASK FIRST, PREPARE ONLY ON YES — `GET /api/night-run/would-start`,
  and THE ONE-PREDICATE GUARANTEE IS THE POINT OF IT** (2026-09-02, the
  seam's addenda 7-9). His house PREPARES before it starts a night (River
  fires the "Dark Music" envelope, then pushes start), so on 2026-09-01 the
  envelope fired, the start declined by name — no declared queue, the
  DESIGNED outcome — and his house sat lit while he slept. The preflight is
  a PURE READ (open, like every other read here; no writes, no state, no
  room touched) answering the exact three gates a start applies: owned?
  declared-and-parses? prices inside the 05:30 bound? — plus the two
  already-running gates. `{"would_start": true, ...}` or `{"would_start":
  false, "reason": <the start's OWN sentence>, "code": <not_owned |
  no_declared_queue | already_running | will_not_fit, or a calibration
  declaration's own refusal kind>}`, and the planned end / priced seconds /
  window ride along because the pricing already computed them.
  **`night_run.evaluate_start` IS THE ONE GATE CHAIN — `start()` calls it
  too, and neither caller keeps a gate of its own.** A preflight with its
  own copy would be worse than none: a confident wrong answer at 1am with
  nobody awake. `tests/test_night_would_start.py` holds that structurally
  (a sentinel proving both callers route through the one function, a
  yes-under-a-hostile-world proving neither kept a private veto, and a
  callgraph check that no gate NAME appears in either caller's body) and
  BOTH halves were verified RED against a re-introduced second
  implementation. The staleness window is NAMED, not closed: a yes can go
  stale, and closing that would mean reserving something — preparation
  before confirmation in disguise. Safety does not rest on the yes; River
  snapshots before preparing and restores on any start answer that is not
  `state == "running"`.

- **THE BOUNDARY: a start arriving while SPECTRA does not ALREADY hold the
  room DECLINES by name, records the declined night, and does nothing
  else.** The Admiral's word at the time — "it does not help itself to his
  room while he sleeps. That boundary is worth more than an occasional
  missed night." **HE HAS SINCE OVERRULED IT** for a RELEASED room behind
  one absent-by-default lever — see THE SELF-TAKING NIGHT below; everything
  in this bullet is still exactly what an UNARMED deploy does, and that is
  every deploy until he words the arm. The ownership record is read FIRST, before
  anything is resolved or driven, so a declined night cannot have had a side
  effect. A DECLINE IS A NORMAL RECORDED OUTCOME (200, not 4xx): "did last
  night run?" must be a read, never a silence indistinguishable from the
  seam being broken.
- **THE HARD PLANNED END IS 05:30 HOUSE TIME** (`HOUSE_TZ`,
  America/New_York, via `zoneinfo` — never a fixed number of seconds added
  to a timestamp). His HA morning routine runs the flag then and THE BLINDS
  OPEN ~05:40: daylight in the frame is a capture CONTAMINANT, so this is a
  bound, not a preference. The declared queue is PRICED at start
  (`price_items`) and refused by name if it cannot fit; the bound is then
  re-checked BEFORE EVERY ITEM through `capture_queue.run_queue`'s new
  `guard` seam (default `None`, so every existing caller is unchanged) —
  a queue that fitted at 01:00 has not necessarily got room for item six at
  05:28. A commissioning item is priced at `commissioning.NOMINAL_PASS_S`,
  a NAMED nominal used for this bound ONLY and never for the hold ceiling.
- **`morning-routine` is an ORDINARY ENDING, not an abort.** All three stop
  events (`sleep-ended`, `light-touched`, `morning-routine`) arrive at the
  one `/abort` endpoint and do the same three things to the room; the
  morning one records `ended_by_morning`. Folding it into `aborted` would
  make every ordinary night read as an incident, which is how a record stops
  being read.
- **ABORT IS THREE PIECES OF EXISTING MACHINERY IN AN ORDER THAT IS THE
  SEMANTICS**: `session.run_abort` (the run stops at its next capture
  boundary WITH ITS PARTIALS KEPT), `capture_queue.stop()`, then
  `flare_preview_hold.close_hold()` after a short bounded grace —
  REGARDLESS, because his dark room back within seconds outranks a tidy run.
  Nothing new was invented for it.
- **LIGHTS ON IF NECESSARY** — `spectra/services/night_power.py`, the
  `fixture_brightness.owned` pattern one axis down (power first, then
  brightness: raising the brightness of a fixture that is off writes a value
  nothing displays). Read its docstring for WHAT WAS ESTABLISHED about a
  powered-off WLED under a realtime stream **and what was not**: the answer
  for his fixtures could not be settled from here, so the run is correct
  under either — it turns on only what reads off, CONFIRMS by reading back,
  restores in a `finally`, and reports per fixture. `fx/VENDOR.md` #30 fixes
  `WLED.get_power_state`/`set_power_state`, which were dead and broken in
  three ways until this became their first caller.
- **THE HONEST EXIT** (`spectra/services/night_exit.py`) — the new standard's
  first application: at every run end, normal or aborted, every fixture is
  read back AT THE EMITTED LIGHT (WLED `json/state`+`json/info`, Hue via
  `release_fade.read_hue_light_states`) and named DARK / EMITTING / UNKNOWN.
  **A mode or setting read is not verification, and neither is the house's
  own envelope.** An unreadable fixture is UNKNOWN, never dark. An emitting
  one is attributed: `by_design` (Dark-mode shielded — those were the lit
  sets he woke to on 2026-09-01), `run_fixture` (ours, did not let go — the
  only category this seam owes anybody an explanation for), or
  `outside_run`.
- **THE EXPORT IS TWO LISTS AND THE SECOND ONE IS THE LESSON.** `fixtures`
  is what the night took; `standing_lit_under_dark` is computed LIVE from
  `dark_light._shielded_set` at request time, never hardcoded, so his
  pending shield decision reaches River's morning backstop with nothing to
  remember. Turning off both lists is a complete morning scope; the first
  alone is the gap he already fell into.

- **A CALIBRATION CAN BE WHAT THE NIGHT RUNS** (2026-09-01, §104) —
  `spectra/services/night_calibration.py` is the binding statement.
  `PUT /api/night-run/queue` takes EITHER the plain item list OR a
  `calibration_id` (+ optional `amend`), never both, validated the whole way
  down AT DECLARATION through the same `amendment.resolve_subset` /
  `capture_queue.parse_items` the routes use. The night calls
  `calibration_runs.run_calibration`/`run_amendment` — which simply gained
  `run_queue`'s own `guard`/`save` seams (default None) so the 05:30 bound
  and the per-item record reach a calibration's queue with **no night-only
  copy of the walk**. What it measures lands in that calibration's own
  lineage; the night record carries a LINK AND A VERDICT, never a copy. A
  refusal (an amendment's mixing gate, a moved camera) is
  `night_run.STATE_REFUSED` — distinct from `declined` (never started) and
  `failed` (unexpected error).
- **THE MORNING READ** — `spectra/services/morning_read.py`,
  `GET /api/night-run/morning`, also folded into `/night-run/fixtures` so
  "what did last night do to my calibrations" and "what do I turn off" are
  ONE read. His bar: which calibration ran, what it measured (and whether
  ANY of it was applied), what changed via `calibration_diff` (never a
  second arithmetic), and what waits on him — his nouns, never a log. It
  computes and judges nothing of its own.

**Run state on `GET /api/engine/status` is a TRIGGER, not a dashboard
field** — the house restores its own "Dark Music" envelope off it, so
`status_brief()` reads the live in-memory record (stamped before the network
work) and exposes ONE `active` boolean derived from `ENDED_STATES`.

**The house lights are Home Assistant's.** The "Dark Music" envelope is
fired and restored by River's side; nothing here fires a house scene, and
this app originates exactly two HA requests, both GETs (below). Nothing on
this path assumes a host either — the capture client runs on a remote Pi
near the camera.

Spec: `tests/test_night_run.py` (the boundary, the planned end, the export
tracking a shield change, abort, the morning ending),
`tests/test_night_calibration.py` (the calibration path: the boundary
re-asserted, the lineage landing, the mixing gate at 2am, a morning-cut
amendment applying nothing, the morning read),
`tests/test_night_run_api.py` (auth, the payloads, both reads),
`tests/test_night_would_start.py` (the preflight: the one-predicate drift
proof both ways, every decline's sentence asserted against the START's own
record rather than a copy, the honest yes, and byte-identical stores across
ten calls),
`tests/test_night_exit.py` (RED-WHEN-LYING against the real headless
pipeline and real `fx.utils.WLED` transport), `tests/test_night_power.py`.

### THE SELF-TAKING NIGHT — armed, it takes a RELEASED room and comes up DARK

The Admiral overruled the never-takes-the-room boundary above (2026-09-04,
of having to leave his room in a special state before bed: "no!!! i dont
want to have to turn it on. why can't you"). **`spectra/services/
night_take.py`'s module docstring is the binding statement**; the design is
the seam's addenda 10-11 and nothing departs from it. Read it before
touching anything on this path. Eight things:

- **ONE ARMING LEVER, ABSENT BY DEFAULT.** `SPECTRA_NIGHT_SELF_TAKE=1`
  (`config.night_self_take()`, read at call time). Unarmed — the shipped
  state — a start on a released room declines with
  `mapping_refusals.night_not_owned`'s own sentence BYTE FOR BYTE, asserted
  against that function's output rather than a copy of its text. It is
  deliberately NOT `SPECTRA_HANDOVER_ARMED`: that latch guards the
  interactive route, and two levers for one act is how a night silently
  fails to run for a reason nobody looks at.
- **IT ONLY EVER TAKES A `released` ROOM.** Held by the older SpotFX
  process, or mid-handover, still declines: displacing a live writer while
  he sleeps is not what he asked for. Checked twice — in the gate chain and
  again inside `take_room`, which closes the window between the preflight
  and the start.
- **THE QUIET TAKE CLOSES BOTH SOURCES OF LIGHT, and there were two.** The
  stack comes up BLACK (`fx/VENDOR.md` deviation #32: a LOAD-TIME
  substitution — `virtual_cfg` untouched, so nothing persists and every
  ordinary take-back afterwards restores his show), and `engine.go_live` is
  NEVER called, so the conductor/response/trigger engines write to the
  RecordingExecutor. `fx_seam` routes on the OWNERSHIP RECORD plus
  `facade.set_host` and never on the engine's executor — which is exactly
  why the night's own capture writes land while the show does not. A third
  thing is a SKIP, not a mode: `run_handover(quiet=True)` does not run the
  post-commit ambient reconcile, because a hold is Hue bulbs lit.
  **Do not "fix" this with `pause_all`** — pausing suppresses the flush, so
  the fixture holds its last frame instead of being driven black AND the
  VIRTUAL_UPDATE freshness the activation gate verifies goes silent.
- **NO DARK MUSIC — his sleeping house IS the envelope** (settled with
  River 2026-09-03, his-routine-outranks-our-envelope). The self-taking
  flow fires NO house scene; the quiet take darkens only SPECTRA's own
  fixtures; a stray house light is the contamination witness's business,
  per capture. `tests/test_night_self_take.py` asserts the module body
  contains no house-scene call so nobody adds it back helpfully.
- **GIVE-BACK ON EVERY EXIT, AND THE ORDER IS THE SEMANTICS**: stop,
  RELEASE, terminal state, announce — River's re-dark rides the night's
  state, so the room is his again before he is told it is. Gated on
  `night_take`'s durable snapshot and NEVER on the armed flag or the
  current owner, so **a night that ran on a room SPECTRA already held
  releases nothing**. The honest exit still reads at the light: releasing
  tears the live stack down, so `night_run.Instruments` captures the driver
  handles BEFORE the release and the report then answers the better
  question — is it dark now that we have let go.
- **A STOP ARRIVING DURING THE TAKE IS HONOURED, and it is a window only
  this build created.** `capture_queue.stop()` is a no-op with nothing
  running, and the take now spends real seconds holding the room BEFORE
  there is any night for an abort to stop — so a `sleep-ended` landing
  mid-handover used to be swallowed while the room stayed held. `night_run.
  _stop_mark`/`_stop_source` (bumped by EVERY `abort()`, including the ones
  with nothing to stop) are read either side of the take; a stop that
  landed in between hands the room straight back and declines the night by
  name, naming WHICH stop it was (his morning routine is an ordinary
  ending; a touched light is not). A touched house is his house even when
  the house was touched between two of our own statements.
- **CRASH RECOVERY RUNS BEFORE `resume_own_room()`, and that ordering is
  the whole point.** `night_run.recover_orphaned_night()` is called from
  `spectra/app.py`'s lifespan first: without it the resume would
  re-activate the stack and resume his SHOW at 2am, through a door the
  quiet take never opens. The orphan is stamped `failed` with
  `refusal="crashed"` — an ending River's `active` boolean already covers;
  inventing a state word for a frozen contract is how a seam breaks
  quietly — the room goes back, the terminal state is re-posted and the
  give-back announced. A night already stamped by a proper ending is never
  restamped.
- **THE ANNOUNCEMENT IS BOTH ENDS, TIMESTAMPED AND SILENT** (Order 22 for
  a sleeping house): durable records plus `take`/`self_take` on
  `status_brief()` and `fixtures_export()`, never a sound and never a push.
  `night_take.merge_announcement` is the ONE merge — folding a give-back's
  `as_dict()` in naively REPLACES the take's own entry, which was got wrong
  twice before it was factored out.

**The instrument gate joins the preflight for EVERY night**, self-taking or
not (`night_run._can_measure` over `capture_runs.session_view()`, the one
thing asked about the camera): a room must never be TAKEN for — nor held
dark all night by — a night that cannot measure. It sits after the
declaration (the cheaper answer when both are true) and before pricing.
Any night spec that wants a night to RUN must now say a camera is there —
`conftest.measuring_session(monkeypatch)` is the one definition.

**NOT BUILT, and it is the named follow-up**: the durable per-declaration
`may_take_room: true` consent field (addendum 10, item 2). His spoken word
covered the first night; the second gate belongs on the declaration.

Specs: `tests/test_night_self_take.py` (the unarmed byte-identity, the
gates, the give-back ordering, idempotence, the silence),
`tests/test_quiet_take_dark.py` (the emitted-light proof through
`fx.headless`, with the ordinary path as its own red-first control),
`tests/test_night_take_crash_recovery.py` (the REAL lifespan, a control
proving the resume would have re-lit the room, and a fresh interpreter),
and — the COMPOSITION of all of them —
`tests/test_selftake_dark_e2e.py` + `tests/selftake_dark_e2e_driver.py`.

**THE COMPOSITION PROOF, and what its numbers are (2026-09-05, PR
fm/spectra-selftake-dark-e2e-proof).** The two halves above each prove
their own half with the other one faked; this one runs the WHOLE armed
flow — `night_run.start` → the real `take_room` → the real `run_handover`
→ a real `SpectraSide(quiet=True)` over a real `fx.headless` host — and
records every frame that reaches a device transport. MEASURED, quiet:
232 frames, 21 non-black, ALL of them the run's own capture lamp on the
one emitter it named; zero in the take, the dark step, the show being
driven, the give-back and after it; owner back to `released`, snapshot
dropped, zero frames once it let go. The ORDINARY path through the same
driver: 154 non-black, first lit in the TAKE. Three things it settles
that neither half did — the engine's executor is still the
RecordingExecutor DURING the queue (a write pushed through
`engine.conductor.executor` reaches nothing), the run's own hold reverts
to the snapshot it took and under a quiet take that snapshot is BLACK,
and a restart on a RELEASED room drives ZERO frames while the same
restart on an OWNED room drives 102. Read the test's own docstring for
the four named substitutions (no camera, so the queue item is
representative; `engine.start()`'s bridge WS is not opened; dummies, not
his fixtures; pricing).

**A PHASE LABEL IS NOT A CLOCK — bound a drain by measurement.** Building
it, one lamp frame landed on the far side of a phase label that was
flipped before the revert was awaited, and read as a stray light in his
room. A render pipeline has latency: a frame already assembled reaches a
transport after the write that supersedes it returns, so asserting the
room is black the instant a write is ISSUED asserts something physically
false. The fix is not a looser assertion — it is `REVERT_DRAIN_S` plus
`lit_after_revert_ms`/`lit_after_drain`, which say how far past the
revert the last lit frame actually landed. Any future instrument
labelling frames by phase around an in-flight write needs the same
treatment, or it will report a race as a defect.

### The contamination witness, and THE SCONCE MAINS RULE

`spectra/services/witness.py` is a READ-ONLY client for River's deployed
house-state witness — `GET {SPECTRA_WITNESS_URL}/witness/{changes,scope}`,
bearer from `SPECTRA_WITNESS_TOKEN`, both read at call time, the
deploy-time secret living outside this repository and never entering code,
a log or a record. SPECTRA CONFORMS to her contract, it does not
renegotiate it (`transcription.py`'s own posture with the Whisper bridge).
Its docstring is the binding statement; the short list:

- **A house light coming on mid-capture is measured as the fixture's own
  light** — the same class of failure the exposure lock and the
  firmware-brightness guard each refuse, arriving by a door this instrument
  could not see through before. Every capture window is asked about
  IMMEDIATELY as it closes (`RunDeps.witness`, **no added settle — the dark
  time stays flat**), plus ONE settled whole-run sweep at the end
  (`RunDeps.witness_sweep`) so a late row still indicts the capture it
  overlaps. Both feed ONE contamination re-take pass
  (`room_mapping._retake_contaminated`), which reuses the unseen-retry
  machinery and its ONE-retry-never-a-loop rule.
- **THREE verdicts, and the third is the point.** `witness_unavailable`
  MARKS, never discards and never kills a run: the capture is KEPT, stamped,
  NO CLEAN CLAIM is made, and it is named in the exit report
  (`night_run.witness_summary`). "We could not check" and "we checked and it
  was fine" are different facts — the same distinction `night_exit` draws
  between DARK and UNKNOWN. With no witness configured every capture is
  `unclaimed`, never `clean`.
- **A COMMISSIONING PASS IS ONE MEASUREMENT, so it gets ONE question over
  its whole span and NO re-take** (`commissioning._judge_contamination`): a
  gray-code stack is read against one dark and one full reference, so a
  house light landing anywhere in it corrupts the decode rather than one row
  of it, and re-taking one IS a whole new pass — which is what `repeat`
  already is. It RECORDS and NAMES, and never touches `ok` or the five
  pre-registered tolerances: contamination is a fact about the instrument's
  conditions, like the exposure lock, not a table row.
- **Our own fixtures are subtracted** from the rows, by slugified id/name
  against the entity's object id (`own_entities`/`is_ours`) — exact, never a
  substring. The match is BIASED TO OVER-INDICT on purpose: a fixture of
  ours we fail to recognise costs a re-take; a house light we mistake for
  ours silently corrupts a footprint.
- **THE SCONCE MAINS RULE (Admiral-binding, both fleets):**
  `light.dimmer_kitchen_sconce` is the kitchen sconces' MAINS SUPPLY. **No
  run path may ever turn it off or lower it** — this side does not drive HA
  entities at all, and `tests/test_witness.py` asserts the module body
  contains no write verb. It is **BINARY, 0% or 100%, a switch with no scale
  factor**: nothing records its level per measurement and nothing is
  designed against it scaling (the Admiral's own correction, superseding an
  earlier level-recording idea); the witness treats it as an ordinary scope
  entity, so an accidental write to it indicts overlapped captures like any
  other row. At 0% BOTH sconces are dead and it looks exactly like a dead
  controller or a lost network, so `SCONCE_MAINS_FIRST_CHECK` is the NAMED
  FIRST LINE of any sconce diagnostic (`capture_refusal`,
  `activate_for_capture`'s failures, the not-rendering case) — FIRST is the
  whole point; buried three paragraphs down it is the hour this exists to
  save.

Spec: `tests/test_witness.py` (wire shape, the window cap, the three
verdicts, the mains rule), `tests/test_witness_retake.py` (the re-take on
the REAL `run_mapping`, including the no-added-settle proof and the
byte-identical unconfigured path).

## UNATTENDED CAPTURE — the client, the queue, and ONE seam for a run

His bottleneck, not a feature request: a mapping or commissioning run
needed a person at every step (open the page on a device with a camera,
grant it, wait for the lock, aim, keep the tab alive, press Start, press
the next one), so every capture experiment queued behind his availability.
**`docs/UNATTENDED_CAPTURE.md` carries the LEDGER** — what now runs with
zero human involvement, what needs a human once (aiming and choosing the
pose, camera permission, `ffmpeg`/`v4l2-ctl`, confirming that camera can
lock at all, declaring the queue), and what still needs his hands per run
(SPECTRA owning the lights, a second pose for unseen emitters, judging a
`findings` verdict, deciding what to do with a `marginal` refusal). Keep
those three categories separate whenever this area changes; blurring them
is the one way this build can become a lie.

- **`spectra/capture_client/camera.py` is the binding statement for the
  lock's honesty, and the rule is one sentence: automating the lock
  REQUEST is the point, automating the lock CONFIRMATION is forgery.**
  `apply_lock()` asks the V4L2 control and then READS IT BACK;
  `read_lock()` only ever returns what `v4l2-ctl --get-ctrl` printed; a
  driver that accepts the write and keeps its old value reports auto, and
  the run refuses by name. The `SyntheticCamera` every proof uses has NO
  locked default, so a proof cannot pass without exercising the gate.
  Nothing here may grow a flag that proceeds anyway.
- **The POSE TOKEN is minted inside `camera.open()`, and that placement is
  the whole design.** A footprint is `lit - dark` in one camera's byte
  scale, so footprints are comparable within a pose and not across two. A
  dropped WebSocket moves nothing and re-locks nothing, so the client
  re-asserts its pose on reconnect (`hello`'s `pose_hint` →
  `mapping_session._adopt_pose`) — labelling one measurement as two is the
  dangerous direction. A camera REOPEN mints a new token, and
  `capture_queue` names the change (`mapping_refusals.pose_changed_note`).
  Don't move the token's creation, and don't let the client decide a pose
  survived.
- **`spectra/services/capture_runs.py` is now the ONE seam that executes a
  capture run** — the run lock, the no-session gate and the two runs moved
  out of `spectra/api/rooms.py`, which is now the human-pressed caller of
  the same function `capture_queue` drives. A new gate goes there once.
  `RunOutcome.escaped` distinguishes a refusal the run STATED (200 with
  its record, which may hold kept footprints) from one that RAISED (409
  with the sentence) — conflating them either loses a partial map or
  claims a result that does not exist.
- **`spectra/services/capture_queue.py`**: waits for a session that is
  present AND LOCKED, walks the declared list, KEEPS partials, carries on
  past a refusal, retries ONLY a `partial` and only when the item declared
  it, and rewrites `storage/spectra/capture_queue.json` after EVERY item
  (nobody is watching; a queue killed by a reboot has still explained
  itself). It stores a SUMMARY per run — the full map is in
  `room_maps.json`, the full judged table in `commissioning.json`; copying
  either in would make the one file nobody watches the unbounded one.
  A queue is validated AT DECLARATION, so a typo is refused before the
  room goes dark.
- Three new sentences in `mapping_refusals` (no camera / session lost /
  queue stopped) plus one FACT (`pose_changed_note`), and `lock_refusal`
  reworded ONCE to speak to both client kinds rather than growing a second
  wording for the native one.
- Proofs: `scripts/check_capture_queue_e2e.py` (real server, real
  WebSocket, the REAL client, a synthetic camera — a five-item queue with
  no human action after start, a mid-queue refusal it carries on past, a
  dropped socket whose partial is kept and whose retry completes, the pose
  held across the drop and named across a reopen, the gate refusing an
  automated client, and a blind machine saying so), run from
  `tests/test_light_field_checks.py`; `tests/test_capture_queue.py`;
  `tests/test_capture_client.py`. **No live-room proof exists, and the
  V4L2 backend has never met real hardware** (the build machine has no
  `/dev/video*` and no `v4l2-ctl`) — both stated in the doc's own "What is
  proven, and what is not". Every way that backend can be wrong fails
  SAFE by the read-back rule: a missing tool, a missing control or an
  ignored write all report NOT LOCKED and refuse the run by name, so a
  wrong V4L2 detail costs a refused run, never a map that looks fine and
  is not.

### THE CAMERA HOST AS A BOOT SERVICE — and the Pi that does not exist

**`docs/CAPTURE_CLIENT_HOST.md` is the binding statement, and its LEDGER is
the deliverable**: what is proven on a dev host, what only real hardware can
settle, and what buying the board unlocks. **No Raspberry Pi exists.**
Nothing here may be reported as a working Pi deployment, and when hardware
arrives the correction is a DATED AMENDMENT, never a quiet rewrite of a
sentence that was true when written. Six things:

- **THE UNIT SHIPS VERBATIM** (`deploy/spectra-capture-client.service`) and
  is checked by `systemd-analyze verify` — systemd's own parser, which
  rejected two real mistakes here (`StartLimitIntervalSec` belongs in
  `[Unit]`, not `[Service]`; a `Documentation=file:` relative path is
  invalid). It carries NO host path: `%h` only, `ExecStart` takes NO
  arguments, and everything that differs per machine lives in a launcher
  `scripts/install_capture_client.sh` writes. Verifying the shipped bytes
  is only meaningful because they ARE the installed bytes.
- **`systemd` HAS NEVER STARTED IT.** This build machine has no D-Bus
  session bus and a private `systemd --user` refuses without cgroup
  delegation, so `systemctl --user start` cannot run here at all. The unit's
  RESTART BEHAVIOUR is executed by a supervisor in
  `scripts/check_capture_client_service.py` that reads `Restart=`/
  `RestartSec=` out of the INSTALLED unit and obeys them. That proves what
  the unit tells systemd to do; it is not a proof that systemd did it, and
  it must never be reported as one. Do NOT install a probe unit into his
  live user manager to work around this.
- **ONE ENV FILE IS THE WHOLE CONFIGURATION**
  (`spectra/capture_client/config.py`, `SPECTRA_CAPTURE_*`): an explicit
  argument beats the environment beats the default, and a malformed number
  REFUSES BY NAME at startup rather than silently defaulting.
  `SPECTRA_CAPTURE_POSE` is a **LABEL** — his own words for where the camera
  stands, so a status surface can name WHICH camera is missing. It is never
  evidence of where the camera is; only `pose_fingerprint` measures that.
- **ABSENCE IS A READ — three states, not two**
  (`spectra/services/capture_health.py`, `storage/spectra/
  capture_health.json`, autouse-isolated in `tests/conftest.py`).
  `never` / `present` / `absent`, the last naming the machine, its build,
  its declared placement and how long it has been gone. It is folded into
  `capture_runs.session_view()` (so the queue and the calibration routes get
  it for free) and `mapping_session.status()`. **IT GATES NOTHING** — the
  run's refusal is still `lock_refusal`'s and `NO_SESSION`; a reporting
  surface that could refuse a run would be a second exposure gate. This
  makes `mapping_session` write ONE small row to disk (who is holding the
  camera), which is why its "persists nothing" docstring and test now say
  "no pixels" instead.
- **THE CLIENT'S DEPENDENCIES ARE TWO, AND `requirements.txt` IS THE
  SERVER'S.** `requirements-capture-client.txt` is httpx + websockets;
  installing the server's list on a camera host would drag compiled wheels
  (`aubio-ledfx`, `samplerate-ledfx`, `python-mbedtls`, `pyfastnoiselite`,
  scipy, librosa, pillow) with no guaranteed aarch64 build onto the board.
  `scripts/check_capture_client_deps.py` proves the closure by importing the
  client with 28 server-only packages BLOCKED at the meta path, asserts it
  never touches `fx/`, and audits for architecture literals
  (`platform.machine()` is REPORTED in `hello`, never branched on).
- **THE CLIENT ACQUIRES NO ROOM AUTHORITY, structurally.** Nothing under
  `spectra/capture_client/` may mention `fx_seam`, `light_ownership`,
  `handover`, a device driver or a compiler, and it imports nothing from
  `spectra.services.*` — asserted in `tests/test_capture_client_service.py`.
  Making it a boot service changed none of that.

Provisioning: `scripts/install_capture_client.sh`, idempotent, `--check`
writes nothing, every prerequisite refused BY NAME with its fix (ffmpeg,
`v4l2-ctl`, python3/venv, the video group, the configuration, linger). **It
is `pipefail`-strict** — a `grep` that legitimately finds nothing needs
`|| true` or the script dies silently mid-check (a real bug found here).

### A MACHINE MUST BE ABLE TO SAY WHAT IS WRONG WITH IT

2026-09-02, PR fm/instrument-visibility, after eight successive failures on
his laptop in one evening — every one ours, every one INVISIBLE here until
he pasted something. **The defect was not any of the eight; it was that we
had no way to know.** `spectra/capture_client/doctor.py`'s module docstring
is the binding statement. Five things, and the middle three generalize well
past this subsystem:

- **`spectra-capture-client --doctor` is the one command**, and it is
  **STDLIB-ONLY and runnable as a plain file**
  (`python3 spectra/capture_client/doctor.py`, no package import — the
  package `__init__` pulls in `websockets`). That is a requirement, not a
  preference: it is the tool you reach for when the VIRTUALENV is the broken
  thing, which two of the eight were. The installer runs it before it writes
  anything, which is how the address branch became a pre-install check.
- **ASK THE PREDICATE, NOT THE NEIGHBOURING QUESTION.** `[ -r /dev/video0 ]`
  is not `id -nG | grep -qx video`: a desktop seat's ACL grants read access
  with no group at all, so the old installer check passed on a machine whose
  service could never open the camera. This is the SAME shape as the
  `import venv` vs `ensurepip` bug (PR #241) one section over, and both cost
  an evening. When adding a precondition check, write down the thing that
  actually has to be true and check THAT.
- **A GROUP IS NOT APPLIED UNTIL THE USER MANAGER RESTARTS.** `usermod -aG`
  changes the database, not any running process; `systemd --user` takes its
  supplementary groups once at manager start and, being unprivileged, cannot
  gain one after. A user service INHERITS the manager's groups, so `id -nG`
  in a fresh shell can say `video` while the service holding the camera has
  none. The doctor reads the manager's own `/proc/<pid>/status` `Groups:`
  line — a pure read with the same answer as running a test unit, without
  writing a transient unit into his manager every time. **Say REBOOT, not
  "log out and back in"**, especially with linger enabled.
- **`SupplementaryGroups=` IN A USER UNIT CAN NEVER WORK, AND MEMBERSHIP IS
  IRRELEVANT TO THAT** (2026-09-03, PR fm/unit-group-directive-fix). An
  unprivileged manager is refused `setgroups(2)` outright — `216/GROUP`,
  "Changing group credentials failed: **Operation not permitted**" — so a
  user who IS in the group fails identically. The shipped user unit carried
  it; the owner was told to `usermod` and REBOOT, did both, twice, and it
  still died. **The boundary: the directive is legitimate ONLY under a ROOT
  manager that drops privileges — a SYSTEM unit may carry it, a USER unit
  must not.** They are two files (`deploy/spectra-capture-client.service`
  and `...-system.service.in`, the installer's `--system` mode) rather than
  one template with a conditional line, and the user unit's header NAMES the
  directive it excludes so nobody re-adds it beside `DeviceAllow=`.
- **`216/GROUP` HAS TWO CAUSES AND THE STATUS CODE CANNOT TELL THEM APART**
  — only the journal's own reason line can: "Operation not permitted" is the
  privilege cause above (fix: remove the directive, `daemon-reload`,
  restart, NO reboot); anything else is the membership-shaped one. The
  doctor's `read_216_cause()` reads it and gives them separate verdicts.
  **The general rule: an exit status is a CLASS, not a diagnosis.** Before
  translating one into advice, check whether the class has more than one
  cause — collapsing two into the more common one produces a confident wrong
  answer that sends someone to fix a thing that is not broken.
- **A CONTROL YOU DID NOT RUN IS A CONFOUND YOU DID NOT RULE OUT.** Rig A's
  original red case (`SupplementaryGroups=video` on a user NOT in the group)
  went red, proved 216, and PASSED FOR THE WRONG REASON: it never ran the
  IN-GROUP control, where the same 216 arrives for the same reason. When a
  proof attributes a failure to a variable, run the case where that variable
  has the OTHER value — `check_capture_client_fresh_host.py` rig A now runs
  A1 (in-group), A2 (out-of-group), A3 (no directive → STARTS) and A4 (the
  stale-ghost case) on real systemd, cross-checking the doctor's translation
  against each REAL journal line rather than a typed constant.
- **A LAST-ERROR VERDICT WITHOUT A CLOCK IS A GHOST** (same PR). After the
  owner's fix the doctor still headlined `last error` as a problem, quoting
  a failure from before it, while the service was up and connected. A
  journal read with no clock cannot tell a scar from a wound. It now
  compares against the unit's own `ActiveEnterTimestampMonotonic` and
  reports `IS FAILING` vs `FAILED EARLIER` as different verdicts — the
  second is UNKNOWN, visible and never counted. **Use the MONOTONIC clock,
  not `journalctl --since`**: `ActiveEnterTimestamp` is a wall-clock string
  with SECOND granularity and a `Restart=` loop fits inside a second, so the
  old failure lands in the window and reads as current;
  `ActiveEnterTimestampMonotonic` and `journalctl -b -o short-monotonic` are
  the same boot-relative clock at microsecond precision, with nothing to
  parse but a number systemd printed.
- **A MENU CONTROL HAS NO SINGLE OUTPUT FORMAT** (same PR).
  `v4l2-ctl --get-ctrl` prints `auto_exposure: 1` on some drivers and
  `auto_exposure: 1 (Manual Mode)` on others — including his. The read-back
  compared the whole string to `"1"`, so a camera GENUINELY AT MANUAL
  reported `exposure_locked=False` and every calibration-grade run refused
  by name while quoting a mode that said Manual. `camera._menu_value` parses
  the LEADING INTEGER and every menu comparison in that file goes through
  it (exposure, white balance, continuous autofocus); `_as_float` does the
  same for the four levers, which were silently reading None on the same
  drivers. Never compare a driver's printed value by string equality.
- **A REACHABLE-BUT-BROKEN CLIENT MUST NOT LOOK LIKE A HEALTHY ONE.**
  `capture_health` has a FOURTH state, `impaired` — connected and saying why
  it cannot work, in the client's own words. `present` stays a boolean about
  the socket so every earlier reader is unchanged, and NOT-YET is not
  CANNOT: only a lock that was REPORTED and did not lock counts, or every
  healthy startup would flap through it. It still gates nothing.
- **AN INSTALLER MAY NOT CLAIM WHAT IT DID NOT CHECK.** The old script ended
  by announcing "SPECTRA can now SEE this machine" — unconditionally, while
  installing a service that could not start. It now WAITS (bounded) for a
  real hello on `camera_host` and reports one of four outcomes, non-zero for
  three of them.

**`systemctl --user` DOES work from an agent shell here** — the memory that
it cannot is about the SHELL, not the machine. Export
`XDG_RUNTIME_DIR=/run/user/$(id -u)` and
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus` and his live user
manager answers. Without them it fails "Failed to connect to bus", which
reads exactly like "no such service" — so anything reporting on a unit must
fill those in and, when the bus is genuinely absent, say so as a property of
the shell. **This unlocks a real proof**: `systemd-run --user
--property=SupplementaryGroups=<any group> /bin/true` reproduces a genuine
`216/GROUP` in about two seconds — for ANY group, member or not — and the
same transient unit with no directive starts clean; `reset-failed` leaves
nothing behind. Do NOT install, enable or start the real unit in his manager
to test something.

**Proving a provisioner needs a host that never saw the repo.**
`scripts/check_capture_client_fresh_host.py` is the pattern: rig A drives
real systemd as above; rig B is `docker run --rm -v $REPO:/repo:ro
debian:stable-slim` with a user created seconds ago — not in `video` because
nobody put it there, and with no `ensurepip` because that is what a bare
Debian is. Shims in `check_capture_client_service.py` force both answers to
a question so a refusal is exercised deterministically; they cannot prove
the QUESTION is right, which is exactly what the fresh host is for. Either
rig SKIPS with its reason named when the facility is missing — a named hole
beats a false clean row.

**A check script that renders through `fx.headless` must `os._exit()`.**
`fx`'s `TemporalEffect` spawns non-daemon threads the frame-stepped harness
never joins, and `FxHost.stop()` refuses ("refusing to stop the SpotFX
process"), so a plain return leaves the interpreter alive forever — which
reads as a hang, not a failure, and cost a real debugging cycle here. Wrap
`asyncio.run(main())` in try/except and `os._exit(status)`.

## Per-device timing equalization + the device page (`/devices`)

His ask (2026-08-28): "Different devices seem to have different network and
physical latencies... tune the per device settings so that they are timed
equally... negative is that it fires earlier", and "we need a device edit
page to edit and create devices... all the parameters that were tunable in
ledfx on one tab, as well as the groupings and namings".

**`DeviceSettings.timing_offset_ms` is OFFSET family (negative = EARLIER)
and RELATIVE ONLY — it can never move the room.** `spectra/models/
device_settings.py` is the field + sign law; `docs/SPECTRA_TIMING_
CONVENTIONS.md` carries its row against every other timing quantity. The
translation is `delay_i = offset_i - min_j(offset_j)`, always >= 0: a
fixture can only be made to WAIT, so "A earlier" is implemented as delay
for everyone else and the earliest device is delayed by exactly nothing.
All-offsets-equal (including the shipped all-zero default) is byte-identical
pacing to before the field existed — asserted at the transport, not claimed.
**Absolute alignment against the sound is still `av_sync_lead_ms`'s job**
(LEAD family, positive = earlier, applied at the trigger poll); the two are
never added with the same sign.

**ONE application point: `fx/devices/__init__.py::_flush_timed`** (the
device flush layer, `fx/VENDOR.md` deviation #24). `Device.update_pixels`
is the only live-path caller of `self.flush()`, so every driver's transport
is covered by it — Hue's entertainment DTLS stream, WLED via its DDP/UDP
subdevice, e131/ddp/udp/dummy. `E131Device.deactivate()`'s own direct
`flush()` of a blackout frame is deliberately NOT routed through it. Held
frames are COPIED (`assemble_frame` can hand back the device's own buffer)
into a bounded deque and released on the next frame's arrival once due — no
timer, no thread in the write path. `fx/device_timing.py` holds the
arithmetic and the process-global delay map; **`fx/` may not import
`spectra/`**, so SPECTRA PUSHES (`device_settings.push_offsets`, called on
every save and at `live_host.activate` against the host's own roster) and
fx never pulls. Proof: `tests/test_device_timing_landing.py` — two dummy
devices on the real pipeline, both light edges measured AT THE TRANSPORT,
byte-identity negative control, and a test that goes red when the seam is
bypassed.

**The device page (`/devices`, `spectra/web/src/devices/DevicesPage.tsx`)
renders a field list it does not own.** `fx/device_schema.py` introspects
each vendored driver's OWN merged `CONFIG_SCHEMA` — the exact validator
`Device.update_config` runs — so the page cannot drift from what the driver
accepts; 19 distinct config keys across the six vendored types, plus the
timing field. ONE TAB (his hard constraint), grouped within it as Base /
Type / Groupings & naming / Timing, where the Base/Type split is derived
from the class hierarchy, not a second list. **`udp` was missing from
`fx.host.VENDORED_DEVICE_TYPES` while its driver was vendored and
registered** — added 2026-08-28, because that set gates the handover
readiness check and offering a type it would refuse to count is a trap.

**TWO WRITE BRANCHES, mutually exclusive by construction** (`spectra/
services/device_console.py`'s docstring is the binding statement): SPECTRA
owns AND the stack is up → every write goes through `fx.facade` (new routes
`GET/POST /api/devices`, `PUT /api/devices/{id}`), which runs the vendored
create/`update_config` and `save_config` in one call; otherwise → the same
validated entry written atomically into `storage/spectra/fx-live/config.json`,
the file the go-day seeder owns and nothing else is writing while the stack
is down. Both branches STATE which ran (`applied: "live" | "stored"`), so an
edit made while the room is dark is never lost and never claimed live.
**DELETE is deliberately not built** — he asked to edit and create, and
removing a device tears down its virtuals and rewrites his scenes.
Groupings are the shared category registry, which maps a CATEGORY to
VIRTUAL ids, so a device's grouping is its virtuals' membership; a category
is never invented from a typed name.

**Measuring it: `/avsync`'s PER-DEVICE mode** (`av_sync_pattern.
PatternDriver.start(device_id=...)` narrows the flash to the virtuals ONE
device backs and leaves every other virtual playing the show — the
"later per-category selector" that module's docstring always flagged).
`spectra/services/device_equalization.py` turns a set of those runs into
proposed offsets and is the binding statement: the shared audio path
cancels in the BETWEEN-DEVICE differences, so those are the answer; the
SLOWEST device is the reference, so every proposal is a WAIT (>= 0,
positive = later) and nothing is asked to fire before its frame exists;
and **today's applied delay is subtracted back out of each measurement**
(`intrinsic = av_offset - applied_delay`) — the per-device analogue of the
room lead's add-don't-assign rule, without which every re-measure would
chase its own tail. It NEVER writes: `GET /api/av-sync/device-proposal` is
read-only and applying is his press per device through
`PUT /api/devices/{id}/timing`. Equalizing moves the whole room later by
the spread; that global shift is absorbed by the EXISTING room
re-measure + apply loop, and every result says so (`after_note`). His
Hue-slower-than-WLED belief is a hypothesis this measures — nothing in the
arithmetic knows a device's type.

**`storage/device_categories.json` IS NOT UNDER `SPECTRA_STORAGE`** —
`fx.device_model.CATEGORIES_FILE` is a fixed repo-relative path, so
`SPECTRA_STORAGE_DIR` does NOT repoint it. An isolated instance run for a
screenshot writes the WORKTREE'S REAL registry the moment anything touches
the device page's grouping controls (found doing exactly that, 2026-08-28 —
one virtual silently left a category). Set `device_model.CATEGORIES_FILE`
explicitly, or check the file back afterwards.

**ONLY THE DEVICES HE USES ARE LISTED BY DEFAULT** (2026-08-28, his ask:
"only devices i use should be visible on default. can show more with
expansion tab"). `spectra/services/device_usage.py` is the rule and the
binding statement: a device is IN USE iff it backs a virtual in
`room_topology.genuinely_driven_virtual_ids()` — the compiler's own ground
truth, computed AT REQUEST TIME and never stored, so adding a device to a
grouping or a scene moves it into the default view on the next load with
nothing to migrate. Type is never consulted: 2 of his 10 in-use devices are
DUMMIES (`gap-crystal-mapper` in the mapper chain, `radial-dummy`) and 11 of
21 are LedFX-seed machinery (gap placeholders, mask/foreground/background
layer dummies) plus one genuine duplicate. An EMPTY ground truth means NO
restriction (a fresh install shows everything, never an empty page). The
listing still returns EVERY device with `in_use`/`duplicate_of` stamped on
it — hiding is the page's default view, not a server-side omission — and
`usage` carries the counts so the expansion control can name the hidden
number. Duplicates (same name + same type + backing nothing) are FLAGGED,
never deleted; the page deliberately has no delete. `/devices` and
`/avsync`'s per-device rows share the one server flag. Help: `devices-in-use`.
Spec: `tests/test_device_usage.py` (his real 21-device config shape, the
10/11 split, and the liveness proof).

**Sonic parity**: a `device` domain (`device_console.OPERATIONS`, 7 ops)
merged into `settings_agent.ALL_OPERATIONS` — remember the hand-written
`settings_mcp_server.py` wrapper per op AND the CLI fixture manifests
(`tests/fixtures/cli_transcript_synthetic_*.json`), where the three
`_scene_*` and the three original real captures are DELIBERATELY STALE
(tests assert they are refused) and must not be "fixed". Help:
`devices-page` (+ `device-timing-offset`, linked from the page).

## SPECTRA phone A/V-sync instrument (`/avsync`) — MEASURE the audio/visual offset, don't argue it

`spectra/services/av_sync_{correlate,audio_ref,pattern,session}.py` +
`spectra/api/av_sync.py` + `spectra/web/src/avsync/` (built 2026-08-22,
PR fm/phone-audio-video-capture-for-measured-a-7b; `docs/SPECTRA_SPEC.md`
§93). His phone's mic + camera are reduced ON THE PHONE to two number
streams (raw media never leaves it) and correlated server-side against
SPECTRA's own live audio hub (`live.hub`, snapcast.monitor = speaker
time, server timestamps) and a light reference (a random-hold white flash
PATTERN driven over fx_seam with snapshot/revert, or the show's own
writes). Result: `av_offset_ms` (positive = lights BEHIND the sound,
negative = AHEAD — the sign row is in `docs/SPECTRA_TIMING_CONVENTIONS.md`,
it is neither LEAD nor OFFSET family, it is a MEASUREMENT) plus a
statistical ± and NAMED systematic terms with direction; a weak/ambiguous/
unstable correlation REFUSES by name, never guesses. The measurement is
still never applied automatically — see the APPLY section immediately
below for the button that closes the loop on his press. Three things to
know before touching it: (1) the
flash pattern's RANDOM holds are load-bearing (a periodic blink is refused
as ambiguous by design) and the light correlation is on signed EDGES, not
levels (`av_sync_correlate.signed_edges` docstring has the measured why);
(2) the ONLY file it writes is `storage/spectra/av_sync_measurements.json`
(numbers + statement, last 100) — keep it that way, the privacy statement
in help topic `av-sync-privacy` promises it; (3) **camera/mic need a
secure context** and he reaches SPECTRA over plain http (Tailscale, no
`tailscale serve`) — the page detects it and names the two fixes (Chrome's
per-origin flag tonight; HTTPS in front of :8000 properly — which also
unblocks the Settings voice mic, silently dead on his phone for the same
reason). The vision/ArUco stage is deliberately NOT built — only its seam
(`FrameRing`, frame tap OFF by default) is. Proof without a room:
`scripts/check_av_sync.py` (simulated rooms through the real code);
`tests/test_av_sync_*.py`.

### Applying it: `RoomControlState.av_sync_lead_ms` — the ONLY authored term in SPECTRA's fire clock

Built 2026-08-28 (PR fm/avsync-apply-button, his ask: "when I run avsync
how do I update the offset value based on that data?"). **Read
`spectra/services/av_sync_lead.py`'s module docstring before touching
anything here — it is the binding statement** (the sign law, the
add-don't-assign translation, and why the two lookalike settings are
different jobs). The short list:

- **THE TARGET HAD TO BE CREATED, because it did not exist.** Before
  this, SPECTRA's fire clock had exactly ONE correction term and it isn't
  authored: `bridge.effective_position_ms()` = raw position +
  `shape_offset_ms` (spot-effects' machine-learned per-song xcorr number,
  which WANDERS mid-song). `spectra/config.py` and `RoomControlState`
  carried no latency/offset/lead/delay field at all.
- **The two numbers that LOOK like the target are different jobs, not
  older values of this one** — worth knowing before anyone "reuses" one:
  `settings.audio_latency_ms` (root, LIVE) aligns WAV capture boundaries
  for the xcorr training corpus and is **the number he remembers as
  "150"**; `settings.ledfx_trigger_buffer_ms` (root, LEAD family) is
  LedFX-HTTP write-transport compensation read ONLY by the retired legacy
  engine, and holds an inert **−800** on his box. Neither is reachable
  from `spectra/` anyway (import discipline + the read-only bridge), and
  nothing in the apply path may seed from either — pinned by a test.
- **LEAD family, positive = fire EARLIER**, applied as a clock shift at
  **exactly one place**, `spectra/services/engine.py`'s trigger poll, via
  `av_sync_lead.show_clock_ms(...)`. A second application point is the
  thing to never add; `tests/test_av_sync_apply.py` greps for one.
- **`None` (default) means NEVER CALIBRATED, deliberately not `0`** —
  identical at the light, different in the dialogue ("none yet" vs
  "0 ms"), so nothing about his show changed on deploy and no borrowed
  number is ever shown as a previous value of this one.
- **The translation ADDS, never assigns**: `proposed = current +
  round(av_offset_ms)`, because the measurement is taken with the current
  lead already running. Assigning would undo the previous calibration on
  every re-measure. Worked examples both directions are in the
  `av_sync_lead_ms` row of `docs/SPECTRA_TIMING_CONVENTIONS.md`.
- **The write is his press through `PUT /api/room-controls`** (the
  established save path, one field, then a real GET read-back — a PUT
  echoing its own body is not a read-back). Server-side
  `GET /api/av-sync/apply-proposal` owns the sign translation so the page
  renders it and never re-derives it — the flare-preview inverted-sign
  precedent. Excluded from Sonic's registry on `force_scene_*`'s own
  precedent. UI: `spectra/web/src/avsync/ApplyOffsetDialog.tsx`, help
  topic `av-sync-apply` (linked, not orphaned).
- **PROOF BAR: a setting that reads back is not evidence.**
  `tests/test_av_sync_lead_landing.py` measures the LIGHT EDGE moving on
  the real render pipeline (the §84 landing-instrument pattern through
  `fx.headless`) by exactly the amount set, both directions, with an
  uncalibrated negative control — and was verified to go RED when the
  clock shift is removed. Any future change to how this setting reaches
  the show must clear that bar, not a round-tripped JSON value.

## SPECTRA param orphan watchdog (the safety net under momentary releases)

`spectra/services/param_watchdog.py` (own supervised task in `spectra/app.py`'s
lifespan, his ask 2026-08-21 after an effect was left stuck running backwards:
"some kind of watchdog system to make sure that parameters are set correctly
like that"). Every 10s it compares each engine-tracked virtual's LIVE effect
config (read off the in-process host under the effect's own lock) against the
conductor's `VirtualState.param_baseline`, and restores any param away from
baseline with NOTHING holding it for 30s continuously — loudly (WARNING log
naming virtual/param/found/restored/age, `fire_history` bucket `"watchdog"`,
`engine.status()["param_watchdog"]`, an additive `param_watchdog` key on
`GET /spectra/api/liveness`, never part of `healthy`). Read its module
docstring before touching anything that moves a param outside the engine's
bookkeeping — three things to know: (1) **"nothing holding it" is three
structural holders** — a pending release (`ResponseEngine.pending_release_keys`),
a drift mechanism owning the param, a tween in flight on the live effect — and
**the permanent/momentary discriminator is `param_baseline` itself**: a
permanent kind's carry moves the baseline (`conductor.on_surge`), a momentary
kind never does, so the watchdog cannot fight an authored permanent flare by
construction. The restore target is `ResponseEngine.release_target` — a thin
wrapper over the SAME `_carried_value` `flush_releases` uses; never introduce a
second definition of "baseline" next to it (`flush_releases` additionally falls
back to an entry's spike-time `return_to` for a param with NO baseline at all —
a never-authored param — which the watchdog deliberately keeps no opinion on;
`_pending_releases` holds `PendingRelease` dataclass entries since
fm/reverse-flare-glide-and-stuck, owned per fire and armed at spike landing —
see the "reverse flare's ~2x dwell overrun" entry above for why). (2) **`background_brightness`/
`background_color` are out of scope by name** — the conductor's own colour-set
landings write them to the wire WITHOUT moving `param_baseline` (a pre-existing
bookkeeping gap, left alone), and Dark/Light mode own both keys too; `brightness`
is compared against baseline × any `brightness_multiplier` seen since the last
scene fire (the dimmer doesn't rewrite live brightness until the next write —
also pre-existing). If you add a NEW writer that moves a baselined param outside
the engine's carry (another fx_seam path, a new room mode), either move the
baseline with it or gate/exclude it here — otherwise the watchdog will, after
30s, correctly-by-its-own-lights undo it and log an orphan. (3) It stands down
entirely while the engine is dark, the live stack is down, or `preview_pause`/
`flare_preview_hold` is active. A restore that doesn't take is retried at most 3
times then given up on at CRITICAL (named in status) until the next scene fire —
a "PARAM ORPHAN NOT TAKING" line means something keeps re-moving the param or the
schema rejects the write; find that, don't tune the watchdog. Module-global state
(no DI seam — `tests/conftest.py`'s autouse `_isolated_param_watchdog` resets
it); the `Deps` dataclass is the injection seam. Spec:
`tests/test_param_watchdog.py`; timing constants recorded in
`docs/SPECTRA_TIMING_CONVENTIONS.md`; `docs/SPECTRA_SPEC.md` §90.

## SPECTRA two-dimensional drift gradient + Rainbow select

Owner ask 2026-08-20 (`data/two-dimensional-drift-gradient-and-rainb-imfg/
HIS-VERBATIM-WORDS.md`). Two independent features, one PR.

**The 2D drift gradient**: `spectra/models/gradient2d.py` (`GradientProfile`:
`top`/`bottom`, each the SAME "#rrggbb or linear-gradient(...)" string every
colour value in this app already uses — his ask "very similar to the
current gradient picker, just make it a square" is literal: each edge
reuses `ColorGradientPicker` verbatim, `GradientEditor2D.tsx` just stacks
two of them with a square bilinear preview between; `x_mode: "loop"|
"bounce"`, pure `sample()`/`advance_x()` — no spot-effects import, local
reimplementation of the stop-parsing grammar `spectra/services/
color_rotate.py` already established the precedent for). Stored/picked
exactly like a sequencer curve profile (`spectra/services/
gradient2d_store.py`, `storage/spectra/gradients2d.json`,
`GET/PUT /api/gradients2d`) — **not** via `CurveAttachmentEditor.tsx`: a
gradient has exactly ONE room-level attachment point
(`RoomControlState.active_gradient_id`), not a per-entry map, so the
one-off/shared-profile machinery that shape needs doesn't apply; editing is
a local draft with two explicit buttons, "Save" (overwrites its own id) and
"Save as new…" (forks a fresh id) — his literal "save as new or overwrite"
wording, not a detach/revert dance. UI: `DriftGradientBar.tsx`, mounted in
`RoomControlsBar.tsx`'s top-bar group-button row.

X is time, Y is intensity, vertices only at top (y=1) and bottom (y=0),
linear between — explicitly **not** rotation (he pre-empted the
misreading himself). Wired into `drift_conductor.py`'s `tick()`: an active
gradient **replaces** the wheel-based colour journey for that leg (held
exactly like a live rainbow palette already holds it — a different colour
source has taken over), never runs alongside it. X advances a fixed
fraction of `RoomControlState.gradient_x_period_s` every leg, looping or
bouncing per the gradient's own `x_mode`; Y drifts toward a target
(`RoomControlState.gradient_y_slew_s` paces it) rather than snapping.
**The "ahead of arrival" problem, his proposal, adopted as-is** (asked to
propose, said "if this is a good starting place, just go with it"): the Y
target changes only on a trigger firing or an analysed song transition
firing, not continuously every leg — `DriftConductor.on_intensity_event()`
re-anchors the target to the live intensity at that moment;
`trigger_engine.py`'s `_fire()`/`_fire_transition()` call it via a
constructor injectable (`intensity_event`) whose **default is a safe
no-op**, deliberately NOT a lazy import of the production `engine.conductor`
singleton the way `fire_scene`/`fire_response` are — those are the subject
of every trigger_engine test and always explicitly stubbed; this one small
side call is easy to forget to stub, so its own default costs nothing when
forgotten. Production wiring is one explicit line in `services/engine.py`
(`trigger_engine._intensity_event = conductor.on_intensity_event`), the
same place that module already owns constructing the `conductor`/
`responses` singletons. Flares are UNCHANGED — a flare colour jump
(`scene_response.py`) still writes `state.gradient`/`background_color`
directly via `apply_color_set`'s instant jump; the next gradient leg's own
ABSOLUTE `(x, y)` sample (not a delta) simply overwrites it on its own
20s-leg schedule, the same way the wheel journey's rotation already gets
overwritten-then-resumed around a flare jump.

**Any new test/script that calls `DriftConductor.tick()`
must pass `room_controls=`/`gradient_profiles=` explicitly (or isolate
`scfg.ROOM_CONTROLS_FILE`/`GRADIENT2D_FILE` under its own temp
`SPECTRA_STORAGE`)** — `tick()` now reads `room_controls().active_gradient_id`
on every leg to decide the branch above, so an unstubbed default silently
touches real storage (`spectra/services/drift_conductor.py`'s own
`_default_room_controls`/`_default_gradient_profiles` lazy-import the real
stores, matching every other `_default_*` injectable in that file). Found
this while adding the feature: `test_spectra_engine.py`'s shared `_engine()`
helper had to gain `gradient_profiles=lambda: {}` +
`room_controls=lambda: rc.RoomControlState(...)` for exactly this reason —
copy that shape, don't rediscover the gap.

**Rainbow select**: `models/color_set.py` `ColorSetCard.is_rainbow`
(mirrored in `spectra/services/color_sets.py`'s read-only projection — the
usual "defined twice" trap) is **ENUMERATED, never inferred from name** —
his own instruction, since several of his other sets have colourful names
and are not rainbows. Exactly five cards are marked: Hype 1, Hype 2,
Hype 3, the Hype group, Black Hole Rainbow —
`scripts/mark_rainbow_color_sets.py` (dry-run default, `--apply`, raw-dict
patch + backup, matches `set_scene_colorset_preference.py`'s convention;
not run against live storage by this build). `RoomControlState.
rainbow_select_limit` (default 0.9, his words) — above it, automatic
colour-set selection is restricted to `is_rainbow=True` cards only; at or
below it, to `is_rainbow=False` ("single") cards only — a clean exclusive
partition (`spectra/services/rainbow_select.eligible()`), never both, never
neither. Wired into `scene_sequencer._default_eligible_sets` — the SAME one
automatic-selection choke point `mode_availability`/`color_set_preferred`
already reach, following that established precedent — deliberately NOT
`drift_conductor`'s destination pool or `scene_response`'s flare colour-jump
pool (neither of those apply the other two gates either; same documented
scope boundary, not an oversight). A Group card is never itself a selector
candidate here (unchanged, pre-existing), so a Group's own `is_rainbow`
mark has no effect on this gate — it exists for completeness/authoring
symmetry only. UI: `RainbowToggle.tsx` on `ColorSetsPage.tsx`, next to
`ModeAvailabilityToggle`; the limit lives in `DriftGradientBar.tsx`'s panel.

Neither feature is deployed against his live room by this build — land and
verify only. Specs: `tests/test_gradient2d.py`,
`tests/test_drift_conductor_gradient.py`, `tests/test_rainbow_select.py`,
`tests/test_gradient_retarget_hook.py`, `tests/test_mark_rainbow_color_sets.py`.

**Every linear-gradient in this app is HORIZONTAL by convention (`90deg`),
and the angle carries NO engine meaning anywhere** — `spectra/models/
gradient2d.py::parse_stops` discards the head segment before the first
comma, `spectra/services/color_rotate.py` passes it through verbatim, and
the vendored `fx/color.py` parses it into an `angle` attribute no effect
reads (grep-confirmed). It decides only how a value PAINTS as CSS, which is
why a stray vertical angle showed up as his 2026-08-25 report: the 2D
gradient editor's edge strips (a wide 22px bar) painted across the bar
instead of along it. Cause, measured live against the real widget (not
inferred): react-gcolor-picker bakes its OWN angle into everything it emits
— its built-in quick-pick gradients carry 0/45/270/315deg, and a
solid→gradient conversion starts from its internal 180deg default — and
PR #171 hid the angle dial (`showGradientAngle={false}` gates only the
control's render, never the emit), removing the only way to correct one.
`ColorGradientPicker.normalizeGradientAngle` therefore CANONICALIZES to
90deg — rewriting a wrong or keyword direction, not merely supplying a
missing one — and is applied on emit AND on display (the swatch and the
widget both paint a re-angled copy), so a value stored vertical between
#171 and the fix paints correctly with no data migration. Proof, extracted
verbatim from the TSX so it can't drift: `scripts/
check_gradient_angle_canonicalization.mjs`. `web/src/components/
ColorGradientPicker.tsx` (the frozen SpotFX twin) deliberately does NOT
canonicalize — its angle dial is still visible, so a rewrite there would
silently overrule a control the user can see.

**A `ColorGradientPicker` nested inside a `TopBarGroupButton` panel closed
the WHOLE panel on TOUCH (not mouse) the instant he tapped anything inside
the nested picker — fixed 2026-08-20.** His report on `DriftGradientBar`
(top bar → "Gradient"): opening the panel and picking an existing gradient
worked (PR #152's New-draft-race fix, unrelated), but tapping the Solid/
Gradient tab or the hue/saturation area inside the Top/Bottom edge's
colour picker closed the entire Drift gradient panel out from under him.
Root cause, general to BOTH `ColorGradientPicker.tsx` copies (`spectra/
web/src/components/` and `web/src/components/`) and any future consumer
with the same shape: its popover is its OWN `createPortal(...,
document.body)`, a DOM **sibling** of the panel it was opened from, not a
descendant — an enclosing panel's own outside-click dismissal
(`TopBarGroupButton`'s `document.addEventListener('mousedown', ...)`
containment check) can't see the popover's subtree and reads every tap
inside it as an outside click. **Reproduced only under REAL touch
(`Input.dispatchTouchEvent`, letting Chrome synthesize the compat mouse
sequence) — a CDP mouse-only click (`Input.dispatchMouseEvent`/
Puppeteer's `page.click()`) on the identical element did NOT reproduce
it**, so a click-only eye-check of this class of bug can pass while the
real phone still fails; test dialog-closing reports with a raw
`Input.dispatchTouchEvent` tap (see git history for the throwaway CDP
script), not `page.click()`. Fixed at the source, not per-consumer:
`ColorGradientPicker`'s own popover div stops the `mousedown` from
bubbling past itself (`onMouseDown={(e) => e.stopPropagation()}`) — it
never reaches ANY ancestor's document-level listener, regardless of DOM
position, and the picker's own `onDocDown` already excluded clicks inside
its own `popoverRef` so nothing relied on the event still bubbling.
Fixed only in `spectra/web/`'s copy (his actual report); `web/`'s copy
has the identical `createPortal` + document-mousedown shape and is a
same-class latent risk for any future outside-click panel there, not
touched by this fix.

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

### The way back from `released` TOLERATES a partial activation (2026-08-21)

His ruling: "one unreachable device must not be able to keep his entire
room dark" — after six aborted take-backs in one night on one WLED whose
mDNS name would not resolve (and two sconces the morning before that
merely answered too slowly), each abort tearing down the twenty lights
that HAD come up. `handover.run_handover` step 2 now commits a PARTIAL
activation (stack up, ≥1 expected virtual driving, some devices/virtuals
unconfirmed) when `from_world == RELEASED` — aborting there lands on
darkness, not safety, and never saves the unreachable light. **Scope is
bounded and must stay bounded**: a handover FROM a running world keeps
its strict all-or-nothing rollback; a HARD failure from released (stack
never up, or not one expected virtual driving) still aborts. The policy
reads `SpectraSide.activation_outcome()` (structured — `ActivationOutcome.
partial`), mirrors `resume_own_room`'s 2026-08-13 tolerance, and the
skipped light is NAMED everywhere he looks via `spectra/services/
activation_report.py` (the take-back response `committed-partial`, `GET
/ownership` → `activation` → `RoomOwnershipBar`'s amber `ActivationStrip`
on every page, the Status page line, liveness `activation` — additive,
NEVER `healthy`, since the frame watchdog's dead-man must not restart-loop
the service over one dark fixture — and the record's own history note via
`light_ownership.commit(detail=)`). The report is a SNAPSHOT: its
`run_supervised()` rechecks still-dark lights every 30 s through the SAME
probe `device_gaps()` polls (`live_host.probe_device_live`), marks
recovery, and re-runs the vendored driver's own `async_initialize()`+
`activate()` for a never-resolved device — nothing in the render loop ever
re-resolves an inactive device, so without it a fixed light needs a whole
release+take-back cycle to collect one fixture. Before diagnosing "the
take-back failed on device X": read `GET /spectra/api/ownership`'s
`activation` and the record's history — a 200 `committed-partial` is NOT a
failure. Proofs: `tests/test_take_back_partial.py` (real FxHost + real
WLED driver against a `.invalid` name through the real armed route — never
his data, never his network), `tests/test_activation_report.py`,
`scripts/check_ownership.py` §12b. Known environmental note: this worktree
carried his real `storage/device_categories.json` (gitignored), which makes
`tests/test_crystal_activation_verify.py`'s fixture rooms intersect to an
empty `expected_active_ids` — pre-existing, fails identically on pristine
master here; `test_take_back_partial.py` stubs `room_topology.
genuinely_driven_virtual_ids` for exactly that reason.

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

## A CONFIG LOAD IS AN ORDERED PROGRAM — a virtual's restore can undo its neighbour's

Found live 2026-09-01 (`fx/VENDOR.md` #29, PR fm/tvmapper-cold-load-fix): his
`tv-mapper` came up DARK after every SPECTRA restart, deterministically, and
nothing above INFO said so. Three things generalize past this one virtual:

- **Activating a virtual is not a private act.** It registers segments on
  each backing device, and `fx/devices/__init__.py::Device.add_segments_batch`
  deactivates every EXTERNAL virtual streaming to a device whose OWN
  device-virtual is activating (and vice versa). So a virtual's restore can
  silently undo one that already came up. `Virtuals.create_from_config` used
  to restore a stored effect through `set_effect()`, which unconditionally
  activated — even for a virtual stored `active: false`, which the loop then
  set back two statements later. A no-op on itself; permanent on its
  neighbours. `set_effect(..., activate=False)` is the fix, and the STORED
  `active` FLAG now decides. **Before adding anything to a config-load loop,
  ask what it does to virtuals ALREADY loaded — config order is the program,
  and his real ordering (tv-mapper idx 14, both sconces idx 22/27) is what
  made this deterministic rather than a race.**
- **Read the end state back; a step that looked fine when it ran proves
  nothing.** `Virtuals._audit_restored_effects` runs after the whole config
  is loaded and names every virtual the stored config says should be driving
  and isn't — it does not need to know HOW one was stopped, which is exactly
  why it catches this class. `_record_restore_failure` logs at ERROR with the
  virtual, the STORED EFFECT TYPE and the real reason, and
  `Virtuals.restore_failures` carries it to `live_host.activation_gaps` —
  which previously GUESSED "effect restore failed silently at config load"
  and was wrong about this very defect. **A status surface that invents a
  cause is worse than one that says "unknown".**
- **A repair that lies is worse than a failure that is loud** (the captain's
  own ruling). An evicted virtual still HOLDS its effect object; it just runs
  no render thread. So a same-type effects PUT took `facade._effects_put`'s
  `use_tween` / in-place `update_config` branch, which never touches
  `virtual.active`, and returned success: real glide writes in
  `executor.recent_writes`, operator satisfied, fixture dark. Only a
  TYPE-SWITCH write appeared to fix it, because that branch calls
  `set_effect()` — and that asymmetry was the best diagnostic clue.
  `facade._verify_effect_took` now reads the LIVE INSTANCE back on every
  effects PUT (object exists, not a `DummyEffect`, right type, virtual
  actually active), attempts one honest repair, and 500s by name otherwise.
  **A write call returning is never evidence that the write took.**

**How a latent ordering bug became live, and the mapping feature's part in
it:** a device virtual with NO stored `effect` key never enters the restore
branch, so it never activated and never evicted anything. His three
(`tv-backlight`, `sconce-kitchen-left`, `sconce-kitchen-right`) each now hold
`singleColor` at `#000000` brightness 0.0 — `room_mapping.MAP_EFFECT_TYPE` +
`BLACK` verbatim — with `pixelRange`/`pixelPattern` in their stored `effects`
history, lamps that exist nowhere else. `activate_for_capture` writes an
effect and raises the active flag through `fx_seam`, i.e. the facade's
`_effects_put` + `_virtual_put_active`, and BOTH call `save_config()`: a
capture run PERSISTS a stored effect onto a device virtual that had none.
Those values are his own runs' genuine residue, not corruption — the load
path was what was wrong to act on them — so nothing in his config was
rewritten. **Anything that borrows a virtual and puts it back should know it
is writing his stored config, not just the live host.**

Proofs: `tests/test_cold_load_effect_restore.py` (cold start in a FRESH
INTERPRETER per the light-mode cold-start precedent — a warm pytest process
cannot speak honestly about config load order; 5 of its 7 tests verified RED
against the unfixed code, the lying repair reproducing as literal
`200`/`success` with the virtual still dark) and
`scripts/check_cold_load_effect_restore.py`, which cold-loads HIS OWN
`storage/spectra/fx-live/config.json` READ-ONLY with every device swapped for
a dummy of the same pixel count: unfixed, exactly one virtual comes up dark
and it is `tv-mapper`; fixed, all five declared-active virtuals drive. **That
dummy-swap is the general recipe for proving anything about his real config
offline** — it is the only change made, so ordering, segments and pixel
counts are all his.

## Black Hole (`fx/effects/blackhole.py`) — three things that bite

Everything below is recorded in `fx/VENDOR.md` (#12, #14, #18, #19, #20)
with the mechanism detail; this is the short list of traps.

1. **`reverse` is a SPAWN-SIDE flag that also picks the sign of every live
   blob's motion.** Nothing reverses a particle already in flight, which is
   why flipping it back used to snap the whole outbound population around
   in one frame. Since 2026-08-24 the True→False edge arms a real
   turnaround (`_reverse_edge` → `_arm_reverse_fallback`, `p_turn`/`p_vr`,
   `REVERSE_FALLBACK_TURN_S`) that merges back onto the speed curve with no
   step at either seam; the outward eject stays instant by his own ask.
   **Do not "fix" a horizon captive by releasing it** — PR #179 did exactly
   that and was reverted the same day (#181, no reason recorded): a release
   also evicts blobs the flare never moved AND makes them immortal (the
   infall alive-test retires captives by their hold clock and never
   free-fallers). The shipped fix instead pins a captive to the ring only
   while it is AT the ring (`REVERSE_FALLBACK_RING_TOL`).
2. **Two particle flags, not one.** `p_nocap` = "spawned past max_blobs"
   (the drop payoff, the blob rush, the charge's forced formation) and is
   what the density-cap arithmetic reads; `p_is_burst` = "a drop-payoff
   particle" specifically, and additionally drives
   `PHASE_BURST_SPEED_MULT`. Anything measuring the explosion filters on
   `p_is_burst`; anything about the cap uses `p_nocap`. Conflating them
   silently changes what the explosion measurements report.
3. **The charge no longer swallows the panel, and the lull's fill stops at
   the HEX bound, not `r_max`.** `HEX_FILL_RADIUS` (1.128, computed from
   the measured `HEX_SPAWN_VERTS`) is where every real cell is already
   covered; `r_max` (~1.49) is the addressable RECTANGLE's corner and every
   pixel of growth past the hex covers dead cells — that gap was his "it
   currently expands too far". Any "is the panel dark?" measurement on this
   device must be taken over the REAL cells (the device profile's mask), not
   the dummy rectangle a headless harness renders — see
   `scripts/check_blackhole_charge_lull.py` for the instrument and
   `.claude/skills/crystal-hex-grid/SKILL.md` for why.

## A SATURATING SIGNAL MEETING `>=` MAKES A "never" THRESHOLD FIRE

Found 2026-09-02 turning the Dancer's flames off (`fx/VENDOR.md` #31,
PR fm/dancer-flames-off). Every audio power in this pipeline is CLIPPED
to exactly 1.0 upstream (`fx/effects/audio.py::_update_freq_power`'s
`np.minimum(freq_power_raw, 1)`), and an `ExpFilter` over it converges to
EXACTLY 1.0 in float within ~9 audio frames (~150 ms at 60 Hz). So a
user threshold whose Range max is 1.0 — the setting whose whole meaning
is "never" — FIRES on any loud passage the moment the comparison is
`>=`. It is not an overshoot past 1.0, so **clamping the signal fixes
nothing**; the comparison is what has to exclude the top of the range.
Prefer `thr < 1.0 and sig >= thr` over switching to a strict `>`: `>`
also changes the exact-equality case at every OTHER threshold, and a
saturating signal reaches exact equality routinely, so an existing
setting can no longer be claimed bit-identical.

Known instances of this shape, checked not assumed (only the first is
fixed; the rest are reported, and the captain decides):
`fx/effects/dancer.py:1149` `burst_threshold` (FIXED),
`fx/effects/eye.py:574` `snap_threshold` (same defect, unfixed),
`fx/effects/dancer.py:393` + `fx/effects/keybeat2d.py:479`
`min_volume` compared `>=` against a [0,1]-clamped volume — while
`fx/effects/audio.py:1173` and `fx/effects/melbank.py:540` compare the
SAME setting with strict `>`, where 1.0 genuinely does mean never. When
adding any audio gate, check which side of that split you are on.

**And a gate is rarely the only source.** The Dancer has FOUR flame
sources and `burst_threshold` gates only two (beat bursts, the ember
trickle); the flourish payoff burst and the six `_impact_flames` stunt
moments are ungated, so no threshold value can silence them —
`burst_size = 0` is the other half of "off". Before promising a knob
turns something off, enumerate every caller of the emitter, not just the
one the knob's name suggests. Proofs (harness + pinned pre-change
baseline, offline on `fx.headless`):
`tests/test_dancer_flames_off.py`, `scripts/check_dancer_flames_off.py`.

## Fish (`fx/effects/fish.py`) — Orbits' twin, different kinematics

A new Matrix effect + a Fish scene that is a WHOLESALE COPY of his Orbits V2
(flare kinds, bands, initial params, weightings, curves, labels — see
`scripts/seed_fish_scene.py`, dry-run default, and `docs/SPECTRA_SPEC.md`
§94). Three things to know before touching it:

1. **It reuses Orbits' patterns, not its motion.** Each fish has its own
   position, speed and SCREEN-space heading; the thin oval is laid out along
   that heading (never in normalized space — that would shear it by the
   panel's aspect). A real turn RADIUS (`orbit_radius`, re-read) caps the
   turn rate, so an about-face is structurally an arc. Several shared param
   keys keep their names but mean something else on a fish (`orbit_radius` →
   turn radius, `spin` → current swirl, `horizon_scale` → home ring,
   `base_speed` → swim speed, decoupled from the turn radius) — the registry
   `note` on each says so; read it before assuming Orbits semantics.
2. **The population-cap bypass is scoped to two moments**, by his own
   decision: the charge's school and the DROP's rush, via `p_nocap` (the
   rush was the lull's until 2026-08-28 — see 6 below). A cap-exempt fish
   never survives the moment it was granted for, and ordinary swimming
   always obeys `particle_count`. Don't widen this.
3. **Mutual avoidance is STEERING ONLY** (`avoid_strength`, 2026-08-28 —
   his own 2026-08-25 deferral un-parked). It adds one more weighted term
   to the desired-heading sum and is bounded by the SAME turn-rate clamp as
   every other steer, which is what makes both fish laws structural rather
   than best-effort. Three things not to undo: only neighbours in the
   FORWARD arc count and the answer is a lateral swerve (a point-away
   vector asks for a 180 and measurably made crossings WORSE); the
   separation radius is DERIVED from body length, never a second knob; and
   it is off during the charge's school and the lull's rush, which are
   authored choreography, not crowds to fix. Sweep + tuned default:
   `scripts/check_fish_avoidance.py`.

4. **A strong beat LUNGES** (`LUNGE_*`, 2026-08-28) — his live diagnosis:
   the ripple scales off real speed and flap correctly, but the beat speed
   boost used to decay within tens of ms, so big ripples rode tiny travel.
   The envelope holds the boost near full for `LUNGE_HOLD_S` so a beat
   covers several body lengths. Motion side only; the wake was deliberately
   NOT touched (it self-heals once the travel widens). It rides
   `speed_jump` x the existing spike signal and adds NO knob, and arms only
   above `LUNGE_SPIKE_MIN` so quiet swimming stays byte-identical. Sweep:
   `scripts/check_fish_lunge.py`.

5. **Positions are a WORLD FRAME and the panel is a WINDOW onto it**
   (`camera_follow`, 2026-08-28): the render subtracts a camera origin
   (screen = world - cam), and AT REST THAT MAPPING IS THE IDENTITY — which
   is why `camera_follow=0` is byte-identical to the pre-window effect, not
   merely close (`tests/test_fish_camera.py` proves it against the
   PRE-CAMERA BASELINE's own module, loaded out of git as a second
   registered effect — reuse that trick for any future byte-identity claim
   in `fx/`). That baseline ref is PINNED, and imported from
   `scripts/check_fish_camera.py::BASELINE_REF` rather than copied: it was
   originally the moving ref `master`, which silently retired the whole
   proof to `pytest.skip` the moment the camera merged. **A false alarm is
   loud and gets fixed; a permanent skip is silent and reads as green** —
   when an instrument's reference moves out from under it, pin the
   reference, never silence the instrument. What the knob
   actually does is UNDO A CLAMP: the charge already held the school on
   screen by subtracting the school's own velocity from every swimming fish
   — a window locked rigidly to the shoal — so `camera_follow` is the
   fraction of that travel handed back to the fish, with the window
   following at its own lagging, speed-capped pace. Three things not to
   undo: the window moves ONLY during the charge and the lull; it follows
   only fish it can currently SEE (which is what makes "the school is never
   lost" structural rather than tuned, and what stops a rush stayer
   converted far off-window from dragging it away); and ripples are stored
   in WORLD px so they are left behind in the water, with anything far
   off-window CULLED, never wrapped. Everything naming the visible water —
   pond bound, home ring, "inward", the lull's centre pull, where arrivals
   and the drop's burst appear — is measured from the window, not a fixed
   world point, or the school would just circle a stationary pond. The lull's
   own centre pull is deliberately left WHOLE (it is what holds his "stays in
   the centre of view" to 4px); relaxing it with `camera_follow` is a design
   fork, not taken. Measured basis for the 0.8 default, and the honest
   surprise that the CHARGE's wake already streamed on master (so the gain
   there is the shoal moving, not the water starting to):
   `scripts/check_fish_camera.py`.

6. **THE WAKE, THE CHARGE'S SPREAD AND THE LULL CLOCK were all replaced
   2026-08-28** (`fm/fish-ripples-charge-lull-rework`), on his word. Do not
   restore any of the three out of loyalty to what was there before.
   * **The wake is Orbits' trail, plus expansion.** One persistent
     accumulation buffer (`self.wake`) decayed exponentially AND diffused
     outward every frame; deposits are soft FILLED splats at the tail, laid
     every frame through the same `_splat_many` each body segment uses.
     There is no ripple ring buffer, no radius, no outline — his objection
     was the visible circle line. Energy still rides speed x flap, never a
     beat value. It is SCREEN space but WORLD anchored: rolled each frame
     by exactly the displacement the world->screen mapping moved, with the
     sub-pixel remainder carried; what rolls off an edge is dropped, never
     wrapped. **Its colour rule is stated in the module and read off the
     RESOLVED gradient curve, never the config string** — a real gradient
     gives the wake a different colour (`WAKE_GRAD_OFFSET`, a half turn); a
     solid palette gives it substantially less brightness
     (`WAKE_SOLID_DIM`). Measured proof: `scripts/check_fish_wake.py`.
   * **The charge spreads.** An even (low-discrepancy) spawn plus an
     omnidirectional separation steer (`SCHOOL_SPACING_W`), weighted well
     under `SCHOOL_W` so the shared heading still governs the unison
     arrival. `avoid_strength`'s forward-arc dodge is still OFF in a
     school; these are different terms. Before/after against the merge-base:
     `scripts/check_fish_charge_spread.py`.
   * **The lull is a CLOCK in thirds of its own (dynamic) duration**: every
     fish gone by 1/3 — no lone fish, no survivor, with a hard backstop, not
     just a schedule; ripples only to 2/3; fully dark after (the wake is
     RAMPED to zero, because a half-life never reaches it). The window eases
     home once there is nothing left to follow. **The lull's rush MOVED INTO
     THE DROP** (his addendum): it rushes in at the drop instant, swirls for
     the drop's duration (`RUSH_SWIRL_W`), and `particle_count` of them stay
     behind — read ONCE at the settle, after which the ordinary
     intensity-driven count owns the population again through the normal
     entry/exit paths (`_settle_rush`'s docstring is the binding statement).
     With `rush_count` at 0 the drop is exactly what it was.
   * **`scripts/check_fish_camera.py::BASELINE_REF` moved forward** to that
     PR's merge-base, because the old "camera_follow=0 IS the pre-camera
     commit, bit for bit" claim needs a reference differing ONLY by the
     camera, and the wake changes the render at knob zero. What it asserts
     now: the window origin is EXACTLY zero at knob 0 across the whole arc,
     and ordinary swimming with the wake off is byte-identical to the
     merge-base. If you change ordinary swimming, that second one goes red —
     which is the point.

Every new fish knob is a first guess pending his eye; the effect ships
tunable, not tuned. Proof: `scripts/check_fish.py`,
`scripts/check_fish_avoidance.py`, `scripts/check_fish_lunge.py`,
`scripts/check_fish_camera.py`, `scripts/check_fish_wake.py`,
`scripts/check_fish_charge_spread.py`, `tests/test_fish.py`,
`tests/test_fish_camera.py`.

## Radial (STAR) rotation is audio-lows-driven — a healthy `spin` can read as parked

`fx/effects/radial.py`'s ONLY motion source is the audio callback:
`spin_total += lows_impulse * spin_cfg²/10` per 60 Hz callback, i.e.
**rev/s = 6 × lows_impulse × spin²** — `spin` is a gain on the LIVE
captured lows power (snapcast.monitor melbank), NOT a motor speed, and NOT
the bridge's "intensity" (that's stored librosa file analysis; the two
diverge freely). During bass-light passages the lows impulse idles ~0.01,
so a healthy spin 0.55 turns ~6°/s — reads as frozen while rendering fine.
Diagnosed live 2026-08-21 (his "star is not moving at any speed" — his own
binding edit and #168's flip port both ruled out with evidence):
`docs/spectra-star-motion-audio-idle.md`. Executable proof, real pipeline,
no live access: `scripts/check_star_spin_motion.py`. Before diagnosing any
"effect X ignores its speed/reactivity param" report, check whether the
param is an audio gain (`aspect: reactivity` in `config/effect_params.json`)
and measure the live impulse before blaming the param value or the writer.

**Since 2026-08-25 radial has a second, differently-scaled rotation control
— don't confuse the two** (his ask, PR fm/radial-base-rotation; `fx/VENDOR.md`
deviation #22): `base_rotation` is a QUIET FLOOR in plain REVOLUTIONS PER
SECOND — LINEAR and absolute, never squared, never multiplied by audio —
while `spin`/Speed stays exactly the squared audio gain above. They combine
as `effective rev/s = max(base_rotation, reactive rev/s)`: a FLOOR, not a
sum, so a base never adds anything at a peak and the existing reactivity is
byte-identical wherever the music's own drive is faster (the named
alternative, a sum, is a one-line change in `_base_rotation_step`). It
advances on the RENDER clock (`draw` → `_base_rotation_step(self.passed)`),
NOT in `audio_data_updated` — a base term there would stall in exactly the
quiet case it exists for. Default `0.0`, so every pre-existing scene renders
byte-identically until he sets one (asserted, not claimed). Proofs:
`scripts/check_radial_base_rotation.py`, `tests/test_radial_base_rotation.py`.
Registry-declared param help (`"help_topic"` on an entry in
`config/effect_params.json` → a `HelpLink` on that param's row in
`InitialSetTab.tsx`) is new with this change and is the general way to
deep-link a param to a help topic; note such a topic id lives in the JSON
registry, so the AGENTS.md orphan-audit grep over `.tsx`/`.ts` will not see
it.

## `crystal-mapper` (the hex Matrix virtual) — read the skill before touching it

Load `.claude/skills/crystal-hex-grid/SKILL.md` before changing any effect
targeting the Matrix category (`config/effect_params.json`
`categories.Matrix.effects` — 11 of them, not just Blackhole), before
writing anything that reads `storage/device_profiles/`, or before trusting
any coverage/brightness/"is this visible" measurement on that virtual. Short
version: only 976 of the addressable 72x37=2664 cells are real light
(36.6%), forming a hexagon — real-cell density is a flat 50% out to
`r<=0.85` (normalized radius, r=1 = the panel's own rectangular edge) and a
hard 0% past `r≈1.2`, a cliff, not a gradient. The effect-layer render
pipeline (`fx/effects/twod.py`) has zero awareness of this — `r_width`/
`r_height` are always the full rectangle. Found and fixed 2026-08-17
(`fx/effects/blackhole.py`'s infall spawn annulus landed almost entirely on
the dead corner band — `fx/VENDOR.md` deviation #12, `docs/SPECTRA_SPEC.md`
§76) after repeated prior agent confusion about this device's geometry; the
skill exists so that doesn't happen again. **The boundary is
direction-dependent, not a single radius** — its distance from center is
~0.87 normalized-r at a flat edge's own midpoint-normal vs. ~1.13 at a
corner vertex, so a scalar spawn radius can only coincide with the true
edge at a handful of angles (found the hard way 2026-08-18, same §76: a
hit-rate-maximizing scalar annulus read as spawning "several pixels" inside
the visible edge everywhere except the tight end of that range).
`fx/effects/blackhole.py`'s `HEX_SPAWN_VERTS`/`_hex_spawn_edge_radius`
compute the boundary per spawn angle instead — see the skill's own new
section for the derivation and why a hexagon's inradius is NOT "tangent at
the edge and outside near the corners" (it's inside the polygon everywhere
but the 6 tangent points, by definition).

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

**Never `pkill -f "python -m spectra"` (or any bare-argv pattern match) to stop
your own isolated preview instance — it also matches his REAL live
`spectra.service`, which runs the identical argv from a different
interpreter path, and `pkill -f` can't tell them apart.** Found live
2026-08-19: an isolated instance spun up for a phone screenshot
(`SPECTRA_STORAGE_DIR`/`SPECTRA_PORT` repointed to a spare port, exactly the
established pattern below) was stopped with `pkill -f "python -m spectra"`,
which also SIGTERM'd his live `spectra.service` (`/home/javi/SpotFX/.venv/...`,
not the agent's worktree venv) — systemd restarted it within about a second
(`Restart=` in the unit), but the restart's own resume logic re-activated the
live stack, reconnected the Hue entertainment streams, and fired a real scene
as a side effect: a real, visible, un-undoable room glitch, not a no-op. Kill
your own isolated instance by the exact PID your own `Popen`/background-job
call returned (or `pkill -f` a pattern that includes your unique spare port
or an env marker only your instance sets, e.g. `SPECTRA_STORAGE_DIR=<your
temp path>`), never by the bare module invocation string alone — it is not
unique to your process in this environment.

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
