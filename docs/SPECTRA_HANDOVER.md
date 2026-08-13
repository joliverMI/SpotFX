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

| What | Address |
|---|---|
| Ownership record (inspect) | `GET http://<host>:8000/spectra/api/ownership` |
| **Liveness (THE binding contract)** | `GET http://<host>:8000/spectra/api/liveness` |
| Handover (armed only) | `POST http://<host>:8000/spectra/api/ownership/handover` |
| Orphan recovery | `POST http://<host>:8000/spectra/api/ownership/recover` |
| spot-effects side of the record | `GET http://<host>:8000/api/debug/ledfx-health` (`light_ownership` field) |

The liveness endpoint serves per-virtual frame-flush freshness from the real
render/write path (HTTP 200 healthy / 503 not). After the eventual process
split it stays at `/spectra/api/liveness` on SPECTRA's own port — the
fleet's external write-plane checker survives with at most a host:port
change. **Never delete or repoint it without the Admiral's word** (the
contract in `data/spectra-design-decisions.md`).

## Preparation (any time before go day, all read-only for the room)

1. Seed SPECTRA's live device config from the running LedFX install:

       .venv/bin/python scripts/seed_spectra_fx_live.py            # dry-run report
       .venv/bin/python scripts/seed_spectra_fx_live.py --apply    # writes storage/spectra/fx-live/config.json

   Re-run `--apply` after any LedFX device/virtual change; it is idempotent.
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

## Go day — taking the room (spot-effects → SPECTRA)

1. **Arm** (the owner's word, expressed as an env latch on the process):

       systemctl --user edit spotfx     # add:
       # [Service]
       # Environment=SPECTRA_HANDOVER_ARMED=1
       systemctl --user restart spotfx

2. **Switch**:

       curl -s -X POST localhost:8000/spectra/api/ownership/handover \
            -H 'content-type: application/json' -d '{"to": "spectra"}' | jq .

   What runs, in order (services/handover.py):
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
   `.error` and the record's `history`; the room never splits.

4. **Repoint the fleet checker** to `GET /spectra/api/liveness` (200/503).

## Rollback — giving the room back (SPECTRA → spot-effects)

    curl -s -X POST localhost:8000/spectra/api/ownership/handover \
         -H 'content-type: application/json' -d '{"to": "spot-effects"}' | jq .

Reverse order: engine dark → live stack torn down (render threads joined,
devices deactivated — Hue session released, DDP stopped, audio closed) →
verify → `systemctl --user start ledfx` + wait for `/api/info` → commit.
spot-effects' own reassert machinery then pushes cached effect state.

**Disarm afterwards** (remove the Environment line, restart spotfx) unless
more switches are planned.

## If things go wrong

- **Failed handover**: lands single-owner automatically (the proofs cover
  the §4d failure modes: Hue session exclusivity, handshake timeouts, a
  quiesce that lies). Nothing to clean up; retry when ready.
- **Crash mid-handover**: the record may be orphaned at `handing-over` —
  both worlds refuse to write (dark but safe). It lands back at the
  from-world automatically at the next engine start (age-gated, 120 s), or
  immediately via `POST /spectra/api/ownership/recover`.
- **Manual last resort** (process down, room dark):

      systemctl --user stop spotfx
      rm storage/spectra/ownership.json        # missing record = spot-effects owns
      systemctl --user start ledfx spotfx

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
