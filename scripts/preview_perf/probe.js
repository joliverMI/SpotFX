// Injected before any page script (CDP Page.addScriptToEvaluateOnNewDocument).
// System-agnostic: it instruments the browser, not the app, so the SAME probe
// measures Spectra's page and LedFX's page.
//   ws      : every WebSocket message  [t_ms, bytes, vis_id|null]
//   paints  : every canvas putImageData [t_ms, w, h, cost_ms]
//   lat     : luminance transitions of the latency virtual
//             [epoch_ms_arrival, epoch_ms_presented, lum]
//   raf     : rAF frame count + long frames (main-thread jank)
//   drawn   : rAF frames in which the page actually DREW (a WebGL draw call,
//             or a 2D fill on the Live view's canvas) — "drawn frames a second"
(() => {
  const LAT_ID = '__LAT_ID__';
  const P = (window.__probe = { ws: [], paints: [], lat: [], rafCount: 0, rafLong: [], drawnFrames: 0, drawCalls: 0, start: performance.now(), origin: performance.timeOrigin, sockets: [] });
  const VIS = /"vis_id":\s*"([^"]+)"/;
  const PIX = /"pixels":\s*"([^"]{0,8})/;
  const LAYOUT = /"type":\s*"device_preview_layout"/;
  let lastLum = -1;
  const noteLum = (lum, t) => {
    if (lum === lastLum) return;
    lastLum = lum;
    const arr = P.origin + t;
    requestAnimationFrame(() => {
      // one more frame: the paint issued in this task is on screen after the next vsync
      requestAnimationFrame(() => P.lat.push([arr, P.origin + performance.now(), lum]));
    });
  };
  const Native = window.WebSocket;
  function Wrapped(url, protocols) {
    const ws = protocols === undefined ? new Native(url) : new Native(url, protocols);
    P.sockets.push(String(url));
    const layout = [];   // Spectra protocol 2: device index -> vis_id, per socket
    ws.addEventListener('message', (e) => {
      const t = performance.now();
      let bytes = 0, vis = null;
      if (e.data instanceof ArrayBuffer && e.data.byteLength >= 20 && new Uint8Array(e.data, 0, 1)[0] === 0xd7) {
        // Spectra protocol 2 (spectra/services/preview_stream.py): one binary
        // message per tick; count each device record as that device's frame.
        const v = new DataView(e.data);
        let off = 20;
        for (let i = 0, n = v.getUint8(2); i < n && off + 12 <= e.data.byteLength; i++) {
          const id = layout[v.getUint8(off)] || null;
          const len = v.getUint32(off + 8, true);
          if (id === LAT_ID && len >= 3) noteLum(v.getUint8(off + 12) > 127 ? 1 : 0, t);
          P.ws.push([t, 12 + len, id]);
          off += 12 + len;
        }
        P.msgs = (P.msgs || 0) + 1;
        return;
      }
      if (typeof e.data === 'string') {
        bytes = e.data.length;
        if (LAYOUT.test(e.data)) {
          try { JSON.parse(e.data).devices.forEach((d) => (layout[d.index] = d.vis_id)); } catch (err) { /* ignore */ }
        }
        const m = VIS.exec(e.data);
        if (m) {
          vis = m[1];
          if (vis === LAT_ID) {
            const p = PIX.exec(e.data);
            if (p && p[1].length >= 4) noteLum(atob(p[1].slice(0, 4)).charCodeAt(0) > 127 ? 1 : 0, t);
          }
        }
      } else if (e.data) {
        bytes = e.data.byteLength || e.data.size || 0;
      }
      P.ws.push([t, bytes, vis]);
    });
    return ws;
  }
  Wrapped.prototype = Native.prototype;
  ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach((k) => (Wrapped[k] = Native[k]));
  window.WebSocket = Wrapped;

  const put = CanvasRenderingContext2D.prototype.putImageData;
  CanvasRenderingContext2D.prototype.putImageData = function (...a) {
    const t = performance.now();
    const r = put.apply(this, a);
    P.paints.push([t, this.canvas.width, this.canvas.height, performance.now() - t]);
    return r;
  };

  let drew = false;
  const noteDraw = () => { drew = true; P.drawCalls++; };
  if (window.WebGL2RenderingContext) {
    const proto = WebGL2RenderingContext.prototype;
    for (const name of ['drawArrays', 'drawArraysInstanced', 'drawElements']) {
      const native = proto[name];
      proto[name] = function (...a) { noteDraw(); return native.apply(this, a); };
    }
  }
  const fillRect = CanvasRenderingContext2D.prototype.fillRect;
  CanvasRenderingContext2D.prototype.fillRect = function (...a) {
    // the 2D fallback clears with one full-canvas fill per drawn frame
    if (this.canvas.className === 'live-canvas' && a[2] === this.canvas.width) noteDraw();
    return fillRect.apply(this, a);
  };

  let last = performance.now();
  const tick = (now) => {
    P.rafCount++;
    if (drew) { P.drawnFrames++; drew = false; }
    if (now - last > 34) P.rafLong.push([now, now - last]);
    last = now;
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  try {
    __PRELOAD__
  } catch (e) { /* storage not available yet on about:blank */ }
})();
