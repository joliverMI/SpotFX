/** Shift-All-Triggers: hidden behind a small chip; expands to a full-width
 * slider row attached to the shape canvas. The offset previews live on the
 * canvas (view.triggerOffsetMs) and only moves data on an explicit commit.
 * Range ±10s; slider steps 10ms, number input takes exact values. */
import { useBuilderStore } from '../store';

const MAX_MS = 10_000;

// Keep in lockstep with components/ModeBar.tsx's SETLIST_SLOTS_ENABLED —
// per-song Set List "slot" overrides retired 2026-08-17 (docs/SPECTRA_SPEC.md
// OQ-5/§41). His setlist_triggers data is untouched on disk; this just stops
// "Commit ALL" from writing shifted timestamps into those slot lists too.
const SETLIST_SLOTS_ENABLED = false;

export default function ShiftAllControl({
  open,
  setOpen,
  durationMs,
}: {
  open: boolean;
  setOpen: (v: boolean) => void;
  durationMs: number;
}) {
  const offset = useBuilderStore((s) => s.triggerPreviewOffsetMs);
  const setOffset = useBuilderStore((s) => s.setTriggerPreviewOffset);
  const profile = useBuilderStore((s) => s.profile);
  const slotId = useBuilderStore((s) => s.slotId);

  if (!open) return null;

  const clampMs = (ms: number) => Math.max(0, Math.min(durationMs, Math.round(ms)));
  const shiftList = (ts: { timestamp_ms: number }[]) => {
    for (const t of ts) t.timestamp_ms = clampMs(t.timestamp_ms + offset);
  };

  const commit = (all: boolean) => {
    if (!offset) return;
    const st = useBuilderStore.getState();
    st.mutateProfile((p) => {
      if (all) {
        shiftList(p.triggers);
        if (SETLIST_SLOTS_ENABLED) {
          for (const list of Object.values(p.setlist_triggers)) shiftList(list);
        }
      } else if (slotId) {
        if (!p.setlist_triggers[slotId]) {
          p.setlist_triggers[slotId] = JSON.parse(JSON.stringify(p.triggers));
        }
        shiftList(p.setlist_triggers[slotId]);
      } else {
        shiftList(p.triggers);
      }
    });
    setOffset(0);
  };

  const sign = offset >= 0 ? '+' : '';
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 4px',
                  borderTop: '1px solid var(--border)', marginTop: 2 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', flex: 'none' }}>Shift all</span>
      <input
        type="range"
        min={-MAX_MS}
        max={MAX_MS}
        step={10}
        value={offset}
        onChange={(e) => setOffset(Number(e.target.value))}
        onDoubleClick={() => setOffset(0)}
        title="Preview shift for every trigger — double-click to zero"
        style={{ flex: 1, minWidth: 200 }}
      />
      <input
        type="number"
        min={-MAX_MS}
        max={MAX_MS}
        step={1}
        value={offset}
        onChange={(e) => setOffset(Math.max(-MAX_MS, Math.min(MAX_MS, Number(e.target.value) || 0)))}
        style={{ width: 76, fontFamily: 'monospace' }}
      />
      <span style={{ fontSize: 11, color: offset ? 'var(--accent2)' : 'var(--text-muted)',
                     width: 64, fontFamily: 'monospace' }}>
        {sign}{offset}ms
      </span>
      <button disabled={!profile || !offset} style={{ fontSize: 11 }}
        title={slotId ? 'Bake the shift into this setlist slot only' : 'Bake the shift into the Default triggers'}
        onClick={() => commit(false)}>
        Commit {slotId ? 'slot' : 'Default'}
      </button>
      <button disabled={!profile || !offset} style={{ fontSize: 11 }}
        title="Bake the shift into Default AND every setlist slot"
        onClick={() => commit(true)}>
        Commit ALL
      </button>
      <button disabled={!offset} style={{ fontSize: 11 }} onClick={() => setOffset(0)}>
        Reset
      </button>
      <button style={{ fontSize: 11 }} title="Hide (keeps any uncommitted preview at 0)"
        onClick={() => { setOffset(0); setOpen(false); }}>
        ✕
      </button>
    </div>
  );
}
