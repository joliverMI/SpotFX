---
name: star-scene
description: >
  The "STAR" SPECTRA scene — Matrix `radial`, Strips `melt` (always melt now —
  an intensity-stepped `power` overlay at ⚡0.7+ was removed, see below),
  Singles `power` (`pulse` once scripts/migrate_singles_to_pulse.py runs).
  Load before editing this scene's flare bands/kinds (especially anything
  Reverse-shaped), its Strips config, or the `edges` param — this scene has
  the most edit-history and the most "his own tuning got silently replaced by
  a rebuild" precedent of any scene here. Load radial-effect and melt-effect
  first for the underlying effects.
---

# STAR (scene)

Load `radial-effect` and `melt-effect` first.

## STAR's `edges` field is the canonical "stored data ≠ authored intent"
   example — read before trusting ANY stored field on this scene

His legacy STAR scene authored `edges` as a bare static `6`; the SPECTRA
rebuild silently replaced it with a random dice binding plus two "patch"
flare kinds that exist nowhere in his legacy data — he never asked for
any of it, and only noticed because his six-pointed star stopped being
six-pointed (docs/agents/scenes-and-flares.md, `docs/spectra-star-edges-freeze.md`). **The rule
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

STAR's Strips base effect was always `melt`; `scripts/seed_star_strips.py
--apply` added an intensity STEP on top (`power` at/above ⚡0.7, melt
below). His 2026-08-25 ruling "always do melt" removed that step.
`scripts/star_strips_always_melt.py` is the current, correct script;
`seed_star_strips.py` is the ORIGINAL, now-superseded seeder — re-running
it would silently put the power step back. See the melt-effect skill.

## Drops can switch INTO or OUT OF this scene (2026-10-08)

This scene is drop-switch-ready (its Matrix effect is in
`fx.device_model.CENTRE_BURST_EFFECTS`): once a scene has grown stale, a drop sequence
may hard-cut into this one ON the drop, with this scene's own drop firing
on the mark and adopting the outgoing pieces — or cut out of it the same
way. Nothing in this scene's data opts in or out; `spectra/services/
drop_switch.py` (and the drop-detection skill) is where the rule lives,
including the hand-off table row for this effect (INTO STAR since
2026-10-14 and OUT OF STAR since 2026-10-13: both run a transition
program on the mark).

## Its lull, drop and transitions out (the star plan, 2026-10-13)

His "Use lull b, drop d 3": STAR's lull now breaks its bands into pieces
that fall into the core (black on the shared dark point) and its drop throws
them back out with a hue-kept colour gain — the radial-effect skill has the
mechanism. Nothing in this scene's DATA changed for it: `lull_mode`
defaults to "bands" on the effect, so STAR (and House Star, if a house mode
ever lets a phase through) gets it with no migration; set `lull_mode` to
"implode" on the Matrix entry to put the old lull back. The scene's own
`drop_shock_enabled` switch withholds the snap-back (plain bloom). Every
scene change OUT of STAR into Black Hole / Fireworks / Sauron / Eye /
Squiggles / Orbits / Fish now runs a transition program (approved).

2026-10-14 (his "Do rec on transitions", and Q5 changed): every scene
change INTO STAR from those seven runs a program too — the partner's own
release, then the pieces glide onto STAR's rings while the star grows out
of its core (`ring_reveal_front_s` on the Matrix entry, 0.65 s, Sonic-
reachable; help `star-into-transitions`). And STAR's strip (`radial-dummy`,
Melt) no longer does its own LULL while STAR reads it — STAR's own lull
takes the crystal dark on the dark point by itself; the strip's charge and
drop still ride in. No scene data changed for either. A better STAR charge
is still pending his word.

## The star improve plan (2026-11-12) — what `scripts/star_improve_scene_data.py` changes on THIS scene

Approved by him from the plan artifact ("STAR plan is approved, go ahead
and deploy as soon as it's ready"), applied by DJ at deploy, raw-dict
surgery with backup/--revert/structural diff (the flip-script shape):
(1) Matrix entry: `spin_ease_in_s 1.0`, `star_wave true`, `star_wave_lo
-0.2`, `star_wave_hi 0.4`, and the `star` binding's picks moved INSIDE his
standard range (steps {0.0->0.0, 0.5->0.3}, fallback 0, `random_sign`
off — it was ±0.3/±0.5); (2) "Flare patch 0.7-1" and "Drop patch 0.7-1"
lose their `star: 0.0` write (kept `spin: 0.55`); (3) a new PERMANENT kind
"Edge Morph" (`edges`, mode `random_other`, 3..6) attached at 1.0 to the
0.35-0.7 and 0.7-1 flare bands only; (4) Strips entry `dark_floor 0.5`.
**-0.2 .. +0.4 is STAR's standard star range**: nothing on this scene —
binding or kind — writes `star` outside it; add a new kind here with that
in mind. `tests/test_star_improve.py` proves the script on his STAR shape.
The TV ring (`scripts/tv_ring_pixel_map.py`) is a DEVICE change, not this
scene's data. The radial-effect and melt-effect skills carry the mechanics.

## The spin smooth plan (2026-11-12) — what `scripts/star_spin_smooth_scene_data.py` changes on THIS scene

His words after the star improve plan went live: "too jerky in it's spin
especially on big bass hits ... We need to cap the burst speed ... it
shouldn't be jerky, but it should be dynamic"; then "the burst fade should
be snappier at higher energies and lazier at low energies. do 18 degrees
per frame for now". ONE change, same raw-dict discipline (backup,
--revert, structural diff, dry run by default), DJ applies at deploy:
Matrix entry `spin_release_low_s 0.45`, `spin_release_high_s 0.2` — the
seconds a bass hit's spin burst is spread over at section energy 0 and 1
(a straight line between; the effect default 0/0 is today). The 18 deg per
rendered frame clamp is engine code (`ROTATION_CAP_DEG_FRAME`), not scene
data. Expect a loud fire (spin 0.94 by the `spin` binding at trigger
intensity 1) to sit AT the clamp through a steady loud passage — that is
the trade he chose over 22 deg, revisit the constant, not the binding, if
he wants it faster. `tests/test_star_spin_smooth.py` proves the script on
his STAR shape. The radial-effect skill carries the mechanics.

## Sonic reach

Scene settings and flare kinds only via the scene console; the Matrix
entry's effect VALUES (incl. `lull_mode`, `shape_morph_s`) via
`set_scene_entry_param`.

## Executable proofs

`tests/test_star_strips_always_melt.py` (this scene's Strips migration).
The radial-effect skill owns the effect's own instruments
(`scripts/check_star_spin_motion.py`, `scripts/check_radial_base_rotation.py`).
History: docs/agents/fx-effects.md's "Radial (STAR)" section and docs/agents/scenes-and-flares.md's "A scene's stored data is not proof
he authored it" section — read both before a non-trivial change.
