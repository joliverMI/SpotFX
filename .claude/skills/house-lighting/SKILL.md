---
name: house-lighting
description: >
  The house lighting ENGINE — spectra/services/house.py (modes, the gate,
  tick/reapply, the settings writer), house_fixtures.py (per-fixture
  power/brightness), house_energy.py (frame-rate caps, parking,
  send-on-change, audio pause), house_voice.py (Serenity's colours), and
  the Home Assistant seam (spectra/api/house.py). Load before touching
  any of these modules, the House page's settings panel, or Sonic's
  house_console.py. For the SEEDED CONTENT (the modes/scenes/colour sets
  scripts/seed_house_lighting.py writes), load house-scenes instead —
  that skill covers the data, this one covers the engine that runs it.
---

# House lighting engine

`spectra/services/house.py`'s module docstring (and AGENTS.md's "HOUSE
LIGHTING" sections, phases 1-4) are the binding statements. Five things
worth knowing cold:

1. **INERT UNLESS THREE THINGS ARE ALL TRUE**: a mode is set, SPECTRA
   holds the room, and `HouseSettings.enabled` is True (the CUTOVER
   SWITCH, phase 4 — ships OFF, so adding house lighting never silently
   changed a music take before someone turned it on). `house.gate()`
   answers this in one call; check it before assuming anything here
   acts.
2. **ONE SETTINGS WRITER FOR A FULL PATCH**: `house.apply_settings_patch(body)`
   is the exact merge `PUT /api/house/settings` has always done
   (voice_looks and energy sub-merges keep every OTHER field as he set
   it; `enabled`/`hue_excluded_lights` moving re-applies immediately).
   The HTTP route and Sonic's `house_console.py` (`set_house_lighting_
   enabled`/`set_house_energy`/`set_house_voice_look`) BOTH call this one
   function — never build a second merge beside it. `house.set_enabled
   (bool)` is the ONE exception: a narrower, in-process toggle of just
   the cutover switch (no body to merge), used by Light Show's "Turn
   house lighting on/off" actions — same end effect as the PUT, separate
   code path because Light Show runs in-process and has no body to PATCH.
3. **TWO THINGS NEVER MOVE BY VOICE**: `hue_excluded_lights` (a safety
   fence for a bulb a mode should never touch — empty by default; every
   bulb in his Spectra home, loft uplight and ledge lights included, is
   an ordinary house-mode bulb, and carving those four out as Home
   Assistant's was a wrong assumption, corrected 2026-10-06) and the
   seam-wiring fields (`tv_strips`, `voice_fixtures`,
   `own_brightness`, `owned_brightness`, set once at cutover with River).
   All five stay readable through `get_house_settings`; none is in
   `house_console.ENERGY_KEYS` or any other write op. Don't add a write
   path for them without going back to the Admiral. The 2026-10-06
   correction only fixed what a FRESH `scripts/seed_hue_scope.py`/
   `scripts/seed_house_lighting.py` run writes — a room that already ran
   the old defaults needs the one-time
   `scripts/fix_loft_ledge_bulb_scope.py` (dry-run default, `--apply`
   with a required `--spectra-url`) to move the four bulbs out of
   `hue_scope.json`'s `"excluded"` map and clear them from the live
   `hue_excluded_lights` through this exact `apply_settings_patch` path.
4. **A MODE IS A PERSON'S PICK; HOME ASSISTANT'S WORD IS A CLOCK.**
   `house.set_mode(mode=..., source="sonic")` behaves exactly like a
   House page press — it holds until HA's own `lighting_mode` next
   changes, not until the next tick. `house_console.set_house_mode`
   already resolves a mode by name (exact, then close match) — reuse that
   pattern, don't add id-based lookup.
5. **THE ENERGY BLOCK ACTS ONLY WHILE THE LAYER IS ACTIVE** (same gate as
   #1) — `resting_fps`/`park_idle`/`send_on_change`/`keepalive_s`/
   `audio_pause_after_s` are real-time knobs over `fx/device_rate.py` and
   `fx/device_output.py`; an energy edit re-enters the current mode
   (`house.reapply()`) so a changed default lands now, not at the next
   mode switch.
6. **"PLAYING" MEANS PLAYING ON AN ALLOWED DEVICE (the Admiral,
   2026-10-09)** — `house.deps.playing`/`_default_playing` (NOT
   `bridge.is_playing()` directly) is the one choke point `mode.music ==
   "show"`'s hand-in/hand-out, `scene_deferral()`, `response_deferral()`
   and `house_overrides_display()` all route through; it reads False
   unless `bridge.device_name()` matches `RoomControlState.
   music_device_allowlist` — a FIELD ON THE SETTINGS-CONSOLE ROOM MODEL
   (`spectra/services/room_controls.py`), not `HouseSettings`, so it's
   edited through `RoomControlsBar.tsx`'s "Music devices" field or
   Sonic's `get_music_device_allowlist`/`set_music_device_allowlist`
   (settings domain, NOT this module's `house_console.py`). A device
   switch mid-song hands out immediately (`deps.music_device_mismatch`),
   skipping `music_debounce_s`, which still governs a genuine stop. See
   `house.py`'s own "THE MUSIC-DEVICE GATE" docstring section.

## Sonic reach

`spectra/services/house_console.py`, domain `"house"`. Inside a mode:
`house_status`, `list_house_modes`, `set_house_mode`, `create_house_mode`,
`set_house_mode_setting`, `set_house_fixture`, `set_house_hue`,
`set_house_mode_pool` (all pre-existing). House-wide, added 2026-10-06:
`get_house_settings` (reads everything, including the read-only fields),
`set_house_lighting_enabled` (his ruling: BOTH directions by voice),
`set_house_energy`, `set_house_voice_look`. Deleting a mode, and anything
that writes Home Assistant's own facts (mains, TV Music, media, voice
state) stay out — River's side of the seam, or an irreversible act on his
authored library.

Build item C13's own discipline: every `HouseSettings` field must be
either reachable through a write op or on a named read-only list —
`tests/test_house_console.py::
test_every_house_settings_field_is_settable_or_read_only` holds that by
walking the real model.

## Proofs

`tests/test_house_engine_hooks.py`, `tests/test_house_fixtures.py`,
`tests/test_house_energy.py`, `tests/test_house_voice.py`,
`tests/test_house_console.py`, `tests/test_house_seam_api.py`,
`scripts/check_house_summary.mjs`.
