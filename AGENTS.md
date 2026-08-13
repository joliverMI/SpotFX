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

## SPECTRA app (S1+S2 — separate app, shared process until S3)

`spectra/` is the SPECTRA app (purple-on-black UI at `/spectra/`, own
FastAPI sub-app mounted in main.py; `python -m spectra` is the future S3
standalone entry). Import discipline is load-bearing: nothing under
`spectra/` imports spot-effects runtime internals — only `fx/` (shared
library, incl. `fx/device_model.py`) and stdlib/third-party; music/state
inputs arrive via the S2 read-only bridge (below), which degrades to 0.5
neutral intensity when down (stated). Its scene model (`spectra/models/scene.py`) grows SceneV2
with value bindings (+`dice` correlation), a four-class `responses` block
(legacy `flare_bands` loads as the flare class), drift declarations, and
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

## SPECTRA S2 evolution engine (runs DARK until S3)

The engine (`spectra/services/engine.py` wires it; the HOST lifespan in
main.py owns start/stop — Starlette never runs a mounted sub-app's
lifespan): drift conductor (`drift_conductor.py` — creep/follow legs +
the room colour journey, ~20 s legs), response engine
(`scene_response.py` — the four classes execute bands: patch jumps, gain
envelopes, dice re-rolls, flare colour jump via the shipped selector;
surges CARRY — baselines move permanently), read-only bridge
(`bridge.py` — WS client on spot-effects' /ws + `analysis_reader.py`;
classification: charge/lull/drop stay themselves, scene-family event
types are observations, everything else is a flare). Every glide/jump
goes through the ONE executor seam (`fx_executor.py`): production =
RecordingExecutor (DARK — records and models, never writes; the engine
must never call fx_seam), headless tests = FacadeExecutor driving the
fx/ tween engine. S3 goes live by swapping the executor — nothing else
changes. Specs: `scripts/check_drift.py` (conductor), check_spectra.py
(responses/bridge/Mid Group), `tests/test_spectra_engine.py`
(frame-level proof on the dummy device).

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
a later wiring stage. Do not enable the facade against live hardware
until Stage 2+ resolves Hue-DTLS / DDP single-sender exclusivity with the
running LedFX service.

## Run / deploy

SpotFX runs as the **user systemd unit `spotfx.service`** (`.venv/bin/python
main.py`, port 8000). Backend changes: `systemctl --user restart spotfx`.
React UI (`/app/`) is served from `web/dist` — rebuild with
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

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
