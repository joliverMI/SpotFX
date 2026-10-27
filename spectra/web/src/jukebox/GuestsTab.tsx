/** THE JUKEBOX'S GUESTS TAB (phase 2 PR 2.2: the host's controls; the plan's
 * §4 Show/Guests cards and §12 guards): the guests' own rules (when the
 * night ends and requests close, explicit songs, how many phones, name
 * changes, the word filter), the line with Hold and Remove on each song,
 * and every phone at tonight's party with Approve, Block, Rename and Lock
 * name. Every decision is SpotFX's (services/jukebox/guests.py, one show
 * validator); the words are jukeboxGuests.ts. */
import { useState } from 'react';
import InfoTip from '../components/InfoTip';
import { useToast } from '../components/Toast';
import { lineRows, phoneActions, phoneLine } from './jukeboxGuests';
import { useGuests, useHoldEntry, useHostPhone, useJukeboxShow, useRemoveEntry, useSaveShow } from './queries';
import type { GuestField, GuestPhone, JukeboxStatus, ShowConfig } from './types';

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function GuestsTab({ status }: { status: JukeboxStatus | undefined }) {
  const toast = useToast();
  const running = !!status?.running;
  const guestsQ = useGuests(running);
  const showQ = useJukeboxShow();
  const save = useSaveShow();
  const host = useHostPhone();
  const hold = useHoldEntry();
  const remove = useRemoveEntry();
  const onError = (e: unknown) => toast(errText(e), 'error');
  const phones = guestsQ.data?.phones ?? [];
  const rows = lineRows(status?.line ?? [], phones);
  const fields = showQ.data?.guest_fields ?? [];
  const show = showQ.data?.show;

  return (
    <div className="jukebox-grid">
      <section className="card jukebox-card" data-testid="jukebox-guest-rules">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-guests"
            text="The guests' own rules: when tonight ends and requests close (last call), explicit songs, how many phones, name changes and the word filter. Each saves on its own; a value outside its range is refused.">
            <span className="card-title jukebox-card-title">Guest rules</span>
          </InfoTip>
        </div>
        {show ? (
          <div className="jukebox-settings">
            {fields.map((f) => (
              <RuleRow key={f.key} f={f} show={show}
                onSave={(v) => save.mutate({ [f.key]: v }, { onError })}
                onBad={(reason) => toast(reason, 'error')} />
            ))}
          </div>
        ) : <p className="jukebox-muted">Reading the rules…</p>}
      </section>

      <section className="card jukebox-card" data-testid="jukebox-guest-line">
        <div className="jukebox-card-head">
          <span className="card-title jukebox-card-title">The line</span>
          <span className="jukebox-muted">{rows.length ? `${rows.length} waiting` : running ? 'empty — slots pass' : 'no night running'}</span>
        </div>
        {rows.length > 0 && (
          <ol className="jukebox-next">
            {rows.map((r) => (
              <li key={r.entry.id} className={`jukebox-item ${r.sent ? 'jukebox' : 'set'}`}>
                <span className="jukebox-item-words">
                  <span className="jukebox-song-title">{r.entry.title || r.entry.uri}</span>
                  <span className="jukebox-song-artist">
                    {[r.entry.artist, `added by ${r.by}`, r.round, r.sent ? 'sent to Spotify' : '',
                      r.held ? 'on hold' : '', r.doomed ? 'removed: skipped as it starts' : ''].filter(Boolean).join(' · ')}
                  </span>
                </span>
                <span className="jukebox-guest-actions">
                  {r.canHold && (
                    <button onClick={() => hold.mutate({ id: r.entry.id, held: !r.held }, { onError })}>
                      {r.held ? 'Let go' : 'Hold'}
                    </button>
                  )}
                  {!r.doomed && (
                    <button onClick={() => remove.mutate(r.entry.id, { onError })}>Remove</button>
                  )}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-phones">
        <div className="jukebox-card-head">
          <span className="card-title jukebox-card-title">Phones</span>
          <span className="jukebox-muted">
            {running ? `${phones.length} tonight${guestsQ.data?.pending ? ` · ${guestsQ.data.pending} waiting for you` : ''}` : 'no night running'}
          </span>
        </div>
        {phones.length > 0 ? (
          <ul className="jukebox-phones">
            {phones.map((p) => (
              <PhoneRow key={p.id} p={p}
                onSet={(patch) => host.mutate({ id: p.id, ...patch }, { onError })} />
            ))}
          </ul>
        ) : running && <p className="jukebox-muted">No phones yet: they join through tonight's party link.</p>}
      </section>
    </div>
  );
}

function RuleRow({ f, show, onSave, onBad }: {
  f: GuestField; show: ShowConfig; onSave: (v: string | number | boolean) => void;
  onBad: (reason: string) => void;
}) {
  const value = show[f.key];
  const [draft, setDraft] = useState<string | null>(null);
  if (f.key === 'explicit_after' && show.explicit !== 'after') return null;
  if (f.kind === 'bool') {
    return (
      <label className="jukebox-field jukebox-check" data-testid={`rule-${f.key}`}>
        <input type="checkbox" checked={!!value} aria-label={f.label} onChange={(e) => onSave(e.target.checked)} />
        {f.label}
      </label>
    );
  }
  if (f.kind === 'choice') {
    return (
      <label className="jukebox-field jukebox-rule-wide" data-testid={`rule-${f.key}`}>
        <span className="jukebox-field-label">{f.label}</span>
        <select aria-label={f.label} value={String(value ?? f.default)} onChange={(e) => onSave(e.target.value)}>
          {(f.choices ?? []).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </label>
    );
  }
  if (f.kind === 'time') {
    return (
      <label className="jukebox-field jukebox-rule-wide" data-testid={`rule-${f.key}`}>
        <span className="jukebox-field-label">{f.label}</span>
        <input type="time" aria-label={f.label} value={String(value ?? f.default)}
          onChange={(e) => { if (/^\d\d:\d\d$/.test(e.target.value)) onSave(e.target.value); }} />
        <span className="jukebox-muted jukebox-field-range">{f.unit}</span>
      </label>
    );
  }
  const commit = () => {
    if (draft == null) return;
    const t = draft.trim();
    setDraft(null);
    const v = Number(t);
    if (!/^\d+$/.test(t)) { onBad(`${f.label}: a whole number, please`); return; }
    if (f.min != null && v < f.min) { onBad(`${f.label}: at least ${f.min}`); return; }
    if (f.max != null && v > f.max) { onBad(`${f.label}: at most ${f.max}`); return; }
    if (v !== value) onSave(v);
  };
  return (
    <label className="jukebox-field" data-testid={`rule-${f.key}`}>
      <span className="jukebox-field-label">{f.label}</span>
      <input type="number" step={1} aria-label={f.label} value={draft ?? String(value ?? '')}
        onChange={(e) => setDraft(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
      <span className="jukebox-muted jukebox-field-range">{`${f.min ?? '…'}–${f.max ?? '…'} ${f.unit}`}</span>
    </label>
  );
}

function PhoneRow({ p, onSet }: {
  p: GuestPhone; onSet: (patch: { approved?: boolean; blocked?: boolean; name_locked?: boolean; name?: string }) => void;
}) {
  const [renaming, setRenaming] = useState<string | null>(null);
  return (
    <li className={`jukebox-phone${p.blocked ? ' jukebox-phone-blocked' : ''}`} data-testid="jukebox-phone">
      <span className="jukebox-item-words">
        {renaming === null ? (
          <span className="jukebox-song-title">{p.name}</span>
        ) : (
          <input aria-label={`New name for ${p.name}`} value={renaming} maxLength={20} autoFocus
            onChange={(e) => setRenaming(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { onSet({ name: renaming.trim() }); setRenaming(null); }
              if (e.key === 'Escape') setRenaming(null);
            }} />
        )}
        <span className="jukebox-song-artist">{phoneLine(p)}</span>
      </span>
      <span className="jukebox-guest-actions">
        {phoneActions(p).map((a) => (
          <button key={a} onClick={() => {
            if (a === 'approve') onSet({ approved: true });
            else if (a === 'block') onSet({ blocked: true });
            else if (a === 'unblock') onSet({ blocked: false });
            else if (a === 'lock') onSet({ name_locked: true });
            else if (a === 'unlock') onSet({ name_locked: false });
            else if (renaming === null) setRenaming(p.name);
            else { onSet({ name: renaming.trim() }); setRenaming(null); }
          }}>
            {a === 'approve' ? 'Approve' : a === 'block' ? 'Block' : a === 'unblock' ? 'Unblock'
              : a === 'lock' ? 'Lock name' : a === 'unlock' ? 'Unlock name' : renaming === null ? 'Rename' : 'Save'}
          </button>
        ))}
      </span>
    </li>
  );
}
