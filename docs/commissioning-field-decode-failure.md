# The commissioning instrument's first field runs: 0 of 736, and why

**2026-09-01. Desk work from cold evidence; his camera and room were not
available and were not needed.** The evidence is
`/home/javi/fleet-spotfx/data/commissioning-field-evidence/` (both judged
responses, one raw frame from the same camera pose). Re-read it with
`.venv/bin/python scripts/read_commissioning_field_evidence.py`. The
failure itself is reproduced with no evidence at all by
`scripts/check_commissioning.py` section 3c.

## What happened

The gray-code commissioning test (the plan's §8, PR 225) ran twice on his
real `tv-mapper`. Both runs were mechanically clean — 22 captures, ~42 s,
the copy-carrier substitution right, the fixtures brought up and put back,
the room restored, no problems reported — and both judged themselves FAIL
with **0 of 736 pixels decoded**. The same decoder recovers 76 of 76
offline.

|                        | run 1 | run 2 |
|------------------------|-------|-------|
| decoded                | 0 of 736 | 0 of 736 |
| lit camera pixels      | 3,165 | **0** |
| of those, undecodable  | 3,165 | 0 |
| out of range           | 0 | 0 |
| captures / seconds     | 22 / 42.6 | 22 / 42.1 |

## What the evidence says

**The two runs disagree about how much they saw and agree on the only
thing that matters: not one bit was ever confident.** `undecodable ==
lit` with `out_of_range == 0` is not "we decoded badly", it is "no camera
pixel had all ten bits above the confidence bar" — and the decode's own
gate is `|pattern − inverse| ≥ 0.20 × that pixel's own full-minus-dark
brightness`. So on every lit pixel, at least one pattern came back
indistinguishable from its own inverse.

**The kept frame says why.** It is 320×180 and all but **66** of its
57,600 pixels are exactly zero. What light there is sits in rows 53–58 in
**three compact glows** (x 69–77, 135–142, 203–211), peaking at 99 of 255
— three glows for the composition's three fixtures. The whole 736-pixel
composition therefore arrives as about **0.09 camera pixels per
composition pixel**. Each camera pixel is integrating hundreds of LEDs, so
a pattern lighting half of them and the inverse lighting the other half
deliver the same brightness to the same pixels, and their difference is
zero to within the sensor's own rounding.

*(Provenance, stated: the README labels this "one raw frame from the same
camera pose" without naming which capture step it came from. Three glows
at the composition's own three fixtures is a lit frame; a dark step is
black. Nothing below depends on it — run 1's own numbers rule out the
alternatives on their own.)*

## The hypothesis on file, tested and ruled out

The evidence packet's hypothesis was a **systematic mismatch — frames read
at the wrong moments relative to the pattern cadence**. It does not fit,
and the reason is a usable discriminator rather than an opinion:

* A mistimed stack compares two **different** patterns. Different patterns
  differ: the low bits keep real contrast, bits stay confident, and pixels
  decode **confidently to wrong indices** — which shows up as out-of-range
  pixels and scattered support. Driven offline, a one-step lag does
  exactly this (`tests/test_gray_code.py::test_a_mistimed_stack_looks_
  nothing_like_it`).
* His runs showed the opposite shape: **zero** confident bits anywhere and
  **zero** out of range. Reproduced in the field regime, the low bits sit
  at ~0.01 against the 0.20 bar while the **high** bits sit at 0.9 — which
  is what integration over many LEDs does (the coarse halves of the strip
  are still distinguishable; the fine alternation is not) and is not what
  noise or mistiming does.
* The capture loop itself is regular in both runs: 22 captures 1.7–2.3 s
  apart, 3–5 frames averaged each, every capture over its minimum. Nothing
  was starved.

## The second finding: two "lit" numbers that described nothing

The decode's lit gate took the frame's bright end from
`percentile(full − dark, 99)`. That silently assumes the composition
covers more than 1% of the frame. His covers 0.11%, so the 99th percentile
was the read noise (zero, or a fraction of a grey level), the gate
collapsed to *anything at all above the dark reference*, and it reported
**3,165 pixels of averaging noise** in one run and, when the dark average
came out no lower, **zero** in the next. Neither number described his room,
and the frozen table then read "0 of 736" as *occlusion or blob-merge* —
an attribution pointing at his hardware for an instrument pointed at
something it cannot resolve.

## The arithmetic that governs this instrument

Gray bit 0 alternates in runs of **two** indices — the finest structure in
the whole stack. To see a two-index period the camera needs about **two
camera pixels per composition index** along the imaged strip
(`gray_code.MIN_CAMERA_PX_PER_INDEX`). So:

* 736 pixels need **~1,472 camera pixels** of imaged strip;
* his pose delivered **66**;
* and the entire border of the **320×180** frame the phone sends is
  **~1,000**.

**No pose fixed this at the frame size the wire carried when this was
written.** The page downsampled to 320×180 before sending; the run's
"full-resolution ring" is full relative to the 64×36 *map grid*, not to the
camera.

> **RESOLVED, 2026-09-01, by the owner's own instruction** ("raise video
> frame size and tweak whatever settings help"). The commissioning read now
> asks for **1920×1080**, where the same television framed normally images
> a ~4,600-pixel perimeter against the ~1,840 his composition needs with
> margin — chosen by this arithmetic and not by picking the maximum
> (`spectra/services/capture_settings.py` carries the derivation, the
> never-upscale rule and the two manual exposure levers). Ordinary
> footprint mapping stays at 320×180: a footprint is a 64×36 grid and more
> pixels buy it nothing. Everything above this note is the state of the
> world before that raise, and is kept because it is what the raise was
> chosen against.

## What changed

1. **The run asks whether the camera can resolve the composition at all**,
   from the dark and full reference pair alone — two captures, about four
   seconds — and refuses **by name**
   (`gray_code.resolution_report` → `mapping_refusals.
   unresolvable_composition`), naming the measurement, the bar and what to
   do. The frozen table is never handed a stack the camera could not read.
   Its five tolerances are untouched.
2. **The lit gate no longer degenerates**: the bright end is the mean of
   the brightest `PEAK_SAMPLE` pixels, plus a one-grey-level floor. The
   floor is the sensor's own quantisation, not the scene-brightness
   assumption the inverse capture exists to avoid.
3. **Every decode carries `bit_contrast` and the resolution report**, so a
   future failure says *where* it died in its own response instead of
   needing frames nobody kept. That is the gap this investigation was: the
   field responses could not answer it, so it had to be reconstructed.

## What a real retest needs

* **At his own pose, propped as before: about four seconds.** The run will
  refuse with the measurement in it. That is worth doing — it confirms this
  diagnosis on his real hardware at almost no cost — but it will not
  decode.
* **A run that can decode 736 pixels needs a bigger frame on the wire**,
  and that is a decision, not an implementation detail: the 320×180 frame
  size is a contract the mapping instrument shares
  (`light_field.FRAME_W/FRAME_H`, asserted on every frame), and raising it
  raises the bandwidth over the link he actually uses. At 640×360 the
  frame's border carries ~2,000 camera pixels against the 1,472 needed —
  workable with the phone framed on the television, with little margin.
* **Or commission something smaller.** The same dim room, same read noise,
  same grey8 wire, decodes 88 pixels across this frame perfectly
  (section 3c(f)). Commissioning a *sconce* is a real test today.
  Commissioning a coarser version of the TV strip is not the same test the
  frozen table judges, and choosing that is his call, not the
  instrument's.
