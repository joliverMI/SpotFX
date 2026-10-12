/** A THEMATIC TRANSITION PROGRAM's named stages on a preview ruler
 * (fx/effects/transition_program.stages, placed in seconds by
 * spectra/services/transition_preview._program_on_ruler). The server
 * computes every second; this only turns them into ruler bands — the
 * stage that carries the payoff (the one the trigger mark leads into) is
 * accented, the others muted. */
import type { RulerBand } from './PreviewRuler';

export interface ProgramStage {
  label: string;
  from_s: number;
  to_s: number;
  anchor: boolean;
}

export interface PreviewProgram {
  name: string;
  out_type: string;
  in_type: string;
  stages: ProgramStage[];
}

export const PROGRAM_WORDS: Record<string, string> = {
  infall: 'Infall',
  eruption: 'Eruption',
  lensing: 'Lensing',
  fountain: 'Fountain',
  flame_lick: 'Flame Lick',
  ignition: 'Ignition',
  shoal_break: 'Shoal Break',
  shoaling: 'Shoaling',
  unravel: 'Unravel',
};

export function programBands(program: PreviewProgram | null | undefined,
                             accent = true): RulerBand[] {
  if (!program) return [];
  return program.stages.map((s) => ({
    from_s: s.from_s,
    to_s: s.to_s,
    label: s.label,
    tone: accent && s.anchor ? 'accent' : 'muted',
  }));
}
