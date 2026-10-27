/** THE PRE-DROPS CARD on the Phase tab (predrop plan step 5; the Admiral:
 * "Each scene will define the minimum and maximum time duration required
 * for the pre drop"). A direct control beside the Drop Shockwave switch,
 * the plan's own placement — not a sentence for the agent.
 *
 * One row per kind (spike, vocal intro): its power button and its WINDOW,
 * the shortest and the longest gap to its drop in ms. A pre-drop inside
 * the showing scene's window, its kind on, plays here: today that fades the
 * drop's colour change across it. A min/max edit commits on blur or Enter,
 * and only when it fits the kind's bounds with min below max — otherwise
 * the row says why and nothing is written (preDropWindows.editWindow).
 *
 * Under it, the LOOK each device entry plays per kind: "Recommended" (the
 * effect's auto), its declared looks for the kind, "Same as spike" for the
 * vocal intro — or a muted line when the effect declares none, which is
 * every effect until the first looks are built. Every write is a scene-draft
 * edit through setScene; the page's Save keeps it. */
import { useState } from 'react';
import Icon from '../../components/Icon';
import PowerButton from '../../components/PowerButton';
import HelpLink from '../../help/HelpLink';
import { useRegistry } from '../../queries';
import { PRE_DROP_COLOR, type PreDropKind } from '../../timeline/dropSequences';
import type { PreDropKindMeta, PreDropWindow, SceneDeviceConfig, SceneV2 } from '../../types';
import {
  KIND_ICON, PRE_DROP_KINDS, editWindow, kindMeta, lookOptions, looksFor, noLooksLine, windowFor,
  withLook, withWindow,
} from './preDropWindows';

function entryTitle(dev: SceneDeviceConfig): string {
  if (dev.target_kind === 'all') return 'All Devices';
  return dev.target || '— new entry —';
}

/** A millisecond field holding his typing locally until blur or Enter, so
 * a half-typed number is never judged. The value shown otherwise is the
 * one in force. */
function MsField({ value, meta, label, onCommit }: {
  value: number;
  meta: PreDropKindMeta;
  label: string;
  onCommit: (raw: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const raw = draft;
    setDraft(null);
    onCommit(raw);
  };
  return (
    <input type="number" min={meta.min_bound} max={meta.max_bound} step={10}
      aria-label={label} value={draft ?? String(value)}
      style={{ width: 76, fontVariantNumeric: 'tabular-nums' }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
      }} />
  );
}

function KindRow({ kind, win, meta, note, onWindow, onRefused }: {
  kind: PreDropKind;
  win: PreDropWindow;
  meta: PreDropKindMeta;
  note: string | null;
  onWindow: (w: PreDropWindow) => void;
  onRefused: (note: string) => void;
}) {
  const edit = (field: 'min_ms' | 'max_ms') => (raw: string) => {
    const r = editWindow(win, field, raw, meta);
    if (r.ok) onWindow(r.window);
    else onRefused(r.note);
  };
  return (
    <div data-testid={`pre-drop-row-${kind}`}
      style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
      <PowerButton on={win.enabled} onChange={(on) => onWindow({ ...win, enabled: on })} size={22}
        ariaLabel={`${meta.label} pre-drops on this scene`}
        title={win.enabled
          ? `On — a ${meta.label.toLowerCase()} inside this window plays on this scene. Tap to turn it off.`
          : `Off — no ${meta.label.toLowerCase()} plays on this scene; its drops keep the lull as before. Tap to turn on.`} />
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: PRE_DROP_COLOR,
                     opacity: win.enabled ? 1 : 0.55 }}>
        <Icon name={KIND_ICON[kind]} size={16} />
        <b>{meta.label}</b>
      </span>
      <span style={{ opacity: win.enabled ? 1 : 0.55 }}>plays when it sits</span>
      <MsField value={win.min_ms} meta={meta} label={`${meta.label}: shortest gap to the drop, ms`}
        onCommit={edit('min_ms')} />
      <span>to</span>
      <MsField value={win.max_ms} meta={meta} label={`${meta.label}: longest gap to the drop, ms`}
        onCommit={edit('max_ms')} />
      <span>ms before its drop</span>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>({meta.min_bound}-{meta.max_bound})</span>
      {note && (
        <div role="alert" data-testid={`pre-drop-note-${kind}`}
          style={{ flexBasis: '100%', fontSize: 12, color: 'var(--danger, #f66)' }}>{note}</div>
      )}
    </div>
  );
}

export default function PreDropControls({ scene, setScene }: {
  scene: SceneV2;
  setScene: (s: SceneV2) => void;
}) {
  const { data: registry } = useRegistry();
  const [notes, setNotes] = useState<Partial<Record<PreDropKind, string>>>({});
  const setNote = (kind: PreDropKind, note: string | null) =>
    setNotes((n) => ({ ...n, [kind]: note ?? undefined }));

  return (
    <>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 14 }}>
        Pre-drops <HelpLink topic="pre-drop-scene-window" />
      </div>
      <div data-testid="pre-drop-card"
        style={{ background: 'var(--surface2)', padding: 12, borderRadius: 'var(--radius)', fontSize: 13, lineHeight: 1.6 }}>
        <div>
          A pre-drop whose gap to its drop falls inside this scene's window plays here: the drop's
          colour change fades across it. Outside the window, or with its kind off, the lull runs as
          before and the drop's colour change is instant.
        </div>
        {PRE_DROP_KINDS.map((kind) => (
          <KindRow key={kind} kind={kind} win={windowFor(scene, kind, registry)}
            meta={kindMeta(registry, kind)} note={notes[kind] ?? null}
            onWindow={(w) => { setNote(kind, null); setScene(withWindow(scene, kind, w)); }}
            onRefused={(n) => setNote(kind, n)} />
        ))}
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
          The look each device plays on a pre-drop:
        </div>
        {scene.devices.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>This scene has no device entries yet.</div>
        )}
        {scene.devices.map((dev) => {
          const decl = registry?.effects?.[dev.effect_type]?.pre_drop_looks;
          const looks = looksFor(dev);
          const declares = lookOptions(decl, 'spike') !== null;
          return (
            <div key={dev.id} data-testid={`pre-drop-looks-${dev.id}`}
              style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12, marginTop: 4 }}>
              <b>{entryTitle(dev)}</b>
              {!declares ? (
                <span className="pre-drop-no-looks" style={{ color: 'var(--text-muted)' }}>
                  {noLooksLine(dev.effect_type)}
                </span>
              ) : PRE_DROP_KINDS.map((kind) => {
                const meta = kindMeta(registry, kind);
                const opts = lookOptions(decl, kind, looks[kind]) ?? [];
                return (
                  <label key={kind} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <Icon name={KIND_ICON[kind]} size={14} style={{ color: PRE_DROP_COLOR }} />
                    {meta.label}
                    <select value={looks[kind]} style={{ fontSize: 12 }}
                      aria-label={`${entryTitle(dev)}: ${meta.label.toLowerCase()} look`}
                      onChange={(e) => setScene(withLook(scene, dev.id, kind, e.target.value))}>
                      {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </label>
                );
              })}
            </div>
          );
        })}
      </div>
    </>
  );
}
