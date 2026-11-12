<!-- firstmate:maintained-by-project -->
# SpotFX — agent notes

> Size budget: keep this file under ~40 KB. It loads in full on every agent
> request in this repo, so it is the single largest fixed cost of working
> here. New detail belongs in the owning doc under `docs/` (an existing doc
> when one already owns the subject, otherwise `docs/agents/<topic>.md`),
> not in this file. If a new rule is genuinely safety-critical — it must
> hold even for an agent who never opens another file — add it to the
> Safety rules section below instead; everything else is a pointer.
>
> On 2026-11-09 this file was trimmed from ~930 KB/14,054 lines to the
> short core below plus a routing table into `docs/agents/`. Nothing was
> deleted — every section moved verbatim into one of the files the routing
> table names, except the few short passages excerpted inline here and the
> self-referential "maintaining this file" note at the very bottom (both
> listed, with reasons, in PR fm/spotfx-trim-agents-md).

## Safety rules (read these; they must hold even if you read nothing else)

- **No live access from tests, ever.** The test suite (`pytest`) must never
  reach a real LedFX instance, a real Hue/WLED device, a real Spotify
  account, or the live `spotfx.service`/`spectra.service` processes. Fakes
  and harnesses exist for exactly this reason — use them.
- **A worktree isolates the filesystem, not the network.** `127.0.0.1:8000`
  (spot-effects) and `:8010` (SPECTRA) reach the real, live, owner-facing
  instances from inside ANY worktree on this host, including yours. A
  worktree's own `storage/spectra/*.json` is gitignored and untracked —
  it is whatever was copied in when the worktree was created, not proof of
  current live state. Never point `fx/` (the vendored LedFX render
  pipeline) at live hardware outside the handover-gated S3 path
  (`docs/SPECTRA_PROCESS_SPLIT.md`, `docs/SPECTRA_HANDOVER.md`).
- **Restarting a live unit is not a no-op.** `systemctl --user restart
  spectra` re-activates the live room if SPECTRA owns it: it reconnects
  Hue entertainment streams and can fire a real scene as a visible,
  un-undoable side effect in his physical room. Restarting `spotfx`
  (spot-effects, port 8000) while SPECTRA owns the room is its own hazard
  in the other direction: spot-effects runs the only reverse proxy onto
  `/spectra/*` (`services/spectra_proxy.py`), so every port-8000 address —
  including his real remote path — goes unreachable for the length of the
  restart even though `spectra.service` itself keeps running; it also
  tears down the live WebSocket bridge SPECTRA's engine depends on for
  music state, degrading the room's automatic behavior to the documented
  neutral fallback (0.5 intensity, no bridge-relayed events) until it
  reconnects. Never restart a live unit to "test" something; use an
  isolated instance on a spare port instead.
- **Never `pkill -f` a bare module-invocation pattern** (e.g. `python -m
  spectra`) to stop your own isolated instance — it matches his real live
  process too, and SIGTERM-ing it can retrigger the resume logic above.
  Kill by the exact PID your own process launch returned, or by a pattern
  that includes a marker unique to your instance (a spare port, an env var
  you set such as `SPECTRA_STORAGE_DIR=<your temp path>`).
- **No automated audio or light action while the house is asleep.** Night
  runs, Absorb Music and the Jukebox's capture lane all gate on the house's
  own sleep/availability signal (`docs/agents/night-run-and-capture-client.md`,
  `docs/agents/absorb-and-jukebox.md`) and must never drive sound or light
  against it. If you add a new automated path that can touch sound or
  light, it must check that gate before acting, not after.
- **His data is not yours to silently change.** A scene's or setting's
  stored data is not proof he authored it — "migrated from legacy" proves
  only that something is old, not that he put it there
  (`docs/agents/scenes-and-flares.md`). Never have an automated or
  AI-assisted write path (including Sonic, the settings agent) silently
  overwrite his authored triggers, scene data, or settings: every such
  write distinguishes authored-by-him from generated/automated, asks first
  for anything consequential, and is backed up with an undo path. When
  editing a stored model via script, mutate the raw dict for the one field
  you intend to change — re-serializing the whole object through its model
  class can silently rewrite other fields into a newer canonical shape.
- **Secrets hygiene (this is a public repo).** Never commit an API key,
  bearer token, or other secret. Every secret-bearing value in this
  codebase (`SPECTRA_HA_TOKEN`, `SPECTRA_PRETAKE_TOKEN`,
  `SPECTRA_WITNESS_TOKEN`, `SPECTRA_NIGHT_RUN_TOKEN`, `ANTHROPIC_API_KEY`,
  `CLAUDE_CODE_OAUTH_TOKEN`, etc.) is read from the environment at call
  time — never hardcoded, never logged, never written to a committed file.
  Preserve that pattern in any new secret-bearing code.
- **Merging a PR does not deploy it.** The live `spotfx.service` (port
  8000) and `spectra.service` (port 8010) run whatever was last deployed
  and restarted on the host, independent of what's merged to `master`.
  Don't report a change as "live" or "in production" because it merged.
- **Deploy recipe, and its hazard.** A backend change needs the owning
  unit restarted: `systemctl --user restart spotfx` (spot-effects) or
  `spectra` (SPECTRA) — never both reflexively, restart only the unit that
  owns the changed code. A `spectra` restart auto-resumes the room if she
  owns it (see the restart hazard above). A frontend-only change needs no
  restart — rebuild `web/dist` (`cd web && npx vite build`) or SPECTRA's
  own `spectra/web` build and refresh the browser.
- **The human tuning gate on new effects.** Follow
  `docs/ADDING_EFFECTS.md`'s full checklist when adding a new LedFX effect.
  The gate is deliberate: Javi tunes an effect's defaults live, in his
  room, before any scene is seeded with it — never seed a scene with a
  new effect ahead of that tuning session.
- **The help-content rule.** Whenever you add or change a user-facing
  SPECTRA feature — a page, keyboard shortcut, gesture, filter syntax,
  mode, or setting — update `spectra/web/src/help/helpContent.ts` in the
  same change. Treat it as part of the definition of done, not an
  afterthought; `docs/agents/ui-infra-and-tests.md` has the full
  authoring/orphan-audit detail.

## Timing conventions — one more safety-shaped rule

Two families of timing quantity in this codebase use **opposite sign
conventions for "earlier"** (a `lead_ms` family, positive=earlier; an
`offset_ms` family, negative=earlier), both live simultaneously in
`spectra/services/trigger_engine.py`'s `tick()`. Mixing them up is silent
and has cost real time more than once. `docs/SPECTRA_TIMING_CONVENTIONS.md`
is the canonical, file:line-cited record of every timing/offset/lead/delay
quantity in the codebase, its unit, its sign convention, and which engine
owns it — read it before writing, measuring, or reasoning about anything
time-related.

## Orientation

- Tests: `pip install -r requirements-dev.txt && python -m pytest` (plain
  pytest, no async plugin — tests drive their own loop). See
  `tests/conftest.py` for the fake-LedFX harness and the autouse isolation
  fixtures referenced throughout `docs/agents/`.
- Before touching anything under `spectra/`, read `docs/SPECTRA_SPEC.md` —
  the live reconciliation surface for every SPECTRA-relevant capability's
  honest state, the Admiral's standing decisions, and every open question.
  It supersedes the one-time capability audit it's built from wherever the
  two disagree; it carries its own maintenance protocol.
- `.claude/skills/` carries one skill per live effect and per live scene
  (cold-start knowledge an agent needs before touching that effect/scene —
  param meanings, Sonic reach, non-obvious invariants) plus a handful of
  cross-cutting skills (`sonic-ops`, `house-lighting`, `house-scenes`,
  `absorb-music`, `drop-detection`, `tv-display`, `led-gif-assets`,
  `sung-labels`). `effect-design` is the design PROCESS (interview →
  visual comparisons → confirmed plan) for building or improving any
  effect, scene, flare kind, transition or drop-sequence effect — load it
  when he says "I want to build a new ..." or "I want to improve ...".
  `.claude/skills/EFFECT_SCENE_MAP.json` maps which files trigger which
  skill, and `scripts/check_effect_scene_skills_current.py` (run by
  `tests/test_effect_scene_skills_current.py`) FAILS a branch that changed
  a mapped effect/scene file without updating its skill, or that adds a
  new registered effect with no skill and no entry in
  `acknowledged_effect_gaps`. Whenever you change an effect's or scene's
  behaviour, update that effect's/scene's own `SKILL.md` in the same
  change — treat it as part of the definition of done, exactly like
  `helpContent.ts` above.

## Routing table — read the named doc before touching the named thing

| When you touch… | Read |
|---|---|
| Timing/offset/lead sign conventions anywhere | `docs/SPECTRA_TIMING_CONVENTIONS.md` |
| Adding a new LedFX effect, the tuning gate, scene seeding order | `docs/ADDING_EFFECTS.md` |
| Designing a NEW or IMPROVED effect/scene/flare kind/transition/drop-sequence effect with him (the interview, the explainer, the plan he confirms) | `.claude/skills/effect-design` |
| The in-app Help page, `helpContent.ts`, deep links, orphan topics | `docs/agents/workflow-conventions.md`, `docs/agents/ui-infra-and-tests.md` |
| SPECTRA's own capability/decision ledger | `docs/SPECTRA_SPEC.md` |
| SceneV2, scene authorship, the two trigger-store copies, trigger authoring, transition timing/programs, the known-audio-buffer, Energy, per-song intensity scale, fire-history, feedback sessions | `docs/agents/scenes-and-flares.md` |
| The SPECTRA app process, the S2 evolution engine (drift conductor, response engine, bridge, flare kinds, colour journey, dwell, mode availability, Force Scene/Colour, House Modes overriding display) | `docs/agents/spectra-engine-core.md` |
| Sonic / the settings console, per-item mode availability, per-scene colour-set preference, likelihood curves, minimum dwell, scrubbing previews | `docs/agents/sonic-and-colour.md` |
| The Light Show (`/show`) | `docs/agents/light-show.md`, `.claude/skills/sonic-ops` |
| House lighting (`/house`), HA seam, Hue scope | `docs/agents/house-lighting.md`, `.claude/skills/house-lighting`, `.claude/skills/house-scenes` |
| The room light-field map (`/rooms`), room effects, commissioning | `docs/agents/rooms-and-capture.md` |
| The night run (unattended/self-taking), pretake/release pings, the window, the contamination witness | `docs/agents/night-run-and-capture-client.md` |
| The unattended-capture client, the capture-client host/service, instrument visibility (`--doctor`) | `docs/agents/night-run-and-capture-client.md` |
| Per-device timing equalization, the device page, A/V-sync instrument (`/avsync`), the dark-fixture watch, the param orphan watchdog, dynamic colour, the 2D drift gradient + rainbow select, Sonic's token-usage record, S3 light ownership/handover | `docs/agents/devices-and-ownership.md` |
| `fx/` (vendored LedFX pipeline), any Matrix/Strip effect's cross-cutting mechanics (config-load ordering, background mode, the lull dark point, the strip phase layer, lull hand-off, drop shockwave, the crystal-mapper hex grid) | `docs/agents/fx-effects.md`, and the per-effect skill named in "Orientation" above |
| An individual effect (Black Hole, Fish, Sauron, Pulse, Radial/STAR, Orbits, Squiggles, Eye, Fireworks, Dancer, Pacman, Melt, Power, Gradient) | the matching `.claude/skills/<effect>-effect` skill first, then `docs/agents/fx-effects.md` for anything cross-cutting |
| SPA cache headers, SPECTRA icons, the Release-to-HA button, `/spectra/spec`, the shared TopBar, the LedFX write-plane gate, test-harness gotchas | `docs/agents/ui-infra-and-tests.md` |
| The root xcorr/lock engine's song identity, the whole-song check, `librosa_offset_ms`, backfilling trigger intensity from section energy | `docs/agents/audio-analysis.md` |
| Absorb Music | `docs/agents/absorb-and-jukebox.md`, `.claude/skills/absorb-music` |
| The Jukebox (sets, credits, guests, the capture lane, the TV relay) | `docs/agents/absorb-and-jukebox.md` |
| The music-analysis test bed (`/testbed`), lyrics, beat-snap, rhythmic edges, the scene-change planner, drop detection | `docs/agents/testbed-and-drops.md`, `.claude/skills/drop-detection`, `.claude/skills/sung-labels` |
| Touch panning, the global song timeline / `show_clock_ms`, Home, the grouped nav/one-bar layout, the design-fidelity gate, the TV display plan | `docs/agents/ui-timeline-and-tv.md`, `.claude/skills/tv-display` |

## Maintaining this file and `docs/agents/`

Keep `AGENTS.md` for the safety rules above and the routing table — nothing
else. When a change adds durable, non-obvious project knowledge, write it
into the `docs/agents/<topic>.md` (or owning doc) the routing table already
points to, or add a new routing-table row if it's a genuinely new area; do
not grow this file's own prose. Do not repeat what the codebase already
shows — point to the authoritative file, command, or doc instead. Prefer
rewriting or pruning an existing `docs/agents/` entry over appending a new
one in a different place. When a path or anchor in the routing table or in
a `docs/agents/` file moves, update the reference in the same change.
