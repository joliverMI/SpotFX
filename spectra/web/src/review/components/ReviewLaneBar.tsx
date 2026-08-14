/** Read-only lane over one song's reconstructed show — same visual/gesture
 * family as SpectraTriggerBar (position-proportional strip, hover tooltip)
 * but with no drag/edit: this is a review surface, not an authoring one.
 * Events render as thin ticks color-coded by bucket; notes render as
 * taller pins so they read as "pinned against" the show at a glance. */
import { useRef, useState } from 'react';
import type { ReviewTimelineItem } from '../../types';
import { BUCKET_COLOR, describeEvent } from '../describeEvent';

export default function ReviewLaneBar({
  durationMs,
  timeline,
  selectedIndex,
  onSelect,
}: {
  durationMs: number;
  timeline: ReviewTimelineItem[];
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ text: string; leftPct: string } | null>(null);

  const dur = Math.max(1, durationMs);
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;

  return (
    <div
      ref={barRef}
      className="review-lane-bar"
      title="Click a marker to see it with the surrounding show"
    >
      {hover && (
        <div className="review-lane-tooltip" style={{ left: hover.leftPct }}>
          {hover.text}
        </div>
      )}
      {timeline.map((item, i) => {
        if (item.position_ms == null) return null;
        const isNote = item.type === 'note';
        const selected = i === selectedIndex;
        const color = isNote ? 'var(--accent2)' : BUCKET_COLOR[item.bucket];
        const label = isNote ? `Note: ${item.note || '(no text)'}` : describeEvent(item);
        return (
          <button
            key={`${item.type}-${i}`}
            type="button"
            className={`review-lane-marker ${isNote ? 'note' : 'event'} ${selected ? 'selected' : ''}`}
            style={{ left: pct(item.position_ms), background: color }}
            onPointerEnter={() => setHover({ text: label, leftPct: pct(item.position_ms!) })}
            onPointerLeave={() => setHover(null)}
            onClick={() => onSelect(i)}
            aria-label={label}
          />
        );
      })}
    </div>
  );
}
