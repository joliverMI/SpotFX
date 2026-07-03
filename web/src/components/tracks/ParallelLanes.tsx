import type { MorphLane } from '../../types/events';
import ActionCard from '../cards/ActionCard';

/** morph_set / scene_update lanes: each lane picks ONE alternative; all lanes fire in parallel. */
export default function ParallelLanes({ lanes }: { lanes: MorphLane[] }) {
  return (
    <div className="track">
      <div className="track-header">
        <span>⫴</span>
        <span>Parallel lanes — one pick per lane, all fire together</span>
      </div>
      {lanes.map((lane, i) => (
        <div key={i} className="action-card" style={{ padding: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{ fontWeight: 600, fontSize: 13 }}>{lane.name || `Lane ${i + 1}`}</span>
            {lane.offset_ms !== 0 && (
              <span className="chip">{lane.offset_ms > 0 ? '+' : ''}{lane.offset_ms} ms</span>
            )}
            {lane.labels.map((l) => (
              <span key={l} className="chip">{l}</span>
            ))}
            <span className="chip">🎲 1 of {lane.alternatives.length}</span>
          </div>
          <div style={{ marginLeft: 12 }}>
            {lane.alternatives.map((a, j) => (
              <ActionCard key={j} action={a} />
            ))}
            {!lane.alternatives.length && <p className="empty-note">No alternatives.</p>}
          </div>
        </div>
      ))}
      {!lanes.length && <p className="empty-note">No lanes.</p>}
    </div>
  );
}
