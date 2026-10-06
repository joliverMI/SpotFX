/** The drop-sequence EDITS for one song (drop-detection plan, phase 4):
 * every POST to spectra/api/drop_sequences.py's edit routes, the undo/redo
 * stack over the before/after pair each one answers, and the last error.
 *
 * Edits run ONE AT A TIME, in the order they were asked for (a keyboard
 * step's save, then the Enter that confirms it). Each answer carries the
 * song's merged view after the edit, which replaces the cached view at
 * once — the canvas never waits on a refetch to show what he did. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiPost } from '../../api/client';
import type { DropSequencesResponse, Handle } from '../dropSequences';
import {
  EMPTY_STACKS, afterRedo, afterUndo, editErrorText, guardInFlight, pushEdit, pushEditChanged,
  redoRequest, undoRequest, type DropEdits, type UndoEntry, type UndoStacks,
} from '../dropEdit';

interface EditAnswer {
  result: unknown;
  view: DropSequencesResponse;
  before: DropEdits;
  after: DropEdits;
  rev_before: string;
  rev_after: string;
}

export interface DropEditor {
  canUndo: boolean;
  canRedo: boolean;
  undoLabel: string | null;
  redoLabel: string | null;
  busy: boolean;
  error: string | null;
  clearError: () => void;
  /** the last thing that happened, in words ("confirmed 0:47.6", "undone: …") */
  note: string | null;
  confirm: (key: string, what?: string) => Promise<string | null>;
  dismiss: (key: string, what?: string) => Promise<string | null>;
  revert: (key: string, what?: string) => Promise<string | null>;
  moveHandles: (key: string, handles: Partial<Record<Handle, number | null>>, what?: string) => Promise<string | null>;
  member: (key: string, handle: 'lull' | 'charge', off: boolean) => Promise<string | null>;
  fill: (key: string, handle: 'lull' | 'charge') => Promise<string | null>;
  review: (key: string, choice: 'keep' | 'take') => Promise<string | null>;
  add: (dropMs: number) => Promise<string | null>;
  confirmAll: () => Promise<string[] | null>;
  redetect: () => Promise<boolean>;
  /** resolves to the key of the sequence the step was about (to select it) */
  undo: () => Promise<string | null>;
  redo: () => Promise<string | null>;
}

export function useDropEditor(uri: string | null): DropEditor {
  const qc = useQueryClient();
  const [stacks, setStacks] = useState<UndoStacks>(EMPTY_STACKS);
  const stacksRef = useRef(stacks);
  stacksRef.current = stacks;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const uriRef = useRef(uri);
  uriRef.current = uri;
  // guards undo()/redo() against a second call reading the same stale
  // top-of-stack entry while the first is still queued/in flight — e.g.
  // holding Ctrl+Z fires keydown repeats faster than one round trip
  const undoRedoInFlight = useRef(false);

  useEffect(() => {
    setStacks(EMPTY_STACKS);
    setError(null);
    setNote(null);
  }, [uri]);

  const putView = useCallback((u: string, view: DropSequencesResponse) => {
    qc.setQueryData<DropSequencesResponse>(['drop-sequences', u], (old) =>
      ({ ...(old ?? {}), ...view } as DropSequencesResponse));
  }, [qc]);

  /** One edit, queued behind any in flight. Resolves to the answer, or null
   * (the error is kept for the page to show; the view is refetched so the
   * page is never left showing an edit that did not land). */
  const run = useCallback(<T,>(path: string, body: Record<string, unknown>,
    after: (a: EditAnswer, u: string) => T): Promise<T | null> => {
    const u = uriRef.current;
    if (!u) return Promise.resolve(null);
    const job = queue.current.then(async () => {
      setBusy(true);
      try {
        const a = await apiPost<EditAnswer>(`/drop-sequences/${path}`, { uri: u, ...body });
        if (uriRef.current === u) {
          putView(u, a.view);
          setError(null);
        }
        return after(a, u);
      } catch (err) {
        if (uriRef.current === u) {
          setError(editErrorText(err));
          // a stale undo (409): his edits changed elsewhere, so no step on
          // either stack still describes them — start the stacks again
          if (err instanceof Error && err.message.includes('→ 409')) setStacks(EMPTY_STACKS);
          void qc.invalidateQueries({ queryKey: ['drop-sequences', u] });
        }
        return null;
      } finally {
        setBusy(false);
      }
    });
    queue.current = job.catch(() => undefined);
    return job;
  }, [putView, qc]);

  const edit = useCallback((path: string, body: Record<string, unknown>, label: string,
    keyOf: (a: EditAnswer) => string | null) =>
    run(path, body, (a, u) => {
      const key = keyOf(a);
      if (uriRef.current === u) {
        const entry: UndoEntry = {
          label, before: a.before, after: a.after,
          revBefore: a.rev_before, revAfter: a.rev_after, key,
        };
        // pushEditChanged is the one place that decides whether anything
        // actually changed; a note is shown only when it did, or a no-op
        // edit would claim a success that never happened
        let changed = false;
        setStacks((st) => {
          const [next, did] = pushEditChanged(st, entry);
          changed = did;
          return next;
        });
        if (changed) setNote(label);
      }
      return key;
    }), [run]);

  const asKey = (fallback: string) => (a: EditAnswer) =>
    (typeof a.result === 'string' ? a.result : fallback);

  const confirm = useCallback((key: string, what = '') =>
    edit('confirm', { key }, `confirmed${what ? ` ${what}` : ''}`, asKey(key)), [edit]);
  const dismiss = useCallback((key: string, what = '') =>
    edit('dismiss', { key }, key.startsWith('added:') ? `removed${what ? ` ${what}` : ''}`
      : `not a drop${what ? `: ${what}` : ''}`, asKey(key)), [edit]);
  const revert = useCallback((key: string, what = '') =>
    edit('revert', { key }, `back to detected${what ? `: ${what}` : ''}`, () => key), [edit]);
  const moveHandles = useCallback((key: string, handles: Partial<Record<Handle, number | null>>,
    what?: string) =>
    edit('handles', { key, handles }, what ?? `moved ${Object.keys(handles).join(' + ')}`, asKey(key)), [edit]);
  const member = useCallback((key: string, handle: 'lull' | 'charge', off: boolean) =>
    edit('member', { key, handle, off }, `${handle} ${off ? 'off' : 'on'}`, asKey(key)), [edit]);
  const fill = useCallback((key: string, handle: 'lull' | 'charge') =>
    edit('fill', { key, handle }, `added a ${handle}`, asKey(key)), [edit]);
  const review = useCallback((key: string, choice: 'keep' | 'take') =>
    edit('review', { key, choice }, choice === 'keep' ? 'kept your place' : 'took the new place',
      asKey(key)), [edit]);
  const add = useCallback((dropMs: number) =>
    edit('add', { drop_ms: Math.round(dropMs) }, 'added a drop', asKey('')), [edit]);
  const confirmAll = useCallback(() =>
    run('confirm-all', {}, (a, u) => {
      const keys = Array.isArray(a.result) ? (a.result as string[]) : [];
      if (uriRef.current === u) {
        setStacks((st) => pushEdit(st, {
          label: `confirmed ${keys.length} confident`, before: a.before, after: a.after,
          revBefore: a.rev_before, revAfter: a.rev_after, key: null,
        }));
        setNote(keys.length ? `confirmed ${keys.length} confident detection${keys.length === 1 ? '' : 's'}`
          : 'nothing confident left to confirm');
      }
      return keys;
    }), [run]);

  const redetect = useCallback(async () => {
    const u = uriRef.current;
    if (!u) return false;
    setBusy(true);
    try {
      const view = await apiPost<DropSequencesResponse>('/drop-sequences/redetect', { uri: u });
      if (uriRef.current === u) {
        putView(u, view);
        setNote('detected again — your edits are kept');
        setError(null);
      }
      return true;
    } catch (err) {
      setError(editErrorText(err));
      return false;
    } finally {
      setBusy(false);
    }
  }, [putView]);

  const undo = useCallback(() => guardInFlight(undoRedoInFlight, async () => {
    const e = stacksRef.current.undo[stacksRef.current.undo.length - 1];
    if (!e) return null;
    const ok = await run('restore', undoRequest(e) as unknown as Record<string, unknown>, () => true);
    if (ok) {
      setStacks((st) => afterUndo(st));
      setNote(`undone: ${e.label}`);
      return e.key;
    }
    return null;
  }, null), [run]);

  const redo = useCallback(() => guardInFlight(undoRedoInFlight, async () => {
    const e = stacksRef.current.redo[stacksRef.current.redo.length - 1];
    if (!e) return null;
    const ok = await run('restore', redoRequest(e) as unknown as Record<string, unknown>, () => true);
    if (ok) {
      setStacks((st) => afterRedo(st));
      setNote(`redone: ${e.label}`);
      return e.key;
    }
    return null;
  }, null), [run]);

  const u = stacks.undo[stacks.undo.length - 1];
  const r = stacks.redo[stacks.redo.length - 1];
  return {
    canUndo: !!u, canRedo: !!r, undoLabel: u?.label ?? null, redoLabel: r?.label ?? null,
    busy, error, clearError: () => setError(null), note,
    confirm, dismiss, revert, moveHandles, member, fill, review, add, confirmAll, redetect,
    undo, redo,
  };
}
