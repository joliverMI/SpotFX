/** Whole-song check — the per-song watchdog's visible record (Timing page).
 *
 * After a play that did not hard-lock (and every Nth play that did), the
 * root sweep votes the play's own audio over the whole song and, when one
 * offset wins clearly and beats the saved one, corrects the stored offset so
 * the next play starts there (services/whole_song_check.py). This card lists
 * those checks — corrections first-class, every other outcome with its
 * reason — and edits the thresholds (PUT /lock-history/whole-song/settings,
 * the same route Sonic uses).
 *
 * Twin: web/src/timingviz/WholeSongCheckPanel.tsx (only the api
 * import differs). */
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPut } from '../api/spotfx';
import HelpLink from '../help/HelpLink';

export interface WholeSongEntry {
  at: string;
  uri: string;
  title?: string;
  artist?: string;
  play_locked?: boolean;
  action: string;
  reason: string;
  old_offset_ms?: number | null;
  new_offset_ms?: number | null;
  vote_offset_ms?: number | null;
  wins?: number;
  n_windows?: number;
  median_r?: number | null;
  median_r_saved?: number | null;
  saved?: boolean | null;
}

interface SettingSpec { kind: 'bool' | 'int' | 'float'; min?: number; max?: number; label: string; help: string }

interface WholeSongResp { entries: WholeSongEntry[]; settings: Record<string, number | boolean> }
interface SettingsResp { settings: Record<string, number | boolean>; spec: Record<string, SettingSpec> }

const ACTION_LABEL: Record<string, string> = {
  corrected: 'corrected',
  agrees: 'agrees',
  small_move: 'close enough',
  no_clear_majority: 'no clear majority',
  too_few_windows: 'too short',
  weak: 'too weak',
  not_ahead: 'not clearly better',
  user_verified: 'user-verified',
};

const fmtMs = (ms?: number | null): string =>
  ms == null ? '—' : `${ms >= 0 ? '+' : ''}${ms}ms`;

const fmtAgo = (iso: string): string => {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 129600) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};

export default function WholeSongCheckPanel({ onPick }: { onPick?: (uri: string) => void }) {
  const qc = useQueryClient();
  const [showAll, setShowAll] = useState(false);
  const [editing, setEditing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { data } = useQuery({
    queryKey: ['whole-song-checks', showAll],
    queryFn: () => apiGet<WholeSongResp>(
      `/lock-history/whole-song?limit=30&corrections_only=${showAll ? 'false' : 'true'}`),
    refetchInterval: 30000,
    retry: false,
  });
  const { data: spec } = useQuery({
    queryKey: ['whole-song-settings'],
    queryFn: () => apiGet<SettingsResp>('/lock-history/whole-song/settings'),
    enabled: editing,
    retry: false,
  });
  if (!data) return null;
  const on = data.settings?.xcorr_whole_song_enabled !== false;

  const save = async (key: string, value: number | boolean) => {
    setErr(null);
    try {
      await apiPut('/lock-history/whole-song/settings', { [key]: value });
      qc.invalidateQueries({ queryKey: ['whole-song-settings'] });
      qc.invalidateQueries({ queryKey: ['whole-song-checks'] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
        <span style={{ fontSize: 13, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          Whole-song check <HelpLink topic="timing-whole-song-check" title="What the whole-song check does" />
        </span>
        <span style={{ fontSize: 11, color: on ? '#4caf50' : 'var(--text-muted)' }}>{on ? 'on' : 'off'}</span>
        <label style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> every check
        </label>
        <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => setEditing((v) => !v)}>
          {editing ? 'Done' : 'Settings'}
        </button>
      </div>
      {editing && spec && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: '4px 10px', fontSize: 12, marginBottom: 8 }}>
          {Object.entries(spec.spec).map(([key, s]) => (
            <SettingRow key={key} name={key} spec={s} value={spec.settings[key]} onSave={save} />
          ))}
          {err && <div style={{ gridColumn: '1 / -1', color: '#f44336' }}>{err}</div>}
        </div>
      )}
      {data.entries.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {showAll ? 'No checks yet.' : 'No corrections yet — every checked song agreed with its saved offset, or was left alone.'}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: 'var(--text-muted)', textAlign: 'left' }}>
                <th>When</th><th>Song</th><th>Outcome</th><th>Saved → vote</th><th>Windows</th><th>r (vote / saved)</th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map((e) => (
                <tr key={`${e.at}-${e.uri}`} title={e.reason}
                    style={{ cursor: onPick ? 'pointer' : undefined, borderTop: '1px solid var(--border, #333)' }}
                    onClick={() => onPick?.(e.uri)}>
                  <td style={{ whiteSpace: 'nowrap' }}>{fmtAgo(e.at)}</td>
                  <td style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {e.title || e.uri}{e.artist ? <span style={{ color: 'var(--text-muted)' }}> — {e.artist}</span> : null}
                  </td>
                  <td style={{ color: e.action === 'corrected' ? '#4caf50' : 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                    {ACTION_LABEL[e.action] ?? e.action}{e.action === 'corrected' && e.saved === false ? ' (save failed)' : ''}
                  </td>
                  <td style={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                    {fmtMs(e.old_offset_ms)} → {fmtMs(e.vote_offset_ms)}
                  </td>
                  <td style={{ fontFamily: 'monospace' }}>{e.wins ?? 0}/{e.n_windows ?? 0}</td>
                  <td style={{ fontFamily: 'monospace' }}>
                    {e.median_r != null ? e.median_r.toFixed(2) : '—'} / {e.median_r_saved != null ? e.median_r_saved.toFixed(2) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SettingRow({ name, spec, value, onSave }: {
  name: string; spec: SettingSpec; value: number | boolean | undefined;
  onSave: (key: string, value: number | boolean) => void;
}) {
  const [draft, setDraft] = useState<string>(value == null ? '' : String(value));
  return (
    <>
      <span title={spec.help}>{spec.label}</span>
      {spec.kind === 'bool' ? (
        <input type="checkbox" checked={value === true} onChange={(e) => onSave(name, e.target.checked)} />
      ) : (
        <input
          type="number" style={{ width: 80 }} value={draft}
          min={spec.min} max={spec.max} step={spec.kind === 'int' ? 1 : 0.01}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => { const n = Number(draft); if (draft !== '' && Number.isFinite(n) && n !== value) onSave(name, n); }}
        />
      )}
    </>
  );
}
