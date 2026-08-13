/**
 * summarizeAction() — TS port of trigger_engine._describe_action so collapsed
 * card summaries match the preview strings SpotFX shows on Now Playing.
 */
import type { Action, ActionType, MusicEvent } from './events';
import { SCENE_GROUP_COLOR_REF, CURRENT_COLOR_GROUP_REF } from './events';

/** Everything the Add Action dialog can create: the real action types plus
 * UI-only pseudo-types that map to a specialized factory. */
export type AddableActionType = ActionType | 'light_mode_chooser';

export interface SummaryContext {
  /** id → event, for resolving event_ref names */
  events?: Record<string, MusicEvent>;
  /** color-set card id → name, for set_color */
  colorSetNames?: Record<string, string>;
}

export const ACTION_ICONS: Record<AddableActionType, string> = {
  event_ref: '🔗',
  ledfx_scene: '🎬',
  ledfx_ambient: '🌈',
  ledfx_ambient_color: '🎨',
  ledfx_global_transition: '⏱️',
  ledfx_effect_param: '🎛️',
  morph_step: '🧬',
  set_color: '🖌️',
  morph_color: '🎡',
  scene_morph: '🎞️',
  device_settings: '⚙️',
  brightness: '🔆',
  random_group: '🎲',
  sequence_group: '➡️',
  parallel_group: '⫴',
  intensity_chooser: '⚡',
  light_mode_chooser: '🌗',
};

export const ACTION_TYPE_LABELS: Record<AddableActionType, string> = {
  event_ref: 'Event Reference',
  ledfx_scene: 'LedFX Scene',
  ledfx_ambient: 'Ambient',
  ledfx_ambient_color: 'Complementary Color',
  ledfx_global_transition: 'Global Transition',
  ledfx_effect_param: 'Effect Params',
  morph_step: 'Morph Step',
  set_color: 'Set Color',
  morph_color: 'Morph Color',
  scene_morph: 'Scene Morph',
  device_settings: 'Device Settings',
  brightness: 'Brightness',
  random_group: 'Random Group',
  sequence_group: 'Sequence',
  parallel_group: 'Parallel',
  intensity_chooser: 'Intensity Chooser',
  light_mode_chooser: 'Light Mode Chooser',
};

/** UI-only alias: the Light Mode Chooser is an intensity_chooser with
 * source 'display_mode' under the hood, but gets its own Add entry / label. */
export const addableKeyOf = (a: Action): AddableActionType =>
  a.type === 'intensity_chooser' && a.source === 'display_mode'
    ? 'light_mode_chooser' : a.type;

/** Cheap deep scan: does this action contain any value binding? */
export function hasBindingDeep(action: Action): boolean {
  return JSON.stringify(action).includes('"bind":"signal"');
}

export function summarizeAction(action: Action, ctx: SummaryContext = {}): string {
  switch (action.type) {
    case 'ledfx_scene':
      return action.scene_id;
    case 'ledfx_ambient': {
      const parts: string[] = [];
      if (action.color) parts.push(action.color);
      if (action.brightness != null) parts.push(`${Math.round(action.brightness * 100)}% bright`);
      return 'Ambient ' + (parts.length ? parts.join(', ') : '–');
    }
    case 'ledfx_ambient_color':
      return 'Complementary color';
    case 'ledfx_global_transition':
      return `Transition ${action.transition_time}s`;
    case 'ledfx_effect_param': {
      const scope = action.virtual_id || action.category || 'all';
      const names = action.params.map((p) => p.param_label).filter(Boolean);
      const body = names.length ? names.join(', ') : 'params';
      return `${body} (${scope})${hasBindingDeep(action) ? ' ⚡' : ''}`;
    }
    case 'morph_step': {
      const n = action.targets.length;
      const aspects = [...new Set(action.targets.map((t) => t.aspect))].sort();
      const body = aspects.length ? aspects.join(', ') : 'no targets';
      const head = action.name ? `Morph “${action.name}”` : `Morph ${n}×`;
      return `${head} (${body})${hasBindingDeep(action) ? ' ⚡' : ''}`;
    }
    case 'set_color': {
      const name = action.ref_id === SCENE_GROUP_COLOR_REF
        ? "Scene Group's colors"
        : action.ref_id === CURRENT_COLOR_GROUP_REF
          ? 'current group'
          : ctx.colorSetNames?.[action.ref_id] ?? '?';
      return `Color → ${name}${hasBindingDeep(action) ? ' ⚡' : ''}`;
    }
    case 'morph_color': {
      const sign = action.direction === 'backward' ? '-' : '+';
      const bits = [...action.scope.categories, ...action.scope.virtual_ids, ...action.scope.roles];
      const where = bits.length ? ` (${bits.join(', ')})` : '';
      const deg = typeof action.degrees === 'number' ? `${action.degrees}°`
        : action.degrees.signal === 'random' ? '🎲°' : '⚡°';
      return `Rotate ${sign}${deg}${where}${hasBindingDeep(action) ? ' ⚡' : ''}`;
    }
    case 'scene_morph': {
      const sign = action.direction === 'backward' ? '-' : '+';
      return `Scene morph ${sign}${action.advance}`;
    }
    case 'device_settings':
      return `Device settings (${action.targets.length}×)`;
    case 'brightness': {
      const bits: string[] = [];
      const fmt = (v: number | { signal?: string } | null): string =>
        typeof v === 'number' ? `${v}` : v?.signal === 'random' ? '🎲' : '⚡';
      for (const [label, mode, value, nudge] of [
        ['bright', action.brightness_mode, action.brightness_value, action.brightness_nudge],
        ['bg', action.bg_mode, action.bg_value, action.bg_nudge],
      ] as const) {
        if (mode === 'absolute') bits.push(`${label} ×${fmt(value)}`);
        else if (mode === 'nudge') {
          const amt = nudge?.amount ?? 0;
          bits.push(typeof amt === 'number'
            ? `${label} ${nudge?.random_sign ? '±' + Math.abs(amt) : (amt >= 0 ? '+' : '') + amt}`
            : `${label} ±${fmt(amt)}`);
        }
      }
      return `Brightness ${bits.length ? bits.join(', ') : '(keep)'}${hasBindingDeep(action) ? ' ⚡' : ''}`;
    }
    case 'event_ref': {
      const sub = ctx.events?.[action.event_id];
      return sub ? `→ ${sub.name}` : '→ (event ref)';
    }
    case 'random_group':
      return `🎲 1 of ${action.options.length}`;
    case 'sequence_group':
      return action.timing === 'beats'
        ? `🥁 Beat seq · ${action.children.length} steps`
        : `➡️ Seq · ${action.children.length} steps`;
    case 'parallel_group':
      return `⫴ ${action.children.length} lanes`;
    case 'intensity_chooser':
      if (action.source === 'display_mode') {
        const names = action.lanes.map(
          (l) => l.name || (l.mode === 'dark' ? '🌙' : l.mode === 'light' ? '☀️' : '?'));
        return `🌗 ${names.join(' / ')}`;
      }
      return `⚡ 1 of ${action.lanes.length} lanes`;
  }
}
