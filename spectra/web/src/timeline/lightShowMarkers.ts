/** THE LIGHT SHOW's High/Low Trigger markers, as drawn on the Timeline's
 * audio-shape canvas and full-song strip — his ask, verbatim: "I also want
 * to see a marker showing where the light show triggers are, even if they
 * aren't active."
 *
 * A cue's POSITION (spectra/services/show_cues.py, served as
 * AnalysedPlan.show_cues — see ../debug/plannedEvents.ts) is deterministic
 * per song and exists whether or not anything is armed on it — that is
 * what "even if they aren't active" means, and why these markers never
 * disappear. Whether something is actually ARMED to fire there
 * (spectra/services/show_arms.py, ArmsStatus) is live room state, checked
 * here the same way show_arms.py's own `_applies_to_song` does: an arm
 * with no `song_uri` carries to every song, one with a `song_uri` applies
 * only to that song.
 *
 * Pure, DOM-free, so scripts/check_timeline_light_show_markers.mjs can
 * drive it with no browser. */
import type { ArmsStatus, ShowArm, SongCues } from '../lightshow/types';
import { mmss } from '../lightshow/showSummary';

export interface LightShowCueMarker {
  level: 'high' | 'low';
  ms: number;
  /** something is currently armed to fire on this cue (for this song) */
  armed: boolean;
  /** the armed thing(s)' own labels, for the hover card */
  armedLabels: string[];
  title: string;
}

/** Warm white ▲ High, indigo ▼ Low — the same colours ShowCueBar.tsx's
 * flags already use, kept off the charge/lull/drop phase colours
 * (timeline/dropSequences.ts PHASE_COLOR) so a marker never reads as a
 * phase. One definition, so the strip, the canvas layer and the legend
 * can never quietly drift apart. */
export const LIGHT_SHOW_COLOR = { high: '#f5f5f4', low: '#818cf8' } as const;

function cueSourceWords(source: string): string {
  return source === 'moved' ? 'moved by him'
    : source === 'drop_mark' ? 'his own drop mark' : 'automatic';
}

/** Mirrors show_arms.py's own `_applies_to_song`: an arm with no
 * `song_uri` carries to every song; one with a `song_uri` applies only
 * to that song. */
export function armAppliesToCue(arm: ShowArm, level: 'high' | 'low', uri: string | null): boolean {
  return arm.on === level && (arm.song_uri === null || arm.song_uri === uri);
}

/** Armed sets whose trigger is the next SCENE CHANGE — no fixed song
 * position (it fires on whichever scene change happens next), so these
 * are never drawn as a position marker; a caller surfaces them in words
 * instead (the Light Show legend). */
export function sceneChangeArms(arms: ArmsStatus | null | undefined, uri: string | null): ShowArm[] {
  return (arms?.armed ?? []).filter((a) => a.on === 'scene_change' && (a.song_uri === null || a.song_uri === uri));
}

/** One marker per cue the song actually has (0, 1 or 2 — a song can lack
 * either). `uri` is the song currently shown on the Timeline, which may
 * not be the one playing. */
export function lightShowCueMarkers(
  cues: SongCues | null | undefined,
  arms: ArmsStatus | null | undefined,
  uri: string | null,
): LightShowCueMarker[] {
  const out: LightShowCueMarker[] = [];
  for (const level of ['high', 'low'] as const) {
    const cue = cues?.[level];
    if (!cue) continue;
    const matching = (arms?.armed ?? []).filter((a) => armAppliesToCue(a, level, uri));
    const armed = matching.length > 0;
    const name = level === 'high' ? 'High Trigger' : 'Low Trigger';
    const when = `${mmss(cue.timestamp_ms)} (${cueSourceWords(cue.source)})`;
    const armedWords = armed
      ? `armed: ${matching.map((a) => a.label || 'an action').join(', ')} — fires here`
      : 'nothing armed on it';
    out.push({
      level, ms: cue.timestamp_ms, armed,
      armedLabels: matching.map((a) => a.label || 'an action'),
      title: `${name} · ${when} · ${armedWords}`,
    });
  }
  return out;
}
