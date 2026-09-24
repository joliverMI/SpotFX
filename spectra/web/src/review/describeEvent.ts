/** Human labels for a show-log event, read off the same `detail` shape
 * each fire_history choke point already stamps (see fire_history.py's
 * record_fire call sites) — no extra lookups needed. */
import type { ReviewEventItem } from '../types';

const BUCKET_LABEL: Record<ReviewEventItem['bucket'], string> = {
  scenes: 'Scene',
  responses: 'Response',
  color_sets: 'Colour set',
  triggers: 'Trigger',
  deferred: 'Deferred (dwell)',
};

export const BUCKET_COLOR: Record<ReviewEventItem['bucket'], string> = {
  scenes: '#a855f7',
  responses: '#f59e0b',
  color_sets: '#14b8a6',
  triggers: '#60a5fa',
  deferred: '#94a3b8',
};

/** engine._response_gate/_update_gate's refusal words, as a reader says them.
 * An unlisted reason is shown verbatim rather than guessed at. */
const KIND_BATCH_SKIP_REASON: Record<string, string> = {
  preview: 'a Preview held the room',
  scene_change_mode: 'scene-change mode closed',
};

export function describeEvent(item: ReviewEventItem): string {
  const d = item.detail;
  switch (item.bucket) {
    case 'scenes': {
      const name = (d.scene_name as string | undefined) ?? item.key;
      const intensity = d.intensity as number | undefined;
      return `Scene: ${name}${intensity != null ? ` @ ⚡${intensity.toFixed(2)}` : ''}`;
    }
    case 'responses': {
      const cls = (d.event_class as string | undefined) ?? item.key;
      const intensity = d.intensity as number | undefined;
      return `Response: ${cls}${intensity != null ? ` @ ⚡${intensity.toFixed(2)}` : ''}`;
    }
    case 'color_sets': {
      const name = (d.set_name as string | undefined) ?? item.key;
      return `Colour set: ${name}`;
    }
    case 'triggers': {
      const kind = (d.action_kind as string | undefined) ?? item.key;
      const source = d.source as string | undefined;
      const snapGrid = d.snap_grid as string | undefined;
      const snapMoved = d.snap_moved_ms as number | undefined;
      const snapNote = snapGrid
        ? ` · moved to ${snapGrid} (${snapMoved != null && snapMoved >= 0 ? '+' : ''}${snapMoved ?? 0}ms)`
        : '';
      return `Trigger fired: ${kind}${source ? ` (${source})` : ''}${snapNote}`;
    }
    case 'deferred': {
      if (item.key === 'kind_batch') {
        // A staggered flare-kind batch that woke to a refused show gate
        // (engine._run_kind_batch) — not a dwell hold, so it names its own
        // cause instead of borrowing the dwell wording below.
        const reason = d.reason as string | undefined;
        const why = (reason && KIND_BATCH_SKIP_REASON[reason]) ?? reason ?? 'unknown reason';
        const names = d.kind_names as string[] | undefined;
        const delay = d.delay_ms as number | undefined;
        return `Flare kinds skipped (${why}): ${names?.length ? names.join(', ') : item.key}${delay != null ? `, +${delay}ms` : ''}`;
      }
      const name = (d.scene_name as string | undefined) ?? item.key;
      const remaining = d.remaining_dwell_s as number | undefined;
      const result = d.update_result as string | undefined;
      return `Held (minimum dwell): ${name}${remaining != null ? `, ${remaining.toFixed(1)}s left` : ''}${result ? ` — update: ${result}` : ''}`;
    }
    default:
      return `${BUCKET_LABEL[item.bucket] ?? item.bucket}: ${item.key}`;
  }
}
