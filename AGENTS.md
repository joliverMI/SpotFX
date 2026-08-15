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
actions alongside the pull-a-profile dropdown, so editing a curve never has
to silently retune a profile shared by other scenes. `web/src/scenes/
{SequencerPanel,CurveProfilesCard}.tsx` is the spot-effects `/app/` twin of
this same pattern (its own top-level sequencer, above) — `CurveProfilesCard`
still forces a `prompt()`-named profile before any edit and has no
Detach/Promote; left as-is since that Scenes page is frozen pending SPECTRA
superseding it.

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
`scripts/seed_star_strips.py --apply`, NEVER by re-running the v2 seeder),
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

**Ambient's music-precedence gate** (found live 2026-08-15: `ambient_enabled:
true` + a real track playing + an active scene + firing triggers = all 19 Hue
bulbs sat frozen at ambient cream, following none of it — Ambient wasn't
competing with music, it was silently swallowing the whole song, and was
likely a second, independent cause of his original "no scene changes"
complaint on top of the `scene_change_mode` fix). His ruling: Ambient is the
room's RESTING state — MUSIC WINS while it plays, Ambient resumes on its own
the instant it stops. `spectra/services/ambient_music_gate.py` is the single
choke point every path that can change the live hold now funnels through (a
human PUT, every bridge state broadcast, process startup/resume) — none of
them may call `services.ambient.reconcile()` directly, or the precedence rule
can be bypassed. `RoomControlState.ambient_enabled` still means "I want
Ambient"; the gate tracks the LIVE hold against a second signal,
`bridge.is_playing()`. A confirmed read always wins, even over an existing
hold; an UNKNOWN read never actively changes anything (carries the current
hold forward) — collapsing unknown onto "release" was rejected because a
transient bridge blip would otherwise flicker-release an already-quiet held
room. Visible always-live status (`off`/`holding`/`yielding`/`transitioning`)
folds into `GET /spectra/api/engine/status`'s `ambient` key and shows as a
persistent badge on `RoomControlsBar.tsx`, separate from the one-shot
PUT-outcome badge. Full detail + room-proof status: `docs/SPECTRA_SPEC.md`
§52. Spec: `tests/test_ambient_music_gate.py`, `tests/test_bridge.py`.

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
agent.py`'s module docstring first if touching this. The model is handed
exactly two tools (`get_settings` read, `set_setting` -> `apply_change`);
`_dispatch()` is the complete, exhaustive name->code mapping, so there is no
third branch to reach for a shell/file/HTTP/service-control/light-driving
call, whatever the prompt or transcript says. `tests/test_settings_console.py`
proves this without a network call (fabricated tool names/keys rejected,
nothing persists on rejection) plus one live-model smoke test skipped
without `ANTHROPIC_API_KEY`. Model id from `spectra.config.
settings_agent_model()` (env `SPECTRA_SETTINGS_AGENT_MODEL`, default
`claude-sonnet-5`); API key from `settings_agent_api_key()` (env
`ANTHROPIC_API_KEY`) — unset means a stated 503, never a silent no-op.

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
`--tools ""` + `--allowedTools` naming exactly the two tools its own MCP
server (`spectra/services/settings_mcp_server.py`, a stdio wrapper around the
SAME `settings_agent._dispatch()` the API backend uses — no second authority)
exposes, and re-verifies the live `system/init` tool manifest on every single
response before trusting anything in it. That last check exists because a
live re-proof caught `claude-haiku-4-5` fabricating tool-call output in plain
prose, twice, when the real tool manifest didn't contain what it claimed —
`_parse_transcript()` reads ONLY structured `tool_use`/`tool_result` blocks,
never the model's narrated text. Tests: `tests/test_settings_agent_cli.py`
(offline, against real captured transcripts in `tests/fixtures/
cli_transcript_*.json`) + a live smoke test skipped without
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

Spec: `scripts/check_settings_console.py` + `tests/test_settings_console.py`.

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
active virtuals are deactivated over its API.
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
back to a virtuals read-back when that unit is still running. It returns a
`ReleaseResult` (record/verified/problems) — the record always lands
`released`, but the API reports `result="released-unverified"` (HTTP 207)
with the specific `problems` when a device couldn't be confirmed dark,
instead of silently claiming success.
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

## Run / deploy

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
