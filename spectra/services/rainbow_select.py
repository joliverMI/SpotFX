"""Rainbow select (owner ask 2026-08-20): a colour set is authored "rainbow"
or "single" (models/color_set.py ColorSetCard.is_rainbow — enumerated, never
inferred; see scripts/mark_rainbow_color_sets.py for exactly which of his
cards carry it). Above the room's rainbow_select_limit, only rainbow-marked
cards are eligible; at or below it, only single (non-rainbow) cards are —
his words: "anything above chooses a rainbow color set... they should only
get selected if they are above the set rainbow limit."

A clean partition, not a filter that can leave BOTH kinds eligible at once:
this is deliberate — "anything above chooses a rainbow color set" reads as
exclusive, not merely permissive. Wired at the same one automatic-selection
choke point mode_availability/color_set_preferred already reach
(scene_sequencer._default_eligible_sets) — matching that precedent, this
is NOT applied to drift_conductor's destination pool or scene_response's
flare colour-jump pool (checked, not assumed to be covered; those two
choke points don't apply mode_availability/preference either, for the
same reason: out of this feature's stated scope).
"""
from __future__ import annotations


def eligible(is_rainbow: bool, intensity: float, limit: float) -> bool:
    """True when a card of this rainbow-ness may be picked at this
    intensity. intensity > limit: rainbow-only. intensity <= limit:
    single-only (never both, never neither, for a well-formed limit)."""
    return is_rainbow if intensity > limit else not is_rainbow
