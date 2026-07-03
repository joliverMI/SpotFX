import { Link } from 'react-router-dom';
import type { RevertConfig, SequenceStep } from '../../types/events';
import ActionCard from '../cards/ActionCard';
import { useSummaryCtx } from '../SummaryCtx';

export function stepActions(step: { action: SequenceStep['action']; actions: SequenceStep['actions'] }) {
  return step.actions.length ? step.actions : step.action ? [step.action] : [];
}

export default function SequenceTrack({ steps, revert }: { steps: SequenceStep[]; revert: RevertConfig | null }) {
  const ctx = useSummaryCtx();
  return (
    <div className="track">
      <div className="track-header">
        <span>➡️</span>
        <span>Sequence — {steps.length} steps</span>
      </div>
      {steps.map((step, i) => (
        <div key={i} className="action-card" style={{ padding: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: step.step_type === 'action' ? 8 : 0 }}>
            <span className="step-badge">{i + 1}</span>
            <span className="chip">+{step.delay_ms} ms</span>
            {step.labels.map((l) => (
              <span key={l} className="chip">{l}</span>
            ))}
            {step.step_type === 'event' && (
              <span style={{ fontSize: 14 }}>
                🔗{' '}
                {step.event_id && ctx.events?.[step.event_id] ? (
                  <Link to={`/event/${step.event_id}`}>{ctx.events[step.event_id].name}</Link>
                ) : (
                  <em>(no event)</em>
                )}
              </span>
            )}
          </div>
          {step.step_type === 'action' && (
            <div style={{ marginLeft: 32 }}>
              {stepActions(step).map((a, j) => (
                <ActionCard key={j} action={a} />
              ))}
              {stepActions(step).length > 1 && (
                <p className="empty-note" style={{ fontSize: 11 }}>All fire concurrently</p>
              )}
            </div>
          )}
        </div>
      ))}
      {!steps.length && <p className="empty-note">No steps.</p>}
      {revert?.enabled && (
        <div className="track-header" style={{ marginTop: 10, marginBottom: 0 }}>
          <span>↩️</span>
          <span>
            Revert after +{revert.delay_ms} ms (ramp {revert.transition_ms} ms)
          </span>
        </div>
      )}
    </div>
  );
}
