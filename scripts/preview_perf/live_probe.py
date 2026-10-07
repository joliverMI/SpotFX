"""Read-only measurement of the preview stream under a REAL show, on the
live services (preview-perf plan, phase 4 / change 7).

It touches no light and changes nothing: it opens two protocol-2 viewer
connections of its own from this host — one through the spot-effects
reverse proxy (:8000, the path his browser takes) and one direct to the
Spectra process (:8010) — acks every tick like the browser does, and records
what each path delivers. Because the probe and the server share one clock,
`arrival - sent_ms` is the exact one-way delay of each message, so the two
paths differ ONLY by the proxy hop: the Tailscale link is not in either.

The link itself is read off the kernel: every `--ss-period` seconds it
samples `ss -tin` for the established sockets on :8000 and :8010 whose peer
is a Tailscale address (100.64.0.0/10) — his real browser's connection —
and keeps rtt, min rtt, retransmits, unacked segments, the kernel's queued
bytes (Send-Q / notsent) and the busy time. Nothing is written to those
sockets.

Beside both, every `--http-period` seconds it times one GET of the liveness
endpoint through each port, which shows an event-loop stall in either
process as a latency spike independent of the preview stream.

HIS REAL PATH (measured 2026-10-07): the browser reaches
https://serenity.tailb5ca89.ts.net, which is `tailscale serve` proxying
`/` to http://127.0.0.1:8000 — so his connections arrive as 127.0.0.1
sockets owned by tailscaled (`--loopback-peers`), never as 100.x peers,
and the kernel sees only the loopback leg of his link. `--extra-url` adds
a third viewer against any URL (e.g. the serve hostname itself) so a
routing change can be verified from this host after it is applied:

  .venv/bin/python scripts/preview_perf/live_probe.py --out <dir> \
      --duration 60 --extra-url serve=wss://serenity.tailb5ca89.ts.net/spectra/api/device-preview/ws

Usage (from the repo root, the live services up):

  .venv/bin/python scripts/preview_perf/live_probe.py --out <dir> \
      --wait --duration 600

With `--wait` it polls once a minute until music is playing AND a Tailscale
viewer is connected to the preview, then measures for `--duration` seconds.
Without it, it measures at once. Results: `<out>/probe.json` (every sample)
and `<out>/probe.md` (the summary table). Exit 0 when a measurement was
taken, 3 when `--wait-until` passed with nothing to measure.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import websockets

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from spectra.services.preview_stream import decode_message  # noqa: E402

logger = logging.getLogger("live_probe")

WS_PATH = "/spectra/api/device-preview/ws"
STATUS_PATH = "/spectra/api/device-preview/status"
ENGINE_PATH = "/spectra/api/engine/status"
LIVENESS_PATH = "/spectra/api/liveness"
TAILSCALE_RE = re.compile(r"^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.")
GAP_MS = 100.0


def percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# ── the kernel's view of his socket ──────────────────────────────────────

LOOPBACK_PEERS = False
OWN_PEERS: set[str] = set()


def tailscale_sockets(ports: tuple[int, ...] = (8000, 8010)) -> list[dict]:
    """`ss -tin` rows for established sockets on `ports` whose peer is a
    Tailscale address — or, with `LOOPBACK_PEERS` (his path through
    `tailscale serve`: https://<host>.ts.net -> tailscaled -> 127.0.0.1:8000),
    whose peer is 127.0.0.1 and is not one of this probe's own connections.
    Each row: port, peer, send_q, recv_q and the parsed info line (rtt,
    minrtt, retrans, unacked, notsent, busy, ...). On the serve path the
    kernel sees only the loopback leg; his Tailscale link lives inside
    tailscaled, so Send-Q/notsent there mean "tailscaled has not read it
    yet", i.e. backpressure from his link."""
    filt = " or ".join(f"sport = :{p}" for p in ports)
    try:
        out = subprocess.run(["ss", "-tin", "state", "established", f"( {filt} )"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[dict] = []
    lines = out.splitlines()
    i = 0
    while i < len(lines):
        parts = lines[i].split()
        if len(parts) >= 4 and ":" in parts[2] and ":" in parts[3] and not lines[i].startswith("\t") \
                and parts[0].isdigit():
            recv_q, send_q, local, peer = int(parts[0]), int(parts[1]), parts[2], parts[3]
            info = lines[i + 1] if i + 1 < len(lines) and lines[i + 1].startswith("\t") else ""
            i += 2 if info else 1
            peer_ip = peer.rsplit(":", 1)[0]
            if LOOPBACK_PEERS:
                if peer_ip != "127.0.0.1" or peer in OWN_PEERS:
                    continue
            elif not TAILSCALE_RE.match(peer_ip):
                continue
            port = int(local.rsplit(":", 1)[1])
            rows.append({"port": port, "peer": peer, "send_q": send_q, "recv_q": recv_q,
                         **parse_ss_info(info)})
        else:
            i += 1
    return rows


def parse_ss_info(info: str) -> dict:
    d: dict = {}
    m = re.search(r"\brtt:([\d.]+)/([\d.]+)", info)
    if m:
        d["rtt_ms"], d["rtt_var_ms"] = float(m.group(1)), float(m.group(2))
    for key in ("minrtt", "retrans", "unacked", "notsent", "busy", "cwnd",
                "bytes_sent", "bytes_retrans", "lastsnd", "lastack"):
        m = re.search(rf"\b{key}:([\d./]+)(ms)?", info)
        if m:
            val = m.group(1)
            if key == "retrans":           # "retrans:0/8" = current/total
                cur, tot = val.split("/")
                d["retrans_now"], d["retrans_total"] = int(cur), int(tot)
            else:
                try:
                    d[key] = float(val) if "." in val else int(val)
                except ValueError:
                    pass
    return d


# ── one protocol-2 viewer ───────────────────────────────────────────────

@dataclass
class ViewerRecord:
    name: str
    url: str
    arrivals: list[float] = field(default_factory=list)        # time.time()
    delays_ms: list[float] = field(default_factory=list)       # arrival - sent_ms
    ages_ms: list[int] = field(default_factory=list)           # max record age
    rates: list[int] = field(default_factory=list)
    srtts_ms: list[int] = field(default_factory=list)
    seqs: list[int] = field(default_factory=list)
    bytes: int = 0
    messages: int = 0
    rate_changes: list[tuple[float, int]] = field(default_factory=list)
    opened_at: Optional[float] = None
    closed_reason: Optional[str] = None

    def summary(self) -> dict:
        span = (self.arrivals[-1] - self.arrivals[0]) if len(self.arrivals) > 1 else 0.0
        intervals = [(b - a) * 1000 for a, b in zip(self.arrivals, self.arrivals[1:])]
        seq_gaps = sum(1 for a, b in zip(self.seqs, self.seqs[1:]) if b - a > 1)
        rate_hist: dict[int, int] = {}
        for r in self.rates:
            rate_hist[r] = rate_hist.get(r, 0) + 1
        return {
            "name": self.name, "url": self.url, "messages": self.messages,
            "seconds": round(span, 1),
            "delivered_fps": round(self.messages / span, 2) if span > 0 else None,
            "delay_ms": {"p50": percentile(self.delays_ms, 0.5),
                         "p95": percentile(self.delays_ms, 0.95),
                         "p99": percentile(self.delays_ms, 0.99),
                         "max": max(self.delays_ms) if self.delays_ms else None},
            "interval_ms": {"p50": percentile(intervals, 0.5),
                            "p95": percentile(intervals, 0.95),
                            "max": max(intervals) if intervals else None,
                            "gaps_over_100ms": sum(1 for x in intervals if x > GAP_MS)},
            "server_age_ms": {"p50": percentile([float(a) for a in self.ages_ms], 0.5),
                              "p95": percentile([float(a) for a in self.ages_ms], 0.95),
                              "max": max(self.ages_ms) if self.ages_ms else None},
            "srtt_ms": {"p50": percentile([float(s) for s in self.srtts_ms], 0.5),
                        "max": max(self.srtts_ms) if self.srtts_ms else None},
            "rate_fps_share": {str(k): round(v / max(1, len(self.rates)), 3)
                               for k, v in sorted(rate_hist.items())},
            "rate_changes": len(self.rate_changes),
            "seq_gaps": seq_gaps,
            "kbit_s": round(self.bytes * 8 / span / 1000, 1) if span > 0 else None,
            "closed_reason": self.closed_reason,
        }


async def run_viewer(rec: ViewerRecord, stop_at: float, level: str, scope: str,
                     connected: Optional[asyncio.Event] = None) -> None:
    try:
        async with websockets.connect(rec.url, open_timeout=5, max_size=2 ** 24,
                                      ping_interval=None) as ws:
            rec.opened_at = time.time()
            try:
                sock = ws.transport.get_extra_info("sockname")
                OWN_PEERS.add(f"{sock[0]}:{sock[1]}")
            except Exception:
                pass
            if connected is not None:
                connected.set()
            await ws.send(json.dumps({"type": "hello", "protocol": 2,
                                      "level": level, "scope": scope}))
            last_rate: Optional[int] = None
            while time.time() < stop_at:
                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=max(0.1, stop_at - time.time()))
                except asyncio.TimeoutError:
                    break
                now = time.time()
                if isinstance(data, str):
                    continue
                msg = decode_message(data)
                await ws.send(json.dumps({"type": "ack", "seq": msg["seq"]}))
                rec.messages += 1
                rec.bytes += len(data)
                rec.arrivals.append(now)
                rec.delays_ms.append(now * 1000.0 - msg["sent_ms"])
                rec.ages_ms.append(max((r["age_ms"] for r in msg["records"]), default=0))
                rec.rates.append(msg["rate_fps"])
                rec.srtts_ms.append(msg["srtt_ms"])
                rec.seqs.append(msg["seq"])
                if last_rate is not None and msg["rate_fps"] != last_rate:
                    rec.rate_changes.append((now, msg["rate_fps"]))
                last_rate = msg["rate_fps"]
    except Exception as exc:      # the measurement reports, it never raises
        rec.closed_reason = repr(exc)
    finally:
        if connected is not None:
            connected.set()


# ── the side samplers ──────────────────────────────────────────────────

VIEWER_READY_TIMEOUT_S = 10.0


async def sample_sockets(samples: list[dict], stop_at: float, period: float,
                         ready_events: Optional[list[asyncio.Event]] = None) -> None:
    """Waits for every viewer's own connect (success or failure) to finish —
    so its socket is in `OWN_PEERS` before the first sample under
    `--loopback-peers` — then samples off the event loop (`ss` shells out
    and can cost tens of ms, which would otherwise delay every viewer's
    `ws.recv()` for the duration of the call)."""
    if ready_events:
        try:
            await asyncio.wait_for(
                asyncio.gather(*(e.wait() for e in ready_events)),
                timeout=VIEWER_READY_TIMEOUT_S)
        except asyncio.TimeoutError:
            pass
    while time.time() < stop_at:
        samples.append({"at": time.time(), "sockets": await asyncio.to_thread(tailscale_sockets)})
        await asyncio.sleep(period)


async def sample_http(samples: list[dict], stop_at: float, period: float,
                      ports: tuple[int, ...]) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        while time.time() < stop_at:
            row = {"at": time.time()}
            for port in ports:
                t0 = time.perf_counter()
                try:
                    r = await client.get(f"http://127.0.0.1:{port}{LIVENESS_PATH}")
                    row[str(port)] = {"ms": round((time.perf_counter() - t0) * 1000, 1),
                                      "status": r.status_code}
                except httpx.HTTPError as exc:
                    row[str(port)] = {"ms": None, "error": repr(exc)}
            samples.append(row)
            await asyncio.sleep(period)


async def sample_engine(samples: list[dict], stop_at: float, period: float) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        while time.time() < stop_at:
            try:
                r = await client.get(f"http://127.0.0.1:8010{ENGINE_PATH}")
                d = r.json()
                track = (d.get("bridge") or {}).get("track") or {}
                samples.append({"at": time.time(), "is_playing": track.get("is_playing"),
                                "uri": track.get("uri") or track.get("spotify_uri"),
                                "position_ms": track.get("position_ms") or track.get("progress_ms")})
            except Exception as exc:
                samples.append({"at": time.time(), "error": repr(exc)})
            await asyncio.sleep(period)


# ── readiness ──────────────────────────────────────────────────────────

def readiness() -> dict:
    """Is music playing, and is a Tailscale viewer on the preview? Read-only."""
    out = {"at": time.time(), "is_playing": None, "preview": None, "tailscale_sockets": []}
    try:
        with httpx.Client(timeout=5.0) as client:
            eng = client.get(f"http://127.0.0.1:8010{ENGINE_PATH}").json()
            track = (eng.get("bridge") or {}).get("track") or {}
            out["is_playing"] = bool(track.get("is_playing"))
            out["dark"] = eng.get("dark")
            out["preview"] = client.get(f"http://127.0.0.1:8010{STATUS_PATH}").json()
    except Exception as exc:
        out["error"] = repr(exc)
    out["tailscale_sockets"] = [{"port": s["port"], "peer": s["peer"]}
                                for s in tailscale_sockets()]
    prev = out.get("preview") or {}
    out["viewer_connected"] = bool(prev.get("connected")) and not prev.get("paused") \
        and (LOOPBACK_PEERS or bool(out["tailscale_sockets"]))
    out["ready"] = bool(out["is_playing"]) and out["viewer_connected"]
    return out


# ── the measurement ────────────────────────────────────────────────────

async def measure(out_dir: Path, duration: float, level: str, scope: str,
                  ss_period: float, http_period: float,
                  extra_urls: Optional[list[tuple[str, str]]] = None) -> dict:
    stop_at = time.time() + duration
    proxied = ViewerRecord("proxy :8000", f"ws://127.0.0.1:8000{WS_PATH}")
    direct = ViewerRecord("direct :8010", f"ws://127.0.0.1:8010{WS_PATH}")
    extras = [ViewerRecord(name, url) for name, url in (extra_urls or [])]
    all_viewers = [proxied, direct, *extras]
    ready_events = [asyncio.Event() for _ in all_viewers]
    sockets: list[dict] = []
    http: list[dict] = []
    engine: list[dict] = []
    started = time.time()
    await asyncio.gather(
        *[run_viewer(rec, stop_at, level, scope, connected=ev)
          for rec, ev in zip(all_viewers, ready_events)],
        sample_sockets(sockets, stop_at, ss_period, ready_events=ready_events),
        sample_http(http, stop_at, http_period, (8000, 8010)),
        sample_engine(engine, stop_at, 5.0),
    )
    result = {
        "started": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
        "duration_s": round(time.time() - started, 1),
        "level": level, "scope": scope,
        "viewers": {"proxy": proxied.summary(), "direct": direct.summary(),
                    **{x.name: x.summary() for x in extras}},
        "proxy_hop_ms": hop_summary(proxied, direct),
        "his_sockets": socket_summary(sockets),
        "liveness_ms": http_summary(http),
        "playing_share": round(sum(1 for e in engine if e.get("is_playing")) / max(1, len(engine)), 2),
        "samples": {"proxy": viewer_rows(proxied), "direct": viewer_rows(direct),
                    "sockets": sockets, "http": http, "engine": engine},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "probe.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (out_dir / "probe.md").write_text(render_md(result), encoding="utf-8")
    return result


def viewer_rows(rec: ViewerRecord) -> list[list]:
    return [[round(a, 3), round(d, 1), g, r, s, q] for a, d, g, r, s, q in
            zip(rec.arrivals, rec.delays_ms, rec.ages_ms, rec.rates, rec.srtts_ms, rec.seqs)]


def hop_summary(proxied: ViewerRecord, direct: ViewerRecord) -> dict:
    """The proxy hop's own cost: the proxied path's delay minus the direct
    path's, at matched percentiles (both paths carry the same frames of
    the same show at the same moments)."""
    out = {}
    for p in (0.5, 0.95, 0.99):
        a, b = percentile(proxied.delays_ms, p), percentile(direct.delays_ms, p)
        out[f"p{int(p * 100)}"] = round(a - b, 1) if a is not None and b is not None else None
    return out


def socket_summary(samples: list[dict]) -> dict:
    by_peer: dict[str, list[dict]] = {}
    for s in samples:
        for row in s["sockets"]:
            by_peer.setdefault(f"{row['peer']}->:{row['port']}", []).append(row)
    out = {}
    for key, rows in by_peer.items():
        rtts = [r["rtt_ms"] for r in rows if "rtt_ms" in r]
        out[key] = {
            "samples": len(rows),
            "rtt_ms": {"p50": percentile(rtts, 0.5), "p95": percentile(rtts, 0.95),
                       "max": max(rtts) if rtts else None},
            "minrtt_ms": min((r["minrtt"] for r in rows if "minrtt" in r), default=None),
            "retrans_total_delta": (max(r.get("retrans_total", 0) for r in rows)
                                    - min(r.get("retrans_total", 0) for r in rows)),
            "bytes_retrans_delta": (max(r.get("bytes_retrans", 0) for r in rows)
                                    - min(r.get("bytes_retrans", 0) for r in rows)),
            "bytes_sent_delta": (max(r.get("bytes_sent", 0) for r in rows)
                                 - min(r.get("bytes_sent", 0) for r in rows)),
            "send_q_max": max(r["send_q"] for r in rows),
            "send_q_p95": percentile([float(r["send_q"]) for r in rows], 0.95),
            "notsent_max": max((r.get("notsent", 0) for r in rows), default=0),
            "unacked_max": max((r.get("unacked", 0) for r in rows), default=0),
        }
    return out


def http_summary(samples: list[dict]) -> dict:
    out = {}
    for port in ("8000", "8010"):
        ms = [s[port]["ms"] for s in samples if s.get(port, {}).get("ms") is not None]
        out[port] = {"samples": len(ms), "p50": percentile(ms, 0.5),
                     "p95": percentile(ms, 0.95), "max": max(ms) if ms else None,
                     "errors": sum(1 for s in samples if s.get(port, {}).get("ms") is None)}
    return out


def _f(v, nd=1) -> str:
    return "-" if v is None else f"{v:.{nd}f}"


def render_md(r: dict) -> str:
    v = r["viewers"]
    lines = [f"# Live preview probe — {r['started']} ({r['duration_s']} s, level={r['level']}, "
             f"scope={r['scope']}, music playing {int(r['playing_share'] * 100)}% of samples)", "",
             "## The two paths from this host (same frames, same clock)", "",
             "| path | msgs | fps | delay p50 | p95 | p99 | max | interval p95 | max | gaps>100ms "
             "| server age p95 | srtt p50 | rate share | rate changes | seq gaps | kbit/s |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key in v:
        s = v[key]
        d, i, a = s["delay_ms"], s["interval_ms"], s["server_age_ms"]
        lines.append(f"| {s['name']} | {s['messages']} | {_f(s['delivered_fps'], 2)} | {_f(d['p50'])} | "
                     f"{_f(d['p95'])} | {_f(d['p99'])} | {_f(d['max'])} | {_f(i['p95'])} | {_f(i['max'])} | "
                     f"{i['gaps_over_100ms']} | {_f(a['p95'])} | {_f(s['srtt_ms']['p50'])} | "
                     f"{s['rate_fps_share']} | {s['rate_changes']} | {s['seq_gaps']} | {_f(s['kbit_s'])} |")
    h = r["proxy_hop_ms"]
    lines += ["", f"Proxy hop cost (proxied minus direct delay): p50 {_f(h['p50'])} ms, "
              f"p95 {_f(h['p95'])} ms, p99 {_f(h['p99'])} ms.", "",
              "## His Tailscale socket(s), from the kernel", "",
              "| socket | samples | rtt p50 | p95 | max | min rtt | retrans Δ | bytes retrans Δ | "
              "bytes sent Δ | Send-Q max | Send-Q p95 | notsent max | unacked max |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, s in r["his_sockets"].items():
        t = s["rtt_ms"]
        lines.append(f"| {key} | {s['samples']} | {_f(t['p50'])} | {_f(t['p95'])} | {_f(t['max'])} | "
                     f"{_f(s['minrtt_ms'], 3)} | {s['retrans_total_delta']} | {s['bytes_retrans_delta']} | "
                     f"{s['bytes_sent_delta']} | {s['send_q_max']} | {_f(s['send_q_p95'])} | "
                     f"{s['notsent_max']} | {s['unacked_max']} |")
    if not r["his_sockets"]:
        lines.append("(no Tailscale socket was established on :8000/:8010 during the run)")
    lines += ["", "## Liveness GET latency (event-loop stalls)", "",
              "| port | samples | p50 | p95 | max | errors |", "|---|---|---|---|---|---|"]
    for port, s in r["liveness_ms"].items():
        lines.append(f"| :{port} | {s['samples']} | {_f(s['p50'])} | {_f(s['p95'])} | {_f(s['max'])} | {s['errors']} |")
    return "\n".join(lines) + "\n"


# ── main ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--duration", type=float, default=600.0)
    ap.add_argument("--wait", action="store_true", help="poll until a show with a remote viewer")
    ap.add_argument("--poll", type=float, default=60.0)
    ap.add_argument("--wait-until", default=None,
                    help="ISO local time after which --wait gives up (exit 3)")
    ap.add_argument("--level", default="full", choices=("summary", "full"))
    ap.add_argument("--scope", default="favorites", choices=("favorites", "in_use"))
    ap.add_argument("--ss-period", type=float, default=5.0)
    ap.add_argument("--http-period", type=float, default=2.0)
    ap.add_argument("--require-viewer", action="store_true", default=True)
    ap.add_argument("--no-require-viewer", dest="require_viewer", action="store_false")
    ap.add_argument("--extra-url", action="append", default=[], metavar="NAME=URL",
                    help="one more viewer against this WebSocket URL (repeatable)")
    ap.add_argument("--loopback-peers", action="store_true",
                    help="his browser arrives via tailscale serve: watch 127.0.0.1 peers on :8000")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    global LOOPBACK_PEERS
    LOOPBACK_PEERS = a.loopback_peers
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    give_up = datetime.fromisoformat(a.wait_until).timestamp() if a.wait_until else None
    if a.wait:
        while True:
            r = readiness()
            ready = bool(r["is_playing"]) and (r["viewer_connected"] or not a.require_viewer)
            logger.info("readiness: playing=%s viewer=%s sockets=%s dark=%s%s",
                        r["is_playing"], r["viewer_connected"], r["tailscale_sockets"],
                        r.get("dark"), f" error={r['error']}" if "error" in r else "")
            with (out_dir / "readiness.log").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(r) + "\n")
            if ready:
                break
            if give_up is not None and time.time() > give_up:
                logger.info("gave up waiting at %s", a.wait_until)
                return 3
            time.sleep(a.poll)
    logger.info("measuring for %.0f s", a.duration)
    extras = [tuple(x.split("=", 1)) for x in a.extra_url if "=" in x]
    result = asyncio.run(measure(out_dir, a.duration, a.level, a.scope, a.ss_period,
                                 a.http_period, extra_urls=extras))
    print(render_md(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
