import type { DeviceSettingTarget } from '../../types/events';

function scopeLabel(t: DeviceSettingTarget): string {
  const parts = [...t.scope.virtual_ids, ...t.scope.categories, ...t.scope.roles];
  return parts.length ? parts.join(', ') : 'all virtuals';
}

export default function DeviceTargetsTrack({ targets }: { targets: DeviceSettingTarget[] }) {
  return (
    <div className="track">
      <div className="track-header">
        <span>⚙️</span>
        <span>Device settings — applied instantly</span>
      </div>
      {targets.map((t, i) => (
        <div key={i} className="action-card" style={{ padding: 10, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="chip accent">{scopeLabel(t)}</span>
          {t.max_brightness != null && <span className="chip">max bright {Math.round(t.max_brightness * 100)}%</span>}
          {t.frequency_min != null && <span className="chip">freq min {t.frequency_min} Hz</span>}
          {t.frequency_max != null && <span className="chip">freq max {t.frequency_max} Hz</span>}
        </div>
      ))}
      {!targets.length && <p className="empty-note">No targets.</p>}
    </div>
  );
}
