/** House lighting's words — the Mode chip and the House page's "Now" panel
 * read the SAME sentences from here (no DOM, so
 * scripts/check_house_summary.mjs can drive it directly). */
import type { HouseMode, LightingStatus } from './types';

export function sourceWord(source: string | null | undefined): string {
  switch (source) {
    case 'ha': return 'Home Assistant';
    case 'ha_manual': return 'the Home Assistant dashboard';
    case 'sonic': return 'Sonic';
    case 'spectra': return 'you';
    case null: case undefined: case '': return 'nobody yet';
    default: return source;
  }
}

export type ChipTone = 'on' | 'music' | 'idle' | 'off';

/** The Mode chip, first in the top bar on every page. */
export function chipLine(l: LightingStatus | undefined): { text: string; tone: ChipTone; title: string } {
  if (!l || l.error) {
    return { text: 'Mode: …', tone: 'off', title: 'House lighting status unavailable' };
  }
  if (!l.mode) {
    const ha = l.ha_value ? ` Home Assistant says "${l.ha_value}"${l.ha_mapped_mode ? '' : ' (no mode answers to it)'}.` : '';
    return { text: 'Mode: none', tone: 'off', title: `No house mode is set.${ha}` };
  }
  const who = l.source === 'ha' ? ' · HA' : l.manual ? ' · manual' : '';
  const base = `Mode: ${l.mode.name}${who}`;
  const title = `${l.mode.name}, set by ${sourceWord(l.source)}. ${phaseLine(l)}`;
  switch (l.phase) {
    case 'resting': return { text: base, tone: 'on', title };
    case 'music': return { text: `${base} · ♪`, tone: 'music', title };
    case 'standby': return { text: `${base} · paused`, tone: 'idle', title };
    default: return { text: `${base} · not applied`, tone: 'idle', title };
  }
}

/** One plain sentence: what the house layer is doing right now. */
export function phaseLine(l: LightingStatus | undefined): string {
  if (!l) return '';
  if (!l.mode) return 'No house mode is set — the room behaves as it always has.';
  switch (l.phase) {
    case 'resting':
      return `Resting — ${l.mode.name}'s look is on the room.`;
    case 'music':
      if (l.music?.returns_in_s != null) {
        return `Music stopped — back to ${l.mode.name} in ${Math.ceil(l.music.returns_in_s)} s `
          + '(the show keeps the room until then, so a pause or a track gap never flaps).';
      }
      return `Music is playing — the show has the room. It returns to ${l.mode.name} after the music stops.`;
    case 'standby':
      return `Paused — ${l.reason}. ${l.mode.name} comes back when that ends.`;
    default:
      return `Not applied — ${l.reason}. It applies when SPECTRA holds the room.`;
  }
}

export function manualLine(l: LightingStatus | undefined): string | null {
  if (!l?.mode || !l.manual) return null;
  return l.manual_until
    ? `Picked by hand — holds until ${l.manual_until}.`
    : 'Picked by hand — holds until Home Assistant\'s lighting mode next changes.';
}

export function blankMode(name: string): HouseMode {
  return {
    name, ha_aliases: [], scenes: [], color_sets: [],
    flow: { scene_every_min: 45, journey_deg_per_min: 15, intensity: 0.25 },
    fixtures: [], hue: [], music: 'show', music_hue: 'hold',
    transitions: { clock_glide_s: 90, button_glide_s: 5, music_debounce_s: 60, music_return_glide_s: 20 },
    notes: '',
  };
}

/** An sRGB approximation of a colour temperature, for a swatch only
 * (Tanner Helland's fit). Never sent to a bulb — the bulb gets mirek. */
export function kelvinToHex(kelvin: number): string {
  const t = Math.max(1000, Math.min(40000, kelvin)) / 100;
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
  const r = t <= 66 ? 255 : 329.698727446 * Math.pow(t - 60, -0.1332047592);
  const g = t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661
    : 288.1221695283 * Math.pow(t - 60, -0.0755148492);
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  return `#${[r, g, b].map((v) => clamp(v).toString(16).padStart(2, '0')).join('')}`;
}

export const MUSIC_WORDS: Record<string, string> = {
  show: 'the full show',
  calm: 'keep this look (flares only)',
  ignore: 'no show at all',
};

export const MUSIC_HUE_WORDS: Record<string, string> = {
  hold: 'stay held at this look',
  join: 'join the show',
  room: 'follow the Hue Hold switch',
};
