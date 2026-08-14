"""The room's genuinely-driven virtual roster — ground truth for the
fresh-handover activation gate to validate fx-live/config.json's
declared-active virtuals against (report gate, 2026-08-14: the
"unfalsifiable gate" defect).

fx-live/config.json is seeded VERBATIM from the old LedFX world
(scripts/seed_spectra_fx_live.py) and inherits its dynamic tricks — a
full-span "crystal" duplicate of "crystal-mapper", mask/foreground/
background layer virtuals per mapper, gap-* dummy placeholders, and
contextual rooms (dining, porch, sconces) the old app drove but SPECTRA's
own scene engine may never address. "Has an effect and isn't
active:false" (live_host._config_expected_active_ids) is necessary but not
sufficient for "this light is supposed to rise."

The room's own engine (spectra/services/scene_compiler.py) resolves every
scene entry through exactly two address spaces: device_model's imported
category topology (target_kind "all"/"category", storage/
device_categories.json via fx.device_model) and literal virtual ids
(target_kind "virtual", spectra/services/scene_store.py). Their union is
everything the room's scene engine could ever legitimately address — the
SAME truth compile_scene() itself resolves writes against, so this can
never drift out of step with a real fire.

Deliberately NOT restricted to only the categories/virtuals referenced by
CURRENTLY STORED scenes: importing a virtual into a category is itself a
curation decision (a human chose to bring that light into the topology),
and "absent from every category AND every scene's literal target" is
exactly the "genuinely never addressed" case this module exists to name —
narrower than that risks recreating the unfalsifiable-gate defect in
reverse (refusing to trust a legitimately-imported light just because no
CURRENT scene happens to reference it yet — CAUTION in the report: not
every declared extra is stale).

genuinely_driven_virtual_ids() returns an EMPTY set when no ground truth
exists (storage/device_categories.json missing/empty AND zero stored
scenes) — callers must treat empty as "no restriction available", never as
"nothing is genuinely driven": an absent ground truth must never make a
safety gate vacuously pass.
"""
from __future__ import annotations

from fx import device_model


def genuinely_driven_virtual_ids() -> set[str]:
    from spectra.services import scene_store

    driven: set[str] = set(device_model.get_all_virtual_ids())
    for scene in scene_store.list_all():
        for dev in scene.devices:
            if dev.target_kind == "virtual" and dev.target:
                driven.add(dev.target)
    return driven
