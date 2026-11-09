# SPA/UI infrastructure, the release button and tests

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

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

## SPECTRA icons are inline SVG, never a raw Unicode character — his "appears as an X" report (2026-10-06)

Found 2026-10-06: "Force colour" and "Snap generated cues to beat" both
showed an X instead of their power-toggle glyph on his screen.
Root cause: `PowerButton.tsx` (used by scenes, colour sets, flares, Force
Colour, "Snap generated cues to beat", and more) rendered the raw
character `⏻` (U+23FB POWER SYMBOL) and relied on the viewer's font stack
having a glyph for it — a Miscellaneous Technical codepoint several UI
fonts lack, which falls back to a missing-glyph box (an "X" on some
platforms). `spectra/web/src/components/{iconRegistry.ts,Icon.tsx}` is
the fix: every icon is a hand-authored inline SVG path, so rendering never
depends on font coverage. `iconRegistry.ts`'s `ICONS` map is the one
registry; `Icon`'s `name` prop is the closed `IconName` TypeScript union
(an unregistered name is a compile error — `tsc --noEmit` runs as part of
`npm run build`), and `scripts/check_icon_registry.mjs` is the second,
independent check (every real `<Icon name="...">` call site across the
app, verified against the registry; also fails if the raw U+23FB
character reappears anywhere). Add a new icon by adding a key to
`ICONS`, never by embedding a Unicode symbol character directly in JSX —
that's the whole class of defect this exists to close.

## The Release-to-Home-Assistant control is small, iconic, and hold-to-confirm

His ask, 2026-10-06: SPECTRA now runs his everyday house lighting (see the
HOUSE LIGHTING section above), so releasing the room is rare and
consequential — the opposite of the always-reachable, no-confirmation
button `RoomOwnershipBar.tsx` shipped with originally.
`spectra/web/src/components/ReleaseButton.tsx` is the control now
(mounted at the right end of `RoomControlsBar.tsx`'s row, after
brightness): a small icon button requiring roughly a one-second
press-and-hold (`spectra/web/src/lib/useHoldToConfirm.ts` — pointer AND
keyboard, Enter/Space held down; visible progress via an SVG ring whose
`stroke-dashoffset` tracks live progress). A short tap/keypress shows
"hold to release" and does nothing. `RoomOwnershipBar.tsx` keeps only the
activation/dark-fixture strips and the full-width released banner — its
own always-reachable button is gone, moved here; the way back from
`released` is unchanged.

**Did not actually hold on his phone — fixed 2026-10-09.** His report:
"I tried pressing and holding the release to home assistant button on my
phone and it didn't seem to work." Both this button's `.release-hold-btn`
and the Mode chip's `.mode-chip-link` (ModeChip.tsx, the other button
built on this same `useHoldToConfirm.ts` hook) shipped with `touch-action:
manipulation` — which still lets the browser claim an ordinary finger's
small in-place drift as an intended pan/scroll and fire a native
`pointercancel` at the element well before the hook's ~1s duration
elapses, on a button this small (28-30px). Measured under real
touch-emulated pointer events (chrome-devtools-axi's snapshot/eval tools
hit the known `pageId` bug on this host — worked around with raw CDP over
a locally-launched Playwright Chromium, per the standing memory note on
that workaround): ~18px of drift was enough to cancel it, well within an
ordinary held finger's wobble. Fixed by setting `touch-action: none` on
both classes instead — the established pattern every drag-style control
in this app already uses (`ShapeControls.tsx`, `PaletteCard.tsx`,
`SpectraTriggerBar.tsx`, etc.) — which leaves the whole gesture to the
hook's own pointer handlers; mouse/keyboard behaviour is unchanged
(`touch-action` only affects touch). **Any future hold-to-act button
built on `useHoldToConfirm.ts` (or any other pointer-driven hold/drag
gesture) needs `touch-action: none` on the bound element, not
`manipulation`** — the latter reads as "touch-safe" but only suppresses
double-tap-zoom/pinch-zoom-delay, not the pan-gesture takeover that
breaks a stationary hold. Spec: `scripts/check_touch_press_hold.mjs`
(§1 is the direct CSS regression; jsdom can't synthesize a real browser's
native `pointercancel`, so §2-§4 prove the hook's own pointer/keyboard/
mouse contract is otherwise unchanged, against the real components under
a hand-driven fake clock; §5 onward cover the other hold targets, below).

**The same investigation widened to every OTHER hold/long-press button in
the app (follow-up review, same day) — grep for `useLongPress(` and
`useHoldToConfirm(` call sites before adding a new one, this is the
complete list.** Four more targets share `spectra/web/src/lib/
useLongPress.ts` (fire-after-N-ms, no visible progress — a different hook
from `useHoldToConfirm.ts` above, but the same touch-safety requirement):
`TopBarGroupButton.tsx` (Mode/Ambient's hold-to-expand — its own
`.top-bar-group-btn` carried the identical `manipulation` bug, fixed the
same way), `PaletteCard.tsx` (hold a palette key to edit it),
`ShapeControls.tsx` (hold the ⚡ button to pick its intensity source), and
`ColorSetsPage.tsx` (hold ▶ Preview to pause the room up to 60s — this one
had **no touch protection at all**, not even `touch-action`, the most
broken of the four). `ShapeControls.tsx`'s own hand-rolled band buttons
(hold+drag to scale, a different gesture that rolls its own pointer
handlers rather than using the hook) already had `touch-action: none` but
were missing the other two.

Two changes make this "one shared hook" rather than four separate
patches: `useLongPress.ts` itself now binds `onContextMenu` (prevents the
browser's own press-and-hold menu/callout) AND `onPointerCancel` (a real
gap found here — only `onPointerUp`/`onPointerLeave` cancelled before;
a native gesture takeover firing `pointercancel` left the timer running,
risking a stale fire after the browser had already taken the touch away)
— every current and future caller gets both for free. A new shared CSS
class, `.long-press-target` (touch-action: none, -webkit-touch-callout:
none, user-select: none, both -webkit- and plain), covers the three
plain-inline-styled buttons (`TopBarGroupButton.tsx`'s own `.top-bar-
group-btn` already had its own copy of the trio, just with the wrong
`touch-action` value, fixed in place rather than switched to the shared
class). Spec: `scripts/check_touch_press_hold.mjs` §5-§8b (CSS regression
for both classes, the hook's own pointer/keyboard contract including the
two new wires, a real mount for `ShapeControls.tsx`, and real mounts for
`PaletteCard.tsx`/`ColorSetsPage.tsx` driving a held pointer through
their real query hooks — fetch intercepted, not a source-text check —
to prove the editor/preview actually opens, not just that the className
sits next to the binding).

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

**`xcorr_monitor` IS THE POST-LOCK DRIFT MONITOR — it only ever runs after a
song HARD-LOCKS, so no absence of it is evidence about a song that has not.**
That is the whole of the 2026-09-08 defect: the lock badge was driven by that
WS alone, so with no monitor message and any stored offset it printed the
literal string "Lock idle" — a song still searching, one that finished at
grade F, and one genuinely idle after a good lock all read identically. His
report, verbatim: when a song has not locked the badge "should be failed or
still trying". The per-play SWEEP, where searching and failing actually
happen, is `services/auto_offset_service.py`; it now REPORTS its lifecycle
through `services/lock_state.py` (four phases; its module docstring is the
binding statement) as both a `lock_state` push and a copy on every `state`
broadcast — the push-plus-poll-backstop shape, one store field, so a client
that connects mid-song is never blind. Three things before touching any of it:

- **THE TERMINAL SIGNAL MEANS "THE ENGINE STOPPED SEARCHING", never "the
  windows ran out" and never "`lock_history` was written."** A weak result
  calls `note_outcome(locked=False)`, which records the numbers and LEAVES the
  phase at `searching`; only `note_search_ended()` resolves it, wired today as
  the sweep task's own done-callback (so a search can never outlive the task
  doing it). The keep-searching engine below keeps its task alive, so the
  phase stays `searching` by construction.
- **THE BADGE'S DECISION IS ONE PURE FUNCTION**, `web/src/components/
  lockBadge.ts`, kept out of React so `scripts/check_lock_badge_states.mjs`
  can transpile the real module with esbuild and drive the whole table (it
  carries the pre-fix rule alongside as its own red control). Its invariant:
  **`Lock idle` is reachable from EXACTLY ONE input — a search that ended in a
  hard lock whose live monitor has since gone quiet.** Never widen that; a
  song nobody checked says "Not checked", and one we have not heard about yet
  says "Lock unknown", because "we did not check" and "we checked and it was
  fine" are different facts.
- **NOTHING THIS REPORTS MAY REACH A TIMING DECISION.**
  `tests/test_lock_state_badge.py` asserts by AST that every `lock_state.*`
  call in the sweep is a bare statement whose value is discarded, that
  `lock_state` imports none of the timing kernels, and that
  `xcorr_core`/`xcorr_sweep`/`lock_history`/`trigger_engine` never mention it.
  The `offset_ms` it carries is a display copy with its own row in
  `docs/SPECTRA_TIMING_CONVENTIONS.md`'s master table.

**A PLAY THAT DRAINS ITS PLANNED WINDOWS WITHOUT A HARD LOCK KEEPS SEARCHING
(2026-09-15, `spotfx-lock-early-window-exhaustion`, the Admiral: "if it has
low confidence, it should keep spike detection on to try to get better").**
`services/xcorr_sweep.py`'s `KeepSearching` docstring is the binding
statement. A song's planned windows can all sit near its start, and the loop
used to `break` the moment that queue drained, so MAYDAY stopped 32 s into a
4-minute song. It now places one spike-targeted window (`mismatch_spike`, the drift
monitor's own placement) every 5 s through the ordinary per-window gates,
hands off to the post-lock path on a lock, and gives up with a named reason
— `nothing_to_find` (45 s of song, no usable measurement), `no_time_left`
(the last 30 s, where no window is planned), `nothing_admissible` (below),
`user_verified` — holding
`_watching_uri` so the next poll cannot relaunch and overwrite "Lock failed"
with "Not checked" (the pre-change sweep did exactly that). Six things
before touching it:

- **It is armed at ONE exit only**: planned queue empty AND
  `_locked_via_stop` False. A play that ever locked — including a drift-monitor
  recovery whose re-armed queue just drained — keeps its old exit, which is
  what makes the early-lock and post-lock paths byte-identical.
- **A play that continued can end AFTER its song did** (a track change cancels
  it, and `app_state` already holds the next song's Set List and duration),
  so its end-of-play writes — anti-corr streak, `lock_history`, the final
  `_save_offset` — take the `PlayContext` snapshot the play started under. A
  play that never continued still reads live state, byte-identically. Anchor
  matching stays live during the continued search, by decision.
- **A continued window carries the envelope the U-Score planner would assign
  a window at that exact position.** The envelope clip looks a window up by
  its exact bounds in the planner's stored windows, so a spike-placed window
  had none and the clip was silently a no-op — in exactly the stretches the
  planner rejected as too self-similar to place a window. The shared
  `uscore_planner.window_envelope` (which `plan_uscore_windows` itself now
  calls, output proven identical against the pinned ref) is applied over the
  planner's own full-song bands and beats (`ContinuedEnvelopes`, built once
  when the search engages) and registered in the evaluator's lookup before
  each window runs. A new place a window can come from needs the same
  treatment, or the clip will not see it. **That envelope is floored at
  ±`xcorr_save_confirm_tol_ms` (300ms) ONLY where the planner's own gate
  failed** (`_floored_envelope`: total width under `_MIN_TOTAL_ENVELOPE_MS`,
  100ms) and used verbatim otherwise — a side the planner measured narrower
  than 300ms is a twin it found, never widened. 124 of 563 of his uscore-v8
  songs, MAYDAY included, carry a ZERO-WIDTH (0, 0) envelope on every
  planned window — force-picked past that gate — which admits only a
  measurement equal to the engine's offset to the millisecond, so after the
  first off-grid snap the continued search could neither confirm nor
  correct. 300ms stays under a one-beat twin (500ms at 120bpm). And **clipped
  continued windows against an unchanging engine offset give up as
  `nothing_admissible` only once they have spanned the same 45 s budget
  `nothing_to_find` uses** — the OLD measurement still casts votes there, so
  without it such a play burns a window every 5 s to `no_time_left`; it is no
  faster because a clip belongs to the STRETCH (a clearer section later can
  still lock) and a clipped window's OLD vote still feeds agreement and
  lock-and-stop. **The clip holds at EVERY ladder
  stage for a continued window** (`_envelope_exempt`): the global stage still
  exempts planned and drift-recovery windows, never a continued one, because
  the ladder gets there without any clip firing (empty continued windows, an
  escalated plan, an anti-correlated baseline). THE TRADE-OFF, stated: once
  the engine has snapped, a continued window cannot make a LARGE correction
  the envelope rejects at its position; a cold start still can (play-best 0
  skips the clip), and anything inside the envelope is untouched — it refuses
  probably-wrong locks, not better ones. **A clipped continued window
  leaves no other trace**: the search ladder does not hear it (counted empty,
  a run of them walks into the global stage) and the evidence accumulator
  does not take its landscape (the clip only
  nulls the discrete NEW; the accumulator's own save and lock-and-stop never
  read the envelope). Both are scoped to continued windows — planned and
  drift-recovery windows are unchanged — and beyond them a continued window
  chooses AND SAVES exactly like a planned one (his ruling, "it should save
  also"). **His room runs the FFT kernel, accumulator, ladder and progressive
  matching** (`storage/settings.json`), so a proof on the driver's default
  legacy-kernel `SETTINGS` says nothing about it: `LIVE_FLAGS` is that path.
- **Evidence is a confirmation VOTE** (the evaluator's
  `confirmation_shifts` grew), and a continued window may not re-measure more
  than the U-Score planner's own 1 s of audio: the same seconds scored twice
  would manufacture agreement out of one measurement.
- **`tests/sweep_world_driver.py` drives the REAL `on_track_change` →
  `_detect_loop_xcorr`** over a scripted world (only capture, math kernel,
  engine and disk replaced) and can load the pinned pre-change module out of
  git (`BASELINE_REF`); `tests/test_keep_searching.py` compares whole traces
  against it. Reuse the driver for any future sweep-control-flow change
  rather than modelling the loop.
- The badge's Searching half fell out of the terminal-signal design by
  construction; the one thing that did not was "Searching… 4/4" printing a
  finished fraction on an unfinished search — hence `continued`/
  `continued_windows`, added ONLY to plays that continue. The debug page
  holds itself to the same rule: a continued window's `xcorr_spike` carries
  `source: "keep_searching"` and `web/src/debug/spikeLine.ts` (and its
  `spectra/web` twin) never files it under "Mismatch spikes (recovery
  windows)" (`node scripts/check_debug_spike_lines.mjs`).

