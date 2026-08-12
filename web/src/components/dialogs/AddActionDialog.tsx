import { useEffect, useMemo, useRef, useState } from 'react';
import { ACTION_ICONS, ACTION_TYPE_LABELS, type AddableActionType } from '../../types/summaries';

const DESCRIPTIONS: Record<AddableActionType, string> = {
  event_ref: 'Fire another event’s action pool',
  ledfx_scene: 'Activate a named LedFX scene',
  ledfx_ambient: 'Patch the Single Color Effect (color, blur…)',
  ledfx_ambient_color: 'Apply the complementary of the current ambient color',
  ledfx_global_transition: 'Set LedFX global transition time / mode',
  ledfx_effect_param: 'Set effect parameters by unified label',
  morph_step: 'Multi-target aspect changes (shape/effect/color/…)',
  set_color: 'Apply a saved Color Set or Color Group',
  morph_color: 'Rotate the showing colors around the hue wheel',
  scene_morph: 'Step the active Scene Group ±N scenes and fire the result',
  device_settings: 'Virtual-config changes (max brightness, freq band)',
  brightness: 'Set/nudge brightness & BG brightness multipliers over the Color Set values',
  random_group: 'Pick one weighted option; its actions fire together',
  sequence_group: 'Run children in order with ms or beat delays',
  parallel_group: 'Run children at once, each with its own offset',
  intensity_chooser: 'Trigger intensity picks one threshold lane; it fires alone',
  light_mode_chooser: 'The Now Playing Dark/Light mode picks a lane; choose which is the default',
};

/** HA-style searchable "Add action" dialog. `types` limits what can be added here. */
export default function AddActionDialog({
  types,
  onPick,
  onClose,
}: {
  types: AddableActionType[];
  onPick: (t: AddableActionType) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return types.filter(
      (t) =>
        !needle ||
        ACTION_TYPE_LABELS[t].toLowerCase().includes(needle) ||
        t.includes(needle) ||
        DESCRIPTIONS[t].toLowerCase().includes(needle),
    );
  }, [q, types]);

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '10vh',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{ width: 520, maxWidth: '92vw', maxHeight: '75vh', overflowY: 'auto', margin: 0 }}
      >
        <input
          ref={inputRef}
          type="search"
          placeholder="Search action types…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && visible.length === 1) onPick(visible[0]);
          }}
          style={{ width: '100%', marginBottom: 12 }}
        />
        {visible.map((t) => (
          <div
            key={t}
            className="action-card-row"
            style={{ border: '1px solid var(--border)', borderRadius: 8, marginBottom: 6 }}
            onClick={() => onPick(t)}
          >
            <span className="action-card-icon">{ACTION_ICONS[t]}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{ACTION_TYPE_LABELS[t]}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{DESCRIPTIONS[t]}</div>
            </div>
          </div>
        ))}
        {!visible.length && <p className="empty-note">No action types match “{q}”.</p>}
      </div>
    </div>
  );
}
