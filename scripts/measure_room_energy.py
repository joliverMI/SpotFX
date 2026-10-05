#!/usr/bin/env python3
"""Measure what SPECTRA costs the house: one process's CPU and the host's
UDP packets, over a window — the planner's own instrument, made repeatable
(data/standard-lighting-plan/report.md §6.1 and §13: `/proc/net/dev` on the
LAN interface, the kernel's UdpOutDatagrams counter that `nstat` reads, and
`/proc/<pid>/task/*/stat` for the process and its busiest threads, over a
60-90 s window).

READ-ONLY. It reads /proc and, when asked, GETs SPECTRA's own house status
(the energy block's per-fixture frames — an ESTIMATE from the fixtures' own
counters, printed beside the host's counters, never instead of them). It
writes nothing, drives nothing and takes nothing.

No default target, on purpose (a disposable worktree isolates the
filesystem, never the network or /proc): name the process with --pid, or
ask for the live service with --find-live (the `python -m spectra` whose
working directory is --live-dir).

  .venv/bin/python scripts/measure_room_energy.py --find-live --seconds 60 \\
      --spectra-url http://127.0.0.1:8010

The host counters are HOST-WIDE: anything else sending UDP in the window
counts too. Measure the released room first (the baseline) with the same
command, and compare.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from typing import Optional

CLK_TCK = os.sysconf("SC_CLK_TCK")


def default_iface() -> Optional[str]:
    """The interface carrying the default route (/proc/net/route)."""
    try:
        with open("/proc/net/route") as fh:
            next(fh)
            for line in fh:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000":
                    return parts[0]
    except OSError:
        return None
    return None


def iface_counters(iface: str) -> tuple[int, int]:
    """(tx_bytes, tx_packets) for one interface."""
    with open("/proc/net/dev") as fh:
        for line in fh:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            if name.strip() == iface:
                f = rest.split()
                return int(f[8]), int(f[9])
    raise SystemExit(f"no interface {iface!r} in /proc/net/dev")


def udp_out() -> int:
    """The kernel's Udp OutDatagrams (what `nstat UdpOutDatagrams` reads)."""
    with open("/proc/net/snmp") as fh:
        lines = [ln.split() for ln in fh if ln.startswith("Udp:")]
    header, values = lines[0], lines[1]
    return int(values[header.index("OutDatagrams")])


def proc_ticks(pid: int) -> int:
    with open(f"/proc/{pid}/stat") as fh:
        f = fh.read().rsplit(")", 1)[1].split()
    return int(f[11]) + int(f[12])          # utime + stime


def thread_ticks(pid: int) -> dict[str, tuple[str, int]]:
    out = {}
    base = f"/proc/{pid}/task"
    for tid in os.listdir(base):
        try:
            with open(f"{base}/{tid}/stat") as fh:
                raw = fh.read()
            name = raw[raw.index("(") + 1:raw.rindex(")")]
            f = raw.rsplit(")", 1)[1].split()
            out[tid] = (name, int(f[11]) + int(f[12]))
        except (OSError, ValueError, IndexError):
            continue
    return out


def find_live(live_dir: str) -> int:
    hits = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = fh.read().split(b"\0")
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        if b"-m" in argv and b"spectra" in argv and os.path.realpath(cwd) == os.path.realpath(live_dir):
            hits.append(int(pid))
    if len(hits) != 1:
        raise SystemExit(f"--find-live found {len(hits)} candidate(s) {hits} in {live_dir}; "
                         f"pass --pid")
    return hits[0]


def fetch_energy(url: str) -> Optional[dict]:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/spectra/api/house/mode", timeout=3) as r:
            body = json.load(r)
    except Exception as exc:                             # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"mode": (body.get("mode") or {}).get("name"), "phase": body.get("phase"),
            "energy": body.get("energy")}


def measure(pid: int, seconds: float, iface: str) -> dict:
    b0, p0 = iface_counters(iface)
    u0 = udp_out()
    c0 = proc_ticks(pid)
    t0_threads = thread_ticks(pid)
    w0 = time.monotonic()
    time.sleep(seconds)
    w1 = time.monotonic()
    b1, p1 = iface_counters(iface)
    u1 = udp_out()
    c1 = proc_ticks(pid)
    t1_threads = thread_ticks(pid)
    span = w1 - w0
    threads = []
    for tid, (name, ticks) in t1_threads.items():
        before = t0_threads.get(tid, (name, ticks))[1]
        pct = 100.0 * (ticks - before) / CLK_TCK / span
        threads.append({"tid": int(tid), "name": name, "cpu_pct": round(pct, 1)})
    threads.sort(key=lambda t: -t["cpu_pct"])
    return {
        "window_s": round(span, 1),
        "pid": pid,
        "cpu_pct_of_one_core": round(100.0 * (c1 - c0) / CLK_TCK / span, 1),
        "udp_out_datagrams_per_s": round((u1 - u0) / span, 1),
        "iface": iface,
        "iface_tx_packets_per_s": round((p1 - p0) / span, 1),
        "iface_tx_kbytes_per_s": round((b1 - b0) / 1024.0 / span, 1),
        "top_threads": threads[:8],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--pid", type=int)
    who.add_argument("--find-live", action="store_true")
    ap.add_argument("--live-dir", default="/home/javi/SpotFX")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--iface", default=None)
    ap.add_argument("--spectra-url", default=None,
                    help="also GET this SPECTRA's house status (energy block)")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    pid = args.pid if args.pid is not None else find_live(args.live_dir)
    iface = args.iface or default_iface()
    if not iface:
        raise SystemExit("no default-route interface; pass --iface")
    before = fetch_energy(args.spectra_url) if args.spectra_url else None
    out = measure(pid, args.seconds, iface)
    out["label"] = args.label
    if args.spectra_url:
        out["spectra_before"] = before
        out["spectra_after"] = fetch_energy(args.spectra_url)
    json.dump(out, sys.stdout, indent=2)
    print()
    print(f"# {args.label or 'window'}: {out['cpu_pct_of_one_core']}% of one core, "
          f"{out['udp_out_datagrams_per_s']} UDP datagrams/s, "
          f"{out['iface_tx_packets_per_s']} {iface} packets/s, "
          f"{out['iface_tx_kbytes_per_s']} KB/s over {out['window_s']} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
