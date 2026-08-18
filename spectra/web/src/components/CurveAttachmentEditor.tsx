/** Shared likelihood-curve attachment editor — extracted from the scene
 * Sequencing tab (2026-08-17, colour-set/group likelihood curves, owner
 * ask: "reuse the same kind of structure as for scenes") so scenes, colour
 * SETS, and colour GROUPS all edit curves through the identical component,
 * with the identical safety rule. Nothing about the safety behaviour below
 * changed in the extraction — this is the same code SequencingTab.tsx used
 * inline, just parameterized by which SequencerConfig field/id it targets.
 *
 * THE SAFETY RULE (unchanged from the original): dragging a point only
 * ever writes to local `draft` state — no code path here writes an edited
 * point into `curves[existingId]` except SaveCurveDialog's own confirmed
 * submit, which itself refuses to reuse an existing name without the
 * caller having answered its overwrite-warning stage first. Every other
 * write (`applyOneOff`) targets THIS entry's own `inline_points` — never
 * the shared profile — so editing a shared curve is structurally incapable
 * of retuning any other entry's copy of it; only an explicit named save,
 * confirmed past a warning on a collision, can touch the shared store.
 */
import { useEffect, useState } from 'react';
import CurveEditor, { type CurvePoint } from './CurveEditor';
import CurveThumbnail from './CurveThumbnail';
import { useToast } from './Toast';
import { useAttachCurve, useSaveCurves } from '../queries';
import type { CurveProfile, SelectorEntry } from '../queries';

const FLAT: CurvePoint[] = [{ x: 0, y: 1 }];

function SaveCurveDialog({
  initialName, curves, usedBy, onCancel, onConfirm,
}: {
  initialName: string;
  curves: Record<string, CurveProfile>;
  usedBy: (profileId: string) => string[];
  onCancel: () => void;
  onConfirm: (name: string, overwriteId: string | null) => void;
}) {
  const [name, setName] = useState(initialName);
  const [pending, setPending] = useState<CurveProfile | null>(null);

  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const existing = Object.values(curves).find(
      (c) => c.name.trim().toLowerCase() === trimmed.toLowerCase());
    if (existing) setPending(existing);
    else onConfirm(trimmed, null);
  };

  return (
    <div onClick={onCancel}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 110,
               display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 380, maxWidth: '92vw', margin: 0 }}>
        {!pending ? (
          <>
            <div className="card-title">Save as named curve</div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
              Name
            </label>
            <input type="text" autoFocus value={name} onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
              placeholder="e.g. High-energy ramp" style={{ width: '100%', marginBottom: 12 }} />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={onCancel}>Cancel</button>
              <button className="primary" disabled={!name.trim()} onClick={submit}>Save</button>
            </div>
          </>
        ) : (
          <>
            <div className="card-title">Overwrite existing curve?</div>
            <p style={{ fontSize: 13, marginTop: -4 }}>
              A curve named <b>"{pending.name}"</b> already exists
              {usedBy(pending.id).length > 0
                ? <> — used by <b>{usedBy(pending.id).length}</b> other item{usedBy(pending.id).length === 1 ? '' : 's'}: {usedBy(pending.id).join(', ')}</>
                : ''}. Saving will overwrite it for everything using it.
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setPending(null)}>Back</button>
              <button className="danger" onClick={() => onConfirm(name.trim(), pending.id)}>
                Overwrite
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function CurveAttachmentEditor({
  id, entries, curves, histogram, attachField, labelForEntry,
  title = 'Likelihood curve', noneNote, flatNote, footer,
}: {
  /** The SequencerConfig entry key this editor targets — a scene id, or a
   * colour Set/Group card id. */
  id: string;
  /** The WHOLE field this id's entry lives in (config.entries or
   * config.color_set_entries) — used only to compute "used by" labels for
   * the save/overwrite dialog. */
  entries: Record<string, SelectorEntry>;
  curves: Record<string, CurveProfile>;
  histogram?: number[];
  attachField: 'entries' | 'color_set_entries';
  /** Turns another entry's key into a human label for the "used by X" text. */
  labelForEntry: (entryId: string) => string;
  title?: string;
  noneNote?: React.ReactNode;
  flatNote?: React.ReactNode;
  /** Optional content rendered below the curve tile grid, e.g. a
   * relationships/read-only block specific to the caller's domain. */
  footer?: React.ReactNode;
}) {
  const toast = useToast();
  const attachMut = useAttachCurve(attachField);
  const saveCurvesMut = useSaveCurves();

  const entry = entries[id];
  const attachment: string = !entry ? 'none'
    : entry.curve_ref ? entry.curve_ref
    : entry.inline_points ? 'inline'
    : 'flat';
  const profile = entry?.curve_ref ? curves[entry.curve_ref] : undefined;

  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState<CurvePoint[] | null>(null);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  useEffect(() => {
    setOpenId(null);
    setDraft(null);
    setSaveDialogOpen(false);
  }, [id]);

  const points = draft ?? (profile ? profile.points : entry?.inline_points ?? FLAT);

  const usedBy = (profileId: string) =>
    Object.entries(entries)
      .filter(([, e]) => e.curve_ref === profileId)
      .map(([eid]) => labelForEntry(eid));
  const otherUsers = (profileId: string) =>
    Object.entries(entries)
      .filter(([eid, e]) => e.curve_ref === profileId && eid !== id)
      .map(([eid]) => labelForEntry(eid));

  const attach = async (value: string): Promise<boolean> => {
    try {
      if (value === 'none') await attachMut.mutateAsync({ entryId: id, attachment: { kind: 'none' } });
      else if (value === 'flat') await attachMut.mutateAsync({ entryId: id, attachment: { kind: 'flat' } });
      else if (value === 'inline') {
        await attachMut.mutateAsync({
          entryId: id,
          attachment: { kind: 'inline', points: profile ? profile.points : points },
        });
      } else {
        await attachMut.mutateAsync({ entryId: id, attachment: { kind: 'profile', profileId: value } });
      }
      toast('Curve attachment saved', 'success');
      return true;
    } catch (e) {
      toast(`Attach failed: ${e}`, 'error');
      return false;
    }
  };

  const selectTile = async (value: string) => {
    setDraft(null);
    const ok = await attach(value);
    if (!ok) return;
    setOpenId(value === 'inline' || curves[value] ? value : null);
  };

  const requestClose = () => {
    if (draft && !window.confirm('Discard unsaved edits to this curve?')) return;
    setOpenId(null);
    setDraft(null);
    setSaveDialogOpen(false);
  };

  const applyOneOff = async () => {
    const pts = draft ?? points;
    try {
      await attachMut.mutateAsync({ entryId: id, attachment: { kind: 'inline', points: pts } });
      setDraft(null);
      setOpenId('inline');
      toast('Applied as one-off — this item only', 'success');
    } catch (e) {
      toast(`Apply failed: ${e}`, 'error');
    }
  };

  const saveNamed = async (name: string, overwriteId: string | null) => {
    const curveId = overwriteId ?? crypto.randomUUID();
    const pts = draft ?? points;
    try {
      await saveCurvesMut.mutateAsync({ ...curves, [curveId]: { id: curveId, name, points: pts } });
      await attach(curveId);
      setOpenId(curveId);
      setDraft(null);
      setSaveDialogOpen(false);
      toast(`Saved as "${name}"${overwriteId ? ' (overwritten)' : ''}`, 'success');
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  const users = profile ? usedBy(profile.id) : [];

  const tiles: { value: string; label: string; points: CurvePoint[] | null; badge?: string }[] = [
    { value: 'none', label: '— not sequenced —', points: null },
    { value: 'flat', label: 'Flat 1.0 (no curve)', points: FLAT },
    ...Object.values(curves)
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((p) => {
        const n = usedBy(p.id).length;
        return { value: p.id, label: p.name, points: p.points, badge: n > 1 ? `${n} items` : undefined };
      }),
    { value: 'inline', label: 'Inline one-off…', points: profile ? profile.points : points },
  ];

  const windowOpen = openId !== null;
  const editing = draft !== null;
  const statusLine = editing
    ? 'Editing — one-off, not yet applied. Nothing shared is affected.'
    : profile
      ? `Shared profile "${profile.name}"${users.length > 1 ? ` — changes everything using it (${users.join(', ')})` : ''}`
      : 'Inline one-off — this item only';

  return (
    <div>
      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
          {title} — click a tile to open and edit it
        </div>
        <div style={{ maxHeight: 260, overflowY: 'auto', paddingRight: 4 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(112px, 1fr))', gap: 6 }}>
            {tiles.map((t) => (
              <button
                key={t.value}
                type="button"
                aria-label={t.label}
                aria-pressed={attachment === t.value}
                title={t.label}
                onClick={() => void selectTile(t.value)}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                  padding: 5, borderRadius: 'var(--radius)', background: 'var(--surface2)',
                  border: attachment === t.value ? '2px solid var(--accent2)' : '1px solid var(--border)',
                  cursor: 'pointer',
                }}
              >
                {t.points ? <CurveThumbnail points={t.points} /> : (
                  <div style={{
                    width: 96, height: 48, display: 'flex', alignItems: 'center',
                    justifyContent: 'center', color: 'var(--text-muted)', fontSize: 16,
                  }}>—</div>
                )}
                <span style={{
                  fontSize: 11, textAlign: 'center', overflow: 'hidden',
                  textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 106,
                }}>{t.label}</span>
                {t.badge && <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{t.badge}</span>}
              </button>
            ))}
          </div>
        </div>
      </div>

      {attachment === 'none' && noneNote && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>{noneNote}</div>
      )}
      {attachment === 'flat' && flatNote && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>{flatNote}</div>
      )}

      {windowOpen && (
        <div onClick={requestClose}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
                   display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '8vh' }}>
          <div className="card" onClick={(e) => e.stopPropagation()}
            style={{ width: 560, maxWidth: '92vw', maxHeight: '86vh', overflowY: 'auto', margin: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <div className="card-title" style={{ margin: 0, flex: 1 }}>
                {profile ? profile.name : attachment === 'inline' ? 'Inline one-off' : 'Flat 1.0'}
              </div>
              <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={requestClose}>✕ Close</button>
            </div>

            <CurveEditor points={points} onChange={setDraft} histogram={histogram} />

            <div style={{ fontSize: 11, color: 'var(--text-muted)', margin: '6px 0 10px' }}>
              {statusLine}
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {(profile || editing) && (
                <button style={{ fontSize: 11, padding: '2px 8px' }}
                  title="Copy the current curve into this item's own one-off — never touches the shared profile"
                  onClick={() => void applyOneOff()}>
                  {editing ? 'Apply edited one-off to this item' : 'Detach — edit just this item'}
                </button>
              )}
              {editing && (
                <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => setDraft(null)}>
                  Discard edits
                </button>
              )}
              <span style={{ flex: 1 }} />
              <button className="primary" style={{ fontSize: 11, padding: '2px 10px' }}
                title="Save this curve under a name — creates a new shared profile, or overwrites an existing one after a warning"
                onClick={() => setSaveDialogOpen(true)}>
                Save as named curve…
              </button>
            </div>
          </div>
        </div>
      )}

      {saveDialogOpen && (
        <SaveCurveDialog
          initialName={profile?.name ?? ''}
          curves={curves}
          usedBy={otherUsers}
          onCancel={() => setSaveDialogOpen(false)}
          onConfirm={(name, overwriteId) => void saveNamed(name, overwriteId)}
        />
      )}

      {footer}
    </div>
  );
}
