/**
 * summarizeAction() — TS port of trigger_engine._describe_action so collapsed
 * card summaries match the preview strings SpotFX shows on Now Playing.
 */
import type { Action, MusicEvent } from './events';

export interface SummaryContext {
  /** id → event, for resolving event_ref names */
  events?: Record<string, MusicEvent>;
  /** color-set card id → name, for set_color */
  colorSetNames?: Record<string, string>;
}

export const ACTION_ICONS: Record<Action['type'], string> = {
  event_ref: '🔗',
  ledfx_scene: '🎬',
  ledfx_ambient: '🌈',
  ledfx_ambient_color: '🎨',
  ledfx_global_transition: '⏱️',
  ledfx_effect_param: '🎛️',
  morph_step: '🧬',
  set_color: '🖌️',
  morph_color: '🎡',
  device_settings: '⚙️',
  random_group: '🎲',
  sequence_group: '➡️',
  parallel_group: '⫴',
};

export const ACTION_TYPE_LABELS: Record<Action['type'], string> = {
  event_ref: 'Event Reference',
  ledfx_scene: 'LedFX Scene',
  ledfx_ambient: 'Ambient',
  ledfx_ambient_color: 'Complementary Color',
  ledfx_global_transition: 'Global Transition',
  ledfx_effect_param: 'Effect Params',
  morph_step: 'Morph Step',
  set_color: 'Set Color',
  morph_color: 'Morph Color',
  device_settings: 'Device Settings',
  random_group: 'Random Group',
  sequence_group: 'Sequence',
  parallel_group: 'Parallel',
};

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
      const name = ctx.colorSetNames?.[action.ref_id] ?? '?';
      return `Color → ${name}${hasBindingDeep(action) ? ' ⚡' : ''}`;
    }
    case 'morph_color': {
      const sign = action.direction === 'backward' ? '-' : '+';
      const bits = [...action.scope.categories, ...action.scope.virtual_ids, ...action.scope.roles];
      const where = bits.length ? ` (${bits.join(', ')})` : '';
      return `Rotate ${sign}${action.degrees}°${where}${hasBindingDeep(action) ? ' ⚡' : ''}`;
    }
    case 'device_settings':
      return `Device settings (${action.targets.length}×)`;
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
  }
}
