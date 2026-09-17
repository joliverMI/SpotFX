---
name: star-scene
description: >
  The "STAR" SPECTRA scene — Matrix `radial`, Strips `melt` (was `power`,
  see below), Singles `power`. Load before editing this scene's flare
  bands/kinds (especially anything Reverse-shaped), its Strips config, or
  the `edges` param — this scene has the most edit-history and the most
  "his own tuning got silently replaced by a rebuild" precedent of any
  scene here. Load radial-effect and melt-effect first for the underlying
  effects.
---

# STAR (scene)

Load `radial-effect` and `melt-effect` first.

## STAR's `edges` field is the canonical "stored data ≠ authored intent"
   example — read before trusting ANY stored field on this scene

His legacy STAR scene authored `edges` as a bare static `6`; the SPECTRA
rebuild silently replaced it with a random dice binding plus two "patch"
flare kinds that exist nowhere in his legacy data — he never asked for
any of it, and only noticed because his six-pointed star stopped being
six-pointed (AGENTS.md, `docs/spectra-star-edges-freeze.md`). **The rule
this proves: an artifact's presence in stored scene data is NOT evidence
he authored it.** Before touching any of this scene's fields, especially
anything that looks like a dice/random binding, check his LEGACY data
(spot-effects' pre-rebuild source), never infer authorship from what's
currently stored.

## Two Reverse flare kinds, and a permanent one STICKS

STAR has "Reverse Direction" (PERMANENT) attached to its 0.35-0.7 and
0.7-1.0 flare bands, and "Reverse Momentarily (500ms)" attached to
0-0.35. A PERMANENT kind's carry moves `param_baseline`
(`conductor.on_surge`), so after ONE mid/high-intensity flare, reversed
IS the new baseline — every LATER momentary reverse on the low band lands
`-|spin|` and releases back to `-|spin|`. **This is "stuck in reverse" by
CONSTRUCTION, not a race or a bug** — the watchdog correctly finds
nothing to restore. Whether this permanent attachment is what he actually
wants is HIS call (the scene backups show the two kinds were declared
unattached by script and the band attachment was a later UI save) — don't
"fix" it as a bug without checking with him first; do check which kind is
attached to which band before diagnosing a "stuck reversed" report.

## Both Reverse kinds target `spin_sign`, NOT `spin` directly — his own
   ask, "use the flip control for star"

They target the sign-control param (`spin_sign`, value 0/1), which
redirects the write onto `spin` with ONLY the sign flipped, magnitude
PRESERVED from the current carried value, and forced through
`executor.jump()` (never glide) on both departure and release — see the
radial-effect skill's `spin_sign` note. `scripts/
switch_star_reverse_flares_to_flip.py` is the one-field migration that
ported these two kinds from a raw `spin` target to `spin_sign` (dry-run
default, `--apply`, `--revert`) — NOT `scene_console.apply_flare_kind`'s
model round-trip, because that round-trip silently added unwanted flare
kinds to Squiggles the same night this was built. `scripts/
add_star_reverse_flares.py` is the ORIGINAL migration that created the
two kinds in the first place (goes through `scene_console.
apply_flare_kind` correctly, since creating a kind is exactly what that
function is for).

## Strips: `melt`, always — a superseded seeder still exists

His 2026-08-25 ruling "always do melt" removed STAR's Strips power step.
`scripts/star_strips_always_melt.py` is the current, correct script;
`scripts/seed_star_strips.py --apply` is the ORIGINAL, now-superseded
seeder for the intensity-stepped `effect_steps` binding — re-running it
would silently put the power step back. See the melt-effect skill.

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

`scripts/check_star_spin_motion.py`, `tests/test_star_strips_always_melt.py`.
History: AGENTS.md's "STAR" scene and "A scene's stored data is not proof
he authored it" sections — read both before a non-trivial change.
