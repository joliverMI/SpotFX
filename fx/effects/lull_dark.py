"""THE LULL'S DARK POINT — one rule for every lull effect that goes dark.

His ask, 2026-10-07 (the Admiral, verbatim): "For the lull effects like
black hole and squiggles, (and pulse) we have full darkness half way
through the lull. Sometimes the lull is very extended and it's too long to
be fully dark. Instead of always setting the dark point to half way through
the lull, set a max time for that portion to 3 seconds (make this something
sonic can change). So if we have a 20 second lull ... Now it would be 17
seconds of expansion and 3 seconds of dark. Pulse should match, so it's
only pitch black for 3 seconds. Do just these 3 effects for now, but
prepare clear method for doing it with others and future ones."

THE RULE (`dark_hold_s` / `dark_start_s`, the ONE definition):

    dark_hold  = min(lull / 2, max_dark)
    dark_start = lull - dark_hold          # the approach before it

so a 20 s lull is 17 s of approach and 3 s of dark, and a 4 s lull keeps
its half-and-half 2 s + 2 s. `max_dark` is the room setting
`RoomControlState.lull_dark_max_s` (default 3.0, Sonic-editable); 0 means
the lull only reaches dark on its drop.

WHY THE EFFECT HAS TO BE TOLD. An effect only ever sees `phase_progress`,
which SpotFX ramps 0 -> 1 over ~90% of the real gap to the drop and then
HANGS at 1.0 (spectra scene_response._phase_ramp_ms). A fixed progress
fraction therefore cannot express "3 s before the drop" — it can only ever
mean a fixed share of the lull. So SpotFX computes the rule at the lull's
own arm write (scene_response._drive_phase, the one place a phase is
written) and pushes two plain numbers alongside `phase`/`phase_progress`:

- `lull_dark_s`: seconds from the lull's start to its dark point;
- `lull_ramp_s`: how long SpotFX's progress ramp runs (seconds) — the end
  of the lull's movement, which `after` runs up to.

Both default to 0 = NOT TOLD (an older SpotFX, a hand-written test, a LedFX
UI scrub): the effect then behaves exactly as it did before this rule
existed, at its own `legacy_dark_at` progress — byte-identical, so nothing
changes for a write that does not carry the keys.

SECONDS INTO THE LULL ARE THE EFFECT'S OWN CLOCK, NOT `phase_progress`.
Once told, an effect measures the lull on its own seconds-in-phase (reset on
the lull's edge, advanced every rendered frame), never by turning progress
back into seconds. Two reasons, both measured, not argued:
  1. A lull that follows a COMPLETED charge — the ordinary charge -> lull ->
     drop sequence — starts its progress at 1.0, not 0: the arm's 1 ms
     reset tween has not rendered a frame when the ramp's glide retargets
     it, so the glide runs from the charge's finished 1.0 to 1.0 and the
     lull sits at its end for its whole length (an fx tween property:
     start_param_transitions retargets from the prior tween's current
     value). Read off progress, Black Hole was dark and Pulse black from the
     lull's first frame. The effect's own clock does not care.
  2. A lull longer than ten times the cap has its dark point inside the
     hang, where progress no longer moves (a 40 s lull's dark point sits at
     37 s, after its 36 s ramp) — only a clock can find it.

HOW A LULL EFFECT OPTS IN (existing or future — two calls, plus two lines):
  1. splice `**lull_dark.schema_fields()` into its CONFIG_SCHEMA (and
     `*lull_dark.KEYS` into ADVANCED_KEYS, beside `phase_progress`);
  2. add its registry name to `fx.device_model.LULL_DARK_EFFECTS`, which is
     what makes SpotFX push the two keys on its lull arm;
  3. read `lull_dark.lull_timing(self._config, progress, phase_t,
     legacy_dark_at=<the progress its dark point sat at before>)` — with
     `phase_t` its own seconds since the lull's edge — wherever
     it used a fixed progress fraction for its dark point. `approach` runs
     0 -> 1 from the lull's start to the dark point (an expansion, a fade, a
     squash), `dark` says the dark portion has begun, and `after` runs 0 -> 1
     from the dark point to the end of SpotFX's ramp (a second movement
     inside the dark, e.g. Squiggles' line pinching to its dot);
  4. hand its orphan watchdog `lull_dark.watchdog_progress(self._config,
     phase, progress, phase_t)` instead of the raw progress, so a long told
     lull is not released early (see that function).
Only Black Hole, Squiggles and Pulse are opted in (his "just these 3 for
now"); blackhole1d — Black Hole's own strip — is the natural next one.
"""

from __future__ import annotations

from typing import Mapping, NamedTuple

import voluptuous as vol

RAMP_KEY = "lull_ramp_s"
DARK_KEY = "lull_dark_s"
KEYS = (RAMP_KEY, DARK_KEY)

DEFAULT_MAX_DARK_S = 3.0

# A dark-to-ramp-end span shorter than this has no room for a second
# movement: `after` jumps straight to 1 at the dark point.
MIN_AFTER_SPAN_S = 1e-3


class LullTiming(NamedTuple):
    approach: float   # 0 -> 1, lull start -> dark point
    dark: bool        # the dark portion has begun
    after: float      # 0 -> 1, dark point -> the end of SpotFX's ramp


def dark_hold_s(lull_s: float, max_dark_s: float) -> float:
    """How long the lull holds dark: half the lull, never more than the cap."""
    lull_s = max(0.0, float(lull_s))
    return min(lull_s / 2.0, max(0.0, float(max_dark_s)))


def dark_start_s(lull_s: float, max_dark_s: float) -> float:
    """Seconds from the lull's start to its dark point."""
    lull_s = max(0.0, float(lull_s))
    return lull_s - dark_hold_s(lull_s, max_dark_s)


def keys_for(lull_s: float, ramp_s: float, max_dark_s: float) -> dict:
    """The two config keys SpotFX pushes on a lull arm (see the module
    docstring). `lull_s` is the real lull length (the gap to its drop);
    `ramp_s` how long the phase_progress ramp runs."""
    return {
        RAMP_KEY: max(0.0, float(ramp_s)),
        DARK_KEY: dark_start_s(lull_s, max_dark_s),
    }


def schema_fields() -> dict:
    """CONFIG_SCHEMA entries for the two pushed keys — spliced into an
    opted-in effect's schema so a validated write keeps them. Like the phase
    keys, never part of the effect-parameter registry: only the lull arm
    write carries them."""
    return {
        vol.Optional(
            RAMP_KEY,
            description="Lull: seconds the phase_progress ramp runs (driven by SpotFX; 0 = not told)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional(
            DARK_KEY,
            description="Lull: seconds from the lull's start to its dark point (driven by SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
    }


def told(config: Mapping) -> bool:
    """SpotFX pushed this lull's timing (the rule applies), rather than the
    effect falling back to its legacy progress fraction."""
    return float(config.get(RAMP_KEY, 0.0) or 0.0) > 0.0


def watchdog_progress(config: Mapping, phase: str, progress: float,
                      phase_t: float) -> float:
    """The progress the shared orphan watchdog (particle_handoff.
    phase_release_due) should judge a lull by. A told lull is measured on the
    effect's own clock, so its build completes when SpotFX's ramp would have
    (`lull_ramp_s` in) — never on its first frame, which is where a lull
    following a completed charge reads progress 1.0 and would otherwise be
    released PHASE_GRACE_S (12 s) in, cutting a long lull short. Anything
    else is judged by its progress, exactly as before."""
    if phase != "lull" or not told(config):
        return progress
    ramp_s = float(config.get(RAMP_KEY, 0.0) or 0.0)
    return min(1.0, max(0.0, float(phase_t)) / ramp_s)


def _clip01(x: float) -> float:
    return min(1.0, max(0.0, x))


def lull_timing(config: Mapping, progress: float, phase_t: float,
                legacy_dark_at: float) -> LullTiming:
    """Where this lull is relative to its dark point (module docstring).
    `phase_t` is the effect's own seconds since the lull's edge (used once
    SpotFX has told it the lull's timing); `legacy_dark_at` is the progress
    the effect's dark point sat at before the rule — used verbatim when
    SpotFX did not push the keys."""
    p = _clip01(float(progress))
    ramp_s = float(config.get(RAMP_KEY, 0.0) or 0.0)
    dark_s = float(config.get(DARK_KEY, 0.0) or 0.0)
    if not told(config):
        legacy = float(legacy_dark_at)
        if legacy <= 0.0:
            return LullTiming(1.0, True, p)
        dark = p >= legacy
        if legacy >= 1.0:
            after = 1.0 if dark else 0.0
        else:
            after = _clip01((p - legacy) / (1.0 - legacy))
        return LullTiming(min(p / legacy, 1.0), dark, after)
    t = max(0.0, float(phase_t))
    if dark_s <= 0.0:
        approach = 1.0
    else:
        approach = min(t / dark_s, 1.0)
    dark = t >= dark_s
    span = ramp_s - dark_s
    if span > MIN_AFTER_SPAN_S:
        after = _clip01((t - dark_s) / span)
    else:
        after = 1.0 if dark else 0.0
    return LullTiming(approach, dark, after)
