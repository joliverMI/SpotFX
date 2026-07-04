import type { DeviceSettingsAction, DeviceSettingTarget } from '../../types/events';
import { NumberInput, Row } from './inputs';
import { ParentScopeToggle } from './ScopePicker';

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
          <Row label="Target" help="parent = inherit the nearest group/lane Target (or all devices)">
            <ParentScopeToggle scope={t.scope}
              onChange={(s) => update((a) => { a.targets[i].scope = s ?? { virtual_ids: [], categories: [], roles: [] }; })} />
          </Row>
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
