"""Rainbow select (owner ask 2026-08-20): a colour set is authored "rainbow"
or "single" (models/color_set.py ColorSetCard.is_rainbow — enumerated, never
inferred; see scripts/mark_rainbow_color_sets.py for exactly which of his
cards carry it). Above the room's rainbow_select_limit, only rainbow-marked
cards are eligible; at or below it, only single (non-rainbow) cards are —
his words: "anything above chooses a rainbow color set... they should only
get selected if they are above the set rainbow limit."

A clean partition, not a filter that can leave BOTH kinds eligible at once:
this is deliberate — "anything above chooses a rainbow color set" reads as
exclusive, not merely permissive. Wired at the automatic-selection choke
point mode_availability/color_set_preferred already reach
(scene_sequencer._default_eligible_sets, and scene_sequencer.
automatic_pool_cards for the drop colour change) AND, since the owner's
2026-11-11 report that rainbow sets kept appearing on flares at low
Energy, scene_response._default_eligible_sets (the flare colour-jump
pool) too — matching that precedent for the gate itself, but NOT for
mode_availability/color_set_preferred, which the flare pool still does
not apply (out of this fix's stated scope; see scene_response.py's
_default_eligible_sets docstring/comment). It is NOT applied to
drift_conductor's destination pool (checked, not assumed to be covered;
out of scope for the same reason).
"""
from __future__ import annotations


def eligible(is_rainbow: bool, intensity: float, limit: float) -> bool:
    """True when a card of this rainbow-ness may be picked at this
    intensity. intensity > limit: rainbow-only. intensity <= limit:
    single-only (never both, never neither, for a well-formed limit)."""
    return is_rainbow if intensity > limit else not is_rainbow
