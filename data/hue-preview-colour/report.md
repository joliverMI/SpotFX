# Hue preview colour fix (2026-10-06)

## The report

The Admiral, playing with House scene settings and pressing "Set": the
Hue bulbs read as yellow-green in the preview (top strip, Live tab / room
map) despite the house mode holding them at a white kelvin look. DJ's
read-only check of both Hue bridges confirmed the REAL bulbs are correct
(mirek 477 ≈ 2095 K, xy (0.5163, 0.4145)) — the bug is in the preview
only.

## Root cause

`fx/devices/hue.py`: while a Hue device is `frozen` (held over REST by
house lighting / Ambient), "the driving virtual stays ACTIVE and
rendering — only this device's output is muted." The device-preview
pipeline (`preview_stream.py` / `device_preview.py`) taps that same
render (`Event.VIRTUAL_UPDATE`), which never stops computing while
frozen — so the preview showed whatever the room's ordinary show happens
to paint on that virtual, completely unrelated to the REST colour
actually on the bulb.

On his real `hues` virtual this is structural, not incidental: it is ONE
shared, copy-mapped effect pixel covering every bulb across BOTH
entertainment areas (`tests/test_preview_layout.py`'s `hue-lights`
living / `dining-hues` dining fixture). Even a perfectly correct render
could never show two different held areas at two different colours —
only reading the HELD LOOK itself, never the render, can.

Ruled out: `houseSummary.ts::kelvinToHex` (the House page's editor
swatch) uses a correct Tanner Helland blackbody fit — verified by hand
and by test, not buggy. No xy-as-RGB naive bug was found anywhere in the
render/preview path (the preview never reads bridge xy at all, only
mirek/colour via `ambient.py`'s own look tuples).

## The fix

- `spectra/services/hue_preview_colour.py` (new): correct `kelvin_to_rgb`
  (the same Tanner Helland fit) and `xy_to_rgb` (CIE xy → XYZ → the Hue
  bridge's own wide-gamut D65 matrix, inverted from `ambient.py::
  _hex_to_xy` → gamma-encoded sRGB, out-of-gamut scaled down not
  clipped), plus `held_hex_for_look` mirroring `ambient.py`'s own
  `(area, kind, mirek, color, brightness)` look tuple.
- `spectra/services/preview_layout.py`: each fixture (and, for the top
  strip's single swatch, each virtual) now carries a `held` hex field —
  resolved from `house.hue_directive()`'s own per-device look, the SAME
  data ambient.py sends to the bridge. `None` means "not held, draw the
  live render unchanged" (unaffected — every non-Hue fixture, and a Hue
  fixture under `"show"`/no hold).
- Frontend (`positions.ts::withHeldOverlay`, `stage.ts::pushFrame`,
  `DevicePreviewStrip.tsx`): a held fixture's points draw the server's
  `held` colour instead of the streamed frame, in both the Live view
  (per bulb/area) and the top strip (a pixel-weighted mean per virtual).

## Verification

- `tests/test_hue_preview_colour.py` — kelvin 2000/2700/3500/6500 K and
  the live xy point (0.5163, 0.4145) all convert to plausible, non-green
  sRGB; `held_hex_for_look` for off/hold/show.
- `tests/test_preview_layout.py` — two Hue areas sharing one effect pixel
  preview as two different real colours; an un-held fixture is
  untouched; off → black.
- `scripts/check_hue_preview_colour.mjs` — drives the REAL
  `positions.ts`/`stage.ts` (via esbuild) end to end: pushes a literal
  yellow-green stream frame and confirms the held area overrides it
  while the un-held area still shows the raw stream.
- Real-browser check (headless Chromium, no live SPECTRA instance — a
  throwaway client-side harness deleted before commit): `before-after.png`
  in this folder. BEFORE — both Hue areas drawn yellow-green from the
  shared stream pixel (reproducing the report exactly). AFTER — Living
  (`#ff9d31`, authored) and Dining (2095 K / mirek 477) each draw their
  own correct warm colour.

No live light, room-control, or house setting was touched at any point.
