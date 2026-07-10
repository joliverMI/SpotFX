/** TS mirrors for models/color_set.py (as used by frontend/color-sets.html). */
import type { MorphScope } from '../types/events';

export interface ColorSetEntry {
  scope: MorphScope;
  color_kind: 'gradient' | 'solid' | null;
  color_value: string | null;
  bg_color: string | null;
  bg_mode: 'overwrite' | 'additive' | null;
  brightness: number | null;
  background_brightness: number | null;
  accent_color: string | null;
  ramp_ms: number | null;
}

export interface GroupMember {
  color_set_id: string;
  weight: number;
}

export interface ColorSetCard {
  id: string;
  name: string;
  color: string;
  kind: 'set' | 'group';
  labels: string[];
  /** kind=set: the palette. kind=group: per-device/category overrides merged
   * onto the picked member Set at fire time (set fields win over the Set). */
  entries: ColorSetEntry[];
  members: GroupMember[];
  mode: 'cycle' | 'weighted';
  cycle_behavior: 'wrap' | 'bounce';
  exclude_current: boolean;
  [k: string]: unknown;
}

export interface SavedGradient {
  id: string;
  name: string;
  value: string;
}

export const emptyEntry = (): ColorSetEntry => ({
  scope: { virtual_ids: [], categories: [], roles: [] },
  color_kind: null,
  color_value: null,
  bg_color: null,
  bg_mode: null,
  brightness: null,
  background_brightness: null,
  accent_color: null,
  ramp_ms: null,
});

export function newCard(kind: 'set' | 'group', id: string): ColorSetCard {
  return {
    id,
    name: kind === 'group' ? 'New Group' : 'New Color Set',
    color: '#FFD700',
    kind,
    labels: [],
    entries: [],
    members: [],
    mode: 'cycle',
    cycle_behavior: 'wrap',
    exclude_current: true,
  };
}
