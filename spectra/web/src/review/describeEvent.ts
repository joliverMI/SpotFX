/** Human labels for a show-log event, read off the same `detail` shape
 * each fire_history choke point already stamps (see fire_history.py's
 * record_fire call sites) — no extra lookups needed. */
import type { ReviewEventItem } from '../types';

const BUCKET_LABEL: Record<ReviewEventItem['bucket'], string> = {
  scenes: 'Scene',
  responses: 'Response',
  color_sets: 'Colour set',
  triggers: 'Trigger',
};

export const BUCKET_COLOR: Record<ReviewEventItem['bucket'], string> = {
  scenes: '#a855f7',
  responses: '#f59e0b',
  color_sets: '#14b8a6',
  triggers: '#60a5fa',
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
      return `Trigger fired: ${kind}${source ? ` (${source})` : ''}`;
    }
    default:
      return `${BUCKET_LABEL[item.bucket] ?? item.bucket}: ${item.key}`;
  }
}
