/** Curve profile library — the named likelihood-curve shapes scenes (and
 * later colour sets / flares) reference by id (decision 4). Editing a
 * profile here retunes every scene that references it; the per-scene
 * "which scenes use this" line keeps that honest. Deleting a referenced
 * profile is refused by the API. */
import { useState } from 'react';
import CurveEditor, { type CurvePoint } from '../components/CurveEditor';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import {
  useIntensityHistogram, useSaveCurves, useSequencerConfig, useSequencerCurves,
} from './sequencerQueries';
import type { SceneV2 } from './types';

const uuid = () => crypto.randomUUID();
const DEFAULT_POINTS: CurvePoint[] = [{ x: 0, y: 0 }, { x: 0.65, y: 0.2 }, { x: 1, y: 1 }];

export default function CurveProfilesCard({ scenes }: { scenes: SceneV2[] }) {
  const toast = useToast();
  const { data: curves = {} } = useSequencerCurves();
  const { data: config } = useSequencerConfig();
  const { data: hist } = useIntensityHistogram();
  const saveMut = useSaveCurves();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<CurvePoint[] | null>(null);

  const profiles = Object.values(curves).sort((a, b) => a.name.localeCompare(b.name));
  const profile = selectedId ? curves[selectedId] : profiles[0];

  const usedBy = (profileId: string) =>
    Object.entries(config?.entries ?? {})
      .filter(([, e]) => e.curve_ref === profileId)
      .map(([sid]) => scenes.find((s) => s.id === sid)?.name ?? sid);

  const save = async (next: Record<string, typeof curves[string]>, ok: string) => {
    try {
      await saveMut.mutateAsync(next);
      setDraft(null);
      toast(ok, 'success');
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  const addProfile = () => {
    const name = prompt('Profile name (e.g. "High-energy ramp"):');
    if (!name) return;
    const id = uuid();
    void save({ ...curves, [id]: { id, name, points: DEFAULT_POINTS } }, `Profile "${name}" created`);
    setSelectedId(id);
  };

  const deleteProfile = () => {
    if (!profile) return;
    const users = usedBy(profile.id);
    if (users.length) {
      toast(`"${profile.name}" is used by: ${users.join(', ')} — detach first`, 'error');
      return;
    }
    if (!confirm(`Delete curve profile "${profile.name}"?`)) return;
    const { [profile.id]: _, ...rest } = curves;
    void save(rest, 'Profile deleted');
    setSelectedId(null);
  };

  const users = profile ? usedBy(profile.id) : [];

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
        <select value={profile?.id ?? ''} style={{ fontSize: 12 }}
          onChange={(e) => { setSelectedId(e.target.value); setDraft(null); }}>
          {!profiles.length && <option value="">— no profiles yet —</option>}
          {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <button style={{ fontSize: 11, padding: '2px 10px' }} onClick={addProfile}>+ New profile</button>
        {profile && (
          <button className="danger" style={{ fontSize: 11, padding: '2px 10px' }}
            onClick={deleteProfile}>✕ Delete</button>
        )}
        <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          {profile
            ? users.length
              ? `used by ${users.join(', ')}`
              : 'used by no scene yet'
            : 'named shapes scenes reference — seed from legacy with scripts/seed_sequencer_from_legacy.py'}
          <HelpLink topic="curve-editor" />
        </span>
      </div>
      {profile && (
        <div key={profile.id}>
          <CurveEditor points={draft ?? profile.points} onChange={setDraft} histogram={hist?.counts} />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, color: 'var(--text-muted)' }}>
            <span>
              {(draft ?? profile.points).length} points
              {hist ? ` · underlay: ${hist.total.toLocaleString()} library trigger intensities` : ''}
              {users.length > 0 && ` · saving retunes ${users.length} scene${users.length === 1 ? '' : 's'}`}
            </span>
            {draft && (
              <>
                <button className="primary" style={{ fontSize: 11, padding: '2px 10px', marginLeft: 'auto' }}
                  onClick={() => void save({ ...curves, [profile.id]: { ...profile, points: draft } }, 'Profile saved')}>
                  Save profile
                </button>
                <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => setDraft(null)}>Discard</button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
