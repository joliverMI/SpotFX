# Unattended capture — the client, the queue, and an honest ledger

A room-mapping or commissioning run used to need a person at every step.
The captain ran one overnight queue and it worked only because he
personally set the session up before bed; while the camera session is the
bottleneck, every capture experiment queues behind his availability.

This is what now runs without him, what needs him once, and what still
needs his hands each time. **The ledger is the deliverable.** Read it
before the how-to.

---

## THE LEDGER

### (a) Now proceeds with ZERO human involvement

Once the capture client process is running on a machine whose camera is
already pointed at the room:

| | Was | Is |
|---|---|---|
| Establishing the capture session | open a page, in a browser, on a device someone is holding | `CaptureClient` connects, says hello, pairs clocks, streams frames |
| Requesting the exposure / white-balance lock | tap Start camera, watch it settle | `camera.apply_lock()` asks the driver, then **reads the control back** |
| Keeping the session alive | keep the tab awake | the client holds it; a dropped WebSocket reconnects with backoff |
| Surviving a dropped connection | notice, reopen the page, start again | reconnect **keeping the same pose**, so the map either side is one measurement |
| Starting each run | press Start mapping, wait, press the next one | `capture_queue` walks the declared list |
| Choosing per-run parameters | re-set the controls between runs | each item carries its own granularity, block size and four protocol waits |
| Getting the right FRAME SIZE for the run | (there was one size, and it could not read a composition) | the server asks (320x180 for a map, 1920x1080 for a commissioning read) and the client adopts the largest rung its camera can honestly fill |
| Setting a manual integration time / gain | not possible at all | per-run request, applied by the driver and **read back**; a lever the camera did not take refuses by name |
| Widening a capture window for a long exposure | (nothing knew the exposure) | `capture_windows` widens both so `MIN_FRAMES` is still averaged, and the estimate prices the widened run |
| Keeping a run that was cut short | judge it, decide, re-run by hand | recorded `partial`, footprints kept, declared retry re-runs it |
| Knowing what happened | watch the page | one machine-readable outcome per item, written after **every** item |
| Explaining a refusal | read a status word, guess | `mapping_refusals`' own sentence, on the page and in the record |
| Releasing the room afterwards | (already automatic) | unchanged — the held-room sweep still owns it |
| **Starting the night at all** | he set a session up before bed and pressed | his `Sleeping` helper, on for 30 minutes, pushes one event (`POST /api/night-run/start`) |
| **Stopping when he stirs, or when his morning comes** | nobody was awake to | one `/abort` push — `sleep-ended`, `light-touched`, or his 05:30 `morning-routine` |
| **Turning a fixture on that was switched off for the night** | it simply photographed an unlit strip | `night_power.owned` turns on only what reads off, confirms by reading back, and puts his switch back in a `finally` |
| **Knowing the room is actually dark at the end** | a mode read, or nothing | `night_exit` reads every fixture back AT THE EMITTED LIGHT and names what still emits and why |
| **Noticing the house changed light mid-capture** | nothing could see it | the contamination witness, asked per capture window and once more settled at the end; contaminated captures are re-taken |
| **Telling the morning backstop what to turn off** | a hand-kept list that missed the shielded sets | `GET /api/night-run/fixtures` — what the run took AND what Dark mode leaves standing, both computed live |

Also automatic, and unchanged by this work because it already was: the
fixture firmware-brightness guard, the one-run-at-a-time lock, the hold
ceiling, the unseen-emitter record, and the room coming back however a run
ends.

### (b) Needs a human ONCE — per machine, or per camera position

- **Physically placing and aiming the camera at the room, and deciding
  where it stands.** This is the pose. Nothing here estimates it and
  nothing here should: a footprint is what a camera at one place saw.
- **Camera permission on the capture machine**: the user must be able to
  read `/dev/video*` (usually one `usermod -aG video`, then log in again).
  The client refuses by name if it cannot.
- **`ffmpeg` and `v4l2-ctl` installed** on the capture machine
  (`apt install ffmpeg v4l-utils`). Each is checked for by name and
  refused by name.
- **Checking what resolution that camera actually produces.**
  `--capture-size` defaults to `1920x1080`, which is what a commissioning
  read wants; the client steps down to 1280x720 then 640x480 if the camera
  will not open there, and SAYS which it got. It never sends a wire frame
  bigger than what it captures, so a 720p webcam simply reads at 720p and
  the run reports that rung — nothing to configure, but worth knowing
  before wondering why a read refused as marginal.
- **Checking whether that camera has manual exposure/gain at all**, if a
  run is going to ask for them: `v4l2-ctl --list-ctrls-menus` should show
  `exposure_time_absolute` and `gain` alongside `auto_exposure`. A camera
  without them refuses those runs by name — honestly, and the run without
  the levers still works.
- **Confirming that camera can actually lock exposure.**
  `v4l2-ctl --list-ctrls-menus` should show `auto_exposure` with a
  `Manual Mode` entry. A camera without it will be refused on every run,
  honestly and uselessly — that is a camera to replace, not a gate to
  loosen.
- **Deciding the queue**: which rooms, which granularity, which
  commissioning targets. A queue file is a list of button presses; it is
  not generated. For the NIGHT run this is a stored DECLARATION
  (`PUT /api/night-run/queue`, the same items) — declared while he is awake
  and has hours to fix a typo in it, which is the whole point of it being
  declared rather than composed when the event arrives at 1am.
- **Provisioning the two secrets, in the environment only**:
  `SPECTRA_NIGHT_RUN_TOKEN` (the bearer Home Assistant presents on the two
  pushes) and `SPECTRA_WITNESS_URL` + `SPECTRA_WITNESS_TOKEN` (the
  contamination witness). Unset means the night seam is SHUT (every push
  401s) and the witness is absent (every capture recorded UNCLAIMED, never
  clean) — both fail closed and say so.
- Optionally, **making the client a systemd unit** so "start the client"
  stops being a step at all.

### (c) STILL needs his hands, per run

- **Making sure SPECTRA owns the lights before the queue starts.** A
  released room refuses by name (one press on the ownership bar) — the
  queue will not take the room back on its own, and should not. **The night
  trigger has no exception to this, ever**: a start arriving on a room
  SPECTRA does not hold DECLINES by name, records the declined night, and
  does nothing else.
- **Checking `light.dimmer_kitchen_sconce` when a sconce will not answer.**
  It is the kitchen sconces' MAINS SUPPLY and it is a switch (0% or 100%);
  at 0% both are dead and it looks exactly like a dead controller or a lost
  network. Nothing in SPECTRA can turn it on and nothing here ever turns it
  off — the diagnostic names it FIRST so it is checked first.
- **Moving the camera to a second pose** for any emitter the first pose
  could not see. The map already reports those (`unseen`); acting on it is
  walking across the room.
- **Judging a commissioning verdict of `findings`.** The frozen table
  attributes each red row, but "is this a dead pixel or my mapper" ends in
  a decision about his hardware.
- **Choosing what to do when a target refuses as `marginal` or
  `impossible`**: move the camera closer, or commission a smaller piece.
  The instrument refuses; it never commissions something smaller on his
  behalf.
- **Choosing the integration time and gain a run asks for, and deciding
  what the exposure comparison's answer means.** The comparison MEASURES
  which regime put more light in the frame
  (`POST /api/rooms/{id}/exposure-test`); picking the numbers to try, and
  deciding whether a 3x gain is worth its noise, is his.
- **Starting the client**, unless it is a systemd unit (see above).

### What was deliberately NOT automated

- **The exposure-lock refusal.** Automating the lock *request* is the
  whole point; automating the lock *confirmation* would forge the
  instrument's signature. Every lock this client reports is a read-back
  from the device, and a camera that will not lock refuses the run.
- **Taking the room back from a release.** That is an ownership decision,
  and the night trigger gets no scoped exception to it.
- **Anything that drives a Home Assistant entity.** This side originates
  exactly two HA requests and both are read-only witness GETs. The house's
  own "Dark Music" envelope is fired and restored by the house side; the
  emitted-light exit verification is NOT waived because of it.
- **A dawn line of our own.** His 05:30 morning routine IS the hard end
  bound and it arrives as an event; nothing here schedules against a clock,
  and no capture work is ever scheduled past it.
- **Aiming, and choosing a pose.**
- **Anything about the frozen commissioning table or its five
  tolerances.** The wire's FRAME SIZE is no longer in that list — it was
  raised on 2026-09-01 by the owner's own instruction, and only because
  §98's arithmetic showed no pose could ever have read a composition
  through the old one (`spectra/services/capture_settings.py`). The
  tolerances did not move, and the resolution REFUSAL boundary moved only
  because its input arithmetic did.
- **Choosing a frame size bigger than the camera has.** The client
  negotiates DOWN and never up: a bigger picture of a smaller image is not
  more detail, and counting interpolated pixels as resolution is exactly
  how a ground-truth test comes back confident and wrong.

---

## What is proven, and what is not

Proven offline, against a synthetic camera and an isolated local SPECTRA
instance: the whole wire, the queue, the seam, the reconnect, the pose
assertion, the kept partial, the declared retry, and every refusal on this
path (`scripts/check_capture_queue_e2e.py`, 42 checks, run from pytest).

**Not proven, and stated rather than implied:**

- **The V4L2 backend has never met real hardware.** The machine this was
  built on has no `/dev/video*` and no `v4l2-ctl`. The control names, the
  menu parsing and the ffmpeg pipeline are written against V4L2's
  documented shapes and unit-tested against a fake `v4l2-ctl` speaking a
  real `--list-ctrls-menus` transcript — that is not the same as a webcam.
  The first run on his laptop is the measurement.
- **Nothing has run against his room.** By instruction.
- **No night run has happened.** The seam, its refusals, the planned-end
  bound, the abort, the power ownership, the exit report and the witness
  re-take are each proven offline (see Proofs below) against fakes, an
  isolated instance and a real headless render pipeline. The first real
  night is the measurement.
- **Whether a powered-off WLED displays a realtime stream, on HIS
  fixtures, is NOT established** — see `spectra/services/night_power.py`'s
  docstring for what the fleet has actually observed and why the run is
  built to be correct under either answer rather than betting on one. The
  first real night settles it as a by-product: the report says which
  fixtures were found switched off.
- **The witness has never been asked for real.** Its wire shape is built to
  River's deployed, proven contract and exercised against
  `httpx.MockTransport`; the entity subtraction is a slug match biased to
  OVER-indict, which costs re-takes and never corrupts a footprint. If a
  real night shows it over-indicting, the fix is to agree explicit entity
  ids with River — not to loosen the match.
- **The manual exposure/gain levers have never met a real driver either.**
  They are written against V4L2's documented control names and unit-tested
  against read-backs, exactly like the lock — and they fail the same safe
  way: a control this camera does not have, or one that answers with a
  different number, refuses the run BY NAME rather than measuring under a
  regime nobody asked for. A run that asks for neither is byte-for-byte the
  protocol that has always shipped.
- **No frame larger than 320x180 has crossed a real network.** The
  negotiation, the downgrade and the never-upscale rule are proven over a
  real uvicorn server and a real WebSocket with a synthetic camera
  (`scripts/check_capture_queue_e2e.py` §5: asked 1920x1080, got 320x180
  from a camera that has no more, said so) — the BYTES at 1080p, ~2 MB a
  frame before base64, are an untested cost on his own LAN.

The two ways the real backend can be wrong both fail SAFE, which is the
point of the read-back rule:

| | What happens |
|---|---|
| `ffmpeg` missing, device missing, device busy, device unreadable | the client still CONNECTS, reports `camera_error`, and every run refuses with that sentence naming the machine |
| `v4l2-ctl` missing, or a control this camera does not have | the camera opens and reports **NOT LOCKED**, with "v4l2-ctl is not installed" (or the missing control) in its capabilities — the run refuses by name |
| the control exists, the write is accepted, and the camera ignores it | the read-back says auto, so it reports **NOT LOCKED** — the run refuses by name |

None of those produce a map. A wrong V4L2 detail costs a refused run and a
sentence saying which control was missing; it cannot produce a map that
looks fine and is not.

## Running it

On the capture machine (his Linux laptop reaches SPECTRA over the
tailnet):

```bash
# hold a session, so a queue started anywhere can use it
python -m spectra.capture_client --url http://spectra:8000/spectra

# or: hold it AND run a declared queue to the end
python -m spectra.capture_client \
    --url http://spectra:8000/spectra \
    --device /dev/video0 \
    --queue overnight.json \
    --json-out /tmp/last-capture.json
```

Exit codes: `0` every item completed, `1` the queue ran and something did
not complete (the JSON says which item and why), `2` nothing ran — no
camera, no session, a bad queue file, or SPECTRA unreachable.

A queue file is a list of the same arguments the page's own buttons take:

```json
{
  "label": "overnight sweep",
  "items": [
    {"kind": "map", "room_id": "...", "label": "tv in blocks",
     "granularity": "block", "block_pixels": 30},
    {"kind": "map", "room_id": "...", "label": "tv, slower reference",
     "granularity": "block", "block_pixels": 30,
     "dark_settle_s": 2.0, "lit_capture_s": 2.0, "retries": 1},
    {"kind": "commission", "room_id": "...", "label": "per fixture",
     "per_fixture": true, "repeat": 2}
  ]
}
```

`retries` is 0 unless declared: a retry costs the room another dark
minute, so it is a decision, not a default. Only a `partial` is ever
retried — a refusal refuses identically the second time.

The queue can also be started without the client (`POST
/api/rooms/capture-queue`); it waits up to each item's `session_wait_s`
for a camera session to arrive, which is what makes "start the queue, then
start the client" work.

## Where to read the result

- The **Rooms page**, "Unattended capture": the live queue, every item's
  outcome with its sentence, and the last few queues.
- `GET /api/rooms/capture-queue` — the same thing as JSON.
- `storage/spectra/capture_queue.json` — bounded, rewritten after every
  item. It holds a SUMMARY per run; the full map is in `room_maps.json`
  and the full judged table in `commissioning.json`.

## The pieces

| | |
|---|---|
| `spectra/capture_client/camera.py` | what a camera is, and the read-back rule (**binding statement** for the lock's honesty) |
| `spectra/capture_client/session.py` | hello, frames, pong, reconnect, pose |
| `spectra/capture_client/__main__.py` | the command line and the exit codes |
| `spectra/services/capture_runs.py` | the ONE seam that executes one run — the page's button and the queue both go through it |
| `spectra/services/capture_queue.py` | the runner: waits, walks, keeps partials, names pose changes, writes as it goes |
| `spectra/api/capture_queue.py` | `POST`/`GET`/`stop` |
| `spectra/services/mapping_refusals.py` | one wording per condition, including the three new ones |
| `spectra/services/night_run.py` | **the night seam's binding statement** — the boundary, the planned end, the pricing, the abort |
| `spectra/api/night_run.py` | `start` / `abort` (Bearer) + the open `fixtures` and `queue` reads |
| `spectra/services/night_power.py` | lights on if necessary, and **what was established about that and what was not** |
| `spectra/services/night_exit.py` | the honest exit — read back at the emitted light, never a mode |
| `spectra/services/witness.py` | the contamination witness client, and **the sconce mains rule** |

## Proofs

| | |
|---|---|
| `scripts/check_capture_queue_e2e.py` | the whole path: real server, real WebSocket, the real client, a synthetic camera. A declared queue of five runs with no human action after start; a mid-queue refusal that the queue carries on past; a dropped socket whose partial is kept and whose retry completes; the pose held across the drop and NAMED across a reopen; the exposure gate refusing an automated client; a machine with no camera connecting anyway to say so. Run from pytest via `tests/test_light_field_checks.py`. |
| `tests/test_capture_queue.py` | what the runner does with each outcome it is handed |
| `tests/test_capture_client.py` | the lock is read back, never asserted — including a driver that ignores the write |
| `tests/test_night_run.py` | the boundary declines and RECORDS; the planned-end bound at start and per item; the export's two lists, with the shield list following a config change; abort; his morning as an ordinary ending |
| `tests/test_night_run_api.py` | auth (absent, wrong, unprovisioned, rotated), HA's own payloads, both open reads |
| `tests/test_night_exit.py` | **RED WHEN LYING**: a fixture forced lit at its own firmware fails the dark claim, on a real headless render host through real `fx.utils.WLED` transport to a real HTTP endpoint |
| `tests/test_night_power.py` | the two vendored WLED calls' wire shape, and the switch going back on the failure path |
| `tests/test_witness.py` | the query shape, the window cap, the three verdicts, the mains rule, and no write verb anywhere in the module |
| `tests/test_witness_retake.py` | the re-take on the REAL `run_mapping`: immediate per-window queries with **no added settle**, the settled sweep catching a late row, one re-take never a loop, and an unconfigured host byte-identical to before |

**No live-room proof exists for any of this**, by instruction: it is
proven against a synthetic camera and an isolated local instance. A run
against his real room and his real laptop camera is a separate step the
captain schedules.
