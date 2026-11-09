# Timeline UI, song layout and the TV display

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## Touch panning + Light Show flag touch precision (2026-10-08)

The Admiral: "i want to be able to drag the audio shape graph somehow on a
tablet or phone... single finger if it would work well." The canvas's own
pointer wiring already unified mouse/touch (Pointer Events), and empty-
canvas hit-testing already ran before any drag decision — so single-finger
pan never conflicts with marker drag/scrub: no scrub-by-click existed on
this canvas, and a hit on a marker (trigger/flare/drop-seq) still wins at
`down()`, same as before. No pinch-zoom was added — no mouse-wheel zoom
exists to mirror (zoom is still minimap-edge-drag only, `TimelineBar.tsx`).

`spectra/web/src/timeline/canvas/touchPan.ts` (byte-identical twin
`web/src/builder/canvas/touchPan.ts`) is the pure direction-lock + delta
arithmetic — `resolveTouchPanLock(dx,dy)` (6px threshold, ties resolve to
pan) and `panDeltaMs` (the SAME formula the pre-existing middle-mouse pan
already used, factored out so both paths can't diverge). `TimelineCanvas.tsx`
(both twins) wires it: an empty-canvas touch arms a `touchCandidate`
(no `preventDefault` yet — undecided); the first move resolving to 'pan'
locks in and hands off to the ordinary `panStart` path; resolving to
'vertical' clears the candidate and lets the browser's own page scroll
take over. The canvas's `touchAction` changed from `'none'` to `'pan-y'`
to let that vertical scroll through — which meant every marker-drag branch
now needs its own explicit `ev.preventDefault()` (added at the hit-branch
in `down()`) so a vertical intensity drag can't race the browser's native
pan. A `pointercancel` listener was added too (there wasn't one) — without
it a touch gesture the browser takes over could leave `dragging`/`panStart`
stuck forever with no `pointerup` to clear them.

**Hardened for multi-touch same day** (`dragging`/`panStart`/`touchCandidate`
all now carry the owning pointer's own id, checked on every `move()`/`up()`
in both twins): before this, `dragging`/`panStart` were pointer-agnostic, so
a second, unrelated pointer — a resting palm beside a panning or dragging
finger — could drive or end the FIRST pointer's drag/pan with its own
move/up. Covers every drag branch (marker drag, context-menu drag, mouse/
touch pan), not just the Light Show flag below. Exec spec: `scripts/
check_timeline_canvas_pointer_isolation.mjs` (+ `tests/
test_timeline_canvas_pointer_isolation.py`) — mounts the real component
(both twins) under jsdom via react-dom/client and dispatches real
multi-pointer `PointerEvent`s, asserting on the `pointer` prop's own
callback invocations.

Exec spec: `scripts/check_timeline_touch_pan.mjs` (+ `tests/
test_timeline_touch_pan.py`), the `followWindow.ts`-style pure-module
pattern — transpiles the twin files and proves byte-identity + the lock/
delta arithmetic. Manual proof: a raw-CDP Python driver against a
throwaway Vite harness (`chrome-devtools-axi` has the known `pageId`
bug on this host — see the memory note on driving raw CDP instead),
`Input.dispatchTouchEvent` + `Emulation.setDeviceMetricsOverride`, at
phone (390×844) and tablet (1024×768); confirmed visually both sizes.
**One false alarm worth recording**: a harness debug `<p>` that grew to a
second line of text on `pointerdown` reflowed the canvas down ~18px before
the first `pointermove` landed, so a horizontal-only synthetic touch
"measured" as vertical-dominant and got the wrong lock — not a bug in the
touch-pan code, a layout-shift artifact from the DEBUG TEXT ITSELF sitting
above the canvas in the harness page. Any future manual proof that reads
live `getBoundingClientRect()` deltas between a down and a move needs a
fixed-height (or no) status readout above the canvas, or it will
reproduce this same false reading.

**The Light Show High/Low Trigger flag is now draggable directly on the
audio-shape canvas** (his second ask, same session: "i can't seem to move
the marker on the audio shape"). `canvas/lightShowLayer.ts`'s `hitTest`
(previously absent — the flag was tooltip-only, "never a click target so
a trigger under it still drags") now returns a `'light-show-flag'` Hit at
a touch-sized radius (14px, matching the `triggers` layer's own line-hit
convention) along the flag's WHOLE scan-line, not just the small glyph —
but since the `triggers` layer (z=60) is checked first in `TimelineCanvas`'s
z-descending hit order and `lightShowMarkers` is z=41, a SPECTRA trigger
under the flag still wins and still drags, unchanged. `hooks/
useLightShowDrag.ts` is the drag controller (grab-offset preserved so the
flag tracks the finger without jumping, beat-snap via `cueFlags.
snapCueMs`, live ms readout drawn on the canvas) — `snapCueMs`'s own
pixel-radius-to-ms conversion takes the canvas's own current WINDOW span
as an optional 5th argument now, not just `durationMs`: the canvas can be
zoomed narrower than the whole song, and scaling the radius off the full
song duration (the full-song `ShowCueBar.tsx` bar's own correct
assumption, below) inflated it by however far zoomed in, reaching a beat
well outside the window's own touch radius. Wired into
`BuilderPage.tsx`'s pointer chain ahead of `triggerPointer` the same way
`dropUi` already is. `frame.ts` grew `lightShowDrag` on `LayerDataBag` (the
live ghost position) and the `'light-show-flag'` `Hit` kind. SPECTRA-only
(no twin in `web/src/builder/` — Light Show postdates that frozen fork).

**`ShowCueBar.tsx`** (the full-song "large bar," his words: "trouble
precisely moving the trigger on the large bar") got the same three fixes:
a grab-offset ("no jump" — `cueFlags.rawMsAt` is the new UNSNAPPED
position-at-pointer function, captured once at drag start and reapplied
every move, instead of snapping the flag straight to the raw touch
point); a wider invisible touch target (32px vs the drawn 14px handle,
same glyph, same `CIRCLE_HIT_R`-style split between drawn size and hit
size); and a beat-snap (`cueFlags.snapCueMs`, same two-tier pixel-radius-
converted-to-ms convention the canvas trigger editor's `snapTimestamp`
uses) falling back to the pre-existing flat 20ms grid when no beats are
given. A fine-adjust path was added where none existed: ←/→ nudges the
flag 20ms (Shift = 5ms) when its handle is focused, plus a live mm:ss
readout while dragging — mirroring `dropEdit.ts`'s `NUDGE_MS` convention
on the canvas's drop-sequence editor, the strongest existing precedent for
keyboard fine-adjust in this codebase.

Exec spec: `scripts/check_show_cue_flags.mjs` sections THREE/FOUR (+
`tests/test_show_cue_flags.py`) prove the beat-snap radius arithmetic and
the no-jump grab-offset property directly.

## THE SONG-LAYOUT PLAN — one show clock, the global song timeline, Home, kiosk

2026-10-14, `data/ui-layout-plan/report.md` (+ `explainer-final.html`, his
edited copy with every decision). Four pieces, phased by the plan's own
build order — slices 3/4 (the clock, the timeline, Home, kiosk) landed
alongside slices 1/2 and the bar/settings half of slice 5 (the grouped
menu, the one consolidated bar, Settings cards) built in the parallel
`ui-build-bar` task — see "THE GROUPED MENU, ONE BAR, AND HOME" below.

- **ONE SHOW CLOCK**: `spectra/services/engine.py::current_show_clock_ms()`
  is a second READER of the exact application point
  `_run_trigger_engine` already feeds `tick()` with
  (`av_sync_lead.show_clock_ms(bridge.effective_position_ms(),
  av_sync_lead.current_lead_ms(), known_buffer.compensation_ms())`) —
  never a second computation of it. Served on `GET /api/engine/status`'s
  `bridge.track.show_clock_ms` (alongside new `artist`/`duration_ms`,
  which were already on SpotFX's own broadcast and simply never parsed
  by `bridge.py` before) and pushed once a second on the SPECTRA
  websocket as `{"type": "clock", show_clock_ms, position_ms, is_playing,
  server_ms}` (`engine.run_clock_push_supervised`, wired in
  `spectra/app.py`'s lifespan). `spectra/web/src/lib/showClock.ts` is the
  ONE client-side anchor — a plain module-level function
  (`getShowClockMs()`), not a hook, so a per-frame caller (a rAF loop)
  never triggers a React re-render; `queries.ts`'s `useShowClockSeed()`
  feeds the 3s poll in as the backstop before the first push lands.
  Fixes the pre-existing three-playhead mismatch (the Timeline page's own
  SPECTRA strips, the audio-shape canvas, and the engine's real fire
  clock could each read a different "now" for the same song — measured
  1.73s/4.5s apart on two real songs). `BuilderPage.tsx`'s
  `getStripNowMs` switches TimelineBar/SpectraTriggersCard/
  DropSequenceStrip's "played" fill AND the audio-shape canvas's own
  playhead (his own "perfectly matched" follow-up ask) to it — the old
  `getCanvasNowMs`/`getPlayheadMs` (`audio_latency_ms` subtract + stored
  shape-offset add, `drawnPlayheadMs`) are RETIRED, not merely left
  alone: that shift was misaligning the canvas playhead against its OWN
  RMS/trigger data too (already drawn at raw, unshifted song time —
  `debug/plannedEvents.ts`'s own docstring), not only against the
  strips. `canvas/layers.ts`'s shared `playhead` layer now draws
  `f.nowMs` verbatim — safe for `DebugPage.tsx` (shares the same layer
  object) because it already passed `view.offsetMs: 0` and does its own
  shifting entirely inside its own `getCanvasNowMs`, proven by
  `scripts/check_timeline_playhead_one_clock.mjs`'s behavioural check
  (a huge, wrong `view.offsetMs` changes nothing drawn, with a red
  control showing the retired formula really would have moved it).
  `audio_latency_ms` itself is untouched elsewhere (capture alignment, a
  separate job).
- **`GET /api/upcoming?uri=&limit=`** (`spectra/api/upcoming.py`): the
  merged "what will actually fire" list for one song — computed by the
  engine's OWN gating (`TriggerEngine._trigger_allowed`/
  `_effective_mode_for_song`, `analysed_flares`, `drop_firing.annotate`,
  `show_cues`), never re-derived in TypeScript. On a song where his own
  triggers fire instead of the planned analysed events, this lists HIS
  triggers; a drop-sequence member only appears when `drop_firing` says
  `fires=True` (a SUGGESTED, unconfirmed detection is excluded). Proof:
  `tests/test_upcoming_api.py`, driven against a real swept
  `TriggerEngine.tick()` — the "prove from the show side" standard.
- **THE GLOBAL SONG TIMELINE** (`spectra/web/src/components/SongStrip.tsx`
  + the pure helpers in `songStrip.ts`, spec'd by
  `scripts/check_song_strip.mjs`): a 39px strip mounted by
  `AppChrome.tsx` on every route except `/timeline` (its own full
  editing toolset) and the `/live` pop-out — INCLUDING Home since
  2026-10-15, where it also hosts the draggable window Home's audio
  shape follows (read-only everywhere else); see "THE DESIGN-FIDELITY
  GATE"'s later entries for the current mount/edit split, superseding
  the per-route "editable copy" design in the HOME bullet below.
  Markers reuse `debug/plannedEvents.ts`'s own rank-tier sizing/opacity rules and
  `timeline/dropSequences.ts`'s `PHASE_COLOR` — one definition of
  "strong", shared with the Timeline/debug canvases. The playhead and the
  fixed-96px next-event countdown move in ONE rAF loop that writes
  SVG attributes / `textContent` directly, never a React render per
  frame — measured at ~60 drawn fps over a 6s window
  (`scripts/check_song_strip_fps.py`, the `preview_perf` rig's own
  drawn-fps TECHNIQUE — a real headless Chromium + CDP, wrapping
  `requestAnimationFrame` to count real per-frame work — applied to a
  purpose-built mocked-fetch/WebSocket harness page
  (`spectra/web/harness/songstrip.html`, built alongside the existing
  harness pages by `vite.harness.config.ts`) rather than the rig's own
  `:live`/`:map` systems, which are specific to the device-preview/
  Live-view feature and need a real dummy-device fx host to drive). The
  markers themselves are rebuilt only when the song or its
  plan changes, into a dedicated `<g>` the rAF loop never touches (a
  React-managed sibling `<line>` is the playhead — clearing the wrong
  node here throws on reconciliation, don't merge the two).
- **HOME (`/`)** is now the landing page (`home/HomePage.tsx`,
  `home/HomeTimeline.tsx`, `home/HomeQuickRuns.tsx`). Its own timeline
  card — icon toggles for analysed events/drop sequences/Light Show, a
  draggable/zoomable window via `timeline/hooks/useFollowWindow`,
  TimelineBar's own `dragEdge` shape re-implemented here since
  `TimelineBar` itself is bound to the legacy `MusicTrigger`/
  `EventOption` editor model, undo/redo — was RETIRED 2026-10-15: the
  window now lives on the chrome's one global strip (shared state in
  `components/songTimelineView.tsx`), and the filter toggles/undo-redo/
  Follow controls moved onto Home's own thin control row beneath the
  shape (see "THE DESIGN-FIDELITY GATE"'s later entries for the full
  current split). Home's card today is that tuned audio-shape trace,
  aligned under the strip's track, plus the control row and the
  capped-width `.home-quick-runs` cards (Quick sequences / Quick actions,
  plus a third Drops card since the predrop plan — see "HOME'S DROPS
  PANEL" below). The audio shape's own samples are WAV-time; each is shifted by
  the song's stored `timestamp_offset_ms` to land on the SAME song-time
  axis the strip's markers use — deliberately a NARROWER reconciliation
  than the Timeline page's own `audio_latency_ms`-involving math (Home's
  shape is a glance-and-navigate view, not an editing surface). `HomeQuickRuns.tsx`
  is deliberately self-contained rather than literally extracting
  `QuickStartCard`/`SetRunRows` out of `lightshow/SequenceView.tsx`/
  `RunView.tsx` — a real follow-up, not done here, to let the Light
  Show page's own Run view and Home share one implementation.
  `main.home-route` drops the page's usual 1200px cap so Home's timeline/
  shape run edge to edge on desktop; the quick-run cards stay capped
  through their own grid.
- **THE KIOSK VIEW** (`/?kiosk=1`, `spectra/web/src/kiosk/`): a Home
  Assistant dashboard-tab iframe for a wall-mounted Raspberry Pi 7in
  touchscreen (800x480, plain http, touch-only — River's 2026-10-14
  measurement). `App.tsx` checks `kioskConfig.isKioskRequested(search)`
  BEFORE every other route, rendering `KioskPage` (no menu,
  `RoomControlsBar`/`TopBarStrip` wrapped in `.one-bar` — see "THE ONE BAR
  IS TWO-TIER" below for why 800px lands on that band's deliberate two
  rows — plus `HomePage` with its audio shape dropped). `kioskConfig.ts`
  is the ONE place the 800x480/56px-HA-header/424px-usable sizing lives,
  so a later real measurement is a one-line change. `spectra/config.py::
  kiosk_frame_ancestors()` (env override `SPECTRA_KIOSK_FRAME_ANCESTORS`)
  + `spectra/app.py`'s unconditional middleware set a
  `Content-Security-Policy: frame-ancestors` header on every response —
  the default origins are `http://homeassistant.local:8123` and
  `http://192.168.40.16:8123`. Noted, not addressed: an HTTPS Home
  Assistant view (the phone app's remote access) refuses to embed a
  plain-HTTP iframe as mixed content — the wall kiosk itself is
  unaffected (both plain HTTP, same LAN).
- **`components/IconToggle.tsx`**: the shared 30px icon-toggle component
  (report §9 idea 6) was built independently on both the `ui-build-home`
  and `ui-build-bar` sides of this plan; reconciled on the latter's own
  shape (`onChange: (on: boolean) => void`, `role="switch"`/
  `aria-checked`/`aria-label` — see "THE GROUPED MENU, ONE BAR, AND HOME"
  below) when the two landed together — `HomeTimeline.tsx`'s three
  toggles (Analysed events / Drop sequences / Light Show) call it that
  way too.

**HOME'S AUDIO SHAPE NOW DRAWS FROM THE SAME rAF LOOP AS ITS PLAYHEAD, AND
CARRIES SCENE/FLARE/DROP/LIGHT-SHOW MARKERS (2026-10-14, the Admiral: "the
audio shape isn't as responsive and it should also show scenes, flares,
drops, and light show triggers").** `HomeTimeline.tsx`'s own module
docstring has the measured before/after. The root cause, found by reading
`useFollowWindow()`: it returns a FRESH object literal every render (only
its `getWin` property is a stable `useCallback`), so the shape canvas's
trace+resize effect — keyed on `[shape, offsetMs, win]` — reran on every
unrelated parent re-render (the 3s engine-status poll) AND on every single
pointermove of a window drag, each time doing a full `canvas.width = …`
resize. **Measured with a real headless-Chromium harness
(`scripts/check_home_timeline_fps.py` + `spectra/web/harness/
hometimeline.{html,tsx}`, the `check_song_strip_fps.py` technique): before,
a synthetic drag cost 180 backing-buffer resizes over 180 pointermoves (one
per move, unconditionally); after, zero — the trace, its own marker
overlay, the window-overlay rect and both playheads all moved into ONE rAF
loop reading the window/shape/events through refs, exactly matching
SongStrip.tsx's "no React render per frame" rule and TimelineCanvas.tsx's
own "resize only when the measured size actually changed" guard.** The
strip's marker-SVG rebuild had the identical shape (rebuilding on every
`win.*` dep even though a marker's x never depends on the window) and is
now gated on `[shown, durationMs]` only. The Timeline (Builder) page's own
audio-shape canvas needed none of this — it already runs through the
shared, rAF-driven `TimelineCanvas.tsx` (`BUILDER_LAYERS`, which already
draws `analysedEvents`/`lightShowMarkers`/`dropSeqBody`) — so this build is
Home-only. The new marker overlay on Home's shape canvas is
`songStrip.ts`'s `drawShapeMarkers()` — the same `KIND_COLOR`/
`markerSizePx`/`markerOpacity` the SVG strip already draws with, just
canvas primitives instead of DOM nodes — proven pure in
`scripts/check_song_strip.mjs` §FIVE and behaviourally (real component,
real jsdom) in `scripts/check_home_timeline_responsiveness.mjs`.
**`components/songStrip.ts` and `components/SongStrip.tsx` differ only by
the case of their first letter, on purpose (songStrip.ts's own docstring),
and esbuild's bundler gets confused by that pair the moment `songStrip` is
reached as a TRANSITIVE, extension-less import from a third file (as
`HomeTimeline.tsx` does) rather than given directly as an entry point: it
case-insensitively matches the request against `SongStrip.tsx`, warns
about the mismatch, then tries to literally read the (wrong-case,
nonexistent) path anyway and fails.** `check_song_strip.mjs` never hit this
because it bundles `songStrip.ts` AS the entry point; any future script
that bundles a file importing `songStrip` transitively needs the same
one-`onResolve` esbuild-plugin workaround `check_home_timeline_responsiveness.mjs`
uses (resolve `/components\/songStrip$/` straight to the absolute `.ts`
path) — this is a test-tool-only quirk, not a reason to rename either
production file.

**`kind: "high"/"low"` ARE the Light Show's High/Low Trigger cues — not a
second concept.** `spectra/api/upcoming.py`'s own docstring and handler
read them straight off `plan["show_cues"]` (`spectra/services/
show_cues.py`), stamped `source: "show_cue"` — the exact store the
Timeline page's own `canvas/lightShowLayer.ts` flags already draw from.
Proven behaviourally — the real `/api/upcoming` handler driven as a
subprocess, and the real `drawShapeMarkers`/`HomeTimeline.tsx` bundled with
esbuild — in `scripts/check_home_timeline_light_show_markers.mjs`
(Timeline parity is its own pre-existing proof,
`scripts/check_timeline_light_show_markers.mjs`). **That same build fixed a
latent catch-all bug found while verifying it**: both HomeTimeline.tsx's
strip-marker SVG builder and `songStrip.ts`'s `drawShapeMarkers()` used to
treat "anything that isn't scene/flare/charge/lull/drop" as a Light Show
flag — which also matches `kind: "colour"` (an authored `select_color_set`
trigger, reachable through `/api/upcoming`'s "his own triggers fire
instead" branch) and drew it as a flag it is not. Both now check
`kind === 'high' || kind === 'low'` explicitly, matching `SongStrip.tsx`'s
own flag branch, which already got this right; `colour` is left undrawn
everywhere, the same silent-drop `SongStrip.tsx` already shipped. The
Timeline page's audio-shape canvas already drew every one of the
Admiral's named marker kinds (scene/flare via `analysedEvents`,
charge/lull/drop via `dropSeqBody`'s gold-wedge/blue-band/drop, high/low
via `lightShowMarkers`) before this build touched anything — confirmed,
not assumed, by reading each layer; no Timeline change was needed.

**HOME'S RMS BANDS NOW READ THE SAME SCALE MULTIPLIERS THE TIMELINE PAGE
DOES (2026-10-25, his report: "I don't like the scalings of all the rms
values on the home page. Match it to what I have right now in the
timeline graph.").** `spectra/web/src/timeline/BuilderPage.tsx` seeds its
sticky `scales` state (Total/Bass/Mid/High RMS multipliers drawn by the
shared `rmsBands`/`intensityBackground` canvas layers) from the SpotFX
settings `shape_scale_total`/`_bass`/`_mid`/`_high` (`config.py`,
tunable on `web/src/settings/SettingsPage.tsx`) via `useSticky('scales',
...)` — and persists hand-adjustments from its own `ShapeControls`
sliders to the SAME `spotfx.builder.v1.scales` localStorage key
(`spectra/web/src/lib/useSticky.ts`), which outlives the settings seed.
`HomeTimeline.tsx` used to hardcode `scales: { total: 1, bass: 1, mid: 1,
high: 1 }`, ignoring both — so the identical song's RMS fill bands drew
at a different height on Home than on the Timeline page, even though
both already render through the SAME canvas layer code
(`BUILDER_LAYERS`/`TimelineCanvas`). Fixed by having Home read the
IDENTICAL sticky key with the identical settings seed
(`spectra/web/src/lib/shapeScales.ts`'s `shapeScalesSeed()`/
`DEFAULT_SHAPE_SCALES`, the one shared definition both pages' own
`useSticky('scales', ...)` calls now draw from) — "right now" means
whatever he currently has dialed in there, hand-tuned sliders included,
not just the server default. `scaleOverall` was already `1` on both
pages (the Timeline page hardcodes it too, unlike `NowPlayingPage.tsx`)
and needed no change. Spec: `scripts/check_home_rms_scaling.mjs` (run by
`tests/test_home_rms_scaling.py`) transpiles the pure seed module with
esbuild and asserts it against the Timeline page's own inline `?? 1`
fallback.

## THE GROUPED MENU, ONE BAR, AND HOME — UI declutter plan (2026-10-14)

The Admiral's layout declutter plan (`data/ui-layout-plan/` in
fleet-spotfx, report.md + his edited explainer-final.html) replaced the
17-link flat nav and two separately-wrapping top strips. Slices 1, 2 and
the bar/settings half of slice 5 are built here; the editable Home
timeline, the global read-only song timeline, `show_clock_ms` and
`/api/upcoming` are the parallel `ui-build-home` task's own build — see
"THE SONG-LAYOUT PLAN" above, landed alongside this one.

- **The menu**: `spectra/web/src/nav/{navGroups.ts,NavMenu.tsx,NavBar.tsx}`
  — Home | Artifacts ▾ | Engine ▾ | Settings, a plain data table
  (`NAV_GROUPS`) driving the dropdowns. Feedback sits under Engine, next
  to Review. The unsaved-changes guard is STILL a capture-phase handler on
  `<nav>` reading `a.closest('a')` — every dropdown item renders INLINE
  (absolute-positioned, never portalled to `<body>`) specifically so this
  guard keeps covering it; don't portal a future menu item without
  rechecking this.
- **One bar**: `RoomControlsBar.tsx` and `TopBarStrip.tsx` are UNCHANGED as
  components (same state/hooks) — App.tsx wraps both in one `<div
  className="one-bar">`, and `tokens.css` gives each of their own root
  divs `display: contents` so their CHILDREN become direct flex items of
  `.one-bar`. Left-to-right order (house icon → display mode → Hue Hold →
  Scenes → Colour → Energy+Mark → Light Show → preview swatches → ⚠ chip →
  Release) is CSS `order` on each occupant's own class (`.one-bar
  .mode-chip { order: 1; }` etc. in tokens.css), not DOM reordering — a new
  occupant needs an `order` rule there, not a JSX move. `ModeChip.tsx`
  (house mode) is icon-only now (no cycling text); `ReleaseButton.tsx`
  uses a "plug" icon (the "home" glyph is ModeChip's now). The Scenes
  popover (`RoomControlsBar.tsx`) keeps ONLY Force Scene (moved to the
  TOP, his edit), the scene-change-tier select, and recents — every other
  tuning field that used to live there moved to Settings (below).
  `DevicePreviewStrip.tsx`'s swatches are now the expand/collapse toggle
  themselves (no separate Expand/Favourites buttons); `WarningChip.tsx`
  collapses the three full-width amber strips (`RoomOwnershipBar.tsx`'s
  `ActivationStrip`/`DarkFixtureStrip`/`HueScopeStrip`, still exported from
  there, just not rendered by that module's own default export in the
  normal path) into a small "⚠ N" popover.
- **Settings gained two direct-control cards** (`spectra/web/src/settings/
  {RoomCard,ScenesDropsCard}.tsx`), a stated exception to "talk to Sonic,
  no forms" (his own decision): Room (brightness, the drift gradient —
  `components/DriftGradientPanel.tsx`, the old `DriftGradientBar.tsx`'s
  panel content with the `TopBarGroupButton` wrapper stripped off since
  it's inline on its own page now — and the Favourites picker) and
  "Scenes & drops" (every tuning field moved out of the Scenes popover).
  Both own their own draft/commit cycle against `RoomControlState`,
  independent of RoomControlsBar's.
- **Light Show's bar slot** (`LightShowStrip.tsx`) shows current→next with
  trigger icons and a live countdown (10s lead-in fill), computed by the
  pure `showNowNext()` in `lightshow/showSummary.ts` from `useShowArms`/
  `useSequenceRunStatus` (both in `timeline/queries.ts`, cross-imported —
  an established pattern, see `DebugPage.tsx`/`ReviewPage.tsx`) folded
  together with push hooks `useLightShowBriefPush`/
  `useLightShowSequencePush` (queries.ts) onto the websocket's existing
  `light_show`/`light_show_sequence` broadcasts. Deep links
  (`/show?tab=sequence&sub=run` / `/show?tab=run`) are read once on mount
  by `LightShowPage.tsx` — a plain `?tab=` deep link in, never written
  back on a later tab click.
- **Home** (`spectra/web/src/home/HomePage.tsx`) is the real page built by
  the parallel `ui-build-home` task (editable timeline, tuned audio shape,
  quick-run cards — see "THE SONG-LAYOUT PLAN" above's own HOME bullet),
  landed together with this one. `/` routes to it; `/scenes` still reaches
  ScenesPage directly.
- **Shared components, reusable outside this area**: `IconToggle.tsx` (a
  30px icon toggle, purple-tinted when on — used on Test Bed's waveform-
  lane visibility toggle, `testbed/TestbedPage.tsx`, AND on Home's own
  timeline filter toggles, `home/HomeTimeline.tsx`) and `InfoTip.tsx` (a
  rich hover/long-press tooltip carrying a short description plus a
  `HelpLink`, replacing a bare "?" circle where one control deserves its
  own explanation — used on the Light Show bar slot). **IT DRAWS NO
  TRIGGER OF ITS OWN SINCE THE DESIGN-FIDELITY PASS** — callers wrap
  their control in it; see "THE DESIGN-FIDELITY GATE" below, which is the
  current account of idea 5. **Since 2026-10-14
  (idea 5, "one help '?' per page") it also replaces the four
  always-visible bar circles** (`ModeChip`/`LiveEnergyReadout`/
  `IntensityMarkControl`/`DevicePreviewStrip`) **and each card's own
  always-visible header circle on the Scenes page** (`ScenesPage`/
  `EngineStatusStrip`/`SequencerStatusStrip`/`SummaryTab`'s "Scenes" /
  "Engine" / "Sequencer" / "Summary" titles) — a state-conditional
  `HelpLink` elsewhere on the same card (e.g. `EngineStatusStrip`'s
  "dark — recording" badge) is untouched, since it isn't one of the
  always-visible circles this pass targeted. Neither component is wired
  into every page; a future pass choosing to do that inherits these.
- **Icons**: `dash`/`cube`/`gauge`/`chevronDown`/`plug`/`info`/`wave`/
  `wait` added to `iconRegistry.ts` for this build; the design-fidelity
  pass then lifted the approved artifact's OWN icon table into the same
  registry (`spark`/`note`/`pause`/`play`/`undo`/`redo`/`follow`/`full`/
  `plus`/`more`/`clock`/`palette`/`layers`/`devices`/`rooms`/`roomfx`/
  `bug`/`sync`/`flask`/`timeline`/`chat`/`review`/`warn`) — see that file
  before adding a near-duplicate, and re-lift from the artifact rather
  than redrawing a glyph by eye.
- **Tests**: `scripts/check_nav_menu.mjs` (the menu: every route
  reachable, keyboard open/close, the unsaved guard still intercepts a
  dropdown item), `scripts/check_light_show_now_next.mjs`
  (`showNowNext()`'s four rules), `scripts/check_favorites_picker_cancel.mjs`
  (FavoritesPicker.tsx's Cancel button, real-behaviourally: toggling a
  checkbox then cancelling reverts it rather than being a no-op — a real
  regression once the picker moved from a popover, where Cancel's old
  `onClose` unmount discarded the draft as a side effect, to a permanently-
  mounted inline control on Settings → "Room", where `onClose` is a no-op
  and nothing else discarded it), `scripts/check_onebar_fixed_widths.mjs`
  (a CHEAP SMOKE TEST ONLY — reads tokens.css itself for the fixed-width/
  tabular-nums declarations that are SUPPOSED to make the bar's no-jump
  property structural, which can't catch a conflicting rule elsewhere or a
  declaration gone dead — e.g. `.top-bar-strip`'s own `flex-wrap: wrap`
  once that div went `display: contents` under `.one-bar`), and
  `scripts/check_onebar_layout.py` (the actual proof, a REAL headless
  Chromium over raw CDP — the only honest way to prove no horizontal
  overflow; jsdom has no layout engine; connects to a PAGE target's own
  `webSocketDebuggerUrl` from `/json/list`, never the browser-level
  `/json/version` one, which 404s `Page.navigate`/`Runtime.evaluate` with
  "wasn't found" on current Chrome — found live while building this).
  That script also measures the no-jump claim BEHAVIOURALLY (mutates the
  Scenes/Colour value text client-side, re-measures a later sibling,
  restores the text) and the device-preview "Expand" feature (clicking the
  swatches must drop `.device-preview-expanded-row` onto its own line
  below every other occupant — `.one-bar:has(.device-preview-expanded-row)`
  in tokens.css, with `.device-preview-expanded-row`'s own CSS `order`
  moved past the warning chip and Release so it can never wrap ahead of
  them onto a second line and push them to a third). Read-only against a
  live instance (`SPECTRA_LIVE_URL`, default `http://127.0.0.1:8000/spectra/`
  — through the spot-effects proxy, not :8010, because the Colour button's
  own data only resolves same-origin through :8000); skips cleanly when no
  Chromium/live app is reachable. **Teardown is by the exact Popen
  pid/pgid only, never `pkill -f`** — a loose pattern can match an
  unrelated real process on a shared host (see the `pkill -f` memory
  entries); this script's own `start_new_session=True` + `os.killpg` is
  the pattern to copy for any future browser-automation check script here.

## THE ONE BAR IS TWO-TIER (1180/1440 one line, 1024/kiosk two rows) — the Admiral's own 2026-10-14 reversal

The tablet-height fix above first tried to keep 1024 (and the kiosk's
800px) on ONE line by shedding/capping occupants (fewer swatches, a
glyph-only Clear button, hiding the Light Show "next" item) — all of it
was abandoned the same day on the Admiral's own word: "extend the phone
two-row top-bar rule from <=520px up to about 1100px... do not shed
swatches or hide controls to force one line." **1024 and the kiosk's
800px are now a DELIBERATE TWO ROWS, nothing hidden; only 1180 and 1440
stay one line** (with the swatch cap — 2 shown — still needed there).

The split is a forced flex line-break, not organic reflow: `.one-bar`'s
unused `order: 5` (between Colour at 4 and Energy+Mark at 6) carries a
`.one-bar::before { content: ""; flex-basis: 100%; height: 0; }` at that
width band (`521px`–`1100px`, deliberately excluding the already-shipped,
separately-tuned <=520px phone tier). Row 1 is house/display-mode/Hue-Hold/
Scenes/Colour (short, fixed); row 2 is Energy+Mark/Light-Show/preview/⚠/
Release — the one that actually varies with his live data (a long scene
name, a marked song's extra "Clear" button, an armed Light Show item) —
and it fits with room to spare once it has a whole row rather than
fighting row 1 for one line. The kiosk's own touch-target floor (`.kiosk-
page button { min-height: 44px }`) is scoped to `main` only, never the
bar — it used to win over `.scenes-group-btn`'s own fixed 30px height by
CSS specificity (an element+class selector beats a bare class one),
which is what grew the kiosk bar tall independent of the row question.
`scripts/check_onebar_layout.py` clusters occupants into rows by their
own `top` (tolerant of the few px of `align-items: center` spread within
one row, strict about the ~40px+ gap between two real rows) and asserts
the row COUNT per width, not just a height ceiling — a stray third row
or a silent collapse back to one are both regressions this now catches
that a pure height check cannot.

## SONG TIMELINE MARKERS — superseded, see "THE DESIGN-FIDELITY GATE" below

The original fix for the stretched-icon report (a `viewBox="0 0 100 39"`
force-stretched to the rendered box, so a marker's raw size scaled by a
different factor per axis) was a per-axis `axisScale`/`compensate`
compensation in `songStrip.ts`. The design-fidelity pass's
`trackPainter.paintTrack` replaced the stretched viewBox with a 1:1-pixel
one at its source instead (an x is a pixel, a circle is a circle) —
`axisScale`/`compensate` are REMOVED, not merely superseded, and nothing
in this codebase calls them any more. See `songStrip.ts`'s own `trackX`
docstring and "THE DESIGN-FIDELITY GATE" below for the current mechanism.

## THE DESIGN-FIDELITY GATE — compare the page to the mockup, or it drifts (2026-10-14)

The Admiral, reviewing the shipped UI declutter: "why doesnt the spectra
ui upgrade look like the artifact? its much worse than i remember." The
read-only audit (`data/ui-fidelity-audit/report.md`) found 8 glaring, 19
noticeable and 14 minor drift gaps and named the cause in one line:
**the structure shipped and the DRAWING did not, because nothing compared
a pixel to the mockup.** Every acceptance check PRs 422-425 added
measures heights, rows, overflow, routes, maths or fps — and every one of
them PASSED on the build he called much worse. Four things now hold:

- **THE APPROVED MOCKUPS ARE THE DESIGN, and they are DOM frames, not
  text.** `data/ui-layout-plan/explainer-final.html` (fleet-spotfx home)
  is the artifact he edited and approved; its mockups are `.fw > .frame`
  nodes populated by its own `<script>` at load, so a brief that says
  "read its text" reads empty divs — which is exactly what happened.
  `docs/design/spectra-ui-mockups.html` is the frozen in-repo reference,
  derived MECHANICALLY by `scripts/regenerate_ui_mockups.py` (its
  `<style>` and `<script>` copied verbatim, its prose and its base64
  screenshots of the old app dropped). Re-derive it, never retype it.
- **THE GATE IS `scripts/check_ui_fidelity.py`** (`tests/
  test_ui_fidelity.py` runs it, so it fires on a full test run): it
  renders every mockup frame at its native width and the live chrome at
  the same size, writes the stacked pairs to `docs/evidence/ui-fidelity/`
  for a person to EYE, and asserts ~90 measurable things (sizes, weights,
  colours, dividers, rows per width, tabular digits, no help circles,
  the empty states). It runs against the repo's own mocked harness page
  (`spectra/web/harness/fidelity.tsx` — the REAL NavBar/SongStrip/one-bar/
  Home with the artifact's own canned song, plus `?nothing=1` for the
  empty state); `--app-url http://127.0.0.1:8000/spectra/` points it at
  the live app after a deploy. A machine with no Chromium/harness build
  SKIPS, saying why.
- **A CONTROL THAT UNMOUNTS IS HALF THE DRIFT.** The song timeline and
  the Light Show slot each returned `null` when nothing was playing or
  armed — his own evening state — so the two elements the plan made the
  centre of the chrome were absent most of the day, and their arrival was
  itself a layout jump. Both now draw an EMPTY STATE the mockup specifies
  ("—" in the next box, "Nothing armed · tap to run an action"), and the
  Scenes/Colour slots read "—" rather than dropping their name span. When
  a plan says "nothing jumps", a conditional `return null` in the chrome
  is the thing to look for first.
- **`button { padding: 6px 12px }` IS WHY ICONS RENDER TINY.** Every
  fixed-size icon button in `tokens.css` must set `padding: 0`: a 30px
  button that inherits the global rule has 30 - 24 - 2 = FOUR pixels of
  content box, and flex squeezes a 16px glyph to 4px wide while leaving
  it 16px tall. That was the audit's "icons render tiny (~6px glyphs)" —
  not the icon paths, which were right all along. The gate asserts the
  RENDERED glyph box of every small icon button, because every
  attribute-level check reads correct while this is broken.

**THE CHROME IS ONE COMPOSITION, `components/AppChrome.tsx`** — and
since 2026-10-15 the order is MENU, then BAR, then TIMELINE, a
DELIBERATE DEPARTURE from the mockups' `nav() + timelineRow() + bar()`
on the Admiral's own later word ("move the timeline below the toolbar
(with all the buttons and things like scene, colour, mark, etc)"); the
gate's chrome-order assertion encodes the APP's order and says so, so a
pair image showing the row in a different place from the mockup is the
ask, not a regression. App.tsx, the kiosk and the fidelity harness all
render it, and it now takes the PAGE BODY AS CHILDREN so the shared
song-timeline view state has exactly one mount point
(`components/songTimelineView.tsx` — the one window, the one marker
filter set, the one view history). It exists because the ORDER drifted
and the gate could not see it: App.tsx rendered the bar second and the
strip third while the harness drew the mockup's order, so the pair
images looked right because the HARNESS was right. A harness that models
the app rather than rendering it proves nothing about the app.

**THE TIMELINE IS ONE ROW ON EVERY ROUTE BUT `/timeline`, AND HOME EDITS
IT RATHER THAN DRAWING A SECOND ONE (2026-10-15).** `showsSongStrip`
(same module) is still the one rule, but Home is no longer excluded — his
report was that the row JUMPED from the chrome down the page there,
because Home carried its own copy. `SongStrip` now also hosts the
draggable WINDOW, shown only while something is listening to it
(`useSongTimelineShape`, Home's audio shape today — which is why the
kiosk, where the shape is dropped for space, offers no drag that would
move nothing). Home's card is the shape plus one control row: the three
marker filters sit immediately LEFT of the intensity bolt (his own
placement) and undo/redo + Follow/Full-song moved there with them.
**The shape is ALIGNED to the track by a MEASURED CORRECTION**
(`HomeTimeline.tsx::alignCorrection` — it reads where the canvas is
against where the track is and nudges by the difference, re-run from a
ResizeObserver): an absolute `track.left - parent.left` was tried first
and measured 18px out at every width, because every bit of box model
between the two is in that gap. The card still holds the mockup's flat
230px canvas with NO beat-strip lanes (`beatStrips: false`, which
`canvas/frame.ts`'s `stripCountFor` answers with zero before it looks at
anything else, and `rails: null`). **The intensity layer's `'section'`
mode draws per-section BLOCKS** from the same `sections[].energy_rms` the
row's terrain uses, and Home passes `librosaOffsetMs: 0` — the raw
convention this file already records as the right one — so the blocks,
the section lanes and the row's terrain are all on one axis.

**THE PREVIEW-HIDDEN CLASS OF BUG: A WRAP IS NOT A RELEASE.**
`.one-bar` is `height: 48px` + `overflow-x: auto`, and
`:has(.device-preview-expanded-row)` wrapped for the expanded stage
without releasing either — so a correctly laid out 1408x445 stage sat
inside a 47px scroll container and `elementFromPoint` over its middle
returned the page below it (the Admiral: "when I expand the preview, it
is completely hidden"). It worked at 1024/800 only because the
deliberate-two-row band already sets `height: auto` there, which is why
the report was a desktop one. **Anything that makes a fixed-height
overflow container wrap must release the height AND the overflow in the
same rule**, and `overflow-x: auto` silently makes `overflow-y` a clip
too. `.song-strip` also dropped to `z-index: 2` when it moved below the
bar — a row that follows the bar in the DOM would otherwise paint over
every popover the bar drops downward.

**ONE HELP "?" PER PAGE IS STRUCTURAL NOW** (idea 5): `InfoTip.tsx`
renders NO trigger of its own — callers WRAP their control in it, and
hovering/long-pressing that control opens the panel (which still carries
the `HelpLink`, so no topic is orphaned — AGENTS.md's own orphan rule).
The one visible circle in the chrome is the menu row's own page "?".
A Settings card's field rows carry their help the same way. The gate
counts `.info-tip-btn` (must be 0) and `.help-link` inside the bar, the
strip and a Settings row (0) versus the nav (exactly 1). Home's own card
HEAD is gone with the 2026-10-15 move, so there is no third surface to
scope; its CONTROL ROW is deliberately not scoped in its place — that
row has always been allowed its own InfoTips.

**HIS SIX FIDELITY ANSWERS, 2026-10-15 ("all recs")** — every one of
them is asserted in `scripts/check_ui_fidelity.py`, so the reasoning
lives here and the measurement lives there:

- **Q1 — the next-event box is in the BAR at 521-1100px**, sharing row 2
  with the Light Show slot, which now GROWS to fill that row.
  `components/SongNextBox.tsx` is the one component and
  `useNextBoxInBar()` the one predicate both hosts ask, so it is never
  drawn twice or nowhere; it owns its own rAF loop precisely so moving
  between hosts hands over no state. **The phone tier (<=520px) is
  excluded and it was measured**: adding a 92px occupant to a row the
  phone already wraps by content pushed the bar to THREE rows, and the
  phone's timeline row has its own next-box column anyway. Making row 2
  fill also fixed his separate "Nothing a…" truncation at the 800 kiosk
  — same cause, one change.
- **Q2 — nothing playing shows the LAST song, dimmed.**
  `songTimelineView`'s `track`/`showingLast` remember it IN MEMORY ONLY
  (a remembered song is a courtesy for the minutes after the music
  stops, not a durable claim; persisting it would open a cold load on a
  song from days ago dressed as "last played"). Both the row and Home's
  shape read that ONE resolved track, so they can never show different
  songs. The bare "Nothing playing" card is now reachable only in a
  session where nothing has played at all.
- **Q3 — the house button is the mockup's purple-lit/grey-off**, with the
  ♪ badge carrying the music state rather than a third colour. The fourth
  state his three words do not cover (a mode SET but not applied) stays
  the plain unlit button: not purple, because it is not driving, and not
  the off grey, because it is not off.
- **Q4 — "Scenes & drops" opens as three grouped rows** (transition
  low/high, lull darkness/breath-hold, drop timing/shockwave) with
  everything else behind a "More" expander that is `hidden`, not
  unmounted, so a field's draft and focus survive a collapse. No setting
  was removed or changed.
- **Q5/Q6 — the kiosk keeps the shape hidden; the terrain and up-next
  stay.** Both were already true and are now asserted rather than
  assumed.

**THE TRACK IS PAINTED ONCE, BY ONE FUNCTION, IN 1:1 PIXEL SPACE.**
`spectra/web/src/components/trackPainter.ts` draws the inset panel, the
energy terrain (approved idea 4 — librosa's own per-section `energy_rms`,
never a synthesised curve and never re-derived from a marker's RANK,
which orders a boundary's energy CHANGE), the drop sequences' gold→sky→
numbered-pink band, the flags and the rank-sized markers — for BOTH the
global strip and Home's editable copy, which had drifted into two
implementations. It rewrites the SVG's `viewBox` to the measured pixel
box every build, so an x is a pixel and a circle is a circle; the
stretched `0 0 100 39` viewBox that forced `axisScale`/`compensate` (see
the section above — both functions are now dead and removed) is gone
from these two. An SVG geometry attribute takes no `calc()`, which is
the other reason: the mockup's pill-offset-by-half-its-width and
triangular flag heads cannot be expressed in percent at all.

**THE LIGHT SHOW SLOT'S OWN "Nothing a…" CLIP SURVIVED PR 427 IN TWO
GAPS — a text element's own fixed `max-width` and the band that happens
to lift it are two different things, and a band that doesn't cover the
whole cap is a clip waiting to be found at the next width over
(spotfx-deploy-427).** `.light-show-act-name` carried a hand-set
`max-width: 72px` for EVERY width <=1180px, and the ONE override that
lifted it (`.one-bar .light-show-act-name { max-width: none; }`) was
scoped to the 521-1100px two-row band only — leaving the cap live, and
the idle "Nothing armed" clipped to "Nothing a…", in 1101-1180px (one
line, where the slot's own 262px flex-basis already had ~217px of
genuinely free text column — the cap was throwing away room nothing
else was contending for) and the phone tier (<=520px). **Fixed by
deleting the cap, not widening the band**: `.light-show-act-name` is a
plain `display: block` child of the slot's own fixed-width grid cell, so
it already fills exactly the slot's available width and ellipsises only
when that's genuinely too small — the same way `.light-show-act-when`
beside it always has, with no cap of its own; its `overflow: hidden`
makes its min-content contribution to every ancestor exactly 0, so
deleting a text element's own cap can never widen the SLOT (the no-jump
property survives — slot width is set by `.light-show-strip`'s
flex-basis, never by this text). **The phone tier still had a GENUINE
width shortage, not a removable cap**: the "when" line's own box there
measured ~101px against the ~122px "tap to run an action" needs, so
`LightShowStrip.tsx`'s idle branch now renders two sibling spans
(`.light-show-act-when-full`/`-short`, "tap to run" the short one),
toggled by the slot's own existing `max-width: 520px` rule in
`tokens.css` — never a JS width check. Both check scripts gained the
matching assertion (`check_ui_fidelity.py`'s harness-driven FIVE-A,
`check_onebar_layout.py`'s live-only addition) at exactly 1180/1101/390 —
the two gaps plus the phone tier. **The general lesson, since this is
the SECOND time a width-scoped override on this exact element has left a
gap (the 1180/521-1100 split was itself the first)**: before adding an
override that "lifts a cap for band X", check whether the cap's own
unconditional media query covers any width OUTSIDE band X too — a cap
and its lifting override must share the same boundary, or state exactly
why they don't.

## THE TV PROBE — phase 0 of the TV display plan: `GET /spectra/tv/probe`

Plan: `/home/javi/fleet-spotfx/data/tv-display-plan/{report.md,plan.html}`,
approved 2026-11-01 — the Admiral's one note: "the media room vizio is
legacy and should be ignored," so that TV is dropped from the whole plan
outright (no targeting, discovery, or fallback to it anywhere, this PR or
any later phase). The plan grows outward from the Jukebox toward "quality
effects on the screen" in later phases (a TV app shell, a `screen` fx
device, Milkdrop/twin looks); this PR is phase 0 only — it reads the TV's
own browser and drives no light.

`spectra/services/tv_probe.py`'s module docstring is the binding
statement. A SELF-CONTAINED page (no build step, one `<style>`/`<script>`,
no external fetches — the same reason-and-convention `spec_viewer.py`
uses for `/spectra/spec`: it has to run unmodified on whatever webOS
Chromium build the LG actually has) served at `spectra/api/tv_probe.py`'s
`GET /tv/probe`, registered in `spectra/app.py` BEFORE any future static
mount a later phase might add at `/tv` (an explicit route always wins a
same-prefix `Mount` regardless of registration order otherwise — keep this
one ahead of it). It reads WebGL 1/2 + GPU string via
`WEBGL_debug_renderer_info` on two SEPARATE fresh canvases — a canvas
whose context is already bound to one type (`"webgl"`) returns `null` for
a different type (`"webgl2"`) on a later `getContext()` call per the HTML
Canvas spec, so each needs its own canvas (the first-shipped version
shared one and silently read `webgl2: false` on every real GPU; fixed
same-day in review); runs a 10 s drawn-fps ladder (2D fill, a one-pass
shader at 540p/720p/1080p, a `milkdrop_weight_approx` tier — several trig
terms approximating Butterchurn's per-pixel cost, named so nothing
downstream reads it as a measured Milkdrop number — and an
`instanced_points` tier approximating the Live view's own "ONE instanced
WebGL2 call, MAX blend" renderer, see the Live-view section above); times
ping round-trips against `GET /api/tv/probe/ping` (a bare `{"ok": true}`
— the ASGI/HTTP hop itself is what's measured, never a computation); and
logs every `visibilitychange` (the screensaver). Results POST to
`POST /api/tv/probe/result` and MERGE into ONE record per `probe_id`
(`storage/spectra/tv_probe_results.json`, `TV_PROBE_FILE`, bounded
`MAX_RESULTS=8`, oldest `updated_ms` evicted first — a diagnostic page
opened repeatedly while tuning this build must not grow the store without
limit), read back by `GET /api/tv/probe/results` and rendered at the
bottom of the page itself. **The result is never a verdict, only a
measurement** — reading what came back (buy a box? is the fps enough?) is
the Admiral's, from the test evening.

**Touches no light, structurally** — proven by driving every
`/api/tv/probe/*` route through the real, fully-wired `create_app()` with
`fx_seam.apply_writes`/`light_ownership.commit` poisoned to raise (both
proven live first, so the poison is confirmed working before it's trusted
as a negative — the two choke points any real scene/flare/colour write in
this app passes through). No help topic — like `/spec`, this is a page a
human opens directly in a browser tab, outside the SPA's own nav and
`helpContent.ts`. Specs: `scripts/check_tv_probe_page.py` (a real headless
Chromium over raw CDP against a real uvicorn server, running the page's
own unattended fps/ping battery exactly as the LG would), `tests/
test_tv_probe.py`.

## THE TV APP SHELL — phase 1, PR 1.1 of the TV display plan: `/spectra/tv/`

`spectra/web/src/tv/TvApp.tsx`'s own module docstring is the binding
statement. Its own small Vite build (`spectra/web/vite.tv.config.ts`, `cd
spectra/web && npx vite build --config vite.tv.config.ts` →
`spectra/web/tv-dist/` — the guest page's own build, above, is the
precedent this copies) measures ~46 KB gz (JS+CSS) against the plan's <=
120 KB target, and is served by `spectra/config.py::TV_DIST` /
`spectra/app.py` mounting it at `/tv` (reached at `/spectra/tv/`) — never
through the main SPA's ~1.89 MB bundle. It reuses the SAME
`SPAStaticFiles` class the `/spectra` SPA mount already uses (not a third
subclass), so it inherits that class's Cache-Control contract for free —
see "SPA `index.html` must revalidate every request" above.

**Registration order is load-bearing, and the mount site's own comment in
`spectra/app.py` says so**: the `/tv` mount is registered BEFORE the main
`/` SPA mount (a `Mount("/", ..., html=True)` would otherwise catch every
unmatched path first) but AFTER `/tv/probe`'s own explicit route (phase
0, above) — an explicit `Route` always wins over a same-prefix `Mount`
regardless of registration order, so the ordering only has to protect
against the SPA's catch-all. With no TV build on disk (`TV_DIST`
missing), no `/tv` mount is added at all and the request falls through to
the main SPA's own catch-all — never a dead mount.

Three planes stacked in one page, no app chrome: `VisualPlane.tsx`
(canvas, behind everything — phase 1 draws only a slow, OLED-safe
two-blob colour-haze drift with no real room-colour data yet), `InfoPlane.tsx`
(DOM, sized for an 83" TV read from ~3.5m per the plan's own §2.4
reading-distance floors — body >= 32px, a now-playing title 64-80px — so
later real content slots into type that's already the right size, rather
than being resized once it lands), and `SystemPlane.tsx` (a small, dim
diagnostic corner: the shell's own build id from `build.ts`'s
`TV_BUILD_ID`, baked in at build time by `vite.tv.config.ts`'s `define` —
a fresh `Date.now()` id, not a content hash, which only has to differ
across deploys — plus a connected/not-connected dot and a clock-offset
readout, both now driven by the real feed; see "THE TV FEED" below).
`build.ts`'s `shouldReload(serverBuildId)` is the pure half of "build-id
reload" (the plan's own "nobody stands at the TV to press refresh"): an
empty/missing server id is never evidence of staleness and never triggers
a reload — PR 1.2's feed is what actually calls it with the server's real
id, on every `config` message. The Info plane's real content — now
playing/votes/progress/up-next/join QR — is PR 1.4's own Party screen
(below); the Attract/Sleep/lost-connection screens are PR 1.5's own, one
section further down ("THE ATTRACT, SLEEP AND LOST-CONNECTION SCREENS").
This shell's three-plane structure held through PR 1.4 (`InfoPlane.tsx`
just gained one more conditional branch) but gained a real fourth piece
under PR 1.5: `TvApp.tsx` now also mounts a `ConnectionOverlay` above all
three planes and short-circuits to a separate, smaller tree (`SleepScreen`
+ `ConnectionOverlay` only) whenever `layout === 'sleep'` — see that
section for why sleep is deliberately not just another `InfoPlane`
branch.

No help topic — like `/spec` and `/tv/probe`, this is a page a human (or
a TV) opens directly, outside the SPA's own nav and `helpContent.ts`.
**The plan's own row lists a `/jukebox/tv` redirect for this PR; it was
deliberately NOT cut over here, and still isn't — PR 1.4's own Party
screen (below) renders now/next/votes/QR, never the board.** The
existing Jukebox board page (`JukeboxTvPage.tsx`, phase 3 of the Jukebox
plan, above) honours an on/off gate ("On the TV") with an honest
off-message; the relay's own jukebox payload (`GET /api/jukebox/tv`, PR
1.3, below) still carries no `board_on_tv` field at all, so redirecting
`/jukebox/tv` to this shell today would still trade a working, gated
board for a screen with no board at all. The redirect stays deferred to
whichever later PR gives the TV shell a board of its own and carries the
gate forward, within the same approved phased plan; `/jukebox/tv`
remains unchanged.

Specs: `scripts/check_tv_app_shell.py` (a real headless Chromium over raw
CDP against a real uvicorn server mounting the built `tv-dist/` exactly
as production does — the gzip budget, both target viewports [1920x1080,
1280x720], the `/tv/probe` route still answering alongside the mount),
`tests/test_tv_app_shell.py` (the mount-order/fallback contract, against
a throwaway hand-written `index.html` rather than depending on a real
build having run).

## THE TV FEED — phase 1, PR 1.2 of the TV display plan: `/spectra/api/tv/ws`

`spectra/services/tv_feed.py`'s module docstring is the binding statement
for the wire protocol; `spectra/web/src/tv/{clock,feed,useFeed}.ts` is the
client half. One WebSocket carries everything the shell (PR 1.1, above)
needs that a static build can't: the `hello`/`config` handshake, an
NTP-style ping/pong clock, a 4 Hz show-clock anchor, the layout director's
"party"/"attract" pick, and a relay of SpotFX's own Jukebox board. Six
things:

- **PING/PONG IS CLIENT-INITIATED, deliberately NOT `av_sync_session.
  ClockMap`** (that module is server-initiated, built for the opposite
  direction — a phone filming a fixture). The TV sends `{"type": "ping",
  "t": <client_send_ms>}` every 2s; the server replies with its own
  `server_recv_ms`/`server_send_ms`, bracketing whatever work
  (`handle_ping`'s `before_pong_send` hook, a no-op in production) runs
  between them — the classic 4-timestamp NTP formula is resistant to a
  PROCESSING delay there (SPECTRA's event loop is known to stall —
  AGENTS.md's own "THE PREVIEW STREAM IS PROTOCOL 2" section is the
  standing evidence): the stall shows up as added round-trip delay, never
  as skew, provided both server timestamps are taken close to the real
  recv/send.
  `clock.ts`'s `NtpClock` keeps the fastest (lowest-RTT) of the last 8
  samples' offset. Both ends must share one epoch-ms scale —
  `feed.ts`'s `nowMs()` is `performance.timeOrigin + performance.now()`,
  never bare `performance.now()` (relative to page-navigation start,
  which would make the offset read as the page's own age, not a real
  clock skew).
- **THE SHOW CLOCK IS PUSHED AT `CLOCK_PUSH_S` (0.25s, "4 Hz anchors")**,
  read through `engine.current_show_clock_ms()` + `engine.bridge`'s own
  position/is-playing (the live singleton instance `engine.py` constructs
  — `bridge.py` itself has no module-level equivalents to call directly).
  `clock.ts`'s `interpolateShowClockMs` advances the anchor 1:1 with the
  client's own clock between pushes (corrected by the NTP offset) rather
  than timing anything by message arrival, so a late push never makes the
  drawn clock jump.
- **THE JUKEBOX RELAY READS SPOTFX'S OWN `GET /api/jukebox/tv`** (PR 1.3,
  `services/jukebox/guests.py::Guests.tv_view()` — now playing with live
  votes/progress, the next 3 program items with who added them, only the
  people boards guests see, the guest join link while it's live, and a
  revision that moves on any change), the leaner purpose-built shape the
  plan's own row 1.3 names — through the one swappable seam
  `TvFeedDeps.fetch_jukebox`. PR 1.2's own first version pointed this at
  the older `GET /api/jukebox/board` (PR 466) as an interim source since
  this endpoint didn't exist yet; 1.3 is exactly that one-line follow-up,
  not a second relay implementation. `running` (whether a night plays) is
  read FROM that same fetched payload, never a second call — polling it
  separately to decide whether to poll it would be circular, and SpotFX's
  own read is already lean (no Spotify call — `tv_view()`'s own
  docstring). Polled at `JUKEBOX_POLL_S`
  (1.0s) and sent only when the payload actually changed (plain dict
  equality) — this structurally bounds "a vote reaches a TV" at one poll
  interval plus negligible send time, comfortably under the plan's own
  1.5s acceptance bound. The very first `config` reply reads a FRESH board
  rather than waiting on the relay loop's own first poll tick — a stale
  "attract" for up to a whole poll interval right at connect would be the
  wrong screen for a night already running.
- **THE LAYOUT DIRECTOR (`resolve_layout`) COMPOSES THREE DECISIONS IN ONE
  PRIORITY ORDER, PR 1.5** — `director_layout`'s own plain split ("party"
  while a night plays, else "attract", `None` reading as the calmer
  "attract") is still the base case, with two fallbacks layered on top of
  it, each checked first:
  `sleep` wins outright once the process-wide `ActivityTracker` instance
  `_activity` (fed by "a night is running OR music is playing") has
  accumulated `SLEEP_TIMEOUT_S` (600s, plan row 1.5/Q8: "black after 10
  min with no night and no music") of idle time; else, while a night IS
  running, `attract` wins too once a SECOND, independent
  `ActivityTracker` instance `_board_activity` (fed by "the relayed board
  actually changed this tick" — the same comparison `run_jukebox_loop`
  already makes for its own send-on-change dedup) shows the board has sat
  unchanged for `UNCHANGED_TIMEOUT_S` (180s, plan §2.2's own "a night runs
  but the screen has been unchanged a while") — a running night always
  counts as "active" for the sleep clock, so without this a
  quiet-but-running night (no votes, same song still playing) would show
  `party` forever; else `director_layout`'s own split. Both trackers are
  process-wide (outside `TvFeedDeps`), for the same reason: the room's
  idle time and the board's own staleness are each a single fact, not a
  per-connection one — a fresh `TvFeedDeps()` built per connection would
  otherwise give every TV its own idea of either clock. The client's
  `Layout` type still carries `'calibrate' | 'lost'` as placeholders for
  later phases.
- **BUILD-ID RELOAD IS NOW COMPLETE END TO END** (closing PR 1.1's own
  deferred acceptance item): `vite.tv.config.ts`'s `writeBuildIdManifest`
  plugin writes a plain-text `tv-dist/build-id.txt` beside the build (a
  .js bundle isn't convenient for the Python side to inspect);
  `tv_feed._default_build_id` reads it (a missing file is `None`, never a
  reason to instruct a reload); `config_message` carries it in the one
  `config` reply every connection gets, so a reconnect (the client's own
  fixed-backoff retry, `feed.ts`) is what catches a TV up to a newer
  build; the client's own `shouldReload()` (built in PR 1.1, unchanged)
  decides. `SystemPlane.tsx` shows the live connected/not-connected dot
  plus the measured clock offset, and `InfoPlane.tsx` shows a
  connection/layout-dependent line — the one visible proof, at the TV
  itself, that the feed and the NTP sync are actually working, useful for
  the phase 0/1.2 test evening without devtools. The Party screen's
  content is PR 1.4's own ("THE PARTY SCREEN" below); the Attract/Sleep/
  lost-connection screens are PR 1.5's own ("THE ATTRACT, SLEEP AND
  LOST-CONNECTION SCREENS" below).
- **EVERY WS SEND SHARES ONE LOCK.** `spectra/api/tv_feed.py` serializes
  every send (the two background loops plus the ping/pong dispatch)
  through a single `asyncio.Lock` — three independent writers on one
  socket otherwise race `ws.send_json`. A dead socket
  (`WebSocketDisconnect`, or the `RuntimeError` FastAPI raises on a send
  after close) ends a background loop quietly; any OTHER exception logs a
  warning — a routine disconnect must not read as a bug, and a real one
  must never be swallowed.

No help topic — like `/spec`, `/tv/probe` and the shell, this is a page a
human (or a TV) opens directly, outside the SPA's own nav and
`helpContent.ts`. Specs: `scripts/check_tv_clock.mjs` (the pure NTP
math — skew recovery through a deliberate 300ms processing stall,
fastest-of-8, the show-clock interpolator, `shouldReload`), `tests/
test_tv_feed.py` (the pure message builders; the ping/pong formula's
stall-resistance proven directly by injecting a real 300ms delay via
`before_pong_send`; both background loops' quiet-vs-loud exception
handling; the 1.5s jukebox-relay acceptance bound measured in real time;
the full `/spectra/api/tv/ws` route over FastAPI's `TestClient`); `tests/
test_jukebox_tv_feed_endpoint.py` (`Guests.tv_view()` + the `GET
/api/jukebox/tv` route itself, over the real fake Jukebox world).

## THE PARTY SCREEN — phase 1, PR 1.4 of the TV display plan

`spectra/web/src/tv/PartyScreen.tsx`'s own module docstring is the
binding statement. `InfoPlane.tsx` renders it only while `feed.connected
&& feed.layout === 'party' && feed.jukebox` all hold (the feed, PR 1.2,
above) — a connected TV on any OTHER layout renders the real Attract
screen instead ("THE ATTRACT, SLEEP AND LOST-CONNECTION SCREENS" below,
PR 1.5); only "not yet connected" still keeps the plain placeholder. Five
things:

- **ART IS NEVER ALTERED, structurally, not by convention** — Spotify's
  Design and Branding Guidelines (no crop/overlay/animation/blur).
  `.tv-party-art`'s `object-fit: contain` can't crop, and nothing in the
  DOM draws on top of it (no `::after`, never composited with the
  room's own colour haze behind everything, `VisualPlane.tsx` — two
  separate layers, always). `check_tv_party_screen.py` reads the
  rendered `src`/`object-fit`/`filter` back off the real DOM rather than
  trusting the markup.
- **PROGRESS IS CLIENT-SIDE INTERPOLATION BETWEEN ~1 Hz RELAY PUSHES, not
  a live read** — `now.progress_ms` is a snapshot from the jukebox relay
  loop (PR 1.2/1.3, above), advanced forward by elapsed CLIENT time
  while `is_playing` (`partyLogic.interpolatedProgressMs`, clamped at
  the song's own length), the same shape the show-clock interpolation
  already uses and for the identical reason. **Both the anchor
  (`FeedState.jukeboxReceivedAtMs`, stamped on every `jukebox` message)
  and the "now" it's measured against must share `feed.ts`'s own
  `nowMs()` (`performance.timeOrigin + performance.now()`) — caught in
  review after `PartyScreen` first measured against `Date.now()`, a
  different clock than the one that stamped the anchor.** This is the
  same "both ends must share one epoch-ms scale" lesson "THE TV FEED"
  section above already names for ping/pong; `nowMs()` is now exported
  from `feed.ts` for exactly this second caller.
- **THE UP-NEXT CALLOUT FIRES IN THE LAST 30s OF A SONG, once a next song
  is known** (`partyLogic.showCallout`) — `next` already excludes an
  unfilled jukebox slot (`tv_view()`'s own filter, `services/jukebox/
  guests.py`), so a non-empty list alone means a real next song and the
  callout is purely the 30s window on top of that; it shows only the
  next item's title and who added it, never prices or credits.
- **THE JOIN QR REUSES THE ONE SHARED ENCODER** (`../lib/qr.ts`,
  extracted out of the printed guest cards' own `cardQr.ts` in PR 1.3
  specifically so the TV screens never grow a second one — see "THE
  PRINTED CARD (N2)" above) and shows only while `jukebox.link` is
  non-null, the plan's own Q5; "Ask the host for the link to join"
  otherwise.
- **A MALFORMED `jukebox` MESSAGE RENDERS NOTHING, never crashes**:
  `jukeboxTypes.isJukeboxView` is a loose runtime check (only the one
  field the Party screen actually branches on, `next` being an array)
  run before the feed ever stores the message — it's JSON off the
  network, never trusted blindly.

Text floors (plan §2.4: body >= 32px, song lines >= 40px, the
now-playing title 64-80px) are `tv.css`'s own `clamp()` MINIMUM
argument, never the vw-relative "preferred" term — raised on the shared
`InfoPlane.tsx` placeholder text too (`.tv-info-title`/`.tv-info-sub`),
so the floor holds on every screen this plane shows, placeholder
included, not just the Party content. `useTick.ts` forces a 500ms
re-render so the progress bar/clock visibly advances between relay
pushes; its own return value is unused — every caller reads the clock
itself via `nowMs()`.

No help topic — like the probe and the shell, this is a page a TV opens
directly, outside the SPA's own nav and `helpContent.ts`. Specs:
`scripts/check_tv_party.mjs` (the pure logic — progress interpolation,
the callout window, `fmtMMSS`/`byWords` — against synthetic clocks, no
DOM/network) and `scripts/check_tv_party_screen.py` (a developer-run
real-browser check, the same convention as `check_tv_app_shell.py`: a
real uvicorn server with `tv_feed.production_deps` swapped for a canned
Party scenario, a real headless Chromium over raw CDP — no page
overflow, every text node >= 32px, the art unaltered, the attribution
link present, and the up-next callout itself rendered and naming the
next song).

## THE ATTRACT, SLEEP AND LOST-CONNECTION SCREENS — phase 1, PR 1.5 of the TV display plan

`spectra/services/tv_feed.py`'s own "THE SLEEP TIMEOUT"/"THE 'BOARD WENT
STALE' FALLBACK" docstring sections are the binding statement for WHEN
each layout fires (server side; "THE TV FEED" above already covers
`resolve_layout`'s precedence in full — this section doesn't repeat it).
The three screens' own module docstrings (`AttractScreen.tsx`,
`SleepScreen.tsx`, `ConnectionOverlay.tsx`) are the binding statement for
WHAT each one draws. Five things:

- **`InfoPlane.tsx` IS NOW A TWO-SCREEN SPLIT, NOT A PLACEHOLDER**: while
  connected, `layout === 'party'` with jukebox data renders the Party
  screen (PR 1.4, above); anything else connected renders `AttractScreen`.
  Only "not yet connected" keeps the plain placeholder text. `layout ===
  'sleep'` never reaches `InfoPlane` at all — `TvApp.tsx` short-circuits
  to a SEPARATE, SMALLER tree (`SleepScreen` + `ConnectionOverlay` only,
  no `VisualPlane`/`InfoPlane`/`SystemPlane`) before `InfoPlane` mounts,
  because true black has zero burn-in risk ONLY because nothing is drawn
  underneath it — if the haze or the status dot kept rendering while
  "asleep," a multi-hour sleep would itself become the static-pixel risk
  this screen exists to prevent.
- **BURN-IN SAFETY IS PURE ARITHMETIC OF ELAPSED TIME** (`burnIn.ts`): the
  Attract deck cycles cards (join/top/now) every 15s (`ATTRACT_CARD_MS`),
  the card drifts up to ±16px over an 8-minute triangle wave
  (`DRIFT_PERIOD_MS`/`DRIFT_AMPLITUDE_PX`, x/y phases offset by a third of
  the period so neither axis peaks alone), and the join QR cycles all
  four corners every 10 minutes (`QR_SWAP_PERIOD_MS`). The drift period
  (8 min) is DELIBERATELY SHORTER than the plan's own 10-minute "no
  element static" acceptance window — a continuous, non-constant function
  with a period under the sampling window has already cycled through its
  whole range before that window closes. `VisualPlane.tsx`'s haze also
  dims to 0.4x (`dimRef`, a mutable ref the draw loop reads every frame —
  never a dependency of the canvas setup effect, so a layout change
  doesn't tear down and rebuild the canvas/`ResizeObserver`) while
  `layout === 'attract'`, the plan's own "a very dim haze."
- **THE LOST-CONNECTION OVERLAY IS A FOURTH, ALWAYS-MOUNTED PLANE**
  (`ConnectionOverlay.tsx`, stacked above the other three in `TvApp.tsx`
  so it can cover them once the 60s mark passes): nothing for the first
  5s (`MARK_AFTER_MS`, a quiet blip leaves whatever's already on screen
  fully visible), a small dim "Reconnecting…" mark from 5-60s, full black
  (`.tv-lost-black`, `z-index: 10`) at 60s (`BLACK_AFTER_MS`) — matching
  the plan's own acceptance text exactly. `feed.disconnectedAtMs` is
  stamped with `feed.ts`'s own `nowMs()` (`performance.timeOrigin +
  performance.now()`), never `Date.now()` — the same clock-source mismatch
  PartyScreen's own PR 1.4 review already caught once for its progress
  interpolation (see "THE PARTY SCREEN" above); comparing it against a
  different clock here would have reintroduced that exact bug. Cleared
  the instant `onopen` fires again (`feed.ts`'s own `disconnectedAtMs:
  null`).
- **THE LAYOUT PUSH STAYS DECOUPLED FROM THE BOARD'S OWN CHANGE** — see
  `run_jukebox_loop`'s own docstring: a `layout` message is sent only
  when the RESOLVED layout itself changes, never tied to a `jukebox`
  message landing, which is what lets the room sit on an unchanging board
  for the whole sleep timeout OR the whole stale-board fallback window
  and still have either clock re-checked every poll tick. The dead
  `layout_message()` helper (PR 1.2's board-paired shape, superseded by
  `_layout_payload` + `resolve_layout`) was removed in review rather than
  left behind as an unused second definition.
- **NOTHING ABOUT THE OTHER PLANES' OWN SHAPE CHANGED** — `VisualPlane`
  still draws the same two-blob haze and `SystemPlane` still reads the
  same feed; this PR only ADDS the dim ref to the former and the fourth
  overlay plane plus the sleep short-circuit to `TvApp.tsx` ("THE TV APP
  SHELL" above has the updated structure).

No help topic — like `/spec`, `/tv/probe` and the shell, this is a page a
TV opens directly, outside the SPA's own nav and `helpContent.ts`. Specs:
`scripts/check_tv_burnin.mjs` (+ `tests/test_tv_burnin.py` — the pure
drift/QR/card-rotation arithmetic over simulated time, no DOM/browser),
`tests/test_tv_feed.py` (`resolve_layout`'s full precedence table,
`ActivityTracker`'s reset-on-activity/accumulate-while-idle behaviour, and
both background-loop simulations driven on a fake clock — one that
actually reaches "sleep" after enough simulated idle polls, one that
falls back to "attract" after enough simulated unchanged-board polls and
then recovers to "party" on the very next real board change), and
`scripts/check_tv_attract_sleep.py` (a developer-run real-browser check,
the same convention as `check_tv_app_shell.py`/`check_tv_party_screen.py`:
four scenarios over a real uvicorn server + real headless Chromium —
Attract's deck/text-floor/card-change, the haze's measured dim, Sleep's
pure-black DOM with nothing painted underneath, and the lost-connection
timing itself, which alone takes over a minute of real wall-clock time and
is a one-off manual proof, not a fast per-commit check).

## THE ONE TAP — phase 1, PR 1.6 of the TV display plan (closes phases 0-1)

`spectra/services/tv_launch.py`'s module docstring is the binding
statement. SPECTRA never talks to the TV directly — ONE Home Assistant
script (River's own, default `script.tv_open_spectra`) owns "open the TV
app," and every one of the four ways to trigger it funnels through the
ONE function here, `put_on_tv()`, into `ha_client.call_service("script",
"turn_on", ...)`: the Jukebox page's "Put on the TV" button
(`spectra/api/tv_launch.py`'s `POST /api/tv/put-on-tv`), a Light Show HA
step (`show_actions.py`'s `ha_put_on_tv`, the fourth kind in the "ha"
group — see that section above), the optional auto-open poller (below),
and Sonic (`jukebox_console.put_on_tv`, asks first — the one op in that
domain that calls here in-process rather than hopping to SpotFX over
HTTP like every other op there; filed under `jukebox` anyway because the
plan's own diagram groups "Put on the TV" with the Jukebox page as the
thing it opens, not because it is a new domain). Inert without
`SPECTRA_HA_URL` configured, structurally — no second gate was added on
top of `ha_client.py`'s own "unset URL == inert" rule. Five things:

- **THE CONFIG IS ITS OWN TINY STORE** (`storage/spectra/tv_launch.json`,
  `TvLaunchConfig`: `auto_open_enabled` default `False`, `script_entity`
  default `None` meaning `DEFAULT_SCRIPT_ENTITY`) — never a
  `RoomControlState` field (that's lighting) and never a `ShowConfig`/
  `ProgramConfig` field (the Jukebox's own settings live in SpotFX, which
  this module may not import). `GET/PUT /api/tv/launch-config` is a TRUE
  PARTIAL UPDATE (`room_controls.merge_room_controls`'s own precedent).
- **A MALFORMED `auto_open_enabled` IS REFUSED, NEVER GUESSED** —
  `_coerce_bool` accepts a real bool or the literal strings `"true"`/
  `"false"` case-insensitively and raises `TvLaunchPatchError` (mapped to
  HTTP 422) on anything else, so a bare `bool(value)` truthiness cast can
  never read the JSON string `"false"` as `True` and silently invert a
  safety-critical default — the same discipline `show_actions._coerce`'s
  own bool branch already holds for Light Show params.
- **THE AUTO-OPEN POLLER IS ITS OWN ALWAYS-RUNNING TASK**
  (`run_auto_open_supervised`, wired in `spectra/app.py`'s lifespan),
  deliberately NOT riding `tv_feed.run_jukebox_loop`'s existing
  per-connection poll — that loop only runs once a TV is already
  connected, exactly the case auto-open exists to cover (nobody has the
  TV open yet). It polls SpotFX's `GET /api/jukebox/tv` on its own
  10 s cadence and fires on the RISING EDGE of `running`, only while
  `auto_open_enabled` (default OFF — the plan's own Q4: "a TV switching
  itself on is surprising"). THE FIRST POLL OF A FRESH PROCESS NEVER
  FIRES, even if a night is already running — only an edge OBSERVED by
  this poller counts, so a process restart mid-night can never fire a
  spurious auto-open (`tv_feed.ActivityTracker`'s own "a fresh tracker
  starts just became active, never already idle" reasoning, restated
  here for the identical restart hazard). A failed fetch is "unknown,"
  never "not running," and an unknown→True transition DOES count as an
  edge — the conservative direction, risking one unneeded open over
  silently missing a real night start on one dropped poll.
- **NO TV CALL IN ANY TEST** — every test injects a fake `call_service`/
  `put_on_tv`/`fetch_running`, structurally (nothing imports httpx/
  `ha_client` at module load time).
- **THIS CLOSES THE TV DISPLAY PLAN'S PHASES 0 AND 1** (the Admiral's
  approval note on the whole plan: the media room Vizio stays out of
  scope here exactly as in every prior PR). The `tv-display` skill
  (`.claude/skills/tv-display/SKILL.md`) is the cold-start map across
  every phase/PR; load it before touching any TV-plan file.

Help: `put-on-the-tv` (the Jukebox section, linked from the button's own
`InfoTip`) and the widened `show-ha-actions` entry (above). Specs:
`tests/test_tv_launch.py`, `tests/test_tv_launch_api.py`,
`tests/test_show_ha_actions.py`'s `ha_put_on_tv` section,
`tests/test_jukebox_console.py`'s "one tap" section,
`tests/test_settings_agent_cli.py`'s `put_on_tv` widening fixture.

