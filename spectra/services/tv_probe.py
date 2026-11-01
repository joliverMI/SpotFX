"""THE TV PROBE — phase 0 of the TV display plan (data/tv-display-plan/
plan.html PR 0.1, report.md §1/§4). Before anything beat-synced is built for
a TV, this page answers what the plan calls "unproven" about it: the real
browser engine, WebGL 1/2 and GPU, how many frames a second it can actually
draw at a few workloads, how long a round trip to Serenity takes, and
whether/when the screensaver takes the page away. It touches no light and
drives no fixture — it is a diagnostic, nothing else.

SELF-CONTAINED, deliberately, the same reason `spec_viewer.py` renders a
plain string rather than shipping a build: a Vite bundle needs the TV app
shell this probe runs BEFORE (phase 1, PR 1.1 is the first thing that gets
one), and the page has to run unmodified on whatever webOS Chromium build
the LG actually has (reported anywhere from Chromium 108 up) with nothing
to compile or deploy first. One `<style>`, one `<script>`, no external
fetches except back to this same server — exactly the convention the
scout's own plan page documents for itself.

THE RESULT IS NEVER A VERDICT, only a MEASUREMENT. This module stores
numbers and strings the browser reported about itself; it does not decide
"the LG passes" or "buy a box" — that reading is the Admiral's, from the
test evening (plan row 0.3), looking at what came back.

ONE RECORD PER SCREEN, LAST-SEEN KEPT. A probe run mints a `probe_id`
(the client's own random id, stable for one page life) and every POST for
that id MERGES into the same stored record rather than creating a new row
per update — the ladder's one-time result and the screensaver log's
periodic growth are two writers to the same entry. Bounded
(`MAX_RESULTS`): a diagnostic page opened a dozen times while tuning this
build must not grow the store without limit; the oldest `updated_ms` is
evicted first.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any

from spectra import config as scfg

logger = logging.getLogger(__name__)

#: How many distinct probe runs are remembered. Small — this is "what did
#: the last few evenings at the TV look like", not an unbounded log.
MAX_RESULTS = 8


def _path(path=None):
    return path or scfg.TV_PROBE_FILE


def load(path=None) -> dict[str, dict]:
    p = _path(path)
    try:
        if not os.path.exists(p):
            return {}
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return dict(data.get("results") or {})
    except Exception:                                  # noqa: BLE001
        logger.exception("tv probe: unreadable store %s", p)
        return {}


def _save(results: dict[str, dict], path=None) -> None:
    p = _path(path)
    os.makedirs(os.path.dirname(str(p)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(p)) or ".",
                               prefix="tv-probe", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"results": results}, fh, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_result(probe_id: str, patch: dict[str, Any], path=None) -> dict:
    """Merge `patch` into the stored record for `probe_id` (new fields
    overwrite old ones of the same name; a field the patch omits — e.g. a
    screensaver-log-only update that doesn't repeat the fps ladder —
    survives from the prior write), stamp `updated_ms`, evict the
    least-recently-updated record past `MAX_RESULTS`, and return the
    merged record."""
    probe_id = str(probe_id or "").strip()
    if not probe_id:
        raise ValueError("probe_id is required")
    results = load(path)
    row = dict(results.get(probe_id) or {})
    row.update({k: v for k, v in (patch or {}).items() if k != "probe_id"})
    row["probe_id"] = probe_id
    row["updated_ms"] = int(time.time() * 1000)
    row.setdefault("first_seen_ms", row["updated_ms"])
    results[probe_id] = row
    if len(results) > MAX_RESULTS:
        oldest = sorted(results.items(), key=lambda kv: kv[1].get("updated_ms", 0))
        for pid, _ in oldest[: len(results) - MAX_RESULTS]:
            results.pop(pid, None)
    _save(results, path)
    return row


def list_results(path=None) -> list[dict]:
    """Newest-updated first — what the probe page's own "stored runs"
    table reads, and what a human checking `/api/tv/probe/results` sees."""
    results = load(path)
    return sorted(results.values(), key=lambda r: r.get("updated_ms", 0), reverse=True)


# ── the page itself ─────────────────────────────────────────────────────────

_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SPECTRA TV probe</title>
<style>
:root { --bg: #06040b; --surface: #140d1f; --surface2: #1f1430; --border: #372552;
        --accent: #a855f7; --text: #ece7f7; --muted: #9585b5; --ok: #4ade80; --no: #f87171; }
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--text);
             font: 16px/1.5 system-ui, sans-serif; overflow-x: hidden; }
header { padding: 18px 20px 6px; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
p.sub { color: var(--muted); margin: 0; font-size: 14px; }
main { padding: 0 20px 28px; max-width: 900px; }
section { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
          padding: 12px 16px; margin: 14px 0; }
h2 { font-size: 15px; margin: 0 0 8px; color: var(--accent); text-transform: uppercase;
     letter-spacing: 0.06em; }
dl.kv { display: grid; grid-template-columns: max-content 1fr; gap: 3px 14px;
        font-size: 14px; margin: 0; }
dl.kv dt { color: var(--muted); }
dl.kv dd { margin: 0; font-variant-numeric: tabular-nums; word-break: break-all; }
#canvasHost { position: relative; width: 320px; height: 180px; background: #000;
              border-radius: 6px; overflow: hidden; }
#canvasHost canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
#status { font-size: 15px; margin: 6px 0 0; }
#status.ok { color: var(--ok); }
#status.err { color: var(--no); }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 600; }
.idle-note { color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<header>
  <h1>SPECTRA TV probe</h1>
  <p class="sub">Measures this browser — nothing here drives a light. Runs a short fps ladder, times a few round trips to Serenity, then watches for the screensaver. Leave this open and the remote alone for the test evening (data/tv-display-plan/report.md §1).</p>
</header>
<main>
  <section>
    <h2>Browser</h2>
    <dl class="kv" id="browserInfo"><dt>reading…</dt><dd></dd></dl>
  </section>
  <section>
    <h2>Drawn-fps ladder</h2>
    <div id="canvasHost"></div>
    <dl class="kv" id="fpsInfo" style="margin-top:10px"><dt>not started</dt><dd></dd></dl>
  </section>
  <section>
    <h2>Ping round-trips to Serenity</h2>
    <dl class="kv" id="pingInfo"><dt>not started</dt><dd></dd></dl>
  </section>
  <section>
    <h2>Screensaver log</h2>
    <p class="idle-note" id="screensaverNote">Watching document.visibilitychange. A blank/hidden page here means something (the TV's own screensaver, or the app being backgrounded) took the page away.</p>
    <table id="screensaverTable"><thead><tr><th>t (s since load)</th><th>state</th></tr></thead><tbody></tbody></table>
  </section>
  <section>
    <p id="status">Starting…</p>
  </section>
  <section>
    <h2>Stored runs on this server</h2>
    <table id="resultsTable"><thead><tr><th>probe</th><th>updated</th><th>UA</th><th>webgl2</th><th>fps (2d / 1080p shader)</th></tr></thead><tbody></tbody></table>
  </section>
</main>
<script>
(function () {
  "use strict";

  function uuid() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "p-" + Math.random().toString(16).slice(2) + Date.now().toString(16);
  }
  var PROBE_ID = uuid();
  var loadedAt = performance.now();
  var result = { probe_id: PROBE_ID, started_ms: Date.now() };

  function setKv(elId, pairs) {
    var el = document.getElementById(elId);
    el.innerHTML = "";
    pairs.forEach(function (p) {
      var dt = document.createElement("dt"); dt.textContent = p[0];
      var dd = document.createElement("dd"); dd.textContent = p[1];
      el.appendChild(dt); el.appendChild(dd);
    });
  }

  function setStatus(text, cls) {
    var el = document.getElementById("status");
    el.textContent = text;
    el.className = cls || "";
  }

  // ── static info ──────────────────────────────────────────────────────
  function collectStaticInfo() {
    var info = {
      user_agent: navigator.userAgent,
      platform: navigator.platform || "",
      screen_width: window.innerWidth,
      screen_height: window.innerHeight,
      device_pixel_ratio: window.devicePixelRatio || 1,
      webgl1: false, webgl2: false,
      gpu_vendor: "", gpu_renderer: "",
    };
    // Separate canvases: once a canvas's context is bound to one type
    // ("webgl"), a later getContext() call for a DIFFERENT type on the
    // SAME canvas always returns null, per the HTML Canvas spec — so
    // webgl1 and webgl2 must each get their own fresh canvas.
    var probe1 = document.createElement("canvas");
    var gl1 = probe1.getContext("webgl") || probe1.getContext("experimental-webgl");
    info.webgl1 = !!gl1;
    var probe2 = document.createElement("canvas");
    var gl2 = probe2.getContext("webgl2");
    info.webgl2 = !!gl2;
    var gl = gl2 || gl1;
    if (gl) {
      var ext = gl.getExtension("WEBGL_debug_renderer_info");
      if (ext) {
        info.gpu_vendor = gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) || "";
        info.gpu_renderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "";
      } else {
        info.gpu_vendor = gl.getParameter(gl.VENDOR) || "";
        info.gpu_renderer = gl.getParameter(gl.RENDERER) || "";
      }
    }
    setKv("browserInfo", [
      ["User-Agent", info.user_agent], ["Platform", info.platform],
      ["Page size", info.screen_width + "x" + info.screen_height],
      ["devicePixelRatio", String(info.device_pixel_ratio)],
      ["WebGL 1 / 2", (info.webgl1 ? "yes" : "no") + " / " + (info.webgl2 ? "yes" : "no")],
      ["GPU", (info.gpu_renderer || info.gpu_vendor || "(not reported)")],
    ]);
    return info;
  }

  // ── fps ladder: each tier runs for TIER_MS, counting rAF callbacks ─────
  var TIER_MS = 1500;
  var host = document.getElementById("canvasHost");

  function freshCanvas(w, h) {
    host.innerHTML = "";
    var c = document.createElement("canvas");
    c.width = w; c.height = h;
    host.appendChild(c);
    return c;
  }

  function runForMs(ms, drawFrame) {
    return new Promise(function (resolve) {
      var count = 0;
      var t0 = performance.now();
      function tick() {
        drawFrame();
        count += 1;
        var elapsed = performance.now() - t0;
        if (elapsed < ms) {
          requestAnimationFrame(tick);
        } else {
          resolve(count / (elapsed / 1000));
        }
      }
      requestAnimationFrame(tick);
    });
  }

  function tier2dFill() {
    var c = freshCanvas(320, 180);
    var ctx = c.getContext("2d");
    var n = 0;
    return runForMs(TIER_MS, function () {
      n += 1;
      ctx.fillStyle = "hsl(" + ((n * 7) % 360) + ",70%,50%)";
      ctx.fillRect(0, 0, c.width, c.height);
      for (var i = 0; i < 40; i++) {
        ctx.fillStyle = "rgba(255,255,255," + (0.1 + 0.02 * i) + ")";
        ctx.fillRect((i * 13 + n) % c.width, (i * 7) % c.height, 6, 6);
      }
    });
  }

  var SHADER_VS = "attribute vec2 p; void main(){ gl_Position = vec4(p,0.0,1.0); }";
  var SHADER_FS_PLAIN =
    "precision mediump float; uniform float t; uniform vec2 res;" +
    "void main(){ vec2 uv = gl_FragCoord.xy / res;" +
    " vec3 c = vec3(0.5+0.5*sin(uv.x*10.0+t), 0.5+0.5*cos(uv.y*10.0+t*1.3), 0.5+0.5*sin((uv.x+uv.y)*8.0+t*0.7));" +
    " gl_FragColor = vec4(c, 1.0); }";
  // A heavier pass approximating Butterchurn's per-pixel cost (several
  // trig terms, not the real Milkdrop preset math) — named "approx" on the
  // result so nothing downstream reads it as a measured Milkdrop number.
  var SHADER_FS_HEAVY =
    "precision mediump float; uniform float t; uniform vec2 res;" +
    "void main(){ vec2 uv = gl_FragCoord.xy / res; vec3 c = vec3(0.0);" +
    " for (int i = 0; i < 6; i++) { float fi = float(i);" +
    "   c += 0.16 * vec3(0.5+0.5*sin(uv.x*(10.0+fi*4.0)+t*(1.0+fi*0.3))," +
    "                    0.5+0.5*cos(uv.y*(10.0+fi*3.0)+t*(1.1+fi*0.2))," +
    "                    0.5+0.5*sin((uv.x+uv.y)*(8.0+fi*5.0)+t*(0.7+fi*0.4))); }" +
    " gl_FragColor = vec4(c, 1.0); }";

  function compile(gl, vsSrc, fsSrc) {
    function sh(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    }
    var prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, vsSrc));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fsSrc));
    gl.linkProgram(prog);
    return prog;
  }

  function shaderTier(w, h, fsSrc) {
    var c = freshCanvas(w, h);
    var gl = c.getContext("webgl") || c.getContext("experimental-webgl");
    if (!gl) return Promise.resolve(null);
    var prog = compile(gl, SHADER_VS, fsSrc);
    gl.useProgram(prog);
    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    var tLoc = gl.getUniformLocation(prog, "t");
    var resLoc = gl.getUniformLocation(prog, "res");
    gl.viewport(0, 0, w, h);
    var t = 0;
    return runForMs(TIER_MS, function () {
      t += 0.03;
      gl.uniform1f(tLoc, t);
      gl.uniform2f(resLoc, w, h);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    });
  }

  // Approximates the Live view's own renderer (AGENTS.md: "ONE instanced
  // WebGL2 call ... MAX blend") with many instanced points, MAX-blended.
  function instancedPointsTier() {
    var c = freshCanvas(320, 180);
    var gl = c.getContext("webgl2");
    if (!gl) return Promise.resolve(null);
    var N = 2000;
    var vs = "#version 300 es\\n" +
      "in vec2 offset; uniform float t;" +
      "void main(){ float a = float(gl_InstanceID) * 0.017 + t;" +
      " vec2 p = offset + 0.6 * vec2(cos(a), sin(a));" +
      " gl_Position = vec4(p, 0.0, 1.0); gl_PointSize = 3.0; }";
    var fs = "#version 300 es\\n" + "precision mediump float; out vec4 o;" +
      "void main(){ o = vec4(1.0, 0.8, 1.0, 0.25); }";
    var prog = compile(gl, vs, fs);
    gl.useProgram(prog);
    var offsets = new Float32Array(N * 2);
    for (var i = 0; i < N; i++) { offsets[i * 2] = 0; offsets[i * 2 + 1] = 0; }
    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, offsets, gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(prog, "offset");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    var tLoc = gl.getUniformLocation(prog, "t");
    gl.viewport(0, 0, 320, 180);
    gl.enable(gl.BLEND);
    gl.blendEquation(gl.MAX);
    var t = 0;
    return runForMs(TIER_MS, function () {
      t += 0.02;
      gl.uniform1f(tLoc, t);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArraysInstanced(gl.POINTS, 0, 1, N);
    });
  }

  function runFpsLadder() {
    var fps = {};
    return tier2dFill().then(function (v) { fps["2d_fill"] = v;
      return shaderTier(960, 540, SHADER_FS_PLAIN); }).then(function (v) { fps["shader_540p"] = v;
      return shaderTier(1280, 720, SHADER_FS_PLAIN); }).then(function (v) { fps["shader_720p"] = v;
      return shaderTier(1920, 1080, SHADER_FS_PLAIN); }).then(function (v) { fps["shader_1080p"] = v;
      return shaderTier(960, 540, SHADER_FS_HEAVY); }).then(function (v) { fps["milkdrop_weight_approx"] = v;
      return instancedPointsTier(); }).then(function (v) { fps["instanced_points"] = v;
      return fps; });
  }

  // ── ping round trips ────────────────────────────────────────────────────
  function measurePings(n) {
    var out = [];
    function one(i) {
      if (i >= n) return Promise.resolve(out);
      var t0 = performance.now();
      return fetch("../api/tv/probe/ping", { cache: "no-store" }).then(function () {
        out.push(performance.now() - t0);
        return one(i + 1);
      }).catch(function () {
        return one(i + 1);
      });
    }
    return one(0);
  }

  // ── screensaver log ──────────────────────────────────────────────────────
  var screensaverLog = [];
  function logVisibility() {
    var row = { t: (performance.now() - loadedAt) / 1000, state: document.visibilityState };
    screensaverLog.push(row);
    var tbody = document.querySelector("#screensaverTable tbody");
    var tr = document.createElement("tr");
    var td1 = document.createElement("td"); td1.textContent = row.t.toFixed(1);
    var td2 = document.createElement("td"); td2.textContent = row.state;
    tr.appendChild(td1); tr.appendChild(td2);
    tbody.appendChild(tr);
    postResult({ screensaver_log: screensaverLog });
  }
  document.addEventListener("visibilitychange", logVisibility);

  // ── posting + rendering stored results ──────────────────────────────────
  function postResult(patch) {
    return fetch("../api/tv/probe/result", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ probe_id: PROBE_ID }, patch)),
    }).catch(function () { /* best-effort: a dropped POST just means a quieter record */ });
  }

  function renderResults(rows) {
    var tbody = document.querySelector("#resultsTable tbody");
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      [
        (r.probe_id || "").slice(0, 8),
        r.updated_ms ? new Date(r.updated_ms).toLocaleString() : "",
        (r.user_agent || "").slice(0, 40),
        r.webgl2 ? "yes" : "no",
        (r.fps ? (Math.round(r.fps["2d_fill"] || 0) + " / " + Math.round(r.fps["shader_1080p"] || 0)) : ""),
      ].forEach(function (text) {
        var td = document.createElement("td"); td.textContent = text; tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  function refreshResults() {
    fetch("../api/tv/probe/results", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (rows) { renderResults(rows); })
      .catch(function () { /* diagnostic only */ });
  }

  // ── the run ──────────────────────────────────────────────────────────────
  var staticInfo = collectStaticInfo();
  var lastFps = {};
  setStatus("Running the fps ladder…");
  runFpsLadder().then(function (fps) {
    lastFps = fps;
    setKv("fpsInfo", Object.keys(fps).map(function (k) {
      return [k, fps[k] === null ? "n/a (no context)" : fps[k].toFixed(1) + " fps"];
    }));
    setStatus("Measuring ping round-trips…");
    return measurePings(10);
  }).then(function (pings) {
    var sorted = pings.slice().sort(function (a, b) { return a - b; });
    var min = sorted.length ? sorted[0] : null;
    var median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : null;
    setKv("pingInfo", [
      ["samples", String(pings.length)],
      ["min (ms)", min === null ? "n/a" : min.toFixed(1)],
      ["median (ms)", median === null ? "n/a" : median.toFixed(1)],
    ]);
    return postResult(Object.assign({}, staticInfo, {
      fps: lastFps, ping_ms: pings, screensaver_log: screensaverLog,
    }));
  }).then(function () {
    setStatus("Probe stored. Leave this page open and the remote alone to log the screensaver.", "ok");
    refreshResults();
  }).catch(function (err) {
    setStatus("Probe error: " + (err && err.message ? err.message : String(err)), "err");
  });
})();
</script>
</body>
</html>
"""


def render_probe_html() -> str:
    return _PAGE_HTML
