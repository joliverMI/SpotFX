/** /devices — CREATE and EDIT devices, their groupings and their namings.
 *
 * His ask, verbatim: "We need a device edit page to edit and create
 * devices. It should include all the parameters that were tunable in ledfx
 * on one tab, as well as the groupings and namings."
 *
 * ONE TAB is a hard constraint from him, so there are no sub-tabs: a
 * selected device shows its complete parameter set on one surface,
 * GROUPED WITHIN it — Base (the keys every device type shares), Type (what
 * this one driver adds), Groupings & naming, and Timing. The field list is
 * not written here: the server reads it off each vendored driver's own
 * CONFIG_SCHEMA (fx/device_schema.py) and this page renders whatever comes
 * back, so it can never drift from the real validator.
 *
 * FUNCTION FIRST, his standing order — plain layout, complete and correct,
 * no polish pass.
 *
 * ONLY THE DEVICES HE USES are listed by default, his own ask ("only
 * devices i use should be visible on default. can show more with expansion
 * tab"). The used/not-used split arrives on the listing as a per-device
 * `in_use` flag computed server-side from the room's own ground truth
 * (spectra/services/device_usage.py) — this page never re-derives topology.
 * The expansion control names the hidden COUNT, so an absent device is a
 * number he can see, never a silent omission, and a duplicate is flagged in
 * the expanded list rather than removed (the page has no delete, by design).
 *
 * The banner at the top is load-bearing, not decoration: `source` says
 * whether the room is RUNNING (edits reach the fixtures now) or not (edits
 * are written to the fx-live config and land at the next activation). A
 * write is never silently lost and never silently claimed live.
 */
import { useEffect, useMemo, useState } from 'react';
import SonicChatPopover from '../components/SonicChatPopover';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import {
  useCreateDevice, useDevices, useSetDeviceCategories, useSetDeviceTiming, useUpdateDevice,
} from '../queries';
import type { DeviceField, DeviceRecord } from '../types';

function coerce(field: DeviceField, raw: string | boolean): unknown {
  if (field.kind === 'boolean') return Boolean(raw);
  if (field.kind === 'integer' || field.kind === 'number') {
    if (raw === '') return undefined;
    const n = Number(raw);
    return Number.isFinite(n) ? (field.kind === 'integer' ? Math.round(n) : n) : undefined;
  }
  return raw;
}

/** One field. The label column is a minmax track and every control is
 * width:100% inside a min-width:0 cell, so nothing can push the page wider
 * than the phone — the overflow trap this codebase has hit repeatedly
 * (see the device-preview strip's own phone fix). An UNSET optional key
 * shows the driver's default as a PLACEHOLDER, never as a value: writing
 * the default back would read as an edit the owner did not make. */
function FieldRow({ field, value, onChange }: {
  field: DeviceField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const id = `dev-field-${field.name}`;
  const placeholder = field.default === null || field.default === undefined
    ? '' : `${field.default} (default)`;
  const box = { width: '100%', maxWidth: field.kind === 'text' ? 320 : 160,
                boxSizing: 'border-box' as const };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 150px) minmax(0, 1fr)',
                  gap: 8, alignItems: 'start', marginBottom: 8 }}>
      <label htmlFor={id} title={field.description} style={{ overflowWrap: 'anywhere' }}>
        {field.name}
        {field.required && <span style={{ color: '#f87171' }}> *</span>}
      </label>
      <div style={{ minWidth: 0 }}>
        {field.kind === 'boolean' ? (
          <input id={id} type="checkbox" checked={Boolean(value ?? field.default)}
                 onChange={(e) => onChange(coerce(field, e.target.checked))} />
        ) : field.kind === 'enum' ? (
          <select id={id} value={String(value ?? field.default ?? '')} style={box}
                  onChange={(e) => onChange(e.target.value)}>
            {(field.choices ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        ) : (
          <input id={id}
                 type={field.kind === 'integer' || field.kind === 'number' ? 'number' : 'text'}
                 min={field.min} max={field.max} placeholder={placeholder}
                 value={value === undefined || value === null ? '' : String(value)}
                 onChange={(e) => onChange(coerce(field, e.target.value))}
                 style={box} />
        )}
        {field.description && (
          <div style={{ fontSize: 11, opacity: 0.6, marginTop: 2, overflowWrap: 'anywhere' }}>
            {field.description}
          </div>
        )}
      </div>
    </div>
  );
}

function EditDevice({ device, fields, categoryNames, appliedDelayMs, offsetLimitMs, source }: {
  device: DeviceRecord;
  fields: DeviceField[];
  categoryNames: string[];
  appliedDelayMs: Record<string, number>;
  offsetLimitMs: number;
  source: string;
}) {
  const toast = useToast();
  const update = useUpdateDevice();
  const setTiming = useSetDeviceTiming();
  const setCategories = useSetDeviceCategories();
  const [draft, setDraft] = useState<Record<string, unknown>>(device.config);
  const [offset, setOffset] = useState(String(device.timing_offset_ms));

  useEffect(() => {
    setDraft(device.config);
    setOffset(String(device.timing_offset_ms));
  }, [device.id, device.config, device.timing_offset_ms]);

  const changed = useMemo(
    () => Object.keys(draft).filter((k) => JSON.stringify(draft[k]) !== JSON.stringify(device.config[k])),
    [draft, device.config],
  );

  const saveConfig = () => {
    if (changed.length === 0) return;
    const patch: Record<string, unknown> = {};
    changed.forEach((k) => { patch[k] = draft[k]; });
    update.mutate({ deviceId: device.id, config: patch }, {
      onSuccess: (r) => toast(r.summary, 'success'),
      onError: (e: Error) => toast(e.message, 'error'),
    });
  };

  const saveTiming = () => {
    const n = Math.round(Number(offset));
    if (!Number.isFinite(n)) { toast('Timing offset must be a number of milliseconds', 'error'); return; }
    setTiming.mutate({ deviceId: device.id, timingOffsetMs: n }, {
      onSuccess: (r) => toast(r.summary, 'success'),
      onError: (e: Error) => toast(e.message, 'error'),
    });
  };

  const toggleCategory = (virtualId: string, name: string, on: boolean) => {
    const current = device.categories[virtualId] ?? [];
    const next = on ? [...current, name] : current.filter((c) => c !== name);
    setCategories.mutate({ virtualId, categories: next }, {
      onSuccess: (r) => toast(r.summary, 'success'),
      onError: (e: Error) => toast(e.message, 'error'),
    });
  };

  const group = (g: string) => fields.filter((f) => f.group === g);

  return (
    <div className="card">
      <div className="card-title">
        {device.name} <span style={{ opacity: 0.6, fontWeight: 400 }}>({device.type} · {device.id})</span>
      </div>
      {!device.in_use && (
        <div style={{ marginBottom: 8 }}>
          <span className="badge badge-gray">
            Not in use — no scene can currently light this device
            {device.duplicate_of ? ` · duplicate of ${device.duplicate_of}` : ''}
          </span>
          {' '}<HelpLink topic="devices-in-use" />
        </div>
      )}

      <div className="card-subtitle">
        Base <HelpLink topic="devices-parameters" />
      </div>
      {group('base').map((f) => (
        <FieldRow key={f.name} field={f} value={draft[f.name]}
                  onChange={(v) => setDraft({ ...draft, [f.name]: v })} />
      ))}

      <div className="card-subtitle" style={{ marginTop: 12 }}>{device.type} settings</div>
      {group('type').length === 0
        ? <div className="empty-note">This device type adds no settings of its own.</div>
        : group('type').map((f) => (
          <FieldRow key={f.name} field={f} value={draft[f.name]}
                    onChange={(v) => setDraft({ ...draft, [f.name]: v })} />
        ))}

      <div style={{ marginTop: 10 }}>
        <button onClick={saveConfig} disabled={changed.length === 0 || update.isPending}>
          {changed.length === 0 ? 'No changes' : `Save ${changed.length} change${changed.length === 1 ? '' : 's'}`}
        </button>
        {changed.length > 0 && (
          <button style={{ marginLeft: 8 }} onClick={() => setDraft(device.config)}>Revert</button>
        )}
        <span style={{ marginLeft: 10, fontSize: 12, opacity: 0.7 }}>
          {source === 'live'
            ? 'The room is running — a save reaches this fixture now.'
            : 'The room is not running — a save is stored and lands at the next activation.'}
        </span>
      </div>

      <div className="card-subtitle" style={{ marginTop: 16 }}>
        Groupings &amp; naming <HelpLink topic="devices-groupings" />
      </div>
      <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>
        The device&apos;s name is the <code>name</code> field above. Groupings are per
        VIRTUAL — the things this device renders.
      </div>
      {device.virtuals.length === 0
        ? <div className="empty-note">No virtual renders onto this device yet.</div>
        : device.virtuals.map((vid) => (
          <div key={vid} style={{ marginBottom: 6 }}>
            <div style={{ fontFamily: 'monospace', fontSize: 12 }}>{vid}</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 2 }}>
              {categoryNames.map((name) => (
                <label key={name} style={{ fontSize: 12 }}>
                  <input type="checkbox"
                         checked={(device.categories[vid] ?? []).includes(name)}
                         onChange={(e) => toggleCategory(vid, name, e.target.checked)} />
                  {' '}{name}
                </label>
              ))}
            </div>
          </div>
        ))}

      <div className="card-subtitle" style={{ marginTop: 16 }}>
        Timing <HelpLink topic="device-timing-offset" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 150px) minmax(0, 1fr)',
                    gap: 8, alignItems: 'start' }}>
        <label htmlFor="dev-timing">Timing offset (ms)</label>
        <div style={{ minWidth: 0 }}>
          <input id="dev-timing" type="number" step={5}
                 min={-offsetLimitMs} max={offsetLimitMs}
                 value={offset} onChange={(e) => setOffset(e.target.value)}
                 style={{ width: 140 }} />
          <button style={{ marginLeft: 8 }} onClick={saveTiming} disabled={setTiming.isPending}>
            Apply timing
          </button>
          <div style={{ fontSize: 11, opacity: 0.75, marginTop: 4 }}>
            <strong>Negative fires this device EARLIER</strong> than the rest of the
            room; positive later; 0 unchanged. Only differences between devices
            matter — a fixture can only be made to wait, so making one device
            earlier delays the others, and the earliest device is never delayed.
            This cannot move the whole room against the music; that is the
            room&apos;s own A/V sync lead.
          </div>
          <div style={{ fontSize: 11, opacity: 0.75, marginTop: 4 }}>
            Currently held back by <strong>{appliedDelayMs[device.id] ?? 0} ms</strong> to
            match the rest of the room.
          </div>
        </div>
      </div>
    </div>
  );
}

function CreateDevice({ types, fieldsByType, onCreated }: {
  types: string[];
  fieldsByType: Record<string, DeviceField[]>;
  onCreated: (id: string) => void;
}) {
  const toast = useToast();
  const create = useCreateDevice();
  const [type, setType] = useState(types[0] ?? 'dummy');
  const fields = fieldsByType[type] ?? [];
  const [draft, setDraft] = useState<Record<string, unknown>>({});

  useEffect(() => {
    const seeded: Record<string, unknown> = {};
    (fieldsByType[type] ?? []).forEach((f) => {
      if (f.default !== null && f.default !== undefined) seeded[f.name] = f.default;
    });
    setDraft(seeded);
  }, [type, fieldsByType]);

  const submit = () => {
    const config: Record<string, unknown> = {};
    Object.entries(draft).forEach(([k, v]) => {
      if (v !== undefined && v !== '') config[k] = v;
    });
    create.mutate({ type, config }, {
      onSuccess: (r) => {
        toast(r.summary, 'success');
        onCreated(r.device_id ?? r.device?.id ?? '');
      },
      onError: (e: Error) => toast(e.message, 'error'),
    });
  };

  return (
    <div className="card">
      <div className="card-title">
        New device <HelpLink topic="devices-create" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 150px) minmax(0, 1fr)',
                    gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <label htmlFor="dev-new-type">Type</label>
        <select id="dev-new-type" value={type} onChange={(e) => setType(e.target.value)}>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      {(['base', 'type'] as const).map((g) => (
        <div key={g}>
          <div className="card-subtitle">{g === 'base' ? 'Base' : `${type} settings`}</div>
          {fields.filter((f) => f.group === g).map((f) => (
            <FieldRow key={f.name} field={f} value={draft[f.name]}
                      onChange={(v) => setDraft({ ...draft, [f.name]: v })} />
          ))}
        </div>
      ))}
      <button onClick={submit} disabled={create.isPending}>Create device</button>
      <div style={{ fontSize: 11, opacity: 0.7, marginTop: 6 }}>
        Only the six device drivers this app actually ships are offered. Fields
        marked * are required; the server validates against the driver&apos;s own
        schema and says why if it refuses.
      </div>
    </div>
  );
}

export default function DevicesPage() {
  const { data, isLoading, error } = useDevices();
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  // Collapsed on every load, deliberately — not remembered. The default
  // view IS the answer to his ask; a sticky expansion would quietly undo it.
  const [showAll, setShowAll] = useState(false);

  const devices = data?.devices ?? [];
  const hidden = devices.filter((d) => !d.in_use).length;
  const shown = showAll ? devices : devices.filter((d) => d.in_use);
  // A device selected while expanded stays selected if he collapses again;
  // otherwise the first SHOWN device is the one being edited.
  const current = devices.find((d) => d.id === selected)
    ?? shown[0] ?? devices[0] ?? null;

  return (
    <div>
      <div className="card">
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Devices <HelpLink topic="devices-page" />
        </div>
        {isLoading && <div className="empty-note">Loading…</div>}
        {error && <div className="empty-note">Could not read devices: {(error as Error).message}</div>}
        {data && (
          <>
            <div style={{ marginBottom: 8 }}>
              {data.source === 'live' ? (
                <span className="badge badge-gray">The room is RUNNING — edits reach the fixtures now.</span>
              ) : (
                <span className="badge badge-gray">
                  The room is NOT running — edits are stored in the fx-live config and land at the next activation.
                </span>
              )}
              {' '}<HelpLink topic="devices-live-or-stored" />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {shown.map((d) => (
                <button key={d.id}
                        onClick={() => { setSelected(d.id); setCreating(false); }}
                        className={current?.id === d.id && !creating ? 'active' : ''}
                        title={d.duplicate_of
                          ? `Not in use — duplicate of ${d.duplicate_of}`
                          : d.in_use ? undefined : 'Not in use — no scene can light this device'}>
                  {!d.in_use && <span style={{ opacity: 0.7 }}>◦ </span>}
                  {d.name}
                  <span style={{ opacity: 0.6 }}> · {d.type}</span>
                  {d.timing_offset_ms !== 0 && (
                    <span style={{ opacity: 0.8 }}> · {d.timing_offset_ms > 0 ? '+' : ''}{d.timing_offset_ms}ms</span>
                  )}
                  {d.duplicate_of && (
                    <span style={{ opacity: 0.8 }}> · duplicate of {d.duplicate_of}</span>
                  )}
                </button>
              ))}
              <button onClick={() => setCreating(true)} className={creating ? 'active' : ''}>+ New</button>
            </div>
            {hidden > 0 && (
              <div style={{ marginTop: 8 }}>
                <button onClick={() => setShowAll(!showAll)}>
                  {showAll
                    ? `Hide ${hidden} not in use`
                    : `Show all devices — ${hidden} more not in use`}
                </button>
                {' '}<HelpLink topic="devices-in-use" />
                {showAll && (
                  <div style={{ fontSize: 11, opacity: 0.75, marginTop: 4 }}>
                    A device marked <strong>◦</strong> backs no virtual the room&apos;s scene
                    engine can address, so no scene can currently light it. It is hidden,
                    never deleted — {data.usage.rule}
                  </div>
                )}
              </div>
            )}
            {devices.length === 0 && !creating && (
              <div className="empty-note">No devices yet — press “+ New”.</div>
            )}
          </>
        )}
      </div>

      {data && creating && (
        <CreateDevice types={data.types} fieldsByType={data.fields}
                      onCreated={(id) => { setCreating(false); if (id) setSelected(id); }} />
      )}

      {data && !creating && current && (
        <EditDevice device={current}
                    fields={data.fields[current.type] ?? []}
                    categoryNames={data.category_names}
                    appliedDelayMs={data.timing.applied_delay_ms}
                    offsetLimitMs={data.timing.offset_limit_ms}
                    source={data.source} />
      )}

      {/* Everything this page can set, Sonic can set too — his standing
          preference. Same popover the Scenes page mounts, same endpoint. */}
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        You can also just tell Sonic (💬) — &ldquo;make the hue lights fire 80 ms
        earlier&rdquo;, &ldquo;rename the back strip to Sofa&rdquo;.{' '}
        <HelpLink topic="devices-sonic" />
      </div>
      <SonicChatPopover />
    </div>
  );
}
