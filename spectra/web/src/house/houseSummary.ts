/** House lighting's words — the Mode chip and the House page's "Now" panel
 * read the SAME sentences from here (no DOM, so
 * scripts/check_house_summary.mjs can drive it directly). */
import type { HouseMode, LightingStatus, SeamFixture } from './types';

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

/** One line per fixture the seam is doing something to, in plain words —
 * the House page's Home Assistant card. Only fixtures that differ from
 * "streamed and on" are named; a fixture held on at the owned brightness is
 * the normal case and stays quiet. */
export function fixtureLine(f: SeamFixture): string | null {
  const name = f.name || f.device;
  const outcome = f.applied && f.applied.outcome !== 'landed' && f.applied.outcome !== 'sent'
    && f.applied.outcome !== 'withheld'
    ? ` — ${f.applied.outcome}${f.applied.detail ? `: ${f.applied.detail}` : ''}` : '';
  if (f.target === 'lent') return `${name}: lent — ${f.why ?? 'no stream'}${outcome}`;
  if (f.target === 'off') return `${name}: switched off — no stream${outcome}`;
  if (f.target === 'on') return outcome ? `${name}: on${outcome}` : null;
  if (f.override?.power === 'off') return `${name}: switched off (recorded, not acted on)`;
  if (f.override?.lent_to) return `${name}: lent to ${f.override.lent_to} (recorded, not acted on)`;
  return null;
}

/** The Home Assistant card's lines: TV strip, media, voice, and anything
 * the seam is doing to a fixture. */
export function seamLines(l: LightingStatus | undefined): string[] {
  if (!l) return [];
  const out: string[] = [];
  if (l.seam_active === false && l.seam_reason) {
    out.push(`Recorded, not acted on — ${l.seam_reason}.`);
  }
  const strip = l.tv_strip;
  if (strip && strip.devices.length) {
    out.push(strip.owner === 'spectra'
      ? `TV strip: Spectra drives it${l.tv_music === true ? ' (TV Music on)' : ''}.`
      : `TV strip: ${strip.owner} — ${strip.why ?? 'lent'}.`);
  }
  const m = l.media;
  if (m?.active) {
    out.push(`Media: ${m.source ?? 'a source'} is ${m.state}`
      + (m.mode ? ` → ${m.mode}.` : ` — no mode answers to ${m.words.map((w) => `"${w}"`).join(' or ')}, so ${l.clock_mode?.name ?? 'the clock\'s mode'} stays.`));
  }
  const v = l.voice;
  if (v && v.state !== 'idle') {
    out.push(`Voice: ${v.state} on ${v.fixtures.join(', ') || 'nothing'}`
      + (v.skipped.length ? ` (skipped ${v.skipped.map((s) => `${s.fixture}: ${s.reason}`).join('; ')})` : '') + '.');
  }
  for (const f of l.fixtures_seam?.fixtures ?? []) {
    const line = fixtureLine(f);
    if (line) out.push(line);
  }
  for (const c of l.fixtures_seam?.corrections ?? []) {
    out.push(`Corrected ${c.device}: found on=${c.found.on} brightness=${c.found.bri} — something else wrote it (${c.outcome}).`);
  }
  for (const [d, r] of Object.entries(l.fixtures_seam?.rechecks ?? {})) {
    if (r.state === 'found') out.push(`Recheck: ${d} answered after ${r.after_s ?? '?'} s${r.moved ? ' (it had moved)' : ''}.`);
    else if (r.state === 'not_found') out.push(`Recheck: ${d} did not answer — ${r.reason ?? 'no answer'}.`);
    else if (r.state === 'rechecking') out.push(`Recheck: looking for ${d}…`);
  }
  return out;
}
