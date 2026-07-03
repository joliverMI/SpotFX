import type { MusicEvent } from '../../types/events';
import { findByUid, ROOT_PATH } from '../../lib/paths';

/** Dot path to a container action itself (for nested container paths like
 * `${groupPath}.children.0.actions`). The composite root maps to "root". */
export function groupPathOf(draft: MusicEvent, uid: string): string | null {
  const loc = findByUid(draft, uid);
  if (loc?.kind !== 'action') return null;
  return loc.containerPath === ROOT_PATH ? 'root' : `${loc.containerPath}.${loc.index}`;
}
