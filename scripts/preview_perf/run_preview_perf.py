"""Preview performance test: Spectra's browser preview vs LedFX's, same shapes,
same emulated link, same browser, same probe.

For each (system, link profile) it opens the system's real preview page in
headless Chromium THROUGH the link emulator and measures, in the browser:

  delivered fps      WebSocket frames/s for the motion virtual (crystal-mapper)
  painted fps        ledfx: canvas putImageData calls/s for the 72-wide
                      canvas; every "spectra*" system: the same drawn-frame
                      count "drawn fps" uses, since the expanded strip and
                      the Live view share one WebGL/2D-fallback renderer
                      (live/useLiveStageCanvas.ts) and neither ever calls
                      putImageData for its own pixels
  jitter             inter-frame interval: mean / stdev / p95 / p99 / max, stalls
  input-to-photon    API call (through the link) -> changed frame presented
  bandwidth          bytes/s through the link, both directions
  browser CPU        main-thread task time / wall time (CDP Performance.getMetrics)
  server CPU         process CPU with a viewer minus without one

Systems (parts combine: spectra-legacy@30+proxy:collapsed):
  spectra        the shipped preview: the protocol-2 stream
                 (spectra/services/preview_stream.py), strip expanded
  +proxy         behind the real :8000 reverse-proxy class
                 (services/spectra_proxy.py) -- the address he actually uses
  :collapsed     the strip collapsed (one averaged colour per device)
  -legacy        the old JSON format (the page skips the protocol-2 hello)
  -legacy@N      the old format with only its relay fps raised (what-if)
  :live          the Live view (Devices > Live) instead of the top strip, on
                 his room's real topology; adds "drawn fps" — animation
                 frames in which the page actually drew
  :map           the Live view's Room map instead of its Layout (with :live):
                 the rig's synthetic camera pose, every strip block mapped
  :phone         a phone: 390x844 at 3x, CPU slowed by --phone-cpu (4x)
  :canvas        the Live view's 2D-canvas fallback instead of WebGL
  ledfx          the real LedFX fork + its real frontend, his config
                 (visualisation_fps 30, visualisation_maxlen 4096, compressed)

Everything runs on dummy devices on spare ports. It never touches the room.

  .venv/bin/python scripts/preview_perf/run_preview_perf.py --out /tmp/out [--quick]

The gate applies to the FIRST system listed (and to its ":collapsed" row when
one is listed); exit code 1 on a failure. --gate is the rebuild's acceptance
gate (data/preview-perf-plan/report.md section 7), plus "match or beat LedFX
as measured in this same run" when ledfx is among the systems (--vs); every
threshold also has its own flag, and the interval and latency ones take
per-link values:

  ... --systems spectra+proxy,spectra+proxy:collapsed,ledfx --gate
  ... --pass-fps 25 --pass-p95-ms lan=50,ts-direct=56,ts-relay=69 --pass-latency-ms 250
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import linkemu  # noqa: E402
import rig_common  # noqa: E402

CHROME = os.environ.get("PREVIEW_PERF_CHROME") or os.path.expanduser(
    "~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome")
LEDFX_BIN = os.environ.get("PREVIEW_PERF_LEDFX", "/home/javi/ledfx/bin/ledfx")
LEDFX_PY = os.path.join(os.path.dirname(LEDFX_BIN), "python")

SPECTRA_PORT, LEDFX_PORT, PROXY_PORT, LINK_PORT, CDP_PORT = 9110, 9120, 9130, 9201, 9333

# name: (rtt_ms, jitter_ms, down_kbps, up_kbps)   0 kbps = uncapped
PROFILES = {
    "lan":          (0, 0, 0, 0),
    "ts-direct":    (30, 5, 20000, 10000),   # Tailscale, direct path
    "ts-relay":     (80, 15, 4000, 2000),    # Tailscale via DERP: 71-88 ms measured 2026-10-05
    "poor":         (150, 40, 1000, 500),    # hotel / mobile data
}


def http(method: str, url: str, body: dict | None = None, timeout: float = 10.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        return json.loads(raw)
    except Exception:
        return raw


def wait_http(url: str, seconds: float = 40.0) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            http("GET", url, timeout=2)
            return
        except Exception:
            time.sleep(0.4)
    raise RuntimeError(f"not up: {url}")


class Proc:
    def __init__(self, argv, **kw):
        self.p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=kw.pop("stderr", subprocess.DEVNULL),
                                  start_new_session=True, **kw)
        self.pid = self.p.pid

    def stop(self):
        try:
            os.killpg(self.pid, signal.SIGTERM)
            self.p.wait(timeout=8)
        except Exception:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except Exception:
                pass


def start_spectra(harness: str, relay_fps: float | None, log_dir: str,
                  room: bool = False) -> Proc:
    argv = [sys.executable, os.path.join(HERE, "spectra_rig.py"), "--port", str(SPECTRA_PORT),
            "--harness", harness]
    if room:
        argv.append("--room")
    if relay_fps:
        argv += ["--relay-fps", str(relay_fps)]
    p = Proc(argv, cwd=REPO, stderr=open(os.path.join(log_dir, "spectra_rig.log"), "w"))
    wait_http(f"http://127.0.0.1:{SPECTRA_PORT}/spectra/rig/info")
    return p


def start_ledfx(log_dir: str) -> Proc:
    cfg = tempfile.mkdtemp(prefix="preview-perf-ledfx-")
    version = subprocess.check_output(
        [LEDFX_PY, "-c", "import ledfx.consts as c; print(c.CONFIGURATION_VERSION)"]).decode().strip()
    rig_common.write_config(cfg, version, {
        "host": "127.0.0.1", "port": LEDFX_PORT,
        # his real values (~/.ledfx/config.json and fx-live/config.json, read 2026-10-05)
        "visualisation_fps": 30, "visualisation_maxlen": 4096, "transmission_mode": "compressed",
        "scan_on_startup": False,
    })
    p = Proc([LEDFX_BIN, "-c", cfg, "-p", str(LEDFX_PORT), "--host", "127.0.0.1",
              "--offline", "--no-tray"], cwd=cfg,
             stderr=open(os.path.join(log_dir, "ledfx.log"), "w"))
    wait_http(f"http://127.0.0.1:{LEDFX_PORT}/api/info")
    return p


class Cdp:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0

    async def call(self, method: str, params: dict | None = None):
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def eval(self, expr: str):
        r = await self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                  "awaitPromise": True})
        return r.get("result", {}).get("value")


_ledfx_warmed = False


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


async def measure(system: str, profile: str, seconds: float, flashes: int,
                  server_pid: int, idle_cpu: float, shots: str | None,
                  phone_cpu: float = 4.0) -> dict:
    import websockets

    rtt, jit, down, up = PROFILES[profile]
    target = LEDFX_PORT if system == "ledfx" else (PROXY_PORT if "+proxy" in system else SPECTRA_PORT)
    collapsed = ":collapsed" in system
    live_view, phone = ":live" in system, ":phone" in system
    counter = linkemu.Counter()
    server, _ = await linkemu.serve(LINK_PORT, target, rtt, jit, down, up, counter)
    base = f"http://127.0.0.1:{LINK_PORT}"
    if system == "ledfx":
        url = f"{base}/#/Devices"
        preload = f"localStorage.setItem('ledfx-host', '{base}');"
    else:
        url = f"{base}/spectra/" + ("live.html" if live_view else "")
        preload = ("localStorage.setItem('spectra-device-preview-expanded', '%s');"
                   % ("0" if collapsed else "1"))
        if ":canvas" in system:
            preload += "localStorage.setItem('spectra-live-force-canvas', '1');"
        if live_view:
            preload += ("localStorage.setItem('spectra-live-view', '%s');"
                        % ("room" if ":map" in system else "layout"))
        if "legacy" in system:
            preload += "localStorage.setItem('spectra-device-preview-legacy', '1');"
    probe = (open(os.path.join(HERE, "probe.js")).read()
             .replace("__LAT_ID__", rig_common.LATENCY_ID).replace("__PRELOAD__", preload))

    global _ledfx_warmed
    if system == "ledfx" and not _ledfx_warmed:
        # LedFX's frontend only subscribes to pixel frames from its SECOND load on a
        # fresh browser origin (the first load just stores its first-run state): load
        # it once through the link origin and throw that tab away.
        warm = http("PUT", f"http://127.0.0.1:{CDP_PORT}/json/new?{base}/")
        await asyncio.sleep(8)
        http("GET", f"http://127.0.0.1:{CDP_PORT}/json/close/{warm['id']}")
        await asyncio.sleep(1)
        _ledfx_warmed = True
    tab = http("PUT", f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank")
    result: dict = {"system": system, "profile": profile,
                    "link": {"rtt_ms": rtt, "jitter_ms": jit, "down_kbps": down, "up_kbps": up}}
    try:
        async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=None) as sock:
            cdp = Cdp(sock)
            for m in ("Page.enable", "Runtime.enable", "Performance.enable"):
                await cdp.call(m)
            await cdp.call("Emulation.setDeviceMetricsOverride",
                           {"width": 390, "height": 844, "deviceScaleFactor": 3, "mobile": True}
                           if phone else
                           {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})
            if phone and phone_cpu > 1:
                await cdp.call("Emulation.setCPUThrottlingRate", {"rate": phone_cpu})
            await cdp.call("Network.enable")
            await cdp.call("Network.setCacheDisabled", {"cacheDisabled": True})
            await cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": probe})
            await cdp.call("Page.navigate", {"url": url})

            # wait until motion frames are flowing, then start the clean window
            end = time.time() + 45
            while time.time() < end:
                await asyncio.sleep(0.5)
                # a collapsed strip gets a device's colour only when it changes
                want = "true" if collapsed else f"m[2]==='{rig_common.MOTION_ID}'"
                n = await cdp.eval(
                    f"(window.__probe?window.__probe.ws.filter(m=>{want}).length:0)")
                if n and n >= 5:
                    break
            else:
                result["error"] = "no frames arrived"
                return result
            await asyncio.sleep(2.0)

            def metrics(ms):
                return {m["name"]: m["value"] for m in ms["metrics"]}

            await cdp.eval("(()=>{const p=window.__probe;p.ws.length=0;p.paints.length=0;"
                           "p.lat.length=0;p.rafLong.length=0;p.rafCount=0;p.drawnFrames=0;p.drawCalls=0;"
                           "p.start=performance.now();})()")
            m0 = metrics(await cdp.call("Performance.getMetrics"))
            cpu0, wall0 = rig_common.cpu_seconds(server_pid), time.time()
            down0, up0 = counter.down, counter.up

            await asyncio.sleep(seconds)

            m1 = metrics(await cdp.call("Performance.getMetrics"))
            cpu1, wall1 = rig_common.cpu_seconds(server_pid), time.time()
            down1, up1 = counter.down, counter.up
            dump = await cdp.eval("JSON.stringify({ws:window.__probe.ws,paints:window.__probe.paints,"
                                  "rafCount:window.__probe.rafCount,rafLong:window.__probe.rafLong,"
                                  "drawnFrames:window.__probe.drawnFrames,drawCalls:window.__probe.drawCalls,"
                                  "elapsed:performance.now()-window.__probe.start,sockets:window.__probe.sockets})")
            d = json.loads(dump)
            result["webgl_renderer"] = await cdp.eval(
                "(()=>{const g=document.createElement('canvas').getContext('webgl2');"
                "if(!g)return 'none';const e=g.getExtension('WEBGL_debug_renderer_info');"
                "return e?g.getParameter(e.UNMASKED_RENDERER_WEBGL):'unknown'})()")
            if system != "ledfx":
                try:   # the stream's own view of this viewer (rate, window, held ticks)
                    result["stream"] = http(
                        "GET", f"http://127.0.0.1:{SPECTRA_PORT}/spectra/rig/info").get("stream")
                except Exception:
                    pass

            # input-to-photon: flash the latency virtual through the SAME link
            lat = []
            for i in range(flashes):
                on = 1 if i % 2 == 0 else 0
                before = await cdp.eval("window.__probe.lat.length")
                t0 = time.time() * 1000.0
                if system == "ledfx":
                    body = {"type": "singleColor",
                            "config": {"color": "#ffffff" if on else "#000000",
                                       "speed": rig_common.LATENCY_SPEED}}
                    await asyncio.to_thread(
                        http, "PUT", f"{base}/api/virtuals/{rig_common.LATENCY_ID}/effects", body)
                else:
                    await asyncio.to_thread(http, "POST", f"{base}/spectra/rig/flash?on={on}")
                stop = time.time() + 5
                while time.time() < stop:
                    await asyncio.sleep(0.03)
                    rows = await cdp.eval("JSON.stringify(window.__probe.lat)")
                    rows = json.loads(rows)
                    if len(rows) > before:
                        arr, shown, _lum = rows[-1]
                        lat.append({"arrive_ms": arr - t0, "photon_ms": shown - t0})
                        break
                # A random gap: a fixed one starts every flash at the same
                # point of the sender's own frame clock (33 ms here, 48 ms
                # for LedFX), which biases each system by a different amount.
                await asyncio.sleep(0.3 + random.random() * 0.15)

            if shots:
                shot = await cdp.call("Page.captureScreenshot", {"format": "png"})
                import base64
                with open(os.path.join(shots, f"{system.replace('@', '-').replace('+', '-').replace(':', '-')}-{profile}.png"), "wb") as f:
                    f.write(base64.b64decode(shot["data"]))
    finally:
        try:
            http("GET", f"http://127.0.0.1:{CDP_PORT}/json/close/{tab['id']}")
        except Exception:
            pass
        server.close()
        counter.close_all()

    el = d["elapsed"] / 1000.0
    motion = [m[0] for m in d["ws"] if m[2] == rig_common.MOTION_ID]
    gaps = [b - a for a, b in zip(motion, motion[1:])]
    paints = [p for p in d["paints"] if p[1] == 72]
    nominal = statistics.median(gaps) if gaps else 0
    wall = wall1 - wall0
    result.update({
        "window_s": round(el, 2),
        "delivered_fps": round(len(motion) / el, 2),
        # ledfx's own frontend still paints its 72-wide canvas with
        # putImageData; every "spectra*" system draws the expanded strip
        # (and the Live view) with the shared LiveStage renderer instead
        # (live/useLiveStageCanvas.ts -- a WebGL draw, or the 2D fallback's
        # full-canvas clear), so for those systems this reports the SAME
        # drawn-frame count "drawn_fps" below does, never 0.
        "painted_fps": round((len(paints) if system == "ledfx" else d["drawnFrames"]) / el, 2),
        "all_ws_msgs_per_s": round(len(d["ws"]) / el, 1),
        "interval_ms": {
            "mean": round(statistics.mean(gaps), 1) if gaps else None,
            "stdev": round(statistics.pstdev(gaps), 1) if gaps else None,
            "p95": round(pct(gaps, 0.95), 1) if gaps else None,
            "p99": round(pct(gaps, 0.99), 1) if gaps else None,
            "max": round(max(gaps), 1) if gaps else None,
        },
        "stalls_over_2x": sum(1 for g in gaps if nominal and g > 2 * nominal),
        "gaps_over_100ms": sum(1 for g in gaps if g > 100),
        "motion_frame_bytes": round(statistics.mean(
            [m[1] for m in d["ws"] if m[2] == rig_common.MOTION_ID]), 0) if motion else None,
        "down_kbps": round((down1 - down0) * 8 / wall / 1000.0, 1),
        "up_kbps": round((up1 - up0) * 8 / wall / 1000.0, 2),
        "paint_cost_ms_mean": round(statistics.mean([p[3] for p in paints]), 3) if paints else None,
        "browser_main_thread_pct": round(100 * (m1["TaskDuration"] - m0["TaskDuration"]) / wall, 1),
        "browser_script_pct": round(100 * (m1["ScriptDuration"] - m0["ScriptDuration"]) / wall, 1),
        "raf_fps": round(d["rafCount"] / el, 1),
        "drawn_fps": round(d["drawnFrames"] / el, 1),
        "draw_calls_per_frame": round(d["drawCalls"] / max(1, d["drawnFrames"]), 2),
        "raf_longest_ms": round(max((x[1] for x in d["rafLong"]), default=0), 1),
        "raf_long_frames": len(d["rafLong"]),
        "server_cpu_pct": round(100 * (cpu1 - cpu0) / wall, 1),
        "server_cpu_idle_pct": round(idle_cpu, 1),
        "server_preview_cpu_pct": round(100 * (cpu1 - cpu0) / wall - idle_cpu, 1),
        "latency_ms": {
            "n": len(lat),
            "photon_median": round(statistics.median([x["photon_ms"] for x in lat]), 0) if lat else None,
            "photon_max": round(max([x["photon_ms"] for x in lat]), 0) if lat else None,
            "arrive_median": round(statistics.median([x["arrive_ms"] for x in lat]), 0) if lat else None,
        },
        "sockets": d["sockets"],
    })
    return result


def idle_cpu(pid: int, seconds: float = 8.0) -> float:
    c0, t0 = rig_common.cpu_seconds(pid), time.time()
    time.sleep(seconds)
    return 100 * (rig_common.cpu_seconds(pid) - c0) / (time.time() - t0)


def table(rows: list[dict]) -> str:
    head = ("| system | link | delivered fps | painted fps | interval p95 / max (ms) | gaps >100ms | "
            "input→photon median / max (ms) | frame bytes | wire kbps down | browser main thread | server CPU for preview | "
            "drawn fps | long frames (>34 ms) |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    out = []
    for r in rows:
        if "error" in r:
            out.append(f"| {r['system']} | {r['profile']} | ERROR: {r['error']} |||||||||")
            continue
        iv, la = r["interval_ms"], r["latency_ms"]
        out.append(f"| {r['system']} | {r['profile']} | {r['delivered_fps']} | {r['painted_fps']} | "
                   f"{iv['p95']} / {iv['max']} | {r['gaps_over_100ms']} | "
                   f"{la['photon_median']} / {la['photon_max']} | {r['motion_frame_bytes']} | {r['down_kbps']} | "
                   f"{r['browser_main_thread_pct']}% | {r['server_preview_cpu_pct']}% | "
                   f"{r['drawn_fps']} | {r['raf_long_frames']} |")
    return head + "\n".join(out) + "\n"


async def main_async(args) -> int:
    os.makedirs(args.out, exist_ok=True)
    shots = os.path.join(args.out, "shots")
    os.makedirs(shots, exist_ok=True)
    harness = args.harness or os.path.join(REPO, "spectra", "web", "harness-dist")
    if not os.path.isdir(harness):
        print(f"harness build missing: {harness} (see README)", file=sys.stderr)
        return 2
    profiles = args.profiles.split(",")
    systems = args.systems.split(",")
    profile_dir = tempfile.mkdtemp(prefix="preview-perf-chrome-")
    # The Live view draws with WebGL. With no GPU Chromium runs it in
    # software (SwiftShader), which measures this machine's CPU, not the
    # view: use the real GPU for those rows unless told otherwise. Every row
    # records the renderer it actually got.
    gpu = args.gpu == "on" or (args.gpu == "auto" and any(":live" in s for s in systems))
    gpu_flags = ["--ignore-gpu-blocklist", "--use-angle=gl-egl"] if gpu else ["--disable-gpu"]
    chrome = Proc([CHROME, "--headless=new", "--no-sandbox", *gpu_flags,
                   f"--remote-debugging-port={CDP_PORT}", "--no-first-run",
                   "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                   "--disable-backgrounding-occluded-windows",
                   f"--user-data-dir={profile_dir}", "about:blank"])
    wait_http(f"http://127.0.0.1:{CDP_PORT}/json/version")
    rows: list[dict] = []
    try:
        for system in systems:
            proxy = None
            if system == "ledfx":
                srv = start_ledfx(args.out)
            else:
                fps = (float(system.split("@")[1].split("+")[0].split(":")[0])
                       if "@" in system else None)
                srv = start_spectra(harness, fps, args.out, room=":live" in system)
                if "+proxy" in system:
                    proxy = Proc([sys.executable, os.path.join(HERE, "proxy_rig.py"),
                                  "--port", str(PROXY_PORT), "--target", str(SPECTRA_PORT)], cwd=REPO)
                    wait_http(f"http://127.0.0.1:{PROXY_PORT}/rig/up")
            try:
                time.sleep(3)
                idle = idle_cpu(srv.pid)
                for profile in profiles:
                    print(f"… {system} over {profile}", flush=True)
                    try:
                        r = await asyncio.wait_for(
                            measure(system, profile, args.seconds, args.flashes, srv.pid, idle, shots,
                                    phone_cpu=args.phone_cpu),
                            timeout=args.seconds + 150)
                    except Exception as exc:   # a hung page must not hang the whole gate
                        r = {"system": system, "profile": profile,
                             "error": f"{type(exc).__name__}: {exc}"[:120]}
                    rows.append(r)
                    print(json.dumps({k: r.get(k) for k in (
                        "delivered_fps", "painted_fps", "drawn_fps", "raf_long_frames", "interval_ms", "latency_ms", "down_kbps",
                        "browser_main_thread_pct", "server_preview_cpu_pct", "error")}), flush=True)
            finally:
                srv.stop()
                if proxy is not None:
                    proxy.stop()
    finally:
        chrome.stop()
        shutil.rmtree(profile_dir, ignore_errors=True)

    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "seconds": args.seconds,
                   "profiles": PROFILES, "rows": rows}, f, indent=1)
    md = table(rows)
    with open(os.path.join(args.out, "results.md"), "w") as f:
        f.write(md)
    print("\n" + md)

    failed = gate(rows, systems, args)
    if failed is not None:
        print("GATE:", "FAIL — " + "; ".join(failed) if failed else "PASS")
    return 1 if failed else 0


def per_profile(value: str | None) -> dict:
    """"60" -> the same limit on every link; "lan=50,ts-relay=69" -> per link
    (a link not named has no limit)."""
    if not value:
        return {}
    if "=" not in value:
        return {"*": float(value)}
    return {k.strip(): float(v) for k, v in (part.split("=") for part in value.split(","))}


# The preview rebuild's acceptance gate (data/preview-perf-plan/report.md
# section 7): LedFX's own baseline numbers on each link are the bar.
SECTION_7 = {
    "pass_fps": 28.0, "pass_max_gap_ms": 100.0, "pass_main_thread_pct": 20.0,
    "pass_p95_ms": "lan=50,ts-direct=56,ts-relay=69",
    "pass_latency_ms": "lan=95,ts-direct=141,ts-relay=216",
    "poor_fps": 15.0, "poor_latency_ms": 450.0, "poor_latency_max_ms": 1000.0,
    "collapsed_kbps": 20.0,
}


def gate(rows: list[dict], systems: list[str], args) -> list[str] | None:
    """None when no threshold was asked for; else the list of failures."""
    if args.gate:
        for key, value in SECTION_7.items():
            if not getattr(args, key):
                setattr(args, key, value)
    p95, latency = per_profile(args.pass_p95_ms), per_profile(args.pass_latency_ms)
    if args.gate and not args.vs and any(r["system"] == "ledfx" for r in rows):
        args.vs = "ledfx"
    asked = any((args.pass_fps, p95, latency, args.pass_max_gap_ms, args.pass_main_thread_pct,
                 args.poor_fps, args.poor_latency_ms, args.poor_latency_max_ms,
                 args.collapsed_kbps, args.vs, args.pass_drawn_fps))
    reference = {r["profile"]: r for r in rows
                 if args.vs and r["system"] == args.vs and "error" not in r}
    if not asked:
        return None
    subject = systems[0]
    failed: list[str] = []

    def over(label, value, limit, unit=""):
        if limit and (value is None or value > limit):
            failed.append(f"{label} {value}{unit} > {limit}{unit}")

    def under(label, value, limit, unit=""):
        if limit and (value is None or value < limit):
            failed.append(f"{label} {value}{unit} < {limit}{unit}")

    for r in rows:
        name = f"{r['system']} {r['profile']}:"
        if ":live" in r["system"] and args.pass_drawn_fps:
            # Every Live view row, whichever system is first: the display's
            # own rate, drawn, on every link.
            if "error" in r:
                failed.append(f"{name} {r['error']}")
            else:
                under(f"{name} drawn", r["drawn_fps"],
                      args.poor_drawn_fps if r["profile"] == "poor" else args.pass_drawn_fps,
                      " fps")
            if r["system"] != subject:
                continue
        if r["system"] == subject + ":collapsed":
            if "error" in r:
                failed.append(f"{name} {r['error']}")
            else:
                over(f"{name} wire", r["down_kbps"], args.collapsed_kbps, " kbit/s")
            continue
        if r["system"] != subject:
            continue
        if "error" in r:
            failed.append(f"{name} {r['error']}")
            continue
        iv, la, link = r["interval_ms"], r["latency_ms"], r["profile"]
        if link == "poor":
            under(f"{name} delivered", r["delivered_fps"], args.poor_fps, " fps")
            over(f"{name} latency median", la["photon_median"], args.poor_latency_ms, " ms")
            over(f"{name} latency worst", la["photon_max"], args.poor_latency_max_ms, " ms")
            continue
        under(f"{name} delivered", r["delivered_fps"], args.pass_fps, " fps")
        over(f"{name} interval p95", iv["p95"], p95.get(link, p95.get("*")), " ms")
        over(f"{name} interval max", iv["max"], args.pass_max_gap_ms, " ms")
        over(f"{name} latency median", la["photon_median"],
             latency.get(link, latency.get("*")), " ms")
        over(f"{name} browser main thread", r["browser_main_thread_pct"],
             args.pass_main_thread_pct, "%")
        ref = reference.get(link)
        if args.vs and ref is None:
            failed.append(f"{name} no {args.vs} row on this link to compare against")
        elif ref is not None:
            # Measured in THIS run, on the same link: the fixed limits above
            # are LedFX's numbers from the day the plan was written.
            under(f"{name} delivered vs {args.vs}", r["delivered_fps"], ref["delivered_fps"], " fps")
            over(f"{name} interval p95 vs {args.vs}", iv["p95"],
                 ref["interval_ms"]["p95"] + args.vs_slack_ms, " ms")
            over(f"{name} latency median vs {args.vs}", la["photon_median"],
                 ref["latency_ms"]["photon_median"] + args.vs_slack_ms, " ms")
    return failed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--harness", default=None)
    ap.add_argument("--systems", default="spectra+proxy,spectra+proxy:collapsed,ledfx")
    ap.add_argument("--profiles", default="lan,ts-direct,ts-relay,poor")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--flashes", type=int, default=8)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--gate", action="store_true",
                    help="the rebuild's acceptance gate (report section 7)")
    ap.add_argument("--pass-fps", type=float, default=0)
    ap.add_argument("--pass-p95-ms", default="",
                    help="one limit, or per link: lan=50,ts-direct=56,ts-relay=69")
    ap.add_argument("--pass-latency-ms", default="",
                    help="input-to-photon median; one limit, or per link")
    ap.add_argument("--pass-max-gap-ms", type=float, default=0,
                    help="no inter-frame gap over this (not applied to poor)")
    ap.add_argument("--pass-main-thread-pct", type=float, default=0)
    ap.add_argument("--poor-fps", type=float, default=0)
    ap.add_argument("--poor-latency-ms", type=float, default=0)
    ap.add_argument("--poor-latency-max-ms", type=float, default=0)
    ap.add_argument("--vs", default="",
                    help="also require the first system to match or beat this system's "
                         "rows from the same run (--gate uses ledfx when it was run)")
    ap.add_argument("--vs-slack-ms", type=float, default=3.0,
                    help="measurement noise allowed in the --vs comparison")
    ap.add_argument("--pass-drawn-fps", type=float, default=0,
                    help="every ':live' row must DRAW at least this many frames a "
                         "second (the Live view's gate: 59, the display's 60 less "
                         "measurement rounding)")
    ap.add_argument("--gpu", choices=("auto", "on", "off"), default="auto",
                    help="auto: the machine's GPU when a ':live' system is listed, "
                         "software rendering otherwise (as the stream gate was measured)")
    ap.add_argument("--poor-drawn-fps", type=float, default=0,
                    help="the drawn-fps limit on the 'poor' link, where frames can "
                         "arrive further apart than any ease should bridge (0 = none)")
    ap.add_argument("--phone-cpu", type=float, default=4.0,
                    help="CPU slowdown for ':phone' rows (Chromium's own throttle)")
    ap.add_argument("--collapsed-kbps", type=float, default=0,
                    help="wire limit for the first system's ':collapsed' row")
    a = ap.parse_args()
    if a.quick:
        a.seconds, a.flashes, a.profiles = 8.0, 4, "lan,ts-relay"
    sys.exit(asyncio.run(main_async(a)))
