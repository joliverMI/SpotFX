/** Shape Map editor — text-defined geometry for shaped LED matrices.
 *
 * Edits a LedFX virtual's `shape v1` map (which cells of the render grid are
 * real LEDs + strip order). Validate runs a dry-run compile on LedFX and
 * either lists per-line errors or previews the shape on a canvas: live LEDs
 * as dots, in-silhouette holes hollow, catchment coverage tinted per LED.
 * Apply pushes the map (LedFX regenerates the virtual's segments from it and
 * starts kernel-resampling effects onto the real LEDs).
 */
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from '../api/client';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';

interface ShapeError { line: number; msg: string }
interface DryRun {
  status: string;
  errors?: ShapeError[];
  summary?: {
    width: number; height: number; live: number; gaps: number;
    device: string; digest: string; in_sync: boolean; resampling: boolean;
  } | null;
  cells?: [number, number, number][];   // [row, col, led_index]
  coverage?: number[];                  // per render cell: owner LED or -1
  truncated?: number;
}

const GUIDE = `shape v1                      # required header
grid 72 x 37                  # render grid, W x H
device crystal                # physical output device id
gap gap-crystal-mapper        # dummy device id for dead cells
parity odd                    # live iff (col+row)%2==1 (even: ==0; none: all)
row 0: 17-51 holes 21,23      # row 0: parity cols in [17,51] minus holes
rows 5-7: 12-58               # same extent for a row range
cell +10,3                    # escape hatch: force one cell live / dead
order:                        # strip order (device indices 0..N-1)
  explicit 1,16 0,17 1,18     # exact r,c walk for irregular sections
  serpentine rows 2-34 first desc   # complete rows, alternating direction

Authoring (for an LLM): prefer parity + row extents for the regular body;
use "holes" for missing LEDs inside an extent; use "explicit" order lines
only where the physical strip path is irregular (e.g. interleaved pole
rows). If no order block is given, serpentine over all rows (row 0
ascending) is assumed. Validate reports every error with its line number.`;

export default function ShapeMapDialog({
  virtualId,
  onClose,
}: {
  virtualId: string;
  onClose: () => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dry, setDry] = useState<DryRun | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [summaryLine, setSummaryLine] = useState<string>('');

  useEffect(() => {
    apiGet<{ shape_map: string; compiled: DryRun['summary'] }>(`/shape-maps/${virtualId}`)
      .then((res) => {
        setText(res.shape_map ?? '');
        if (res.compiled) {
          setSummaryLine(
            `current: ${res.compiled.live} LEDs on ${res.compiled.width}×${res.compiled.height}` +
            `${res.compiled.in_sync ? '' : ' — OUT OF SYNC with segments'}` +
            `${res.compiled.resampling ? ' · resampling on' : ''}`,
          );
        } else {
          setSummaryLine('no shape map set — effects are point-sampled');
        }
        setLoaded(true);
      })
      .catch((e) => { toast(`Load failed: ${e}`, 'error'); setLoaded(true); });
  }, [virtualId]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (dryRun: boolean) => {
    setBusy(true);
    try {
      const res = await apiPost<DryRun>(`/shape-maps/${virtualId}`, { text, dry_run: dryRun });
      setDry(res);
      if (res.status === 'success' && !dryRun) {
        toast('Shape map applied', 'success');
        void qc.invalidateQueries({ queryKey: ['ledfx-virtuals'] });
        if (res.summary) {
          setSummaryLine(`applied: ${res.summary.live} LEDs · in sync · resampling on`);
        }
      }
    } catch (e) {
      toast(`Request failed: ${e}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
               display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
               paddingTop: '6vh', overflowY: 'auto' }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 760, maxWidth: '94vw', margin: 0 }}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Shape map — {virtualId}
          <HelpLink topic="shape-maps" />
          <button style={{ marginLeft: 'auto', fontSize: 12 }} onClick={onClose}>Close</button>
        </div>

        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>{summaryLine}</div>

        <textarea
          value={text}
          onChange={(e) => { setText(e.target.value); setDry(null); }}
          spellCheck={false}
          placeholder={loaded ? 'shape v1\ngrid 72 x 37\n…' : 'Loading…'}
          style={{
            width: '100%', minHeight: 220, fontFamily: 'monospace', fontSize: 12,
            whiteSpace: 'pre', resize: 'vertical',
          }}
        />

        <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
          <button disabled={busy || !text.trim()} onClick={() => run(true)}>Validate</button>
          <button className="primary" disabled={busy || !text.trim()} onClick={() => run(false)}>
            Apply
          </button>
          <button style={{ fontSize: 12 }} onClick={() => setGuideOpen((g) => !g)}>
            {guideOpen ? 'Hide' : 'Show'} authoring guide
          </button>
          {dry?.status === 'success' && dry.summary && (
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              ✓ {dry.summary.live} LEDs · {dry.summary.gaps} gaps
              {dry.truncated ? ` · ${dry.truncated} truncated!` : ''}
            </span>
          )}
        </div>

        {dry?.status === 'error' && dry.errors && (
          <div style={{
            marginTop: 8, padding: 8, borderRadius: 'var(--radius)',
            border: '1px solid var(--danger)', fontSize: 12, fontFamily: 'monospace',
            maxHeight: 140, overflowY: 'auto',
          }}>
            {dry.errors.map((e, i) => (
              <div key={i} style={{ color: 'var(--danger)' }}>
                {e.line > 0 ? `line ${e.line}: ` : ''}{e.msg}
              </div>
            ))}
          </div>
        )}

        {dry?.status === 'success' && dry.cells && (
          <ShapeCanvas dry={dry} />
        )}

        {guideOpen && (
          <pre style={{
            marginTop: 8, padding: 8, fontSize: 11, lineHeight: 1.45,
            background: 'var(--surface2)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', overflowX: 'auto', whiteSpace: 'pre',
          }}>{GUIDE}</pre>
        )}
      </div>
    </div>
  );
}

/** Read-only preview: live LEDs as dots (hue = catchment owner so coverage
 * reads as tinted patches), orphan cells dimmed, silhouette holes hollow. */
function ShapeCanvas({ dry }: { dry: DryRun }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    const s = dry.summary;
    if (!canvas || !s || !dry.cells || !dry.coverage) return;
    const scale = Math.max(4, Math.min(12, Math.floor(720 / s.width)));
    canvas.width = s.width * scale;
    canvas.height = s.height * scale;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = '#101014';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    // catchment coverage: tint each covered render cell by its owner LED
    for (let cell = 0; cell < dry.coverage.length; cell++) {
      const owner = dry.coverage[cell];
      if (owner < 0) continue;
      const r = Math.floor(cell / s.width);
      const c = cell % s.width;
      ctx.fillStyle = `hsl(${(owner * 47) % 360} 45% 22%)`;
      ctx.fillRect(c * scale, r * scale, scale, scale);
    }
    // live LEDs on top
    for (const [r, c] of dry.cells) {
      ctx.fillStyle = '#ffd54a';
      ctx.beginPath();
      ctx.arc((c + 0.5) * scale, (r + 0.5) * scale, Math.max(1.5, scale * 0.28), 0, Math.PI * 2);
      ctx.fill();
    }
  }, [dry]);
  return (
    <div style={{ marginTop: 8, overflowX: 'auto' }}>
      <canvas ref={ref} style={{ display: 'block', borderRadius: 4, maxWidth: '100%' }} />
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
        dots = real LEDs · tinted patches = each LED's resample catchment · dark = orphan cells
      </div>
    </div>
  );
}
