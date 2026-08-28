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
   decision: the charge's school and the lull's rush, via `p_nocap`. A
   cap-exempt fish never survives the moment it was granted for, and
   ordinary swimming always obeys `particle_count`. Don't widen this.
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

Every new fish knob is a first guess pending his eye; the effect ships
tunable, not tuned. Proof: `scripts/check_fish.py`, `tests/test_fish.py`.

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
