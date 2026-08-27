"""FORCE COLOUR — the room's colour stops changing and stays on his pick.

Owner ask 2026-08-27 (corr=dee5132bf1a25c35, item 3), verbatim: "Add an
ability to force a color set or color group, similar to force scene, so the
color does not change and stays on a specific set."

Force Scene's twin, one axis over: Force Scene pins WHICH SCENE plays,
this pins WHICH COLOURS it wears. The two are independent and compose
(pin a scene, pin a colour, pin both, pin neither) — neither reads the
other's fields.

  room_controls.RoomControlState.force_color_enabled/force_color_target_id

`force_color_target_id` is a `ColorSetCard` id — a SET or a GROUP, the same
vocabulary every other colour surface in SPECTRA accepts (POST
/api/room-color/apply, a select_color_set trigger action, a scene fire's
own color_set_id). Default off, target None, so the field's arrival changes
nothing about his room.

WHAT A PIN MEANS, SET vs GROUP (stated, because the two genuinely differ):

  A SET pin is fully STATIC — `resolve_for_fire` on a "set" card is
  deterministic (its own entries, with every enclosing Group's override
  entries chained on, §10's 2026-08-19 broadening). Every fire wears
  exactly the same colours.

  A GROUP pin keeps the GROUP's own rotation semantics LIVE — that is what
  a Group IS (`color_set_groups._resolve_group_fire`: cycle wrap/bounce or
  weighted+exclude_current picking, Palette Sync, the group's override
  entries merged on top). Pinning a Group therefore means "only ever draw
  from this pool", not "freeze on one member". Nothing else could honour
  both halves of his sentence ("a color set OR color group") without
  either refusing groups outright or silently reducing a Group to whichever
  member happened to be current when he pressed the button. If he meant
  stricter, that is a tuning decision on top of this, not a different
  mechanism.

GATES — every automatic colour choice, each choke point checked
INDIVIDUALLY (§86's lesson: three separate functions in this same area each
had to be fixed on their own; "the family is covered" is not evidence):

  scene_sequencer.fire_scene_by_id      the scene-fire colour, replacing
                                        whatever the caller resolved
  scene_sequencer._roll_color_set       the sequencer's own colour roll —
                                        short-circuited so it never churns
                                        the wheel for a pick that is about
                                        to be overridden anyway
  scene_compiler.room_active_set        the TERMINAL fallback — the path
                                        100% of his real fire_scene
                                        triggers actually take (none carry
                                        an explicit color_set_id)
  drift_conductor.tick/_journey_leg     the colour journey HOLDS its walk
                                        (held_for="force_color"), the same
                                        held shape a live rainbow palette
                                        and an active gradient already use
  drift_conductor._bootstrap_room_color a set-less room bootstraps to the
                                        PIN, not to a selector draw
  scene_response._color_jump            a flare's colour jump lands the
                                        pin instead of rolling the selector
  trigger_engine._default_select_color_set  a select_color_set trigger
                                        redirects to the pin, NAMED in its
                                        fire-history record (forced_from)

NOT gated, deliberately: his own EXPLICIT actions. POST /api/room-color/
apply and the Colour Sets editor's Preview still do exactly what he asked
them to — but they NAME the contradiction (`overrode_force_color`) rather
than silently applying under a pin he may have forgotten is on, the same
"an explicit press always wins, but say so" discipline Force Scene's
overrode_disabled/overrode_dwell already established. A manual apply does
NOT clear the pin, and the next automatic change reasserts it.

PRECEDENCE (named, not guessed):

  vs. the ACTIVE 2D GRADIENT (room_controls.active_gradient_id, which also
  replaces the journey) — FORCE COLOUR WINS while enabled, and the gradient
  resumes on release. Reasoning: both are "an alternate colour source takes
  over", so one has to be on top; the pin is the more explicit, more
  momentary statement (a switch he just flipped, meaning "stop changing"),
  while the gradient is a standing configuration. A gradient that kept
  driving under a colour pin would make the pin look broken in exactly the
  way Force Scene's passive-redirect gap did. Nothing is torn down: the
  gradient id stays stored, and the very next conductor leg after release
  picks it back up.

  vs. AMBIENT's hold — composes for free, VERIFIED not assumed, exactly the
  way Dark/Light already composes with it (AGENTS.md's own note): a frozen
  Hue device is driven by direct bridge REST (services/ambient.py),
  bypassing the effect-config write path entirely, so a colour pin has no
  visible effect on it while it is held and applies normally the moment it
  isn't. Neither feature reads the other's fields; the orthogonality is a
  property of the write path, not a rule either encodes.

  vs. PREVIEW HOLD (preview_pause) — preview still outranks everything,
  unchanged: the pin's own reconcile fire goes through
  drift_conductor.apply_set_directly, and the conductor's tick already
  defers under preview.

DISABLED (§ColorSetCard.disabled, PR #200): pinning a card he has marked
disabled is the same contradiction shape as Force Scene firing a disabled
scene — it APPLIES and is NAMED (`overrode_disabled`), never silently
refused. So the pin resolves through `color_set_groups.resolve_for_fire`,
never `resolve_for_fire_mode_gated`: mode availability and the disabled
gate both exist to filter AUTOMATIC choices, and a pin is not one. (A
pinned GROUP whose every member is disabled still resolves to None — that
is the group's own emptiness, not a gate, and is reported as a stated
reason rather than a silent keep.)

SONIC: `force_color_target_id` is deliberately NOT in
settings_console.SETTINGS_REGISTRY, following force_scene_*'s own precedent
— it names a card by opaque id, which a spoken instruction cannot produce
and a mis-transcription would silently mispoint.

This module is a LEAF: it imports nothing under spectra/services at module
scope (every lookup is a local import inside the function that needs it),
so any of the choke points above can import it at any scope without
reintroducing the 2026-08-20 light-mode cold-start crash class.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The reason string every held/redirected surface reports, so one grep
# finds every place a pin is what stopped the colour from changing.
HELD_FOR = "force_color"


def _controls(controls: Any | None = None):
    if controls is not None:
        return controls
    from spectra.services.room_controls import load_room_controls
    return load_room_controls()


def pinned_id(controls: Any | None = None) -> Optional[str]:
    """The pinned card id while the pin is enabled AND a target is set,
    else None. Does NOT check the id resolves — see pinned_card."""
    st = _controls(controls)
    if not getattr(st, "force_color_enabled", False):
        return None
    return getattr(st, "force_color_target_id", None) or None


def pinned_card(controls: Any | None = None):
    """The pinned card RESOLVED for a fire — a Group picks a member and
    overlays its own entries (rotation stays live, see the module
    docstring), a Set chains every enclosing Group's overrides onto its
    own. None when: the pin is off, no target is set, the target id names
    no card, or a pinned Group has no usable member. Never mode- or
    disabled-gated: a pin is an explicit statement, not an automatic pick.

    Called fresh at every choke point, every fire — never cached — so a
    Group's rotation advances exactly as it would for any other fire of
    that Group, and an edit to the pinned card takes effect immediately."""
    set_id = pinned_id(controls)
    if set_id is None:
        return None
    from spectra.services import color_set_groups, color_sets
    card = color_sets.get_by_id(set_id)
    if card is None:
        logger.warning("force colour: pinned id '%s' names no colour card — "
                       "the room's own colour selection continues", set_id)
        return None
    resolved = color_set_groups.resolve_for_fire(card)
    if resolved is None:
        logger.warning("force colour: pinned group '%s' has no usable member "
                       "— the room's own colour selection continues",
                       getattr(card, "name", set_id))
    return resolved


def active(controls: Any | None = None) -> bool:
    """True when a pin is enabled AND its target id names a real card —
    i.e. when this feature is governing the room's colour right now.

    DELIBERATELY CHEAP AND SIDE-EFFECT-FREE: it must never call
    pinned_card(), because resolving a pinned GROUP advances that group's
    own rotation cursor (color_set_groups._pick_member). This function is
    called from held/deferral checks that run on every conductor leg and
    every status poll — advancing a rotation there would roll his colours
    on nothing but someone looking at the page. pinned_card() is called
    exactly once per real fire, at the choke point about to use its
    result, which is what makes a Group's rotation advance once per fire
    and no more.

    A pin whose target names a deleted card is NOT active: the room keeps
    choosing for itself rather than losing its colour entirely, the same
    degrade-gracefully posture every other colour choke point takes on an
    unresolvable reference. (A pinned Group whose every member is
    currently disabled reads as active here and resolves to None at the
    fire — the caller then falls back exactly as it already does for any
    unusable colour reference.)"""
    set_id = pinned_id(controls)
    if set_id is None:
        return False
    from spectra.services import color_sets
    return color_sets.get_by_id(set_id) is not None


def overrode_disabled(controls: Any | None = None) -> bool:
    """True when the pin is live and the card he PINNED is marked disabled
    — the contradiction to NAME, never to act on silently.

    Scoped to the referenced card only, for the same side-effect reason as
    active() above: learning which member a pinned Group resolves to would
    advance its cursor. The reconcile path (room_controls.
    reconcile_force_color_if_changed) already holds the resolved card in
    hand and checks BOTH there, which is where the badge he actually reads
    comes from."""
    set_id = pinned_id(controls)
    if set_id is None:
        return False
    from spectra.services import color_sets
    card = color_sets.get_by_id(set_id)
    return card is not None and getattr(card, "disabled", False)
