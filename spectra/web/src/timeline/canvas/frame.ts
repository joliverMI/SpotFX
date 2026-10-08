/** Layered-canvas contracts — the reuse surface for the future debug and
 * ai_triggers migrations. A layer is a pure draw over a CanvasFrame. */
import type {
  AudioShapeData, AudioShapeMeta, EventOption, LibrosaAnalysis, MarkType, MusicTrigger,
} from '../types';
import type { DisplaySeq, DropRails, Handle } from '../dropSequences';
import type { Ghost, SnapGuide } from '../dropEdit';

export interface Win {
  startMs: number;
  endMs: number;
}

export interface ViewState {
  filters: { total: boolean; bass: boolean; mid: boolean; high: boolean; marks: boolean };
  avgFilters: { total: boolean; bass: boolean; mid: boolean; high: boolean };
  markFilters: Record<MarkType, boolean>;
  librosaFilters: {
    sections: boolean; beats: boolean; onsets: boolean; harmonic: boolean;
    bass: boolean; snare: boolean; mfcc: boolean;
  };
  scales: { total: number; bass: number; mid: number; high: number };
  scaleOverall: number;
  offsetMs: number;         // shape offset — data shifts, triggers/playhead don't
  librosaOffsetMs: number;
  triggerOffsetMs: number;  // shift-all preview
  maxRms: number | null;    // pinned Y max
  intensityMode: IntensityBgMode;
  advanced: boolean;
}

export type IntensityBgMode = 'off' | 'total' | 'bass' | 'section' | 'triggers';
export const INTENSITY_MODES: IntensityBgMode[] = ['off', 'total', 'bass', 'section', 'triggers'];
export const INTENSITY_MODE_LABELS: Record<IntensityBgMode, string> = {
  off: 'Intensity', total: 'Total RMS', bass: 'Bass RMS',
  section: 'Section energy', triggers: 'Trigger intensity',
};

export interface LayerDataBag {
  shape: AudioShapeData | null;
  averages: { rms_total: number[]; rms_low: number[]; rms_mid: number[]; rms_high: number[] } | null;
  meta: AudioShapeMeta | null;
  librosa: LibrosaAnalysis | null;
  mfccDistances: number[] | null;
  triggers: MusicTrigger[];
  events: EventOption[];
  calibrationTargetsMs: number[];
  /** transient drag ghost; delta vs baseIntensity also shifts other selected circles */
  draggingIntensity: { triggerId: string; intensity: number; baseIntensity: number } | null;
  selectedIds: string[];
  hoverTriggerId: string | null;

  // ── Debug-page extensions (optional — builder layers ignore them) ─────────
  /** live xcorr capture, already shifted into saved-shape time (mirrored down) */
  live?: LiveShapeLayerData | null;
  /** matcher's-view diff series, normalized ±1 (pos = live louder) */
  diff?: DiffSeries | null;
  /** confirmed mismatch spikes + their recovery windows (magenta) */
  spikes?: SpikeMarker[];
  /** per-window xcorr outcome brackets */
  xcorrWindows?: XcorrWinMarker[];
  /** rolling-R monitor history (song-time x, r y; null r = neutral gap) */
  monitorHistory?: MonitorPoint[];
  /** AI-triggers suggestion markers (draggable; index = suggestion index) */
  aiMarkers?: AiMarker[];
  /** planned analysed events (debug page): scene changes + analysed flares,
   *  already placed where they will fire against this canvas's playhead */
  plannedEvents?: PlannedEventMarker[];
  /** THE DROP-SEQUENCE LAYER (Timeline page only; ./dropSeqLayer.ts): the
   *  song's charge/lull/drop sequences, the snap rails drawn under them,
   *  and what is selected/hovered. Absent = the layer draws nothing and
   *  reserves no rail band. */
  dropSeq?: DropSeqLayerData | null;
  /** THE LIGHT SHOW's High/Low Trigger markers (Timeline page only;
   *  ./lightShowLayer.ts, ../lightShowMarkers.ts) — shown whether or not
   *  anything is armed on them; empty/absent = the layer draws nothing. */
  lightShow?: import('../lightShowMarkers').LightShowCueMarker[];
  /** A Light Show flag being dragged directly on the canvas right now
   *  (hooks/useLightShowDrag.ts) — the live ghost position, drawn in place
   *  of the flag's stored ms until the drag ends and it saves. Null/absent
   *  = nothing is being dragged on the canvas. */
  lightShowDrag?: { level: 'high' | 'low'; ms: number } | null;
}

/** What a hand on the drop-sequence layer is doing RIGHT NOW (phase 4) —
 * read by the layer every frame from a ref, so a drag never costs a React
 * render: the ghost being moved, the snap target it is on, and the add-a-
 * drop preview. */
export interface DropLive {
  ghost: Ghost | null;
  guide: SnapGuide | null;
  /** "＋ Add a drop" is armed: where a click would put the drop */
  addAt: SnapGuide | null;
}

export interface DropSeqLayerData {
  seqs: DisplaySeq[];
  rails: DropRails | null;
  selectedKey: string | null;
  /** the selected handle (C/L/D, or the one last grabbed) — ringed */
  selectedHandle?: Handle | null;
  /** "＋ Add a drop" is armed */
  adding?: boolean;
  /** the live drag/add state (a ref the page mutates) */
  live?: { current: DropLive } | null;
  hover: { key: string; handle: Handle } | null;
  /** where the recording starts (song ms) — before it is "not captured" */
  capturedFromMs: number | null;
  /** one beat, ms (the protected two-bar tail after a drop is 8 of them) */
  beatMs: number;
}

export interface PlannedEventMarker {
  ms: number;
  kind: 'scene' | 'flare';
  /** rank among the song's analysed transitions (1 = strongest) of rankOf;
   *  null/absent = unranked, drawn exactly as before ranks existed */
  rank?: number | null;
  rankOf?: number | null;
}

export interface AiMarker {
  ms: number;
  /** state color: manual blue / approved green / rejected faded red / pending white */
  color: string;
  eventColor?: string | null;
  highlighted?: boolean;
}

export interface CanvasFrame {
  ctx: CanvasRenderingContext2D;
  w: number;       // CSS px (ctx pre-scaled by dpr)
  h: number;
  mainH: number;   // h minus the snap-rail band and the beat-strip area
  /** the drop-sequence snap rails' band, directly under the main area
   *  (0 when the layer is off); the beat strips start below it */
  railH: number;
  stripH: number;  // height of one strip incl. separator
  stripCount: number;
  win: Win;
  timeToX(ms: number): number;
  xToTime(x: number): number;
  nowMs: number | null;
  data: LayerDataBag;
  view: ViewState;
}

export type Hit =
  | { kind: 'trigger-intensity'; triggerId: string }
  | { kind: 'trigger-triangle'; triggerId: string }
  | { kind: 'ai-marker'; index: number }
  | { kind: 'beat'; beatMs: number; values: Record<string, number> }
  | { kind: 'drop-seq'; key: string; handle: Handle; chip?: boolean }
  | { kind: 'light-show-flag'; level: 'high' | 'low'; ms: number }
  | null;

export interface CanvasLayer {
  id: string;
  z: number; // ascending draw order; hit-testing consults descending
  visible(frame: CanvasFrame): boolean;
  draw(frame: CanvasFrame): void;
  hitTest?(x: number, y: number, frame: CanvasFrame): Hit;
  /** Hover text for a spot no layer hit-tests — read-only markers name
   *  themselves this way without ever stealing a click from a trigger. */
  tooltipAt?(x: number, y: number, frame: CanvasFrame): string | null;
}

export const BEAT_STRIP_H = 21;

/** The drop-sequence snap rails: bass spikes (18 px) over beats (16 px),
 * plus a 2 px gap — plan.html's Timeline mock. */
export const SNAP_RAIL_H = 36;

/** How tall the snap-rail band is for this data: SNAP_RAIL_H while the
 * drop-sequence layer has rails to draw, else 0 — so a canvas without the
 * layer (the debug page) keeps its geometry exactly. */
export function snapRailHFor(data: Pick<LayerDataBag, 'dropSeq'>): number {
  return data.dropSeq?.rails ? SNAP_RAIL_H : 0;
}

export function stripCountFor(data: Pick<LayerDataBag, 'librosa' | 'mfccDistances'>,
                              lib: ViewState['librosaFilters']): number {
  if (!data.librosa?.beats?.length) return 0;
  let n = 5; // rms_total, rms_bass, onset, bass_onset, harmonic
  const hasSnare = data.librosa.beats.some((b) => (b.snare_onset_score ?? 0) > 0);
  if (lib.snare && hasSnare) n += 1;
  if (lib.mfcc) n += 1;
  return n;
}

// ── Debug layer data shapes (rendered by src/debug/layers.ts) ────────────────
export interface LiveShapeLayerData {
  timestamps_ms: number[];
  rms_total: number[];
  rms_low: number[];
  rms_mid: number[];
  rms_high: number[];
}
/** Pos/neg halves of the matcher's-view diff, both ≥0 on the same time grid. */
export interface DiffSeries {
  timestamps_ms: number[];
  pos: number[];
  neg: number[];
}
export interface SpikeMarker {
  spike_ms: number;
  win_start: number;
  win_end: number;
  strength: number;
}
export interface XcorrWinMarker {
  win_start: number;
  win_end: number;
  winner?: string;
  failed?: boolean;
  new_offset_ms?: number | null;
  new_r?: number | null;
}
export interface MonitorPoint {
  ms: number;
  r: number | null;
}
