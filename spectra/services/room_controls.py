"""SPECTRA's room-control surface — agent-tellable room-wide switches that
don't belong to any one scene (spectra-kept-equivalents, the owner's KEPT
legacy picks: decision-legacy-retirement-picks.md):

  display_mode              the legacy global Default/Dark/Light display-mode
  display_light_bg_color/   toggle equivalent (services/display_mode.py in
  _brightness                legacy; day-one bar item, SPECTRA_SPEC.md §9 —
  dark_light_shield_         NOT the retired per-node Light Mode Chooser,
  categories/_virtuals       §36). THREE states, matching legacy exactly
                          (2026-08-16 rebuild — see the "three-state
                          rebuild" note below for why the original two-state
                          bool was a mislabel, not a smaller-but-honest
                          version). "default" is his word "hybrid" (defer to
                          whatever the scene authors — the closest
                          structural match to legacy's own Default, per his
                          standing ruling: use "default" internally, label
                          it "Hybrid" in the UI). Full reasoning for Dark and
                          the shielding mechanism lives in spectra/services/
                          dark_light.py's module docstring — read that
                          before touching this. Reconciled the same way
                          ambient is: reconcile_dark_light_if_changed below,
                          called from the PUT /api/room-controls handler.

    THREE-STATE REBUILD, MIGRATION IS LOAD-BEARING (2026-08-16): the
    original build collapsed legacy's three states into a bool
    (dark_mode_enabled) by mapping False to legacy's Default semantics
    ("nothing forced, whatever's authored shows") while calling it "Light"
    in the code, the API status field, and the help text — legacy's actual
    Light (a configurable, always-on, immediately-repainted forced
    background) was never built. A scout investigation
    (data/spectra-display-mode-three-state/report.md) established this is
    divergent, not a subset — see dark_light.py's docstring for the fixed
    Light mechanism. The migration this field replaced it with is the part
    that can hurt him, so it is spelled out here rather than left for a
    future agent to re-derive:
      dark_mode_enabled: true  -> display_mode: "dark"
      dark_mode_enabled: false -> display_mode: "default", NEVER "light".
    The field WAS called light and BEHAVED as default; mapping false->light
    would have silently changed what his room does on deploy. false->default
    preserves his current behaviour exactly — nobody's room changes when
    this migration runs. Light is a new third option he can choose, never
    something he is moved into. See load_room_controls's migration block
    below for the code.
  brightness_multiplier  the legacy Brightness Multiplier action equivalent
                          (models.music_event.BrightnessAction) — dims/undims
                          the WHOLE room uniformly, applied at the write
                          seams (fx_executor for engine glides/jumps,
                          scene_compiler for scene-fire writes), never the
                          conductor's own carried baseline: the authored
                          "look" stays intact, only the OUTPUT is scaled.
  ambient_mode/_color     the legacy ledfx_ambient / ledfx_ambient_color
                          action equivalents, extended 2026-08-15 to the
                          Admiral's own three settings (his words: "it needs
                          to be a third setting where ambient mode can still
                          come into play when the music is still playing"):
                            "off"    — Ambient never holds. The whole room
                                       performs, Hue included. Today's
                                       unmodified default.
                            "always" — Hue is held lit at ambient_color
                                       UNCONDITIONALLY, music playing or
                                       not — his own request, not the
                                       precedence bug: "my Hue Lights are
                                       lit and bright but the other lights
                                       are still running the show." Every
                                       non-Hue device is architecturally
                                       untouched by Ambient regardless
                                       (services/ambient.py's device filter
                                       is Hue-only), so this mode composes
                                       for free with scene selection — no
                                       code path in selection_kernel.py/
                                       scene_sequencer.py/trigger_engine.py
                                       even references ambient state
                                       (grep-confirmed), so holding Hue can
                                       never double-penalise or starve the
                                       show elsewhere.
                            "auto"   — the 2026-08-15 music-precedence fix
                                       (§52): holds only when playback is
                                       CONFIRMED not-playing, releases the
                                       instant it's confirmed playing,
                                       carries an unresolved read forward
                                       rather than guessing either way.
                          This state is the durable record; the live
                          takeover itself (freezing the room's Hue devices,
                          holding them at ambient_color over direct bridge
                          REST) is driven by services/ambient.py via
                          services/ambient_music_gate.py (the mode
                          precedence gate), reconciled from
                          api/room_controls.py's PUT handler whenever these
                          fields change.
  ambient_brightness_note Brightness is DERIVED from whichever hex is in
                          effect (ambient_color or ambient_color_dark, via
                          effective_ambient_color below) — not a stored
                          field. Found live 2026-08-16: SPECTRA's own
                          ambient.py hard-coded full brightness
                          (AMBIENT_BRIGHTNESS_PCT=100) regardless of the hex,
                          because the bridge's xy chromaticity discards
                          luminance entirely (a darker shade of the same hue
                          is a ~0.01 xy shift — invisible on a real bulb),
                          so a "darker" colour could never dim anything, and
                          the read-back couldn't catch it either (it
                          confirmed against the same constant it had just
                          written). Legacy (services/ambient_mode.py) never
                          derived brightness from colour either — it kept a
                          wholly separate settings.ambient_brightness slider
                          — but the Admiral's own ruling on this fix
                          (2026-08-16, corr on spectra-ambient-brightness-
                          lost) overrides that for SPECTRA: "I want the
                          brightness of the color that I choose for both
                          ambient modes to be applied to the lights."
                          Derivation is HSV Value (the max RGB channel, his
                          own choice after comparing HSV Value/relative
                          luminance/CIE L*): relative luminance was rejected
                          because it double-counts a hue's intrinsic
                          dimness on top of the bulb's own chromaticity
                          render (a saturated blue computes to ~7% —
                          authoring a vivid colour and getting a bulb that's
                          effectively off is the exact "fights the picker"
                          failure this fix exists to prevent), and HSV Value
                          keeps his everyday cream ambient at ~96% (an
                          imperceptible ~4% dimmer than today) rather than
                          luminance's ~71% (a ~29% drop he never asked for
                          and would notice). See spectra/services/ambient.py
                          `_hsv_value_pct` for the implementation — the same
                          measure `_live_look`'s release catch-up ramp
                          already used for its own brightness proxy
                          (max(r,g,b)/255), so this is one formula, not two.
  ambient_color_dark      the SECOND ambient colour (2026-08-15, his ruling:
                          "dark mode during ambient should choose a
                          different color that I pick so we have one color
                          for regular ambient light mode or hybrid mode and
                          then one color for dark mode ... for now make them
                          the same but let me be able to pick it with the
                          color picker"). Authored the same way as
                          ambient_color — the same shipped LedFX colour
                          picker (PR #59), not a new control. `None` means
                          "not customized yet" — NOT a static copy of
                          ambient_color taken at some migration moment, so
                          the two stay identical by construction ("make them
                          the same, for now") until he explicitly picks a
                          different dark colour; see effective_ambient_color
                          below, the one place this fallback is resolved.
                          display_mode == "dark" (above) is the only switch
                          between the two — ambient_mode/_color themselves
                          don't change meaning, "normal ambient colour"
                          still covers both his non-dark ("default"/hybrid)
                          and "light" cases.
  global_transition_ms    the legacy ledfx_global_transition action
                          equivalent — a flat MANUAL override ramp new
                          scene-entry blends use when a scene doesn't
                          author its own entry_ramp_ms (SceneV2.
                          entry_ramp_ms == 0). Superseded as the DEFAULT
                          fallback by scene_transition_ms_gentle/_hard
                          below (2026-08-19) but still wins when he's
                          explicitly set it nonzero — see that pair's own
                          docstring for the full fallback chain.
  scene_transition_ms_    intensity-scaled scene-entry crossfade bounds
  gentle/_hard            (2026-08-19, his ask: two settings he named
                          "max scene transition time"/"min scene
                          transition time", 200ms and 300ms — scale
                          transition time by intensity, linearly). His
                          named numbers are INVERTED from what "max"/"min"
                          would suggest (200 < 300) — the physically
                          sensible reading, and the one this builds,
                          is low intensity gets the LONGER transition,
                          high intensity the SHORTER one. Named here by
                          what they represent instead of by his ambiguous
                          "max"/"min" labels (avoiding a field literally
                          named "max" holding the smaller number), matching
                          the SAME gentle/hard naming spectra/services/
                          scene_response.py already uses for every other
                          intensity-scaled ramp in this codebase
                          (COLOR_JUMP_RAMP_MS_GENTLE/_HARD,
                          UPDATE_RAMP_MS_GENTLE/_HARD — this is the fourth
                          instance of the same shape, not a new one):
                            scene_transition_ms_gentle  300ms @ intensity 0.0
                            scene_transition_ms_hard    200ms @ intensity 1.0
                          Both are plain settings (Sonic-editable via
                          settings_console.SETTINGS_REGISTRY, same as
                          global_transition_ms), swappable without a code
                          change either way he ultimately confirms.
                          scene_transition_ms() below is the shared linear
                          interpolation (same shape as scene_response.
                          _intensity_scaled_ramp_ms) — consulted by
                          scene_compiler.fire_scene as the new DEFAULT
                          fallback (global_transition_ms, when nonzero,
                          still wins — an explicit flat override he set in
                          the past keeps meaning exactly what it always
                          did) and, read-only, by trigger_engine's lead-time
                          peek so the predicted duration matches the one
                          the fire will actually use.
  scene_change_mode  the Admiral's binding settings model (decision-
                          mid-song-model.md + its 2026-08-14 framing
                          correction + the settings-model brief,
                          corr=c14a9bcee40e6df9), extended 2026-08-20
                          (data/spectra-my-triggers-only-mode) with a
                          fourth tier that is NOT part of the original
                          "+" ladder — see the MISLABEL FIX note below
                          before assuming the four values are a strict
                          cumulative ladder:
                            "transitions"   — a scene change on every song
                              transition only (the automatic kernel-picked
                              fire trigger_engine._fire_transition drives
                              on every genuine song-to-song change — see
                              its module docstring). Nothing else.
                            "analysed"      — transitions PLUS the analysed
                              mid-song moments midsong_generator seeds
                              (source="generated" triggers).
                            "triggers_only" — a PREFERENCE WITH A PER-SONG
                              FALLBACK, not an absolute (his 2026-08-20
                              correction below): on a song with at least
                              one stored "authored" trigger, ONLY his own
                              hand-authored triggers fire (fire_scene,
                              fire_response, select_color_set,
                              fire_scene_update) — transitions, generated
                              mid-song triggers, and response-engine
                              flares are all silenced for that song. On a
                              song with NO stored authored trigger, this
                              tier behaves exactly like "analysed" for
                              that song instead (transitions + generated
                              mid-song triggers fire; flares stay off,
                              same as "analysed" always has) — see the
                              PER-SONG FALLBACK entry below for why and
                              the exact rule.
                            "full"          — everything: transitions +
                              generated mid-song triggers + the owner's
                              own hand-authored triggers (source=
                              "authored") + response-engine flares (both
                              bridge-classified and trigger-driven —
                              services/engine.fire_response_event's own
                              gate). Default, and the closest match to
                              pre-existing behaviour (authored triggers and
                              flares had no gate at all before this field).
                          Checked by trigger_engine.tick() (generated vs.
                          authored gating), trigger_engine._fire_transition
                          (transitions gating), and engine.fire_response_event
                          /fire_scene_update_event (flare/update gating) —
                          the same seams the old bool switch used.
                          "transitions" and "analysed" are NOT redundant:
                          they differ in whether generated mid-song
                          triggers fire, exactly the old switch's two
                          states.

                          MISLABEL FIX (data/spectra-my-triggers-only-mode,
                          and the double-fire root cause proven
                          independently in data/charge-lull-drop-timing-
                          blends-and-a-sus-7fm2/report.md §1): "full" was
                          labelled "+ My triggers" in the room bar, read
                          by him as EXCLUSIVE ("only my triggers do
                          anything" — his words) when the code was
                          additive all along — the label and its own
                          tooltip contradicted each other on his screen.
                          "triggers_only" is the mode that actually
                          matches what he wanted; every remaining label
                          was reworded so none implies exclusivity it
                          doesn't have (RoomControlsBar.tsx: "Transitions
                          only" / "Transitions + analysed" / "My triggers
                          only" / "Everything").

                          PER-SONG FALLBACK, his own correction the same
                          day, verbatim: "if no triggers exist, use the
                          analyzed triggers" — a preference with a
                          fallback, not an absolute. Exact rule, stated so
                          it can't be misread: **"no triggers exist" means
                          zero triggers with source=="authored" currently
                          stored for the song's own URI** — checked fresh
                          from trigger_store on every tick/transition
                          (never cached), and independent of each
                          trigger's own `enabled` flag (a song with
                          authored triggers that are all currently
                          disabled still counts as "has authored
                          triggers" — matches how his own real-data count
                          below was taken, a raw storage scan, not a
                          live-gating simulation). PER-SONG, not
                          per-crossing/per-region within a song: a
                          region-level fallback would reintroduce the
                          exact doubling this mode exists to remove,
                          anywhere a generated and an authored trigger
                          landed close together within the same song.
                          His real data settled this rather than leaving
                          it a judgment call: of 853 songs with any
                          stored trigger record, only 313 (37%) have any
                          AUTHORED one — 540 (63%) have none, so the
                          fallback is the COMMON path, not an edge case,
                          and had to behave well rather than merely
                          exist. The sparse-song worry ("one trigger in
                          the first verse silences four minutes") is
                          real in shape but narrow in reach: of the 313
                          authored songs the median carries 29 authored
                          triggers, and only 4 songs in the entire
                          library have between 1 and 5 — his authored
                          songs are densely authored, so the "only his"
                          half of this tier rarely leaves a real gap.
                          Implemented in trigger_engine.py's
                          _effective_mode_for_song (tick()'s stored-
                          trigger gate) and _fire_transition's own check
                          (the automatic transition fire) — both resolve
                          the SAME per-song fallback independently since
                          they gate different mechanisms, not a shared
                          cached flag.

                          THE fire_response_event DUAL-PATH:
                          engine.fire_response_event has TWO callers that
                          share one signature with no source field: the S2
                          bridge's own classification of EVERY trigger_fired
                          broadcast on the shared /ws (which still includes
                          root spot-effects' original legacy trigger engine,
                          unconditionally broadcasting regardless of who
                          owns the lights — a SEPARATE, larger, un-fixed
                          defect, see that report's §1.2/§5 proposed fix #1,
                          out of scope here) and trigger_engine's own
                          fire_response action for a SPECTRA-native
                          authored trigger. "triggers_only" needs the
                          SECOND to fire and the FIRST to stay silent —
                          impossible to tell apart from event_class/
                          intensity alone, so fire_response_event grew an
                          explicit via_trigger=False default (the bridge's
                          existing call site, unchanged) vs. via_trigger=
                          True (trigger_engine's own call site): via_trigger
                          re-checks against ("full", "triggers_only");
                          the bridge path keeps requiring literally "full",
                          same as before this field existed. This also
                          means a bridge-relayed duplicate (the mechanism
                          the linked report proved causes his charge/lull/
                          drop marks to double-fire) is naturally excluded
                          under "triggers_only", without this field trying
                          to solve that larger, separate defect.
                          fire_scene_update_event has only ever had the one
                          (trigger-driven) caller, so its own gate simply
                          extended to ("full", "triggers_only") with no
                          via_trigger parameter needed.
  ambient_hue_group_ids   WHICH Hue entertainment areas Ambient reaches —
                          his own two-bridge room, "hue-lights" (10 bulbs)
                          vs. "dining-hues" (7), and he asked to choose
                          between them twice before this was built (the
                          hold, not a pending decision of his — our
                          failure). Ported from legacy's own per-group
                          picker (services/ambient_mode.py's
                          state.ambient_groups / resolve_groups /
                          set_groups, exposed via the long-press checkbox
                          picker on AmbientButton.tsx) rather than invented:
                          the unit of choice there was one Hue device id per
                          entertainment group/bridge — exactly what
                          services/ambient.py's live_host.live.host.devices
                          (type "hue") already enumerates one entry per, so
                          no new grouping concept was needed on this side.
                          `[]` (the default) means EVERY live Hue device —
                          today's unmodified behaviour, preserved on
                          purpose so deploying this changes nothing until
                          he picks a subset (legacy's own `want=None` ==
                          "all groups" semantics, ported as "empty list").
                          A non-empty list is the exact set of device ids
                          Ambient may hold; a group NOT in the list is never
                          frozen, never written to, and left running its
                          normal reactive show — the SPECTRA-side gap this
                          field closes (services/ambient.py's own docstring
                          used to say plainly "no device-category setting
                          to resolve a target from"). Unlike legacy, there
                          is no separate device-CATEGORY layer to pick a
                          target from first — SPECTRA has no LedFX device
                          categories, and every live Hue device already
                          picks itself as one candidate group, so this list
                          names devices directly. See services/ambient.py's
                          module docstring ("Hue entertainment-area
                          selection") for the reconcile-time mechanics
                          (holding a newly-selected group, releasing one
                          that falls out of scope while Ambient stays
                          engaged, and why an out-of-scope-but-never-frozen
                          device is left untouched rather than "released").
  force_scene_enabled/    the legacy Now Playing "Force Scene" control,
  force_scene_scene_id    ported verbatim (owner direction: reuse the old
                          system's design/behaviour, not reinvent it).
                          Legacy semantics (services/trigger_engine.py's
                          _forced_scene_event/_pick_scene_lanes): while
                          enabled, whenever a scene WOULD be picked
                          automatically, the forced scene fires instead - an
                          unconditional redirect, not a pause. Ported at the
                          single choke point every automatic SPECTRA scene
                          pick already funnels through, scene_sequencer.
                          fire_scene_by_id (sequencer rolls, trigger_engine's
                          fire_scene action, and its automatic transition
                          fire all call it) - one interception point, same
                          as legacy having one settings flag every pick site
                          checked. Only the SCENE is pinned; the caller's own
                          resolved colour set/intensity still applies, same
                          as legacy's "reassert with normal First/Rest."
                          force_scene_scene_id pointing at a missing scene is
                          treated as unset (silently falls through), same as
                          legacy's missing/non-scene event guard. SPECTRA has
                          no Scene Group concept yet, so the legacy group
                          member-rotation half of Force Scene has nothing to
                          port to - out of scope until groups exist. Editor
                          test-fires (POST /scenes/{id}/fire) bypass
                          fire_scene_by_id by design and are NOT redirected -
                          an explicit single fire is not "a scene being
                          picked."

Ambient is wired live (services/ambient.py) — the Dinner-Party half of the
room-MODES gap (gap report §3 row 5) is a separate, still-unbuilt mode;
ambient_mode/_color here are Ambient's alone.

Storage: storage/spectra/room_controls.json — same atomic tmp+replace
discipline as color_journey.py's room_color.json.

FORCE SCENE IS PASSIVE BY CONSTRUCTION — IT MUST ALSO ACT (fixed
2026-08-18, his live report: "I'm trying to test black hole in light
mode... using [Force Scene] to do it and nothing is happening... there's
a song playing with no Triggers on it"). `fire_scene_by_id`'s redirect
only fires when SOMETHING ELSE was already about to pick a scene — and
enabling Force Scene also sets `bridge.sequencer_deferral()` to
"force_scene", stopping the sequencer's own rolls. On a song with no
triggers and no analysis, nothing was ever going to fire, so the redirect
never got a chance to run: the control looked dead, but the mechanism was
working exactly as ported — it was just never given an occasion to act.
`reconcile_force_scene_if_changed` below closes that gap the same way
`reconcile_ambient_if_changed`/`reconcile_dark_light_if_changed` already
do for their own controls: called from the PUT /api/room-controls handler
after the new state is saved, it fires the pinned scene IMMEDIATELY the
instant enabling the pin (or repinning a different scene while already
enabled) is the edit that changed — never on an unrelated field re-save
while an already-enabled pin stays put. A refusal (nothing pinned, or the
pinned id doesn't resolve to a real scene) is returned as a stated reason,
never a silent no-op — the silence is what read as broken in the first
place.

FORCE SCENE OVERRIDING A DISABLED SCENE IS NAMED, NOT SILENT (owner ask
2026-08-18, temporary scene disable — SceneV2.disabled). Pinning a scene
he's marked disabled is contradictory input from him in the moment — the
pin still wins (he pressed it, he means it, same as Force Scene already
overrides display_availability), but `fire_scene_by_id` marks the result
`overrode_disabled=True` and this function forwards it as
`force_scene_result.overrode_disabled` so the badge can say so, rather
than either silently refusing the pin or silently pretending the scene
was never disabled.

FORCE SCENE OVERRIDING AN ACTIVE MINIMUM DWELL IS NAMED, NOT SILENT (owner
ask 2026-08-20, spectra/services/dwell.py) — the identical pattern one
paragraph up: a pin lands even while the active scene hasn't cleared its
own minimum hold yet, and `fire_scene_by_id` marks the result
`overrode_dwell=True`, forwarded here as `force_scene_result.overrode_dwell`.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import typing
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from spectra import config

SceneChangeMode = Literal["transitions", "analysed", "triggers_only", "full"]
AmbientMode = Literal["off", "always", "auto"]
DisplayMode = Literal["default", "dark", "light"]

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class RoomControlState(BaseModel):
    # "default" is his word "hybrid" — defer to whatever the scene authors
    # (legacy's own Default semantics; labelled "Hybrid" in the UI, kept
    # "default" internally per his standing ruling). See the module
    # docstring's "THREE-STATE REBUILD" note for the load-bearing migration
    # off the old dark_mode_enabled bool.
    display_mode: DisplayMode = "default"
    # Legacy's configurable forced Light background (services.trigger_engine
    # settings.display_light_bg_color/_brightness) — defaults ported
    # verbatim. See dark_light.py's docstring for the write mechanism.
    display_light_bg_color: str = "#201830"
    display_light_bg_brightness: float = Field(default=0.3, ge=0.0, le=1.0)
    # Category/virtual exemptions — legacy's default shielded category
    # (config.py's display_shield_categories) is ["Singles"]; matched here
    # for exact fidelity, not re-guessed. Applies to BOTH Dark and Light —
    # a shielded device keeps its own authored background in either mode,
    # exactly as legacy.
    dark_light_shield_categories: list[str] = Field(default_factory=lambda: ["Singles"])
    dark_light_shield_virtuals: list[str] = Field(default_factory=list)
    brightness_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    ambient_mode: AmbientMode = "off"
    ambient_color: Optional[str] = None   # hex; None = no colour authored yet
    # Second colour, for dark mode (see the module docstring's ambient_color_dark
    # entry). None = defer to ambient_color, not a frozen copy of it.
    ambient_color_dark: Optional[str] = None
    # [] = every live Hue device (today's unmodified default — see the
    # ambient_hue_group_ids docstring entry above). A non-empty list names
    # exactly which Hue entertainment areas (device ids from
    # live_host.live.host.devices) Ambient may hold.
    ambient_hue_group_ids: list[str] = Field(default_factory=list)
    # 0 = no room default (today's unchanged instant-jump behaviour for any
    # scene that doesn't author its own entry_ramp_ms). >0 becomes the
    # FALLBACK ramp scene_compiler.fire_scene uses when a scene's own
    # entry_ramp_ms is 0 — the legacy ledfx_global_transition equivalent.
    global_transition_ms: int = Field(default=0, ge=0, le=20000)
    # intensity 0.0 / 1.0 crossfade bounds — see the module docstring's
    # "scene_transition_ms_gentle/_hard" entry for the naming/inversion
    # reasoning behind his 200ms/300ms.
    scene_transition_ms_gentle: int = Field(default=300, ge=0, le=20000)
    scene_transition_ms_hard: int = Field(default=200, ge=0, le=20000)
    scene_change_mode: SceneChangeMode = "full"
    force_scene_enabled: bool = False
    force_scene_scene_id: Optional[str] = None   # id of the scene held while enabled

    # Rainbow select (spectra/services/rainbow_select.py, owner ask
    # 2026-08-20): above this intensity, colour-set selection is restricted
    # to rainbow-marked cards only; at or below it, to single (non-rainbow)
    # cards only. His words: "Default it to .9."
    rainbow_select_limit: float = Field(default=0.9, ge=0.0, le=1.0)

    # The two-dimensional drift gradient (spectra/services/drift_conductor.py
    # _gradient_leg, spectra/models/gradient2d.py — owner ask 2026-08-20):
    # None (default) = off, the wheel-based colour journey drives the room's
    # colour exactly as before this feature. A gradient id here PAUSES the
    # journey (same "an alternate colour source takes over, the walk holds"
    # shape as a live rainbow palette) and drives set-mode virtuals' colour
    # from the gradient instead. gradient_x_period_s/_y_slew_s are state-only
    # tunables, not something he asked to configure per-gradient — kept here
    # (agent-tellable) rather than hardcoded so the pace can be retuned
    # without a redeploy.
    active_gradient_id: Optional[str] = None
    gradient_x_period_s: float = Field(default=300.0, gt=0.0)
    gradient_y_slew_s: float = Field(default=45.0, gt=0.0)

    @field_validator("ambient_color", "ambient_color_dark", "display_light_bg_color")
    @classmethod
    def _validate_hex(cls, v: Optional[str]) -> Optional[str]:
        # Tightened for the settings-console agent (spectra/services/
        # settings_console.py): the field was previously an unvalidated
        # str, so ANY text round-tripped through the human colour-picker
        # path too. Real colour pickers only ever emit #rrggbb, so this
        # is not a behaviour change for the UI — it closes the gap for a
        # write path with no picker to constrain it.
        if v is not None and not _HEX_COLOR_RE.match(v):
            raise ValueError("must be a #rrggbb hex colour")
        return v


def field_bounds(name: str) -> tuple[Optional[float], Optional[float]]:
    """(ge, le) declared on a RoomControlState field, or (None, None) if the
    field carries no numeric bound (bool/enum/str fields). Single source of
    truth for the settings-console registry — it reads the SAME Field(ge=,
    le=) constraints this model enforces, so a range can't drift between
    what a human PUT accepts and what the agent is told is legal."""
    ge = le = None
    for constraint in RoomControlState.model_fields[name].metadata:
        if hasattr(constraint, "ge"):
            ge = constraint.ge
        if hasattr(constraint, "le"):
            le = constraint.le
    return ge, le


def field_choices(name: str) -> Optional[list[str]]:
    """Literal[...] choices declared on a RoomControlState field, or None."""
    args = typing.get_args(RoomControlState.model_fields[name].annotation)
    return list(args) if args and all(isinstance(a, str) for a in args) else None


def effective_ambient_color(state: RoomControlState) -> Optional[str]:
    """The colour Ambient should actually be holding right now — the one
    seam every ambient write/verify path (services/ambient_music_gate.py)
    must resolve through, rather than reading ambient_color directly.
    ambient_color_dark wins while display_mode == "dark" AND he's authored
    one; otherwise the normal/hybrid colour applies, same as before this
    field existed. Because ambient_color_dark defaults to None rather than a
    migration-time copy, this also correctly reports "nothing changed" for
    a display_mode flip into/out of "dark" before he's ever picked a dark
    colour — the two are identical by construction until he diverges them."""
    if state.display_mode == "dark" and state.ambient_color_dark is not None:
        return state.ambient_color_dark
    return state.ambient_color


def scene_transition_ms(state: RoomControlState, intensity: float) -> int:
    """Linear interpolation between the gentle (intensity 0.0) and hard
    (intensity 1.0) crossfade bounds — same shape as scene_response.
    _intensity_scaled_ramp_ms, duplicated rather than imported to avoid a
    room_controls -> scene_response import (scene_response already reaches
    into room-level state indirectly via the engine singleton; this module
    stays a leaf). Clamped so an out-of-[0,1] intensity (shouldn't happen —
    SpectraTrigger.action.intensity is itself bounded — but a caller
    computing render_intensity could theoretically drift) never
    extrapolates past either bound."""
    frac = max(0.0, min(1.0, intensity))
    return int(round(state.scene_transition_ms_gentle
                     + (state.scene_transition_ms_hard
                        - state.scene_transition_ms_gentle) * frac))


def resolve_authored_bg_color(bg_color: str, display_mode: str,
                              light_bg_color: str) -> str:
    """A scene/colour-set entry's authored background is DATA, not the
    room's own Light background — but Light paints its forced background
    ONCE (dark_light.py's reconcile write) and never re-asserts it, while
    every later scene fire re-writes its own colour-set background on top.
    30 entries across 22 of his colour sets author literal #000000, which
    in overwrite mode clears whatever Light just painted, and it never
    comes back (his report: effects "start with a background color
    appropriately and then go dark"). His ruling (option three): in
    "light" mode only, an authored #000000 becomes the room's own Light
    colour instead of literal black. "default"/"dark": unchanged — an
    authored black keeps clearing a virtual's background exactly as it
    always has (the same black is what stops a PRIOR write's colour from
    bleeding into the next fire — see AGENTS.md's "An authored black
    bg_color on a colour set is LOAD-BEARING in Hybrid mode" entry).

    A pure function, deliberately — every caller resolves display_mode/
    light_bg_color itself (fire_scene, ResponseEngine._room_controls(),
    DriftConductor._room_controls()) and passes plain values in here.
    This module MUST stay a leaf its callers can import at any scope
    (see this module's own "room_controls -> scene_response" note above)
    — the 2026-08-20 light-mode-fix crash (AGENTS.md) was two independent
    constructors each binding a `room_controls` name of their own that
    then shadowed the OTHER meaning of the same name; the fix there is to
    never touch this module eagerly, not anything about this function."""
    if display_mode == "light" and bg_color == "#000000":
        return light_bg_color
    return bg_color


def apply_brightness(params: dict, multiplier: float) -> dict:
    """Scale brightness/background_brightness IN a params dict by the room
    multiplier, if present — the uniform write-seam scaling. Never mutates
    the input; returns it unchanged (same object) when neither key is
    present or the multiplier is a no-op (1.0), so callers can skip a copy
    on the common case."""
    if multiplier == 1.0:
        return params
    out = None
    for key in ("brightness", "background_brightness"):
        if key in params and isinstance(params[key], (int, float)):
            if out is None:
                out = dict(params)
            out[key] = max(0.0, min(1.0, params[key] * multiplier))
    return out if out is not None else params


def load_room_controls() -> RoomControlState:
    path = config.ROOM_CONTROLS_FILE
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return RoomControlState()
        # One-way migration from the retired midsong_triggers_enabled bool
        # (pre this settings model) — True mapped to "full" (the closest
        # match to its actual pre-existing behaviour: generated triggers on,
        # and authored triggers/flares always fired regardless of the old
        # switch), False to "transitions" (the owner had deliberately dialed
        # generated triggers off, so the pure baseline is the most faithful
        # read of that intent).
        if "scene_change_mode" not in raw and "midsong_triggers_enabled" in raw:
            raw["scene_change_mode"] = ("full" if raw.pop("midsong_triggers_enabled")
                                        else "transitions")
        else:
            raw.pop("midsong_triggers_enabled", None)
        # One-way migration from the pre-2026-08-15 ambient_enabled bool
        # (§52's own field, PR #73, never merged to master under this name)
        # to the three-setting ambient_mode — True mapped to "auto" (the
        # closest match: that's exactly what True was BUILT and PROVEN to
        # mean throughout §52's lifetime, the music-precedence gate), False
        # to "off" (unchanged meaning either way).
        if "ambient_mode" not in raw and "ambient_enabled" in raw:
            raw["ambient_mode"] = "auto" if raw.pop("ambient_enabled") else "off"
        else:
            raw.pop("ambient_enabled", None)
        # One-way migration from the retired dark_mode_enabled bool (the
        # original two-state build) to the three-state display_mode — LOAD
        # BEARING, see the module docstring's "THREE-STATE REBUILD" note.
        # true -> "dark" (unchanged meaning). false -> "default", NEVER
        # "light": the old field was named "light" but behaved as legacy's
        # Default (nothing forced), so false->default is what preserves his
        # room's current behaviour exactly. Mapping false->light would
        # silently turn on a forced background nobody asked for.
        if "display_mode" not in raw and "dark_mode_enabled" in raw:
            raw["display_mode"] = "dark" if raw.pop("dark_mode_enabled") else "default"
        else:
            raw.pop("dark_mode_enabled", None)
        try:
            return RoomControlState(**raw)
        except Exception:
            return RoomControlState()
    return RoomControlState()


def save_room_controls(state: RoomControlState) -> None:
    path = config.ROOM_CONTROLS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(json.loads(state.model_dump_json()), fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


async def reconcile_ambient_if_changed(previous: RoomControlState,
                                       new_state: RoomControlState) -> Optional[dict]:
    """The ambient-takeover half of a room-controls save, factored out so
    both the human PUT /api/room-controls handler (spectra/api/
    room_controls.py) and the settings-console agent's apply path
    (spectra/services/settings_console.py) drive the SAME reconcile on the
    SAME condition — one write choke point, so the agent can never diverge
    from what a human save does. Returns the ambient_result dict when the
    ambient fields actually changed, else None (no reconnect churn on an
    unrelated field's change).

    Routes through services.ambient_music_gate rather than calling
    services.ambient directly — "auto" must NOT freeze the room's Hue
    devices while music is playing (the music-precedence rule, see
    ambient_music_gate's module docstring); this is the manual-toggle path
    that rule has to cover too, not just the automatic one. "always" is
    unconditional by design (mode 2) — the gate still owns the actual
    write, this is just the "did anything change" gate for whether to
    bother calling it at all.

    Compares effective_ambient_color (above), not the bare ambient_color
    field, so this one condition also covers: an ambient_color_dark edit
    while dark mode is on, and dark_mode_enabled itself flipping while
    ambient is holding — both change what's ACTUALLY held even though
    ambient_mode/ambient_color themselves didn't move. Editing the field
    that ISN'T currently in effect (e.g. the normal colour while dark mode
    is on and a dark colour is already authored) correctly reports no
    change — nothing live needs to move for that edit. Since 2026-08-16,
    brightness is DERIVED from this same resolved hex (services.ambient's
    `_hsv_value_pct` — see the class docstring's ambient_brightness_note
    entry), so a same-hue-different-lightness edit (e.g. his cream to a
    darker cream) is ALSO a resolved-colour change and correctly reaches
    this same condition — no separate brightness comparison needed.

    Also fires on an ambient_hue_group_ids edit while ambient isn't "off" —
    picking a different Hue area (or adding/dropping one) while Ambient is
    already engaged must reconcile immediately (release the deselected
    group, hold the newly-selected one), not wait for a colour/mode edit
    that happens to touch this same PUT. Compared as sets so a reordered
    (but otherwise identical) list doesn't trigger a no-op reconcile."""
    changed = (
        previous.ambient_mode != new_state.ambient_mode
        or (new_state.ambient_mode != "off" and (
            effective_ambient_color(previous) != effective_ambient_color(new_state)
            or set(previous.ambient_hue_group_ids) != set(new_state.ambient_hue_group_ids)
        ))
    )
    if not changed:
        return None
    from spectra.services import ambient_music_gate
    return await ambient_music_gate.reconcile_now()


async def reconcile_dark_light_if_changed(previous: RoomControlState,
                                          new_state: RoomControlState) -> Optional[dict]:
    """The dark_lock/light-bg-sync half of a room-controls save — same
    one-choke-point shape as reconcile_ambient_if_changed above, so a human
    PUT and the settings-console agent's apply path can never diverge. Also
    re-reconciles on a shield-list edit while already dark OR light (mirrors
    legacy's services/display_mode.resync(), called when display_shield_*
    settings change) — a newly (un)shielded virtual should react
    immediately, not wait for the next full toggle. A light-bg colour/
    brightness edit while already in "light" is likewise a live-effecting
    change (Light is a forced, unconditional write — the whole point is
    that it's watchable the instant it's edited, not just on entry).
    Returns None (no live effect, nothing to report) when nothing here
    changed."""
    changed = (
        previous.display_mode != new_state.display_mode
        or (new_state.display_mode in ("dark", "light") and (
            previous.dark_light_shield_categories != new_state.dark_light_shield_categories
            or previous.dark_light_shield_virtuals != new_state.dark_light_shield_virtuals))
        or (new_state.display_mode == "light" and (
            previous.display_light_bg_color != new_state.display_light_bg_color
            or previous.display_light_bg_brightness != new_state.display_light_bg_brightness))
    )
    if not changed:
        return None
    from spectra.services import dark_light
    return await dark_light.reconcile(new_state.display_mode,
                                      new_state.dark_light_shield_categories,
                                      new_state.dark_light_shield_virtuals,
                                      new_state.display_light_bg_color,
                                      new_state.display_light_bg_brightness)


async def reconcile_force_scene_if_changed(previous: RoomControlState,
                                            new_state: RoomControlState) -> Optional[dict]:
    """Force Scene's ACTIVE half of a room-controls save — same
    one-choke-point PUT-triggered shape as reconcile_ambient_if_changed/
    reconcile_dark_light_if_changed above. See the module docstring's
    "FORCE SCENE IS PASSIVE BY CONSTRUCTION" entry for why this exists:
    fire_scene_by_id's redirect only fires on a pick something else was
    already about to make, and enabling the pin also defers the
    sequencer — so a song with no triggers never gave the redirect an
    occasion to run. This fires the pinned scene directly, right here,
    the instant the pin's OWN edit is what changed.

    Fires only on: force_scene_enabled flipping False -> True, or
    force_scene_scene_id changing while already enabled. Re-saving an
    unrelated field while an already-enabled, unchanged pin stays put
    must NOT re-fire — same "only on an actual edit" discipline as the
    other two reconciles, and the same reason a scene shouldn't jump
    every time he nudges the brightness slider.

    Always returns a dict naming what happened — fired, or skipped/error
    with a stated reason — never None-on-refusal the way "nothing to
    reconcile" is signalled elsewhere, because a Force Scene edit is
    always an explicit act that deserves a visible outcome; None here
    means only "this edit wasn't a pin change at all."""
    became_enabled = new_state.force_scene_enabled and not previous.force_scene_enabled
    repinned_while_enabled = (
        new_state.force_scene_enabled and previous.force_scene_enabled
        and new_state.force_scene_scene_id != previous.force_scene_scene_id
    )
    if not (became_enabled or repinned_while_enabled):
        return None
    if not new_state.force_scene_scene_id:
        return {"status": "skipped", "reason": "no scene pinned"}
    from spectra.services import scene_store
    scene = scene_store.get_by_id(new_state.force_scene_scene_id)
    if scene is None:
        return {"status": "skipped", "reason": "pinned scene not found"}
    from spectra.services.engine import bridge
    from spectra.services.scene_sequencer import fire_scene_by_id
    intensity = bridge.intensity()
    if intensity is None:
        intensity = 0.5
    try:
        fire_result = await fire_scene_by_id(new_state.force_scene_scene_id,
                                             intensity=intensity)
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}
    if fire_result.get("skipped"):
        return {"status": "skipped", "reason": fire_result["skipped"],
                "scene_id": new_state.force_scene_scene_id,
                "scene_name": fire_result.get("scene_name")}
    result = {"status": "fired", "scene_id": new_state.force_scene_scene_id,
              "scene_name": scene.name}
    if fire_result.get("overrode_disabled"):
        # The pin landed on a scene marked SceneV2.disabled — contradictory
        # input from him (he disabled it, then pinned it anyway), so the
        # pin is honoured (he pressed it, he means it) but the override is
        # NAMED rather than silently applied, same "always state a reason"
        # discipline as the skipped/error branches above.
        result["overrode_disabled"] = True
    if fire_result.get("overrode_dwell"):
        # Same pattern, dwell's own gate (spectra/services/dwell.py,
        # 2026-08-20): the currently-active scene hadn't cleared its own
        # minimum hold yet, but the pin fires anyway — named, not silent.
        result["overrode_dwell"] = True
    return result
