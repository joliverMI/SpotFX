# Preview performance test

Compares Spectra's browser preview with LedFX's, in a real browser, through the
same emulated link. It is the acceptance gate for the preview stream
(`spectra/services/preview_stream.py`).

It never touches the room: every device is a dummy, every port is a spare one
(9110 Spectra rig, 9120 LedFX, 9130 proxy, 9201 link, 9333 Chromium), and it
reads no live storage.

## Run it

```bash
# once, and after any change under spectra/web/src: build the harness pages
# (spectra/web/harness: index.html mounts the real DevicePreviewStrip,
# live.html the real Live view)
(cd spectra/web && npx vite build --config vite.harness.config.ts)

# the gate: exit 1 unless the FIRST system passes (about 12 minutes)
.venv/bin/python scripts/preview_perf/run_preview_perf.py --out /tmp/preview-perf \
    --systems spectra+proxy,spectra+proxy:collapsed,ledfx --gate

# the Live view's gate: 60 drawn frames a second, desktop and phone, every link
.venv/bin/python scripts/preview_perf/run_preview_perf.py --out /tmp/preview-perf-live \
    --systems spectra+proxy:live,spectra+proxy:live:phone --pass-drawn-fps 59

# quick look (2 link profiles, 8 s each)
.venv/bin/python scripts/preview_perf/run_preview_perf.py --out /tmp/preview-perf --quick

# the old JSON format, for comparison
.venv/bin/python scripts/preview_perf/run_preview_perf.py --out /tmp/preview-perf \
    --systems spectra-legacy,spectra-legacy@30
```

Results land in `--out` as `results.md` (the table), `results.json` (everything,
including the stream's own rate, window and held-tick counts per row) and
`shots/` (one screenshot per run). Run it in the background; a full run is
longer than a 10-minute foreground limit.

## The gate

`--gate` applies these to the first system listed (report section 7):

| where | limit |
|---|---|
| `lan`, `ts-direct`, `ts-relay` | at least 28 delivered fps; no inter-frame gap over 100 ms; interval p95 at most 50 / 56 / 69 ms; input-to-photon median at most 95 / 141 / 216 ms; browser main thread under 20% |
| `poor` | at least 15 fps; input-to-photon median under 450 ms, worst under 1 s |
| the `:collapsed` row | under 20 kbit/s on the wire |
| when `ledfx` was run too | fps, interval p95 and latency median match or beat LedFX's row on the same link **in this run** (`--vs`, with `--vs-slack-ms` 3 for noise) |

`--pass-drawn-fps N` is the Live view's gate and applies to every `:live` row:
at least N animation frames a second in which the page really drew (59 = the
display's 60 less measurement rounding).

Every limit has its own flag. `--pass-p95-ms` and `--pass-latency-ms` take one
number or per-link values (`lan=50,ts-direct=56,ts-relay=69`).

The fixed latency limits are LedFX's numbers from the day the plan was
written, when a flash waited up to 100 ms inside the test's own effect before
either preview saw it. That wait is gone (see "input to photon" below), so
both systems now measure about 45 ms lower and the same-run comparison is the
one that binds.

## What it measures, and how

| number | how |
|---|---|
| delivered fps | frames per second for `crystal-mapper`, counted in the page |
| painted fps | `putImageData` calls per second on the 72-wide canvas |
| interval p95 / max, gaps > 100 ms | time between consecutive frames at the browser: the evenness he sees |
| input to photon | an API call sent through the link flips the `hues` virtual black/white; the clock stops two animation frames after the changed frame reaches the page. The effect redraws at once on both systems, and flashes are spaced randomly so they cannot lock to either sender's frame clock |
| frame bytes / wire kbps | crystal frame size in the page, and bytes actually crossing the link (after WebSocket compression) |
| drawn fps, long frames | animation frames in which the page made a real draw call (a WebGL draw, or the 2D fallback's clear), and frames longer than 34 ms |
| browser main thread | Chromium task time / wall time (CDP `Performance.getMetrics`) |
| server CPU for preview | process CPU with the page open minus CPU with nobody watching (rough) |

The probe (`probe.js`) instruments the browser, not the app. It reads LedFX's
JSON frames and Spectra's binary messages. The link emulator (`linkemu.py`) is
a TCP proxy adding delay, jitter and a bandwidth cap with a bounded queue.

## Systems

Parts combine, e.g. `spectra-legacy@30+proxy`.

- `ledfx` — the real fork (`/home/javi/ledfx/bin/ledfx`) and its real frontend,
  his settings (30 fps, max 4096 pixels, compressed).
- `spectra` — the shipped preview: real relay, stream hub, API route and React
  strip (expanded), fed by a real fx render host.
- `+proxy` — behind the real `services/spectra_proxy.py` class (the :8000
  address he uses).
- `:collapsed` — the strip collapsed: one averaged colour per device.
- `:live` — the Live view (Devices > Live) instead of the strip, on his
  room's real topology (`spectra_rig.py --room`: the crystal through its
  1,952 segments, one strip effect copied onto the TV backlight and both
  sconces, one pixel onto seventeen bulbs — all dummies). `:phone` adds a
  390x844 screen at 3x with the CPU slowed 4x (`--phone-cpu`); `:canvas`
  forces the 2D-canvas fallback.
- `-legacy` — the old JSON format (the page skips the protocol-2 hello);
  `-legacy@N` raises only its relay rate (a what-if).

## Limits

- `:live` rows draw with WebGL. Headless Chromium has no GPU by default and
  rasterises WebGL in software, which measures this machine's CPU rather
  than the view, so `--gpu auto` gives those rows the machine's real GPU
  (`--use-angle=gl-egl`) and leaves every other run on software as the
  stream gate was measured. Each row's `webgl_renderer` in `results.json`
  says what it got; `--gpu off` shows the software case. `:phone` is a
  desktop GPU behind a slowed CPU, not a phone's GPU.
- The link is emulated. Profiles: `lan`, `ts-direct` (30 ms), `ts-relay`
  (80 ms, 4 Mbit; a Tailscale relay ping measured 71-88 ms on 2026-10-05),
  `poor` (150 ms, 1 Mbit). His real link was not measured. The emulator does
  not model packet loss.
- The proxy rig runs the real proxy class in a quiet process; the live
  spot-effects process is busier.
- The content is a scrolling rainbow. `encoding_study.py` sizes frames of his
  real effects instead.
- LedFX's frontend subscribes to frames only from its second load on a fresh
  browser profile, and that warm-up load is slow over a delayed link: list
  `lan` first in `--profiles` when `ledfx` is among the systems.
- Browser automation is raw CDP (the probe must be injected before page load,
  which `chrome-devtools-axi` has no command for).
