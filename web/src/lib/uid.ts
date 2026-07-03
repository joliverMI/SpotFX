/** Ephemeral editor ids (_uid) — attached on load for React keys / DnD, stripped on save. */

let counter = 0;
export const nextUid = () => `u${++counter}`;

export function uuid(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/** Recursively attach _uid to every action, step, lane, target and random option. */
export function attachUids<T>(node: T): T {
  const walk = (v: unknown): void => {
    if (Array.isArray(v)) {
      v.forEach(walk);
    } else if (v && typeof v === 'object') {
      const o = v as Record<string, unknown>;
      if (!o._uid) o._uid = nextUid();
      for (const val of Object.values(o)) walk(val);
    }
  };
  walk(node);
  return node;
}

/** Deep-clone with every underscore-prefixed (editor-only) key removed. */
export function stripUids<T>(node: T): T {
  return JSON.parse(
    JSON.stringify(node, (key, value) => (key.startsWith('_') ? undefined : value)),
  );
}

export const getUid = (o: unknown): string => (o as { _uid: string })._uid;
