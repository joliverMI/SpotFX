# SPECTRA light handover — operator procedure

The S3 machinery is BUILT AND PROVEN but the room changes hands only on the
product owner's explicit word. This is the exact procedure for that day,
including rollback. Nothing here runs on its own: the handover API refuses
until the process is deliberately armed.

The binding rule (Admiral's architecture decision): exactly one process owns
the lights — spot-effects (the external LedFX service) or SPECTRA (the
in-process fx/ pipeline) — never both. The durable record is
`storage/spectra/ownership.json`; a missing record means the shipped
default: **spot-effects owns**.

## Addresses

Since the S3 process split, SPECTRA runs as her own process
(`spectra.service`, port 8010 — `docs/SPECTRA_PROCESS_SPLIT.md`). Every
port-8000 address below still works verbatim through the spot-effects
reverse proxy; the same paths on port 8010 reach the SPECTRA process
directly and are preferred for the fleet checker (they do not share the
spot-effects event loop's stalls).

| What | Address |
|---|---|
| Ownership record (inspect) | `GET http://<host>:8000/spectra/api/ownership` |
| **Liveness (THE binding contract)** | `GET http://<host>:8000/spectra/api/liveness` (direct: `:8010`, same path) |
| Handover (armed only) | `POST http://<host>:8000/spectra/api/ownership/handover` |
| Orphan recovery | `POST http://<host>:8000/spectra/api/ownership/recover` |
| spot-effects side of the record | `GET http://<host>:8000/api/debug/ledfx-health` (`light_ownership` field) |
| **Panic release (NOT armed-gated)** | `POST http://<host>:8000/spectra/api/ownership/release` |

The liveness endpoint serves per-virtual frame-flush freshness from the real
render/write path (HTTP 200 healthy / 503 not), computed inside the SPECTRA
process. **Never delete or repoint it without the Admiral's word** (the
contract in `data/spectra-design-decisions.md`).

## Panic release — the emergency exit, no arming required

Unlike the handover below, `POST /spectra/api/ownership/release` is NOT
gated by `SPECTRA_HANDOVER_ARMED` and needs no body — one press (the SPECTRA
UI's red "Release to Home Assistant" button, or the bare POST) and whichever
world owned the room lets go: the ownership record moves to `released`
first (both worlds' write gates shed immediately), then each device is told
to let go explicitly — WLED gets the JSON API's `{"live": false}`, Hue's
entertainment session is stopped, the external LedFX service's active
virtuals are deactivated over its own API. Home Assistant then has ordinary
direct control of every device. Idempotent (press it again, nothing errors);
refuses (409) only if a handover happens to be mid-flight at that exact
instant — wait a beat and press again.

The way back is the SAME guarded handover as below (`{"to": "spectra"}`),
still armed- and readiness-gated — released is just another `from_world` to
it, with nothing to quiesce. See `fx/light_ownership.py` (the `RELEASED`
state) and `spectra/services/release.py` for the implementation; per-device
RELEASED semantics are documented in `spectra/web/src/help/helpContent.ts`
(topic `panic-release`).

**The way back TOLERATES a partial activation (owner ruling 2026-08-21:
"one unreachable device must not be able to keep his entire room dark").**
Before this, the take-back aborted the whole room — tearing down every
light that HAD come up — the instant any one device could not be confirmed
driving, and landed "back" at released, which is darkness, not safety; he
hit it six times in one night on one WLED whose mDNS name would not resolve
and twice the morning before on two sconces that merely answered too
slowly. Aborting never saved the unreachable light. Now, when the stack
comes up with at least one expected virtual driving but some device (or
virtual) could not be confirmed, the take-back **commits**: HTTP 200,
`result: "committed-partial"`, with an `activation` report naming every
skipped light and why (`spectra/services/activation_report.py`); the
ownership record's own history note for that commit names it too; the
same report rides on `GET /spectra/api/ownership` (`activation`) and, as an
informational (never `healthy`-affecting) key, on `GET /spectra/api/
liveness`; the SPECTRA UI shows an amber strip on every page and a line on
the Status page. Every 30 s the still-dark lights are re-asked (the same
probe the activation used) and a light whose name never resolved gets its
own driver re-initialized, so a light fixed afterwards joins the running
show by itself — no second release/take-back cycle to collect one fixture.
A HARD failure — the stack never comes up, or not one expected virtual is
driving — still aborts back to released exactly as before (502). **Scope
is bounded**: only the way back from `released` is tolerant; a handover
FROM a running world keeps its strict all-or-nothing rollback below.
Proofs: `tests/test_take_back_partial.py` (real FxHost + real WLED driver
against a genuinely unresolvable `.invalid` name, through the real armed
route), `scripts/check_ownership.py` §12b.

## Preparation (any time before go day, all read-only for the room)

1. Seed SPECTRA's live device config from the running LedFX install:

       .venv/bin/python scripts/seed_spectra_fx_live.py            # dry-run report
       .venv/bin/python scripts/seed_spectra_fx_live.py --apply    # writes storage/spectra/fx-live/config.json

   Re-run `--apply` after any LedFX device/virtual change; it is idempotent.

   **This step is ENFORCED, not remembered** (the order-8 correction): the
   switch itself checks it as a precondition and REFUSES — before quiescing
   the current owner, with the room untouched — when the fx-live config is
   missing, unreadable, empty, or has zero virtuals backed by a vendored
   driver type. The refusal (HTTP 412) names the missing preparation and
   this seeder command. Skipping this step can no longer dark the room; it
   just refuses the switch.
2. Confirm the record and the dark liveness state:

       curl -s localhost:8000/spectra/api/ownership | jq .owner        # "spot-effects"
       curl -s localhost:8000/spectra/api/liveness  | jq .state        # "dark", healthy: true
3. Song source: with `song_source = "ledfx"` in settings, stopping LedFX also
   stops track detection and SPECTRA's bridge degrades to neutral 0.5
   intensity (stated behavior). The default `spotify` source is unaffected —
   confirm it before go day.
4. Run the proofs:

       .venv/bin/python scripts/check_ownership.py
       .venv/bin/python -m pytest tests/test_handover.py -q

Preparation accounting — every rememberable step is either enforced by the
switch or stated here as why it stays an operator note:
- Step 1 (fx-live seed): **enforced** (the readiness gate above).
- Step 2 (record + liveness confirm): **enforced structurally** — an
  in-flight or already-owner record refuses at `begin_handover` (409), and
  a live stack without ownership trips the liveness split-brain 503.
- Step 3 (song source): stays an operator note. It is stated degraded
  behaviour, not a room-safety issue, and checking spot-effects settings
  from SPECTRA would cross the import boundary the architecture forbids.
- Step 4 (proofs): development-time, not checkable at switch time.
- Reverse direction: the LedFX unit's existence is **enforced** (readiness
  gate on the rollback path).

## Go day — taking the room (spot-effects → SPECTRA)

1. **Arm** (the owner's word, expressed as an env latch on the process —
   since the process split the handover API runs in the SPECTRA process,
   so the latch goes on HER unit):

       systemctl --user edit spectra    # add:
       # [Service]
       # Environment=SPECTRA_HANDOVER_ARMED=1
       systemctl --user restart spectra

2. **Switch**:

       curl -s -X POST localhost:8000/spectra/api/ownership/handover \
            -H 'content-type: application/json' -d '{"to": "spectra"}' | jq .

   What runs, in order (services/handover.py):
   0. **readiness gate** — SPECTRA's fx-live config is checked (present,
      readable, at least one virtual backed by a vendored driver type). A
      problem REFUSES the whole handover right here: HTTP 412, the record
      never moves, LedFX keeps running, the room is untouched. This is the
      enforced form of preparation step 1.
   1. record → `handing-over/quiescing`; both write planes shed instantly.
   2. quiesce: `systemctl --user stop ledfx` + verify `is-active` says
      stopped (Hue DTLS session released, DDP sending stopped), then a 5 s
      grace for the bridge to free the session.
   3. record → `activating` (only now can the device grant mint).
   4. activate: FxHost on `storage/spectra/fx-live` (real driver init —
      Hue handshake, DDP senders), the Stage-2 audio hub opens the capture
      device, the engine swaps to the facade executor, and the handover
      waits for every active virtual to flush fresh frames.
   5. record → `owner: spectra` (commit).

3. **Verify**:

       curl -s localhost:8000/spectra/api/liveness | jq '{state, healthy, virtuals}'
       curl -s localhost:8000/api/debug/ledfx-health | jq .light_ownership   # "spectra"

   A `502` response instead means a step failed and the handover **landed
   back at spot-effects** (LedFX restarted, record settled) — read
   `.error` and the record's `history`; the room never splits. (From
   `released` only: a `200` with `result: "committed-partial"` means the
   room came up minus the lights named in `.activation` — see "Panic
   release" above.)

4. **Repoint the fleet checker** to `GET /spectra/api/liveness` (200/503).

## Rollback — giving the room back (SPECTRA → spot-effects)

    curl -s -X POST localhost:8000/spectra/api/ownership/handover \
         -H 'content-type: application/json' -d '{"to": "spot-effects"}' | jq .

Reverse order: **readiness gate first** — the LedFX service unit must exist
(`systemctl --user cat <unit>`), else the switch refuses with SPECTRA still
running (a missing unit would otherwise only surface after SPECTRA went
dark). Then: engine dark → live stack torn down (render threads joined,
devices deactivated — Hue session released, DDP stopped, audio closed) →
verify → `systemctl --user start ledfx` + wait for `/api/info` → commit.
spot-effects' own reassert machinery then pushes cached effect state.

**Disarm afterwards** (remove the Environment line, restart spectra) unless
more switches are planned.

**Restart while SPECTRA owns**: a spectra.service restart (deploy, crash,
watchdog) auto-resumes — at process start, a record that says `spectra`
reactivates the live stack through the same guarded path the handover uses
(grant + frame-freshness readiness gate; `handover.resume_own_room`). No
handover cycle needed. If the resume FAILS outright (stack never up, seed
missing), the process lands dark-but-owned and keeps serving — liveness
answers 503 `state: "dark"` and the record is untouched; fix the cause and
restart spectra, or hand the room back manually. A PARTIAL resume (the
stack is up, one device could not be confirmed) keeps every other light
driving and reports the skipped light the same way a partial take-back
does (the `activation` report above; liveness `activation_gaps` still
flips `healthy` for a virtual that never came up).

## If things go wrong

- **Refused handover (HTTP 412)**: not a failure — the readiness gate
  stopped the switch BEFORE anything happened. The room is untouched, the
  record never moved, nothing to clean up. The `.error` names the missing
  preparation and its command; do it and switch again.
- **Failed handover**: lands single-owner automatically (the proofs cover
  the §4d failure modes: Hue session exclusivity, handshake timeouts, a
  quiesce that lies). Nothing to clean up; retry when ready.
- **Partial take-back (from released, HTTP 200 `committed-partial`)**: not
  a failure — the room is up on every light that answered; the named
  light is dark because it could not be reached. Fix the light (power,
  network, its mDNS name); SPECTRA rechecks it every 30 s and brings it
  in on its own. Do NOT release and take back again just for it — that
  blinks every other light for nothing.
- **Crash mid-handover**: the record may be orphaned at `handing-over` —
  both worlds refuse to write (dark but safe). It lands back at the
  from-world automatically at the next engine start (age-gated, 120 s), or
  immediately via `POST /spectra/api/ownership/recover`.
- **Manual last resort** (process down, room dark):

      systemctl --user stop spectra            # the only possible SPECTRA writer
      rm storage/spectra/ownership.json        # missing record = spot-effects owns
      systemctl --user start ledfx spectra

- Watchdog notes, both already ownership-aware: spot-effects' LedFX-restart
  watchdog is dormant while not owner (it must not resurrect the stopped
  service — the §4d trap), and the systemd write-plane watchdog treats a
  surrendered write plane as alive (no completions is then the correct
  state; the liveness endpoint is the room's health signal).

## Standing constraints

- Never run both stacks against the lights — the gates enforce it, don't
  fight them.
- The SPECTRA sequencer stays dark (`storage/spectra/sequencer.json`
  `enabled: false`) — enabling it is a separate owner decision.
- The `deploy/spotfx.service` watchdog lines remain a separate owner action;
  nothing in the handover changes the unit.
