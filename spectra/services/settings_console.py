"""The settings-console MECHANISM (standing order 5: "talk to the software;
do not build the Admiral a settings page"). This module is the whole
authority boundary — it has no import of, or dependency on, any LLM/agent
code (see settings_agent.py for that), so the boundary is provable by
reading this file alone: the only write path is apply_change(), it accepts
exactly one (key, value) pair, and every key/value is validated against
declared, server-owned data BEFORE anything is persisted. There is no
shell, file, HTTP, or service-control primitive reachable from here.

SCOPE (first build): the RoomControlState fields (spectra/services/
room_controls.py) already labelled "agent-tellable room-wide switches" in
that module's own docstring — brightness, ambient mode/colour, the
global transition default, and the scene-change tier. Widened 2026-09-23
with the PLACEMENT RULE R3 knobs (transition_window_beats/_edge_
sensitivity/transitions_per_minute — see room_controls.py's own
docstring on those fields and AGENTS.md's PLACEMENT RULE R3 section), and
again 2026-10-06 (the Sonic coverage audit/build) with
midsong_snap_to_beat, display_mode, rainbow_select_limit, and the drop
detector's own drop_confident_score/drop_suggested_score. Widened again
2026-10-06 with the drop detector's own drop_floor (the Admiral's own
ask for a quiet-song energy gate).
Widened again 2026-10-07 with lull_dark_max_s (the Admiral's own "make
this something sonic can change": the longest a lull stays fully dark).
Widened again 2026-10-11 with background_fade_s (the Admiral's own
background fade: how long a live background change takes to land).
Widened again 2026-10-12 with drop_timing_offset_ms (the Admiral's own
"shifting the drops so they fire 400ms earlier" — spectra/services/
drop_timing.py).

force_scene_scene_id/force_color_target_id STAY OUT OF THIS REGISTRY —
each targets a scene or colour SET/GROUP by OPAQUE ID, a poor fit for
"set this setting to this value" (a picker action, not a scalar). What
CHANGED 2026-10-06 (his own ruling, "allow some flexibility in phrasing
... it should be a close match"): set_force_scene/set_force_color/
get_force_pins below are their own small ops, NOT registry keys — they
resolve a scene/colour-set NAME to its id through name_resolve.py (exact,
then a dropped qualifier like "V2", then a fuzzy match with no near-tie —
see that module's own docstring) and then write through room_controls.
apply_patch exactly as a room-controls PUT would, so the same
force-scene/force-color reconcilers run. This is the deliberate,
one-off extension the 2026-08-27 exclusion above always said this field
was waiting for — it did not need an opaque id once a name could be
resolved safely.

REGISTRY = the declared data. Bounds/choices are NOT re-typed here — they
are read live off RoomControlState's own pydantic Field(ge=, le=)
constraints and Literal[...] annotation (room_controls.field_bounds/
field_choices), so the registry can never state a looser range than the
model that actually enforces it.

apply_change() is the ONLY function that writes: it re-validates the
FULL candidate RoomControlState (current state with one field replaced)
through RoomControlState.model_validate — the exact model class GET/PUT
/api/room-controls binds to — then calls room_controls.save_room_controls
+ reconcile_ambient_if_changed, the same two calls the human PUT handler
makes. A rejected change never reaches save_room_controls.

Change log + undo: storage/spectra/settings_log.json, atomic tmp+replace,
bounded (SETTINGS_LOG_MAX_ENTRIES, oldest evicted first) — the "visible
record of what changed" + one-step-undo answer to mis-transcription risk
(voice dictation mangles his product names regularly — captain-shared.md).
undo_last_change() re-applies the previous value through apply_change()
itself, so an undo is validated exactly like any other change, never a
raw file poke.

OPERATIONS (bottom of file) is this module's contribution to Sonic's
merged, cross-domain allowlist — settings_agent.py combines it with
scene_console.OPERATIONS into ALL_OPERATIONS; see sonic_ops.py's docstring
for why the same declaration enforces AND documents. Sonic's scene/flare
authority (scene_console.py) is a SEPARATE module with zero import of this
one — settings stay settings, scenes stay scenes.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, ValidationError

from spectra import config
from spectra.services import name_resolve, room_controls
from spectra.services.room_controls import RoomControlState
from spectra.services.sonic_ops import SonicOperation

SETTINGS_LOG_MAX_ENTRIES = 200


class SettingSpec(BaseModel):
    key: str
    label: str
    kind: Literal["float", "int", "bool", "enum", "color"]
    description: str
    unit: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[list[str]] = None


class SettingChangeError(Exception):
    """Carries a structured, tool-result-shaped payload — this IS what a
    rejected agent tool call sees, not a generic error string, so the model
    (and a human reading the change log) can see the legal range/choices
    and the nearest legal value rather than just "no"."""

    def __init__(self, message: str, **detail: Any):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def payload(self) -> dict:
        return {"status": "rejected", "reason": self.message, **self.detail}


def _spec(key: str, label: str, description: str) -> SettingSpec:
    ge, le = room_controls.field_bounds(key)
    choices = room_controls.field_choices(key)
    annotation = RoomControlState.model_fields[key].annotation
    if choices:
        kind = "enum"
    elif annotation is bool:
        kind = "bool"
    elif key == "ambient_color":
        kind = "color"
    elif annotation is int:
        kind = "int"
    else:
        kind = "float"
    unit = {"brightness_multiplier": "fraction 0.0-1.0",
            "global_transition_ms": "ms",
            "scene_transition_ms_gentle": "ms",
            "scene_transition_ms_hard": "ms",
            "transition_window_beats": "beats",
            "transition_edge_sensitivity": "fraction of local median step",
            "transitions_per_minute": "per minute of song",
            "scene_changes_per_minute": "per minute of song, 0 = off",
            "rainbow_select_limit": "fraction 0.0-1.0",
            "drop_confident_score": "detector score",
            "drop_suggested_score": "detector score",
            "drop_floor": "top-bar displayed energy, fraction 0.0-1.0",
            "lull_dark_max_s": "seconds",
            "strip_phase_strength": "multiplier 0.0-1.5, 0 = off",
            "background_fade_s": "seconds, 0 = instant",
            "lull_breath_hold_s": "seconds",
            "drop_timing_offset_ms": "ms, negative = earlier, 0 = on the mark",
            "drop_shock_min_energy": "top-bar displayed energy, fraction 0.0-1.0",
            "pulse_flash_min_energy": "top-bar displayed energy, fraction 0.0-1.0",
            "drop_colour_spread_deg": "degrees either side of 180",
            "drop_switch_stale_margin_s": "seconds beyond the scene's own dwell",
            "drop_switch_drops_in_a_row": "drops, 0 = off",
            "drop_switch_swallow_delay_s": "seconds after the drop",
            "drop_switch_hit_threshold": "analysed flare intensity, 0.0-1.0",
            "transition_program_ms": "ms",
            "transition_velocity_blend_ms": "ms",
            "transition_infall_spin": "extra turns",
            "transition_eruption_count": "pieces",
            "transition_eruption_speed": "multiplier",
            "transition_explode_frac": "fraction 0.0-1.0",
            "transition_lensing_pull": "multiplier",
            "transition_ignition_turns": "turns",
            "transition_scatter": "multiplier",
            "transition_bands_pieces": "pieces",
            "transition_bands_hold_ms": "ms",
            "transition_unwind": "px/s^2",
            "transition_burst_px": "px",
            "transition_burst_ms": "ms",
            "transition_land_at": "fraction of the program, 0.1-0.9",
            "transition_graft_ms": "ms",
            "transition_count_hold_ms": "ms"}.get(key)
    return SettingSpec(key=key, label=label, kind=kind, description=description,
                       unit=unit, min=ge, max=le, choices=choices)


# The explicit allowlist — the ONLY keys apply_change will ever accept,
# independent of what RoomControlState happens to declare. Adding a field
# to RoomControlState does NOT expose it to the agent; it has to be added
# here deliberately.
SETTINGS_REGISTRY: dict[str, SettingSpec] = {
    "brightness_multiplier": _spec(
        "brightness_multiplier", "Brightness",
        "Uniform room brightness multiplier, as a fraction from 0.0 (dark) "
        "to 1.0 (full) — convert a spoken percentage yourself (50% -> 0.5)."),
    "global_transition_ms": _spec(
        "global_transition_ms", "Transition (manual override)",
        "A FLAT scene-entry blend time in milliseconds that overrides the "
        "intensity-scaled default below when set above 0 — used when a "
        "scene doesn't author its own entry ramp. Leave at 0 to let "
        "scene_transition_ms_gentle/_hard scale it by intensity instead. "
        "Convert spoken seconds to ms (2s -> 2000)."),
    "scene_transition_ms_gentle": _spec(
        "scene_transition_ms_gentle", "Transition at low intensity",
        "Scene-entry crossfade time in milliseconds used at intensity 0.0 "
        "(the gentle end) — the DEFAULT fallback when a scene has no "
        "entry ramp of its own and global_transition_ms is 0. Linearly "
        "scaled toward scene_transition_ms_hard as intensity rises toward "
        "1.0. Convert spoken seconds to ms."),
    "scene_transition_ms_hard": _spec(
        "scene_transition_ms_hard", "Transition at high intensity",
        "Scene-entry crossfade time in milliseconds used at intensity 1.0 "
        "(the hard end) — see scene_transition_ms_gentle. Convert spoken "
        "seconds to ms."),
    "ambient_enabled": _spec(
        "ambient_enabled", "Ambient",
        "THE Ambient toggle, on or off — on holds the room's live Hue "
        "devices lit at ambient_color, music playing or not, while every "
        "other device keeps running the show. Turning it on or off starts "
        "a transition that takes several seconds; changing your mind "
        "mid-transition is allowed and snaps the room straight to the new "
        "state."),
    "ambient_on_music_pause": _spec(
        "ambient_on_music_pause", "Ambient when music pauses",
        "Off by default. When on, and the Ambient toggle itself is OFF, "
        "Ambient turns itself on whenever the music is confirmed stopped "
        "and releases again the instant it starts — the old 'auto-return' "
        "behaviour, now its own separate switch."),
    "ambient_color": _spec(
        "ambient_color", "Ambient colour",
        "The ambient-mode hex colour, #rrggbb — translate a named colour "
        "('warm white', 'teal') to its nearest hex yourself."),
    "scene_change_mode": _spec(
        "scene_change_mode", "Scene changes",
        "What drives automatic scene changes: 'transitions' (song "
        "transitions only), 'analysed' (+ analysed mid-song moments), "
        "'triggers_only' (his own hand-authored triggers ONLY, on any "
        "song he's placed one on; a song with none falls back to "
        "'analysed' for that song), 'full' (+ hand-authored triggers "
        "and response flares, on every song)."),
    "transition_window_beats": _spec(
        "transition_window_beats", "Transition edge window",
        "How many beats a generated mid-song cue may move to reach a "
        "rhythmic bass-energy edge before falling back to a plain "
        "downbeat snap. Bigger reaches further; convert a spoken "
        "'beats' number directly (no unit conversion needed)."),
    "transition_edge_sensitivity": _spec(
        "transition_edge_sensitivity", "Transition edge sensitivity",
        "How big a bass-energy jump has to be, as a fraction of the "
        "local median step, before a generated cue treats it as an edge "
        "to move onto. Lower catches smaller jumps; higher only the "
        "biggest ones."),
    "transitions_per_minute": _spec(
        "transitions_per_minute", "Total actions per minute",
        "TOTAL ACTIONS PER MINUTE (called 'Transitions per minute' until "
        "2026-10-04 — same setting, same value): how many of a song's "
        "analysed moments per minute the room plans an action for, "
        "strongest first. Each planned moment changes the scene, or — while "
        "the current scene is still inside its minimum hold — fires a "
        "flare. The per-song total is this rate times the song's own "
        "length, scaled by that song's intensity-scale factor (automatic "
        "up to 125%, or a manual mark up to 200%). Analysed moments past "
        "that budget fire as analysed flares. A change re-plans each song "
        "the next time it plays; ask for 'refresh analysed triggers' to "
        "re-plan every song at once."),
    "scene_changes_per_minute": _spec(
        "scene_changes_per_minute", "Scene changes per minute (ceiling)",
        "An optional CEILING on how many of the analysed actions become real "
        "scene changes, per minute of song (scaled by the song's "
        "intensity-scale factor like the total). 0 = off, the default: the "
        "strongest moments become scene changes wherever the minimum scene "
        "hold lets them (about 3 a minute). Set above 0 to have fewer; it "
        "can never add more than the hold allows — for more, the dwell "
        "curve is the dial. Every other action fires as a flare. Reaches a "
        "song the next time it plays."),
    "midsong_snap_to_beat": _spec(
        "midsong_snap_to_beat", "Snap generated cues to beat",
        "Whether a generated mid-song cue (not a hand-authored trigger) "
        "snaps to a rhythmic bass-energy edge or a plain downbeat, "
        "instead of landing on the analysis's raw moment. On by default."),
    "display_mode": _spec(
        "display_mode", "Display mode",
        "The room's global look: 'default' (hybrid — nothing forced), "
        "'dark' (clamps every effect's brightness low), 'light' (forces "
        "a configured background colour on). Shielded categories are "
        "unaffected either way."),
    "rainbow_select_limit": _spec(
        "rainbow_select_limit", "Rainbow colour-set limit",
        "Above this intensity, automatic colour-set selection is "
        "restricted to colour sets marked 'rainbow'; at or below it, to "
        "ordinary single-palette sets. 0.9 is his default — convert a "
        "spoken percentage yourself (90% -> 0.9)."),
    "drop_confident_score": _spec(
        "drop_confident_score", "Drop detection — confident threshold",
        "The detector score at or above which a detected drop sequence "
        "is marked confident rather than merely suggested. Raising it "
        "makes fewer drops read as confident."),
    "drop_suggested_score": _spec(
        "drop_suggested_score", "Drop detection — suggested threshold",
        "The detector score at or above which a drop sequence is "
        "offered at all (below confident). Below this score nothing is "
        "reported for that moment."),
    "drop_floor": _spec(
        "drop_floor", "Drop detection — energy floor",
        "A drop sequence is only generated where the music during or "
        "right after the drop reaches at least this value on the same "
        "0.0-1.0 energy number the top bar's '⚡ Energy' readout shows "
        "(the Mark readout next to it is a separate number and is not "
        "factored in) — so quiet songs or sections don't get drops. "
        "Never removes a drop he has already confirmed, edited or added "
        "himself. Default 0.7."),
    "lull_dark_max_s": _spec(
        "lull_dark_max_s", "Lull darkness (max)",
        "The longest a lull stays fully dark, in seconds, on the lull "
        "effects that go dark (Black Hole, Squiggles, Pulse, Star). A "
        "lull holds dark for half its length, never longer than this — "
        "the rest is its build-up (the black hole's event horizon "
        "expanding, Squiggles' screen squashing, Pulse fading, Star's "
        "bands falling into the core). So at the default 3 "
        "a 20-second lull is 17 seconds of build-up and 3 of dark, and a "
        "4-second lull is still 2 and 2. 0 = the lull only goes dark on "
        "its drop. Takes effect on the very next lull. Convert spoken "
        "minutes to seconds yourself."),
    "strip_phase_strength": _spec(
        "strip_phase_strength", "Strip phase strength",
        "How strongly the strip effects (Melt, Power, and the Black Hole, "
        "Orbits and Fireworks strips) answer a charge, lull and drop: on a "
        "charge their colours get brighter, a fill in the set's colours "
        "rises under them and there's more going on (more blobs, more "
        "fireworks, a faster melt); a lull fades them to black at the same "
        "dark point as the crystal (the Fireworks strip keeps a faint "
        "ember, the Orbits strip one dim blob); a drop sends a shockwave in "
        "the set's colours from the middle (it obeys the drop Shockwave's "
        "switches too). Never adds white. 1 = as tuned (default), 0 = off (the "
        "strips exactly as before — the Black Hole, Orbits and Fireworks "
        "strips keep their own blob/launch choreography, just without the "
        "colour build, fade or shockwave), up to 1.5 = stronger. Takes "
        "effect on the next charge, lull or drop. Per-scene details "
        "(charge fill, drop shockwave, flare punch, ...) are the strip "
        "effect's own settings on the scene (set_scene_entry_param)."),
    "background_fade_s": _spec(
        "background_fade_s", "Background fade",
        "How long, in seconds, the background on the lights takes to fade "
        "when it changes: Dark mode switching on or off, Light painting its "
        "background, or a colour set landing a new background in Hybrid. "
        "It fades round the colour wheel, never through grey or white. A "
        "scene's own crossfade or a flare's colour ramp keeps its own "
        "timing. Default 1; 0 = instant. A Light Show Display mode step "
        "can set its own fade for that one switch."),
    "lull_breath_hold_s": _spec(
        "lull_breath_hold_s", "Breath-hold before the drop",
        "How long the lights go to true black right before a drop lands, "
        "in seconds — on the crystal's Black Hole, Sauron and Eye, on "
        "the Pulse singles, and on Star — so the drop is born out of "
        "black. Orbits only dims to one dim blob and the Fish keeps "
        "swimming (never fully dark). Never longer than the lull's own "
        "darkness allows (half the lull, capped by 'Lull darkness "
        "(max)'). 0 = no breath-hold. Default 0.4. Takes effect on the "
        "very next lull."),
    "drop_timing_offset_ms": _spec(
        "drop_timing_offset_ms", "Drop timing",
        "How far off its mark every drop fires, in milliseconds — "
        "negative is EARLIER, positive later, 0 exactly on the mark. "
        "Default -400 (every drop fires 0.4 s early). Moves the whole "
        "drop together: the explosion, the drop's scene change, the "
        "Shockwave and the strips' drop; the lull before it builds to the "
        "new moment, so its breath-hold still ends right on the drop. "
        "Applies to every drop — his own drop triggers and the detected "
        "drop sequences — on the very next drop. A scene can carry its own "
        "drop timing instead (set later from its drop-sequence preview). "
        "Range -2000 to 2000."),
    "drop_shock_enabled": _spec(
        "drop_shock_enabled", "Drop Shockwave (whole room)",
        "On (default): the crystal effects with a drop Shockwave (Black "
        "Hole, Orbits, Sauron, Eye, Fish) paint it over their own drop — a "
        "rim bloom, a wavefront, debris and a splash on the crystal's edge, "
        "in the colour set's own colours. Off: no Shockwave on any drop, "
        "anywhere; every effect's own drop still plays exactly as before. "
        "A scene can also switch it off for itself (the scene setting "
        "drop_shock_enabled), and quiet drops can be left out with "
        "'Shockwave minimum energy'. The strips' own drop shockwave follows "
        "the same switch (the strips' colour and activity burst still "
        "plays). Star does not paint the Shockwave itself — this switch "
        "instead decides whether its own bands snap back out of the core "
        "on the drop (off: the plain bloom). Takes effect on the very "
        "next drop."),
    "drop_testing": _spec(
        "drop_testing", "Drop testing (play every detected drop)",
        "Off (default): a suggested drop waits for his approval on Home's "
        "Drops panel (or the Timeline) before it plays; a confident one "
        "plays on its own. On: every detected drop plays where a confident "
        "one would, approved or not, so he can watch them in the room and "
        "approve the good ones; the drop that just played moves to the top "
        "of the Drops panel, highlighted. A drop he removed, a part he "
        "switched off and a drop he switched off never play, even with "
        "testing on. The room's 'Scene changes' setting still decides "
        "whether analysed drops play at all. Stays on until switched off."),
    "drop_colour_change": _spec(
        "drop_colour_change", "Drop colour change",
        "On (default): every drop that plays arrives in a new colour set, "
        "about opposite the one showing on the colour wheel (see 'Drop "
        "colour spread') — instantly on the drop, or, once pre-drops play, "
        "fading across the pre-drop and landing on the drop. It picks from "
        "the sets the showing scene accepts (the incoming scene's, when the "
        "drop switches the scene), never a disabled one, through his own "
        "selector weights and rainbow limit; a rainbow counts as a big "
        "change. Force Colour, a resting house mode, a 2D drift gradient "
        "or a preview still win. Applies to his own drop triggers and the "
        "detected drop sequences alike. Off: drops change no colour, as "
        "before. Takes effect on the very next drop."),
    "drop_colour_spread_deg": _spec(
        "drop_colour_spread_deg", "Drop colour spread",
        "How far from exactly opposite (180 degrees on the colour wheel) "
        "the drop colour change may land, in degrees either side. Default "
        "30, i.e. 150-210 degrees away; the sets nearest 180 are likeliest. "
        "Narrower is a more extreme change but fewer sets qualify; when "
        "none does, the drop takes the farthest set it can and the show log "
        "says so. Range 5-90."),
    "drop_shock_min_energy": _spec(
        "drop_shock_min_energy", "Shockwave minimum energy (top-bar Energy)",
        "The drop Shockwave (on the crystal and on the strips), and Star's "
        "own bands snapping back, only happen when the top bar's Energy "
        "reading (the ⚡ Energy number, exactly as shown) is at least this "
        "much at the moment of the drop. Default 0.7. 0 = every drop gets "
        "it. A song's loudest section reads exactly 1.0, so even 1.0 "
        "still lets that section's drops through — to stop it entirely "
        "turn the Shockwave off instead. When the energy can't be read "
        "(no analysis for the song) the drop is not held back. Takes "
        "effect on the very next drop."),
    "pulse_flash_min_energy": _spec(
        "pulse_flash_min_energy", "Pulse flash minimum energy (top-bar Energy)",
        "The Pulse singles' flash flare (the brightness spike) only fires "
        "when the top bar's Energy reading (the ⚡ Energy number, exactly "
        "as shown) is at least this much at that moment — in a lull or "
        "out of one. Default 0.8. 0 = every flash fires. When the energy "
        "can't be read (no analysis for the song) the flash is not held "
        "back. Does not touch the colour-flip flare. Takes effect on the "
        "very next flash."),
    "drop_switch_enabled": _spec(
        "drop_switch_enabled", "Drop-led scene switch",
        "On (default): a drop sequence may change the scene — a hard cut "
        "ON the drop into a different scene that explodes from the centre "
        "(STAR, Orbits, Black Hole, Squiggles, Fish) or Fireworks, when "
        "the scene showing has grown stale. Off: every drop plays on "
        "whatever scene is showing, as before."),
    "drop_switch_after_previous_drop": _spec(
        "drop_switch_after_previous_drop", "Switch after a repeated drop",
        "On (default): a scene that already played the previous drop "
        "(without arriving on it) counts as stale, so the next drop "
        "switches it."),
    "drop_switch_stale_margin_s": _spec(
        "drop_switch_stale_margin_s", "Drop switch: overstayed margin",
        "Seconds beyond the showing scene's own minimum dwell after which "
        "it counts as overstayed — and an overstayed scene is switched "
        "EARLY, at the start of the charge (or on a flare inside the "
        "charge) rather than on the drop. Default 10."),
    "drop_switch_drops_in_a_row": _spec(
        "drop_switch_drops_in_a_row", "Drop switch: drops in a row",
        "A scene that has carried this many drops in a row counts as "
        "stale. Default 2; 0 turns this rule off."),
    "drop_switch_swallow_delay_s": _spec(
        "drop_switch_swallow_delay_s", "Fireworks meld: swallow delay",
        "When a stale Fireworks scene hands over to the Black Hole, "
        "Fireworks plays its own drop and the Black Hole cuts in this many "
        "seconds after the drop mark, swallowing the burst. Default 1."),
    "drop_switch_hit_threshold": _spec(
        "drop_switch_hit_threshold", "Fireworks meld: big-hit strength",
        "When a stale Fireworks scene hands over to Fish, Orbits, Squiggles "
        "or STAR, Fireworks plays its own drop and the next scene cuts in "
        "on the next analysed flare at least this strong (0-1, default "
        "0.6) — or one bar after the drop's tail if none comes."),
    "transition_programs_enabled": _spec(
        "transition_programs_enabled", "Thematic transitions",
        "On (default): a scene change between the Black Hole and the "
        "particle effects (Orbits, Fish, Squiggles, Fireworks), between "
        "Sauron / the Eye and them, and between Fish, Orbits and Squiggles "
        "runs a THEMATIC TRANSITION instead of the half-second crossfade — "
        "Infall / Eruption, Lensing / Fountain (Fireworks), Flame Lick / "
        "Ignition (the eye explodes, or ignites from a vortex onto its "
        "rim), Shoal Break / Shoaling, Unravel. The payoff lands on the "
        "trigger. Off: every switch crossfades as before."),
    "transition_program_ms": _spec(
        "transition_program_ms", "Thematic transition length",
        "How long a thematic transition takes, in milliseconds (600-2500, "
        "default 1400). Its payoff — the Black Hole igniting, or the "
        "eruption's bloom — still lands on the trigger; a longer program "
        "simply starts earlier."),
    "transition_velocity_blend_ms": _spec(
        "transition_velocity_blend_ms", "Thematic transition: velocity blend",
        "The last stretch of an Infall, in ms (default 500), over which "
        "every piece's motion blends into the Black Hole's own so the hand-"
        "off continues one motion. It also sets where the Infall's "
        "ignition (its payoff) sits."),
    "transition_infall_spin": _spec(
        "transition_infall_spin", "Infall: spiral turns",
        "Extra turns the pieces make as they spiral into the Black Hole "
        "(0-3, default 0.75)."),
    "transition_eruption_count": _spec(
        "transition_eruption_count", "Eruption: pieces",
        "How many pieces the Black Hole's eruption sprays before they "
        "implode onto the incoming effect (10-150, default 60)."),
    "transition_eruption_speed": _spec(
        "transition_eruption_speed", "Eruption: speed",
        "How fast the eruption's pieces fly out (0.5-2, default 1); it "
        "also scales the Fountain's spray and the Flame Lick's shards."),
    "transition_explode_frac": _spec(
        "transition_explode_frac", "Flame Lick: exploding fraction",
        "When Sauron or the Eye hands over to a particle effect the eye "
        "itself EXPLODES: this fraction of its lit cells fly out as shards "
        "in the set's colours (0-1, default 0.5); the rest collapse into "
        "the black. The shards then merge into the incoming effect."),
    "transition_lensing_pull": _spec(
        "transition_lensing_pull", "Lensing: pull",
        "How hard the Black Hole's pull bends the Fireworks' sparks into "
        "spiral arms as they fall in (Lensing), and how hard the Black "
        "Hole's gathered ring sprays out into fireworks (Fountain) — "
        "0.2-3, default 1."),
    "transition_ignition_turns": _spec(
        "transition_ignition_turns", "Ignition: vortex turns",
        "Turns the arriving pieces make as they gather onto the iris rim "
        "when Sauron or the Eye comes in (0-3, default 0.6)."),
    "transition_scatter": _spec(
        "transition_scatter", "Shoal Break / Unravel: scatter",
        "How wide a fish's dots spread as its body shatters (Shoal Break) "
        "and a chain's dots as it unspools (Unravel) — 0-2, default 1."),
    "transition_bands_pieces": _spec(
        "transition_bands_pieces", "Out of Star: pieces",
        "When the Star hands over to another effect its bands break into "
        "this many pieces (60-220, default 180), which then fly into the "
        "incoming effect."),
    "transition_bands_hold_ms": _spec(
        "transition_bands_hold_ms", "Out of Star: ring hold",
        "How long the Star's pieces keep turning on their rings before they "
        "unwind toward the Orbits or the Fish, in ms (0-800, default 300)."),
    "transition_unwind": _spec(
        "transition_unwind", "Out of Star: unwind",
        "How hard the Star's pieces unwind outward on their way to the "
        "Orbits (the Fish gets a gentler share) — 0-40, default 14."),
    # THE HOST FRAME (the shoal-burst plan) — the shoaling family: fish,
    # orbits, squiggles and the Black Hole's eruption into them
    "transition_burst_px": _spec(
        "transition_burst_px", "Shoaling: burst size",
        "How far the cloud puffs out from the new object it is riding when "
        "one shoaling effect becomes another (0-20 px, default 7). 0 turns "
        "the burst off everywhere — and for orbits into fish it brings back "
        "the old transition, where the fish simply appear on the blobs."),
    "transition_burst_ms": _spec(
        "transition_burst_ms", "Shoaling: burst opens over",
        "How fast that puff opens, in ms (80-700, default 300) — the only "
        "moment a piece moves quickly against the object it is riding."),
    "transition_land_at": _spec(
        "transition_land_at", "Shoaling: gather begins at",
        "How far into the transition the pieces start gathering back into "
        "the new object, as a fraction of it (0.1-0.9, default 0.45)."),
    "transition_graft_ms": _spec(
        "transition_graft_ms", "Shoaling: keep inherited speed",
        "How long a newly born object keeps the velocity it inherited from "
        "the one it replaced before its own motion takes over, in ms "
        "(60-800, default 250)."),
    "transition_count_hold_ms": _spec(
        "transition_count_hold_ms", "Shoaling: matched count holds",
        "How long after a shoaling transition ends the MATCHED count holds "
        "before the scene's own count wins again, in ms (0-3000, default "
        "400) — 3 fish become 3 orbits, then the scene's 6 a moment later."),
    "transition_match_count": _spec(
        "transition_match_count", "Shoaling: match the count",
        "Whether a shoaling transition gives the new effect as many objects "
        "as the old one had (3 fish become 3 orbits). Off: the new effect "
        "comes in with its own authored count straight away."),
}


def describe_registry() -> list[dict]:
    return [spec.model_dump() for spec in SETTINGS_REGISTRY.values()]


def current_values() -> dict[str, Any]:
    state = room_controls.load_room_controls()
    return {key: getattr(state, key) for key in SETTINGS_REGISTRY}


def describe_current() -> dict:
    """The get_settings tool's return value / GET endpoint body: every
    declared setting with its live value, right beside its legal range —
    so 'what's the brightness right now' never needs a second round trip."""
    values = current_values()
    return {
        "settings": [
            {**spec.model_dump(), "value": values[key]}
            for key, spec in SETTINGS_REGISTRY.items()
        ],
    }


def _nearest_legal(spec: SettingSpec, value: Any) -> Any:
    if spec.kind in ("float", "int") and isinstance(value, (int, float)):
        lo = spec.min if spec.min is not None else value
        hi = spec.max if spec.max is not None else value
        clamped = max(lo, min(hi, value))
        return int(round(clamped)) if spec.kind == "int" else clamped
    return None


def validate_change(key: str, value: Any) -> tuple[RoomControlState, RoomControlState]:
    """Returns (previous, candidate) on success. Raises SettingChangeError
    (never a bare pydantic ValidationError — callers need the structured
    detail) on an unknown key or an out-of-range/wrong-type value. Never
    writes anything."""
    if key not in SETTINGS_REGISTRY:
        raise SettingChangeError(
            f"{key!r} is not a settings-console setting",
            allowed_keys=sorted(SETTINGS_REGISTRY))

    previous = room_controls.load_room_controls()
    candidate_dict = previous.model_dump()
    candidate_dict[key] = value
    try:
        candidate = RoomControlState.model_validate(candidate_dict)
    except ValidationError as exc:
        spec = SETTINGS_REGISTRY[key]
        raise SettingChangeError(
            f"{value!r} is not a legal value for {key!r}",
            spec=spec.model_dump(),
            nearest_legal_value=_nearest_legal(spec, value),
            pydantic_errors=[e["msg"] for e in exc.errors()],
        ) from exc
    return previous, candidate


def _atomic_write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log() -> list[dict]:
    path = config.SETTINGS_LOG_FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def _append_log(entry: dict) -> None:
    log = _load_log()
    log.append(entry)
    while len(log) > SETTINGS_LOG_MAX_ENTRIES:
        log.pop(0)
    _atomic_write_json(config.SETTINGS_LOG_FILE, log)


def load_log(limit: int = 50) -> list[dict]:
    """Most-recent-first, the console's visible "what changed" record."""
    return list(reversed(_load_log()))[:limit]


def _fmt_value(v: Any) -> str:
    """Mirrors scene_console._fmt_value's vocabulary — one deterministic
    rendering for both domains' summary lines, never a raw repr."""
    if v is None:
        return "unset"
    if isinstance(v, bool):
        return "On" if v else "Off"
    return str(v)


async def apply_change(key: str, value: Any, source: str = "agent") -> dict:
    """THE write choke point. Validates (raises SettingChangeError on
    failure, nothing persisted), then writes through room_controls' own
    save + ambient-reconcile — the same two calls PUT /api/room-controls
    makes — and appends one durable, visible change-log entry."""
    previous, candidate = validate_change(key, value)
    room_controls.save_room_controls(candidate)
    ambient_result = await room_controls.reconcile_ambient_if_changed(previous, candidate)
    if previous.background_fade_s != candidate.background_fade_s:
        room_controls.push_background_fade(candidate)

    new_value = getattr(candidate, key)
    label = SETTINGS_REGISTRY[key].label
    entry = {
        "id": str(uuid.uuid4()),
        "ts_ms": int(time.time() * 1000),
        "op": "set_setting",
        "key": key,
        "old_value": getattr(previous, key),
        "new_value": new_value,
        "summary": f"Set {label} to {_fmt_value(new_value)}.",
        "source": source,
        "undone": False,
    }
    _append_log(entry)

    result = {"status": "applied", **entry}
    if ambient_result is not None:
        result["ambient_result"] = ambient_result
    return result


async def _op_get_settings() -> dict:
    return describe_current()


async def _op_set_setting(key: str, value: Any) -> dict:
    """Catches SettingChangeError HERE (not in settings_agent.py's
    dispatcher) so that module can stay domain-agnostic — see
    sonic_ops.py's docstring for why an operation's own handler owns its
    domain's exception type."""
    try:
        return await apply_change(key, value)
    except SettingChangeError as exc:
        return exc.payload()


# ═══ Force Scene / Force Colour BY NAME (2026-10-06, his ruling: "allow
# some flexibility in phrasing ... it should be a close match") — see the
# module docstring's own entry for why these are NOT registry keys. Both
# write through room_controls.apply_patch, the SAME writer PUT
# /api/room-controls uses, so the identical reconcilers run (the pin
# fires or skips exactly as a human PUT would) and there is no second
# write path to drift from it. ═══════════════════════════════════════

def _resolve_scene_name(name: str):
    from spectra.services import scene_store
    candidates = [(s.id, s.name) for s in scene_store.list_all()]
    return name_resolve.resolve_name(name, candidates, noun="scene")


def _resolve_color_target_name(name: str):
    from spectra.services import color_sets
    candidates = [(c.id, c.name) for c in color_sets.list_all()]
    return name_resolve.resolve_name(name, candidates, noun="colour set or group")


def get_force_pins() -> dict:
    state = room_controls.load_room_controls()
    from spectra.services import color_sets, scene_store
    scene = (scene_store.get_by_id(state.force_scene_scene_id)
            if state.force_scene_scene_id else None)
    card = (color_sets.get_by_id(state.force_color_target_id)
           if state.force_color_target_id else None)
    return {
        "force_scene": {"enabled": state.force_scene_enabled,
                        "scene_id": state.force_scene_scene_id,
                        "scene_name": scene.name if scene else None},
        "force_color": {"enabled": state.force_color_enabled,
                        "target_id": state.force_color_target_id,
                        "target_name": card.name if card else None,
                        "target_kind": card.kind if card else None},
    }


async def apply_force_scene(enabled: bool, scene: Optional[str] = None) -> dict:
    body: dict[str, Any] = {"force_scene_enabled": enabled}
    scene_name = None
    if scene:
        match, rejection = _resolve_scene_name(scene)
        if rejection is not None:
            raise SettingChangeError(rejection["reason"],
                                     **{k: v for k, v in rejection.items()
                                        if k not in ("status", "reason")})
        body["force_scene_scene_id"] = match.id
        scene_name = match.name
    elif enabled:
        current = room_controls.load_room_controls()
        if not current.force_scene_scene_id:
            raise SettingChangeError(
                "name a scene to pin — Force Scene needs one while turning on")
    try:
        result = await room_controls.apply_patch(body)
    except room_controls.RoomControlsPatchError as exc:
        raise SettingChangeError(str(exc)) from exc
    if scene_name is None and result.get("force_scene_scene_id"):
        from spectra.services import scene_store
        found = scene_store.get_by_id(result["force_scene_scene_id"])
        scene_name = found.name if found else None
    fired = result.get("force_scene_result") or {}
    if not enabled:
        summary = "Force Scene is off."
    elif fired.get("status") == "fired":
        summary = f"Force Scene is on, pinned to \"{scene_name}\"."
    elif fired.get("status") in ("skipped", "error"):
        summary = (f"Force Scene is pinned to \"{scene_name}\", but it did not fire: "
                  f"{fired.get('reason')}.")
    else:
        summary = f"Force Scene is pinned to \"{scene_name}\"."
    return {"status": "applied", "summary": summary, "force_scene_result": fired,
            "scene_id": result.get("force_scene_scene_id"), "scene_name": scene_name,
            "enabled": enabled}


async def apply_force_color(enabled: bool, target: Optional[str] = None) -> dict:
    body: dict[str, Any] = {"force_color_enabled": enabled}
    target_name = None
    if target:
        match, rejection = _resolve_color_target_name(target)
        if rejection is not None:
            raise SettingChangeError(rejection["reason"],
                                     **{k: v for k, v in rejection.items()
                                        if k not in ("status", "reason")})
        body["force_color_target_id"] = match.id
        target_name = match.name
    elif enabled:
        current = room_controls.load_room_controls()
        if not current.force_color_target_id:
            raise SettingChangeError(
                "name a colour set or group to pin — Force Colour needs one while turning on")
    try:
        result = await room_controls.apply_patch(body)
    except room_controls.RoomControlsPatchError as exc:
        raise SettingChangeError(str(exc)) from exc
    if target_name is None and result.get("force_color_target_id"):
        from spectra.services import color_sets
        found = color_sets.get_by_id(result["force_color_target_id"])
        target_name = found.name if found else None
    applied = result.get("force_color_result") or {}
    if not enabled:
        summary = "Force Colour is off."
    elif applied.get("status") == "applied":
        summary = f"Force Colour is on, pinned to \"{target_name}\"."
    elif applied.get("status") in ("skipped", "error"):
        summary = (f"Force Colour is pinned to \"{target_name}\", but it did not apply: "
                  f"{applied.get('reason')}.")
    else:
        summary = f"Force Colour is pinned to \"{target_name}\"."
    return {"status": "applied", "summary": summary, "force_color_result": applied,
            "target_id": result.get("force_color_target_id"), "target_name": target_name,
            "enabled": enabled}


def _op_get_force_pins() -> dict:
    return get_force_pins()


async def _op_set_force_scene(enabled: bool, scene: Optional[str] = None) -> dict:
    try:
        return await apply_force_scene(enabled, scene)
    except SettingChangeError as exc:
        return exc.payload()


async def _op_set_force_color(enabled: bool, target: Optional[str] = None) -> dict:
    try:
        return await apply_force_color(enabled, target)
    except SettingChangeError as exc:
        return exc.payload()


# ═══ The music-device allowlist (the Admiral, 2026-10-09) — NOT a
# SETTINGS_REGISTRY key, same reason as Force Scene/Force Colour above: a
# list of device names is a poor fit for set_setting's scalar shape, so
# this is its own small pair of ops writing through room_controls.
# apply_patch like everything else here. See RoomControlState.
# music_device_allowlist's own docstring and house.py's "THE MUSIC-DEVICE
# GATE" section for the mechanism this configures. ═══════════════════════

def get_music_device_allowlist() -> dict:
    state = room_controls.load_room_controls()
    return {"devices": list(state.music_device_allowlist)}


async def set_music_device_allowlist(devices: list) -> dict:
    if not isinstance(devices, list) or not all(isinstance(d, str) for d in devices):
        raise SettingChangeError("devices must be a list of device-name strings")
    cleaned = [d.strip() for d in devices if d.strip()]
    if not cleaned:
        raise SettingChangeError(
            "devices must name at least one Spotify Connect device — "
            "an empty allowlist would make the house never go music-reactive")
    try:
        result = await room_controls.apply_patch({"music_device_allowlist": cleaned})
    except room_controls.RoomControlsPatchError as exc:
        raise SettingChangeError(str(exc)) from exc
    return {"status": "applied",
            "summary": "Music-reactive lighting now only follows "
                      + " or ".join(repr(d) for d in cleaned) + ".",
            "devices": result["music_device_allowlist"]}


def _op_get_music_device_allowlist() -> dict:
    return get_music_device_allowlist()


async def _op_set_music_device_allowlist(devices: list) -> dict:
    try:
        return await set_music_device_allowlist(devices)
    except SettingChangeError as exc:
        return exc.payload()


# The one declaration that both enforces (settings_agent.ALL_OPERATIONS is
# built from this dict) and documents (its catalogue_entry() is what the
# "list operations" meta-tool shows Sonic) — see sonic_ops.py's docstring.
OPERATIONS: dict[str, SonicOperation] = {
    "get_settings": SonicOperation(
        name="get_settings", domain="settings", kind="read",
        summary="Read every settings-console setting's current value, "
                "unit, and legal range/choices.",
        instructions=(
            "No arguments. Always small (five settings) — safe to call "
            "whenever you need a fresh value before changing it."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_get_settings),
    "set_setting": SonicOperation(
        name="set_setting", domain="settings", kind="write",
        summary="Change ONE declared room-wide setting.",
        instructions=(
            "key must be one of the keys get_settings just showed you. "
            "The server re-validates the key and value against its "
            "declared range/choices and rejects anything outside them — "
            "this is the only way this changes anything. Voice dictation "
            "can mangle his product names ('spot effects' means SpotFX) — "
            "read intent, don't over-literally match words."),
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "enum": sorted(SETTINGS_REGISTRY)},
                "value": {"description": "The new value — type depends on "
                                         "the setting (see get_settings)."},
            },
            "required": ["key", "value"], "additionalProperties": False},
        handler=_op_set_setting),
    "get_force_pins": SonicOperation(
        name="get_force_pins", domain="settings", kind="read",
        summary="Read whether Force Scene and Force Colour are pinned "
                "right now, and to what.",
        instructions="Call before set_force_scene/set_force_color if "
                    "you need to know the current pin before changing it.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_get_force_pins),
    "set_force_scene": SonicOperation(
        name="set_force_scene", domain="settings", kind="write",
        summary="Turn Force Scene on (pinned to a named scene) or off.",
        instructions=(
            "scene is a scene's NAME — exact, or a close match tolerating "
            "dropped qualifiers like 'V2' ('Orbits' reaches 'Orbits V2' "
            "when that's the only clear match). Required when turning on "
            "unless a scene is already pinned; omit it to leave the pin "
            "as it is while flipping enabled, or to repin an "
            "already-enabled Force Scene to a different scene. Ambiguous "
            "or no-clear-match names are refused with the close "
            "candidates — never guessed between two plausible scenes."),
        input_schema={
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}, "scene": {"type": "string"}},
            "required": ["enabled"], "additionalProperties": False},
        handler=_op_set_force_scene),
    "set_force_color": SonicOperation(
        name="set_force_color", domain="settings", kind="write",
        summary="Turn Force Colour on (pinned to a named colour set or "
                "group) or off.",
        instructions=(
            "target is a colour set or group's NAME — same name-matching "
            "rule as set_force_scene (exact, dropped-qualifier, or a "
            "single clear fuzzy match; refused with candidates on a "
            "near-tie or no match). Required when turning on unless one "
            "is already pinned."),
        input_schema={
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}, "target": {"type": "string"}},
            "required": ["enabled"], "additionalProperties": False},
        handler=_op_set_force_color),
    "get_music_device_allowlist": SonicOperation(
        name="get_music_device_allowlist", domain="settings", kind="read",
        summary="Read which Spotify Connect device names let the house "
                "go music-reactive.",
        instructions="No arguments.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_get_music_device_allowlist),
    "set_music_device_allowlist": SonicOperation(
        name="set_music_device_allowlist", domain="settings", kind="write",
        summary="Replace the list of Spotify Connect device names that "
                "let the house switch from standard lighting to music-"
                "reactive lighting; music on any other device is ignored.",
        instructions=(
            "devices is the WHOLE new list (replaces, never merges) — "
            "call get_music_device_allowlist first if you only need to "
            "add or remove one name. Names must match the real device "
            "name Spotify reports (his usual ones are 'Serenity' and "
            "'Serenity guest'); matching is case-insensitive. Refused if "
            "empty — the house must always have at least one allowed "
            "device."),
        input_schema={
            "type": "object",
            "properties": {"devices": {"type": "array", "items": {"type": "string"}}},
            "required": ["devices"], "additionalProperties": False},
        handler=_op_set_music_device_allowlist),
}


async def undo_last_change() -> dict:
    """Reverts the most recent not-yet-undone change by re-applying its
    old_value through apply_change() itself — an undo is validated exactly
    like any forward change, never a raw file poke, and it leaves its own
    new log entry (source="undo") rather than deleting history."""
    log = _load_log()
    target = None
    for entry in reversed(log):
        if not entry.get("undone"):
            target = entry
            break
    if target is None:
        raise SettingChangeError("nothing to undo")

    result = await apply_change(target["key"], target["old_value"], source="undo")
    result["summary"] = f"Undid — {result['summary']}"

    log = _load_log()
    for entry in log:
        if entry["id"] == target["id"]:
            entry["undone"] = True
            break
    _atomic_write_json(config.SETTINGS_LOG_FILE, log)

    return result
