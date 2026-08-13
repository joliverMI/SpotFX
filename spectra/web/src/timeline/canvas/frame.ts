/** Layered-canvas contracts — the reuse surface for the future debug and
 * ai_triggers migrations. A layer is a pure draw over a CanvasFrame. */
import type {
  AudioShapeData, AudioShapeMeta, EventOption, LibrosaAnalysis, MarkType, MusicTrigger,
} from '../types';

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
  mainH: number;   // h minus beat-strip area
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
  | null;

export interface CanvasLayer {
  id: string;
  z: number; // ascending draw order; hit-testing consults descending
  visible(frame: CanvasFrame): boolean;
  draw(frame: CanvasFrame): void;
  hitTest?(x: number, y: number, frame: CanvasFrame): Hit;
}

export const BEAT_STRIP_H = 21;

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
