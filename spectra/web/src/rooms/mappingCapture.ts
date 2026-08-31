/** Phone-side capture for the ROOM LIGHT-FIELD map (/rooms).
 *
 * PRIVACY, stated where the code is: the camera stream is reduced IN THE
 * BROWSER to a 320x180 single-byte greyscale image and only those bytes
 * cross the same-origin WebSocket. No microphone is ever opened by this
 * page — getUserMedia is called with `audio: false` and there is no audio
 * code in this file at all, which is what makes "no music needed" true by
 * construction rather than by a flag.
 *
 * THE EXPOSURE LOCK IS THE WHOLE INSTRUMENT'S HONESTY. A footprint is
 * `lit - dark` in the camera's own byte scale, and every footprint in a
 * room is compared against every other. If auto-exposure re-scales between
 * the dark reference and the lit capture, every comparison is wrong by an
 * unknown factor and nothing downstream can detect it. So this module:
 *   1. asks the track for manual exposure AND manual white balance,
 *   2. reads back what the browser ACTUALLY did (getSettings, never the
 *      constraint we asked for),
 *   3. reports that state to the server on connect and on every frame,
 * and the SERVER refuses a run when either is unlocked, by name. This file
 * never decides to proceed anyway.
 *
 * WHY grey8 AND NOT JPEG: a lossy codec's own quantisation lands in the
 * difference this instrument measures, and decoding one server-side would
 * put an image library in a path that needs none. 320x180 at ~5 fps is
 * ~58 KB/frame, ~288 KB/s before base64 — the plan's own budget.
 *
 * Deliberately NOT shared with ../avsync/capture.ts: that pipeline opens a
 * microphone, keeps an AudioWorklet, and reduces video to a 4x4 grid of
 * means. Sharing a base class would mean the audio path exists here and is
 * merely switched off.
 */

export const FRAME_W = 320;
export const FRAME_H = 180;
export const GREY_MIME = 'image/grey8';

export type LockState = {
  exposure_locked: boolean;
  white_balance_locked: boolean;
  exposure_mode: string;
  white_balance_mode: string;
  exposure_capabilities: string[];
  white_balance_capabilities: string[];
};

export type MappingHandlers = {
  onFrame: (f: { capturedAtMs: number; width: number; height: number; b64: string }) => void;
  onLock?: (lock: LockState) => void;
  onError?: (message: string) => void;
};

type TrackCaps = MediaTrackCapabilities & {
  exposureMode?: string[];
  whiteBalanceMode?: string[];
  exposureTime?: { min: number; max: number };
};
type TrackSettings = MediaTrackSettings & {
  exposureMode?: string;
  whiteBalanceMode?: string;
};

export function secureContextProblem(): string | null {
  if (!window.isSecureContext) {
    return 'This page is not on a secure (https) address, so the browser hides the camera. Mapping needs the camera.';
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return 'This browser does not expose camera capture (navigator.mediaDevices is missing).';
  }
  return null;
}

/** The 24-bit RGBA canvas readback reduced to one luminance byte per pixel,
 * Rec.601 — the same weighting the AV instrument's own reducer uses, so a
 * "brightness" means one thing across this app. */
function toGrey(data: Uint8ClampedArray, w: number, h: number): Uint8Array {
  const out = new Uint8Array(w * h);
  for (let i = 0, p = 0; p < out.length; i += 4, p += 1) {
    out[p] = (0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]) | 0;
  }
  return out;
}

function b64(bytes: Uint8Array): string {
  let bin = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + CHUNK)) as unknown as number[]);
  }
  return btoa(bin);
}

export class MappingCapture {
  readonly canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private stream: MediaStream | null = null;
  private track: MediaStreamTrack | null = null;
  private timer: number | null = null;
  private stopped = false;
  lock: LockState = {
    exposure_locked: false,
    white_balance_locked: false,
    exposure_mode: '',
    white_balance_mode: '',
    exposure_capabilities: [],
    white_balance_capabilities: [],
  };
  lastFrameAt = 0;
  frames = 0;

  constructor(private video: HTMLVideoElement, private handlers: MappingHandlers) {
    this.canvas = document.createElement('canvas');
    this.canvas.width = FRAME_W;
    this.canvas.height = FRAME_H;
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true })!;
  }

  async start(fps = 5): Promise<void> {
    const problem = secureContextProblem();
    if (problem) throw new Error(problem);
    // audio: false, explicitly and always — see the module docstring.
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
      audio: false,
    });
    this.track = this.stream.getVideoTracks()[0] ?? null;
    this.video.srcObject = this.stream;
    this.video.muted = true;
    this.video.playsInline = true;
    await this.video.play();
    await this.lockExposure();
    this.timer = window.setInterval(() => this.tick(), 1000 / Math.max(0.5, fps));
  }

  /** Ask for manual exposure + white balance, then REPORT WHAT ACTUALLY
   * HAPPENED. Never throws on a camera that cannot lock: refusing is the
   * server's job and its refusal names the capability, so the page's job is
   * to tell the truth about the camera, not to decide. */
  async lockExposure(): Promise<LockState> {
    const track = this.track;
    if (!track) return this.lock;
    const caps = (track.getCapabilities?.() ?? {}) as TrackCaps;
    const wants: MediaTrackConstraintSet[] = [];
    if (caps.exposureMode?.includes('manual')) wants.push({ exposureMode: 'manual' } as MediaTrackConstraintSet);
    if (caps.whiteBalanceMode?.includes('manual')) wants.push({ whiteBalanceMode: 'manual' } as MediaTrackConstraintSet);
    if (wants.length) {
      try {
        // Let auto-exposure settle on the scene BEFORE freezing it — a lock
        // applied the instant the camera opens freezes a half-converged
        // exposure, which is a worse reference than a settled one.
        await new Promise((r) => setTimeout(r, 600));
        await track.applyConstraints({ advanced: wants } as MediaTrackConstraints);
      } catch (err) {
        this.handlers.onError?.(`the camera refused the exposure lock (${String(err)})`);
      }
    }
    const s = (track.getSettings?.() ?? {}) as TrackSettings;
    this.lock = {
      exposure_mode: s.exposureMode ?? '',
      white_balance_mode: s.whiteBalanceMode ?? '',
      exposure_locked: s.exposureMode === 'manual',
      white_balance_locked: s.whiteBalanceMode === 'manual',
      exposure_capabilities: caps.exposureMode ?? [],
      white_balance_capabilities: caps.whiteBalanceMode ?? [],
    };
    this.handlers.onLock?.(this.lock);
    return this.lock;
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.track = null;
    this.video.srcObject = null;
  }

  /** One frame, reduced and handed over. Also re-reads the lock state so a
   * camera that quietly returned to auto is caught at the frame that
   * carries it, not at the next capture window. */
  private tick(): void {
    if (this.stopped || !this.video.videoWidth) return;
    this.ctx.drawImage(this.video, 0, 0, FRAME_W, FRAME_H);
    const img = this.ctx.getImageData(0, 0, FRAME_W, FRAME_H);
    const grey = toGrey(img.data, FRAME_W, FRAME_H);
    const s = (this.track?.getSettings?.() ?? {}) as TrackSettings;
    if (s.exposureMode !== undefined) {
      this.lock = {
        ...this.lock,
        exposure_mode: s.exposureMode ?? '',
        white_balance_mode: s.whiteBalanceMode ?? '',
        exposure_locked: s.exposureMode === 'manual',
        white_balance_locked: s.whiteBalanceMode === 'manual',
      };
    }
    this.frames += 1;
    this.lastFrameAt = performance.now();
    this.handlers.onFrame({
      capturedAtMs: this.lastFrameAt,
      width: FRAME_W,
      height: FRAME_H,
      b64: b64(grey),
    });
  }
}

// ── the WebSocket client ─────────────────────────────────────────────────

export type ServerMessage = Record<string, unknown> & { type: string };

export class MappingClient {
  private ws: WebSocket | null = null;
  private listeners = new Set<(m: ServerMessage) => void>();
  connected = false;

  static url(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/spectra/api/rooms/map/ws`;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(MappingClient.url());
      this.ws = ws;
      ws.onopen = () => {
        this.connected = true;
        resolve();
      };
      ws.onerror = () => reject(new Error('WebSocket to /spectra/api/rooms/map/ws failed'));
      ws.onclose = () => {
        this.connected = false;
      };
      ws.onmessage = (e) => {
        let msg: ServerMessage;
        try {
          msg = JSON.parse(e.data as string) as ServerMessage;
        } catch {
          return;
        }
        // answer on the phone's own clock — the server pairs the two
        if (msg.type === 'ping') this.send({ type: 'pong', seq: msg.seq, t_phone_ms: performance.now() });
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
}
