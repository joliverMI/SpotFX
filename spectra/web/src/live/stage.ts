/** The Live view's renderer and playout: a StagePlan (positions.ts) plus
 * preview-stream frames in, pixels out, at the display's own rate.
 *
 * ONE DRAW CALL, NOTHING ALLOCATED PER FRAME. Every point is one instance of
 * a unit quad (WebGL2 instancing): its place and size are uploaded once per
 * plan, its colour is three bytes in ONE buffer that is rewritten and
 * re-uploaded each drawn frame. A frame from the stream is copied out of the
 * message's own bytes into a preallocated array through the plan's source
 * table — no objects, no strings, no per-pixel arrays. Where WebGL2 is not
 * available the same colour array is painted with a 2D canvas instead.
 *
 * Overlapping dots (a 560-LED strip drawn as a line) combine with MAX, not
 * addition: a strip's colour is its LEDs' colour, not their sum.
 *
 * PLAYOUT (the plan's change 5). Frames arrive about 30 a second and not
 * evenly: on a relayed link the gap between two frames swings by tens of
 * milliseconds. Drawn as they land, motion stutters. So each stream device
 * EASES from what is on screen to its newest frame over one frame interval
 * (its own measured arrival spacing): with even arrivals that is exactly
 * "interpolate between the last two frames, one frame behind", and an early
 * or late frame bends the ease instead of jumping.
 *
 * THE EASE IS AS LONG AS THE LINK IS UNEVEN: the interval plus twice the
 * measured spread of the arrivals around it. An ease of exactly one interval
 * finishes before a late frame lands, and the picture stands still until it
 * does — measured on the relayed-Tailscale profile as 58.5 drawn frames a
 * second instead of 60, each missing one a visible hitch. On an even link
 * the spread is near zero and the cost stays about one frame (33 ms); on an
 * uneven one it grows to what hiding the unevenness takes. It can be
 * switched off (`setSmooth(false)`), which shows
 * each frame the moment it arrives.
 *
 * THE GLOW (a plan with a `glow` layer — the room map). Under the points the
 * stage draws one small picture, stretched over the plan: every measured
 * emitter's footprint times that emitter's live colour (the mean of the
 * pixels it lit), ADDED together, over a dim backdrop. The sum is made on
 * the CPU into one 64x36 texture — a few tens of thousands of multiply-adds
 * a frame however many emitters there are — and drawn with ONE more quad, so
 * the picture costs the same on a phone as on a desk. Points go on top with
 * MAX as before: a dot stays the colour of its LED.
 *
 * `draw` returns false, and touches nothing, when the picture has not
 * changed since the last call — an idle room costs no GPU work. */
import type { PreviewFrame } from '../api/devicePreviewWs';
import type { StagePlan } from './positions';

const VERT = `#version 300 es
in vec2 a_corner;
in vec2 a_xy;
in float a_size;
in vec3 a_color;
uniform vec2 u_scale;
uniform vec2 u_origin;
out vec2 v_uv;
out vec3 v_color;
void main() {
  v_uv = a_corner;
  v_color = a_color;
  vec2 p = a_xy + a_corner * a_size * 1.6;
  gl_Position = vec4((p + u_origin) * u_scale * vec2(1.0, -1.0) + vec2(-1.0, 1.0), 0.0, 1.0);
}`;

// The quad is 1.6 dot radii wide: a solid core out to the dot's own edge
// (0.625 of the quad), then a faint halo. An unlit pixel still shows a dim
// core, so a dark fixture keeps its shape.
const FRAG = `#version 300 es
precision mediump float;
in vec2 v_uv;
in vec3 v_color;
uniform vec3 u_floor;
out vec4 o;
void main() {
  float r = length(v_uv);
  float core = 1.0 - smoothstep(0.52, 0.64, r);
  float halo = (1.0 - smoothstep(0.55, 1.0, r)) * 0.22;
  vec3 lit = max(v_color, u_floor);
  o = vec4(lit * core + v_color * halo, 1.0);
}`;

const GLOW_VERT = `#version 300 es
in vec2 a_corner;
uniform vec2 u_scale;
uniform vec2 u_origin;
uniform vec2 u_size;
uniform vec4 u_crop;
out vec2 v_uv;
void main() {
  vec2 unit = a_corner * 0.5 + 0.5;
  v_uv = mix(u_crop.xy, u_crop.zw, unit);
  gl_Position = vec4((unit * u_size + u_origin) * u_scale * vec2(1.0, -1.0) + vec2(-1.0, 1.0), 0.0, 1.0);
}`;

// The grid is coarse (64x36 stretched over the stage). A cubic filter (four
// bilinear taps) turns its cells into soft light; plain bilinear leaves a
// visible lattice of straight seams.
const GLOW_FRAG = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform sampler2D u_tex;
uniform vec2 u_texSize;
out vec4 o;
vec4 cubic(float v) {
  vec4 n = vec4(1.0, 2.0, 3.0, 4.0) - v;
  vec4 s = n * n * n;
  float x = s.x;
  float y = s.y - 4.0 * s.x;
  float z = s.z - 4.0 * s.y + 6.0 * s.x;
  return vec4(x, y, z, 6.0 - x - y - z) / 6.0;
}
void main() {
  vec2 tc = v_uv * u_texSize - 0.5;
  vec2 f = fract(tc);
  tc -= f;
  vec4 xc = cubic(f.x);
  vec4 yc = cubic(f.y);
  vec4 c = tc.xxyy + vec2(-0.5, 1.5).xyxy;
  vec4 s = vec4(xc.xz + xc.yw, yc.xz + yc.yw);
  vec4 at = (c + vec4(xc.yw, yc.yw) / s) / u_texSize.xxyy;
  vec3 a = texture(u_tex, at.xz).rgb;
  vec3 b = texture(u_tex, at.yz).rgb;
  vec3 d = texture(u_tex, at.xw).rgb;
  vec3 e = texture(u_tex, at.yw).rgb;
  float sx = s.x / (s.x + s.y);
  float sy = s.z / (s.z + s.w);
  o = vec4(mix(mix(e, d, sx), mix(b, a, sx), sy), 1.0);
}`;

// The stage's own dark, and how much of the backdrop and the glow show.
// What an unlit pixel is drawn as, 0..255: dim on the bare stage, a little
// brighter over a glow picture, where the dim one disappears.
const UNLIT = [15, 14, 19];
const UNLIT_OVER_GLOW = [40, 37, 52];
const BG = [6, 4, 11];
const BACKDROP_TINT = [0.1, 0.085, 0.15];
const GLOW_GAIN = 0.95;
const MIN_EASE_MS = 14;
const MAX_EASE_MS = 160;
const SOLO_DIM = 40;      // of 256: what a fixture that is not soloed keeps

interface GroupState {
  first: number;
  count: number;
  cells: number;
  /** When the current ease started, and how long it runs (0 = already there). */
  t0: number;
  dur: number;
  settled: boolean;
  lastArrival: number;
  /** Smoothed gap between arrivals, and smoothed distance of a gap from it. */
  interval: number;
  spread: number;
}

function easeMs(group: GroupState): number {
  return Math.max(MIN_EASE_MS, Math.min(MAX_EASE_MS, group.interval + 2 * group.spread));
}

export class LiveStage {
  readonly mode: 'webgl' | 'canvas';
  /** Frames actually drawn since construction (the view's own drawn-fps). */
  drawn = 0;
  /** Set when a frame's cell count is not the plan's: the layout this plan
   * was built from is out of date (or the stream is the old format). The
   * frame is not drawn — its cells would land on the wrong pixels. */
  stale = false;
  private canvas: HTMLCanvasElement;
  private gl: WebGL2RenderingContext | null = null;
  private ctx: CanvasRenderingContext2D | null = null;
  private program: WebGLProgram | null = null;
  private vao: WebGLVertexArrayObject | null = null;
  private colorBuffer: WebGLBuffer | null = null;
  private staticBuffers: WebGLBuffer[] = [];
  private uScale: WebGLUniformLocation | null = null;
  private uOrigin: WebGLUniformLocation | null = null;
  private uFloor: WebGLUniformLocation | null = null;
  private plan: StagePlan | null = null;
  private groups = new Map<string, GroupState>();
  private from = new Uint8Array(0);
  private to = new Uint8Array(0);
  private cur = new Uint8Array(0);
  private out = new Uint8Array(0);
  private gain: Uint8Array | null = null;
  private glowProgram: WebGLProgram | null = null;
  private glowVao: WebGLVertexArrayObject | null = null;
  private glowCorner: WebGLBuffer | null = null;
  private glowTexture: WebGLTexture | null = null;
  private glowUniforms: Record<string, WebGLUniformLocation | null> = {};
  private glowAcc = new Float32Array(0);
  private glowRgba = new Uint8ClampedArray(0);
  private glowCanvas: HTMLCanvasElement | null = null;
  private glowImage: ImageData | null = null;
  private glowTextureCells = 0;
  private smooth = true;
  private dirty = true;
  private lost = false;
  private onLost = (e: Event) => { e.preventDefault(); this.lost = true; };
  private onRestored = () => { this.lost = false; this.initGl(); this.uploadPlan(); };

  constructor(canvas: HTMLCanvasElement, forceCanvas = false) {
    this.canvas = canvas;
    const gl = forceCanvas ? null : canvas.getContext('webgl2', {
      antialias: false, alpha: false, depth: false, stencil: false,
      preserveDrawingBuffer: false, powerPreference: 'low-power',
    });
    if (gl) {
      this.gl = gl;
      this.mode = 'webgl';
      canvas.addEventListener('webglcontextlost', this.onLost);
      canvas.addEventListener('webglcontextrestored', this.onRestored);
      this.initGl();
    } else {
      this.ctx = canvas.getContext('2d', { alpha: false });
      this.mode = 'canvas';
    }
  }

  private initGl() {
    const gl = this.gl;
    if (!gl) return;
    const compile = (type: number, source: string) => {
      const shader = gl.createShader(type)!;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      return shader;
    };
    const program = gl.createProgram()!;
    gl.attachShader(program, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAG));
    ['a_corner', 'a_xy', 'a_size', 'a_color'].forEach((name, i) => gl.bindAttribLocation(program, i, name));
    gl.linkProgram(program);
    this.program = program;
    this.uScale = gl.getUniformLocation(program, 'u_scale');
    this.uOrigin = gl.getUniformLocation(program, 'u_origin');
    this.uFloor = gl.getUniformLocation(program, 'u_floor');
    const glow = gl.createProgram()!;
    gl.attachShader(glow, compile(gl.VERTEX_SHADER, GLOW_VERT));
    gl.attachShader(glow, compile(gl.FRAGMENT_SHADER, GLOW_FRAG));
    gl.bindAttribLocation(glow, 0, 'a_corner');
    gl.linkProgram(glow);
    this.glowProgram = glow;
    this.glowUniforms = {};
    ['u_scale', 'u_origin', 'u_size', 'u_crop', 'u_tex', 'u_texSize'].forEach((name) => {
      this.glowUniforms[name] = gl.getUniformLocation(glow, name);
    });
    // its own vertex array: the points' one carries per-instance buffers a
    // plain quad must not be drawn with
    this.glowCorner = gl.createBuffer();
    this.glowVao = gl.createVertexArray();
    gl.bindVertexArray(this.glowVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.glowCorner);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
    this.glowTexture = null;
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendEquation(gl.MAX);
    gl.blendFunc(gl.ONE, gl.ONE);
    gl.clearColor(0.024, 0.016, 0.043, 1);
  }

  /** A new position table: allocate the colour arrays and upload the static
   * geometry. Colours already on screen are kept where a device keeps its
   * point count (a resize re-plans without a flash to black). */
  setPlan(plan: StagePlan) {
    const previous = this.groups;
    const previousCur = this.cur;
    this.plan = plan;
    const bytes = plan.pointCount * 3;
    this.from = new Uint8Array(bytes);
    this.to = new Uint8Array(bytes);
    this.cur = new Uint8Array(bytes);
    this.out = new Uint8Array(bytes);
    this.groups = new Map();
    for (const group of plan.groups) {
      const old = previous.get(group.visId);
      if (old && old.count === group.count) {
        const kept = previousCur.subarray(old.first * 3, (old.first + old.count) * 3);
        this.cur.set(kept, group.first * 3);
        this.to.set(kept, group.first * 3);
      }
      this.groups.set(group.visId, {
        first: group.first, count: group.count, cells: group.cells,
        t0: 0, dur: 0, settled: true,
        lastArrival: old?.lastArrival ?? 0, interval: old?.interval ?? 33,
        spread: old?.spread ?? 0,
      });
    }
    this.gain = null;
    const cells = plan.glow ? plan.glow.w * plan.glow.h : 0;
    if (this.glowAcc.length !== cells * 3) {
      this.glowAcc = new Float32Array(cells * 3);
      this.glowRgba = new Uint8ClampedArray(cells * 4);
    }
    this.uploadPlan();
    this.dirty = true;
  }

  /** The glow picture as last composed (RGBA, grid order) — for a test to
   * read; nothing draws from the returned array's identity. */
  glowPixels(): Uint8ClampedArray {
    return this.glowRgba;
  }

  /** Every emitter's footprint times its live colour, added up, over the
   * backdrop, into `glowRgba`. `colors` is what the points are drawn with. */
  private composeGlow(colors: Uint8Array) {
    const glow = this.plan!.glow!;
    const acc = this.glowAcc;
    const out = this.glowRgba;
    acc.fill(0);
    for (const emitter of glow.emitters) {
      const { points, cells, weights } = emitter;
      if (!points.length || !cells.length) continue;
      let r = 0; let g = 0; let b = 0;
      for (let k = 0; k < points.length; k++) {
        const i = points[k] * 3;
        r += colors[i]; g += colors[i + 1]; b += colors[i + 2];
      }
      if (r + g + b === 0) continue;
      const scale = GLOW_GAIN / (points.length * 255);
      r *= scale; g *= scale; b *= scale;
      for (let k = 0; k < cells.length; k++) {
        const c = cells[k] * 3;
        const w = weights[k];
        acc[c] += w * r; acc[c + 1] += w * g; acc[c + 2] += w * b;
      }
    }
    const backdrop = glow.backdrop;
    for (let c = 0, a = 0, o = 0; c < glow.w * glow.h; c++, a += 3, o += 4) {
      const base = backdrop ? backdrop[c] : 0;
      // overlapping lights ease toward full instead of clipping to white
      const r = acc[a]; const g = acc[a + 1]; const b = acc[a + 2];
      out[o] = BG[0] + base * BACKDROP_TINT[0] + (r * 320) / (255 + r);
      out[o + 1] = BG[1] + base * BACKDROP_TINT[1] + (g * 320) / (255 + g);
      out[o + 2] = BG[2] + base * BACKDROP_TINT[2] + (b * 320) / (255 + b);
      out[o + 3] = 255;
    }
  }

  private uploadPlan() {
    const gl = this.gl;
    const plan = this.plan;
    if (!gl || !plan || !this.program) return;
    this.staticBuffers.forEach((b) => gl.deleteBuffer(b));
    if (this.colorBuffer) gl.deleteBuffer(this.colorBuffer);
    if (this.vao) gl.deleteVertexArray(this.vao);
    const vao = gl.createVertexArray()!;
    gl.bindVertexArray(vao);
    const buffer = (data: BufferSource, usage: number) => {
      const b = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, data, usage);
      return b;
    };
    const corner = buffer(new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    const xy = buffer(plan.xy, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(1, 1);
    // the shader wants a radius
    const radius = new Float32Array(plan.size.length);
    for (let i = 0; i < radius.length; i++) radius[i] = plan.size[i] / 2;
    const size = buffer(radius, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(2);
    gl.vertexAttribPointer(2, 1, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(2, 1);
    this.colorBuffer = buffer(this.out, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(3);
    gl.vertexAttribPointer(3, 3, gl.UNSIGNED_BYTE, true, 0, 0);
    gl.vertexAttribDivisor(3, 1);
    gl.bindVertexArray(null);
    this.vao = vao;
    this.staticBuffers = [corner, xy, size];
  }

  setSmooth(smooth: boolean) {
    this.smooth = smooth;
  }

  /** Dim every point outside [first, first + count); null = no solo. */
  setSolo(range: { first: number; count: number } | null) {
    const plan = this.plan;
    if (!plan || !range) {
      this.gain = null;
    } else {
      const gain = new Uint8Array(plan.pointCount).fill(SOLO_DIM);
      gain.fill(255, range.first, range.first + range.count);
      this.gain = gain;
    }
    this.dirty = true;
  }

  /** One stream frame. Copies what it needs: the frame's bytes are not kept. */
  pushFrame(frame: PreviewFrame, now: number) {
    const plan = this.plan;
    const group = this.groups.get(frame.visId);
    if (!plan || !group || frame.kind !== 'full') return;
    const { rgb } = frame;
    const cells = Math.floor(rgb.length / 3);
    if (cells !== group.cells) {
      this.stale = true;
      return;
    }
    const { src } = plan;
    const { from, to, cur } = this;
    const a = group.first * 3;
    const b = (group.first + group.count) * 3;
    from.set(cur.subarray(a, b), a);
    for (let p = group.first, o = a; o < b; p++, o += 3) {
      const cell = src[p];
      if (cell < cells) {
        const i = cell * 3;
        to[o] = rgb[i];
        to[o + 1] = rgb[i + 1];
        to[o + 2] = rgb[i + 2];
      }
    }
    const gap = now - group.lastArrival;
    if (group.lastArrival && gap < 400) {
      group.spread += (Math.abs(gap - group.interval) - group.spread) * 0.2;
      group.interval += (gap - group.interval) * 0.2;
    }
    group.lastArrival = now;
    group.t0 = now;
    group.dur = this.smooth ? easeMs(group) : 0;
    group.settled = false;
  }

  /** The delay smoothing adds for the busiest device right now, in ms. */
  holdMs(): number {
    if (!this.smooth) return 0;
    let fastest = 0;
    this.groups.forEach((g) => {
      if (!g.lastArrival) return;
      const ease = easeMs(g);
      if (!fastest || ease < fastest) fastest = ease;
    });
    return fastest;
  }

  /** Everything to black (the preview stopped: nothing here is live). */
  blank() {
    this.to.fill(0);
    this.cur.fill(0);
    this.groups.forEach((g) => { g.settled = true; });
    this.dirty = true;
  }

  /** Match the canvas's pixel size to its box. Returns true when it changed. */
  resize(): boolean {
    // Soft dots gain nothing past 2x, and a 3x phone would fill 2.25 times
    // the pixels every frame.
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.round(this.canvas.clientHeight * dpr));
    if (this.canvas.width === w && this.canvas.height === h) return false;
    this.canvas.width = w;
    this.canvas.height = h;
    this.dirty = true;
    return true;
  }

  draw(now: number): boolean {
    const plan = this.plan;
    if (!plan || this.lost) return false;
    let moved = false;
    const { from, to, cur } = this;
    this.groups.forEach((g) => {
      if (g.settled) return;
      moved = true;
      const a = g.first * 3;
      const b = (g.first + g.count) * 3;
      const t = g.dur > 0 ? (now - g.t0) / g.dur : 1;
      if (t >= 1) {
        cur.set(to.subarray(a, b), a);
        g.settled = true;
      } else {
        const k = Math.max(0, Math.round(t * 256));
        for (let i = a; i < b; i++) cur[i] = from[i] + (((to[i] - from[i]) * k) >> 8);
      }
    });
    if (!moved && !this.dirty) return false;
    this.dirty = false;
    let colors = cur;
    const gain = this.gain;
    if (gain) {
      const out = this.out;
      for (let p = 0, i = 0; p < gain.length; p++, i += 3) {
        const k = gain[p];
        out[i] = (cur[i] * k) >> 8;
        out[i + 1] = (cur[i + 1] * k) >> 8;
        out[i + 2] = (cur[i + 2] * k) >> 8;
      }
      colors = out;
    }
    if (plan.glow) this.composeGlow(colors);
    if (this.gl) this.drawGl(plan, colors);
    else if (this.ctx) this.drawCanvas(plan, colors);
    this.drawn++;
    return true;
  }

  /** The stage is fitted inside the canvas, centred, keeping its shape. */
  private fit(plan: StagePlan): { scale: number; ox: number; oy: number } {
    const { width, height } = this.canvas;
    const scale = Math.min(width / plan.width, height / plan.height);
    return {
      scale, ox: (width / scale - plan.width) / 2, oy: (height / scale - plan.height) / 2,
    };
  }

  private drawGl(plan: StagePlan, colors: Uint8Array) {
    const gl = this.gl!;
    const { width, height } = this.canvas;
    const { scale, ox, oy } = this.fit(plan);
    gl.viewport(0, 0, width, height);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const glow = plan.glow;
    if (glow && this.glowProgram) {
      const u = this.glowUniforms;
      gl.activeTexture(gl.TEXTURE0);
      if (!this.glowTexture) {
        this.glowTexture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, this.glowTexture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        this.glowTextureCells = 0;
      } else {
        gl.bindTexture(gl.TEXTURE_2D, this.glowTexture);
      }
      if (this.glowTextureCells !== glow.w * glow.h) {
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, glow.w, glow.h, 0, gl.RGBA, gl.UNSIGNED_BYTE,
          this.glowRgba);
        this.glowTextureCells = glow.w * glow.h;
      } else {
        gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, glow.w, glow.h, gl.RGBA, gl.UNSIGNED_BYTE,
          this.glowRgba);
      }
      gl.useProgram(this.glowProgram);
      gl.uniform2f(u.u_scale, (2 * scale) / width, (2 * scale) / height);
      gl.uniform2f(u.u_origin, ox, oy);
      gl.uniform2f(u.u_size, plan.width, plan.height);
      gl.uniform4f(u.u_crop, glow.crop[0], glow.crop[1], glow.crop[2], glow.crop[3]);
      gl.uniform1i(u.u_tex, 0);
      gl.uniform2f(u.u_texSize, glow.w, glow.h);
      gl.bindVertexArray(this.glowVao);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    if (!plan.pointCount) return;
    gl.useProgram(this.program);
    gl.uniform2f(this.uScale, (2 * scale) / width, (2 * scale) / height);
    gl.uniform2f(this.uOrigin, ox, oy);
    const unlit = glow ? UNLIT_OVER_GLOW : UNLIT;
    gl.uniform3f(this.uFloor, unlit[0] / 255, unlit[1] / 255, unlit[2] / 255);
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.colorBuffer);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, colors);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, plan.pointCount);
    gl.bindVertexArray(null);
  }

  private drawCanvas(plan: StagePlan, colors: Uint8Array) {
    const ctx = this.ctx!;
    const { scale, ox, oy } = this.fit(plan);
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = '#06040b';
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    const glow = plan.glow;
    if (glow && typeof document !== 'undefined') {
      if (!this.glowCanvas) this.glowCanvas = document.createElement('canvas');
      const small = this.glowCanvas;
      if (small.width !== glow.w || small.height !== glow.h) {
        small.width = glow.w;
        small.height = glow.h;
      }
      const smallCtx = small.getContext('2d');
      if (smallCtx) {
        if (!this.glowImage || this.glowImage.data !== this.glowRgba) {
          this.glowImage = new ImageData(this.glowRgba, glow.w, glow.h);
        }
        smallCtx.putImageData(this.glowImage, 0, 0);
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(small,
          glow.crop[0] * glow.w, glow.crop[1] * glow.h,
          (glow.crop[2] - glow.crop[0]) * glow.w, (glow.crop[3] - glow.crop[1]) * glow.h,
          ox * scale, oy * scale, plan.width * scale, plan.height * scale);
      }
    }
    ctx.globalCompositeOperation = 'lighten';
    const unlit = glow ? UNLIT_OVER_GLOW : UNLIT;
    const { xy, size } = plan;
    for (let p = 0, i = 0; p < plan.pointCount; p++, i += 3) {
      if (size[p] <= 0) continue;
      const d = size[p] * scale;
      const r = Math.max(colors[i], unlit[0]);
      const g = Math.max(colors[i + 1], unlit[1]);
      const b = Math.max(colors[i + 2], unlit[2]);
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      const x = (xy[p * 2] + ox) * scale;
      const y = (xy[p * 2 + 1] + oy) * scale;
      if (d < 5) {
        ctx.fillRect(x - d / 2, y - d / 2, d, d);
      } else {
        ctx.beginPath();
        ctx.arc(x, y, d / 2, 0, 6.2832);
        ctx.fill();
      }
    }
  }

  dispose() {
    this.canvas.removeEventListener('webglcontextlost', this.onLost);
    this.canvas.removeEventListener('webglcontextrestored', this.onRestored);
    const gl = this.gl;
    if (gl) {
      this.staticBuffers.forEach((b) => gl.deleteBuffer(b));
      if (this.colorBuffer) gl.deleteBuffer(this.colorBuffer);
      if (this.vao) gl.deleteVertexArray(this.vao);
      if (this.program) gl.deleteProgram(this.program);
      if (this.glowProgram) gl.deleteProgram(this.glowProgram);
      if (this.glowVao) gl.deleteVertexArray(this.glowVao);
      if (this.glowCorner) gl.deleteBuffer(this.glowCorner);
      if (this.glowTexture) gl.deleteTexture(this.glowTexture);
    }
    this.plan = null;
  }
}
