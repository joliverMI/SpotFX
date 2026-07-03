import { Link } from 'react-router-dom';
import type { BeatRevertConfig, BeatSequenceStep, MusicEvent } from '../../types/events';
import ActionCard from '../cards/ActionCard';
import { stepActions } from './SequenceTrack';
import { useSummaryCtx } from '../SummaryCtx';

export default function BeatSequenceTrack({
  event,
}: {
  event: Pick<MusicEvent, 'beat_sequence_steps' | 'beat_revert' | 'beat_sequence_fallback' | 'beat_sequence_start_offset_beats'>;
}) {
  const ctx = useSummaryCtx();
  const steps: BeatSequenceStep[] = event.beat_sequence_steps;
  const revert: BeatRevertConfig | null = event.beat_revert;
  return (
    <div className="track">
      <div className="track-header">
        <span>🥁</span>
        <span>Beat sequence — {steps.length} steps</span>
        <span className="chip">no beats: {event.beat_sequence_fallback}</span>
        {event.beat_sequence_start_offset_beats !== 0 && (
          <span className="chip">
            start {event.beat_sequence_start_offset_beats > 0 ? '+' : ''}
            {event.beat_sequence_start_offset_beats} beats
          </span>
        )}
      </div>
      {steps.map((step, i) => (
        <div key={i} className="action-card" style={{ padding: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: step.step_type === 'action' ? 8 : 0 }}>
            <span className="step-badge">{i + 1}</span>
            <span className="chip">+{step.delay_beats} beats</span>
            {step.pre_ramp && <span className="chip" title="Ramp starts early to complete on the beat">pre-ramp</span>}
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
            </div>
          )}
        </div>
      ))}
      {!steps.length && <p className="empty-note">No steps.</p>}
      {revert?.enabled && (
        <div className="track-header" style={{ marginTop: 10, marginBottom: 0 }}>
          <span>↩️</span>
          <span>
            Revert after +{revert.delay_beats} beats (ramp {revert.transition_ms} ms{revert.pre_ramp ? ', pre-ramp' : ''})
          </span>
        </div>
      )}
    </div>
  );
}
