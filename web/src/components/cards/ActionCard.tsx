import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Action } from '../../types/events';
import { ACTION_ICONS, ACTION_TYPE_LABELS, summarizeAction } from '../../types/summaries';
import { useSummaryCtx } from '../SummaryCtx';

/** Fields already shown in the collapsed row — leave them out of the expanded body. */
function detailFields(action: Action): Record<string, unknown> {
  const { type: _type, labels: _labels, weight: _weight, ...rest } = action as Record<string, unknown> & Action;
  const cleaned: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(rest)) {
    if (v === null || v === undefined) continue;
    if (Array.isArray(v) && v.length === 0) continue;
    cleaned[k] = v;
  }
  return cleaned;
}

/** HA-style card: collapsed one-line summary, click to expand details. Read-only (Phase A). */
export default function ActionCard({ action }: { action: Action }) {
  const [open, setOpen] = useState(false);
  const ctx = useSummaryCtx();
  const details = detailFields(action);
  const hasDetails = Object.keys(details).length > 0 || action.labels.length > 0;

  return (
    <div className="action-card">
      <div className="action-card-row" onClick={() => hasDetails && setOpen(!open)}>
        <span className={`caret ${open ? 'open' : ''}`}>{hasDetails ? '▶' : ''}</span>
        <span className="action-card-icon">{ACTION_ICONS[action.type] ?? '❓'}</span>
        <span className="action-card-summary">{summarizeAction(action, ctx)}</span>
        {action.weight !== 1 && <span className="chip" title="Weight in random pick">w {action.weight}</span>}
        {action.labels.slice(0, 3).map((l) => (
          <span key={l} className="chip">{l}</span>
        ))}
        <span className="action-card-type">{ACTION_TYPE_LABELS[action.type] ?? action.type}</span>
      </div>
      {open && (
        <div className="action-card-body">
          {action.type === 'event_ref' && ctx.events?.[action.event_id] && (
            <p style={{ marginBottom: 8 }}>
              <Link to={`/event/${action.event_id}`}>Open “{ctx.events[action.event_id].name}” →</Link>
            </p>
          )}
          {action.labels.length > 0 && (
            <p style={{ marginBottom: 8 }}>
              Labels: {action.labels.map((l) => <span key={l} className="chip" style={{ marginRight: 4 }}>{l}</span>)}
            </p>
          )}
          {Object.keys(details).length > 0 && <pre>{JSON.stringify(details, null, 2)}</pre>}
        </div>
      )}
    </div>
  );
}
