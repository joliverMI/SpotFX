import type { DeviceSettingsAction, DeviceSettingTarget } from '../../types/events';
import { NumberInput, Row, ScopeListInput } from './inputs';

const newTarget = (): DeviceSettingTarget => ({
  scope: { virtual_ids: [], categories: [], roles: [] },
  max_brightness: null,
  frequency_min: null,
  frequency_max: null,
});

export default function DeviceSettingsForm({
  action,
  update,
}: {
  action: DeviceSettingsAction;
  update: (fn: (a: DeviceSettingsAction) => void) => void;
}) {
  return (
    <div>
      {action.targets.map((t, i) => (
        <div key={i} className="action-card" style={{ padding: 10, marginBottom: 8 }}>
          <Row label="Virtuals"><ScopeListInput value={t.scope.virtual_ids} placeholder="ids (blank = any)"
            onChange={(v) => update((a) => { a.targets[i].scope.virtual_ids = v; })} /></Row>
          <Row label="Categories"><ScopeListInput value={t.scope.categories} placeholder="Matrix, Strips, Singles"
            onChange={(v) => update((a) => { a.targets[i].scope.categories = v; })} /></Row>
          <Row label="Roles"><ScopeListInput value={t.scope.roles} placeholder="roles"
            onChange={(v) => update((a) => { a.targets[i].scope.roles = v; })} /></Row>
          <Row label="Max brightness" help="0–1, blank = unchanged">
            <NumberInput value={t.max_brightness} nullable min={0} max={1} step={0.05}
              onChange={(v) => update((a) => { a.targets[i].max_brightness = v; })} />
          </Row>
          <Row label="Freq min (Hz)">
            <NumberInput value={t.frequency_min} nullable min={0}
              onChange={(v) => update((a) => { a.targets[i].frequency_min = v; })} />
          </Row>
          <Row label="Freq max (Hz)">
            <NumberInput value={t.frequency_max} nullable min={0}
              onChange={(v) => update((a) => { a.targets[i].frequency_max = v; })} />
          </Row>
          <button className="danger" style={{ fontSize: 11, padding: '3px 8px' }}
            onClick={() => update((a) => { a.targets.splice(i, 1); })}>✕ Remove target</button>
        </div>
      ))}
      <button style={{ fontSize: 12 }} onClick={() => update((a) => { a.targets.push(newTarget()); })}>
        + Add target
      </button>
    </div>
  );
}
