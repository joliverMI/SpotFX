# House lighting (/house)

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## HOUSE LIGHTING (`/house`) — the room's always-on resting look (phases 1–2)

Plan: `/home/javi/fleet-spotfx/data/standard-lighting-plan/report.md` (his
ask: Spectra as the standard lighting engine, not only music; HA keeps its
`lighting_mode` clock, Spectra owns what each mode looks like).
**`spectra/services/house.py`'s module docstring is the binding statement**;
`spectra/models/house_mode.py` is the shape (two stores, the Light Show's
split). Six things:

- **INERT UNLESS SPECTRA HOLDS THE ROOM AND A MODE IS SET.** The gate is
  `show_output.ownership_refusal()` / `standdown_reason()` — nothing of its
  own. No mode (the shipped state) costs one dict read in every hook. A mode
  set while the room is released is only recorded. Standby (a preview,
  camera run, night run) writes nothing and lifts the caps.
- **THE BASE LAYER LIVES IN `show_output`, not `fx/device_output`** — the
  output layer keeps ONE target per device, so two writers would clobber.
  `show_output.set_base(levels, states)` sits below every show hold/level
  (level = base × show Levels; a hold wins the state); letting go of a show
  hold and End show fade back to the BASE. A room release drops it.
- **HOOKS AT THE EXISTING CHOKE POINTS** (each lazy, never raising, None when
  inert): `house.scene_deferral()` in `fire_scene_by_id` (after Force Scene
  resolves — a pin outranks the mode; the house's own fires pass with
  `origin="house"` and `transition_ms`), in the trigger engine's
  `select_color_set` and `engine.fire_analysed_color_event`;
  `house.response_deferral()` in `engine._response_gate`/`_update_gate`
  ("ignore" only); `house.journey_override()` read by the conductor's
  `_destination_pool`/`_journey_leg` (wired in `engine.py`);
  `house.hue_directive()` read by `ambient_music_gate.reconcile`/`status`
  (plus `house.pending_hue_directive()` at the same two choke points — a
  mode that WILL hold Hue once the layer may act, see the restart-flash fix
  below). A new music-driven write path needs the same check or a calm/
  ignore mode will leak through it.
- **HUE: per-area looks over the bridge** — `ambient.reconcile_looks`/
  `verify_looks` (colour temperature as CLIP v2 `color_temperature.mirek`,
  colour, off), routed by the gate when a directive exists (target tuple
  grew a 4th element, `looks`; a 3-tuple is still accepted). A house hold is
  REPORTED by the verifier, never repaired (yield until the next mode
  change). A mode with no Hue looks leaves Hue to the toggle exactly as
  before. Today's Ambient is labelled **"Hue Hold"** in the UI only — the
  `ambient` wire key, `ambient_status` message and every field name are a
  frozen HA contract and did not change.
- **MOTION AND CAPS**: `"motion": true` tags exactly one numeric param per
  effect in `config/effect_params.json` (`device_model.motion_param_for`);
  a hook's `motion` is a 0..1 position in that param's range, written as a
  glide AND carried with `conductor.on_surge` (or drift and the param
  watchdog fight it). Frame-rate caps are `fx/device_rate.py` (VENDOR #43,
  only ever lowers, per virtual loop — siblings share the lowest cap).
- **THE HA SEAM**: `POST`/`PUT /api/house/mode` `{"ha_mode": ..., "source":
  "ha"}` (idempotent; always 200 with a status word, 404 only for an unknown
  mode NAME), read back on `GET /api/house/mode` and engine status's
  `lighting` key. A non-"ha" source is MANUAL and holds until HA's word
  CHANGES. Sonic domain `house` (`house_console.py`; no delete). Tests:
  `tests/test_house_*.py`, `tests/test_device_rate.py`,
  `scripts/check_house_summary.mjs`. Help section `house`.

**PHASE 2 — the rest of the Home Assistant seam (2026-10-05).**
`docs/HOUSE_HA_SEAM.md` is the wire (every route, for River);
`spectra/services/house_fixtures.py`, `house_voice.py` and
`house_restart.py` are the binding statements. Six things:

- **RECORDED ALWAYS, ACTED ON ONLY WHILE `house.layer_active()`** (a mode
  set, SPECTRA holds the room, no standby). HA's facts (TV Music, the media
  centre, fixture overrides) live in `house_state.json`; the seam's settings
  (TV strip ids, voice fixtures/colours) in the library
  file. No mode → nothing withheld, no WLED written.
- **WITHHELD ≠ DARK.** A lent or switched-off fixture gets NO packet
  (`fx/device_output.set_withheld`, VENDOR #44), checked in
  `Device.update_pixels`; suspension streams it anyway. `streaming_device_ids`
  and `device_gaps` leave withheld fixtures out, or the dark-fixture watch and
  the activation gate would call a switched-off fixture a fault. Off = no
  stream, `{"live": false}`, `{"on": false}`; on = `{"on": true}` WHILE
  STILL WITHHELD, then the stream (`pending_on`).
- **A WLED'S BRIGHTNESS IS HOME ASSISTANT'S — SPECTRA NEVER WRITES IT
  (2026-10-12, the Admiral: "Home assistant can set the WLED global
  brightness of any of these lights, and spectra doesn't touch that
  value"; `data/wled-bri-audit/report.md`, his D1a/D2a/D3a).**
  `house_fixtures.py`'s "BRIGHTNESS IS HOME ASSISTANT'S" and "POWER FOLLOWS
  THE MODE, NEVER RE-ASSERTED" docstring sections are the binding
  statement. It retired a whole week of brightness ownership (2026-10-05
  to 10-12: a per-take "ceiling", soft power through `bri 1`, a 60 s drift
  check that corrected HA's raises back down, a hand-back of a days-old
  `bri` — which left three fixtures stuck at bri 1 the morning it went).
  Four things hold now:
  * **No payload carries `bri`, `seg[].bri` or `maxbri`, anywhere** —
    `fx/utils.py::WLED._wled_request` (the one WLED transport) refuses
    one (VENDOR #78; `set_brightness` is deleted, and the dead flush of
    Force max brightness is refused too), and `tests/test_wled_never_writes_bri.py`
    drives that transport and its real callers (house_fixtures' power
    writes, the vendored sync-mode flush) and asserts the refusal fires
    and nothing reaches `requests.post`.
  * **Power is exactly `{"on": true|false}` and is due only on a CHANGE**:
    the effective mode (a media overlay counts), a fixture's target (lend,
    override, mains), or a take of a released room. `HouseState.
    power_applied` records the last power Spectra switched each WLED to
    and under which mode, durably — a restart under the same mode writes
    nothing. There is NO drift check: an HA "off" stands until the next
    mode change; a failed write is named, not retried on the clock.
  * **Hand-back on release is power only**, and only where Spectra's own
    last switch left the fixture different from `pre_take["on"]`
    (`pre_take` no longer records `bri`; an old entry's is dropped on load).
  * **Mode `level`/`music_level` are pixel brightness that MULTIPLY with
    HA's.** D3a set every WLED row to 100% at ship
    (`scripts/migrate_house_wled_levels_full.py`, dry run default,
    `--apply` with `--spectra-url`; the seeder seeds 100% too).
    `own_brightness`/`owned_brightness` are retired — dropped on load,
    refused by name on a PUT (`house.RETIRED_SETTINGS`).
  Don't "fix" a dim WLED by writing brightness: ask Home Assistant (River).
- **MEDIA IS AN OVERLAY**: `house.current_mode()` is the EFFECTIVE mode —
  the one answering to "TV" / "TV paused" (source-specific first) while a
  source is on AND a clock mode is set — with the clock's pick kept
  underneath (`clock_mode()`). Anything that needs "which mode" calls
  `current_mode()`; only `set_mode` compares against `st.mode_id`.
- **THE VOICE NEVER WAITS** (`house_voice.set_voice` is sync, no I/O —
  asserted structurally) and is an OVERLAY in `show_output` (`overlay_set`/
  `overlay_clear`): precedence voice > show hold > base, except a show hold
  landing mid-utterance takes the fixture outright. Base pushes and every
  release path consult `_overlay`; a new show_output writer must too.
- **A RESTART KEEPS THE LAST PICTURE** while a mode drives the room: the
  shutdown decides `hold_on_shutdown()` BEFORE `go_dark()` and tears down
  with `live.deactivate(hold_last_frame=True)` (no WLED release, VENDOR #45);
  `prepare_for_resume()` re-installs the base/caps/withheld/Hue-held snapshot
  (`house_restart.json`) BEFORE `resume_own_room()`, so the first frame
  carries it; Hue areas come up frozen (VENDOR #46) and `after_resume()`
  unfreezes any the gate neither holds NOR INTENDS to hold
  (`_gate_intends_hold`: an ON transition in flight, a live/pending house
  directive, or the stored toggle — the startup reconcile can return before
  its hold lands, and reading only what LANDED is what let the dining area
  stream the show under "held" on 2026-10-07; a kept area is watched and
  released if the hold never comes). The take scope (PR 317) holds
  throughout: everything resolves through `show_output._real_devices` /
  `resolve_target`. Tests: `tests/test_house_{fixtures,voice,restart_hold,
  withhold_landing,seam_api}.py`, `tests/test_hue_hold_restart_race.py`;
  help topic `house-ha-seam`.

**PHASE 3 — ENERGY (2026-10-05).** `spectra/services/house_energy.py`'s
docstring is the binding statement; the settings are his data
(`HouseSettings.energy`, partial `PUT /api/house/settings {"energy": …}`).
Five things:

- **EVERYTHING HERE ACTS ONLY WHILE `house.layer_active()`** — no mode, a
  standby or a released room is byte-identical to before (no parking, every
  frame sent, audio listening).
- **CAPS AND PARKING ARE TWO OWNERS IN `fx/device_rate.py`.** Resting caps
  (`energy.resting_fps`, Matrix 20 / Strips 20 / Singles 10, a mode's own
  `fps` wins) are pushed with the mode's plan; PARKING (2 frames/s for a
  virtual none of whose devices takes frames — a dummy like `radial-dummy`,
  withheld, a frozen Hue area, an inactive driver) is decided per frame on
  the render thread (VENDOR #47). Never 0: the render-plane dead-man needs
  every active virtual to flush within `live_host.STALE_AFTER_S` (2 s).
  **The vendored fps→sleep table floors at 10 fps**: a cap at or below 10
  used to run at ~11; a LOWERED rate ≤ 10 now sleeps `1/rate`.
- **SEND ON CHANGE** (VENDOR #48): a frame byte-identical (DDP's own
  `astype(uint8)`) to the last one sent is skipped until a keep-alive
  (`energy.keepalive_s`, ≤ 2 s — the sconces leave realtime after 2.5 s).
  Never Hue, never while suspended. Each device counts `_frames_sent`/
  `_frames_skipped`; the House page's Energy lines read those, never a
  setting.
- **OFF MEANS NO STREAM.** A mode's `off` on a WLED fades to black over
  the glide, then `house.mode_off_devices()` hands it to house_fixtures as
  TARGET_OFF (withheld + live:false + on:false). The phase-3 soft power
  (a `bri: 1` dip around every switch, to hide the WLED's own preset) is
  RETIRED with brightness ownership (2026-10-12) — a brief preset frame on
  a switch is possible and was handed to a room check, never to a
  brightness write. A Light Show Steady/Freeze hold beats a mode's off.
- **MAINS OFF = NO STREAM, NO SEARCH.** `PUT /api/house/mains` records HA's
  report (`HouseState.mains_off`); acted on only while a mode drives:
  TARGET_UNPOWERED (withheld, nothing written), `activation_report.recheck`
  skips it (`not_searched`), and a recheck/mains-on clears it whatever the
  room's state. A missed "on" is caught by one json/info knock every
  `MAINS_KNOCK_S` (600 s) — never a sweep. **AUDIO PAUSE**: after
  `energy.audio_pause_after_s` (120) of CONFIRMED quiet the capture stream
  closes (`live.pause_audio`); music, another hub listener (A/V sync) or the
  layer going inactive resume it; an unknown playback read restarts the
  quiet clock. **A RELEASE HANDS BACK POWER** (found in the phase-3 room
  re-measure: the dining table was left ON): before its first power write
  house_fixtures records each WLED's `{on, ip}` (`HouseState.pre_take`,
  durable) and, once the owner is RELEASED, writes `{"on": before}` back
  (only where Spectra's own switch changed it) and reads it back — a
  fixture off before a take is off after. Never
  on a restart or a handover to SpotFX. Status labels are unique
  (`house.fixture_labels()`: four of his WLEDs are all named "WLED").
  Measure with `scripts/measure_room_energy.py` (read-only, the planner's
  method; measured 2026-10-05: 39.3% → 16.1% of a core, 285 → 120 UDP/s,
  14.1% / 78 with the sconce mains reported off). Tests: `tests/test_house_energy.py`,
  `tests/test_send_on_change_landing.py`, the phase-3 sections of
  `tests/test_device_rate.py`, `test_house_lighting.py`,
  `test_house_fixtures.py`, `test_activation_report.py`,
  `test_house_seam_api.py`; help topic `house-energy`.

**THE HUE SCOPE — ONE REST WRITE POINT, A PER-BULB ALLOW-LIST (2026-10-05,
after a 02:31 proof take lit his Loft Ceiling Uplight and Ledge lights).**
`fx/hue_scope.py` is the binding statement. Every Hue light write in either
process goes through `hue_scope.put`: one light at a time, only ids on
`storage/spectra/hue_scope.json` (his 17 living-room + dining bulbs — the
Loft Ceiling Uplight and the three Ledge bulbs included; an earlier build
wrongly carved those four out as Home Assistant's, corrected 2026-10-06,
see "THE FOUR BULBS ARE ORDINARY" below;
`scripts/seed_hue_scope.py` writes it, GET-only, from the bridges), never a
group/room/zone/"all lights"; a missing file allows NOTHING. Resolvers filter
with `allowed_pairs` so out-of-scope bulbs are never attempted or reported.
`tests/conftest.py` makes it permissive for suites not about it (and so must
any subprocess test driver — see `tests/scoped_take_driver.py`); a new Hue
writer must use `hue_scope.put` (`tests/test_hue_scope.py` checks by AST).
Two more rules from the same night: `ambient.room_available()` refuses a
RELEASED record (a release moves the record first and keeps the stack up for
seconds — the stored Hue Hold landed on all 17 bulbs after River's restore),
and `ambient._hue_put` re-checks it per bulb so a hold in flight stops; the
release fade dims only bulbs that READ ON (its dim write carries on:true) and
sends an unreadable bulb the off write only.

**THE STREAM IS IN SCOPE TOO (2026-10-06).** Starting a Hue entertainment
session (`action: start`) makes the bridge switch on EVERY bulb in the
area before any frame is sent, so the REST allow-list alone cannot cover
it — a bulb can be lit by a session start without a single REST write ever
touching it. `HueDevice._blocking_activate` reads the area from the bridge
before every start and refuses (`hue_scope.stream_refusal`, `fx/VENDOR.md`
#52) an area holding a bulb off the allow-list or one it cannot identify;
the area is then simply not streamed, re-read every
`SCOPE_RECHECK_INTERVAL` (60 s), and named on `/ownership` + `/liveness`
(`hue_stream_refusals`) and the room bar (help `hue-scope-stream`). This
is a GENERIC safety net for a bulb genuinely outside the room, not a rule
about any bulb of his today: see "THE FOUR BULBS ARE ORDINARY" below for
why it does not fire for his Music Group. Nothing here depends on the
house layer — the start is the one door every Hue stream goes through.
Spec: `tests/test_hue_stream_scope.py` (a model bridge that powers the
area on start, with the shipped driver as red control).

**THE FOUR BULBS ARE ORDINARY (2026-10-06, the Admiral's own correction,
verbatim: "i want the loft and ledge bulbs to be part of the living room
hues, they should be part of the spectra home. they shouldn't be treated
differently. that was an incorrect assumption yall made").** Built on
2026-10-04/2026-10-05, the Loft Ceiling Uplight and the three Ledge bulbs
(all four in his "Music Group" entertainment area, alongside six other
living-room bulbs) were carved out as "left to Home Assistant" —
`storage/spectra/hue_scope.json`'s allow-list excluded them,
`HouseSettings.hue_excluded_lights` defaulted to naming them
(`scripts/seed_house_lighting.py`'s `HUE_LEFT_ALONE`), and the stream-scope
guard above refused to start the Music Group session at all because it
held them. All of that was a wrong assumption, not a standing design: they
are ordinary bulbs of his Spectra home, driven exactly like the other six
in that area and the seven in the dining area — the music show's
entertainment stream, house modes and Hue looks, Ambient (Hue Hold),
preview, the room map, and Sonic all reach them like any other Hue bulb.
`scripts/seed_hue_scope.py`'s `DEFAULT_EXCLUDE` is now empty (every bulb
in a streamed area is allowed by default) and
`scripts/seed_house_lighting.py` seeds no exclusion at all —
`HouseSettings.hue_excluded_lights` stays available (default `[]`) as the
mechanism for a FUTURE bulb he genuinely wants left to Home Assistant,
never a default. The stream-scope guard above is unchanged and stays a
generic safety net; it simply never fires for the Music Group now that
every bulb in it is allow-listed. Spec: `tests/test_hue_stream_scope.py`,
`tests/test_hue_scope.py`, `tests/test_house_phase4.py`,
`tests/test_seed_house_lighting.py`.

**The fixed defaults only govern a FRESH seeder run — his own already-
persisted `storage/spectra/hue_scope.json` and `HouseSettings.
hue_excluded_lights` are untouched by a deploy restart alone**, since
neither file is migrated on load. `scripts/fix_loft_ledge_bulb_scope.py`
(dry-run default, `--apply`, `--spectra-url` required with `--apply`) is
the one-time catch-up: it moves the four bulbs out of `hue_scope.json`'s
`"excluded"` map by direct backed-up file edit, and clears their names
out of `hue_excluded_lights` through the live service's own
`PUT /api/house/settings` — never a direct edit to `house_modes.json`,
which would race `apply_settings_patch`'s own reconcile tick. Idempotent.
Spec: `tests/test_fix_loft_ledge_bulb_scope.py`.

**A RESTART MUST NOT LAND THE ROOM TOGGLE BEFORE THE MODE (2026-10-06).**
Every restart under Away lit his allow-listed Hue bulbs for ~20 s: the
resume sets `live.host` (so `live.active` reads True) ~16 s before the
engine goes live, the house gate refuses while the engine is on paper, so
`house.hue_directive()` was None and the first bridge broadcast landed the
STORED Hue Hold toggle (#ffe392, 100 %) until the mode's "off" took over.
Two guards: `ambient.room_available()` refuses while `live.assembling`, and
the Hue Hold gate holds the toggle back (no write, status
`house-pending`) while `house.pending_hue_directive()` names a set mode that
will hold Hue once the layer may act (also a quiet take). A new path that
reaches Hue while the house layer is refused must ask the same question.
Spec: `tests/test_restart_hue_flash.py`.

**PHASE 4 — his starting content, and the CUTOVER SWITCH (2026-10-05).**
`scripts/seed_house_lighting.py`'s docstring and `.claude/skills/
house-scenes/SKILL.md` are the binding statements for the content (seven
modes, two house scenes, Calm - Evening, Night Light, every HA word mapped).
Four things:

- **`HouseSettings.enabled` SHIPS OFF and `house.gate()` answers ("off",
  ...) first.** Once modes exist HA's 5-minute POST maps to one, so without
  it the next music take would run under a mode (Hue held, master brightness
  owned, Away silencing music) before River cut a writer over. Off = recorded
  and mapped, nothing applied; the heartbeat reads `idle` with
  `house_enabled: false`. `tests/conftest.py` writes it ON for every test (the
  suites prove a mode acting); `tests/test_house_phase4.py` proves the OFF
  default.
- **A second group over the SAME sets is a trap**: a set fired by its own id
  wears every enclosing group's overrides, alphabetically-last winning, so
  "Calm - Evening" over Calm's members would turn Standard and every music
  show red. Evening is a group of COPIES. Same reason the new sets are
  `scene_v2_opt_out` and the house scenes have NO sequencer entry (which is
  all that keeps the music engine from drawing a scene).
- **Hue bulbs a mode leaves alone** (`hue_excluded_lights`) ride the
  directive as `"skip"` looks, area `"*/<bulb>"` (`ambient.skipped_lights`) —
  never held, switched off or reported. A new consumer of house looks must
  ignore `skip` the way `look_for` does.
- **An ordinary take pre-freezes the Hue areas the mode will hold**
  (`house.take_frozen_areas` → `fx/hue_freeze` in `SpectraSide.activate`,
  added to a restart's names; `house_restart.after_take` unfreezes any the
  gate does not end up holding). Before, a take streamed the scene to every
  bulb in the area for the seconds before the gate froze it.
- **The house journey travels opted-out sets the mode names**
  (`drift_conductor._destination_pool`); before, every Calm member's opt-out
  held Standard's walk forever. The breathing effect (`gradient`) is
  registered with `no_background_color` and its breath survives a glide
  (VENDOR #49, `.claude/skills/gradient-effect`).

**SONIC REACH WIDENED TO HOUSE-WIDE SETTINGS (2026-10-06, Sonic coverage
audit build).** Before this, Sonic could do almost everything INSIDE a
mode but could not touch `HouseSettings` itself — not even read it.
`house_console.py` gained `get_house_settings` (reads everything,
including the fields it cannot change), `set_house_lighting_enabled`
(his ruling: BOTH directions by voice, not off-only), `set_house_energy`
(resting fps per category/fixture or remove, park_idle, send_on_change,
keepalive_s, audio_pause_after_s), and `set_house_voice_look` (Serenity's
colours). `house.apply_settings_patch()` is the ONE writer both
`PUT /api/house/settings` and these ops call — factored out of
`spectra/api/house.py`'s own route so neither can diverge. Still
deliberately read-only: `hue_excluded_lights` (a safety fence around
bulbs outside the room) and the seam-wiring fields (`tv_strips`,
`voice_fixtures` — set once at cutover with River). A WLED's brightness is
no Spectra setting at all (Home Assistant's, 2026-10-12). See the
`house-lighting` skill.

**THE MUSIC-DEVICE GATE (the Admiral, 2026-10-09): "When I'm playing
music on devices that aren't Serenity or Serenity guest the system
should not change from the standard house lighting to the music reactive
lighting ... otherwise it should be ignored."** `RoomControlState.
music_device_allowlist` (`spectra/services/room_controls.py`, default
`["Serenity", "Serenity guest"]` — his two real Spotify Connect device
names, matched case-insensitively against `spectra/services/bridge.py`'s
new `device_name()`, which reads the identical `track.device_name` field
root's own `api/spotify_client.py`/`settings.spotify_device_names`
already match against — the real reported device, never guessed, and
never re-derived from a second source). Gated at exactly ONE choke
point for the "show" policy's own hand-in/hand-out: `house.py`'s
`deps.playing`/`_default_playing` (its own "THE MUSIC-DEVICE GATE"
docstring section is the binding statement) — `scene_deferral()` and
`house_overrides_display()` inherit it for free, since both already
route through `deps.playing`. A device switch mid-song is handled both
ways: switching onto an allowed device hands in immediately (the
existing `playing is True` edge); switching OFF one hands out
immediately too, via a new `deps.music_device_mismatch` seam, rather
than waiting on `music_debounce_s` (tuned for a genuine stop/inter-song
gap, not a deliberate device change).

**Firstmate's confirmation the same day widened this past the "show"
phase alone: "with music on a non-allowed device, NOTHING musical
reaches the lights — no show frames, scene changes, flares, drop
sequences or Light Show trigger arms firing from that playback."**
Scene changes and analysed-colour jumps needed no further work —
`scene_deferral()` already covers every automatic scene/colour choke
point (sequencer rolls, `fire_scene` triggers, `select_color_set`
triggers, the analysed colour event, drop-led switches), and a resting
mode (including one resting BECAUSE of a wrong device) already owns
them all. Two real gaps remained, both because the underlying mechanism
reacts to "a track is playing" with no device awareness of its own:

- **Flares, charge/lull/drop, drop-sequence members, and update
  flares** — all route through `engine._response_gate`/`_update_gate` →
  `house.response_deferral()`, which before this only deferred for an
  "ignore" policy — a "show" mode resting because of a wrong device
  (as opposed to genuinely nothing playing) was never covered, because
  response_deferral predates any device concept and the underlying
  trigger engine keeps ticking on the real position regardless of which
  device reports it. Fixed with a new standalone predicate,
  `house.confirmed_wrong_device()` (a mode is active AND spot-effects
  confirms a track IS playing AND the device fails the allowlist) —
  `response_deferral()` now defers on it UNCONDITIONALLY, regardless of
  `mode.music` policy, so a device he never authorised silences flares
  even under "calm" (whose own docstring otherwise keeps them playing
  through music, by design, on an allowed device).
- **The Light Show's High/Low Trigger cue arms** (`spectra/services/
  show_arms.py`'s `on_cue`, reached through `engine.py`'s `_show_cue`
  wiring) are deliberately independent of `scene_change_mode`/
  `mode.music` by design (every analysed song has cues, his own
  triggers or not) — so they had, and were meant to have, NO house gate
  at all, including none for the wrong-device case. `engine._show_cue`
  now checks `house.confirmed_wrong_device()` before calling
  `show_arms.on_cue`; the crossing's own `_fired` bookkeeping
  (`trigger_engine._tick_show_cues`) still consumes the mark either way,
  so a gated cue is skipped once, never retried or stuck. A manual
  scene-change arm (`show_arms.on_scene_change`, reached from ANY real
  scene fire including his own Fire button) is deliberately NOT gated —
  an explicit human action is never silenced by any of this, matching
  Force Scene's own precedent.

Visible in the UI (`RoomControlsBar.tsx`'s Scenes panel, a "Music
devices" text field, comma-separated) and to Sonic
(`settings_console.get_music_device_allowlist`/
`set_music_device_allowlist` — a dedicated pair, same "a list is a poor
fit for `set_setting`'s scalar shape" reason as Force Scene/Force
Colour, NOT a `SETTINGS_REGISTRY` key). An emptied allowlist is refused
— the house must always have at least one allowed device. Deliberately
NOT touched: `bridge.is_playing()` itself, which Ambient/dark_light/
house_restart each read independently for their own, broader "is music
playing at all" question this ask never named. Spec:
`tests/test_bridge.py`, `tests/test_house_lighting.py`'s "THE
MUSIC-DEVICE GATE" section, `tests/test_house_engine_hooks.py`'s
`_show_cue` tests, `tests/test_settings_console.py`,
`tests/test_settings_agent_cli.py`. Help topic `music-device-gate`.

**THREE DEFECTS FROM THE FIRST REAL HANDOVER, FIXED 2026-10-05 (PR
fm/house-handover-polish)** — all found the same cutover afternoon:

- **A fixture whose mode plan is off was switched ON before being switched
  off, because `house_fixtures.py` and `house.py` run two INDEPENDENT 1 s
  supervisor loops with no ordering guarantee between them.**
  `house_fixtures.desired()`'s own default-everything-ON fallback used to
  fire as soon as `house.layer_active()` went true (room taken over, mode
  set) regardless of whether `house.py`'s own `_enter()` had even STARTED
  computing the mode's `power_off` set — `mode_off_devices()` reads
  `house._rt.off_ready`, which `_enter()` only populates once ITS tick has
  caught up, so in the race window it reads `{}`, not merely "not ready
  yet." `house.mode_power_off_scope()` is the fix: a PURE, synchronous
  recomputation of the current mode's `power_off` set straight from
  `build_plan(current_mode())`, with no dependency on `house.py`'s own
  tick cadence at all. `desired()` now treats any device in that scope as
  "no action yet" (never guessed ON) until `mode_off_devices()` itself
  claims it. Same fix covers the TV strip's own "lend" branch: when the
  mode's plan is off AND the strip isn't actually confirmed receiving
  Hyperion's own realtime stream (`house_fixtures._hyperion_streaming`,
  cached from `live_host.live.read_emission(..., read_state=False).live`,
  refreshed at most every `HYPERION_CHECK_S` — never a live read inside
  `desired()` itself, which must stay off the event loop), it is switched
  off like any other mode-off fixture instead of staying "lent" on the
  strength of "TV Music is off" alone. His "TV Music default on, off only
  for Hyperion" preference is otherwise unchanged. Spec:
  `tests/test_house_fixtures.py` (the Hyperion-gated lend, both ways, and
  the never-guess-on race for a fixture that was off AND one that was on).
- **`POST /ownership/handover` can answer `wait: false`** (default `true`
  — the exact old blocking shape every caller before this field existed,
  including the Spectra UI's own "Take back" button, keeps getting):
  Home Assistant's own `rest_command` client timeout outran a slow
  activation (two unreachable sconces each retried before the take
  committed partial, ~50 s in the field) and reported the call failed
  even though it landed moments later — confirmed from the journal: no
  exception on Spectra's side, no completed access-log line for the
  request at all, just the handler still running when HA's own client
  gave up. `wait: false` still runs every CHEAP, inline check inline
  (armed, already-owner 409, the readiness gate's 412 — via
  `handover.readiness_refusal()`, the message `run_handover` itself now
  calls too, so there is one definition of it) and only forks the SLOW
  part (pretake ping, quiesce, activate, verify, commit —
  `handover.run_handover` itself, completely unchanged) to a referenced
  background task; a poller reads `GET /ownership` (its `handover` block
  while in flight, then `owner`/`activation` once it lands) for the
  outcome. Spec: `tests/test_handover.py` ("proof 9").

**A DUPLICATE DEVICE ROW IS A SECOND WRITER, AND THIS SEAM CANNOT SEE IT
(sconce-flicker-tv-mode, 2026-10-07, the Admiral: "The two sconces keep
turning on while I'm watching TV").** His kitchen left sconce existed
TWICE in `fx-live/config.json` (same MAC, one row backing a virtual and
obeying TV mode's own off list, the stray duplicate backing nothing and
falling into `desired()`'s own default-everything-ON fallback) — the two
rows fought every 60 s drift check, and the right sconce followed the
left one's power-on over its WLED UDP sync group. `device_usage.py`
already named the duplicate (`duplicate_of`), but `desired()` never
consulted it. `house_fixtures._duplicate_ignore_map` (its own docstring is
the binding statement) now skips — never writes, withholds, or drift-
checks — any in-scope row whose hardware_id matches another in-scope row
that backs a virtual, or that `device_usage` flags `duplicate_of`; virtual
membership always outranks merely being named in a mode's plan, so an
interim mode edit naming the duplicate too (as this incident's own
same-night workaround did) changes nothing — the duplicate stays skipped
under every mode. Logged once per (duplicate, winner) pair, not every
tick. Spec: `tests/test_house_fixtures.py` §11.

**THE ROOM MAP VIEW (Devices → Live → Room map; 2026-10-06, phase 3 of the
same plan).** `spectra/services/room_view.py`'s docstring is the binding
statement (server); `spectra/web/src/live/roomMap.ts`'s is the client's. Six
things:

- **ONE CAMERA POSE AT A TIME, and a pose is a `capture.pose_id`, not a room
  entry.** His kiosk pose spans three room entries (Living Room, the crystal,
  the dining table) and they are drawn together; two pose ids never are.
  Every position is a place in that camera's picture (0..1), never a room
  coordinate and never where an LED is — a marker sits at the centre of its
  LIGHT (`room_view.light_core`). The light-field model's fence is unchanged;
  this view only reads it.
- **IT READS `room_maps.json` AND `commissioning.json` AND WRITES NEITHER.**
  Its one store is `config.ROOM_VIEW_FILE` (hand placements per pose, `PUT
  /api/room-view/placements/{pose}`, a partial merge where null removes).
  `tests/test_room_view.py` holds that by bytes and mtime.
- **THERE IS NO STILL OF THE ROOM, by the capture path's own rule** (numbers,
  never images). The backdrop is every footprint of the pose added up.
- **STORED COMMISSIONING DECODES HAD NO POSITIONS** until this build:
  `gray_code.Decode.as_dict` now keeps `positions` for seen indices. The view
  draws a decode only when its own judged table is `pass`/`findings` AND it
  was taken at the pose on screen — a `fail` decodes confidently to wrong
  places. With his data today no decode qualifies, so the sconces are placed
  from their block footprints.
- **`room_view.register_source` is where another per-pixel map plugs in**
  (positions in the pose's picture, per fixture pixel); the decode is the
  first source. Authority per pixel: his hand, a per-pixel source, a
  footprint, the "not placed" tray.
- **THE GLOW IS SUMMED ON THE CPU into one 64x36 texture and drawn with one
  quad** (`stage.ts`), so its cost does not grow with the canvas or the
  emitter count; every fixture pixel stays in the plan (size 0 when not
  placed) because an emitter's glow is tinted by all the pixels it lit. Gate:
  `--systems spectra+proxy:live:map,spectra+proxy:live:map:phone
  --pass-drawn-fps 59` (the rig's synthetic pose, 74 emitters;
  `spectra_rig.py --room --room-maps <copy>` shows a real one).
  Specs: `tests/test_room_view.py`, `node scripts/check_live_view.mjs` (FOUR).

**Sonic reach, read only (2026-10-06)**: `room_effect_console.
list_room_map(pose?)` lists camera poses and, for one pose, which pieces
are placed (by a measured footprint, a per-pixel camera read, or his own
hand) and which are still in the tray — never the glow/backdrop image
data. Hand placement itself stays a drag on the camera picture; there is
no write op.

