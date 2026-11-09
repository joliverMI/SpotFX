# Room light-field mapping and commissioning

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## The room LIGHT-FIELD map (`/rooms`) + room effects (`/room-effects`)

**THE ONE IDEA, his own sentence, and the thing this whole area exists to
protect: the map records WHERE EACH EMITTER'S LIGHT LANDS AND HOW MUCH — a
measured light field — NEVER where the LEDs are.** `spectra/models/
room_map.py`'s docstring is the binding statement. There are no coordinates,
no metres and no room drawing anywhere in this feature, deliberately: a
sconce's spill onto the ceiling and the floor is captured for free by
photographing what it lights, and a fixture-position model would throw
exactly that away. If a change here starts solving for where a strip
physically is, it has left the plan (`/home/javi/fleet-spotfx/.lavish/
room-light-field-plan.html`, §1's own exclusion fence).

Modules, each with a job: `light_field.py` (derivation + store +
`per_emitter_scalar`), `light_field_fields.py` (the four field kinds),
`emitters.py` (WHAT counts as an emitter, at the granularity chosen for one
run), `mapping_session.py` (the phone's server half), `room_mapping.py` (the
protocol as a held-room program), `room_effects.py` (the bounded writer).

**MEMBERSHIP AND PARTICIPATION ARE TWO DIFFERENT ACTS (2026-09-23, PR
fm/rooms-carrier-membership-controls — the carrier-keyed rebuild of the
device-keyed fm/room-member-removal, superseded when `RoomMap` was re-keyed
by carrier; his ask stands unchanged: "just add a delete button next to the
listed devices as well as the ability to deselect a device").** Removing a
carrier from a room edits THAT ROOM's `carrier_ids` and takes its
footprints with it (a footprint measures what a carrier does in THIS room)
— it is never a device delete, and the Devices page still deliberately has
none; the control is labelled "Remove from room" in full for exactly that
reason. Deselecting keeps the carrier in the room with everything it has
measured and sits it out: `RoomMap.deselected_carrier_ids` (additive, empty
default, kept a strict SUBSET of `carrier_ids` by both `remove_carrier` and
the room upsert), read through `RoomMap.selected_carrier_ids()` at the two
automatic consumers — `room_mapping.resolve_plan`'s enumeration (so a run
neither lights it nor overwrites its footprint) and `room_effects.
resolve_driven`'s pool. **The two selection LAYERS compose in one
direction, stated so they cannot disagree: the room decides what is
OFFERED and wins outright — a deselected carrier is not driven even by an
effect whose own `carrier_ids` name it — and Room Effects' per-effect chips
choose among what the room offers.** An all-deselected room refuses a run
and refuses an effect start BY NAME rather than reporting an empty
success. Wire: `DELETE /api/rooms/{id}/carriers/{carrier_id}` and
`POST /api/rooms/{id}/carriers/{carrier_id}/selected`; `RoomBody.
deselected_carrier_ids` is OPTIONAL and omitting it leaves participation
alone (the page saves a room for a dozen unrelated reasons and none may
re-select a carrier he sat out). Help topic `room-members` (linked from
the Rooms page's Emitters section). Spec: `tests/test_room_membership.py`.
Deliberately NOT touched: `exposure_test.py`/`lever_selftest.py`/
`pose_fingerprint.py` each pick ONE emitter from `room.carrier_ids` for an
explicit, human-pressed diagnostic — the same "an explicit press still
works" precedent as Force Scene, not an automatic pool this gate applies to.

**AN EMITTER IS A CARRIER *OR* A PIXEL RANGE OF ONE (2026-08-31, PRs
fm/lightfield-segment-granularity then fm/rooms-picker-light-emitters),
his own correction: "A single device that spans the direction of the wave
should be able to show the effect. the tv mapper is wrapped around a tv. It
should be able to run a dimness wave vertically."** The first slice fenced
an emitter to a whole device, so a wave over a strip wrapped round a
television could only dim the whole television at once.
`spectra/services/emitters.py` is the binding statement for the enumeration
and the id shape. Five things to know:

- **A ROOM IS KEYED BY CARRIER, NOT BY DEVICE**, on his own clarification:
  "i want to be able to work with the devices that i directly use in
  spectra even if they have layers of virtuals before shining... spectra
  can delayer it if easier." A CARRIER is a genuinely-driven virtual
  (`room_topology.genuinely_driven_virtual_ids`) whose segment chain
  reaches at least one light-emitting fixture; `spectra/services/
  carriers.py` is the binding statement. Four of his seven fan out to
  several fixtures (tv-mapper → backlight + both sconces), so a
  device-keyed picker could not name what he calibrates. The chain was
  ALREADY resolved everywhere it mattered — the capture lamp writes to
  virtuals and the gain mask is per-virtual — so this re-key made the list
  agree with the layer beneath it rather than adding a delayering step.
  **The /devices page is untouched**: `device_usage.in_use` answers "does
  this back something driven", a different question, and still lists every
  fixture including the dummies. `emitters.emits_light` is the chain-level
  sub-check and the ONE place a new non-physical type joins the decision.
- **GRANULARITY IS A PER-CAPTURE CHOICE, never a global.** `auto` (default,
  resolved PER CARRIER: `segment` for a strip, `whole` for an all-Hue
  chain) / `whole` (`device` is accepted as the pre-carrier wire word) /
  `segment` (the carrier's own configured segments) / `block`-of-N pixels,
  all in the CARRIER's own effect-pixel space. The Rooms page passes it to
  `POST /rooms/{id}/map`; `GET /rooms/{id}/plan` is the read that says how
  many emitters and how many dark seconds BEFORE he presses.
- **A sub-carrier emitter id is `tv-mapper:blk3[90-119]`** (or `seg`) — the
  NEW ID SHAPE `room_map.py`'s docstring always anticipated — plus a
  STRUCTURED `EmitterFootprint.ranges` and `carrier_id`. Use
  `RoomMap.mapped_carriers()` (not `mapped_ids()`) wherever a CARRIER is
  what a caller selects — `mapped_ids()` returns EMITTER ids, and
  conflating the two silently rejects every legitimate selection (a real
  bug this found in `room_effect_console`). A pre-re-key room on disk
  (`device_ids`) is RESET by `RoomMap`'s own before-validator with a stated
  `migration_note`, never reinterpreted: a device id is not a carrier id
  and a per-device footprint is not a carrier's.
- **"AUTO" GIVES A SINGLE-SEGMENT STRIP *BLOCKS*, and a one-piece map
  WARNS** (2026-08-31, third commit of PR fm/rooms-picker-light-emitters,
  from his own first real run). "Segments for a strip" collapses to ONE
  emitter whenever the strip is configured as a single segment — which his
  TV wrap is — i.e. exactly the outcome this whole feature exists to avoid.
  `emitters.resolve_granularity` now resolves a splittable, multi-pixel
  carrier with `usable_segments(...) < 2` to `block`; an explicit choice is
  still never overridden. Independently, any plan or run yielding one
  emitter for a multi-pixel carrier carries `warnings` (Plan AND
  MappingResult, both on the wire) saying the map cannot show a wave
  travelling and how many pieces Blocks would give —
  `mapping_refusals.one_piece_warning`. A WARNING is not a refusal: the run
  happens and the map is worth keeping, which is why they are separate
  lists.
- **A COPY-MAPPED CARRIER IS NOT A WAVE SURFACE, and the run maps THROUGH
  the fixture's own strip** (2026-08-31, fourth commit of PR
  fm/rooms-picker-light-emitters, from his second failed run). MEASURED
  FIRST, on rendered device pixels: the per-pixel gain mask multiplies the
  effect buffer BEFORE a copy-mapped virtual expands it into each segment,
  so a wave's phase is identical in every segment at every instant —
  `scripts/check_copy_carrier_wave.py`, and do not re-reason this from the
  source. His `tv-mapper` is copy-mapped in front of `tv-backlight` (560 px,
  span, INACTIVE), so `emitters.substitutes_for` prefers the splittable
  DIRECT virtual, footprints keep the carrier's own name, and the SAME
  substitution happens at both ends (capture and wave) for the same reason.
  `room_mapping.activate_for_capture` brings an idle substitute up and puts
  it back; the hold snapshot covers the EFFECT but never an `active` flag it
  did not observe, so the flag is the run's own to restore
  (`tests/test_capture_activation.py` reads it back). `room_effects.start`
  does the same and `stop()` puts it back AFTER the hold's revert.
- **BRINGING A SUBSTITUTE UP TAKES THE CARRIER OFF THE AIR, and the capture
  owes BOTH halves back** (2026-09-06, PR fm/spectra-fix-carrier-activation,
  from his first real sconce commission). `fx/devices/__init__.py::
  Device.add_segments_batch` deactivates every EXTERNAL virtual streaming to
  a device whose own device-virtual activates — so lighting `tv-backlight`
  for one block took the copy-mapped `tv-mapper` off the air, and putting
  the substitute back to sleep did not bring the carrier back. It was left
  HOLDING ITS EFFECT WITH NO RENDER THREAD: liveness `healthy=False` with
  `activation_gaps {tv-mapper}`, .236 stuck on a static frame, and a lever
  self-test reporting "no carrier of this room is rendering", while every
  write to it landed on nothing. **The activation reconciler cannot cover
  this** — it re-inits dark DEVICES, not an inactive VIRTUAL — so the
  restore belongs to the capture path that displaced it.
  `activate_for_capture` now returns a `CaptureActivation` (scope /
  activated / failed / **displaced**) and `deactivate_after_capture` takes
  that WHOLE RECORD and returns a `CaptureRestore` (`left_on` /
  `not_restored`, two different changes to his room, two sentences —
  `mapping_refusals.carrier_not_restored`). Four things not to undo: the
  record is deliberately NOT tuple-unpackable, because the old three-value
  return is exactly how a call site kept `activated` alone and lost the
  other half on every path at once; displacement is **MEASURED** (what was
  rendering, read before and after the activation, minus what this run
  deliberately brought up) and never inferred from the device layer's
  rules, with a failed read claiming NOTHING; the substitute is put to
  sleep BEFORE the carrier goes back on, or the same exclusion rule fires
  in the other direction; and the restore is `deps.reactivate` — the FLAG
  ALONE (`fx_seam.set_virtual_active(vid, True)`), never `deps.activate`,
  which writes the run's black lamp first and would destroy the effect the
  hold's revert just put back. All five capture paths (map, commissioning,
  exposure comparison, pose fingerprint, lever self-test) inherit it from
  the one seam.
- **AND THE HALF THAT WAS FOUND BY BUILDING THAT PROOF: A DISPLACED
  VIRTUAL LEAVES THE WRITE SCOPE FOR THE REST OF THE RUN** (same PR), and
  it is MEASURED, not tidiness. A displaced carrier still HOLDS an effect,
  so the capture's own black write to it takes `fx/facade.py`'s repair
  branch (`_verify_effect_took`, deviation #29), which ACTIVATES it to make
  that write real — and that hands the device straight back, knocking the
  substitute off the air. The two then trade the device on every write, and
  with the carrier's black write last in the payload THE LAMP IS INACTIVE
  WHEN THE CAMERA LOOKS: measured on the real pipeline, the device reads
  `max=0.0` / 0 lit pixels on every step of every pass — a run that maps
  nothing and cannot say why. `CaptureActivation.scope` is therefore
  `(live | activated) - displaced`, which is what makes the substitute's
  own lamp the only thing driving that device for the whole run. It also
  makes the restore self-contained rather than depending on that repair
  firing. Keep it out of scope; do not "complete" the dark step by putting
  it back in.
  Proof for both halves, on a real `fx.headless` host with real render
  threads: `tests/test_capture_carrier_restore.py` — active, a live thread
  AND fresh `VIRTUAL_UPDATE` frames after the restore, plus the real
  `MappingProgram` payloads driven through the real write seam over two
  emitter passes with the DEVICE's own buffer measured. Both verified RED
  against the pre-fix code (`active=False`, effect held, 0 frames; and the
  lamp's virtual off the air during the dark step). That file's own header
  says why its teardown is explicit: it is the only headless test in the
  suite that spawns real render threads (`headless.attach_effect`
  deliberately skips them), and a virtual left rendering is a non-daemon
  thread that hangs the interpreter at exit.
- **A TRANSIENT ACTIVATION IS STORED INACTIVE, or an INTERRUPTED run
  strands the carrier on the next load** (2026-09-08, PR
  fm/spectra-commission-leaves-carrier-inactive; `fx/VENDOR.md` #37 is the
  binding statement). The LIVE restore above (#257) was already right; the
  gap was ON DISK: a capture or a Dim Wave brings the copy-target
  device-virtuals (`tv-backlight`, the kitchen sconces) up for its own
  duration, and a run interrupted before its own deactivate left them
  stored ACTIVATABLE — `active: true`, or a black lamp beside NO `active`
  key, which the loader reads as active. On the next config load they
  evict the copy-mapped `tv-mapper` (deviation #29's eviction; his sconces
  load AFTER it, so order decides), the Living Room has zero active
  carriers, and the take rolls back to `released`. The fix lives in TWO
  places: `fx/facade.py::_virtual_put_active`'s `persist` flag
  (`fx_seam.set_virtual_active(vid, True, persist=False)` raises the flag
  live and STORES an explicit `active: false`) and
  `room_mapping.transient_activate`, the ONE helper both doors —
  `room_mapping.production_deps().activate` (capture) and
  `room_effects.production_deps().activate` (room effects) — delegate to.
  Its docstring owns the three-write ORDER; VENDOR.md #37 owns why the
  false is explicit rather than a skipped write. One-time catch-up for a
  config already carrying either residue shape:
  `scripts/repair_copy_carrier_active_flags.py` (dry-run default,
  `--apply`). Two traps: a test double for `fx_seam.set_virtual_active`
  must accept the `persist` keyword (`scripts/check_capture_queue_e2e.py`,
  `scripts/check_lever_selftest.py`) — `activate_for_capture` swallows a
  `TypeError` from the double into `failed`, hollowing out the substitute
  path of a proof that still reads green; and a repro that loads the
  carrier LAST hides the residue by letting it win on order. DEFERRED,
  filed as `spectra-stale-hold-recovery-reevicts-carrier`:
  `flare_preview_hold`'s restart recovery replays a mid-run hold snapshot
  and re-evicts the carrier LIVE for that process life — pre-existing,
  live-only, exposed by this fix rather than caused by it. Spec:
  `tests/test_capture_active_flag_not_persisted.py`,
  `tests/test_repair_copy_carrier_active_flags.py`.
- **AN EMITTER THE CAMERA NEVER SAW IS A RECORD, NOT AN ABSENCE** (2026-08-31,
  PR fm/mapping-unseen-emitter-note). His first real map ran 22 emitters and
  stored 14; the missing 8 (far-side TV blocks, sconce spill outside the
  frame) produced ~zero lit-minus-dark and simply did not appear in
  `room_maps.json` — correct physics, silent record, with nothing to
  separate "never ran" from "ran, and not in shot". A capture landing under
  `light_field.UNSEEN_WEIGHT` is now STORED footprint-less
  (`EmitterFootprint.unseen`/`note`, empty `grid`/`axis_profile`, so every
  reader already gating on `mapped` skips it exactly as it skipped the
  absence), reported on `MappingResult` (`unseen`, `unseen_count`,
  `summary` — "14 mapped, 8 unseen from this pose"), carried on the room's
  API payload (`unseen`/`note` per footprint, `unseen_ids`) and rendered as
  such by the Rooms page. **The wording is a FACT, not a warning**
  (`mapping_refusals.unseen_note`): a second pose can see the piece later,
  so nothing about it reads as an error and no retry machinery exists.
  SECONDARY HARDENING, never the fix: an emitter measuring ~zero gets ONE
  automatic re-capture later in the same run with a `RETRY_DARK_SETTLE_X`
  (3x) dark settle, and the note then distinguishes the two findings. It was
  built when a neighbour's fade contaminating the next dark reference was
  the leading hypothesis; that was RETIRED in favour of the firmware
  brightness above, and the retry ships as cheap insurance against a
  genuinely contaminated reference, not as an explanation of anything.
  `dark_settle_s`/`lit_settle_s` are per-run, bounded body params
  (`clamp_settle`) — groundwork for quality levels, defaults unchanged.
  Spec: `tests/test_mapping_unseen_emitter.py`.
- **A MAP TAKEN AT 10% FIRMWARE BRIGHTNESS MEASURES THE DIMMER, NOT THE ROOM**
  (2026-08-31, PR fm/mapping-unseen-emitter-note; the captain's verdict on
  his first real map). Every footprint in it came out ~10x dim — five blocks
  at 0.1 or less, i.e. the unseen threshold's own tail — because his fixture
  sat at ten percent FIRMWARE brightness (WLED's `bri`, which scales
  everything the fixture emits including a realtime stream) for the whole
  run, and nothing said so. **`spectra/services/fixture_brightness.py` is
  the binding statement.** SINCE 2026-10-12 IT NEVER WRITES (the
  Admiral's D1a: a WLED's brightness is Home Assistant's): the PLAN reads
  it and warns loudly BEFORE the cost, naming Home Assistant as where to
  raise it (`mapping_refusals.one_piece_warning`'s own discipline); the
  CAPTURE measures AS IS (`fixture_brightness.measured_as_is`, writes
  nothing) and its notes name every fixture captured below full; a NIGHT
  run records "raise X to 100% in Home Assistant" in its `brightness`
  block for the morning read. Until then the capture took each fixture to
  full and put his level back (`owned()`, and the 2026-09-06 restore
  hardening around it — both retired with `WLED.set_brightness`, VENDOR
  #78). A non-WLED fixture is `not_applicable` and a fixture that would
  not answer is `unreadable`; NEITHER is ever given a fabricated 255,
  because a made-up full reading makes an unguarded fixture look guarded.
  Spec: `tests/test_fixture_brightness.py`, `scripts/check_fixture_brightness.py`.
- **A CONTROL WRITE THAT MUST LAND NEEDS A BUDGET THAT BINDS, AND A
  READ-BACK** (2026-09-06, the sconce commissioning, where a single 0.5 s
  restore write left .236 at full). The brightness restore it hardened is
  gone (above), but both lessons still govern every control write here:
  **0.5 s is a DISCOVERY budget, not a control-write one** — a controller
  saturating under its own stream needs `fx.utils.WLED_BRIGHTNESS_TIMEOUT_S`
  (3.0, VENDOR #34, which `get_brightness` and house_fixtures' power writes
  still use) — and **a 2xx is not proof**: confirm by reading back, retry
  bounded and spaced, and keep "accepted but unconfirmed" a different,
  softer sentence from "never accepted".
- **A NORMALISED THUMBNAIL IS BLIND TO THE MAGNITUDE IT NORMALISED AWAY.**
  `light_field.thumbnail` scales each footprint to its OWN peak, so one
  holding a hundredth of its neighbour's light draws an equally convincing
  shape — which is how a whole 10%-brightness map looked fine. A thumbnail
  is therefore NEVER shown without its weight beside it, and
  `light_field.faint_ids` names the footprints under `FAINT_FRACTION` (5%)
  of the strongest in the SAME room. A FRACTION, not an absolute number:
  a footprint is relative luminance in one camera's scale, and the only
  comparison the model permits is within one pose.
- **THE DEVICE LAYER OVERWRITES, IT NEVER BLENDS** — established
  2026-08-31 when a second active virtual on one fixture was suspected of
  attenuating a substituted capture. `fx/devices/__init__.py`'s
  `Device.update_pixels` scatters every active virtual's segments into ONE
  shared `self._pixels` with no alpha or priority, and `assemble_frame`
  returns it unchanged (its own docstring says merging "will eventually" be
  handled). So overlapping writes are LAST WRITE WINS between the
  per-virtual render threads (`fx/virtuals.py::Virtual.activate`) —
  order-dependent, full-or-nothing, and therefore incapable of producing a
  steady fractional dimming. That ruled it out as the dim-map cause; it is
  still a real property worth knowing before lighting one virtual while a
  neighbour covers the same pixels. Proof:
  `tests/test_device_output_composition.py`.
- **A REASON THAT NEVER REACHES A HUMAN IS A SILENT FAILURE — worse, it
  lets us believe we handled the case** (the captain's ruling, same
  commit). `Emitter.note` was written correctly and died in the
  whole-granularity branch. Everything on this path that WRITES a reason now
  leaves for the page: notes → `problems`, a failed activation, a virtual
  left rendering, an unreadable device list (which silently disables the
  emits-light backstop), the substitution itself → `notes`, and the mask
  engine's `skipped_length_mismatch` (a virtual silently not driven) is
  rendered on the room-effects page. Before adding a `reason=`/`note=`
  anywhere here, name the surface it reaches, or do not write it.
- **A RANGE IS AN ADDRESSING FACT, NOT A POSITION** — indices into the
  virtual's own EFFECT pixel space, read out of the segment configuration,
  the same kind of fact `virtual_ids` already was. That is the SAME space
  `fx/effects/pixelRange.py` lights during capture and
  `fx/virtual_gain_mask.py`'s mask indexes at render, so the two address the
  identical pixels with nothing to convert. The map still records where
  light LANDS and nothing else; if a change here starts storing where a
  segment IS, stop.
- **Sub-device capture AND a sub-device wave both need SPECTRA to own the
  lights** — the range lamp is a vendored effect in this process and the
  mask is applied in this process's own frame assembly, so neither reaches
  an external LedFX. Both refuse BY NAME with nothing written. Whole-device
  work is unaffected either way. Re-mapping a carrier drops its previous
  footprints first (`RoomMap.drop_carrier_footprints`), so it carries
  exactly one granularity and is never driven twice.

- **EVERY EXPECTED CONDITION ON THIS PATH IS A SENTENCE, NOT A 500**
  (2026-08-31, second commit of PR fm/rooms-picker-light-emitters). His
  first real run raised `fx_seam.RoomReleased` out of
  `room_mapping.live_virtual_ids` and reached him as a bare 500 with a
  stack trace — for a state the ownership bar fixes in one press.
  `spectra/services/mapping_refusals.py` is the one wording per condition
  (released / handover / mid-run loss / hold ceiling / a dead fixture), so
  the route, the run and the page cannot describe his room differently.
  Matched on the exception CLASS, never message text. **A genuine bug still
  raises** — a sentence invented for one would be a lie. A mid-run
  ownership loss ends the run as a stated PARTIAL (`refusal`/`partial` on
  the result) that KEEPS what it measured, and the refused revert write in
  the `finally` is swallowed so the partial cannot turn back into a 500.
  Spec: `tests/test_mapping_refusals.py`. If you add a seam to this path,
  give its expected conditions a sentence there or confirm one exists —
  the exposure lock's own named refusal is the bar.
- **THE EXPOSURE LOCK IS A HARD REFUSAL, not a warning, and it is the whole
  instrument's honesty.** A footprint is `lit − dark` in the camera's own
  byte scale and every footprint in a room is compared against every other
  one; if auto-exposure re-scales between the dark reference and the lit
  capture, every comparison is wrong by an unknown factor and NOTHING
  downstream can detect it — the grids still look like plausible
  footprints. So a run cannot start unless the browser CONFIRMED both
  exposure and white balance locked (what `getSettings()` returned, never
  what the page asked for), a lock lost mid-run aborts by name, and the
  refusal names the phone and the capability. `mapping_session.lock_refusal`
  is the ONE wording, so the run gate, the mid-run abort and the status
  surface can never disagree.
- **NO AUDIO BY CONSTRUCTION, not by a flag** (his own requirement). This is
  a SECOND session type rather than a mode on `av_sync_session.Session` —
  that class opens an `AudioReference` in its own `open()`. There is no
  audio code here to switch off; `tests/test_mapping_session.py` asserts the
  module body contains none. It DOES reuse `av_sync_session.FrameRing` and
  `ClockMap` by import (the vision seam built naming this stage as its
  consumer), and speaks the same WS message shapes.
- **Pixels are `image/grey8`, never JPEG** — a lossy codec's quantisation
  lands in the difference this instrument measures, and decoding one would
  put an image library in a path that needs none. 320x180 divides the stored
  64x36 grid exactly (5x5 box mean, no interpolation to explain).
- **A mapping run is ONE CONTINUOUS DARK HOLD for the whole capture
  sequence** on `flare_preview_hold.open_program_hold` — snapshot,
  deadline, sweep, ceiling and restart recovery all INHERITED, never a
  second hold system. The dark step covers EVERY live virtual, because
  that is what "the room is dark" means to a camera.
  **It was a CHAIN of short per-emitter holds until 2026-08-31 (PR
  fm/mapping-one-dark-hold) — do not restore that out of loyalty to its
  reasoning.** The chain existed to stay inside `MAX_HOLD_DURATION_S`
  (3 min) and did give a genuinely-restored room between emitters, but the
  owner watched a 22-emitter run and said "just stay dark between tests":
  his show flooded back through the fixtures 22 times, and every dark
  reference after the first was taken moments after a restore, so the show
  fading back out landed IN the dark frame and subtracted the next
  emitter's own light away. **That contamination path is now closed by
  construction** — between two captures the room has been dark all along,
  so `DARK_SETTLE_S` only has to outlast the PREVIOUS EMITTER's own fade,
  which is what it was always for. Restorable-at-any-instant was never the
  chain's property, it is the HOLD's (his Stop, heartbeat lapse, sweep,
  restart recovery all unchanged); what changed is that STOPPING IS HIS
  ACT. `room_mapping.py`'s module docstring is the binding statement.
  Two things ride with it:
  - **THE CEILING IS PER SESSION NOW.** `MAX_HOLD_DURATION_S` is untouched
    and still governs every preview; a session may declare its own on the
    hold's FIRST open (`open_program_hold(max_duration_s=...)`, read once,
    never raisable later), and `flare_preview_hold.session_ceiling_at()` is
    the ONE place anything reads which number a session is held to. A run's
    is `room_mapping.run_ceiling_s(estimate)` — margin ×1.5, floor 180 s
    (= the preview's own), hard cap 900 s — computed at PLAN time, carried
    on the plan response (`hold_ceiling_seconds`) beside the emitter count,
    and handed to the hold so the number he was shown is the one enforced.
    A plan past the hard cap REFUSES by name (`too_long`), never truncates,
    and **never adjusts his granularity/block_pixels to make itself fit** —
    those are his decisions and the plan line's job is to price them.
  - **ALL FOUR protocol waits are bounded per-run params** on
    `POST /rooms/{id}/map` (`dark_settle_s`/`lit_settle_s` plus
    `dark_capture_s`/`lit_capture_s`, added for the overnight speed sweep).
    At the phone's fixed ~5 fps, **lit dwell and frames-averaged are ONE
    knob, not two** — `lit_capture_s` buys frames at ~5/s and nothing else,
    with `MIN_FRAMES=2` the floor — so a sweep must not count them as
    independent variables. `run_estimate_s` is the ONE pricing function
    (the plan quotes it at the shipped defaults; the run re-prices with its
    own four values before deriving the ceiling).
- **THE PER-PIXEL GAIN MASK is `fx/virtual_gain_mask.py` + ONE multiply in
  `Virtual.assemble_frame`** (`fx/VENDOR.md` deviation #25), right after the
  two the fork already does — the layer the driver reads AND the layer the
  device preview taps. Pushed, never pulled (`fx/` may not import
  `spectra/`), and general by construction: a float array per virtual, which
  is what implode/explode will need too, not a wave-shaped thing. With no
  mask installed anywhere — a room with no sub-device emitters driven, and
  every room before this feature — `mask_for()` short-circuits on an empty
  dict and the branch is never reached: byte-identical, asserted in
  `scripts/check_room_effect_mask.py`. A wrong-length mask is SKIPPED and
  counted, never resampled. `room_effects.compute_gains` returns
  `(scalar_gains, masks)`: a masked virtual gets NO brightness write and NO
  `compose()` scaling (the mask multiplies a frame that already carries the
  show's brightness — scaling the write too would square it) and NO watchdog
  holder (nothing it moves is in the effect config). `_release_masks()` runs
  BEFORE the hold closes, same load-bearing ordering as `running = False`.
- **`per_emitter_scalar(field_fn)` is the effect interface, and it serves
  FOUR kinds from day one** (his instruction) — `gain = Σ w·field / Σ w`
  over the emitter's own footprint cells. Only Dim Wave drives lights;
  hue rotation / implode / explode exist as pure fields with tests and
  nothing that writes. **That is WHY the full 64x36 grid is stored and not
  just the axis profile**: the two radial kinds read x/y, and
  `tests/test_light_field.py` has a test that cannot pass against a 1-D map.
  A broad emitter AVERAGES the field over everything it lights — the
  softness is physics falling out of the measurement, not a smoothing hack.
- **A room effect COMPOSES, it never replaces.** `room_effects.compose()` is
  called from inside `fx_seam.apply_writes` (the one write seam) and returns
  the caller's own dict object when nothing is running, so the seam's normal
  path is byte-identical to before the feature existed. The ticker's own
  writes carry `room_effect: True` so they are never scaled twice.
  `stop()` clears `running` BEFORE closing the hold — order is load-bearing,
  or the hold's revert write would be scaled by the gain and hand the room
  back dimmed.
- **A ROOM EFFECT STANDS IN FOR THE CARRIER IT DISPLACES, and gives it
  back (2026-10-04, D2).** Bringing a substitute strip up takes the
  copy-mapped carrier off the air (the same exclusion the capture path
  restores). `room_effects.start` MEASURES what stopped rendering
  (`_state.displaced`), writes the carrier's own effect onto the
  substitutes so the wave modulates the show (not the black lamp), and
  while displaced `fx_seam`/`FacadeExecutor` REDIRECT show writes addressed
  to the carrier onto the substitutes (`room_effects.redirect_targets`) —
  writing the carrier would take #29's repair and evict them. `stop()`
  (`_hand_back`) sleeps the substitutes, puts the carrier back with the flag
  alone, then re-lands the newest redirected show state on it. A substitute
  whose fixture the activation report lists dark is never brought up. Spec:
  `tests/test_room_effect_carrier_restore.py`.
- **Holder 4 on the param watchdog** (`Deps.room_effect_holds`): per (virtual,
  "brightness") KEY, never a global stand-down. Today `_production_gate()`
  already skips the whole sweep while any hold is active, so this is
  belt-and-braces in production — it is proven against a deliberately-open
  gate, which is the shape a narrowed gate would take.
- **Measured, not assumed** (the plan's own named risk): one tick's whole
  seam call for two virtuals costs p50 ~11.6 ms / p95 ~15.5 ms in-process,
  at an achieved 14.99 Hz of a 15 Hz target — `scripts/check_room_effect_wave.py`
  reports it from the instrument. **Finer granularity is CHEAPER, not
  dearer**: a masked virtual needs no seam write at all, so a twenty-range
  TV wrap measures p50 ~0.01 ms / p95 ~0.02 ms and 0 writes/s against the
  same 66.7 ms tick (`scripts/check_room_effect_mask.py` §5). Twenty
  emitters also resolve into ONE mask, so the render sees one multiply
  however fine it gets.
- **The honest bound, stated rather than hidden**: a running room effect
  cannot outlive the hold's 3-minute ceiling. Right for a slice whose whole
  safety story is that seam; "leave the wave on all evening" needs its own
  lifetime story, not a bigger number.
- Sonic parity is `room_effect_console.py` (5 ops, `domain="room"` —
  `list_room_map` read-only since 2026-10-06, see the room-map bullet
  below). Its `carrier_ids` name CARRIERS, not fixtures.
  Excluded BY NAME with reasons in its docstring: starting/stopping an
  effect (a light-driving call — `settings_agent.py`'s whole boundary
  argument is that none exists), running a mapping sync (needs a phone in
  someone's hand) and with it the GRANULARITY that run uses (an argument to
  that same act, not a setting anything reads later — how finely each device
  HAS been mapped IS reported by `list_rooms`), the axis calibration (two
  taps, a visual act — `force_scene_*`'s own precedent), creating/deleting a
  ROOM.
- Proofs: `scripts/check_light_field.py` (a fake emitter painting a known
  region must yield that region's grid, cell by cell, on top of a
  deliberately non-black dark room; ONE snapshot and ONE restore for N
  emitters, with nothing handed back mid-run — §2 was rewritten to go RED
  against the per-emitter chain it replaced; five negative controls),
  `tests/test_mapping_one_dark_hold.py` (the same bar in pytest, plus the
  run-scoped ceiling, the plan-time too-long refusal, and the stop/abandon
  paths), `scripts/check_room_effect_wave.py` (the wave on the
  REAL render pipeline through `fx.headless` — measured phase lag between
  two emitters at different axis positions matched the wave's own travel to
  0.0°, with depth-0 and speed-0 negative controls), `scripts/
  check_mapping_capture_e2e.py` (the whole session over a real uvicorn
  server and a real WebSocket), `scripts/check_light_field_granularity.py`
  (the range lamp on the real pipeline; a synthetic three-segment TV wrap
  captured at segment granularity yielding three footprints, each equal
  cell-for-cell to its own segment's painted region and pairwise DISJOINT,
  with device granularity's single merged footprint as the negative
  control), `scripts/check_room_effect_mask.py` (a vertical wave along ONE
  wrapped device, phase lag between its bottom and top pixel ranges measured
  off `assemble_frame()`, plus the depth-0/speed-0 and no-mask
  bit-identity controls). All five run as subprocesses from
  `tests/test_light_field_checks.py` — **never import one into pytest**: each
  repoints `spectra.config`'s store paths, `device_model.CATEGORIES_FILE`,
  `fx.light_ownership.OWNERSHIP_FILE` (to "spectra owns") and the `fx_seam`
  primitives, and leaking that into a shared interpreter is exactly how
  another test starts passing or failing for a reason nobody can find.

## The COMMISSIONING ground-truth test (`POST /api/rooms/{id}/commission`)

The plan's §8 (`/home/javi/fleet-spotfx/.lavish/room-light-field-plan.html`),
built 2026-08-31. Gray-code his stored `tv-mapper` composition, decode where
every pixel is, and judge a comparison **frozen in the plan before any run**.
Six things to know before touching any of it:

- **THE READ NOW HAPPENS AT 1920x1080, NOT 320x180 (2026-09-01,
  owner-approved).** Everything in the next bullet about "no pose fixes
  that at the current frame size" was TRUE OF THE OLD WIRE and is what the
  raise addressed — see "THE WIRE FRAME AND THE TWO CAMERA LEVERS" above
  for the arithmetic, the never-upscale rule and the levers. A refusal
  after the raise is a REAL pose problem, no longer an arithmetic
  impossibility.
- **ITS FIRST TWO FIELD RUNS FAILED TOTALLY, AND THE CAUSE IS RESOLUTION,
  NOT TIMING AND NOT HIS ROOM (2026-09-01, PR fm/commissioning-decode-
  failure, `docs/SPECTRA_SPEC.md` §98).** Both runs were mechanically clean
  — 22 captures, ~42 s, substitution right, room restored — and decoded 0
  of 736 with ~3,165 lit camera pixels ALL undecodable and 0 out of range.
  The raw frame kept from that pose (`data/commissioning-field-evidence/`)
  says why in one number: 66 of 57,600 camera pixels are non-zero, so his
  whole composition arrives as THREE compact glows and every pattern lands
  on the same camera pixels as its inverse and cancels. **The arithmetic
  that governs this whole instrument, and it is not a tuning knob:** gray
  bit 0 alternates in runs of TWO indices, so the camera needs about
  `gray_code.MIN_CAMERA_PX_PER_INDEX` (2) pixels per composition index
  along the imaged strip — 736 pixels need ~1,472, and the entire border
  of the 320x180 frame the phone sent BEFORE THE RAISE is ~1,000. **No
  pose could fix that at THAT frame size** — which is exactly what the
  2026-09-01 raise addressed (the read now asks for 1920x1080, ~6,000;
  see the section above). The "full-resolution ring" is still full
  relative to the 64x36 MAP GRID, not to the camera. Before proposing a cause for
  any future decode failure here, read `Decode.bit_contrast` in the run's
  own response: a mistimed stack compares two DIFFERENT patterns and keeps
  real low-bit contrast while decoding CONFIDENTLY to wrong indices
  (out-of-range > 0); an unresolvable one has zero confident bits with the
  HIGH bits near 1.0. They are opposite signatures and the response now
  carries both. The run refuses BY NAME two captures in
  (`gray_code.resolution_report` →
  `mapping_refusals.unresolvable_composition`) rather than spending the
  room's dark time, and `scripts/check_commissioning.py` §3c reproduces the
  whole field failure on demand.
- **SO IT RUNS PER FIXTURE (or per segment), NEVER THE STITCHED WHOLE
  (2026-09-01, PR fm/per-fixture-commissioning, the captain's ruling).**
  `POST /api/rooms/{id}/commission` takes `targets` — `["fixtures"]` (or
  `per_fixture: true`), `["segments"]`, or explicit `"device:<id>"` /
  `"segment:<n>"`; omitting it still commissions the whole composition, and
  on his tv-mapper that still refuses in four seconds with the arithmetic.
  `commissioning.slice_composition` is the binding statement. The
  re-addressing IS the point: a slice keeps the mapper's own segments,
  their stored numbers and their stored order, and remembers where each
  pixel sits in the whole (`global_indices`), but the gray code addresses
  0..N-1 — so one sconce is 88 pixels, 7 patterns and ~176 camera pixels
  where the stitched whole is 736, 10 patterns and ~1,472. The stored
  layout is always derived at the COMPOSITION's own size and sliced after
  (`slice_layout`); deriving it at a slice's size would fold the mapper's
  rows against the wrong pixel count and invent an arrangement. Every
  target is judged by the SAME frozen table and the set folds back into
  one table of the same five rows (`commission_compare.aggregate`): a
  field is as bad as its worst target, and a target that produced no
  decode contributes UNMEASURED to every row rather than shrinking the
  denominator to the pieces that happened to work. A target the camera
  cannot read ends that TARGET, not the run.
- **MARGINAL REFUSES, and the refusal says WHICH — the captain's words,
  "marginal is the state that produces a confident wrong answer".**
  `gray_code.RESOLUTION_SAFETY_FACTOR` (1.25) sits on top of
  MIN_CAMERA_PX_PER_INDEX, and `resolution_report` reports three states:
  `ok`, `marginal` (above Nyquist, inside the margin) and `impossible`
  (below it). BOTH refusing states refuse; `resolvable` follows
  `verdict == ok`, so every caller inherits the conservative boundary
  rather than opting in. The reason a margin is needed at all is gray
  code's own guarantee working against you: a low bit flipped by a
  fraction of a camera pixel decodes to a NEIGHBOUR, so a marginal pose
  produces a confident, plausible, WRONG arrangement rather than a visible
  failure. His ring alone (560 px, ~1,120 needed and ~1,400 to be trusted,
  against the ~1,000 the whole border of a 320x180 frame holds) is the
  case it exists to refuse. **It is not a knob for getting a run to pass**
  — lowering it does not make a marginal pose readable, only silent. The
  wire's 320x180 frame contract is deliberately UNTOUCHED; changing it
  goes back to the captain.
- **THE ROOM'S OWN LIGHT IS NOW MEASURED, AND A MOVING WINDOW REFUSES BY
  NAME (2026-09-01, PR fm/ambient-stability-gate).** His first per-fixture
  run had a WINDOW IN VIEW in daylight with cloud moving: the resolution
  gate passed honestly (5.375 camera px/index, peak 49.3), and the decode
  still came back 34 of 88 with `out_of_range_pixels=30` — §98's
  CONFIDENT-WRONG signature, which only happens when the stack compared two
  different scenes. `spectra/services/ambient_stability.py` is the binding
  statement; four things it settles:
  - **The gate never looks at the composition.** It fixes a background set
    ONCE — the dimmer half of `full - dark`, a QUANTILE not a threshold, so
    an ambient step between the two references cannot collapse it — and
    measures the SAME camera pixels in every later capture.
  - **ONLY LAMP-FREE COMPARISONS ARE GATED**, and this took a redesign:
    the PAIR delta (a pattern against its own inverse — complementary
    halves, so the fixture's spill cancels exactly, and it is also the
    quantity that lands in the bit's arithmetic) and DARK-AGAINST-DARK (a
    CLOSING dark capture, now the 23rd capture of every pass). A lamp-ON
    capture's distance from the opening dark carries the fixture's own
    spill and is reported but NEVER gated — gating it refuses a room whose
    fixture lights the walls, which is a wall, not a gate.
  - **The bound is `max(2.0 grey levels, 0.10 x peak)`** — half
    `gray_code.BIT_CONFIDENCE`, so drift alone reaches half the bar a bit
    must clear and cannot manufacture a confident wrong bit. Proven on BOTH
    sides (0.7x passes through to a judged table, 1.6x refuses), the same
    bar the marginal resolution boundary is held to.
  - **A moving change refuses EARLY (the first bad pair); a change that
    arrives and STAYS is invisible to every pair — correctly, it cancels in
    the bit too — and is caught by the closing dark.** That asymmetry is
    the design, not a gap. `gray_code.confident_wrong_signature` is the
    cheap cross-check: it CONFIRMS an ambient refusal that already stands
    on its own measurement, and when the ambient is measured STEADY and the
    signature appears anyway the frozen table's own fail stands unchanged
    with a note saying ambient is ruled out. Deferred, stated: mapping runs
    do not use it (their per-emitter pairs are a different shape).
  - **IT IS THE SAME GATE AT EVERY WIRE RUNG AND UNDER EITHER LEVER**
    (`capture_settings`, the same day): nothing is expressed in the camera
    pixels of one frame — the background set is a quantile (half the frame
    at any rung), the tile minimum is a FRACTION of a tile, and the bound is
    a fraction of a measured `peak`. What IS bounded is how many pixels a
    level is taken over (`SAMPLE_PX`, the same pixels every capture so the
    sampling error is common-mode and cancels): measured, a full-set median
    costs 1.9 ms a capture at 320x180 and 45 ms at 1920x1080 — a second of
    the event loop across a pass, in 45 ms blocks — against ~1.6 ms at every
    rung bounded. A long integration time widens every capture window, so
    **both dark references must be averaged over the SAME widened window**
    or the comparison measures the run's own settings instead of the room.
  Spec: `tests/test_ambient_stability.py` (today's cloud reproduced through
  the real decoder, the gate red on it, and a monkeypatched no-gate run
  proving the harness fails on the defect it was written for) and
  `tests/test_ambient_stability_rungs.py` (the composition with #231: every
  rung, a raised and an honestly-downgraded read through the real run, the
  widened window, and the precedence — a refused lever stops the run before
  the ambient gate has any frames to have an opinion about).
- **THE FIVE TOLERANCES ARE PRE-REGISTERED, NOT TUNING KNOBS.**
  `spectra/services/commission_compare.py` quotes the plan's table verbatim
  in its docstring and owns 0.98 / 2% / 5% / 5% / +/-15 ms. Moving one has
  left the pre-registration; the honest act is a NEW pre-registration
  published before the next run, not an edit. Four verdicts, not two:
  `pass`, `findings` (the table's own his-data outcomes — dead pixels, the
  hand-built mapper off — reported as findings, NEVER as a commissioning
  failure), `incomplete` (a row that could not be measured never passes
  silently), `fail`. Precedence fail > incomplete > findings > pass. Every
  attribution is a rule computed from the numbers, decided in advance —
  there is no judgment call at runtime, which is what makes the route
  unattended-safe.
- **TWO ROWS ARE UNMEASURABLE ON HIS ROOM TODAY, and they say so.** His
  `tv-mapper` is `mapping: copy` with `rows: 1` and no device profile: it
  stores a pixel ORDER and no geometry, so rows 3 and 4 (2-D arrangement,
  cross-device stitch) have no stored layout to fit against and report
  UNMEASURED with what would make them judgeable (a device profile with
  real rows/cols, the shape `storage/device_profiles/crystal-mapper.json`
  already uses). Deriving a rectangle from "it is wrapped around a
  television" would be precisely the plausible-looking answer this test
  exists to refuse. Row 5 is unmeasured for a different stated reason: the
  mapping tap runs at 5 fps and a 15 ms tolerance needs ~67.
- **A GATE ANCHORED ON A PERCENTILE ASSUMES HOW MUCH OF THE FRAME THE
  THING COVERS.** The decode's lit gate took its bright end from
  `percentile(full - dark, 99)` — fine for a synthetic room whose blobs
  cover the frame, meaningless for a composition covering 0.11% of it: the
  percentile landed in the read noise, the gate collapsed to "anything
  above the dark reference", and it reported 3,165 lit pixels in one run
  (averaging noise) and 0 in the next. It is now the mean of the brightest
  `gray_code.PEAK_SAMPLE` pixels plus a one-grey-level floor — the sensor's
  own quantisation, which is NOT the scene-brightness assumption the
  inverse capture exists to avoid. Watch for the same shape anywhere else a
  small bright thing is measured against a whole frame.
- **ONE CONTINUOUS HOLD per pass, where the MAP's run is a chain of short
  ones** — different acts, not a change of mind: a map's emitters are
  independent measurements; a gray-code STACK is ONE measurement against
  one dark and one full reference, so the room coming back to life halfway
  through would put the show's own light into the middle of it. ~35 s,
  inside the hold's own 3-minute ceiling.

Everything else is reused rather than rebuilt: the mapping session (frames,
exposure lock, refusals — plus a full-resolution ring it turns on for the
run and off in a `finally`, because 736 pixels cannot be resolved by 2304
map-grid cells), `flare_preview_hold.open_program_hold`, the copy-carrier
substitution, `activate_for_capture`/`deactivate_after_capture`,
`fixture_brightness.measured_as_is`, and `mapping_refusals`. The lamp is
`fx/effects/pixelPattern.py` (`fx/VENDOR.md` #28, registry-exempt); all the
gray-code arithmetic is `spectra/services/gray_code.py`, pure, so the lamp
and the decoder cannot drift into two ideas of which pixel is which.
Proofs: `scripts/check_commissioning.py` (real render pipeline for the
lamp, then a declared arrangement recovered end to end, then SABOTAGE —
each corrupted stack failing its own row with the table's own attribution;
§7 is the per-target half, including the marginal boundary proven on both
sides against a box-integrating camera whose reported
`camera_px_per_index` IS the number under test),
`tests/test_commissioning.py`, `tests/test_commissioning_per_fixture.py`,
`tests/test_gray_code.py`.

## THE WIRE FRAME AND THE FOUR PINNED CAMERA LEVERS (`capture_settings.py`)

**`spectra/services/capture_settings.py` is the binding statement** — the
ladder of declared frame sizes, the arithmetic that chose them, the four
pinned levers (`LEVER_BOUNDS`: integration time, gain, white balance
temperature, focus — the last two added 2026-09-01, NATIVE CLIENT ONLY,
since the browser can reach neither), and the frame-rate coupling. Read it
before touching anything that sends, sizes or exposes a capture frame. Seven
things:

- **THE WIRE FRAME IS PER RUN, NOT ONE NUMBER (2026-09-01, owner-approved:
  "raise video frame size and tweak whatever settings help").** A MAP still
  sends 320x180 — a footprint is a 64x36 grid and more pixels buy nothing,
  so night runs stay cheap. The COMMISSIONING read asks for **1920x1080**,
  by arithmetic and not by picking the maximum: a decode needs ~2 camera px
  per composition index, so his 736 need ~1,472 of imaged strip (~1,840
  with the safety factor), and a strip wrapped round a screen images as a
  PERIMETER — the whole perimeter of a 320x180 frame is 2x(320+180)=**1,000**,
  so **no pose could ever have worked**. `commission_profile_for()` derives
  the rung (smallest clearing 736 with 2x pose margin at a 77%-fill pose);
  1920x1080 carries ~1,848. **THE STORED 64x36 MAP GRID IS UNCHANGED** —
  every rung is 16:9 and an exact whole multiple of it (5x/10x/15x/20x/30x),
  so `light_field.downsample` stays a box mean and a grid from a 1080p frame
  is directly comparable with one from 320x180. **grey8, uncompressed, at
  every rung** — a lossy stage's noise lands inside the measured difference.
- **ASKING FOR A NEW WIRE FRAME COMMANDS THREE ACTS, AND THEY ARE ADDED, NOT
  SHARED (2026-09-06, PR fm/spectra-fix-framesize-race).** His sconce
  commissioning negotiated 1920x1080 at 22:09, REFUSED at 22:44 ("the camera
  is still sending 320x180 ... 2 frames arrived at the old size while this
  run waited") and worked again at 22:46, with nothing about the camera, the
  pose or the room different — and it was worse whenever an integration time
  rode in the same `config` message. Neither the camera nor the refusal's
  wording was wrong: the client had been told to restart its pixel pipe at
  the new size (for which `capture_client/camera.py::_open_at` allows ITSELF
  15 s), re-read every control, and pay the sensor settle any moved lever
  owes (`regime_settle_s`) — and all three had to fit inside ONE fixed 4.0 s
  window (`room_mapping.FRAME_SWITCH_WAIT_S`) that the run picked without
  knowing which of them it had commanded. `frame_switch_wait_s` derives that
  window instead — the three costs ADDED, from the client's own numbers —
  and `await_frame_size` takes `max(caller, derived)`, so **the caller's
  constant is a FLOOR and never a ceiling**; the negotiation is the only
  place that knows both the request and the client's cost, which is why the
  bound is raised there rather than at four call sites. **It can afford to
  be generous because of what it bounds**: `await_frame_size` returns on the
  FRAME, not on the clock, so this is the longest a run waits before
  REFUSING and never a delay before succeeding — a working camera pays none
  of it. A client that genuinely never switches is still refused by name,
  which is half the proof (`tests/test_frame_size_switch_wait.py` drives the
  real commissioning run over a modelled slow client and carries the
  never-switches control beside it). Before shortening any wait on this
  path, check what the far side was told to DO first.
- **A CLIENT NEVER UPSCALES, and the server asserts it independently.**
  `capture_settings.choose` picks the largest rung no bigger than BOTH the
  request and the camera's own image; every frame carries `source_width`/
  `source_height`; a frame bigger than its source is dropped and NAMED
  (`mapping_refusals.upscaled_frame`). Interpolated pixels would inflate
  `gray_code.resolution_report`'s camera-pixel count and let an unreadable
  target report that it is readable — the MARGINAL confident-wrong-answer
  through a side door. A camera that tops out at 720p **still runs**, at
  720p, and the run says which rung it got (an honest downgrade is a
  RESULT, never a refusal).
- **THE TWO LEVERS ARE PER-RUN AND DEFAULT TO TODAY'S BEHAVIOUR.**
  `exposure_time` is in **100-MICROSECOND UNITS on both paths** (V4L2
  `exposure_time_absolute`, W3C `exposureTime`) so **nothing converts**;
  `gain` is the device's own scale (V4L2 `gain` / the browser's `iso`),
  passed through verbatim — converting it would be an invention. Asking for
  neither is converge-then-freeze exactly as before. **Both are READ BACK
  from the device**, and a lever the camera did not take refuses BY NAME
  before any light (`manual_camera_unavailable`) — measuring under whatever
  the camera chose while reporting the asked-for numbers is the one thing
  this path must never do.
- **A LONG INTEGRATION TIME IS NOT FREE, and it is not silent.** A sensor
  integrating for E seconds gives at most 1/E fps, and a capture averages
  whatever ARRIVED in its window — so `room_mapping.capture_windows` /
  `commissioning.capture_window` widen the CAPTURE windows to still buy
  `MIN_FRAMES`, `run_estimate_s` prices the widened run, and an exposure no
  legal window can average refuses by name (`exposure_too_long`). **With no
  manual exposure asked for both are an EXACT pass-through** — the shipped
  protocol, byte for byte.
- **`capture_settings.CameraNegotiation` IS THE ONE IMPLEMENTATION**, and
  `MappingSession` plus **every test double** (`SessionCameraDouble`)
  inherits it. Seven fake sessions live across `tests/` and `scripts/`; a
  gate they MODEL is a gate no proof exercises — the founding defect of
  this whole area was a hold that reported itself set while the show fired
  underneath. Add a session capability there, not in seven places.
- **THE EXPOSURE COMPARISON** (`spectra/services/exposure_test.py`,
  `POST /api/rooms/{id}/exposure-test`, the Rooms page's own panel) answers
  "is it the room, or the camera settings?": one emitter, one pose, two
  regimes back to back, `better`/`ratio`/`summary`. It **stores nothing**
  (throwaway room copy, no `save_room`) and puts the camera back in a
  `finally`. The two weights are deliberately on different byte scales —
  each is `lit - dark` WITHIN its own regime, so both are honest about how
  much signal that regime produced and **neither is comparable with any
  other footprint in the room**; the summary says so. A default regime that
  saw NOTHING is a RESULT, not a failure.

- **THE LEVERS TRAVEL THROUGH THE QUEUE, AND THE NIGHT PRICES THEM.**
  `QueueItem` carries `exposure_time`/`gain` because its own contract is
  "the SAME arguments the route takes" and both run routes take them — an
  unattended run must not be the one place his camera cannot be told what to
  do. And `night_run.price_items` prices a map item at the windows
  `capture_windows` will WIDEN it to, not the ones it declared: a long
  integration genuinely takes longer, and pricing the declared windows would
  price short against the 05:30 planned-end bound, which is the one bound
  that must not be over-run. Both were found composing #230 and #231 at the
  same choke points; `tests/test_camera_levers_and_night.py` is the proof
  that neither build swallowed the other.

**KNOWN, OPEN, NOT FIXED BY THE RAISE:** `gray_code.resolution_report`
counts lit **AREA**, so a strip thick enough for its LEDs' images to
overlap sideways reports more camera pixels per index than it linearly
resolves — measured at 5.7 where the perimeter supports ~1.4
(`scripts/check_commissioning.py` §3d prints it). The gate can therefore
pass a pose that decodes to NEIGHBOURS. His own field frames were thin
glows so the gate was right about them. Measuring linear extent from the
reference pair alone is separate work; inventing a boundary for it in
passing is exactly what a pre-registered instrument must not do.

Proofs: `scripts/check_commissioning.py` §3d (his own composition at a
77%-fill pose — 320x180 decodes CONFIDENTLY WRONG at ~0.76 LED spacings,
1920x1080 lands at 0.12, and accuracy rather than a count is what is
asserted), `tests/test_capture_settings.py`, `tests/test_camera_levers_in_runs.py`
(the runs actually negotiate and actually restore), `tests/test_exposure_test.py`,
`scripts/check_capture_queue_e2e.py` §5 (the negotiation over the REAL
client, WebSocket and server), `tests/test_camera_levers_and_night.py` (this
build and the night run composing). Help: `camera-settings`,
`exposure-comparison`.

## "THE SETTING IS NOT THE LIGHT" — the lever self-test (`lever_selftest.py`)

**`spectra/services/lever_selftest.py` is the binding statement.** Read it
before touching anything that decides whether a camera can be trusted.

THE EVENING IT EXISTS FOR (2026-09-01): the browser path commanded three
integration times — 10 ms, 60 ms, 200 ms, a factor of twenty end to end —
every one was accepted, every read-back agreed, and the measured light did
not move (footprint weights 0.0, 0.0014, 0.0051 against
`light_field.UNSEEN_WEIGHT` = 1.0), while the camera's own converged regime
wandered 0.23 -> 0.01 between two runs of the same thing. **A read-back
proves the DRIVER holds a value. It cannot prove the SENSOR obeys it.** The
two checks both run and neither substitutes for the other. Seven things:

- **THREE CAPTURES, and the order is the design**: A (dim), B (= A x
  `COMMANDED_FACTOR`), B' (the SAME command again). A->B answers "does more
  commanded time put more light in the frame"; B->B' answers "does this
  camera hold still when nothing was asked to change". The repeat is at the
  BRIGHT regime because a ratio between two near-noise readings measures
  nothing.
- **SIGNAL IS CHECKED BEFORE RESPONSE, and that ordering IS the fix.**
  His three real weights are proportional to two significant figures and
  every one of them is noise — a response check run first would have
  PASSED them. So the bright regime must clear `UNSEEN_WEIGHT` before any
  ratio is quoted, and the no-signal wording names the honest ambiguity (a
  pose that sees nothing and a dead lever look identical, and neither can
  be calibrated through).
- **The measurement is the MAP'S OWN** — `room_mapping._map_one` against a
  throwaway room with no `save_room`, `exposure_test.py`'s own precedent.
  Never a second idea of "how much light".
- **`unprovable`/`unproven` NEVER REFUSE** (`mapping_refusals.
  LEVER_REFUSING` is the list that do, and every one of them is
  a MEASUREMENT). "We could not check" is not "we checked and it is
  broken" — the same distinction `night_exit` draws between DARK and
  UNKNOWN and `witness` between contaminated and witness_unavailable.
  Refusing on a check that could not be made would invent a fault.
- **WIRED AT `capture_runs`, the one seam**, before a map / commissioning
  pass / exposure comparison whose session is the NATIVE client, inside
  the run lock (it drives a light, so it takes the same held room and the
  same camera every capture takes — it acquires nothing new). **The verdict
  is cached ON THE SESSION OBJECT**, which is what makes "at establishment,
  and after any reconnect" structural rather than remembered:
  `mapping_session.open_session` builds a NEW session per WebSocket, so a
  reconnect cannot inherit one, and the fingerprint carries the pose id so
  a camera reopen inside one connection cannot either.
- **IT DRIVES WHAT THE RUN DRIVES, and FAILS CLOSED when it cannot**
  (2026-09-05). `lever_selftest.Scope` — its docstring is the binding
  statement for this rule — is the run's own scope (`emitter_ids`/
  `carrier_ids` PLUS the `granularity`/`block_pixels` the run will use),
  handed down by `capture_runs.run_map` through `_preflight`. Before it the
  self-test drove `plan.emitters[0]` over the whole room however narrowly
  the run was scoped, which on his one-carrier Living Room (`tv-mapper`, a
  560-px strip spanning the TV backlight AND both kitchen sconces) lit the
  kitchen for a run scoped to the backlight's blocks. Four invariants:
  (1) the self-test enumerates at the run's OWN shape ONLY when the scope
  names emitter ids (`Scope.plan_granularity`/`plan_block_pixels`, the one
  definition) — an emitter's id comes from the granularity that produced
  it, so a block-scoped id cannot resolve in a whole-granularity plan; a
  carrier-only scope or an unscoped run enumerates at WHOLE whatever the
  map itself runs at, because following the run's shape unconditionally
  makes an ordinary "auto"=BLOCK map on his single-segment TV wrap earn its
  verdict on one 30-px block at the far end, out of shot, and cache that
  NO-SIGNAL verdict for the session. (2) `Scope.within` is the fail-closed
  guarantee and it is STRUCTURAL — the plan's own list verbatim when
  unscoped, a subset otherwise — so a scoped run resolving nothing reports
  `LEVER_UNPROVEN` with `mapping_refusals.lever_scope_unresolved` and drives
  no light at all; there is no fallback emitter left to widen to. (3)
  ACTIVATION is narrowed too: `activate_for_capture` is handed a plan of the
  ONE driven emitter, never every carrier's substitute (it only ever adds to
  the live list the hold is built over, so the dark reference cannot
  shrink). (4) The cache key deliberately does NOT carry the scope — the
  verdict is about the CAMERA, so a differently-scoped queue pays once.
  `run_commission`/`run_exposure_test`/`run_pose_fingerprint` pass no scope
  and are byte-identical to before.
- **BROWSER SESSIONS ARE NEVER SELF-TESTED** — and since the demotion (see
  "THE BROWSER IS A VIEWFINDER" below) that is because a calibration-grade
  run on one is refused EARLIER and for the broader reason: a browser cannot
  pin the camera at all, so there is nothing here to measure. The order
  matters — a browser failing THIS test would say "your camera is not
  obeying its exposure control", which is true of the browser and would send
  him to look at the camera. `capture_runs.session_view()['native']` is
  still the tell.

**PERSISTENCE IS SOFTWARE, on the other half of this.** Whatever a session
pins is re-asserted by `camera.open()` (a reboot, a re-plug, a dead capture
pipe, a scaler restart) and by the client at every reconnect
(`session._reassert`, counted in `state.reasserts`), then READ BACK.
Nothing is written to disk and nothing about the camera's own memory is
relied on. A `config` message naming one lever does not un-pin the others;
un-pinning is saying so explicitly (`null`).

Proofs: `tests/test_lever_selftest.py` (the pure judgement red/green/drift,
the whole run, sections 5-7 for the scope, its fail-closed rule and the
narrowed activation — both halves verified RED against the widening they
replace — and a test that goes
RED on the defect it was written for —
with the preflight removed, tonight's camera runs a whole map and reports a
ROOM-shaped failure, sending him to move a camera that was standing in
exactly the right place), `tests/test_camera_pinned_settings.py` (four
controls written, read back, and each one's stuck-driver refusal), and
`scripts/check_lever_selftest.py` — both directions over a real server, a
real WebSocket, the REAL capture client and the real map route, run from
`tests/test_light_field_checks.py`.

### A STAMP IS NOT A PHOTON — the stale-stream defect (2026-09-02)

The self-test above met a REAL camera for the first time and refused his
laptop with readings that made no sense: commanded 500 x100 us measured
0.000; commanded 2000 measured 444.282; commanded 2000 AGAIN measured
0.043 — two IDENTICAL commands ten-thousand-fold apart, with every driver
read-back holding Manual throughout. **Nothing was wrong with the lever and
nothing was wrong with the judgement. The frames were OLD.**
`spectra/capture_client/camera.py`'s "FRESH FRAMES" block is the binding
statement. Five things, and the first three generalize well past cameras:

- **A TRANSPORT THAT QUEUES WHOLE FRAMES BREAKS A `lit - dark` INSTRUMENT
  SILENTLY, and no server-side window can see it.** The client reads pixels
  out of an ffmpeg pipe; MEASURED in the exact construction `_open_at`
  builds (OS pipe + `StreamReader(limit=frame*8)`), that path holds up to
  **19 whole 320x180 frames — 3.8 s at 5 fps — and it SATURATES there**. It
  fills the first time the client stops reading for a moment (`open()`
  sleeps `SETTLE_BEFORE_LOCK_S` then runs `apply_lock`; `apply_lock` and
  the paced `read_lock` are BLOCKING `v4l2-ctl` subprocesses on the event
  loop) and is never given back, because the frame loop paces itself at
  exactly the camera's own rate. 3.8 s is longer than a whole capture phase
  (settle 0.7 + window 1.5), so a LIT window lands entirely on frames whose
  photons predate the lamp — and a slightly shallower queue catches it in
  full. That is not noise between two readings; it is the two sides of one
  boundary.
- **A CAPTURE STAMP IS HONEST ABOUT ITSELF AND SAYS NOTHING ABOUT THE
  WORLD.** `captured_at_ms` is stamped when the client READ the frame out
  of its transport. `MappingSession.gather` windows correctly against that
  stamp through the paired clock, and its floor is already the phase's own
  write plus settle — **a second `not_before` floor was considered and is
  decoration; the docstring says so, so it is not re-added.** The whole
  defect lives in the gap between the stamp and the photons, which only the
  client can close.
- **TWO LAGS, TWO FIXES, and each is proven with the other turned off.**
  TRANSPORT: `camera.newest_of` — a frame is returned only when nothing
  newer is already waiting (`DRAIN_PROBE_S` 20 ms, an order of magnitude
  above the ~1 ms an already-buffered frame costs and below a 30 fps frame
  period). Draining the measured 19-frame saturation costs **23 ms**, so
  freshness is free. SENSOR: `camera.SENSOR_APPLY_FRAMES` (3) discarded
  after a control actually MOVES — the frame in flight and the frame
  already integrating were exposed under the old regime, and no drain can
  reach those; the server states the same bound independently as
  `capture_settings.regime_settle_s`, paid ONCE per commanded regime, so an
  ordinary map (whose exposure never moves mid-run) pays nothing. Without
  it a reading's DARK REFERENCE straddles the change and is subtracted from
  a lit capture taken in a different regime.
- **THE SYNTHETIC CAMERA IS FRESH BY CONSTRUCTION, WHICH IS WHY NOTHING
  CAUGHT THIS.** `SyntheticCamera` is a function: no transport, no queue, a
  control change visible in the very next frame. Every proof of this path
  used it. **Any rig that must speak about timing has to model the queue**
  — `tests/test_stream_freshness.py` does, and drives the REAL
  `run_selftest`/`_map_one`/`light_field`/`judge` through it, swept across
  the whole measured band rather than sampled at one depth.
- **A CLIENT DECLARES FRESHNESS AND THE THREE ANSWERS ARE NOT TWO.**
  `hello.fresh_frames` -> `capture_source.serves_fresh_frames`: True,
  False, or **None for a build that did not say** (and a browser, which
  cannot). Nothing REFUSES on it — it is a build's silence, not a
  measurement — but a lever verdict whose readings disagree carries
  `mapping_refusals.STALE_STREAM_FIRST_CHECK` as the NAMED FIRST CHECK, the
  `SCONCE_MAINS_FIRST_CHECK` discipline: two identical commands orders
  apart is what a queued transport looks like, and sending someone to look
  at a working camera instead is the hour that sentence exists to save.

**THE FIX IS CLIENT-SIDE AND SERVER-SIDE, so `spectra.service` must be
deployed for `regime_settle_s`/the freshness note, and the camera host must
pull for the drain.** Until it pulls, its readings are refused-or-noted,
never silently trusted. Proofs: `tests/test_stream_freshness.py` (the
judgement, modelled transport, red and green, swept) and
`scripts/check_stream_freshness.py` (the transport MEASURED against a real
subprocess pipe, the real `V4L2Camera.frame()` beside the read it replaced,
and the whole thing over a real server, WebSocket and capture client —
0.15 s from capture to stamp where the shipped read served 2.2 s of queued
frames).

### THE SHORT-EXPOSURE COMMISSIONING REGIME — a camera honest only at the short end

**`spectra/services/short_exposure.py`'s module docstring is the binding
statement.** 2026-09-09: the lever self-test refused every commissioning run
on his kiosk Brio, night AND daylight, in TWO DIFFERENT SHAPES depending on
ONE V4L2 control — `exposure_dynamic_framerate` ON gave DRIFT (the same
command measured 33.61 then 16.03), OFF gave NO_RESPONSE (commanded 62
measured 12.577, commanded 250 measured 2.46). **Both refusals were
correct**: that control is what lets a UVC camera DROP ITS FRAME RATE to
integrate longer than one frame interval, so leaving it on lets the camera
renegotiate its own timing under a measurement and pinning it off makes a
long command undeliverable. There is no third setting. Six things:

- **HALF THE CEILING IS DERIVED AND HALF IS A SETTING, and which is which
  is stated.** Derived: a sensor delivering F frames a second cannot
  integrate longer than 1/F, and F is READ OFF THE DEVICE (`v4l2-ctl
  --get-parm` → `CameraLock.sensor_fps`, once per open, never the tap rate
  the client paces its sends at). Not derived: WHERE inside that interval
  the camera stops being honest — his two points bracket it (62 good, 250
  bad, frame interval 333) and two points cannot locate a boundary. So the
  fraction is `config.short_exposure_fraction` (`SPECTRA_SHORT_EXPOSURE_
  FRACTION`, default 0.25 → 83 at 30 fps), anchored on those points. **It
  is not a knob to turn until a run passes** — a run that passes because
  the bar moved has measured nothing; re-anchor by MEASURING more points.
- **NOTHING IN THE JUDGEMENT MOVED, and that is the whole point.**
  `COMMANDED_FACTOR`, `MIN_PROVABLE_FACTOR`, `MIN_RESPONSE_FRACTION`,
  `REPEAT_BAND` and `light_field.UNSEEN_WEIGHT` are untouched and asserted
  untouched; the self-test still commands two different times and still
  repeats one. This moved WHERE it measures, never WHETHER the readings
  must agree — a drifting or non-responding camera INSIDE the short regime
  still refuses, proven with his own numbers.
- **ONLY A CONTROL THE CAMERA HAS REPORTED IS EVER ASKED FOR.** The pin and
  the commanded default both gate on the read-back (`Ceiling.commandable`,
  `short_exposure.pinnable`): a camera that never reported an
  integration-time control is not commanded one, and one with no
  `exposure_dynamic_framerate` is left alone — it cannot renegotiate its
  frame rate, so there is nothing to pin. **Absence is never a refusal;** a
  control WRITTEN and read back WRONG still is.
- **THE SWITCH IS OWNED, NOT JUST SET** — `capture_settings.
  PINNED_SWITCHES` (server) / `camera.SWITCHES` (client), declared apart
  from the four levers because their refusal contracts differ. The client
  reads his value before the first pin and writes it back on the un-pin
  (`camera._apply_switches`), which every run's existing all-default
  restore already sends. `night_power.owned` one layer down.
- **THE COMPENSATION IS SMALLER THAN IT SOUNDS, and saying so is the
  useful part.** `room_mapping.LIT_BRIGHTNESS` is already 1.0 and the
  commissioning pattern lamp already writes `brightness: 1.0` — the lamp is
  full. The fixture's own master brightness is Home Assistant's (since
  2026-10-12 no capture raises it), so the lever self-test, like every
  capture path, NAMES a fixture below full in its notes
  (`fixture_brightness.measured_as_is`) for him to raise. Gain is
  deliberately NOT raised to compensate: it would lift the sensor's noise
  into the `lit - dark` difference this instrument measures.
- **A REGIME THAT STILL CANNOT SEE SAYS SO.** `mapping_refusals`'
  NO_SIGNAL wording ADDS the third explanation (not enough light for the
  time this camera can hold) to the two it always had — it never replaces
  them, or a genuinely dead lever would read as a room problem.

**UNVERIFIED AGAINST A LIVE CAMERA.** There was none on the kiosk when this
shipped; it is proven offline only and does not become "his commissioning
works" until a live Calibration One passes. Specs:
`tests/test_short_exposure.py`, `scripts/check_short_exposure.py` (his six
readings replayed through the real `judge`, the ceiling and light budget
computed from his own numbers, the pin's round trip through the real client
and the real `V4L2Camera`) — the check script's LAST LINE is that
unverified statement, asserted by `tests/test_light_field_checks.py` so the
claim cannot quietly go missing.

### THE STREAM'S OWN LAG — a settle tuned for a fast stream is noise on a slow one

**`spectra/services/capture_settings.py`'s SIX section and `lever_selftest.
_measure_stream_lag` are the binding statement.** 2026-09-23, the kiosk's
own follow-on defect after the short-exposure fix above:
`data/kiosk-exposure-lever-no-response/report.md`. His kiosk camera had been
raised to a held 1920x1080/5fps stream (PR #285, correctly — commissioning
needs it) and the SAME 21/83/83 self-test sequence that passed on the old
320x180/30fps stream now refused `no_response`. Daylight measurement through
the real client path proved the sensor DOES obey its exposure control
(10/10 steps); what changed was TIME — every control write or scene change
took 1.4-2.1s to reach the frames the client delivers (six to eight frames
at 4.4 fps, upstream of everything the client's own transport drain can
reach), longer than the self-test's fixed 0.7s dark/lit settles, so its
"dark" reference still showed the previous lit lamp. Four things, matching
the report's own Q5:

- **THE LAG IS MEASURED, not assumed, once per run, before the self-test's
  three regimes.** With the room already dark (this measurement's own
  "dark" step is what makes it so), the ONE driven emitter's lamp steps
  black→lit once and the delivered stream is watched until it crosses
  halfway to its plateau — the same measurement the field report's own
  "run 3" made with `brightness`, made here with a lamp.
  `capture_settings.stream_lag_crossing` is the PURE half (samples in,
  seconds out, or `None` for "could not measure" — never a guessed zero);
  `lever_selftest._measure_stream_lag` is the live half, reading
  `session.grids` (the same timestamped ring `observed_fps` already reads)
  directly rather than calling `gather()` repeatedly — a plain read has no
  side effect on anything else watching the session, where a poll loop
  built on `gather()` would fight the regime loop that runs right after it
  for the same frames.
- **THE SETTLES ARE WIDENED, NEVER NARROWED**: `capture_settings.
  widen_settle(base, lag) = max(base, 1.5 x lag)`, applied to
  `DARK_SETTLE_S`/`LIT_SETTLE_S` for the three regime captures only — never
  to `regime_settle_s` (a DIFFERENT thing, the sensor's own apply delay,
  already priced). A lag past `STREAM_LAG_REFUSAL_S` (4.0s) REFUSES BY NAME
  (`mapping_refusals.stream_lag_too_high`, verdict word
  `LEVER_STREAM_LAG`, added to `LEVER_REFUSING`) rather than measuring
  through it — a MEASUREMENT, exactly like `no_signal`/`no_response`/
  `drift`, never `unprovable`/`unproven`. `stream_lag_s` rides on
  `Verdict.as_dict()` and therefore on `CalibrationRun.lever` for free —
  no separate persistence plumbing needed.
- **A SESSION WITHOUT `.grids` IS NEVER MEASURED AND NEVER REFUSED ON IT** —
  `_measure_stream_lag` returns `(None, False, False)` (its full shape is
  `(lag_s, supported, had_signal)`), and `run_selftest` reads the middle
  `supported` value to tell "could not measure" (skip, old behaviour) from
  "measured, found nothing" (refuse). Every real production session has
  `.grids`; only a test double built before this existed does not — the
  same "did not say" discipline `capture_source.serves_fresh_frames`
  already draws, applied so this measurement can never retroactively
  refuse a fixture whose fake was never asked to model it.
- **THE CLIENT NOW SAYS TWO MORE THINGS ABOUT ITSELF, additively.**
  `hello.fresh_frames` only ever meant "my transport pipe is drained" —
  never "the frame is fresh" (a UVC camera's own firmware/USB pipeline can
  still be seconds behind while this flag is `True` the whole time, which
  is exactly what cost the evening here). `hello.pipe_drained` carries the
  SAME value under its honest name (`BaseCamera.pipe_drained` property);
  `fresh_frames` is kept, unrenamed, for every existing reader —
  `CLIENT_VERSION` bumped to "1.2" for the addition. `hello.delivered_fps`
  is the client's own measured send rate (a bounded 16-sample window,
  mirroring the server's own `observed_fps` algorithm), beside the
  device's DECLARED `sensor_fps` already on `lock` — read server-side via
  `capture_settings.declared_fps(session)`, used only inside
  `lever_selftest._one_regime`'s own fallback (`sess.observed_fps() or
  capture_settings.declared_fps(sess)`) rather than a hardcoded `5.0` —
  deliberately NOT threaded into `room_mapping.py`/`commissioning.py`/
  `exposure_test.py`'s own fallbacks in this pass, to keep the change
  contained to the path the report's field evidence is actually about.

Acceptance (offline, development check): stream_lag_s comes out ≈1.5s on
the held-1080p/5fps stream shape (`tests/test_capture_settings.py`'s own
synthetic-sample tests; `tests/test_lever_selftest.py`'s live-measurement
tests with a `.grids`-bearing fake session prove the full widen/refuse
wiring through `run_selftest`). **Unverified against the real kiosk camera
by this build** — the acceptance bar in the field report (2.5-3x response
ratio through the real client on the held stream) is a live check for
whoever deploys this.

### A CALIBRATION MUST NOT RUN UNDER A LIVE SHOW ENGINE, and a QUIET TAKE IS NOW ONE HTTP CALL AWAY

Second finding of the same 2026-09-23 report: the night window took the
room through the ORDINARY handover (`engine.go_live()`), and ten seconds
into the self-test the drift conductor's own ~20s leg lit the crystal
(Fish) and 17 Hue bulbs — a moving effect landing inside the exact dark/lit
windows the instrument was subtracting, corrupting the "repeat" regime's
own reading (though the refusal that night actually fell on the two
readings taken before that, so the sequence was already doomed by the
stream lag above). Two independent fixes:

- **`calibration_runs._engine_live()`** (a lazy `from spectra.services
  import engine; engine.status()["dark"]` read, the same local-import
  convention every other caller of that module already follows — see the
  room_controls import-time trap elsewhere in this file for why nothing
  built at import time may touch a singleton-adjacent module eagerly) is
  now checked at the top of `_run_declared` — the ONE body `run_calibration`
  and `run_amendment` share — right after the "nothing declared" check and
  before pricing/parsing the queue. A status call that cannot answer is
  `False` (not live), never a refusal on a check that could not be
  made — the same discipline `lever_selftest`'s own UNPROVABLE/UNPROVEN
  verdicts stand on. Refuses with `mapping_refusals.calibration_engine_
  live()`, which names the way out. **This is a real, deliberate new
  constraint on DAYTIME calibration runs too**, not only night ones — the
  contamination mechanism is a property of the engine being live during a
  capture, not of the hour.
- **THE QUIET TAKE, exposed on `POST /ownership/handover`** — until this it
  existed only inside `night_take.take_room` (arming-gated,
  released-room-only). `HandoverRequest.quiet: bool = False` threads
  straight to `handover.production_sides(quiet=...)` +
  `handover.run_handover(..., quiet=...)` — SPECTRA-only (silently ignored
  for a handover to spot-effects, which owns no such mode); the exact API:
  `POST /api/ownership/handover {"to": "spectra", "quiet": true}` (armed by
  `SPECTRA_HANDOVER_ARMED` as always). It brings the stack up BLACK and
  never calls `engine.go_live()` — see the night-self-take section's own
  "THE STACK COMES UP BLACK" / "THE ENGINE STAYS ON PAPER" bullets for the
  mechanism, unchanged; this is the same quiet take, reached from a second
  caller. **Only pass `quiet=True` on the kwarg when it is actually True**
  (`spectra/api/ownership.py::post_handover`) — an unscoped, non-quiet call
  must stay the exact old call shape (`production_sides()`, no keyword at
  all) or a test double built for the old signature breaks.
- **`Calibration.lever_scope`** (`{"emitter_ids": [...]}` or
  `{"carrier_ids": [...]}`, empty default) lets a calibration NAME which
  emitter its own lever self-test drives, overriding the run's own default
  (`plan.emitters[0]`) — found necessary because his kitchen kiosk's pose
  sees the Living Room's `tv-mapper` TV-backlight (every pre-existing
  calibration's default emitter) as a near-invisible 0.2-0.7 grey levels
  per cell, where a kitchen sconce is in frame and legible.
  `calibration_runs._lever_scope(cal)` builds the `lever_selftest.Scope`;
  it reaches BOTH `establish_pose`/`check_pose` (`capture_runs.
  run_pose_fingerprint`'s new `lever_scope` param) AND the declared queue
  (`capture_queue.run_queue`'s new `lever_scope` param, threaded through
  `_execute` and into `capture_runs.run_map`/`run_commission`) — **it has
  to reach BOTH**, found by a failing test: `lever_selftest.ensure`'s own
  cache means whichever calibration-grade call earns the verdict FIRST is
  the one every later item in the session inherits, and a fresh
  calibration establishes its pose before it ever reaches its declared
  items. A `lever_scope` that only reached the queue would be silently
  overridden by the pose-establishment step's own unscoped default. The
  scope decides only which emitter PROVES the camera — it never narrows
  which emitters the run itself measures. `PUT /api/calibrations/{id}`
  accepts `lever_scope` on `CalibrationBody` like any other declared
  field, recorded as an ordinary lineage change — but KNOWING which
  emitter id names the sconce for a real calibration is still an
  operator/deploy call, the same convention `scripts/
  set_scene_colorset_preference.py` already uses — not guessed here from
  live storage this build never read. **`emitter_ids` NAMES WHOLE
  CARRIERS ONLY** — this scope carries no `granularity`/`block_pixels` of
  its own the way a run's `lever_selftest.Scope` does, so a block/segment
  id (`carrier:blk3[90-119]`) could never resolve through it; naming one
  is refused BY NAME (`calibration.lever_scope_rejection`, checked at the
  model's own field validator AND again in `spectra/api/calibrations.py`'s
  `_validate_lever_scope`, since `PUT`'s edit assigns the field directly
  and never re-runs the model's validators) rather than silently earning
  `lever_scope_unresolved` at run time.

Spec: `tests/test_calibration_engine_and_lever_scope.py`,
`tests/test_calibration_api.py`,
`tests/test_handover.py` (proof 8, the quiet-take route),
`tests/test_capture_settings.py`/`tests/test_lever_selftest.py`/
`tests/test_capture_client.py`/`tests/test_mapping_session.py` (the stream
lag + hello-field halves above).

## THE BROWSER IS A VIEWFINDER — a calibration-grade run refuses it BY NAME

**`spectra/services/capture_source.py` is the binding statement** for which
client may source a measurement; `mapping_refusals.browser_not_calibration_
grade` owns the sentence. Read both before touching anything that decides
who is holding the camera. Six things:

- **THE GATE IS ONE `if`, AT THE ONE SEAM.** `capture_runs._gate` refuses a
  browser-established session for any `kind in CALIBRATION_GRADE` (map,
  commissioning, exposure comparison, pose fingerprint), before the room is
  asked for, `refusal="browser_session"`. The button, the unattended queue
  and a calibration re-running itself are callers of equal standing through
  that function, so all three inherit it and none can be the one that
  forgot. **Do not add a second copy of this decision anywhere** — that is
  what `capture_source.calibration_grade` exists to prevent, and it is the
  one line that changes the day a second client kind can hold a camera
  honestly.
- **THE DEMOTED THING IS THE BROWSER'S STANDING, NOT THE TRANSPORT.** The
  native client speaks the SAME `mapping_session` protocol, so none of that
  machinery moved or forked. A browser still connects, streams frames,
  reports its lock and serves the preview — and AIMING stays first-class,
  because pointing a camera does not care whether the sensor obeys its
  exposure control. `tests/test_browser_demotion.py` proves the aiming path
  end to end on the real session and the real routes, and would go red if
  "demote" had been built as "refuse".
- **NEVER A DEAD BUTTON.** The Rooms page keeps every run control and
  executes them against whatever NATIVE session is established (he presses
  it here, that machine measures it), so the buttons are enabled whenever
  ANY camera holds the room. A press with only a browser present comes back
  with the sentence and the one next step. `session_view()` carries
  `source`/`calibration_grade`/`calibration_refusal`/`measured_by`/`aiming`
  — the refusal text arrives from the SAME function the gate calls, so the
  page cannot promise what the gate will not honour.
- **THREE ANSWERS THAT CAN DISAGREE, and collapsing them lies**: `refusal`
  is why the CAMERA is not trusted (the exposure lock), `calibration_refusal`
  is why this CLIENT may not measure (this), and `measured_by` names whose
  camera a run would use. A browser session is present, locked, healthy AND
  unable to run a single item — that is not a broken session.
- **`PREFLIGHT_REFUSALS`** (`capture_runs`) is the set every route answers
  409-with-the-sentence to. Add a pre-light gate at the seam and add its word
  there, or it reaches him as a 200 with an empty result.
- **`SessionCameraDouble` DECLARES ITSELF NATIVE** (`capture_settings`), one
  place for the seven fakes — a spec about a RUN must not refuse for a
  reason it is not about. A spec about the browser sets `hello =
  {"user_agent": ...}` explicitly, which is how the gate gets exercised
  rather than modelled. A session that says nothing is NEVER native.

`capture_queue.wait_for_session` waits for present + locked + CALIBRATION-
GRADE, and at the deadline reports the browser's own sentence rather than
`NO_SESSION` — a queue log saying "no capture session" would send a reader
to look for a machine that was plugged in the whole time.

**This closes the fourth of his 2026-09-01 failures** (a cached tab silently
running old capture code) with no machinery of its own: calibration cannot
ride stale browser code because it cannot ride the browser at all. Help:
`browser-is-a-viewfinder`, linked from the Rooms page and the unattended
card. Spec: `tests/test_browser_demotion.py`.

## THE CALIBRATION RECORD, and the POSE FINGERPRINT that gates it

A calibration stops being a ritual and becomes a durable, named,
re-runnable artefact — step two of `/home/javi/fleet-spotfx/data/
calibration-practice-plan/plan.md` §3. **`spectra/models/calibration.py` is
the binding statement for what a calibration IS; `spectra/services/
pose_fingerprint.py` is the binding statement for what the pose check can
and cannot tell apart.** Read both before touching anything here. Five
things:

- **STORAGE IS A DIRECTORY, not a bounded file** — `storage/spectra/
  calibrations/<id>.json`, one file per calibration (`calibration_store.py`,
  atomic tmp+replace, `config.CALIBRATIONS_DIR`, repointed by
  `tests/conftest.py`'s `_isolated_calibrations`). Every other store here
  holds a HISTORY that ages out and a bound is right for it; a calibration's
  LINEAGE is the one thing that must never be pruned, so a single-file store
  would have to choose between capping it and growing unbounded in a file
  every read parses whole.
- **THE TAG REGISTRY IS STORAGE ONLY, and its one number is MEASURED.**
  `Calibration.tags` (`TagRegistration`: ArUco `tag_id`, `measured_side_mm`,
  `mount`) is empty by default, so its arrival changed nothing. **Nothing in
  this build reads it and there is no tag-detection code anywhere here** —
  it is carried from day one so the later vision step lands into a record
  that already holds his measured truth instead of going back to ask for it
  (`tests/test_calibration_record.py` asserts against the SOURCE that
  `pose_fingerprint`/`calibration_runs` never name it, so the day it starts
  being read is a deliberate edit rather than something that quietly became
  true). **MEASURED, never nominal, and that is the whole point**: a printed
  tag whose real side differs from its nominal one SILENTLY SCALES every
  pose it anchors — a driver told "100 mm" when it is 97 reports a camera 3%
  further away and every distance from it is wrong by that factor with
  nothing to notice, the firmware-brightness failure arriving through
  another door. So one physical tag has one size: a non-positive side is
  refused at the model and a duplicate id is refused by name at the route.
  **An ArUco id is only unique WITHIN a dictionary** and the dictionary is
  deliberately NOT invented here — named in `TagRegistration`'s docstring as
  an open question for whoever knows which one he printed, not left as an
  oversight.
- **RUNS GO THROUGH `capture_runs` — the one seam — and acquire nothing.**
  `calibration_runs.run_calibration` checks the pose, then drives the
  declared items through `capture_queue.run_queue`, so the exposure lock,
  the lever self-test, the ambient gate, the witness, the hold ceiling and
  the ownership boundary all apply exactly as they do to a button press.
  `capture_runs.KIND_FINGERPRINT` is a FOURTH run kind and is
  calibration-grade like the other three. **The declared items are validated
  by `capture_queue.parse_items` — the ONE validator**; a second dialect
  that read almost the same would be the drift this codebase keeps learning
  about. **THE NEVER-TAKES-HIS-ROOM BOUNDARY IS UNMOVED** and no piece of
  the design needed an exception to it.
- **THE FINGERPRINT IS ANCHORED ON WHAT CAMERA GEOMETRY ALONE DETERMINES** —
  where a handful of KNOWN FIXTURES land their own light in the frame,
  measured by briefly driving them through `room_mapping._map_one` against a
  throwaway room (the `lever_selftest`/`exposure_test` precedent: nothing
  stored). **Deliberately NOT the ambient scene**, which is the room's to
  change: a fingerprint made of a reference image fires on a moved chair,
  which is the exact failure this exists to avoid. A camera move shifts
  every fixture's image by one vector; a room change moves one and leaves
  the rest put. That asymmetry is the whole discriminator.
- **FOUR VERDICTS, AND EXACTLY ONE REFUSES.**
  `mapping_refusals.POSE_REFUSING` is `(POSE_CAMERA_MOVED,)` — the plan
  requires a moved camera be a named refusal rather than silently
  incomparable data. **`POSE_ROOM_CHANGED` and `POSE_CANNOT_TELL` RUN**, on
  the captain's binding requirement: "he rearranges his own house; a
  calibration refusing because he moved a chair is a system that expires for
  reasons he cannot see." What is withheld in those two cases is the
  COMPARABILITY CLAIM (`CalibrationRun.comparable`), gated on the
  fingerprint matching AND the pinned regime being identical — two
  independent halves that fail for different reasons and are reported
  separately. An explicit press still wins past a camera move and NAMES it
  (`overrode_camera_moved`, the Force Scene precedent) and never re-anchors
  the pose as a side effect.
- **THE SIX TOLERANCES ARE PRE-REGISTERED** (`commission_compare.py`'s own
  discipline): each is DERIVED from something the instrument already
  measures — `CENTROID_TOLERANCE` is two of the 64-wide grid's cells and is
  proven above the instrument's own repeat wobble (measured at ~11% of it)
  rather than asserted. Moving one is a decision about what this instrument
  claims, not a tweak. **`COHERENCE_FRACTION` is a FRACTION of the shared
  shift and not a fixed band, and that was FOUND BY SWEEPING**
  (`scripts/check_pose_fingerprint.py` §1, which is in the suite via
  `tests/test_light_field_checks.py`): a big camera move pushes anchors near
  the frame edge partly out of shot, so their centroids shift LESS than the
  ones in the middle, and judged against a fixed band the most obvious
  camera move there is fell to `cannot_tell` while a small one was named.
  Sweep a boundary before trusting it here; sampling it once passes.

**THE HONEST LIMITS, stated rather than hidden, and every one of them falls
to "cannot tell" and never to a confident wrong answer:** a camera
TRANSLATION produces parallax (near fixtures shift more than far ones), so
it has no shared vector and reads `cannot_tell`; an anchor set that is too
few (`MIN_DISCRIMINATING` = 3) or too clustered (`MIN_ANCHOR_SPREAD`) cannot
discriminate at all and **SAYS SO AT ESTABLISHMENT**, so the weaker answer
months later is a known property of the pose rather than a surprise; and a
whole-frame brightness change (his firmware-brightness trap, one axis over)
is deliberately not attributed to either. The fingerprint reads each
fixture's firmware brightness and NAMES any below full in its notes
(`fixture_brightness.measured_as_is` — Home Assistant's, never written since
2026-10-12), so that class of change is at least explainable on a re-check.

**PROVENANCE IS A READ, NEVER A COPY.** A run records the emitter ids it
produced; the footprints stay in `room_maps.json`, which remains the live
store. `calibration_store.provenance` resolves them against it AS IT IS NOW
— `present` / `superseded` / `missing` — so a calibration pointing at
footprints that no longer exist REPORTS that rather than implying they are
there. **ABSENCE IS A READ** too: a calibration that never ran says so, and
so does a pose that was never taken. The LINEAGE is append-only —
`Calibration.append_run` is the only mutator and there is no counterpart,
and `POST/GET/PUT` are the only routes (**there is deliberately no
DELETE**). A REFUSED run is an entry, `night_run`'s declined-night precedent.

**NOT BUILT HERE, by design:** night-seam integration (step four), the
browser demotion (step six), and any UI, which is why there is no help
topic: an unlinked topic is an orphan by this file's own rule. Spec:
`docs/SPECTRA_SPEC.md` §102; tests `tests/test_pose_fingerprint.py`,
`tests/test_calibration_record.py`, `tests/test_calibration_api.py`.

### AMENDING ONE FIXTURE without spending the evening

Step three (`plan.md` §4, `docs/SPECTRA_SPEC.md` §103).
**`spectra/services/amendment.py`'s module docstring is the binding
statement for when a partly re-measured carrier is honest** — read it before
touching anything that scopes a capture run or replaces a footprint. Six
things:

- **AN AMENDMENT IS AN ORDINARY RUN OF A SMALLER DECLARATION.**
  `calibration_runs.run_amendment` / `POST /api/calibrations/{id}/amend`
  names DECLARED items by his own labels (`GET` publishes them as
  `item_names`) and shares ONE body — `_run_declared` — with
  `run_calibration`, so a gate added there is added to both. Overrides
  (`amendment.OVERRIDABLE`) change CAPTURE parameters for that run only;
  changing `kind` or `room_id` is an EDIT, refused here. A name this
  calibration does not declare is refused BY NAME, never skipped.
- **SUPERSESSION IS PER EMITTER.** `room_mapping.scope_plan` narrows a
  resolved plan (`carrier_ids` / `emitter_ids`, both threaded through
  `capture_runs.run_map` and `capture_queue.QueueItem`, both defaulting to
  None = the whole room and byte-identical to before). A carrier only PARTLY
  re-measured is no longer dropped wholesale; `put_footprint` replaces
  exactly the amended ids and the siblings keep the run that took them.
  A CARRIER-SCOPED item still re-takes its carrier WHOLE, which is what lets
  an amendment change a carrier's granularity without stranding the old
  shape beside the new one.
- **THE GATE, and it is the whole point:** two readings of one carrier may
  sit side by side only when the pose fingerprint **MATCHED** and the pinned
  regime is **IDENTICAL** to the run that took the kept ones. Stricter than
  what stops a full run, deliberately — a full run replaces the whole
  carrier so only its claim against earlier runs is withheld, where a mixed
  carrier's inconsistency is INSIDE its own footprints and nothing
  downstream could notice. Either half failing refuses by name with nothing
  driven, naming the two ways out (`whole_carrier`, or re-anchor the pose).
  **There is deliberately no force flag for it** — `force` runs past a
  measured camera move exactly as for a full run and never past this.
  UNKNOWN PROVENANCE fails it too (a carrier mapped from the Rooms page
  button carries no pose or regime this record knows). When it passes,
  mixing is still never silent (`mixed_carriers` + `amendment_mixed_note`).
- **TWO GRANULARITIES ON ONE CARRIER ARE REFUSED** one level down
  (`amendment_granularity_conflict`) — `RoomMap.drop_carrier_footprints`'
  own invariant: driving both would dim that fixture twice.
- **THE DECLARATION IS APPEND-ONLY TOO.** A `declaration` entry carries the
  WHOLE PRIOR DECLARATION (`CalibrationRun.previous_declaration`, built by
  `calibration.declaration_snapshot` BEFORE the edit): the change sentences
  say what moved and could never rebuild what was there. An edit still
  touches no measurement.
- **THE DIFF** (`spectra/services/calibration_diff.py`,
  `GET /api/calibrations/{id}/diff`) reads THE LINEAGE, not the room map —
  which is why `ItemOutcomeRecord.measurements` exists: the map holds only
  the LATEST footprint, so a diff against it could compare the newest
  reading only with itself. `NOISE_FRACTION` **IS** `exposure_test.
  TIE_FRACTION` (one instrument, one idea of its own noise) and is
  pre-registered, not tuned. It never treats absence as a change and never
  claims a comparison the record does not support.

- **A CUT-SHORT AMENDMENT APPLIES NOTHING** (Admiral's ruling, 2026-09-01,
  §104). What it measured is KEPT in the lineage; the room map is PUT BACK
  exactly as it was (`amendment.Rollback`, `calibration_runs.
  _land_unapplied`, `CalibrationRun.applied=False`). His reason: a partial
  that applies itself leaves his lighting neither the old calibration nor
  the new one but a mixture **assembled by where the clock fell**. It is a
  ROLLBACK on the ONE store (footprints are written per emitter as they are
  measured, so there is no unwritten moment to withhold), it applies to
  EVERY partial amendment day or night, and **a cut-short FULL RUN is
  unchanged and still keeps its partials** — a full run makes no
  kept/taking split claim. `emitter_origin` skips an unapplied entry and
  provenance reports its emitters `unapplied`, never superseded/missing.

**`RUN_KINDS` (`spectra/models/calibration.py`) is a constant for a
reason**: an amendment produces footprints exactly as a run does, so every
provenance/origin/comparability read uses it — a reader still testing
`kind == "run"` reports his newest measurement as belonging to nobody.

Spec: `docs/SPECTRA_SPEC.md` §103; tests
`tests/test_calibration_amendment.py` (both directions, plus a test that
goes RED on the defect it was written for) and
`tests/test_calibration_diff.py`.

