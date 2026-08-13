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

/** One Dark/Light "mode lane" of a Group card. Active while the resolved
 * display mode matches; "default" always uses the base group as authored.
 * entries = extra overrides layered ON TOP of the group's own (variant wins);
 * members non-empty = replaces the member pool (own cursor). */
export interface ModeVariant {
  entries: ColorSetEntry[];
  members: GroupMember[];
}

export const emptyVariant = (): ModeVariant => ({ entries: [], members: [] });

export interface ColorSetCard {
  id: string;
  name: string;
  color: string;
  kind: 'set' | 'group';
  labels: string[];
  /** Dark/Light cascade levels 6 (group card) / 7 (set card) — only consulted
   * when every level above left the mode at 'default'. */
  display_mode: 'default' | 'dark' | 'light';
  /** kind=set: the palette. kind=group: per-device/category overrides merged
   * onto the picked member Set at fire time (set fields win over the Set). */
  entries: ColorSetEntry[];
  members: GroupMember[];
  mode: 'cycle' | 'weighted';
  cycle_behavior: 'wrap' | 'bounce';
  exclude_current: boolean;
  /** Synced groups share one room-wide palette position: a fire starts from
   * the member nearest the room's current palette hue, not this group's own
   * private cursor. */
  palette_sync: boolean;
  /** kind=group: optional Dark/Light mode lanes (see ModeVariant). */
  dark_variant?: ModeVariant | null;
  light_variant?: ModeVariant | null;
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
    display_mode: 'default',
    entries: [],
    members: [],
    mode: 'cycle',
    cycle_behavior: 'wrap',
    exclude_current: true,
    palette_sync: false,
  };
}
