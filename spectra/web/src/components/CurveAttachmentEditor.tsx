/** Shared likelihood-curve attachment editor — extracted from the scene
 * Sequencing tab (2026-08-17, colour-set/group likelihood curves, owner
 * ask: "reuse the same kind of structure as for scenes") so scenes, colour
 * SETS, and colour GROUPS all edit curves through the identical component,
 * with the identical safety rule.
 *
 * Reworked 2026-08-19 (card reopened — his words: "I do not want them to be
 * expanded when I open the window... if I edit it it should immediately
 * change it to a one-off not default to saving the Curve"), then further
 * clarified the same day to a fully unambiguous spec:
 *
 *   1. The tile grid ("the selector") is NEVER rendered inline, expanded or
 *      collapsed. The default view is a single button — a live
 *      `CurveThumbnail` preview of the curve currently in effect — and
 *      pressing it is what "pulls the selector up" (a picker overlay). This
 *      is a stricter ask than PR #105's "starts collapsed": that still put
 *      the grid in the window by default (just closed); he ruled that
 *      reading out explicitly.
 *   2. Editing takes effect IMMEDIATELY as a one-off — no "Editing — one-off,
 *      not yet applied" pending state, no separate Apply button. His words:
 *      "the status change IS the apply." The safety property this used to
 *      get from a manual gate now comes from where the auto-write lands:
 *      every edit (drag/add/remove point) commits straight to THIS entry's
 *      own inline_points — never `curves[profileId]` — so "immediate" and
 *      "safe" are the same property, not opposed ones. Saving a SHARED,
 *      named profile is still only ever the explicit "Save as named
 *      curve…" action, and an overwrite is still only ever behind
 *      SaveCurveDialog's warning — nothing about that path changed.
 *
 * THE SAFETY RULE (updated but structurally the same shape as before): no
 * code path here writes an edited point into `curves[existingId]` except
 * SaveCurveDialog's own confirmed submit, which itself refuses to reuse an
 * existing name without the caller having answered its overwrite-warning
 * stage first. Every other write (`pushOneOffCommit`, `applyOneOff`)
 * targets THIS entry's own `inline_points` — never the shared profile — so
 * editing a shared curve is structurally incapable of retuning any other
 * entry's copy of it; only an explicit named save, confirmed past a
 * warning on a collision, can touch the shared store. The only thing that
 * changed is WHEN that entry-local write fires: on every edit tick
 * (coalesced — at most one request in flight, a tick that lands mid-request
 * folds into one follow-up with the latest points, same shape
 * ColorSetsPage's live-preview drag already uses) instead of behind a
 * manual Apply click.
 *
 * Picker/editor idiom: reuses the fixed-inset dark-overlay `.card` shape
 * already used twice in this file (the curve-edit window, SaveCurveDialog)
 * rather than a new popover — proven phone-safe at 390×844 since PR #105.
 */
import { useEffect, useRef, useState } from 'react';
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
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 120,
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

  const [pickerOpen, setPickerOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState<CurvePoint[] | null>(null);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  // Edit-session bookkeeping for the auto-commit-on-edit write (see file
  // docstring). `editSessionRef` guards a coalesced write that resolves
  // AFTER the user has already switched tiles/discarded from clobbering
  // whatever they switched to. `originalAttachmentRef`/`originalPointsRef`
  // capture what was attached before the current edit session, so "Revert"
  // can restore it exactly (including reverting an edited INLINE one-off
  // back to ITS pre-edit points, not just "kind inline" with whatever the
  // mutated draft now holds).
  const editSessionRef = useRef(0);
  const originalAttachmentRef = useRef<string | null>(null);
  const originalPointsRef = useRef<CurvePoint[]>(FLAT);
  const committedOneOff = useRef(false);
  const commitInFlight = useRef(false);
  const commitPending = useRef<{ pts: CurvePoint[]; token: number } | null>(null);

  useEffect(() => {
    editSessionRef.current += 1;
    setPickerOpen(false);
    setOpenId(null);
    setDraft(null);
    setSaveDialogOpen(false);
    committedOneOff.current = false;
    originalAttachmentRef.current = null;
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
      return true;
    } catch (e) {
      toast(`Attach failed: ${e}`, 'error');
      return false;
    }
  };

  const selectTile = async (value: string) => {
    editSessionRef.current += 1;
    setDraft(null);
    committedOneOff.current = false;
    const ok = await attach(value);
    if (!ok) return;
    const tile = tiles.find((t) => t.value === value);
    originalAttachmentRef.current = value;
    originalPointsRef.current = tile?.points ?? FLAT;
    setPickerOpen(false);
    setOpenId(value === 'inline' || curves[value] ? value : null);
  };

  const requestClose = () => {
    setOpenId(null);
    setDraft(null);
    setSaveDialogOpen(false);
  };

  // Coalesced auto-commit: at most one write in flight, a tick that lands
  // mid-request folds into a single follow-up with the latest points —
  // same shape as ColorSetsPage's live-drag preview updates. `token` pins
  // this call to the edit session it was scheduled under; if the session
  // has since moved on (tile switched, reverted, id changed) the queued
  // write is dropped rather than clobbering whatever's current now.
  const pushOneOffCommit = async (pts: CurvePoint[], token: number) => {
    if (commitInFlight.current) { commitPending.current = { pts, token }; return; }
    if (editSessionRef.current !== token) return;
    commitInFlight.current = true;
    try {
      await attachMut.mutateAsync({ entryId: id, attachment: { kind: 'inline', points: pts } });
      if (editSessionRef.current === token && !committedOneOff.current) {
        committedOneOff.current = true;
        toast('Now a one-off — this item only', 'success');
      }
    } catch (e) {
      if (editSessionRef.current === token) toast(`Auto-apply failed: ${e}`, 'error');
    } finally {
      commitInFlight.current = false;
      const pending = commitPending.current;
      commitPending.current = null;
      if (pending) void pushOneOffCommit(pending.pts, pending.token);
    }
  };

  const handleCurveChange = (pts: CurvePoint[]) => {
    setDraft(pts);
    void pushOneOffCommit(pts, editSessionRef.current);
  };

  // Detach without editing — fork a private copy now, decoupled from any
  // FUTURE edits to the shared profile, without changing today's shape.
  const applyOneOff = async () => {
    const pts = draft ?? points;
    try {
      await attachMut.mutateAsync({ entryId: id, attachment: { kind: 'inline', points: pts } });
      editSessionRef.current += 1;
      originalAttachmentRef.current = 'inline';
      originalPointsRef.current = pts;
      committedOneOff.current = false;
      setDraft(null);
      setOpenId('inline');
      toast('Detached — a one-off copy, this item only', 'success');
    } catch (e) {
      toast(`Detach failed: ${e}`, 'error');
    }
  };

  const revertEdits = async () => {
    const token = ++editSessionRef.current;
    const original = originalAttachmentRef.current;
    setDraft(null);
    committedOneOff.current = false;
    if (original === null) return;
    try {
      if (original === 'inline') {
        await attachMut.mutateAsync({ entryId: id, attachment: { kind: 'inline', points: originalPointsRef.current } });
      } else {
        await attach(original);
      }
      if (editSessionRef.current === token) toast('Reverted to the original attachment', 'success');
    } catch (e) {
      if (editSessionRef.current === token) toast(`Revert failed: ${e}`, 'error');
    }
  };

  const saveNamed = async (name: string, overwriteId: string | null) => {
    const curveId = overwriteId ?? crypto.randomUUID();
    const pts = draft ?? points;
    try {
      await saveCurvesMut.mutateAsync({ ...curves, [curveId]: { id: curveId, name, points: pts } });
      await attach(curveId);
      editSessionRef.current += 1;
      originalAttachmentRef.current = curveId;
      originalPointsRef.current = pts;
      committedOneOff.current = false;
      setOpenId(curveId);
      setDraft(null);
      setSaveDialogOpen(false);
      toast(`Saved as "${name}"${overwriteId ? ' (overwritten)' : ''}`, 'success');
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  const users = profile ? usedBy(profile.id) : [];

  const editing = draft !== null;
  const oneOffNow = editing || attachment === 'inline';
  const attachmentLabel = profile ? profile.name
    : attachment === 'inline' ? 'Inline one-off'
    : attachment === 'flat' ? 'Flat 1.0 (no curve)'
    : '— not sequenced —';
  const statusLine = oneOffNow
    ? 'One-off — this item only. Nothing shared is affected.'
    : profile
      ? `Shared profile "${profile.name}"${users.length > 1 ? ` — changes everything using it (${users.join(', ')})` : ''}`
      : attachment === 'flat' ? 'Flat 1.0 — no curve' : 'Not sequenced';

  return (
    <div>
      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
          {title}
        </div>
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          title="Tap to change or edit this curve"
          style={{
            display: 'flex', alignItems: 'center', gap: 10, width: '100%',
            padding: 6, borderRadius: 'var(--radius)', background: 'var(--surface2)',
            border: '1px solid var(--border)', cursor: 'pointer', textAlign: 'left',
          }}
        >
          <CurveThumbnail points={points} width={200} height={64}
            style={{ maxWidth: 128, flexShrink: 0 }} />
          <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
            <span style={{
              fontSize: 12, fontWeight: 600, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%',
            }}>
              {attachmentLabel}
            </span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {oneOffNow ? 'one-off — this item only' : profile ? 'shared profile' : 'tap to change'}
            </span>
          </span>
        </button>
      </div>

      {attachment === 'none' && noneNote && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>{noneNote}</div>
      )}
      {attachment === 'flat' && flatNote && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>{flatNote}</div>
      )}

      {pickerOpen && (
        <div onClick={() => setPickerOpen(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
                   display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '8vh' }}>
          <div className="card" onClick={(e) => e.stopPropagation()}
            style={{ width: 420, maxWidth: '92vw', maxHeight: '86vh', overflowY: 'auto', margin: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <div className="card-title" style={{ margin: 0, flex: 1 }}>{title} — pick one</div>
              <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => setPickerOpen(false)}>✕ Close</button>
            </div>
            <div style={{ maxHeight: '68vh', overflowY: 'auto', paddingRight: 4 }}>
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
        </div>
      )}

      {openId !== null && (
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

            <CurveEditor points={points} onChange={handleCurveChange} histogram={histogram} />

            <div style={{ fontSize: 11, color: 'var(--text-muted)', margin: '6px 0 10px' }}>
              {statusLine}
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {!editing && profile && (
                <button style={{ fontSize: 11, padding: '2px 8px' }}
                  title="Copy the current curve into this item's own one-off now — never touches the shared profile"
                  onClick={() => void applyOneOff()}>
                  Detach — make this a one-off copy
                </button>
              )}
              {editing && (
                <button style={{ fontSize: 11, padding: '2px 8px' }}
                  title="Undo this edit — restore what was attached before you started"
                  onClick={() => void revertEdits()}>
                  ↺ Revert to original
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
          initialName={profile?.name
            ?? (originalAttachmentRef.current ? curves[originalAttachmentRef.current]?.name : undefined)
            ?? ''}
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
