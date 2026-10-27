"""The bot party (scripts/jukebox_bot_party.py, the plan's PR 2.3
acceptance): 30 phones over loopback through the REAL guest app into
SpotFX's real Jukebox routes, engine and guests (only Spotify faked), while a
probe measures how late SpotFX's event loop wakes. The acceptance run is 20
minutes (its numbers are in the PR); this is a short party run on every full
test run: the loop's stalls stay under 100 ms at the 99th percentile,
nothing answers with a server error, and the bots really did vote, add and
move songs."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_thirty_phones_never_stall_spotfxs_loop():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "jukebox_bot_party.py"),
                        "--bots", "30", "--seconds", "25", "--json"],
                       cwd=REPO, capture_output=True, text=True, timeout=240)
    assert r.stdout.strip(), f"no report:\n{r.stderr[-3000:]}"
    out = json.loads(r.stdout.strip().splitlines()[-1])
    loop = out["spotfx_loop_stall_ms"]
    assert out["pass"], json.dumps(out, indent=1)
    assert loop["n"] > 1000 and loop["p99"] < 100, loop
    did = out["bots_did"]
    assert out["night"]["phones"] == 30 and did.get("vote_up", 0) + did.get("vote_down", 0)
    assert did.get("add")
    assert not out["server_errors"] and {int(c) for c in out["status_codes"]} <= {200, 409, 422, 429}
