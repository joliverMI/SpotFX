# Devices, timing equalization, A/V sync and S3 ownership

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## Per-device timing equalization + the device page (`/devices`)

His ask (2026-08-28): "Different devices seem to have different network and
physical latencies... tune the per device settings so that they are timed
equally... negative is that it fires earlier", and "we need a device edit
page to edit and create devices... all the parameters that were tunable in
ledfx on one tab, as well as the groupings and namings".

**`DeviceSettings.timing_offset_ms` is OFFSET family (negative = EARLIER)
and RELATIVE ONLY — it can never move the room.** `spectra/models/
device_settings.py` is the field + sign law; `docs/SPECTRA_TIMING_
CONVENTIONS.md` carries its row against every other timing quantity. The
translation is `delay_i = offset_i - min_j(offset_j)`, always >= 0: a
fixture can only be made to WAIT, so "A earlier" is implemented as delay
for everyone else and the earliest device is delayed by exactly nothing.
All-offsets-equal (including the shipped all-zero default) is byte-identical
pacing to before the field existed — asserted at the transport, not claimed.
**Absolute alignment against the sound is still `av_sync_lead_ms`'s job**
(LEAD family, positive = earlier, applied at the trigger poll); the two are
never added with the same sign.

**ONE application point: `fx/devices/__init__.py::_flush_timed`** (the
device flush layer, `fx/VENDOR.md` deviation #24). `Device.update_pixels`
is the only live-path caller of `self.flush()`, so every driver's transport
is covered by it — Hue's entertainment DTLS stream, WLED via its DDP/UDP
subdevice, e131/ddp/udp/dummy. `E131Device.deactivate()`'s own direct
`flush()` of a blackout frame is deliberately NOT routed through it. Held
frames are COPIED (`assemble_frame` can hand back the device's own buffer)
into a bounded deque and released on the next frame's arrival once due — no
timer, no thread in the write path. `fx/device_timing.py` holds the
arithmetic and the process-global delay map; **`fx/` may not import
`spectra/`**, so SPECTRA PUSHES (`device_settings.push_offsets`, called on
every save and at `live_host.activate` against the host's own roster) and
fx never pulls. Proof: `tests/test_device_timing_landing.py` — two dummy
devices on the real pipeline, both light edges measured AT THE TRANSPORT,
byte-identity negative control, and a test that goes red when the seam is
bypassed.

**The device page (`/devices`, `spectra/web/src/devices/DevicesPage.tsx`)
renders a field list it does not own.** `fx/device_schema.py` introspects
each vendored driver's OWN merged `CONFIG_SCHEMA` — the exact validator
`Device.update_config` runs — so the page cannot drift from what the driver
accepts; 19 distinct config keys across the six vendored types, plus the
timing field. ONE TAB (his hard constraint), grouped within it as Base /
Type / Groupings & naming / Timing, where the Base/Type split is derived
from the class hierarchy, not a second list. **`udp` was missing from
`fx.host.VENDORED_DEVICE_TYPES` while its driver was vendored and
registered** — added 2026-08-28, because that set gates the handover
readiness check and offering a type it would refuse to count is a trap.

**TWO WRITE BRANCHES, mutually exclusive by construction** (`spectra/
services/device_console.py`'s docstring is the binding statement): SPECTRA
owns AND the stack is up → every write goes through `fx.facade` (new routes
`GET/POST /api/devices`, `PUT /api/devices/{id}`), which runs the vendored
create/`update_config` and `save_config` in one call; otherwise → the same
validated entry written atomically into `storage/spectra/fx-live/config.json`,
the file the go-day seeder owns and nothing else is writing while the stack
is down. Both branches STATE which ran (`applied: "live" | "stored"`), so an
edit made while the room is dark is never lost and never claimed live.
**DELETE is deliberately not built** — he asked to edit and create, and
removing a device tears down its virtuals and rewrites his scenes.
Groupings are the shared category registry, which maps a CATEGORY to
VIRTUAL ids, so a device's grouping is its virtuals' membership; a category
is never invented from a typed name.

**Measuring it: `/avsync`'s PER-DEVICE mode** (`av_sync_pattern.
PatternDriver.start(device_id=...)` narrows the flash to the virtuals ONE
device backs and leaves every other virtual playing the show — the
"later per-category selector" that module's docstring always flagged).
`spectra/services/device_equalization.py` turns a set of those runs into
proposed offsets and is the binding statement: the shared audio path
cancels in the BETWEEN-DEVICE differences, so those are the answer; the
SLOWEST device is the reference, so every proposal is a WAIT (>= 0,
positive = later) and nothing is asked to fire before its frame exists;
and **today's applied delay is subtracted back out of each measurement**
(`intrinsic = av_offset - applied_delay`) — the per-device analogue of the
room lead's add-don't-assign rule, without which every re-measure would
chase its own tail. It NEVER writes: `GET /api/av-sync/device-proposal` is
read-only and applying is his press per device through
`PUT /api/devices/{id}/timing`. Equalizing moves the whole room later by
the spread; that global shift is absorbed by the EXISTING room
re-measure + apply loop, and every result says so (`after_note`). His
Hue-slower-than-WLED belief is a hypothesis this measures — nothing in the
arithmetic knows a device's type.

**`storage/device_categories.json` IS NOT UNDER `SPECTRA_STORAGE`** —
`fx.device_model.CATEGORIES_FILE` is a fixed repo-relative path, so
`SPECTRA_STORAGE_DIR` does NOT repoint it. An isolated instance run for a
screenshot writes the WORKTREE'S REAL registry the moment anything touches
the device page's grouping controls (found doing exactly that, 2026-08-28 —
one virtual silently left a category). Set `device_model.CATEGORIES_FILE`
explicitly, or check the file back afterwards.

**ONLY THE DEVICES HE USES ARE LISTED BY DEFAULT** (2026-08-28, his ask:
"only devices i use should be visible on default. can show more with
expansion tab"). `spectra/services/device_usage.py` is the rule and the
binding statement: a device is IN USE iff it backs a virtual in
`room_topology.genuinely_driven_virtual_ids()` — the compiler's own ground
truth, computed AT REQUEST TIME and never stored, so adding a device to a
grouping or a scene moves it into the default view on the next load with
nothing to migrate. Type is never consulted: 2 of his 10 in-use devices are
DUMMIES (`gap-crystal-mapper` in the mapper chain, `radial-dummy`) and 11 of
21 are LedFX-seed machinery (gap placeholders, mask/foreground/background
layer dummies) plus one genuine duplicate. An EMPTY ground truth means NO
restriction (a fresh install shows everything, never an empty page). The
listing still returns EVERY device with `in_use`/`duplicate_of` stamped on
it — hiding is the page's default view, not a server-side omission — and
`usage` carries the counts so the expansion control can name the hidden
number. Duplicates (same name + same type + backing nothing) are FLAGGED,
never deleted; the page deliberately has no delete. `/devices` and
`/avsync`'s per-device rows share the one server flag. Help: `devices-in-use`.
Spec: `tests/test_device_usage.py` (his real 21-device config shape, the
10/11 split, and the liveness proof).

**Sonic parity**: a `device` domain (`device_console.OPERATIONS`, 11 ops)
merged into `settings_agent.ALL_OPERATIONS` — remember the hand-written
`settings_mcp_server.py` wrapper per op AND the CLI fixture manifests
(`tests/fixtures/cli_transcript_synthetic_*.json`), where the three
`_scene_*` and the three original real captures are DELIBERATELY STALE
(tests assert they are refused) and must not be "fixed". Help:
`devices-page` (+ `device-timing-offset`, linked from the page).

**Category CRUD was a real gap until 2026-10-09** (the Admiral asked
Sonic to "add a device category called 'Single WLED' and put the porch
rail and dining table in it" and it couldn't) — `set_device_categories`
only ever edits an EXISTING category's membership, by design (a typo
must never invent one), so there was no operation that could create the
container itself. `create_device_category`/`rename_device_category`/
`delete_device_category` (+ `list_device_categories`) close that gap,
resolving a category BY NAME via `name_resolve.resolve_name` (the Force
Scene/Force Colour precedent) rather than an opaque id; a name already in
use (case-insensitive) is refused on create/rename rather than minting a
silent duplicate. His actual ask was done by hand first (`POST
/api/device-categories` on the root process, the app's own category
CRUD API — categories live in `storage/device_categories.json`, read by
`fx/device_model.py`, written by `services/device_category_service.py`
on spot-effects' side): the "Single WLED" category holds the
`single-color-effect` virtual, which — checked first, not assumed —
backs ONLY the `porch-rail` and `dining-table` WLED devices and nothing
else, so no virtual-routing change was needed to give those two their
own category.

## A per-LED `pixel_map` on a device (the TV ring, 2026-11-12)

`fx/devices/__init__.py` (VENDOR.md #93): every device accepts `pixel_map`
(default empty) — physical LED i shows effect pixel `pixel_map[i]`, applied
in `assemble_frame` after `center_offset`, for every effect alike; a bad
map is ignored with one warning. Why it exists: `tv-mapper` is a COPY-
mapped virtual (the 560-px TV strip + two kitchen sconces), so a sconce ring
gets the whole 560-px picture resampled and looks radial, while the TV got
it one-to-one along its frame. `scripts/tv_ring_pixel_map.py` (dry run /
`--apply` / `--revert`, a backup, DJ applies at deploy) builds the TV's
table from the strip's REAL geometry in `config/tv_backlight_layout.json`
(HyperHDR's LED layout read off the strip's own Pi, 2026-11-12:
one clockwise loop seen from the front, LED 0 at the bottom-right corner,
0–199 left along the bottom, 200–259 up the left edge, 260–479 right along
the top, 480–559 down the right; River: DDP pixel i IS physical LED i, no
remap) — each LED shows the strip pixel at its ANGLE about the screen
centre (aspect-corrected), a permutation of 0..559; the old `center_offset`
90 is folded in and set to 0. The strip is the Pi stand-in (WLED 16.0.1
emulation, `product tv-strip-standin`); the fixture's own geometry lives
there, not in any SpotFX store. A `spectra` restart loads the new device
config (the restart hazard in AGENTS.md applies). Help topic
`tv-ring-mapping`; proof `tests/test_star_improve.py`.

## SPECTRA phone A/V-sync instrument (`/avsync`) — MEASURE the audio/visual offset, don't argue it

`spectra/services/av_sync_{correlate,audio_ref,pattern,session}.py` +
`spectra/api/av_sync.py` + `spectra/web/src/avsync/` (built 2026-08-22,
PR fm/phone-audio-video-capture-for-measured-a-7b; `docs/SPECTRA_SPEC.md`
§93). His phone's mic + camera are reduced ON THE PHONE to two number
streams (raw media never leaves it) and correlated server-side against
SPECTRA's own live audio hub (`live.hub`, snapcast.monitor = speaker
time, server timestamps) and a light reference (a random-hold white flash
PATTERN driven over fx_seam with snapshot/revert, or the show's own
writes). Result: `av_offset_ms` (positive = lights BEHIND the sound,
negative = AHEAD — the sign row is in `docs/SPECTRA_TIMING_CONVENTIONS.md`,
it is neither LEAD nor OFFSET family, it is a MEASUREMENT) plus a
statistical ± and NAMED systematic terms with direction; a weak/ambiguous/
unstable correlation REFUSES by name, never guesses. The measurement is
still never applied automatically — see the APPLY section immediately
below for the button that closes the loop on his press. Three things to
know before touching it: (1) the
flash pattern's RANDOM holds are load-bearing (a periodic blink is refused
as ambiguous by design) and the light correlation is on signed EDGES, not
levels (`av_sync_correlate.signed_edges` docstring has the measured why);
(2) the ONLY file it writes is `storage/spectra/av_sync_measurements.json`
(numbers + statement, last 100) — keep it that way, the privacy statement
in help topic `av-sync-privacy` promises it; (3) **camera/mic need a
secure context** — since 2026-10 he reaches SPECTRA at
`https://serenity.tailb5ca89.ts.net` (`tailscale serve` → :8000, see
`docs/SPECTRA_PROCESS_SPLIT.md`'s "His remote path"), a secure context;
the page still detects a plain-http origin and names the two fixes
(Chrome's per-origin flag, or HTTPS in front of :8000 — which is what the
serve route provides) for anyone reaching it another way. The vision/ArUco stage is deliberately NOT built — only its seam
(`FrameRing`, frame tap OFF by default) is. Proof without a room:
`scripts/check_av_sync.py` (simulated rooms through the real code);
`tests/test_av_sync_*.py`.

**THE CAMERA NEED NOT BE A PHONE (2026-09-07, PR fm/spectra-avsync-on-
kiosk-brio-mic).** `spectra/capture_client/avsync_session.py` is a SECOND
client speaking the identical wire from a fixed kiosk camera with the
Brio's own built-in microphone beside it — `--avsync` on the existing
capture client, whose mapping path is untouched (a different mode, taken
before the mapping camera is even constructed). **The server correlation,
references, clock map, statement and refusals are unchanged**; the only
server edit is five `hello` keys the record now KEEPS (`source`/`client`/
`client_version`/`host`/`pose_name`) so a stored measurement says which
camera took it instead of reading like a phone run. Three things before
touching any of it:

- **The reductions are the whole payload and they are pure stdlib**
  (`avsync_reduce.py` is the binding statement): one log-energy dB per
  ~11 ms hop, and per frame one mean + a 4x4 grid of region means. The
  browser's 32x24 canvas is deliberately NOT reproduced — a box-mean
  downscale followed by a proportional partition gives the same region
  means as the partition alone, so the grey8 frame is partitioned
  directly with the browser's own index arithmetic (asserted against a
  line-for-line port of `luminanceOf`, not argued). Measured cost 0.72 ms
  a frame + 30 us a hop, which is why there is no numpy and why
  `check_capture_client_deps.py` still holds at httpx + websockets — that
  script now names EVERY client module, because these three are imported
  lazily and a package-level import would never have asked the blocker
  about them.
- **THE AUDIO CLOCK IS THE FRAGILE PART, and it is where a silent wrong
  answer comes from.** `avsync_reduce.SampleClock` maps sample INDEX ->
  monotonic seconds through one anchor, taken as the MINIMUM over the
  warm-up reads (`ClockMap`'s own min-RTT discipline) and then FROZEN —
  an anchor that keeps improving puts a step in the middle of the window
  being correlated. Stamping a batch when the read returned instead moves
  the answer ~88 ms with nothing downstream able to notice; that is one
  of the two RED CONTROLS in `scripts/check_avsync_kiosk.py`, and the
  other is a flipped sign. Do not "simplify" either away.
- **It reports `capture_time_available: false` and `latency_s: null` on
  purpose.** A v4l2 pipe cannot say when a frame's photons landed, so the
  server names the camera-pipeline term (80 ms, lights_look_later) and the
  microphone term (40 ms, lights_look_earlier) rather than a correction
  nobody measured; they push OPPOSITE ways and are constant for one camera
  in one place. Claiming a capture time here would silently delete the
  larger of the two. **`arecord` has never met a real ALSA device on any
  build machine** (recorded in `docs/CAPTURE_CLIENT_HOST.md`'s ledger);
  every way that can be wrong is a named refusal and a non-zero exit,
  never a silent envelope of zeros. The microphone is bound BY NAME
  (`plughw:CARD=BRIO,DEV=0`), never a card index — that is USB
  enumeration order, not a fact.

Launching it, and the preconditions: `docs/UNATTENDED_CAPTURE.md`'s "THE
OTHER INSTRUMENT" section (SPECTRA must own the lights and music must be
playing, or the client refuses BEFORE flashing his room).

### Applying it: `RoomControlState.av_sync_lead_ms` — the ONLY authored term in SPECTRA's fire clock

Built 2026-08-28 (PR fm/avsync-apply-button, his ask: "when I run avsync
how do I update the offset value based on that data?"). **Read
`spectra/services/av_sync_lead.py`'s module docstring before touching
anything here — it is the binding statement** (the sign law, the
add-don't-assign translation, and why the two lookalike settings are
different jobs). The short list:

- **THE TARGET HAD TO BE CREATED, because it did not exist.** Before
  this, SPECTRA's fire clock had exactly ONE correction term and it isn't
  authored: `bridge.effective_position_ms()` = raw position +
  `shape_offset_ms` (spot-effects' machine-learned per-song xcorr number,
  which WANDERS mid-song). `spectra/config.py` and `RoomControlState`
  carried no latency/offset/lead/delay field at all.
- **The two numbers that LOOK like the target are different jobs, not
  older values of this one** — worth knowing before anyone "reuses" one:
  `settings.audio_latency_ms` (root, LIVE) aligns WAV capture boundaries
  for the xcorr training corpus and is **the number he remembers as
  "150"**; `settings.ledfx_trigger_buffer_ms` (root, LEAD family) is
  LedFX-HTTP write-transport compensation read ONLY by the retired legacy
  engine, and holds an inert **−800** on his box. Neither is reachable
  from `spectra/` anyway (import discipline + the read-only bridge), and
  nothing in the apply path may seed from either — pinned by a test.
- **LEAD family, positive = fire EARLIER**, applied as a clock shift at
  **exactly one place**, `spectra/services/engine.py`'s trigger poll, via
  `av_sync_lead.show_clock_ms(...)`. A second application point is the
  thing to never add; `tests/test_av_sync_apply.py` greps for one.
- **`None` (default) means NEVER CALIBRATED, deliberately not `0`** —
  identical at the light, different in the dialogue ("none yet" vs
  "0 ms"), so nothing about his show changed on deploy and no borrowed
  number is ever shown as a previous value of this one.
- **The translation ADDS, never assigns**: `proposed = current +
  round(av_offset_ms)`, because the measurement is taken with the current
  lead already running. Assigning would undo the previous calibration on
  every re-measure. Worked examples both directions are in the
  `av_sync_lead_ms` row of `docs/SPECTRA_TIMING_CONVENTIONS.md`.
- **The write is his press through `PUT /api/room-controls`** (the
  established save path, one field, then a real GET read-back — a PUT
  echoing its own body is not a read-back). Server-side
  `GET /api/av-sync/apply-proposal` owns the sign translation so the page
  renders it and never re-derives it — the flare-preview inverted-sign
  precedent. Excluded from Sonic's registry on `force_scene_*`'s own
  precedent. UI: `spectra/web/src/avsync/ApplyOffsetDialog.tsx`, help
  topic `av-sync-apply` (linked, not orphaned).
- **PROOF BAR: a setting that reads back is not evidence.**
  `tests/test_av_sync_lead_landing.py` measures the LIGHT EDGE moving on
  the real render pipeline (the §84 landing-instrument pattern through
  `fx.headless`) by exactly the amount set, both directions, with an
  uncalibrated negative control — and was verified to go RED when the
  clock shift is removed. Any future change to how this setting reaches
  the show must clear that bar, not a round-tripped JSON value.

## A LIGHT WE ARE STREAMING TO THAT IS NOT LIT (`dark_fixture_watch.py`)

**`spectra/services/dark_fixture_watch.py`'s module docstring is the binding
statement.** Read it before touching anything that claims a fixture is
healthy. His `tv-backlight` (WLED, 560 px, the Living Room's only capture
carrier) went dark under SPECTRA's stream twice — `on=false` while streaming
at ~54 fps (2026-08-15) and off the network entirely under the same take
(2026-09-06) — and **every** reading we serve said FINE both times. Five
things:

- **THREE SIGNALS THAT LOOK LIKE HEALTH AND ARE NOT.** (1) `live_host.
  probe_device_live` asks WLED's `json/info` for `live`, which means
  "realtime data is arriving" and is TRUE of a switched-off fixture — his
  2026-08-15 state passes it. (2) `activation_report.recheck()` re-asks only
  devices already named dark AT ACTIVATION (`report.still_dark`), so by
  construction NOTHING in this codebase re-probed a confirmed device; a
  light that was fine and then went was invisible forever. (3) liveness's
  `devices[].online` is `Device._online`, set True when the driver is built
  and cleared only by an `OSError` out of `sendto`, which a UDP unicast to a
  dead host does not raise — and the payload read `bool(d.is_online)` on the
  **METHOD OBJECT**, i.e. hardcoded `true` for every device on every
  response (fixed here; the honest limit above still stands, so never read
  it as reachability).
- **BEING STREAMED IS THE PRECONDITION, and it is what keeps the two
  detections from claiming the same silence.** `live_host.LiveLights.
  streaming_device_ids()` is devices behind a virtual that is active AND
  flushing fresh frames, onto an active device — "we are writing light into
  this fixture right now". A fixture nobody writes to may be off; a virtual
  that stopped flushing is `activation_gaps`' business, already named there.
- **ONE READ, TWO JUDGEMENTS.** `LiveLights.read_emission` is the single
  definition of what a fixture is doing (`json/info` for `live`/`lip`,
  `json/state` for `on`/`bri` — WLED splits them, `fx/VENDOR.md` #8).
  `probe_device_live`'s judgement is UNCHANGED (unreachable or `live=false`
  = an activation gap) and asks with `read_state=False`, deliberately: the
  activation gate is a poll-until-live loop and must not add HTTP load to a
  fixture during its own come-up ramp. The watch's judgement adds
  `on=false` / `bri=0`. **The `unreachable` kind claims only what the read
  established** — no reply within `HTTP_TIMEOUT_S` (3 s), which is handed
  to the vendored transport explicitly (`WLED._wled_request(timeout=)`):
  its own default is 0.5 s, and a budget that only bounds the outer
  `wait_for` never binds (the first shipped version declared 3 s and
  decided at 0.5 s). Its sentence says "not answering", never "dark" — a
  controller too busy taking the stream to answer HTTP reads the same as
  one off the network. `probe_device_live` keeps the vendored default
  (`http_timeout_s=None`), so the activation gate's timing is
  byte-identical. **The read is OFF THE EVENT LOOP** — `fx.utils.
  WLED`'s methods are `async def` wrappers around blocking `requests`, so
  awaiting one parks the loop that drives the bridge poll, the trigger tick
  and every WS broadcast; a sweep over dead fixtures would stall all three.
  Proven, not argued: `test_a_dead_fixture_does_not_stall_the_event_loop`.
- **IT NEVER WRITES, and that is structural** (the backlog's own ruling,
  "BUILD THE DETECTION, NOT THE CURE"): no power-on, no refresh-rate change,
  no driver re-init, no release. Repair already has owners
  (`activation_report.recheck`, `device_relocation`); a second, differently-
  motivated writer is how two mechanisms start fighting over one light.
  `test_it_writes_nothing_to_the_fixture_ever` asserts the stub fixture saw
  GETs and nothing else across a whole raised fault.
- **NAMED, NEVER `healthy`.** It lands on `GET /api/liveness` →
  `dark_fixtures`, `GET /api/ownership` → `dark_fixtures` (the room bar's
  `DarkFixtureStrip`, beside the activation strip), `GET /api/engine/status`,
  and a CRITICAL log. It is additive and informational ONLY — the systemd
  dead-man and the fleet checker read `healthy`, and a restart cannot switch
  a light back on while it certainly would darken the ones that work (the
  owner's own 2026-08-21 partial-activation trade). Threshold
  `FAULT_AFTER_S`=60 s over ≥3 reads at a 30 s sweep, so ≤90 s to name and
  no accusation on one noisy read. **An UNKNOWN reading never clears a
  named fault** — a lost `json/state` reply (json/info still answering) is
  listed as `unchecked` and leaves the suspicion and its clock untouched,
  and so is the reader itself raising; only a read that positively says
  lit clears one. The summary line counts only reads that positively said
  lit as "confirmed lit"; its "reading dark or not answering, not yet
  named" clause is built from the STANDING suspicions, not this sweep's
  reads, so a watched fixture stays in the sentence across a lost reply;
  and "not checkable" is said only of a device that cannot be asked at
  all (`uncheckable`), never of a lost reply or reader crash on a fixture
  we can ask (`unchecked this sweep`). The per-fault ages on the strip
  and the Status page are TWO clocks with two labels: "last confirmed
  dark" (`last_checked_age_s` = the last read that positively said dark
  or did not answer — an unknown read does not move it) beside "watch
  swept" (`last_sweep_age_s`), so a light dropping replies is visibly
  different from a stalled watch; never label both "last read". The four
  timing constants have their row in `docs/SPECTRA_TIMING_CONVENTIONS.md`'s
  master table, per that document's own rule. Stands down entirely
  (dropping every suspicion) while the stack is down, SPECTRA does not
  own, a preview/capture hold has the room, or the engine is dark.

**ROOT CAUSE, as far as an offline investigation can honestly go: nothing in
the SPECTRA write path distinguishes .236 from the WLEDs that survive.**
`WLEDDevice.flush` → `DDPDevice.flush` → `send_out` is one code path with no
per-device branch; packet shape is a pure function of `pixel_count`
(560 px = 2 DDP datagrams/frame, ~120/s and ~100 KB/s at the default 60 fps)
and his heavier fixtures send strictly MORE through the same code without
dropping. The fault tracks the STREAM (appears on activation, clears on
release), which is the signature of a controller saturating, not of a wrong
address or a malformed packet. **What DID change on SPECTRA's side is the
rate, and it changed for a good reason**: before the S3 process split her
render threads were frozen by spot-effects' 90 ms–5 s GIL bursts, and the
split plus `sys.setswitchinterval(0.001)` measurably restored them to ~57 fps
(see the S3 section above). A fixture that used to receive a stuttering,
starved stream now receives a steady one at its configured rate — his
observed ~54 fps. That is the fix working, not a defect; but it is the best
available answer to "why SPECTRA, why now", and it is what makes the
per-device rate the right correction rather than a workaround.
**The SPECTRA-side lever therefore already exists and needed no code**: `refresh_rate` is a per-device config field
(base `Device.CONFIG_SCHEMA`, default 60) editable on `/devices`, and
`Virtual.refresh_rate = min(device.max_refresh_rate ...)` — lowering it on
that one device halves its datagram rate. **Its trade, named**: that `min`
means the whole virtual slows, so on his copy-mapped `tv-mapper` it would
also slow both kitchen sconces (the sibling-capping problem open PR #58 is
about). No throttle was invented next to a knob that already works.

**FLAGGED, NOT BUILT: the unified detection.** This watch generalises
cleanly to the other carded blind-spot defects (`spectra-dark-fixture-
detection-unified`) — the read, the streamed-to precondition, the
persistence threshold and the surfacing are all defect-agnostic. That is a
shape decision for firstmate/the captain, not one to take in passing.

**ADJACENT FINDING, REPORTED AND NOT FIXED**: `ownership_reconciler.
_foreign_wled_sources` reads `wled.get_state()` and tests
`wled_state.get("live")`, but WLED reports `live` under `json/info` ONLY
(`fx/VENDOR.md` #8). That foreign-writer check is dead and can never fire.
Same family, but it is ownership logic and deserves its own card.

Spec: `tests/test_dark_fixture_watch.py` (real `fx.headless` render host,
real production `fx.utils.WLED` transport, a real HTTP fixture that can be
taken dark or off the network out of band; the founding test asserts every
OLD signal still reads healthy over his exact 2026-08-15 state before
asserting the watch names it, and a test proves the pre-fix rule names
nothing). Help: `dark-fixture-watch`.

## SPECTRA param orphan watchdog (the safety net under momentary releases)

`spectra/services/param_watchdog.py` (own supervised task in `spectra/app.py`'s
lifespan, his ask 2026-08-21 after an effect was left stuck running backwards:
"some kind of watchdog system to make sure that parameters are set correctly
like that"). Every 10s it compares each engine-tracked virtual's LIVE effect
config (read off the in-process host under the effect's own lock) against the
conductor's `VirtualState.param_baseline`, and restores any param away from
baseline with NOTHING holding it for 30s continuously — loudly (WARNING log
naming virtual/param/found/restored/age, `fire_history` bucket `"watchdog"`,
`engine.status()["param_watchdog"]`, an additive `param_watchdog` key on
`GET /spectra/api/liveness`, never part of `healthy`). Read its module
docstring before touching anything that moves a param outside the engine's
bookkeeping — three things to know: (1) **"nothing holding it" is three
structural holders** — a pending release (`ResponseEngine.pending_release_keys`),
a drift mechanism owning the param, a tween in flight on the live effect — and
**the permanent/momentary discriminator is `param_baseline` itself**: a
permanent kind's carry moves the baseline (`conductor.on_surge`), a momentary
kind never does, so the watchdog cannot fight an authored permanent flare by
construction. The restore target is `ResponseEngine.release_target` — a thin
wrapper over the SAME `_carried_value` `flush_releases` uses; never introduce a
second definition of "baseline" next to it (`flush_releases` additionally falls
back to an entry's spike-time `return_to` for a param with NO baseline at all —
a never-authored param — which the watchdog deliberately keeps no opinion on;
`_pending_releases` holds `PendingRelease` dataclass entries since
fm/reverse-flare-glide-and-stuck, owned per fire and armed at spike landing —
see the "reverse flare's ~2x dwell overrun" entry above for why). (2) **`background_brightness`/
`background_color` are out of scope by name** — the conductor's own colour-set
landings write them to the wire WITHOUT moving `param_baseline` (a pre-existing
bookkeeping gap, left alone), and Dark/Light mode own both keys too; `brightness`
is compared against baseline × any `brightness_multiplier` seen since the last
scene fire (the dimmer doesn't rewrite live brightness until the next write —
also pre-existing). If you add a NEW writer that moves a baselined param outside
the engine's carry (another fx_seam path, a new room mode), either move the
baseline with it or gate/exclude it here — otherwise the watchdog will, after
30s, correctly-by-its-own-lights undo it and log an orphan. (3) It stands down
entirely while the engine is dark, the live stack is down, or `preview_pause`/
`flare_preview_hold` is active. A restore that doesn't take is retried at most 3
times then given up on at CRITICAL (named in status) until the next scene fire —
a "PARAM ORPHAN NOT TAKING" line means something keeps re-moving the param or the
schema rejects the write; find that, don't tune the watchdog. Module-global state
(no DI seam — `tests/conftest.py`'s autouse `_isolated_param_watchdog` resets
it); the `Deps` dataclass is the injection seam. Spec:
`tests/test_param_watchdog.py`; timing constants recorded in
`docs/SPECTRA_TIMING_CONVENTIONS.md`; `docs/SPECTRA_SPEC.md` §90.

## SPECTRA dynamic colour on songs with no authored trigger (2026-09-25)

His report: colour barely drifts on analysed-only songs. Three changes:

- **A same-scene re-fire keeps colour custody** (`DriftConductor.is_refire`/
  `refire_palette`, called from `scene_compiler.fire_scene`'s live branch):
  same scene id AND same colour set (`None` = the room's active set) keeps
  the journey's destination and wears the palette the room is SHOWING, not
  the set's unrotated hues. Mechanisms still re-baseline; a different scene
  or set clears the bearing as before. Trigger-driven picks never exclude
  the current scene, so this is common.
- **Every GENERATED `fire_scene` cue on a song with no authored trigger
  lands a colour moment** (`trigger_engine._fire_analysed_color` →
  `engine.fire_analysed_color_event` → `ResponseEngine.analysed_color_jump`)
  whether the scene fired, re-fired, was dwell-deferred or picked nothing.
  It runs AFTER the scene fire in the same `_fire` call and glides over the
  scene's own crossfade (`scene_transition_lead.crossfade_ms_for`), so its
  middle lands on the mark like the scene's. Precedence is in
  `analysed_color_jump`'s docstring (deferral > force colour > gradient kick
  > live rainbow > the existing `_color_jump`). The trigger-engine hook
  defaults to a NO-OP and is wired in `engine.py`, like `_intensity_event`.
  "Untriggered" is `TriggerEngine.song_untriggered()` (reuses `tick()`'s own
  read; `None` when unknown, which never counts as untriggered).
- **The trigger-timed colour journey REPLACES the untriggered-song gradient**
  (2026-09-26, the Admiral: "Shouldn't [the journey] have a destination
  based on when the next trigger is going to hit" / "yes, replace").
  `untriggered_gradient_enabled`/`_id` are RETIRED (dropped on load);
  `effective_gradient_id()` is now just the manual `active_gradient_id`.
  `color_journey.py`'s TRIGGER-TIMED section is the binding statement. The
  horizon is `TriggerEngine.next_colour_cue()` — exactly what `tick()`
  would fire (same effective mode + `_trigger_allowed`), narrowed to
  `fire_scene`/`select_color_set`, with the analysed plan's kept cues
  standing in before auto-generation (`analysed_flares.
  scene_change_moments`, the ONE list `GET /api/analysed-plan` also
  uses); `None` on a stale show clock (`POSITION_STALE_S`). The conductor
  paces to ARRIVE on it (`color_journey.timed_pace`, 2-720°/min), the last
  leg glides over exactly the time left, arrival commits the destination
  as `active_set_id` (so the cue's scene fire wears it) and holds until the
  cue passes; a fired cue calls `conductor.on_colour_cue` (wired in
  `engine.py`), which re-plans after `CUE_SETTLE_S`. The analysed colour
  jump AGREES with it (`conductor.cue_destination`): arrived → no jump,
  not arrived → it lands the walk's set. Spec:
  `tests/test_timed_colour_journey.py`.

Spec: `tests/test_dynamic_colour_untriggered.py` (includes his real Wonder
cue list), `scripts/check_drift.py`. Help: `journey-refire`,
`journey-destination`, `analysed-colour-jump`.

## SPECTRA two-dimensional drift gradient + Rainbow select

Owner ask 2026-08-20 (`data/two-dimensional-drift-gradient-and-rainb-imfg/
HIS-VERBATIM-WORDS.md`). Two independent features, one PR.

**The 2D drift gradient**: `spectra/models/gradient2d.py` (`GradientProfile`:
`top`/`bottom`, each the SAME "#rrggbb or linear-gradient(...)" string every
colour value in this app already uses — his ask "very similar to the
current gradient picker, just make it a square" is literal: each edge
reuses `ColorGradientPicker` verbatim, `GradientEditor2D.tsx` just stacks
two of them with a square bilinear preview between; `x_mode: "loop"|
"bounce"`, pure `sample()`/`advance_x()` — no spot-effects import, local
reimplementation of the stop-parsing grammar `spectra/services/
color_rotate.py` already established the precedent for). Stored/picked
exactly like a sequencer curve profile (`spectra/services/
gradient2d_store.py`, `storage/spectra/gradients2d.json`,
`GET/PUT /api/gradients2d`) — **not** via `CurveAttachmentEditor.tsx`: a
gradient has exactly ONE room-level attachment point
(`RoomControlState.active_gradient_id`), not a per-entry map, so the
one-off/shared-profile machinery that shape needs doesn't apply; editing is
a local draft with two explicit buttons, "Save" (overwrites its own id) and
"Save as new…" (forks a fresh id) — his literal "save as new or overwrite"
wording, not a detach/revert dance. UI: `DriftGradientBar.tsx`, mounted in
`RoomControlsBar.tsx`'s top-bar group-button row.

X is time, Y is intensity, vertices only at top (y=1) and bottom (y=0),
linear between — **along the hue wheel, never in RGB** (`gradient2d.
_lerp_hex`, mirrored by `lib/gradient2dSample.ts` for the square preview,
parity: `node scripts/check_gradient2d_hue_blend.mjs`): an RGB mix of two
distant hues lands near grey, and a Hue bulb renders grey as WHITE — his
2026-09-26 "blending through white" report. Explicitly **not** rotation (he pre-empted the
misreading himself). Wired into `drift_conductor.py`'s `tick()`: an active
gradient **replaces** the wheel-based colour journey for that leg (held
exactly like a live rainbow palette already holds it — a different colour
source has taken over), never runs alongside it. X advances a fixed
fraction of `RoomControlState.gradient_x_period_s` every leg, looping or
bouncing per the gradient's own `x_mode`; Y drifts toward a target
(`RoomControlState.gradient_y_slew_s` paces it) rather than snapping.
**The "ahead of arrival" problem, his proposal, adopted as-is** (asked to
propose, said "if this is a good starting place, just go with it"): the Y
target changes only on a trigger firing or an analysed song transition
firing, not continuously every leg — `DriftConductor.on_intensity_event()`
re-anchors the target to the live intensity at that moment;
`trigger_engine.py`'s `_fire()`/`_fire_transition()` call it via a
constructor injectable (`intensity_event`) whose **default is a safe
no-op**, deliberately NOT a lazy import of the production `engine.conductor`
singleton the way `fire_scene`/`fire_response` are — those are the subject
of every trigger_engine test and always explicitly stubbed; this one small
side call is easy to forget to stub, so its own default costs nothing when
forgotten. Production wiring is one explicit line in `services/engine.py`
(`trigger_engine._intensity_event = conductor.on_intensity_event`), the
same place that module already owns constructing the `conductor`/
`responses` singletons. Flares are UNCHANGED — a flare colour jump
(`scene_response.py`) still writes `state.gradient`/`background_color`
directly via `apply_color_set`'s instant jump; the next gradient leg's own
ABSOLUTE `(x, y)` sample (not a delta) simply overwrites it on its own
20s-leg schedule, the same way the wheel journey's rotation already gets
overwritten-then-resumed around a flare jump.

**Any new test/script that calls `DriftConductor.tick()`
must pass `room_controls=`/`gradient_profiles=` explicitly (or isolate
`scfg.ROOM_CONTROLS_FILE`/`GRADIENT2D_FILE` under its own temp
`SPECTRA_STORAGE`)** — `tick()` now reads `room_controls().active_gradient_id`
on every leg to decide the branch above, so an unstubbed default silently
touches real storage (`spectra/services/drift_conductor.py`'s own
`_default_room_controls`/`_default_gradient_profiles` lazy-import the real
stores, matching every other `_default_*` injectable in that file). Found
this while adding the feature: `test_spectra_engine.py`'s shared `_engine()`
helper had to gain `gradient_profiles=lambda: {}` +
`room_controls=lambda: rc.RoomControlState(...)` for exactly this reason —
copy that shape, don't rediscover the gap.

**Rainbow select**: `models/color_set.py` `ColorSetCard.is_rainbow`
(mirrored in `spectra/services/color_sets.py`'s read-only projection — the
usual "defined twice" trap) is **ENUMERATED, never inferred from name** —
his own instruction, since several of his other sets have colourful names
and are not rainbows. Exactly five cards are marked: Hype 1, Hype 2,
Hype 3, the Hype group, Black Hole Rainbow —
`scripts/mark_rainbow_color_sets.py` (dry-run default, `--apply`, raw-dict
patch + backup, matches `set_scene_colorset_preference.py`'s convention;
not run against live storage by this build). `RoomControlState.
rainbow_select_limit` (default 0.9, his words) — above it, automatic
colour-set selection is restricted to `is_rainbow=True` cards only; at or
below it, to `is_rainbow=False` ("single") cards only — a clean exclusive
partition (`spectra/services/rainbow_select.eligible()`), never both, never
neither. Wired into `scene_sequencer._default_eligible_sets` (and
`scene_sequencer.automatic_pool_cards`, which the drop colour change
reuses) — the SAME one automatic-selection choke point
`mode_availability`/`color_set_preferred` already reach, following that
established precedent. As of 2026-11-11 (owner report: rainbow sets kept
appearing on flares even at low Energy) `scene_response`'s flare
colour-jump pool (`_default_eligible_sets`) applies this gate too, at the
flare's own intensity — it still deliberately does NOT apply
`mode_availability`/`color_set_preferred`, out of that fix's scope.
`drift_conductor`'s destination pool remains the one pool with none of the
three gates (checked, not an oversight). A Group card is never itself a selector
candidate here (unchanged, pre-existing), so a Group's own `is_rainbow`
mark has no effect on this gate — it exists for completeness/authoring
symmetry only. UI: `RainbowToggle.tsx` on `ColorSetsPage.tsx`, next to
`ModeAvailabilityToggle`; the limit lives in `DriftGradientBar.tsx`'s panel.

Neither feature is deployed against his live room by this build — land and
verify only. Specs: `tests/test_gradient2d.py`,
`tests/test_drift_conductor_gradient.py`, `tests/test_rainbow_select.py`,
`tests/test_gradient_retarget_hook.py`, `tests/test_mark_rainbow_color_sets.py`.

**Every linear-gradient in this app is HORIZONTAL by convention (`90deg`),
and the angle carries NO engine meaning anywhere** — `spectra/models/
gradient2d.py::parse_stops` discards the head segment before the first
comma, `spectra/services/color_rotate.py` passes it through verbatim, and
the vendored `fx/color.py` parses it into an `angle` attribute no effect
reads (grep-confirmed). It decides only how a value PAINTS as CSS, which is
why a stray vertical angle showed up as his 2026-08-25 report: the 2D
gradient editor's edge strips (a wide 22px bar) painted across the bar
instead of along it. Cause, measured live against the real widget (not
inferred): react-gcolor-picker bakes its OWN angle into everything it emits
— its built-in quick-pick gradients carry 0/45/270/315deg, and a
solid→gradient conversion starts from its internal 180deg default — and
PR #171 hid the angle dial (`showGradientAngle={false}` gates only the
control's render, never the emit), removing the only way to correct one.
`ColorGradientPicker.normalizeGradientAngle` therefore CANONICALIZES to
90deg — rewriting a wrong or keyword direction, not merely supplying a
missing one — and is applied on emit AND on display (the swatch and the
widget both paint a re-angled copy), so a value stored vertical between
#171 and the fix paints correctly with no data migration. Proof, extracted
verbatim from the TSX so it can't drift: `scripts/
check_gradient_angle_canonicalization.mjs`. `web/src/components/
ColorGradientPicker.tsx` (the frozen SpotFX twin) deliberately does NOT
canonicalize — its angle dial is still visible, so a rewrite there would
silently overrule a control the user can see.

**A `ColorGradientPicker` nested inside a `TopBarGroupButton` panel closed
the WHOLE panel on TOUCH (not mouse) the instant he tapped anything inside
the nested picker — fixed 2026-08-20.** His report on `DriftGradientBar`
(top bar → "Gradient"): opening the panel and picking an existing gradient
worked (PR #152's New-draft-race fix, unrelated), but tapping the Solid/
Gradient tab or the hue/saturation area inside the Top/Bottom edge's
colour picker closed the entire Drift gradient panel out from under him.
Root cause, general to BOTH `ColorGradientPicker.tsx` copies (`spectra/
web/src/components/` and `web/src/components/`) and any future consumer
with the same shape: its popover is its OWN `createPortal(...,
document.body)`, a DOM **sibling** of the panel it was opened from, not a
descendant — an enclosing panel's own outside-click dismissal
(`TopBarGroupButton`'s `document.addEventListener('mousedown', ...)`
containment check) can't see the popover's subtree and reads every tap
inside it as an outside click. **Reproduced only under REAL touch
(`Input.dispatchTouchEvent`, letting Chrome synthesize the compat mouse
sequence) — a CDP mouse-only click (`Input.dispatchMouseEvent`/
Puppeteer's `page.click()`) on the identical element did NOT reproduce
it**, so a click-only eye-check of this class of bug can pass while the
real phone still fails; test dialog-closing reports with a raw
`Input.dispatchTouchEvent` tap (see git history for the throwaway CDP
script), not `page.click()`. Fixed at the source, not per-consumer:
`ColorGradientPicker`'s own popover div stops the `mousedown` from
bubbling past itself (`onMouseDown={(e) => e.stopPropagation()}`) — it
never reaches ANY ancestor's document-level listener, regardless of DOM
position, and the picker's own `onDocDown` already excluded clicks inside
its own `popoverRef` so nothing relied on the event still bubbling.
Fixed only in `spectra/web/`'s copy (his actual report); `web/`'s copy
has the identical `createPortal` + document-mousedown shape and is a
same-class latent risk for any future outside-click panel there, not
touched by this fix.

## SPECTRA Sonic token-usage record (review page)

`spectra/services/sonic_usage.py` — durable per-call token usage, his ask:
last query / this day / this week, on the Review page (not settings
console — that's where he asked). Captured at the runtime response itself
(`settings_agent.py`'s Anthropic SDK `response.usage`, summed across a
turn's tool rounds; `settings_agent_cli.py`'s `claude -p` final `result`
event's own `usage`/`modelUsage`/`total_cost_usd`) — never estimated; a
call the runtime doesn't report usage for records nothing, no fabricated
zero. **Day/week are FIXED periods anchored Monday 22:00 America/New_York
(stdlib `zoneinfo`, DST-aware), NOT rolling 24h/7d** — his own overruling
ask, because that boundary is presumed aligned to his subscription's own
quota reset, so the figure reads as "how much is left," not just "how
much was spent." Bucketed at READ time against stored `wall_ms`
timestamps (`storage/spectra/sonic_usage.json`), never pre-assigned at
write time, so a future anchor correction re-buckets history correctly.
No DI seam (same class as `fire_history.py`) — `tests/conftest.py`'s
autouse `_isolated_sonic_usage` repoints `config.SONIC_USAGE_FILE`; a new
script reaching `record()`/`summary()` for real needs the same repoint.

**Since the lyrics plan's step 3, this is no longer only Sonic's record**:
`spectra/services/claude_text.py` (the one Claude call behind lyric reading
and colour-meaning drafting, see `docs/agents/testbed-and-drops.md`'s
"Sung labels and word matches" section) records every call here too, `session_id="lyric-reading"`/`"colour-
meanings"` — same account, same backend switch, so the Review page's
"how much of his allowance is gone" figures include those calls, not only
Sonic's.

## SPECTRA S3 light ownership + handover (BUILT AND PROVEN, GATED OFF)

Exactly one process owns the lights. The durable record is
`storage/spectra/ownership.json` via `fx/light_ownership.py` (shared library;
missing file = spot-effects owns — the shipped default). Enforced in the
write paths, not convention: `api/ledfx_client._request()` sheds every call
when not owner and the LedFX-restart watchdog goes dormant (never resurrect a
quiesced LedFX — merge-scout §4d trap); `spectra/services/fx_seam` routes
HTTP↔facade by owner and refuses mid-handover; `fx/host.py` refuses non-dummy
devices without a step-gated ActivationGrant. Two-step handover
`spectra/services/handover.py` (READINESS GATE first — the order-8 fix: a
missing/empty/unusable fx-live config, or a missing LedFX unit on the
reverse path, REFUSES with HTTP 412 before the record moves or anything
quiesces, naming the seeder; then quiesce → verify → activate → commit;
every failure lands single-owner), live stack `spectra/services/live_host.py`
(device layer + audio hub + frame-freshness tap). THE LIVENESS ENDPOINT
CONTRACT: `GET /spectra/api/liveness` (`spectra/api/ownership.py`) — never
delete or repoint without the Admiral's word. The handover API is inert until
`SPECTRA_HANDOVER_ARMED=1`; arming and running it is the owner's word —
procedure in `docs/SPECTRA_HANDOVER.md` (go-day seeder
`scripts/seed_spectra_fx_live.py`). **STANDING DESIGN, Admiral 2026-09-07:
that latch is kept ARMED PERMANENTLY** (already set on the deployed
`spectra.service`; no default changed) because River's take-back button —
the interactive handover TO spectra — is a first-class control, not a
one-off ceremony; there is no "disarm afterwards" step any more. The panic
RELEASE stays un-gated as before, and the self-taking night's
`SPECTRA_NIGHT_SELF_TAKE` is a SEPARATE, still-absent-by-default latch that
this decision does not touch — don't conflate the two. Full note:
`docs/SPECTRA_HANDOVER.md` § "STANDING DESIGN". Spec:
`.venv/bin/python scripts/check_ownership.py` + `tests/test_handover.py`.

### THE HANDOVER ROUTE NAMES ITS CALLER — and it names the CALLER, not itself

Two unannounced takes in two days (2026-09-09 18:10:31, 2026-09-10 19:59:45)
moved his room and the origin could only be INFERRED, because nothing on
`POST /spectra/api/ownership/handover` recorded who asked.
**`spectra/services/caller_identity.py`'s module docstring is the binding
statement.** Every call to that route now logs peer address:port, User-Agent
and — for a caller on this host — the pid, cwd and (redacted) command line of
the process that actually asked, at WARNING, BEFORE anything is decided, so a
REFUSED take is named too. Four things:

- **RESOLVE THE CLIENT END OF THE SOCKET, NEVER THE SERVER'S.** River built
  the same capture on her own endpoint and it printed the pid/cmdline of her
  own LISTENING process — it named herself every time and identified nobody.
  The two ends of one connection are mirrors, so `find_socket_inode` matches
  `local == the peer AND rem == the server` in `/proc/net/tcp{,6}`, then walks
  `/proc/<pid>/fd/*` for that inode. A lookup keyed on the other end is the
  defect; `tests/test_handover_caller_logging.py` asserts the discriminating
  pair (the resolved pid IS a known child's and IS NOT this process's own),
  and was verified RED against a re-introduced wrong-side lookup.
- **A CALLER THAT CANNOT BE RESOLVED IS SAID SO, NEVER GUESSED.** A remote
  peer has no pid here; printing a local one is River's failure inverted.
  Each unresolvable case gets its OWN sentence (remote / socket already
  closed / rewritten in between / no peer at all).
- **A BEST-EFFORT LOOKUP OFF THE LOOP MUST BE A *DAEMON* THREAD, not
  `asyncio.to_thread`** — measured, and it generalizes past this module:
  `to_thread` runs on the loop's default executor, whose threads are JOINED at
  loop shutdown, so a lookup abandoned at its budget still held the process
  (a deliberately wedged one held a test teardown 30 s after the route had
  already returned in 200 ms). On his box that is a wedged read sitting in
  front of a `spectra.service` restart — the thing a stuck room is recovered
  with. A daemon thread is joined by nobody.
- **NO SECRETS.** Headers come from an explicit allowlist (`SAFE_HEADERS`),
  never a loop over what arrived, so `Authorization` cannot leak by accident;
  and the cmdline is redacted PER ARGV ELEMENT (`redact_argv`) — a
  `-H 'Authorization: Bearer <token>'` is two words inside one argument, so
  the mask has to be greedy within it, and redacting the joined string ate the
  `-d` payload after it.

Observation only: it reads /proc and logs, changes no ownership behaviour and
writes nothing. The route function keeps a defaulted `request` parameter so it
stays callable as a plain coroutine (several tests drive it that way); an
in-process call has no peer and is logged as exactly that.

A third owner state, `released` (`fx/light_ownership.RELEASED`), is the
owner's panic handle — `spectra/services/release.py`, `POST
/spectra/api/ownership/release`, the SPECTRA UI's red button
(`RoomOwnershipBar.tsx`). Unlike the handover above it is NOT armed-gated
(going to no-writer is always safe): one atomic step sheds both worlds'
write grants, then each device is told to let go explicitly rather than
left to time out — WLED gets the JSON API's `{"live": false}`
(`fx/utils.py WLED.release_realtime`, wired in `fx/devices/wled.py`; WLED's
own firmware then resumes its on-device show, unlike Hue below), Hue gets
BOTH a bridge-side dim-to-off fade over direct REST
(`spectra/services/release_fade.py`, run before the stream itself stops —
2026-08-14 fix: stopping the entertainment session alone left the bulb
holding SPECTRA's last streamed frame indefinitely, since Hue has no
on-device show to fall back to) and the entertainment session stop
(already explicit — `fx/devices/hue.py`), the external LedFX service's
active virtuals are deactivated over its API. The off write's own 2xx is
not trusted either (spectra-audit-2xx-proof, 2026-08-16, `docs/
SPECTRA_SPEC.md` §64): `release_fade.py` reads each light back after the
off write (one paced retry if still on) and returns any still-on light's
bridge name in `still_on` — his Hue bridge 2xx's a write whether or not
the physical bulb took it (D6), the same fact `ambient.py`'s own
`_hold_and_confirm` was built for, just never applied here until this
pass.
Cleanup runs against BOTH worlds on every press regardless of which one the
record said owned (a rogue writer the record doesn't know about, e.g.
systemd's `Wants=` resurrecting `ledfx.service` behind its back, is
tonight's-incident-shaped and must still be addressed) — see
`spectra/services/release.py`'s module docstring. The external-LedFX calls
go through `spectra/services/ledfx_release.py`, a direct httpx client (same
pattern as `handover.py`'s `SpotEffectsSide.verify_active()`), never through
`api.ledfx_client`: that module's ownership gate sheds every call once the
record has moved to `released` (which happens before cleanup runs), and
routing around it also keeps spectra/'s import discipline (nothing under
`spectra/` imports spot-effects runtime internals) — see
`check_process_split.py` §1b. `release_room()` also verifies afterward
(`_verify_released()`): SPECTRA's stack via `live.active`, the external
service via the same systemctl-is-active check `handover.py` uses, falling
back to a virtuals read-back when that unit is still running — PLUS, since
the §64 fix above, any `still_on` light `release_fade.py`'s own read-back
named. It returns a `ReleaseResult` (record/verified/problems) — the
record always lands `released`, but the API reports
`result="released-unverified"` (HTTP 207) with the specific `problems`
when a device (LedFX virtual or a Hue bulb by name) couldn't be confirmed
dark, instead of silently claiming success.
The way back is the SAME guarded handover, still armed- and readiness-gated
(`run_handover`'s `from_world=="released"` skips the vacuous quiesce step).
Spec: `tests/test_release.py` (+ `tests/test_release_fade.py` for the Hue
fade itself) + `check_ownership.py` §12. Live-fixture proof after a real
press (offline tests can't reach a bridge): `scripts/verify_release_fixtures.py`
— read-only, GET-only CLIP v2 + WLED `json/info`, no writes.

### The way back from `released` TOLERATES a partial activation (2026-08-21)

His ruling: "one unreachable device must not be able to keep his entire
room dark" — after six aborted take-backs in one night on one WLED whose
mDNS name would not resolve (and two sconces the morning before that
merely answered too slowly), each abort tearing down the twenty lights
that HAD come up. `handover.run_handover` step 2 now commits a PARTIAL
activation (stack up, ≥1 expected virtual driving, some devices/virtuals
unconfirmed) when `from_world == RELEASED` — aborting there lands on
darkness, not safety, and never saves the unreachable light. **Scope is
bounded and must stay bounded**: a handover FROM a running world keeps
its strict all-or-nothing rollback; a HARD failure from released (stack
never up, or not one expected virtual driving) still aborts. The policy
reads `SpectraSide.activation_outcome()` (structured — `ActivationOutcome.
partial`), mirrors `resume_own_room`'s 2026-08-13 tolerance, and the
skipped light is NAMED everywhere he looks via `spectra/services/
activation_report.py` (the take-back response `committed-partial`, `GET
/ownership` → `activation` → `RoomOwnershipBar`'s amber `ActivationStrip`
on every page, the Status page line, liveness `activation` — additive,
NEVER `healthy`, since the frame watchdog's dead-man must not restart-loop
the service over one dark fixture — and the record's own history note via
`light_ownership.commit(detail=)`). The report is a SNAPSHOT: its
`run_supervised()` rechecks still-dark lights every 30 s through the SAME
probe `device_gaps()` polls (`live_host.probe_device_live`), marks
recovery, and re-runs the vendored driver's own `async_initialize()`+
`activate()` for a never-resolved device — nothing in the render loop ever
re-resolves an inactive device, so without it a fixed light needs a whole
release+take-back cycle to collect one fixture. Before diagnosing "the
take-back failed on device X": read `GET /spectra/api/ownership`'s
`activation` and the record's history — a 200 `committed-partial` is NOT a
failure. Proofs: `tests/test_take_back_partial.py` (real FxHost + real
WLED driver against a `.invalid` name through the real armed route — never
his data, never his network), `tests/test_activation_report.py`,
`scripts/check_ownership.py` §12b. Known environmental note: this worktree
carried his real `storage/device_categories.json` (gitignored), which makes
`tests/test_crystal_activation_verify.py`'s fixture rooms intersect to an
empty `expected_active_ids` — pre-existing, fails identically on pristine
master here; `test_take_back_partial.py` stubs `room_topology.
genuinely_driven_virtual_ids` for exactly that reason.

### A TAKE AND A RELEASE ARE SCOPED TO THE FIXTURES THEY ACTUALLY DRIVE

2026-09-07, the Admiral verbatim: "you turned off the bathroom light... be
more selective about which lights you turn off." A kitchen capture run took
the whole room — which on his config means ONE virtual, `hues`, spanning
BOTH Hue bridges and the two entertainment configurations behind them,
seventeen bulbs from the hallway to the bathroom — drove every one of them,
and switched every one of them off on the way out. **Neither half was a bug
in the release: the release let go of exactly what the take had taken. The
TAKE was the wrong size.** Two halves, and each is a fact rather than a
policy:

- **`spectra/services/take_scope.py` is the binding statement for how much
  of his house a take may bring up.** A device is activated by ONE thing —
  a virtual with segments on it activating (`Virtual.activate_segments`) —
  so the scope is computed as a set of DEVICES (a room → its carriers →
  the devices those carrier virtuals touch) and the virtual scope handed to
  the take is then *every config virtual whose segments touch only in-scope
  devices*. That makes "no out-of-scope fixture can be activated by this
  take" STRUCTURAL: there is no virtual left able to reach one. It reads
  the STORED `fx-live/config.json` plus the room map, because the scope has
  to be known before there is any host to ask. **Unresolvable widens to the
  whole room WITH A STATED REASON** (unknown room, no carriers, a carrier
  that is not a virtual): a wrongly-narrow take wastes a night, a
  wrongly-wide one is only today's behaviour. An EMPTY intersection is a
  hard refusal in `live_host.activate` — a take with nothing to bring up
  would pass the freshness gate vacuously.
  Threaded as `live_host.activate(scope=)` → `FxHost.start(only_active=)` →
  `Virtuals.create_from_config(only_active=)` (`fx/VENDOR.md` #36), and
  `handover.SpectraSide(scope=)`/`production_sides(scope=)` →
  `night_take.take_room(scope=)`, computed in `night_run.start` from the
  DECLARED queue. `None` everywhere else is byte-identical to before.
- **`release_fade.fade_and_release_hue` fades only Hue devices this stack
  ACTUALLY STREAMED TO** (`Device.ever_activated`, `fx/VENDOR.md` #35 —
  sticky, not "active right now", so a substitute stood down mid-run is
  still owed its let-go). The whole argument for the fade is that a Hue
  bulb holds SPECTRA's last streamed frame; a device never activated holds
  nothing of ours. **The panic release is UNCHANGED** — on a whole-room
  take-back every Hue device comes up, so every one is in scope. A Hue
  device left alone is REPORTED (`untouched`), never silently skipped.

**THE HONEST UNIT IS THE ENTERTAINMENT GROUP, NOT THE BULB, and it is
measured rather than argued** (`tests/test_scoped_take_release.py::
test_a_hue_group_is_indivisible_at_the_wire`): `HueDevice.flush` sends the
WHOLE channel set in one DTLS datagram, and `Device.update_pixels` scatters
every virtual's segments into one shared buffer, so streaming any part of a
group drives every bulb in it (the unwritten ones to black). Every bulb in
a streamed group is therefore holding a frame of ours and is owed the fade.
Splitting finer is a bridge-side grouping decision this code cannot invent.

**AMBIENT AND DARK/LIGHT STAY INSIDE THE TAKE TOO (2026-10-04).** Ambient
drives Hue over bridge REST, outside the render path, so the virtual scope
above never reached it: a take scoped to the Living Room held all seventeen
Hue bulbs because his stored Ambient was on, and it landed three seconds
BEFORE the commit (a bridge broadcast's reconcile saw a live stack).
`live.scope_device_ids()` is the scope as devices; `ambient._hue_devices`
filters by it, `ambient.room_available()` refuses while a handover is in
flight, and `dark_light` writes only in-scope virtuals. Spec:
`tests/test_ambient_take_scope.py`.

**AND A LATER WRITE STAYS INSIDE IT (2026-10-04, D4).** The scope at START
said nothing about what a later write may bring up: a scene fire wrote the
held-back house `hues` virtual and the facade's activate-on-write repair
(#29) brought it — and both Hue areas — up for four minutes.
`FxHost.virtual_in_scope` is now the write boundary (`fx/VENDOR.md` #42):
the facade refuses effect writes/activations outside it, `fx_seam` and the
engine's `FacadeExecutor` skip them, and the Light Show's targets list only
`scope_device_ids()`. A new writer that bypasses those two seams must ask
`facade.out_of_scope()` itself. Spec: `tests/test_scene_fire_scope.py`.

`night_exit`'s own `release_fade.read_hue_light_states` is deliberately NOT
scoped: it is READ-ONLY and its attribution (`outside_run`) is what makes
an out-of-scope lit bulb legible rather than blamed.

Proofs: `tests/test_scoped_take_release.py` (the whole night through the
real `night_run.start` → `take_room` → `run_handover` → a real
`fx.headless` host with the REAL `HueDevice` class, transport stubbed —
every frame that reaches a device and every REST call that reaches a
bridge, with an `unscoped` run of the identical night as the red control,
reproducing "his bathroom was switched off" by name) and
`tests/test_take_scope.py` (the rule, and every case it refuses to narrow).

### Two-writers prevention build (2026-08-13 incident: `Wants=ledfx.service`
in the unit resurrected a deliberately-quiesced LedFX on a routine
`systemctl restart spotfx` while SPECTRA owned — see
`/home/javi/fleet-spotfx/data/spectra-two-writers/report.md`)

`deploy/spotfx.service` no longer `Wants=` ledfx (kept in `After=` for
ordering only) — the handover orchestrator is the only legitimate
starter/stopper of that unit. Two continuous reconcilers, one per process,
each periodically assert the ANTI-state (never their own health) rather
than trusting the ownership record forever once proven true at handover
time: `spectra/services/ownership_reconciler.py` (while spectra owns,
`ledfx.service` must be inactive and no foreign realtime source may hold
her WLEDs — read via each device's own `wled.get_state()` `live`/`lip`)
and `services/spectra_liveness_reconciler.py` (while spot-effects owns,
SPECTRA's own `/spectra/api/liveness` must not report `live`/`split-brain`).
Both alarm-only (CRITICAL log) by default; `SPECTRA_RECONCILER_ESCALATE=1`
arms a sustained-violation drop to `released` (the already-proven panic
handle) — same "gated until the owner's word" posture as
`SPECTRA_HANDOVER_ARMED`. `spectra/services/handover.py`'s `run_handover`
re-verifies `from_side.verify_quiesced()` immediately before `commit()`
(closes the verify→commit resurrect gap) and `api/ledfx_client.py`'s
LedFX-restart watchdog now requires a genuinely dead probe (not sustained
high RTT alone) plus a named veto (`_ledfx_restart_veto_reason`) checked
immediately before spawning `systemctl`. Spec:
`tests/test_ownership_reconciler.py`, `tests/test_ledfx_watchdog_veto.py`,
`tests/test_handover.py`.

The crystal lazy-activation class (a handover/resume brought up only SOME
config-declared virtuals and still reported success — a mapper-chain
virtual excluded from the old "every ACTIVE virtual" freshness check is
invisible to it, vacuously healthy): `spectra/services/live_host.py`'s
`LiveLights.activation_gaps()`/`wait_fully_active()`/`device_gaps()`
compare the fx-live config's declared-active virtuals (whatever a scene
fire or the seeded baseline persisted) against runtime reality — per-virtual
frame freshness AND, for WLED-backed virtuals, the device's own `live` flag,
never assumed from the host's in-memory state alone. A fresh handover
(`SpectraSide.verify_active()`) rolls back on ANY gap — there's a known-good
from-world to fall back to. `resume_own_room` (process restart while
already owner, no from-world to fall back to) instead reports every gap
loudly (CRITICAL + the liveness endpoint's `activation_gaps` field) and
leaves every other device driving — one failing device must never strand
the rest. Spec: `tests/test_crystal_activation_verify.py`.

The fresh-handover path's naming gap (SpectraSide.verify_active() used to
return a bare bool — a refused take-back couldn't say which light):
`live_host.describe_gaps()` builds a named detail from `activation_gaps()`/
`device_gaps()`, `verify_active()` logs it CRITICAL and stashes it on
`verification_detail()`, and `run_handover` folds that into the
`HandoverFailed` message the `/ownership/handover` API's `error` field
returns verbatim — read by `spectra/web/src/api/client.ts`'s `errorDetail()`
(which must check BOTH `detail` — FastAPI's default HTTPException shape —
and `error` — this route's own JSONResponse shape — or a named refusal is
silently dropped before it reaches the toast). `resume_own_room`'s own
naming (above) is untouched; both callers now name every gap, by design,
in the paths built for each.

`expected_active_ids` (what the gate above validates against) used to be
EVERY virtual fx-live/config.json declares active — that config is seeded
VERBATIM from the old LedFX world and inherits its dynamic tricks (mask/
foreground/background layer virtuals, gap-dummy placeholders, a full-span
duplicate of a mapper virtual, legacy contextual rooms SPECTRA's own scene
engine never addresses), so the gate could refuse forever on layers never
supposed to rise. `spectra/services/room_topology.py`'s
`genuinely_driven_virtual_ids()` — the SAME ground truth
`scene_compiler.compile_scene()` itself resolves real fires against
(`fx.device_model`'s imported category topology ∪ stored scenes' literal
`target_kind="virtual"` targets) — is intersected into `expected_active_ids`
at every activation; an ABSENT ground truth (no categories imported, no
scenes) falls back to the raw declared set rather than vacuously passing.
`scripts/check_spectra_expected_active.py` is the evidence-printing,
dry-run-by-default correction script (the `seed_spectra_fx_live.py`
pattern) for the PERSISTED config — diagnostic/belt-and-braces, since the
runtime intersection above is the actual fix. Spec:
`tests/test_spectra_activation_truth.py`.

