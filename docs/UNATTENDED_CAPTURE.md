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
| Keeping a run that was cut short | judge it, decide, re-run by hand | recorded `partial`, footprints kept, declared retry re-runs it |
| Knowing what happened | watch the page | one machine-readable outcome per item, written after **every** item |
| Explaining a refusal | read a status word, guess | `mapping_refusals`' own sentence, on the page and in the record |
| Releasing the room afterwards | (already automatic) | unchanged — the held-room sweep still owns it |

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
- **Confirming that camera can actually lock exposure.**
  `v4l2-ctl --list-ctrls-menus` should show `auto_exposure` with a
  `Manual Mode` entry. A camera without it will be refused on every run,
  honestly and uselessly — that is a camera to replace, not a gate to
  loosen.
- **Deciding the queue**: which rooms, which granularity, which
  commissioning targets. A queue file is a list of button presses; it is
  not generated.
- Optionally, **making the client a systemd unit** so "start the client"
  stops being a step at all.

### (c) STILL needs his hands, per run

- **Making sure SPECTRA owns the lights before the queue starts.** A
  released room refuses by name (one press on the ownership bar) — the
  queue will not take the room back on its own, and should not.
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
- **Starting the client**, unless it is a systemd unit (see above).

### What was deliberately NOT automated

- **The exposure-lock refusal.** Automating the lock *request* is the
  whole point; automating the lock *confirmation* would forge the
  instrument's signature. Every lock this client reports is a read-back
  from the device, and a camera that will not lock refuses the run.
- **Taking the room back from a release.** That is an ownership decision.
- **Aiming, and choosing a pose.**
- **Anything about the frozen commissioning table**, its five tolerances,
  or the 320x180 wire-frame contract.

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

## Proofs

| | |
|---|---|
| `scripts/check_capture_queue_e2e.py` | the whole path: real server, real WebSocket, the real client, a synthetic camera. A declared queue of five runs with no human action after start; a mid-queue refusal that the queue carries on past; a dropped socket whose partial is kept and whose retry completes; the pose held across the drop and NAMED across a reopen; the exposure gate refusing an automated client; a machine with no camera connecting anyway to say so. Run from pytest via `tests/test_light_field_checks.py`. |
| `tests/test_capture_queue.py` | what the runner does with each outcome it is handed |
| `tests/test_capture_client.py` | the lock is read back, never asserted — including a driver that ignores the write |

**No live-room proof exists for any of this**, by instruction: it is
proven against a synthetic camera and an isolated local instance. A run
against his real room and his real laptop camera is a separate step the
captain schedules.
