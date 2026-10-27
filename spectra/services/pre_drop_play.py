"""WHETHER A PRE-DROP PLAYS — the one rule (predrop plan step 5, §3.3).

A drop sequence (or one of his own grouped charge/lull/drop) may carry a
PRE-DROP: a spike or a vocal intro shortly before the drop
(predrop_detector.py finds them; the Timeline and the Drops panel edit
them). Whether it PLAYS is decided once, at the moment its LULL fires,
here, and that one answer drives everything that follows: the told keys on
each pre-drop effect's lull arm (fx/effects/pre_drop.py; none yet — the set
is empty until step 6) and the drop's colour change, which fades across a
pre-drop that plays and is instant on one that does not
(trigger_engine's THE DROP COLOUR CHANGE).

THE RULE, in order (the first that fails is the reason):

1. there is a pre-drop and its PART may play — present, not switched off,
   and approved, or waiting with a tier that plays on its own, or Testing
   (drop_firing._member_ms / his_pre_drops decide that before a candidate
   is ever built: no candidate, nothing to decide);
2. the sequence's LULL fires (a candidate only rides a lull: a sequence
   without one plays its drop exactly as today — there is no build for the
   pre-drop to change);
3. a scene is showing — the one whose lull this is (a drop-led switch that
   cut at the charge already put the incoming scene there; one that cuts on
   the drop has not yet, so the lull and its pre-drop run on the scene that
   is showing);
4. that scene has the pre-drop's KIND on (SceneV2.pre_drop_spike /
   pre_drop_intro `enabled`);
5. the pre-drop-to-drop GAP — the music's gap — is inside that kind's
   window [min_ms, max_ms];
6. the pre-drop lands at least MIN_AFTER_LULL_MS after the lull actually
   fired (a vocal intro entering less than 200 ms into its lull is not
   told: there is no lull left to shape before it).

TIMING (docs/SPECTRA_TIMING_CONVENTIONS.md): `at_ms` is measured from the
lull's ACTUAL fire on the show clock — the tick's own position, which can
be up to one TICK_S after the lull's mark — to the pre-drop's target, so
the pre-drop lands on the clap or the entry whatever the lull's own
lateness. The target is the pre-drop's mark moved WITH ITS DROP: the drop's
own fire shift (its band anchor plus the drop timing offset, OFFSET family)
applies to both, so the gap stays the music's gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from fx.effects import pre_drop as fx_pre_drop

MIN_AFTER_LULL_MS = 200

KIND_LABELS = {fx_pre_drop.KIND_SPIKE: "spike",
               fx_pre_drop.KIND_INTRO: "vocal intro"}

REASON_PLAYS = "plays"
REASON_NO_SCENE = "no_scene"
REASON_UNKNOWN_KIND = "unknown_kind"
REASON_KIND_OFF = "kind_off"
REASON_GAP_SHORT = "gap_below_min"
REASON_GAP_LONG = "gap_above_max"
REASON_TOO_SOON = "too_soon_after_lull"


@dataclass(frozen=True)
class PreDropCandidate:
    """A pre-drop that MAY play on this lull (rule 1 and 2 already passed):
    `at_ms` from the lull's actual fire to the pre-drop's target, `gap_ms`
    from it to the drop's, its `kind`, and `key` — whose pre-drop it is (a
    sequence key, or "his:<drop trigger id>")."""
    at_ms: int
    gap_ms: int
    kind: str
    key: str = ""

    def as_dict(self) -> dict:
        return {"at_ms": int(self.at_ms), "gap_ms": int(self.gap_ms),
                "kind": self.kind, "key": self.key}


@dataclass(frozen=True)
class Verdict:
    plays: bool
    reason: str
    kind: str
    at_ms: int
    gap_ms: int
    window: Optional[dict] = None

    def as_dict(self) -> dict:
        return {"plays": self.plays, "reason": self.reason, "kind": self.kind,
                "at_ms": int(self.at_ms), "gap_ms": int(self.gap_ms),
                "window": self.window}


def window_of(scene: Any, kind: str) -> Optional[Any]:
    getter = getattr(scene, "pre_drop_window", None)
    return getter(kind) if callable(getter) else None


def decide(scene: Any, cand: PreDropCandidate) -> Verdict:
    """Rules 3-6 for a candidate (module docstring)."""
    def out(plays: bool, reason: str, window: Any = None) -> Verdict:
        w = None if window is None else {
            "enabled": bool(window.enabled), "min_ms": int(window.min_ms),
            "max_ms": int(window.max_ms)}
        return Verdict(plays, reason, cand.kind, int(cand.at_ms),
                       int(cand.gap_ms), w)

    if scene is None:
        return out(False, REASON_NO_SCENE)
    if cand.kind not in fx_pre_drop.KINDS:
        return out(False, REASON_UNKNOWN_KIND)
    window = window_of(scene, cand.kind)
    if window is None:
        return out(False, REASON_UNKNOWN_KIND)
    if not window.enabled:
        return out(False, REASON_KIND_OFF, window)
    if cand.gap_ms < window.min_ms:
        return out(False, REASON_GAP_SHORT, window)
    if cand.gap_ms > window.max_ms:
        return out(False, REASON_GAP_LONG, window)
    if cand.at_ms < MIN_AFTER_LULL_MS:
        return out(False, REASON_TOO_SOON, window)
    return out(True, REASON_PLAYS, window)


def sentence(verdict: Mapping) -> str:
    """One plain sentence for a verdict (the preview, the show log)."""
    kind = KIND_LABELS.get(str(verdict.get("kind")), "pre-drop")
    gap = int(verdict.get("gap_ms") or 0)
    w = verdict.get("window") or {}
    reason = verdict.get("reason")
    if reason == REASON_PLAYS:
        return (f"The {kind} plays: {gap} ms before the drop, inside this "
                f"scene's {w.get('min_ms')}-{w.get('max_ms')} ms window.")
    if reason == REASON_KIND_OFF:
        return f"This scene has {kind} pre-drops off: the lull runs as before."
    if reason == REASON_GAP_SHORT:
        return (f"The {kind} is {gap} ms before the drop, shorter than this "
                f"scene's {w.get('min_ms')} ms minimum: the lull runs as before.")
    if reason == REASON_GAP_LONG:
        return (f"The {kind} is {gap} ms before the drop, longer than this "
                f"scene's {w.get('max_ms')} ms maximum: the lull runs as before.")
    if reason == REASON_TOO_SOON:
        return (f"The {kind} lands less than {MIN_AFTER_LULL_MS} ms after its "
                "lull starts: the lull runs as before.")
    if reason == REASON_NO_SCENE:
        return "No scene is showing: nothing plays."
    return "This pre-drop's kind is not known: the lull runs as before."


def look_for(scene: Any, entry_id: str, effect_type: str, kind: str) -> str:
    """The resolved look an entry plays for a pre-drop `kind`
    (fx/effects/pre_drop.resolve_look against the effect's declared looks);
    "" when the effect declares none or the entry is not found."""
    from fx import device_model
    declared = device_model.pre_drop_looks(effect_type)
    if not declared:
        return ""
    entry = next((d for d in getattr(scene, "devices", []) or []
                  if getattr(d, "id", None) == entry_id), None)
    picks = getattr(entry, "pre_drop_looks", None)
    chosen = ({"spike": picks.spike, "intro": picks.intro}
              if picks is not None else None)
    return fx_pre_drop.resolve_look(declared, kind, chosen)


def window_bounds() -> dict:
    """Each kind's legal bounds and defaults, read off the model's own
    Field(ge=, le=) — what GET /api/registry serves the Phase tab, so the
    page never carries a second copy."""
    from spectra.models.scene import PreDropIntroWindow, PreDropSpikeWindow

    def bounds(cls) -> dict:
        lo = hi = None
        for c in cls.model_fields["min_ms"].metadata:
            lo = getattr(c, "ge", lo)
        for c in cls.model_fields["max_ms"].metadata:
            hi = getattr(c, "le", hi)
        return {"min_bound": lo, "max_bound": hi,
                "default_min_ms": cls.model_fields["min_ms"].default,
                "default_max_ms": cls.model_fields["max_ms"].default}

    return {"kinds": {
        fx_pre_drop.KIND_SPIKE: {"label": "Spike", **bounds(PreDropSpikeWindow)},
        fx_pre_drop.KIND_INTRO: {"label": "Vocal intro",
                                 **bounds(PreDropIntroWindow)},
    }}
