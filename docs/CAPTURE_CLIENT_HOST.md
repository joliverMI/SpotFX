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
| **Absence is a READ** | **Four** states, not two: `never` (no client has ever connected — an installation, not a diagnosis), `present`, `impaired` (see the next row), and `absent` with the machine named, the build it was running, its placement, and how long it has been gone. Proven by killing the client and reading the sentence back. |
| **A reachable-but-BROKEN client never looks like a healthy one** | *(2026-09-02)* `impaired` — connected, and saying it cannot do the job — carries the client's OWN reason (no camera, a lock it reported and did not get, a measured lever failure). `present` stays a boolean fact about the socket, so every earlier reader is unchanged. Proven end to end in `check_capture_client_service.py` §5, whose own synthetic camera IS such a client, and RED-verified against the pre-`impaired` behaviour. |
| **Health gates nothing** | The run's refusal is still `mapping_session.lock_refusal`'s and `NO_SESSION`, asserted unchanged while the host reads absent. |
| **ONE DOCTOR COMMAND answers every branch** | *(2026-09-02)* `spectra-capture-client --doctor` checks, in dependency order: python / venv+**ensurepip** / the installed virtualenv's pip; ffmpeg + `v4l2-ctl`; the device; **group MEMBERSHIP and whether the running user manager has it** (the reboot-pending case, read out of `/proc`); the address in **three readings** (resolves / connects / answers); the unit's state, its exit status translated, and its own last journal line; and whether SPECTRA can see this machine. It fixes nothing and starts nothing. `tests/test_capture_doctor.py` (27 tests). |
| **The doctor works when the virtualenv is the broken thing** | It is **stdlib-only** and runs as a plain file (`python3 spectra/capture_client/doctor.py`) with no package import — proven by importing it with `httpx` and `websockets` blocked at the meta path, and by running it inside a fresh Debian container with nothing installed at all. |
| **The installer verifies through to a REAL hello, and claims nothing else** | *(2026-09-02)* It probes the address BEFORE writing anything, and after starting the service it WAITS (bounded) for this machine to appear on `camera_host`, then reports what actually happened: connected (with the lever verdict), present-but-unable, the unit's own failure words, or never-arrived. The old unconditional "SPECTRA can now SEE this machine" is gone — it used to print that while installing a service that could not start. §8 of the service check, RED-verified against the old ending. |
| **The 216/GROUP case, on REAL systemd** | *(2026-09-02)* `scripts/check_capture_client_fresh_host.py` rig A: a transient `systemd-run --user` unit with `SupplementaryGroups=video`, on a user not in that group, produces the real `ExecMainStatus=216` / "Changing group credentials failed" — and the doctor's `/proc` predicate is cross-checked against that live outcome rather than against a typed-in constant. |
| **And on a host that never saw this repo** | Rig B: a stock `debian:stable-slim`, a user created seconds ago (not in `video`), the repo mounted read-only. The installer refuses on BOTH the group and the genuinely-missing `ensurepip`, in one pass, writing nothing; the doctor runs there standalone. |
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
- **`systemd` actually starting THE REAL UNIT.** The unit's TEXT is verified
  by systemd; its restart policy is executed by a supervisor that reads
  `Restart=`/`RestartSec=` out of the installed file. That proves what the
  unit tells systemd to do. **The first `systemctl --user enable --now` of
  the real unit on a real machine is still the measurement.**

  *Amended 2026-09-02:* the old sentence here said `systemctl --user`
  "cannot execute here at all". That was true of the shell it was written
  in and not of the machine: this host's user manager IS reachable once
  `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` are set (an agent shell
  usually has neither, and `systemctl --user` then fails with "Failed to
  connect to bus", which reads exactly like a missing service). So
  `check_capture_client_fresh_host.py` rig A now drives real systemd for the
  one thing that matters most — a genuine `216/GROUP` — and both the doctor
  and that script fill the two variables in rather than reporting the
  shell's condition as the machine's. What is still unproven is systemd
  starting **this unit, with its sandboxing directives, on his hardware**.
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

## THE SHORTEST PATH: one command, one reboot

*(2026-09-02. On 2026-09-01 this took nine steps and did not work at the end
of them, because each failure was found one at a time and none of them
reported itself.)*

On the machine with the camera, from a SpotFX checkout. **Run this first —
before installing anything.** It writes nothing, starts nothing and opens no
camera, and it tells you everything that is wrong at once instead of one
thing per attempt:

```bash
python3 spectra/capture_client/doctor.py --url http://spectra:8000/spectra
```

It needs no virtualenv and no dependencies — that is deliberate, because the
virtualenv is one of the things that can be broken. Do what it says (usually
one `apt install` line and one `usermod`), then:

```bash
sudo usermod -aG video "$USER"      # if the doctor asked for it
sudo loginctl enable-linger "$USER" # headless: start at boot, not at login

scripts/install_capture_client.sh \
    --url http://spectra:8000/spectra \
    --pose-name "the north shelf"

sudo reboot                          # if the group was just added
```

**The reboot is not superstition.** `usermod -aG` changes the group
database; it changes no running process. `systemd --user` takes its
supplementary groups once, when the manager starts, and — being unprivileged
— cannot gain one afterwards. So a fresh terminal can print `video` while
the manager that has to launch the unit still cannot, and the unit keeps
failing `216/GROUP` with everything you can see saying it is fine. The
doctor reads the *running manager's* own groups and says which of the two is
missing.

After the reboot, one command confirms the whole chain end to end:

```bash
spectra-capture-client --doctor
```

The installer itself now ends with the same answer: it probes the address
before writing anything, and after starting the service it **waits** for
this machine to actually appear on SPECTRA's `camera_host` surface and
prints what really happened. It no longer claims SPECTRA can see a machine
it never asked about.

### The rest of it

```bash
# every check, writing nothing at all:
scripts/install_capture_client.sh --check --url http://spectra:8000/spectra

# what the service itself is doing:
systemctl --user status spectra-capture-client
journalctl --user -u spectra-capture-client -f
```

On Debian-family systems (Debian, Ubuntu, Raspberry Pi OS) the standard
library's `venv` imports fine while the part that seeds pip into a new
environment ships separately, so a venv built without it comes out with no
pip. Both the installer and the doctor check for **that** rather than for
`import venv`, and refuse by name with the fix:
`sudo apt install -y python3-venv python3-pip`.

### What `--doctor` checks, in order

The order is the dependency order, so the FIRST failure is the one to fix
first — a venv with no pip in it makes every later answer meaningless. It
names one of four verdicts per line, and **`?` (could not check) is never
counted as a failure**: a blind spot reported as a fault sends you to fix a
machine that is working.

1. python; whether a venv built by it would contain pip (**ensurepip**, not
   `import venv`); and the installed virtualenv's own pip and dependencies.
2. `ffmpeg` and `v4l2-ctl`, each by name and package.
3. the camera device exists.
4. **group membership** — the predicate the unit's `SupplementaryGroups=`
   actually needs — and separately whether the **running user manager** has
   it yet (the reboot-pending case above). Deliberately *not* whether the
   device is readable: a desktop seat grants that through an ACL with no
   group in sight, which is how a machine whose unit could never start used
   to pass.
5. the address, in **three readings**: does the name resolve here, does
   anything accept a connection there, and is what answers actually SPECTRA
   (a missing `/spectra` prefix is the common one).
6. the unit: installed, enabled, running or crash-looping; its exit status
   translated (`216/GROUP` is a group problem, not a mystery); and its own
   last real journal line.
7. whether SPECTRA can see this machine — which is a different question from
   "is my service running", and they came apart on the evening this was
   written.

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
| `scripts/check_capture_client_fresh_host.py` | *(2026-09-02)* the same failures on machines that never saw this repo: **rig A** drives the host's own systemd user manager to a real `216/GROUP` and cross-checks the doctor's `/proc` predicate against that live outcome; **rig B** is a stock `debian:stable-slim` with a user created seconds ago (not in `video`, no `ensurepip`) where the installer refuses both by name and the doctor runs standalone. A rig it cannot run is SKIPPED with the reason named — never a pass |
| `tests/test_capture_doctor.py` | *(2026-09-02)* every doctor verdict, the reboot-pending case, the three readings of an address, the exit-status translation, the bounded wait's four outcomes, and that an UNKNOWN never counts as a failure |
| `scripts/check_capture_client_deps.py` | the import closure, the meta-path blocker, the fx/ boundary, the architecture audit |
| `tests/test_capture_client_service.py` | the configuration's rules, the presence record, and the two structural properties (no room authority, no server imports) |
| `tests/test_camera_pinned_settings.py` | settings written, read back, and re-asserted (pre-existing) |
| `scripts/check_capture_queue_e2e.py` | reconnect keeping the pose, and a reopen naming a new one (pre-existing) |

All three check scripts run from `tests/test_light_field_checks.py`, and
each prints what it did **not** prove as part of passing.

**Red-verified**, because a proof that cannot fail on the defect it was
written for is decoration. Each of these was confirmed to go RED against
the pre-fix behaviour before being kept: the `impaired` state (against a
`health()` that always said `present`), the group refusal (against the old
`[ -r $DEV ]` check, whose `/dev/null` device IS readable — so it passed
exactly as it did on his laptop), the installer's post-install verification
(against the old unconditional closing claim), and the reboot-pending
finding (against a doctor that checked membership only).
