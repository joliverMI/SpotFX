# SPECTRA process split — deploy procedure (one pass, one room interruption)

Why: the 2026-08-13 frame-rate diagnosis (fleet data,
`spectra-framerate-diagnosis/report.md`) proved the chop was the whole
SpotFX application sharing one interpreter with the render threads — the
main event loop holds the GIL in 90 ms–5 s pure-Python bursts (worst on
track audio-analysis ingest) and every burst froze every virtual at once.
The same pipeline in an idle interpreter held a flawless 30/62 fps at 3–6 %
of one core. Process isolation is what made the old LedFX path smooth;
this split gives SPECTRA the same isolation.

What changed in the code (already landed when you read this):

- `python -m spectra` is SPECTRA's own process: her API/UI, the evolution
  engine, the fx render host, and `sys.setswitchinterval(0.001)` (the
  Stage-1 mitigation, applied at her process entry — see
  `spectra/app.py::_standalone`).
- The spot-effects app no longer mounts or starts anything under
  `spectra/`; `/spectra/*` on port 8000 is a transparent reverse proxy
  (`services/spectra_proxy.py`) to `settings.spectra_port` (8010). Every
  existing address — the owner's `/spectra/` bookmark, the liveness
  contract `GET :8000/spectra/api/liveness`, the handover API — keeps
  working verbatim, HTTP and WebSocket alike.
- Watchdog reconciliation (detection Option B, outage-scoping report §3):
  `spotfx.service` keeps the gate-health predicate
  (`services/write_plane_watchdog.py`); `spectra.service` gets its own
  `Type=notify`/`WatchdogSec=90` gated on frame-flush freshness
  (`spectra/services/frame_watchdog.py` — pings only while the render
  plane is provably alive or deliberately dark; dark-but-owned never
  restart-loops).

## The one-pass apply (owner-approved: new unit + watchdog lines together)

From the repo on the fleet box, after pulling the landed change and
rebuilding nothing (no frontend change is required for the split):

    cp deploy/spotfx.service deploy/spectra.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable spectra
    systemctl --user restart spotfx spectra     # ← the one interruption

Verify (all three in the first minute):

    systemctl --user status spotfx spectra          # both active (running)
    curl -s localhost:8000/spectra/api/status | jq .app        # "SPECTRA" (proxied)
    curl -s localhost:8010/spectra/api/liveness | jq .state    # direct port answers
    journalctl --user -u spotfx -u spectra -n 50    # no restart loops

Room-state note: restarting while SPECTRA owns the lights costs only the
restart gap — at process start a record that says `spectra` auto-resumes
the live stack through the guarded activation path (the twice-proven
dark-until-manual-cycle gap is closed; `docs/SPECTRA_HANDOVER.md`,
"restart while owner"). A FAILED resume lands dark-but-owned with liveness
503 — check `journalctl --user -u spectra` for the activation error.

## Addresses after the split

| What | Address |
|---|---|
| Owner's bookmark (unchanged) | `http://<host>:8000/spectra/` |
| Liveness contract (unchanged, proxied) | `GET http://<host>:8000/spectra/api/liveness` |
| Liveness, direct (preferred for the fleet checker) | `GET http://<host>:8010/spectra/api/liveness` |
| SPECTRA everything, direct | `http://<host>:8010/spectra/...` |

The proxied read shares the spot-effects event loop, so it inherits that
loop's stalls (the render plane does not — that is the point of the
split). Move the fleet checker to the direct port when convenient; the
proxied address stays contractual either way.

Direct-port caveat: browsing the UI at `:8010/spectra/` works except for
the colour-set/gradient pickers, which call spot-effects' `/api/*` on the
same origin — the UI's canonical address remains `:8000/spectra/`.

## Rollback

Stop and disable `spectra.service`, restore the previous `spotfx.service`,
check out the pre-split revision, restart spotfx. The pre-split process
serves `/spectra/` in-process again. The ownership record is untouched by
deploys in either direction.
