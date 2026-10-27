"""THE PRE-DROP — how a lull is TOLD that its drop has one, and a clock that
names a phase's moments for an effect drawing them.

Built 2026-10-26 (predrop plan step 5, /home/javi/fleet-spotfx/data/
predrop-plan/report.md §3.3-3.4). Some drops have a PRE-DROP: a moment
shortly before the drop that a scene may play — a SPIKE (one loud short hit
in the high band, a clap) or a VOCAL INTRO (a line entering in the mid band
out of a hush). spectra/services/predrop_detector.py finds them; a scene
chooses per kind whether its pre-drops play and inside what gap
(SceneV2.pre_drop_spike / pre_drop_intro); each scene entry chooses a LOOK
per kind (SceneDeviceConfig.pre_drop_looks).

THE PRE-DROP IS NOT A PHASE. A new `phase` value would be rejected by every
effect that does not know it (`vol.In(["none","charge","lull","drop"])`
drops the whole write), and a scene without pre-drops must work exactly as
before. So the pre-drop rides the LULL's own arm write as four more told
keys — the way the dark point (lull_dark.py), the hand-off
(lull_handoff.py) and the breath-hold (phase_grammar.py) already do:

- `pre_drop_at_s` (float s): from the lull's start to the pre-drop, on the
  effect's own phase clock (0 = none);
- `pre_drop_s` (float s): the pre-drop-to-drop gap;
- `pre_drop_kind` (str): "spike" or "intro" ("" = none);
- `pre_drop_look` (str): the look the showing scene chose for this entry
  and kind, already resolved ("auto" -> the effect's own recommendation,
  "same" -> the spike's look), so the effect needs no registry.

WHO IS TOLD: only effects in `fx.device_model.PRE_DROP_EFFECTS` (empty at
step 5; Fireworks and Pulse joined at step 6, Orbits and Black Hole at step
7 — each member's own PRE_DROP constants are its look). SpotFX decides
(spectra/services/pre_drop_play.py is the one rule): on a lull arm whose
sequence has a pre-drop that may play, that lands at least
pre_drop_play.MIN_AFTER_LULL_MS after the lull actually fired, whose kind
the showing scene has on, with its gap inside that kind's window.

THE LULL IS MEASURED TO THE PRE-DROP for a member that plays it (his
answer 4: "the blackout needs to happen before the pre-drop, so it
shifts"): its progress ramp, its dark point (when it is a LULL_DARK member)
and its breath-hold are computed over the time to the pre-drop instead of
the drop, so `lull_breath_at_s + lull_breath_s == pre_drop_at_s` exactly —
dark, then the pre-drop, then its look runs into the drop. A member is
ALWAYS told the breath keys on a lull arm (the shifted breath when it plays
the pre-drop; its ordinary breath, or zeros when it is no breath-hold
effect, when it does not), so a breath shifted for one lull is never left
standing into the next. A breath ending on a told pre-drop holds no
BREATH_OVERRUN_S (phase_grammar._breath_gain): the pre-drop is on the
effect's own clock and cannot be lost.

THREE RULES (lull_dark.py's, kept identical):

1. KEYS RIDE ONLY THE DEDICATED PHASE WRITE — never in
   config/effect_params.json, never on an editor surface. A member splices
   `**schema_fields()` (and `**phase_grammar.breath_schema_fields()` if it
   is not a breath-hold effect already) into its CONFIG_SCHEMA and `*KEYS`
   into ADVANCED_KEYS (and into PASSIVE_CONFIG_KEYS for a strip phase
   member, so the arm write stays passive).
2. EVERY MEMBER GETS EVERY KEY ON EVERY LULL ARM, even "none" (NOT_TOLD):
   `Effect._apply_config` partial-merges, so a pre-drop told for one lull
   would otherwise survive into the next.
3. NOT TOLD IS THE EFFECT'S OWN LULL. An older SpotFX, a hand test, a LedFX
   UI scrub, or a lull whose pre-drop does not play: zeros, and the effect
   draws its ordinary lull.

HOW AN EFFECT OPTS IN (step 6 onwards):
  1. the schema fields and ADVANCED_KEYS (rule 1);
  2. its registry name in `fx.device_model.PRE_DROP_EFFECTS`;
  3. its looks in config/effect_params.json — a `pre_drop_looks` block on
     the effect: {"looks": {name: {"label": ..., "kinds": [...]}},
     "auto": {"spike": name, "intro": name}} — so the Phase tab offers them
     and "auto" means its recommendation;
  4. read `phase_clock(...)` each frame and draw a handler per segment.

THE PHASE CLOCK (plan 3.4): one object per frame with the named moments
worked out, from keys an effect already receives plus these four:

    clk = pre_drop.phase_clock(self._config, phase=self._phase,
                               progress=self.phase_progress,
                               phase_t=self._phase_t, prev=self._clk)
    self._clk = clk
    clk.segment     # "charge" | "approach" | "dark" | "breath" |
                    # "pre_drop" | "drop" | "none"
    clk.kind        # "spike" | "intro" (the told pre-drop's kind, else "")
    clk.look        # the look the scene chose for this entry and kind
    clk.frac        # 0 -> 1 through the current segment
    clk.edge        # True on the first frame of a segment
    clk.until_drop  # seconds to the drop when known

The lull's two ways are two segment lists: without a pre-drop `approach ->
dark -> breath`, the breath ending on the drop; with one `approach -> dark
-> breath -> pre_drop`, the breath ending on the pre-drop. Reading the clock
changes nothing about an effect's output on its own.
"""
from __future__ import annotations

from typing import Mapping, NamedTuple, Optional

import voluptuous as vol

from fx.effects import lull_dark, phase_grammar

AT_KEY = "pre_drop_at_s"
GAP_KEY = "pre_drop_s"
KIND_KEY = "pre_drop_kind"
LOOK_KEY = "pre_drop_look"
KEYS = (AT_KEY, GAP_KEY, KIND_KEY, LOOK_KEY)

KIND_SPIKE = "spike"
KIND_INTRO = "intro"
KINDS = (KIND_SPIKE, KIND_INTRO)

LOOK_AUTO = "auto"
LOOK_SAME = "same"           # the vocal intro wears the spike's look

NOT_TOLD = {AT_KEY: 0.0, GAP_KEY: 0.0, KIND_KEY: "", LOOK_KEY: ""}

SEGMENTS = ("none", "charge", "approach", "dark", "breath", "pre_drop",
            "drop")

# a breath "ends on the pre-drop" when the two land this close (seconds)
_ON_PRE_DROP_EPS_S = 1e-3


def keys_for(at_s: float, gap_s: float, kind: str, look: str) -> dict:
    """The four keys SpotFX pushes on a member's lull arm when its pre-drop
    plays (module docstring)."""
    return {AT_KEY: max(0.0, float(at_s)), GAP_KEY: max(0.0, float(gap_s)),
            KIND_KEY: str(kind), LOOK_KEY: str(look or "")}


def schema_fields() -> dict:
    """CONFIG_SCHEMA entries for the four pushed keys (rule 1)."""
    return {
        vol.Optional(
            AT_KEY,
            description="Lull: seconds from the lull's start to its pre-drop "
                        "(driven by SpotFX; 0 = none)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional(
            GAP_KEY,
            description="Lull: seconds from the pre-drop to the drop "
                        "(driven by SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional(
            KIND_KEY,
            description="Lull: the pre-drop's kind, spike or intro (driven "
                        "by SpotFX; empty = none)",
            default="",
        ): vol.In(("",) + KINDS),
        vol.Optional(
            LOOK_KEY,
            description="Lull: the pre-drop look the scene chose for this "
                        "entry (driven by SpotFX)",
            default="",
        ): str,
    }


def _f(config: Mapping, key: str) -> float:
    try:
        return float(config.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def told(config: Mapping) -> bool:
    """This lull was told a pre-drop it plays."""
    return _f(config, AT_KEY) > 0.0 and config.get(KIND_KEY) in KINDS


def at_s(config: Mapping) -> float:
    return _f(config, AT_KEY) if told(config) else 0.0


def gap_s(config: Mapping) -> float:
    return _f(config, GAP_KEY) if told(config) else 0.0


def kind(config: Mapping) -> str:
    return str(config.get(KIND_KEY)) if told(config) else ""


def look(config: Mapping) -> str:
    return str(config.get(LOOK_KEY) or "") if told(config) else ""


def breath_ends_on_pre_drop(config: Mapping) -> bool:
    """The told breath-hold ends exactly on a told pre-drop — the case whose
    black holds no BREATH_OVERRUN_S (phase_grammar._breath_gain)."""
    if not told(config):
        return False
    b = _f(config, phase_grammar.BREATH_KEY)
    if b <= 0.0:
        return False
    end = _f(config, phase_grammar.BREATH_AT_KEY) + b
    return abs(end - _f(config, AT_KEY)) <= _ON_PRE_DROP_EPS_S


def resolve_look(declared: Optional[Mapping], kind_: str,
                 chosen: Optional[Mapping]) -> str:
    """The look name an entry's choice resolves to for `kind_`, against the
    effect's declared `pre_drop_looks` block (module docstring, opt-in step
    3). "auto" (or a name the effect does not declare) is the effect's own
    recommendation for the kind; "same" on the vocal intro is whatever the
    spike resolves to. "" when the effect declares no looks."""
    if not declared or kind_ not in KINDS:
        return ""
    looks = declared.get("looks") or {}
    auto = declared.get("auto") or {}
    picks = chosen or {}
    target = kind_
    choice = str(picks.get(kind_) or LOOK_AUTO)
    if kind_ == KIND_INTRO and choice == LOOK_SAME:
        target = KIND_SPIKE
        choice = str(picks.get(KIND_SPIKE) or LOOK_AUTO)
        if choice == LOOK_SAME:
            choice = LOOK_AUTO
    if choice != LOOK_AUTO and choice in looks:
        return choice
    name = auto.get(target)
    return str(name) if name in looks else ""


# ── the phase clock ─────────────────────────────────────────────────────────

class PhaseClock(NamedTuple):
    segment: str
    kind: str
    look: str
    frac: float
    edge: bool
    until_drop: Optional[float]
    phase: str
    t: float


def _clip01(x: float) -> float:
    return min(1.0, max(0.0, float(x)))


def _span_frac(t: float, start: float, end: float) -> float:
    span = end - start
    if span <= 1e-9:
        return 1.0 if t >= start else 0.0
    return _clip01((t - start) / span)


def _lull_segment(config: Mapping, progress: float,
                  t: float) -> tuple[str, float, Optional[float]]:
    dark_told = lull_dark.told(config)
    dark_s = _f(config, lull_dark.DARK_KEY) if dark_told else None
    b = _f(config, phase_grammar.BREATH_KEY)
    breath_at = _f(config, phase_grammar.BREATH_AT_KEY) if b > 0.0 else None
    if told(config):
        pre_at = _f(config, AT_KEY)
        drop_at = pre_at + _f(config, GAP_KEY)
        if t >= pre_at:
            return ("pre_drop", _span_frac(t, pre_at, drop_at),
                    max(0.0, drop_at - t))
        end = pre_at
    elif breath_at is not None:
        end = breath_at + b
        drop_at = end
    else:
        end = None
        drop_at = None
    until = None if drop_at is None else max(0.0, drop_at - t)
    if breath_at is not None and t >= breath_at:
        return "breath", _span_frac(t, breath_at, breath_at + b), until
    if dark_s is not None and t >= dark_s:
        stop = breath_at if breath_at is not None else end
        frac = _span_frac(t, dark_s, stop) if stop is not None else 1.0
        return "dark", frac, until
    stop = (dark_s if dark_s is not None
            else breath_at if breath_at is not None else end)
    frac = _span_frac(t, 0.0, stop) if stop is not None else _clip01(progress)
    return "approach", frac, until


def phase_clock(config: Mapping, phase: str, progress: float, phase_t: float,
                prev: Optional[PhaseClock] = None) -> PhaseClock:
    """Where `phase` is on the effect's own clock (module docstring, THE
    PHASE CLOCK). `phase_t` is the effect's seconds since the phase's edge;
    `prev` the clock it read last frame (None on the first), which is what
    makes `edge` true on a segment's first frame and on a fresh instance of
    the same segment (phase_t went backwards: a new lull)."""
    t = max(0.0, float(phase_t))
    p = _clip01(progress or 0.0)
    if phase == "charge":
        segment, frac, until = "charge", p, None
    elif phase == "lull":
        segment, frac, until = _lull_segment(config, p, t)
    elif phase == "drop":
        segment, frac, until = "drop", p, 0.0
    else:
        segment, frac, until = "none", 0.0, None
    in_lull = phase == "lull"
    edge = (prev is None or prev.segment != segment or prev.phase != phase
            or t < prev.t)
    return PhaseClock(segment=segment, kind=kind(config) if in_lull else "",
                      look=look(config) if in_lull else "", frac=frac,
                      edge=edge, until_drop=until, phase=str(phase), t=t)


__all__ = [
    "AT_KEY", "GAP_KEY", "KIND_KEY", "LOOK_KEY", "KEYS", "KIND_SPIKE",
    "KIND_INTRO", "KINDS", "LOOK_AUTO", "LOOK_SAME", "NOT_TOLD", "SEGMENTS",
    "keys_for", "schema_fields", "told", "at_s", "gap_s", "kind", "look",
    "breath_ends_on_pre_drop", "resolve_look", "PhaseClock", "phase_clock",
]
