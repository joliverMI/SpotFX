/** Phone-side capture for the ROOM LIGHT-FIELD map (/rooms) and for the
 * COMMISSIONING read.
 *
 * PRIVACY, stated where the code is: the camera stream is reduced IN THE
 * BROWSER to a single-byte greyscale image and only those bytes cross the
 * same-origin WebSocket. No microphone is ever opened by this page —
 * getUserMedia is called with `audio: false` and there is no audio code in
 * this file at all, which is what makes "no music needed" true by
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
 * WHY grey8 AND NOT JPEG, AT ANY SIZE: a lossy codec's own quantisation
 * lands in the difference this instrument measures, and decoding one
 * server-side would put an image library in a path that needs none.
 * 320x180 at ~5 fps is ~58 KB/frame, ~288 KB/s before base64 — the plan's
 * own budget.
 *
 * THE FRAME SIZE IS PER RUN, AND THE SERVER ASKS FOR IT (2026-09-01).
 * `spectra/services/capture_settings.py` is the binding statement — the
 * ladder of declared sizes and the arithmetic that chose them. A MAP still
 * sends 320x180; the COMMISSIONING read asks for 1920x1080, because a
 * gray-code decode needs about two camera pixels per LED and 736 of them
 * therefore need ~1,472 pixels of imaged strip, where the whole perimeter
 * of a 320x180 frame is 1,000. The server sends a `config` message and
 * `setFrameSize` below answers it.
 *
 * THIS PAGE NEVER UPSCALES, and that rule is the reason the raise is safe.
 * A 1920x1080 canvas drawn from a 1280x720 camera image holds no more
 * detail than the 720p it came from — but the decode COUNTS CAMERA PIXELS,
 * so interpolated ones would inflate the count and a target that cannot be
 * resolved would report that it can: the confident-wrong-answer the whole
 * instrument exists to refuse, arriving through a side door. So the canvas
 * is clamped to the largest declared size the live track actually
 * delivers, every frame carries `source_width`/`source_height`, and the
 * SERVER checks the same thing independently.
 *
 * THE TWO MANUAL LEVERS ride the same `config` message: integration time
 * (`exposureTime`, in 100-microsecond units — the same unit V4L2 uses, so
 * nothing converts) and gain (`iso`, a device-specific scale passed
 * through verbatim). Both are OPTIONAL and asking for neither is today's
 * behaviour exactly: let auto-exposure converge on the scene, then freeze
 * it. Where a lever is asked for and this camera does not offer it, the
 * page REPORTS that by name in `manual_refusals` and the server refuses —
 * the existing lock discipline extended, never weakened. This file still
 * never decides to proceed anyway.
 *
 * Deliberately NOT shared with ../avsync/capture.ts: that pipeline opens a
 * microphone, keeps an AudioWorklet, and reduces video to a 4x4 grid of
 * means. Sharing a base class would mean the audio path exists here and is
 * merely switched off.
 */

/** THE LADDER, mirroring `spectra/services/capture_settings.PROFILES`.
 * Every rung is 16:9 and an exact whole multiple of the stored 64x36 map
 * grid (5x, 10x, 15x, 20x, 30x), so the server's downsample stays a box
 * mean with no interpolation to explain at any of them. Small to large. */
export const FRAME_SIZES: ReadonlyArray<readonly [number, number]> = [
  [320, 180], [640, 360], [960, 540], [1280, 720], [1920, 1080],
];
/** The MAP's frame, and this page's starting size. */
export const FRAME_W = 320;
export const FRAME_H = 180;
export const GREY_MIME = 'image/grey8';

/** The largest rung no bigger than what was ASKED FOR and no bigger than
 * what the camera actually DELIVERS — the "never upscale" rule, in one
 * place, mirroring `capture_settings.choose`. An unknown source (0) is not
 * treated as unlimited by accident: it returns the request, and the server
 * checks the arriving frames against the source size we report anyway. */
export function chooseFrameSize(
  want: readonly [number, number],
  sourceW: number,
  sourceH: number,
): [number, number] {
  if (!sourceW || !sourceH) return [want[0], want[1]];
  for (let i = FRAME_SIZES.length - 1; i >= 0; i -= 1) {
    const [w, h] = FRAME_SIZES[i];
    if (w <= want[0] && h <= want[1] && w <= sourceW && h <= sourceH) return [w, h];
  }
  return [FRAME_SIZES[0][0], FRAME_SIZES[0][1]];
}

export type LockState = {
  exposure_locked: boolean;
  white_balance_locked: boolean;
  exposure_mode: string;
  white_balance_mode: string;
  exposure_capabilities: string[];
  white_balance_capabilities: string[];
  /** WHAT THE BROWSER READ BACK, never what was asked for. `exposure_time`
   * is in 100-microsecond units on both this path and the capture client's
   * V4L2 one, so nothing converts it; `gain` is `iso`, a device-specific
   * scale passed through verbatim. null means this camera would not say. */
  exposure_time: number | null;
  gain: number | null;
  exposure_time_range: [number, number] | null;
  gain_range: [number, number] | null;
  /** Manual levers a run ASKED FOR that this camera does not offer or did
   * not take, in words. The server refuses on these; this page only
   * reports them. */
  manual_refusals: string[];
  source: string;
};

/** What the server asked this camera for, in one `config` message. */
export type CameraRequest = {
  frame_size?: { width: number; height: number } | null;
  exposure_time?: number | null;
  gain?: number | null;
};

export type MappingHandlers = {
  onFrame: (f: {
    capturedAtMs: number; width: number; height: number; b64: string;
    sourceWidth: number; sourceHeight: number;
  }) => void;
  onLock?: (lock: LockState) => void;
  onError?: (message: string) => void;
};

type TrackCaps = MediaTrackCapabilities & {
  exposureMode?: string[];
  whiteBalanceMode?: string[];
  exposureTime?: { min: number; max: number };
  iso?: { min: number; max: number };
};
type TrackSettings = MediaTrackSettings & {
  exposureMode?: string;
  whiteBalanceMode?: string;
  exposureTime?: number;
  iso?: number;
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
  /** What the server ASKED for. `size` below is what this camera can
   * actually give of it — never the same field, and never upscaled. */
  private wanted: [number, number] = [FRAME_W, FRAME_H];
  size: [number, number] = [FRAME_W, FRAME_H];
  lock: LockState = {
    exposure_locked: false,
    white_balance_locked: false,
    exposure_mode: '',
    white_balance_mode: '',
    exposure_capabilities: [],
    white_balance_capabilities: [],
    exposure_time: null,
    gain: null,
    exposure_time_range: null,
    gain_range: null,
    manual_refusals: [],
    source: 'getSettings',
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
    // ASK FOR 1080p, take what arrives: the commissioning read needs it and
    // `ideal` degrades on a camera that has less rather than failing. What
    // is actually SENT is clamped to `videoWidth`/`videoHeight` in
    // `applySize`, so asking high here can never turn into upscaling.
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    });
    this.track = this.stream.getVideoTracks()[0] ?? null;
    this.video.srcObject = this.stream;
    this.video.muted = true;
    this.video.playsInline = true;
    await this.video.play();
    this.applySize();
    await this.lockExposure();
    this.timer = window.setInterval(() => this.tick(), 1000 / Math.max(0.5, fps));
  }

  /** The server asked for a frame size and/or manual levers (its `config`
   * message). Answer it: resize the canvas to the largest rung this camera
   * can honestly fill, then re-apply and RE-READ every control.
   *
   * Never throws and never refuses: refusing is the server's job, and its
   * refusal names the camera and the capability. This page's job is to tell
   * the truth about what happened. */
  async applyConfig(req: CameraRequest): Promise<LockState> {
    if (req.frame_size && req.frame_size.width && req.frame_size.height) {
      this.wanted = [req.frame_size.width, req.frame_size.height];
      this.applySize();
    }
    return this.lockExposure(req);
  }

  /** Size the canvas to the largest declared rung no bigger than BOTH what
   * was asked for and what the live track actually produces. This is the
   * whole of "never upscale" on this side. */
  private applySize(): void {
    const sw = this.video.videoWidth || 0;
    const sh = this.video.videoHeight || 0;
    const [w, h] = chooseFrameSize(this.wanted, sw, sh);
    this.size = [w, h];
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
  }

  /** Ask for manual exposure + white balance — and, when a run asks for
   * them, a specific integration time and gain — then REPORT WHAT ACTUALLY
   * HAPPENED. Never throws on a camera that cannot lock or cannot take a
   * lever: refusing is the server's job and its refusal names the
   * capability, so the page's job is to tell the truth about the camera,
   * not to decide.
   *
   * DEFAULTS PRESERVE TODAY'S BEHAVIOUR EXACTLY. With no `req` (or one
   * carrying neither lever) this is the converge-then-freeze it always was
   * and `manual_refusals` comes back empty, which is what makes the server's
   * manual gate a no-op for every ordinary run. */
  async lockExposure(req?: CameraRequest): Promise<LockState> {
    const track = this.track;
    if (!track) return this.lock;
    const caps = (track.getCapabilities?.() ?? {}) as TrackCaps;
    const wants: MediaTrackConstraintSet[] = [];
    const refusals: string[] = [];
    if (caps.exposureMode?.includes('manual')) wants.push({ exposureMode: 'manual' } as MediaTrackConstraintSet);
    if (caps.whiteBalanceMode?.includes('manual')) wants.push({ whiteBalanceMode: 'manual' } as MediaTrackConstraintSet);
    // THE LEVERS. Asked for only when a run asks, and only when THIS camera
    // declares the capability — a constraint a browser silently ignores
    // would look like it worked, so an absent capability is named here
    // rather than discovered from a read-back that never moved.
    if (req?.exposure_time != null) {
      if (caps.exposureTime) {
        wants.push({ exposureTime: req.exposure_time } as MediaTrackConstraintSet);
      } else {
        refusals.push('this camera exposes no exposureTime control, so a manual integration time cannot be set from a browser');
      }
    }
    if (req?.gain != null) {
      if (caps.iso) {
        wants.push({ iso: req.gain } as MediaTrackConstraintSet);
      } else {
        refusals.push('this camera exposes no iso control, so a manual gain cannot be set from a browser');
      }
    }
    if (wants.length) {
      try {
        // Let auto-exposure settle on the scene BEFORE freezing it — a lock
        // applied the instant the camera opens freezes a half-converged
        // exposure, which is a worse reference than a settled one. A run
        // asking for a MANUAL integration time does not need that wait: it
        // is naming the value rather than accepting whatever converged.
        if (req?.exposure_time == null) await new Promise((r) => setTimeout(r, 600));
        await track.applyConstraints({ advanced: wants } as MediaTrackConstraints);
      } catch (err) {
        this.handlers.onError?.(`the camera refused the exposure lock (${String(err)})`);
        refusals.push(`applyConstraints was refused (${String(err)})`);
      }
    }
    // THE READ-BACK IS THE ONLY STATEMENT THIS MAKES. Everything below comes
    // from getSettings(), never from the constraint above.
    const s = (track.getSettings?.() ?? {}) as TrackSettings;
    const exposureTime = typeof s.exposureTime === 'number' ? s.exposureTime : null;
    const gain = typeof s.iso === 'number' ? s.iso : null;
    if (req?.exposure_time != null && exposureTime !== null
        && Math.abs(exposureTime - req.exposure_time) > 1e-6) {
      refusals.push(`asked for an integration time of ${req.exposure_time} (x100us) and the camera reports ${exposureTime}`);
    }
    if (req?.gain != null && gain !== null && Math.abs(gain - req.gain) > 1e-6) {
      refusals.push(`asked for a gain of ${req.gain} and the camera reports ${gain}`);
    }
    this.lock = {
      exposure_mode: s.exposureMode ?? '',
      white_balance_mode: s.whiteBalanceMode ?? '',
      exposure_locked: s.exposureMode === 'manual',
      white_balance_locked: s.whiteBalanceMode === 'manual',
      exposure_capabilities: caps.exposureMode ?? [],
      white_balance_capabilities: caps.whiteBalanceMode ?? [],
      exposure_time: exposureTime,
      gain,
      exposure_time_range: caps.exposureTime
        ? [caps.exposureTime.min, caps.exposureTime.max] : null,
      gain_range: caps.iso ? [caps.iso.min, caps.iso.max] : null,
      manual_refusals: refusals,
      source: 'getSettings',
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
    // A track can renegotiate its own resolution mid-stream (a camera
    // switching mode, a browser reclaiming bandwidth), so the clamp is
    // re-applied every frame rather than once at start: the moment the
    // source shrinks, so does what we send.
    this.applySize();
    const [w, h] = this.size;
    this.ctx.drawImage(this.video, 0, 0, w, h);
    const img = this.ctx.getImageData(0, 0, w, h);
    const grey = toGrey(img.data, w, h);
    const s = (this.track?.getSettings?.() ?? {}) as TrackSettings;
    if (s.exposureMode !== undefined) {
      this.lock = {
        ...this.lock,
        exposure_mode: s.exposureMode ?? '',
        white_balance_mode: s.whiteBalanceMode ?? '',
        exposure_locked: s.exposureMode === 'manual',
        white_balance_locked: s.whiteBalanceMode === 'manual',
        exposure_time: typeof s.exposureTime === 'number' ? s.exposureTime : this.lock.exposure_time,
        gain: typeof s.iso === 'number' ? s.iso : this.lock.gain,
      };
    }
    this.frames += 1;
    this.lastFrameAt = performance.now();
    this.handlers.onFrame({
      capturedAtMs: this.lastFrameAt,
      width: w,
      height: h,
      b64: b64(grey),
      // WHAT THE CANVAS WAS DRAWN FROM. The server checks the same thing
      // independently and drops any frame bigger than its own source, so
      // "never upscale" is asserted on both sides rather than trusted on
      // one.
      sourceWidth: this.video.videoWidth || 0,
      sourceHeight: this.video.videoHeight || 0,
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
