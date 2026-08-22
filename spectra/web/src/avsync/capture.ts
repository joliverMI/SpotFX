/** Phone-side capture pipeline for the AV-sync instrument (/avsync).
 *
 * PRIVACY, stated where the code is: raw audio and raw video never leave
 * this device. The microphone stream is reduced IN THE BROWSER to a
 * log-energy envelope (one dB number per ~11 ms hop); the camera stream is
 * drawn onto a 32×24 canvas and reduced to one mean brightness plus a 4×4
 * grid of region means per frame. Only those numbers cross the WebSocket
 * to SPECTRA (same origin you are already on). The ONE exception is the
 * frame tap — OFF by default, switched on only from the server side
 * (POST /api/av-sync/frame-tap) — which sends small JPEG stills to the
 * server's MEMORY for the future vision stage; see av_sync_session.py.
 *
 * CLOCKS — everything the phone sends is stamped on ONE clock,
 * performance.now() (DOMHighResTimeStamp, ms since the page opened):
 *   video  requestVideoFrameCallback's `captureTime` when the browser
 *          provides it (Chrome does for a local camera — the frame's
 *          capture time, not its display time), else the callback time
 *          (`now`), flagged to the server as capture_time_available=false
 *          so the extra camera-pipeline latency is NAMED as a systematic.
 *   audio  the AudioWorklet's context clock (`currentTime` at each hop),
 *          mapped onto performance.now() through
 *          AudioContext.getOutputTimestamp() — the browser's own
 *          (contextTime, performanceTime) pairing. The mic's input latency
 *          (if MediaTrackSettings.latency is reported) is sent in hello so
 *          the server can subtract it; otherwise it's a named systematic.
 * The server pairs this clock with its own over ping/pong; the residual
 * cancels in the offset (it's common to both lags).
 *
 * THE VISION SEAM, phone side: `FrameSource.consumers` — the luminance
 * extractor is one consumer of the decoded frames; `frameTap` is the
 * second (off by default). A later stage that wants pixels gets them
 * here, with the same capture timestamps, without touching the
 * measurement path. Nothing in this file recognises anything in a frame.
 */

export type AudioBatch = { t0Ms: number; hopMs: number; v: number[] };
export type VideoSample = { tMs: number; lum: number; grid: number[] };

export type Capabilities = {
  secureContext: boolean;
  captureTime: boolean;
  audioWorklet: boolean;
  rvfc: boolean;
  audioLatencyS: number | null;
  sampleRate: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  facing: string | null;
};

export type FrameTapConfig = { enabled: boolean; fps: number; width: number };

export type CaptureHandlers = {
  onAudio: (b: AudioBatch) => void;
  onVideo: (samples: VideoSample[]) => void;
  onFrame?: (f: { capturedAtMs: number; width: number; height: number; mime: string; b64: string }) => void;
  onLevel?: (audioDb: number, lum: number) => void;
  onError?: (message: string) => void;
};

const GRID = 4;
const ANALYSIS_W = 32;
const ANALYSIS_H = 24;
const AUDIO_HOP_QUANTA = 4; // 4 × 128-sample render quanta ≈ 10.7 ms @ 48 kHz
const AUDIO_BATCH_HOPS = 8;
const VIDEO_BATCH = 4;
const VIDEO_FLUSH_MS = 120;

export function secureContextProblem(): string | null {
  if (!window.isSecureContext) {
    return 'This page is not on a secure (https) address, so the browser hides the camera and microphone.';
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return 'This browser does not expose camera/microphone capture (navigator.mediaDevices is missing).';
  }
  return null;
}

// The AudioWorklet module, inlined as a Blob URL so it needs no extra asset
// (Chrome + Safari both accept blob: module URLs for addModule).
const WORKLET_SRC = `
class SpectraEnvelopeProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.acc = 0; this.n = 0; this.quanta = 0; this.hopT0 = -1;
    this.times = []; this.vals = [];
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    if (this.hopT0 < 0) this.hopT0 = currentTime;
    let s = 0;
    for (let i = 0; i < ch.length; i++) s += ch[i] * ch[i];
    this.acc += s; this.n += ch.length; this.quanta += 1;
    if (this.quanta >= ${AUDIO_HOP_QUANTA}) {
      const p = this.n > 0 ? this.acc / this.n : 0;
      const db = p > 0 ? Math.max(-90, 10 * Math.log10(p)) : -90;
      this.times.push(this.hopT0); this.vals.push(db);
      this.acc = 0; this.n = 0; this.quanta = 0; this.hopT0 = -1;
      if (this.vals.length >= ${AUDIO_BATCH_HOPS}) {
        this.port.postMessage({ t0: this.times[0], hopS: ${AUDIO_HOP_QUANTA} * 128 / sampleRate, v: this.vals });
        this.times = []; this.vals = [];
      }
    }
    return true;
  }
}
registerProcessor('spectra-envelope', SpectraEnvelopeProcessor);
`;

function luminanceOf(data: Uint8ClampedArray, w: number, h: number): { mean: number; grid: number[] } {
  const cellW = w / GRID;
  const cellH = h / GRID;
  const sums = new Float64Array(GRID * GRID);
  const counts = new Float64Array(GRID * GRID);
  let total = 0;
  for (let y = 0; y < h; y++) {
    const gy = Math.min(GRID - 1, Math.floor(y / cellH));
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      const l = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
      const gx = Math.min(GRID - 1, Math.floor(x / cellW));
      const k = gy * GRID + gx;
      sums[k] += l;
      counts[k] += 1;
      total += l;
    }
  }
  const grid: number[] = [];
  for (let k = 0; k < GRID * GRID; k++) grid.push(counts[k] ? +(sums[k] / counts[k]).toFixed(2) : 0);
  return { mean: +(total / (w * h)).toFixed(2), grid };
}

export class PhoneCapture {
  readonly caps: Capabilities;
  private stream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private rvfcHandle: number | null = null;
  private rafHandle: number | null = null;
  private stopped = false;
  private pendingVideo: VideoSample[] = [];
  private lastVideoFlush = 0;
  private canvas: HTMLCanvasElement;
  private ctx2d: CanvasRenderingContext2D;
  private tapCanvas: HTMLCanvasElement | null = null;
  private tap: FrameTapConfig = { enabled: false, fps: 1, width: 320 };
  private lastTapAt = 0;
  private frameCount = 0;
  private firstFrameAt: number | null = null;
  private lastLevel = { db: -90, lum: 0 };

  constructor(private video: HTMLVideoElement, private handlers: CaptureHandlers) {
    this.caps = {
      secureContext: window.isSecureContext,
      captureTime: false,
      audioWorklet: false,
      rvfc: typeof (HTMLVideoElement.prototype as unknown as { requestVideoFrameCallback?: unknown })
        .requestVideoFrameCallback === 'function',
      audioLatencyS: null,
      sampleRate: null,
      fps: null,
      width: null,
      height: null,
      facing: null,
    };
    this.canvas = document.createElement('canvas');
    this.canvas.width = ANALYSIS_W;
    this.canvas.height = ANALYSIS_H;
    this.ctx2d = this.canvas.getContext('2d', { willReadFrequently: true })!;
  }

  /** Opens camera + mic (ONE permission prompt pair: Camera, Microphone),
   * starts both extractors, resolves once the first video frame has been
   * analysed (so `caps.captureTime` is known before `hello`). */
  async start(): Promise<void> {
    const problem = secureContextProblem();
    if (problem) throw new Error(problem);
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 320 },
        height: { ideal: 240 },
        frameRate: { ideal: 60, min: 15 },
      },
      // Processing off: echo cancellation / noise suppression / AGC all
      // reshape the envelope and add their own latency.
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    const vt = this.stream.getVideoTracks()[0];
    const at = this.stream.getAudioTracks()[0];
    const vs = vt?.getSettings() ?? {};
    const as = (at?.getSettings() ?? {}) as MediaTrackSettings & { latency?: number };
    this.caps.fps = typeof vs.frameRate === 'number' ? vs.frameRate : null;
    this.caps.width = typeof vs.width === 'number' ? vs.width : null;
    this.caps.height = typeof vs.height === 'number' ? vs.height : null;
    this.caps.facing = typeof vs.facingMode === 'string' ? vs.facingMode : null;
    this.caps.audioLatencyS = typeof as.latency === 'number' ? as.latency : null;
    this.caps.sampleRate = typeof as.sampleRate === 'number' ? as.sampleRate : null;

    this.video.srcObject = this.stream;
    this.video.muted = true;
    this.video.playsInline = true;
    await this.video.play();
    await this.startAudio(this.stream);
    await this.startVideo();
  }

  stop(): void {
    this.stopped = true;
    if (this.rvfcHandle !== null) {
      (this.video as unknown as { cancelVideoFrameCallback?: (h: number) => void })
        .cancelVideoFrameCallback?.(this.rvfcHandle);
      this.rvfcHandle = null;
    }
    if (this.rafHandle !== null) {
      cancelAnimationFrame(this.rafHandle);
      this.rafHandle = null;
    }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    void this.audioCtx?.close();
    this.audioCtx = null;
  }

  setFrameTap(cfg: FrameTapConfig): void {
    this.tap = { ...cfg };
  }

  level(): { db: number; lum: number } {
    return this.lastLevel;
  }

  measuredFps(): number | null {
    if (this.firstFrameAt === null || this.frameCount < 10) return null;
    return +((this.frameCount - 1) / ((performance.now() - this.firstFrameAt) / 1000)).toFixed(1);
  }

  // ── audio ────────────────────────────────────────────────────────────
  private async startAudio(stream: MediaStream): Promise<void> {
    const Ctx = (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext);
    const ctx = new Ctx();
    this.audioCtx = ctx;
    if (ctx.state === 'suspended') await ctx.resume();
    this.caps.sampleRate = ctx.sampleRate;
    const src = ctx.createMediaStreamSource(stream);
    const mapToPerf = (contextTimeS: number): number => {
      const m = ctx.getOutputTimestamp();
      if (typeof m.contextTime === 'number' && typeof m.performanceTime === 'number') {
        return (contextTimeS - m.contextTime) * 1000 + m.performanceTime;
      }
      // very old engines: fall back to "now minus elapsed"
      return performance.now() - (ctx.currentTime - contextTimeS) * 1000;
    };
    const emit = (t0S: number, hopS: number, v: number[]) => {
      if (this.stopped) return;
      const db = v[v.length - 1] ?? -90;
      this.lastLevel = { db, lum: this.lastLevel.lum };
      this.handlers.onAudio({ t0Ms: mapToPerf(t0S), hopMs: hopS * 1000, v });
      this.handlers.onLevel?.(db, this.lastLevel.lum);
    };
    if (ctx.audioWorklet) {
      try {
        const url = URL.createObjectURL(new Blob([WORKLET_SRC], { type: 'application/javascript' }));
        await ctx.audioWorklet.addModule(url);
        const node = new AudioWorkletNode(ctx, 'spectra-envelope', { numberOfInputs: 1, numberOfOutputs: 0 });
        node.port.onmessage = (e: MessageEvent) => {
          const d = e.data as { t0: number; hopS: number; v: number[] };
          emit(d.t0, d.hopS, d.v);
        };
        src.connect(node);
        this.caps.audioWorklet = true;
        return;
      } catch (err) {
        this.handlers.onError?.(`AudioWorklet unavailable (${String(err)}) — using ScriptProcessor`);
      }
    }
    // Fallback: ScriptProcessorNode — deprecated but universal; its
    // playbackTime is the context time of the buffer's first sample.
    const proc = ctx.createScriptProcessor(1024, 1, 1);
    const hop = 256;
    proc.onaudioprocess = (e) => {
      const ch = e.inputBuffer.getChannelData(0);
      const hopS = hop / ctx.sampleRate;
      const v: number[] = [];
      for (let i = 0; i + hop <= ch.length; i += hop) {
        let s = 0;
        for (let j = i; j < i + hop; j++) s += ch[j] * ch[j];
        const p = s / hop;
        v.push(p > 0 ? Math.max(-90, 10 * Math.log10(p)) : -90);
      }
      emit(e.playbackTime, hopS, v);
    };
    src.connect(proc);
    proc.connect(ctx.destination); // required by some engines to keep the node alive (muted by zero gain below)
    const g = ctx.createGain();
    g.gain.value = 0;
    proc.disconnect();
    proc.connect(g);
    g.connect(ctx.destination);
  }

  // ── video ────────────────────────────────────────────────────────────
  private startVideo(): Promise<void> {
    return new Promise<void>((resolve) => {
      let resolved = false;
      const analyse = (tMs: number) => {
        if (this.stopped) return;
        this.ctx2d.drawImage(this.video, 0, 0, ANALYSIS_W, ANALYSIS_H);
        const img = this.ctx2d.getImageData(0, 0, ANALYSIS_W, ANALYSIS_H);
        const { mean, grid } = luminanceOf(img.data, ANALYSIS_W, ANALYSIS_H);
        this.lastLevel = { db: this.lastLevel.db, lum: mean };
        this.frameCount += 1;
        if (this.firstFrameAt === null) this.firstFrameAt = performance.now();
        this.pendingVideo.push({ tMs, lum: mean, grid });
        const now = performance.now();
        if (this.pendingVideo.length >= VIDEO_BATCH || now - this.lastVideoFlush > VIDEO_FLUSH_MS) {
          this.lastVideoFlush = now;
          const out = this.pendingVideo;
          this.pendingVideo = [];
          this.handlers.onVideo(out);
        }
        this.handlers.onLevel?.(this.lastLevel.db, mean);
        this.maybeTap(tMs);
        if (!resolved) {
          resolved = true;
          resolve();
        }
      };
      const v = this.video as HTMLVideoElement & {
        requestVideoFrameCallback?: (cb: (now: number, meta: Record<string, unknown>) => void) => number;
      };
      if (typeof v.requestVideoFrameCallback === 'function') {
        const loop = (now: number, meta: Record<string, unknown>) => {
          if (this.stopped) return;
          const ct = meta.captureTime;
          if (typeof ct === 'number') {
            this.caps.captureTime = true;
            analyse(ct);
          } else {
            analyse(now);
          }
          this.rvfcHandle = v.requestVideoFrameCallback!(loop);
        };
        this.rvfcHandle = v.requestVideoFrameCallback(loop);
      } else {
        // no per-frame callback: sample at display rate, timestamped now
        const loop = () => {
          if (this.stopped) return;
          analyse(performance.now());
          this.rafHandle = requestAnimationFrame(loop);
        };
        this.rafHandle = requestAnimationFrame(loop);
      }
    });
  }

  private maybeTap(capturedAtMs: number): void {
    if (!this.tap.enabled || !this.handlers.onFrame) return;
    const now = performance.now();
    if (now - this.lastTapAt < 1000 / Math.max(0.2, this.tap.fps)) return;
    this.lastTapAt = now;
    const vw = this.video.videoWidth || 320;
    const vh = this.video.videoHeight || 240;
    const w = Math.max(16, Math.min(this.tap.width, vw));
    const h = Math.max(12, Math.round((w / vw) * vh));
    if (!this.tapCanvas) this.tapCanvas = document.createElement('canvas');
    this.tapCanvas.width = w;
    this.tapCanvas.height = h;
    const c = this.tapCanvas.getContext('2d')!;
    c.drawImage(this.video, 0, 0, w, h);
    this.tapCanvas.toBlob((blob) => {
      if (!blob) return;
      blob.arrayBuffer().then((buf) => {
        let bin = '';
        const bytes = new Uint8Array(buf);
        for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
        this.handlers.onFrame?.({ capturedAtMs, width: w, height: h, mime: 'image/jpeg', b64: btoa(bin) });
      });
    }, 'image/jpeg', 0.7);
  }
}

// ── the WebSocket client ─────────────────────────────────────────────────

export type ServerMessage = Record<string, unknown> & { type: string };

export class AvSyncClient {
  private ws: WebSocket | null = null;
  private listeners = new Set<(m: ServerMessage) => void>();
  private openListeners = new Set<(open: boolean) => void>();
  connected = false;

  static url(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/spectra/api/av-sync/ws`;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(AvSyncClient.url());
      this.ws = ws;
      ws.onopen = () => {
        this.connected = true;
        this.openListeners.forEach((fn) => fn(true));
        resolve();
      };
      ws.onerror = () => reject(new Error('WebSocket to /spectra/api/av-sync/ws failed'));
      ws.onclose = () => {
        this.connected = false;
        this.openListeners.forEach((fn) => fn(false));
      };
      ws.onmessage = (e) => {
        let msg: ServerMessage;
        try {
          msg = JSON.parse(e.data as string) as ServerMessage;
        } catch {
          return;
        }
        if (msg.type === 'ping') {
          // answer on the phone's own clock — the server pairs the two
          this.send({ type: 'pong', seq: msg.seq, t_phone_ms: performance.now() });
        }
        this.listeners.forEach((fn) => fn(msg));
      };
    });
  }

  close(): void {
    try {
      this.ws?.close();
    } catch {
      /* ignore */
    }
    this.ws = null;
  }

  send(msg: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  onMessage(fn: (m: ServerMessage) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  onOpenChange(fn: (open: boolean) => void): () => void {
    this.openListeners.add(fn);
    return () => this.openListeners.delete(fn);
  }
}
