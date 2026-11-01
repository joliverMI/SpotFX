---
name: tv-display
description: >
  The TV display plan (data/tv-display-plan/{report.md,plan.html}), phase 0
  and phase 1: the TV probe page (spectra/services/tv_probe.py), the small
  TV app (spectra/web/src/tv/, its own Vite build), its one WebSocket feed
  (spectra/services/tv_feed.py, spectra/api/tv_feed.py), SpotFX's
  GET /api/jukebox/tv relay, and "one tap" (spectra/services/tv_launch.py,
  spectra/api/tv_launch.py, the "Put on the TV" button, a Light Show HA
  step, Sonic's put_on_tv op, the optional auto-open at a jukebox night's
  start). Load before touching any of these files, before adding a TV
  screen/setting/action, or before a report shaped like "the TV didn't open
  / the wrong screen is showing / a clock looks off / the auto-open fired
  when it shouldn't have."
---

# The TV display plan

AGENTS.md's own TV sections and each module's module docstring are the
binding statements. The Media Room Vizio is explicitly OUT OF SCOPE
everywhere in this build (the Admiral's one note on approving the plan) —
no targeting, discovery, or fallback to it anywhere.

## The shape, cold

1. **The TV app is its OWN small build, served by SPECTRA, never its own
   process.** `spectra/web/vite.tv.config.ts` (base `/spectra/tv/`) builds
   to `spectra/web/tv-dist/`, mounted in `spectra/app.py` as a static `Mount`
   at `/tv` — registered AFTER the probe page's explicit route (`/tv/probe`)
   so that explicit route keeps winning once the mount exists, and BEFORE
   the main SPA's catch-all. Rebuild it with `cd spectra/web && npx vite
   build --config vite.tv.config.ts` whenever `spectra/web/src/tv/*`
   changes — the main app's own `npx vite build` does NOT touch it.
2. **SPECTRA never talks to the TV directly.** One Home Assistant script
   (River's own, default `script.tv_open_spectra`) owns "open the TV app" —
   `spectra/services/tv_launch.py`'s module docstring is the binding
   statement. Every caller — the Jukebox page's "Put on the TV" button, a
   Light Show HA step (`ha_put_on_tv`), the optional auto-open poller, and
   Sonic (`put_on_tv`, in the `jukebox` domain, asks first) — funnels
   through its ONE function, `put_on_tv()`, into
   `ha_client.call_service("script", "turn_on", ...)`. Inert without
   `SPECTRA_HA_URL` configured, structurally (`ha_client.py`'s own "unset
   URL == inert" rule) — no second gate was added on top of it.
3. **The feed is ONE WebSocket, client-initiated ping.** `spectra/services/
   tv_feed.py` — hello/config handshake, an NTP-style clock (the TV asks,
   the server answers with two timestamps bracketing whatever work happens
   between them, which is what makes the offset formula survive a server
   stall), a 4 Hz show-clock push, the layout director (`resolve_layout`:
   sleep after 10 idle minutes, else attract-while-a-running-night's-board-
   is-stale-past-3-minutes, else the plain party/attract split), and a
   relay of SpotFX's own `GET /api/jukebox/tv` (PR 1.3,
   `services/jukebox/guests.py::tv_view()` — now/votes/next 3/board/link,
   no Spotify call).
4. **The auto-open poller is its OWN always-running task, independent of any
   connected TV.** `tv_launch.run_auto_open_supervised`, wired in
   `spectra/app.py`'s lifespan — polls SpotFX's `/api/jukebox/tv` on its own
   10 s cadence (`tv_feed.run_jukebox_loop`'s per-connection poll only runs
   while a TV is already open, which defeats the point of auto-OPENING one).
   Fires on the RISING EDGE of `running`, ONLY while `auto_open_enabled`
   (default OFF, the plan's own Q4: "a TV switching itself on is
   surprising"), and NEVER on the very first poll of a fresh process even if
   a night is already running (a restart during an ongoing night must not
   re-trigger — the same "a fresh tracker starts just became active, never
   already idle" reasoning `tv_feed.ActivityTracker` already states for the
   identical restart hazard).
5. **The screens are pure functions of feed state, proven over simulated
   time, not a browser's wall clock.** `burnIn.ts` (drift/corner-swap/card-
   rotation) is checked by `scripts/check_tv_burnin.mjs` (wired into pytest
   via `tests/test_tv_burnin.py`) over simulated 10+-minute windows — no
   element may stay static for MORE than 10 minutes (a window of EXACTLY
   10 minutes, aligned perfectly to a period, can legitimately show zero
   change — check any "no element static" claim with windows strictly
   longer than the period in question, not equal to it).
6. **Real-browser proofs use raw CDP over `websockets`, never
   `chrome-devtools-axi`** (its known `pageId` bug on this host). A naive
   per-call `ws.recv()` racing a separate event-listener loop on the same
   connection non-deterministically steals replies — every check script
   here uses a `CDPSession` class with ONE background reader demuxing
   replies-by-id from unsolicited events (`check_tv_app_shell.py`,
   `check_tv_party_screen.py`, `check_tv_attract_sleep.py`,
   `check_tv_probe_page.py`).
7. **No TV call in any test, anywhere.** Every test injects a fake
   `ha_client.call_service` / `tv_launch.put_on_tv` / `fetch_running` — the
   module docstrings say so and the tests prove it structurally (no httpx
   import reachable without the injection seam).

## Files

- `spectra/services/tv_probe.py` + `spectra/api/tv_probe.py` — the probe
  page (PR 0.1), self-contained HTML/JS, no React.
- `spectra/web/src/tv/*` — the TV app (PR 1.1-1.5): `TvApp.tsx` (the
  three-plane shell + sleep short-circuit), `VisualPlane.tsx` (the haze,
  dims during attract), `InfoPlane.tsx` (Party/Attract split),
  `SystemPlane.tsx`, `PartyScreen.tsx`, `AttractScreen.tsx`,
  `SleepScreen.tsx`, `ConnectionOverlay.tsx`, `burnIn.ts`, `clock.ts`,
  `feed.ts`, `useFeed.ts`, `partyLogic.ts`, `jukeboxTypes.ts`.
- `spectra/services/tv_feed.py` + `spectra/api/tv_feed.py` — the WS feed
  (PR 1.2).
- `services/jukebox/guests.py::tv_view()` + `routers/jukebox_router.py`'s
  `GET /tv` — SpotFX's relay target (PR 1.3).
- `spectra/services/tv_launch.py` + `spectra/api/tv_launch.py` — "one tap"
  (PR 1.6): `TvLaunchConfig`, `put_on_tv()`, `run_auto_open_supervised`.
- `spectra/services/show_actions.py`'s `ha_put_on_tv` action kind (the "ha"
  group, alongside `ha_volume_absolute`/`ha_activate_scene`).
- `spectra/services/jukebox_console.py`'s `put_on_tv` Sonic op — filed
  under the EXISTING `jukebox` domain (not a new one), the one named
  exception to that module's "every op is an HTTP call to SpotFX" rule
  (this one is SPECTRA-native, in-process).
- `spectra/web/src/jukebox/JukeboxPage.tsx`'s "Put on the TV" button +
  `queries.ts`'s `usePutOnTv` — the ONE `apiPost` (SPECTRA-native) call on
  an otherwise all-`spotfxPost` page.

## Sonic reach

`put_on_tv` (domain `jukebox`, write, asks first) — optional
`script_entity` override, otherwise the configured script. Reads/writes of
`auto_open_enabled`/`script_entity` itself have NO dedicated Sonic op yet
(a named gap, not forgotten) — they're reached today only through
`GET/PUT /api/tv/launch-config` directly.

## Specs

`tests/test_tv_probe.py`, `tests/test_tv_app_shell.py`,
`tests/test_tv_feed.py`, `tests/test_jukebox_tv_feed_endpoint.py`,
`tests/test_tv_burnin.py`, `tests/test_tv_launch.py`,
`tests/test_tv_launch_api.py`, `tests/test_show_ha_actions.py` (the
`ha_put_on_tv` section), `tests/test_jukebox_console.py` (the "one tap"
section), `tests/test_settings_agent_cli.py` (the `put_on_tv` widening
fixture). Real-browser (manual, not in the fast pytest loop):
`scripts/check_tv_probe_page.py`, `scripts/check_tv_app_shell.py`,
`scripts/check_tv_party_screen.py`, `scripts/check_tv_attract_sleep.py`.
Pure-logic (`.mjs`, in pytest via subprocess): `scripts/check_tv_clock.mjs`,
`scripts/check_tv_party.mjs`, `scripts/check_tv_burnin.mjs`.
