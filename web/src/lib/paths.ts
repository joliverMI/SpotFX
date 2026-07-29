/** Locate actions/steps inside a MusicEvent draft by their editor _uid. */
import type { Action, MusicEvent } from '../types/events';
import { getUid } from './uid';

export interface ActionContainer {
  /** dot path from the event root to the Action[] array, e.g. "sequence_steps.2.actions" */
  path: string;
  actions: Action[];
}

export function getAtPath(root: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((o, k) => (o as Record<string, unknown>)?.[k], root);
}

/** Every Action[] container in the event, including containers nested inside
 * random/sequence/parallel groups and under a composite root. */
export function collectActionContainers(ev: MusicEvent): ActionContainer[] {
  const out: ActionContainer[] = [];
  const addNestedOf = (basePath: string, a: Action) => {
    if (a.type === 'random_group') {
      a.options.forEach((opt, j) => addWithNested(`${basePath}.options.${j}.actions`, opt.actions));
    } else if (a.type === 'sequence_group' || a.type === 'parallel_group') {
      a.children.forEach((c, j) => addWithNested(`${basePath}.children.${j}.actions`, c.actions));
    } else if (a.type === 'intensity_chooser') {
      a.lanes.forEach((l, j) => addWithNested(`${basePath}.lanes.${j}.actions`, l.actions));
    }
  };
  const addWithNested = (path: string, actions: Action[]) => {
    out.push({ path, actions });
    actions.forEach((a, i) => addNestedOf(`${path}.${i}`, a));
  };
  addWithNested('actions', ev.actions);
  ev.sequence_steps.forEach((s, i) => addWithNested(`sequence_steps.${i}.actions`, s.actions));
  ev.beat_sequence_steps.forEach((s, i) =>
    addWithNested(`beat_sequence_steps.${i}.actions`, s.actions),
  );
  ev.morph_lanes.forEach((l, i) => addWithNested(`morph_lanes.${i}.alternatives`, l.alternatives));
  if (ev.root) addNestedOf('root', ev.root);
  return out;
}

/** Sentinel containerPath for the composite root action (not inside any array). */
export const ROOT_PATH = '__root__';

export interface ActionLoc {
  kind: 'action';
  containerPath: string;
  index: number;
  action: Action;
}
export interface StepLoc {
  kind: 'step' | 'beat_step';
  containerPath: 'sequence_steps' | 'beat_sequence_steps';
  index: number;
}
export type NodeLoc = ActionLoc | StepLoc;

export function findByUid(ev: MusicEvent, uid: string): NodeLoc | null {
  if (ev.root && getUid(ev.root) === uid) {
    return { kind: 'action', containerPath: ROOT_PATH, index: -1, action: ev.root };
  }
  for (const c of collectActionContainers(ev)) {
    const i = c.actions.findIndex((a) => getUid(a) === uid);
    if (i >= 0) return { kind: 'action', containerPath: c.path, index: i, action: c.actions[i] };
  }
  const si = ev.sequence_steps.findIndex((s) => getUid(s) === uid);
  if (si >= 0) return { kind: 'step', containerPath: 'sequence_steps', index: si };
  const bi = ev.beat_sequence_steps.findIndex((s) => getUid(s) === uid);
  if (bi >= 0) return { kind: 'beat_step', containerPath: 'beat_sequence_steps', index: bi };
  return null;
}
