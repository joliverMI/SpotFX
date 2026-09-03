# The camera host — the capture client as a boot service

**THE PI DOES NOT EXIST YET.** Nothing in this document reports a working
Raspberry Pi deployment, because none has happened. What is here is what a
plain Linux box can prove, and an explicit ledger of what only real hardware
can settle. That split is the deliverable — read the ledger before the
how-to, the same way `docs/UNATTENDED_CAPTURE.md` puts its ledger first.

The standard this follows is the capture client's own unmet-hardware
commitment (`docs/UNATTENDED_CAPTURE.md`, "What is proven, and what is
not"): a claim that has not been measured is written down as unmeasured, and
when real hardware arrives the amendment is **dated** rather than quietly
replacing the sentence it corrects.

---

## THE LEDGER

### (a) PROVEN NOW, on the dev host

Every row is exercised by a check that runs in the suite
(`tests/test_light_field_checks.py`), or by an offline test
(`tests/test_capture_client_service.py`). No row here depends on anything in
(b).

| What | How it is proven |
|---|---|
| **The unit is valid systemd** | `systemd-analyze verify` — systemd's own parser — on the exact bytes that get installed, with a deliberately broken copy refused by the same check. It rejected two real mistakes while this was written (`StartLimitIntervalSec` in the wrong section, an invalid `Documentation=`), which is why it is a check and not a belief. |
| **The unit is host-agnostic** | It contains no host path at all: `%h` specifiers only, one launcher, and a test that fails if a `/home/...` or `/usr/local` literal appears. The same bytes go to every machine, which is what makes verifying them meaningful. |
| **Provisioning takes a fresh host from nothing to a running service** | `scripts/install_capture_client.sh` run for real on a throwaway `HOME`: it builds a virtualenv from `requirements-capture-client.txt`, writes the launcher, writes the configuration, installs the unit, verifies it, and calls `systemctl --user daemon-reload` / `enable --now`. |
| **Provisioning refuses BY NAME at each missing prerequisite, and writes nothing when it does** | ffmpeg, `v4l2-ctl`, python3, the video group, the configuration, linger — each exercised against a PATH genuinely missing that one binary, each naming the command that fixes it, each leaving the host untouched. `--check` runs every check and writes nothing at all. |
| **It is runnable twice** | Second run: unit byte-identical, virtualenv reused, and a value edited by hand in the configuration between runs is still there afterwards. |
| **The configuration is ONE file** | The unit's `ExecStart` carries no arguments; the client is started with the unit's own `EnvironmentFile` as its whole configuration and establishes a real session on a real server. A malformed number in that file refuses by name rather than silently defaulting. |
| **Restart on failure** | The client is `SIGKILL`ed and comes back under `Restart=always` / `RestartSec=5` **read out of the installed unit**, and re-establishes the session. The new session is honestly a **new pose**, because the camera was opened again. |
| **Reconnect keeps the pose; a camera reopen does not** | Pre-existing and unchanged by this work: `scripts/check_capture_queue_e2e.py` §5 and §7. |
| **Pinned camera settings are re-asserted at every open** | Pre-existing and unchanged: `camera.open()` re-asserts on every reopen, the client re-asserts on every reconnect, and both end in a read-back (`tests/test_camera_pinned_settings.py`). |
| **Health the server can SEE** | `GET /api/rooms/map/status` → `camera_host`, and the same read inside every `session_view()` (the capture queue, the calibration routes). It carries the machine's name, its **build**, its **declared placement**, the board string it reported, its camera, its lock state and its **lever self-test verdict**. |
| **Absence is a READ** | Three states, not two: `never` (no client has ever connected — an installation, not a diagnosis), `present`, and `absent` with the machine named, the build it was running, its placement, and how long it has been gone. Proven by killing the client and reading the sentence back. |
| **Health gates nothing** | The run's refusal is still `mapping_session.lock_refusal`'s and `NO_SESSION`, asserted unchanged while the host reads absent. |
| **The client acquires no room authority** | Structural: nothing in `spectra/capture_client/` mentions `fx_seam`, `light_ownership`, `handover`, a device driver or a compiler, and it imports nothing from `spectra.services.*`. Making it a boot service changed none of that — a queue arriving on a room SPECTRA does not hold still refuses by name. |
| **Its dependency closure is two pure-Python packages** | It imports with 28 server-only packages **blocked at the meta path**, never reaches into `fx/`, and every third-party import it makes is declared in `requirements-capture-client.txt`. |
| **Nothing in it branches on an architecture** | No `x86`/`amd64`/`aarch64` literal anywhere in the package; `platform.machine()` is *reported* in `hello` (so SPECTRA can say which board it is talking to) and never compared against. |

### (b) NOT TESTABLE UNTIL A PI EXISTS — each one named

- **ARM execution itself.** No aarch64 machine has run one line of this. The
  dependency closure above is evidence that the usual way an ARM port dies
  (a compiled wheel with no board build) does not apply here. It is not
  evidence that it runs.
- **`websockets` on that board.** It ships a C speedup with a pure-Python
  fallback; which one a Pi's wheel gives it, and whether the fallback's
  throughput is enough at 1080p, is unmeasured.
- **The Brio on that USB controller.** Whether a Logitech Brio negotiates
  1920x1080 raw (or needs `SPECTRA_CAPTURE_INPUT_FORMAT=mjpeg`) through a
  Pi's USB stack, and whether it holds it without dropping, is unknown. The
  client steps down and SAYS which rung it got, so the failure mode is a
  smaller read, not a silent one — but the rung it lands on there is
  unmeasured, and a commissioning read's whole arithmetic depends on it
  (`spectra/services/capture_settings.py`).
- **`v4l2-ctl` against the Brio's real control set.** Named already in
  `docs/UNATTENDED_CAPTURE.md`: the V4L2 backend has never met real
  hardware, on any machine. **This dev host does not even have
  `v4l-utils` installed** — the provisioning script refuses on it here,
  correctly, which is how that refusal came to be exercised for real.
- **1080p frames over his LAN from that board.** ~2 MB a frame before
  base64, at 5 fps, is an untested cost — untested on x86 too, and a Pi
  adds its own encode-free-but-copy-heavy path to the question.
- **Thermals and sustained capture.** A 35-minute commissioning pass, or a
  whole night's queue, on a board in a case near a television. Nothing here
  has run long enough anywhere to say.
- **Boot timing on his network.** Whether the unit's
  `After=network-online.target` plus the client's own reconnect backoff is
  enough on his tailnet after a power cut, or whether the first connection
  attempt lands before DNS is up. The client survives either (it reconnects
  with backoff and holds an open camera while it waits) — but *how long*
  the room waits after a power cut is unmeasured.
- **`systemd` actually starting the unit.** Not a Pi limitation — a
  limitation of the machine this was built on, which has no D-Bus session
  bus, so `systemctl --user start` cannot execute here at all and a private
  `systemd --user` refuses to start without cgroup delegation. The unit's
  TEXT is verified by systemd; its restart policy is executed by a
  supervisor that reads `Restart=`/`RestartSec=` out of the installed file.
  That proves what the unit tells systemd to do. **The first `systemctl
  --user enable --now` on a real machine is the measurement.**
- **Linger.** A user unit starts at boot only with
  `loginctl enable-linger`. The installer checks for it and says so; that
  it survives a real reboot on his hardware is unmeasured.
- **The unit's sandboxing directives.** `ProtectSystem=strict`,
  `ProtectHome=read-only`, `PrivateTmp`, `DeviceAllow=char-video4linux` and
  `SupplementaryGroups=video` are all things only a running systemd applies;
  `systemd-analyze verify` accepts them without exercising them. They are
  right (a camera process should not be able to write his home) and they are
  a real footgun: a `SPECTRA_CAPTURE_JSON_OUT` pointing anywhere but the
  unit's own `RuntimeDirectory` will fail at run time, not at install time.
  The env-file example says so; the first real start is the measurement.

### (c) WHAT BUYING THE PI UNLOCKS — the plain list

1. **The laptop stops being part of the instrument.** Today a calibration
   needs a machine that is awake, unlocked and not asleep for the whole run.
   That is the last human ritual left in an overnight calibration, and it is
   the one this removes.
2. **A camera that stays where it was put.** The pose is the thing a
   calibration is comparable within. A laptop gets carried; a board screwed
   to a shelf does not, so a re-run's pose check has a real chance of
   matching, and the pose fingerprint's refusals stop being the common case.
3. **A night run that does not depend on him remembering.** With the unit
   started at boot, the session is simply there when the `Sleeping` push
   arrives — including after a power cut, which is the case a laptop
   silently loses.
4. **The four pinned levers against a real driver, on a machine dedicated to
   it.** Integration time, gain, white balance and focus have never met real
   hardware anywhere; a permanent camera host is where that gets settled
   once instead of per session.
5. **A second pose becomes cheap to think about.** Emitters the first pose
   cannot see are already reported (`unseen`). A second board is a second
   pose, permanently, rather than a walk across the room with a laptop.
6. **Nothing about the room's safety changes.** The client is a camera
   process. It takes no lights, and a run on a room SPECTRA does not hold
   still declines by name. Buying hardware does not widen that boundary and
   is not asked to.

### The scorecard, honestly

**This retires none of his four.** It is not a measurement, a refusal or a
gate; it moves no tolerance and changes nothing about what a calibration
means. What it removes is the last standing human ritual — *a laptop that
must not sleep* — and it removes it **only once hardware exists**. Until
then this is a unit, a provisioner and a health read that have been proven
on a dev host and have never met the machine they are for.

---

## Running it

On the machine with the camera, from a SpotFX checkout:

```bash
scripts/install_capture_client.sh \
    --url http://spectra:8000/spectra \
    --pose-name "the north shelf"

# check every prerequisite and write nothing:
scripts/install_capture_client.sh --check
```

On Debian-family systems (Debian, Ubuntu, Raspberry Pi OS) the standard
library's `venv` imports fine while the part that seeds pip into a new
environment ships separately, so a venv built without it comes out with no
pip. The script checks for that and refuses by name with the fix:
`sudo apt install -y python3-venv python3-pip`.

Then, on a headless host, so the unit starts at boot rather than at login:

```bash
sudo loginctl enable-linger "$USER"
```

Afterwards:

```bash
systemctl --user status spectra-capture-client
journalctl --user -u spectra-capture-client -f
```

### The three files it installs

| | |
|---|---|
| `~/.config/spectra-capture/client.env` | **the whole configuration** — server URL, camera device, pose name. Created once from `deploy/spectra-capture-client.env.example`; a later run updates only the keys you name again. |
| `~/.local/bin/spectra-capture-client` | the launcher. The one thing that genuinely differs between machines (the checkout and the interpreter) lives here, so the unit can ship verbatim and be verified as the bytes that get installed. |
| `~/.config/systemd/user/spectra-capture-client.service` | `deploy/spectra-capture-client.service`, copied unchanged and then verified. |

### Dependencies: install the CLIENT's, not the server's

```bash
# what the installer does, and the only Python packages a camera host needs
pip install -r requirements-capture-client.txt      # httpx, websockets
```

`requirements.txt` is the **server's**. It carries compiled wheels
(`aubio-ledfx`, `samplerate-ledfx`, `python-mbedtls`, `pyfastnoiselite`,
`scipy`, `librosa`, `pillow`, …) that exist to render light and analyse
audio — none of which a camera process does, several of which have no
guaranteed aarch64 wheel and would be compiled on the board or simply fail.
`scripts/check_capture_client_deps.py` proves the client never needs them by
importing it with all of them blocked.

## Is my camera host there?

```bash
curl -s http://spectra:8000/spectra/api/rooms/map/status | jq .camera_host
```

Three answers, and they are deliberately different:

- `"state": "never"` — no capture client has ever connected. That is an
  installation, not a fault.
- `"state": "present"` — with the machine, its build, its declared
  placement, the board it reported, its camera, its lock state and its lever
  self-test verdict.
- `"state": "absent"` — **the machine named**, the build it was running,
  and how long it has been gone. Nothing is wrong with SPECTRA: that host is
  off, its service is not running, or it cannot reach this address.

The same read is inside every `session_view()`, so the capture queue and the
calibration routes carry it too. It **reports** and never gates: a run's own
refusal is unchanged.

## Proofs

| | |
|---|---|
| `scripts/check_capture_client_service.py` | the unit verified by systemd's own parser (with a broken-unit negative control), the provisioner's refusals and idempotence on a throwaway HOME, the unit's `ExecStart` configured only by its `EnvironmentFile` against a real server, the death-is-a-read sentence, and the restart |
| `scripts/check_capture_client_deps.py` | the import closure, the meta-path blocker, the fx/ boundary, the architecture audit |
| `tests/test_capture_client_service.py` | the configuration's rules, the presence record, and the two structural properties (no room authority, no server imports) |
| `tests/test_camera_pinned_settings.py` | settings written, read back, and re-asserted (pre-existing) |
| `scripts/check_capture_queue_e2e.py` | reconnect keeping the pose, and a reopen naming a new one (pre-existing) |

Both check scripts run from `tests/test_light_field_checks.py`, and both
print what they did **not** prove as part of passing.
