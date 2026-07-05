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

// ── Debug / ai_triggers layer data contracts (interfaces only — the layers
// themselves are implemented when those pages migrate) ──────────────────────
export interface LiveShapeLayerData {
  timestamps_ms: number[];
  rms_total: number[];
  rms_low: number[];
  rms_mid: number[];
  rms_high: number[];
}
export interface CustomMarker {
  ms: number;
  color: string;
  shape: 'triangle' | 'diamond';
  highlighted?: boolean;
}
export interface AnchorCandidate { ms: number; score: number; }
export interface XcorrWindowMarker { startMs: number; endMs: number; label?: string; }
export interface MismatchSpike { ms: number; magnitude: number; }
