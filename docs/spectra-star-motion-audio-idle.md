# STAR "not moving at any speed" — diagnosis (2026-08-21)

His report, verbatim: "I'm running the star effect right now and it doesn't
seem to be moving at any speed. I recently tried to update the initial
conditions on speed but I don't think I should have broken anything."

## Verdict

**Nothing is broken, and nobody's change caused it — his edit and every one
of today's engine changes (#168, #172, #174) are each ruled out below with
evidence.** The star was not moving because the radial effect's rotation is
**audio-driven, not a motor**: the speed parameter is a *gain* on the live
captured audio's LOWS power, and during the bass-light stretches of what he
was playing that power idles near zero, so a perfectly healthy `spin=0.55`
rotates at ~6°/second — one full revolution per minute. To the eye that is
"not moving at any speed". When the track's bass pumps, the same
configuration measurably turns at 45–90°/s.

## The mechanism (fx/effects/radial.py, vendored verbatim)

The ONLY thing that advances the pattern is the audio callback:

```python
def audio_data_updated(self, data):                    # radial.py:154
    self.impulse = getattr(data, self.power_func)()    # lows_power()
    self.spin_total += self.impulse * self.spin        # the motion line
```

`draw()` renders `spin_total`; `rotation` and `twist` are static (his STAR
authors `twist: 0`). `config_updated` derives
`self.spin = nonlinear_log(spin_cfg, 2) / 10 = sign·spin_cfg²/10`
(radial.py:132, fx/utils.py:2780). At 60 audio callbacks/s:

> **rev/s = 6 × lows_impulse × spin_cfg²**

At his observed `spin=0.55` that is `1.815 × impulse`. The impulse is
`lows_power()` — the average of the beat (≤100 Hz) and bass (100–250 Hz) mel
bins of the **live captured room audio** (`snapcast.monitor`), through a
fast-decay filter (`alpha_decay=0.2` at 60 Hz ≈ 50 ms half-life), and
force-zeroed entirely whenever capture volume is under `min_volume=0.2`.

**The trap that made this look like a bug:** the bridge's "intensity"
readout (0.38–0.69 during the session) comes from *stored librosa analysis
of the song file* and stays high regardless of what the live capture hears.
The star does not listen to that number. The two can diverge arbitrarily —
and did.

## Measured, not asserted

Offline reproduction against the REAL pipeline — `fx.headless` host +
`fx.audio_ingest.HubMelbankSource` (the identical wiring
`spectra/services/live_host.py` installs), his live
`storage/spectra/fx-live/config.json` audio/melbank settings, his exact
scene params (`spin 0.55, star -0.5, edges 6, twist 0`), fed 12.3 s of audio
**recorded from `snapcast.monitor` during the session** (LOS PITS playing):

| passage | lows share of energy | avg lows impulse | rotation |
|---|---|---|---|
| sec 0–6 (verse, bass-light) | 8–20 % | ~0.009 | 0.014–0.02 rev/s ≈ **6°/s — reads as parked** |
| sec 7–11 (bass back) | 58–81 % | 0.07–0.13 | 0.12–0.25 rev/s ≈ 45–90°/s — visible |

Durable executable proof (synthetic audio, no live access, assert-gated):
`scripts/check_star_spin_motion.py` — silence and mid-only (1 kHz) audio
advance a `spin=0.55` star by exactly/effectively zero; pumping bass turns
the same config at 0.5 rev/s; `spin=0` with pumping bass is exactly zero
(both factors required).

## Everything ruled out, with the evidence

- **His edit is NOT the cause.** Before (worktree snapshot, 16:48):
  map out **0.1→1.0**, random_sign **false**, fallback 0.55. After (live):
  out **0.2→0.8**, random_sign **true**, fallback 0.55. No value in either
  version can produce zero; the edit's only speed effect is capping the top
  end (spin 1.0→0.8 ≈ 36 % slower at max intensity via the ² curve). His
  suspicion of himself is unfounded.
- **#168 (spin_sign flip port) is NOT the cause.** The sign-control write
  preserves magnitude from spin's own carried value (registry default 0.2 if
  never carried; "0 stays 0" can't trigger — the live magnitude was 0.55,
  observed on the wire). A flip changes direction, never rate. The
  same-named local `spin_sign` in radial.py's particle-handoff snapshot
  (lines 229/281) is unrelated metadata, and with `twist: 0` the handoff
  sign-adoption branch is a no-op (`if spin_sign and tw:` — tw is 0).
- **#172/#174 (trigger offsets/double-fire) are NOT starving it.** Spin
  writes were arriving during the live watch: 0.55 (scene fallback) and
  0.25 — the latter is exactly "Flare patch 0–0.35"'s authored absolute,
  proving low-band flares were landing (and confirming the room's trigger
  intensity was reading < 0.35, consistent with a quiet passage).
- **The audio path is healthy at every layer**, checked live 2026-08-21:
  SPECTRA's capture stream open on `snapcast.monitor` (pid-matched, 100 %
  volume, unmuted; note SPECTRA's stream-restore identity "ALSA plug-in
  [python3.12]" differs from spot-effects' streams — checked separately on
  purpose); real signal on the monitor (RMS 0.10–0.18 → pipeline volume
  0.75–0.85, well over the 0.2 gate); hub pump alive (a dead pump fills its
  ~3 s queue and warn-logs the first drop — zero drop logs in 2 days);
  effects subscribing/unsubscribing cleanly on every scene change.
- **Latched-NaN freq_power filter ruled out** (the incident class the
  isfinite guard at fx/effects/audio.py:1456 documents): the live process
  restarted 18:12 today, and his live melbank config produces valid
  non-empty freq slices (`freq_mel_indexes [1, 3, 15, 22]`), so there is no
  NaN entry path; the reproduction with the same config shows healthy
  values.

## One real behaviour change worth his attention (not a bug, not a freeze)

His STAR bands now attach the #168 kinds: "Reverse Direction" (permanent,
`spin_sign` value 0.0 = Off = **force negative**) on both the 0.35–0.7 and
0.7–1 flare bands, and "Reverse Momentarily (500ms)" on 0–0.35. Because the
same band also carries a "Flare patch" writing `spin` absolute, and the
reverse kind sits later in the band's kind order (last-write-wins per the
documented lane-order rule), **every mid/high flare now lands spin
negative — a constant forced direction, not a toggle** — and every low
flare flips it negative for 500 ms and back. None of this changes the
rotation *rate*, but if he expected "reverse" to alternate direction per
flare, what it actually does is pin one direction. His data, his call.

## What would change what he saw (his decisions, nothing touched)

1. **Raise the spin range back up** — the ² curve means the top end matters:
   out_max 0.8 → 1.0 is ~56 % more rotation at full intensity.
2. **Choose a different `frequency_range` on the scene** — the schema
   default "Lows (beat+bass)" parks the star between bass hits; "Mids"
   would rotate more continuously on vocal/melodic content.
3. **Accept it as designed** — the star deliberately breathes with the
   bass: parked in verses, whipping on drops (0.5+ rev/s measured).
4. **A product change** (owner decision, deliberately NOT made here): give
   radial a base rotation floor independent of the impulse, or slow the
   lows filter decay so sparse 808s sustain more drive. Either is a
   deviation from the vendored effect (fx/VENDOR.md discipline applies).
