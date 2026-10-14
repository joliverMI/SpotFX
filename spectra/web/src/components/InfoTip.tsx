/** A rich tooltip: hover (mouse) or long-press (touch) reveals a short
 * description plus a "Help" link into the full topic — UI declutter plan
 * idea 5 ("One help '?' per page"), replacing a bare circled "?" wherever
 * a control's own description is worth more than a plain `title` attribute
 * can hold (a native tooltip can't carry a clickable link). The page-level
 * "?" in the grouped menu (nav/NavBar.tsx, already context-sensitive via
 * help/routeTopics.ts) stays the one always-reachable way into Help; this
 * is for a control that deserves its own short explanation in place.
 *
 * Deliberately a small floating panel, not `TopBarGroupButton`'s bigger
 * one — this never holds editable fields, only prose plus one link, so it
 * closes on blur/mouseleave rather than needing outside-click handling. */
import { useRef, useState } from 'react';
import { useLongPress } from '../lib/useLongPress';
import HelpLink from '../help/HelpLink';
import Icon from './Icon';

export default function InfoTip({ text, topic }: { text: string; topic?: string }) {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPress = useLongPress(400);

  const show = () => {
    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
    setOpen(true);
  };
  const hideSoon = () => {
    closeTimer.current = setTimeout(() => setOpen(false), 150);
  };

  return (
    <span className="info-tip long-press-target" onMouseLeave={hideSoon}>
      <button
        type="button"
        className="info-tip-btn"
        aria-label="More about this control"
        onMouseEnter={show}
        onFocus={show}
        onBlur={hideSoon}
        {...longPress(show)}
      >
        <Icon name="info" size={13} className="info-tip-icon" />
      </button>
      {open && (
        <div className="info-tip-panel" role="tooltip" onMouseEnter={show} onMouseLeave={hideSoon}>
          <p>{text}</p>
          {topic && <HelpLink topic={topic} title="Full help topic" />}
        </div>
      )}
    </span>
  );
}
