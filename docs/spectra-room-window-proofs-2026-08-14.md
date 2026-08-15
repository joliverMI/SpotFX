# SPECTRA room-window proofs — 2026-08-14

Live-room verification of the two builds merged locally onto the Admiral's
running `spectra.service` tonight: PR 62 (live section-energy readout) and
PR 61 (ambient release ease-back). Run against `http://127.0.0.1:8010/spectra/`
with `chrome-devtools-axi` at phone width (390×844), inside the granted
02:42:00Z room window. No restarts, no settings left changed.

Screenshots: `/home/javi/fleet-spotfx/data/spectra-room-window-proofs/`
- `01-scenes-phone.png` — Scenes route, phone width, energy readout at 1.00
- `02-timeline-phone.png` — Timeline route, phone width, energy readout at 0.77
- `03-ambient-cyan-picked.png` — Ambient enabled, `#00e5ff` picked via the
  native colour input, ColorWell reflects the pick
- `04-ambient-restored.png` — immediately after the restoring PUT (UI still
  showing stale cached state — see Proof 2 notes)
- `05-ambient-restored-reload.png` — after a reload, UI confirmed matching
  the Admiral's original settings

## Proof 1 — live energy readout (PR 62)

- **Renders on more than one route, in the room-controls strip**: confirmed
  on both `/spectra/scenes` and `/spectra/timeline` at phone width — same
  `⚡ Energy` row directly under Brightness/Ambient/Transition/Scene
  changes/Force Scene. It's mounted once in `App.tsx` (`TopBarStrip`,
  wrapping every route), so structurally it's on every page, not just the
  two sampled.
- **Moves with the music, not frozen**: sampled repeatedly over ~40s on the
  Scenes route: `0.71 → 1.00 → 0.83 → 0.94 → 0.57 → 0.78 → 0.74`. Clearly
  live, not a static number.
- **Degrades honestly to a dash**: read `LiveEnergyReadout.tsx` directly —
  `intensity != null ? intensity.toFixed(2) : '—'`. No live value (bridge
  down / nothing playing / song has no analysis) renders `—`, never a fake
  `0.00`. Did not force a live bridge outage to avoid destabilizing his
  room inside the window; the source is unambiguous on this point.
- **Fits at phone width without crowding**: it's its own full-width row
  below the four-control row, doesn't compress or hide Brightness/Ambient/
  Transition/Scene changes/Force Scene. See screenshots 01/02.

**Verdict: PASS**, all four criteria met.

## Proof 2 — colour picker, lights actually took it (PR 61's ambient path)

Surface used: the room bar's Ambient colour picker (native
`<input type="color">`, `RoomControlsBar.tsx`), the only live
"pick a colour → lights change" surface currently deployed (PR 59's LedFX
colour-picker component is not merged on this box tonight — only PR 61 and
PR 62 are).

Steps, with his standing permission to drive the room:
1. Recorded his original room-controls state before touching anything:
   `ambient_enabled=false, ambient_color=#f5da8c, brightness_multiplier=1.0,
   global_transition_ms=500, scene_change_mode=analysed,
   force_scene_enabled=false`.
2. Enabled Ambient via the UI checkbox (picked up his own `#f5da8c` first —
   `journalctl`: `Ambient ON: ['dining-hues', 'hue-lights'] held at
   #f5da8c, 17 light(s) set`).
3. Picked a new colour, `#00e5ff` (cyan), directly on the native colour
   input (dispatched via the native value setter + bubbling `input`/`change`
   events — SPECTRA's fast poll cycle makes the axi ref system too slow to
   win the race otherwise). `GET /api/room-controls` immediately reflected
   `ambient_color: "#00e5ff"`.
   `journalctl`: `Ambient ON: ['dining-hues', 'hue-lights'] held at #00e5ff,
   17 light(s) set` — **his real Hue lights (17 across both Hue groups)
   took the picked colour**, confirmed server-side, not just UI state.
4. Restored his original state with one PUT (`ambient_enabled=false,
   ambient_color=#f5da8c`, everything else untouched).
   `journalctl`: `Ambient OFF: ['dining-hues', 'hue-lights'] released
   (caught up: True)` — this is PR 61's release ease-back path firing
   cleanly (`caught up: True`), not a snap-off.
5. Reloaded the page: checkbox unchecked, ColorWell back to disabled
   `#f5da8c` — UI matches his original settings exactly (screenshot 05).
   Note: right after the restoring PUT, before the reload, the UI still
   showed the stale ON/cyan state (screenshot 04) — that PUT went straight
   to the API, bypassing the UI's own poll cycle, so the display lagged
   until the next refetch/reload. Not a defect in the shipped ambient
   logic; only relevant to how *this test* drove the API directly for the
   restore step.

Final state verified via `GET /api/room-controls`: identical to the
recorded original. `GET /api/liveness`: 21/21 devices online, `healthy:
true`, `state: live`. `GET /api/ownership`: `owner: spectra,
live_stack_active: true`.

`journalctl --user -u spectra` around the whole test: no tracebacks, no
new warnings caused by these actions. Two pre-existing `WARNING` lines
(`Hue Dining Hues: failed to (re)activate entertainment stream after 3
attempts: DTLS handshake timed out`) appear at 21:50:21 and 21:50:40 —
**before** any ambient interaction in this session (the earliest ambient
action was 21:54:13) — so they predate this test and aren't caused by it;
noted here since the brief asked for anything found in the log, not
because they're attributed to PR 61/62.

**Verdict: PASS.** Colour picked in the UI → confirmed server-side →
confirmed on his real Hue lights via the ambient service's own log line →
released cleanly via the ease-back path → room restored to his exact
original settings.
