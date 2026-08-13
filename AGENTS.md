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
