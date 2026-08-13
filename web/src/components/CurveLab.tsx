/** CurveLab — storybook-style dev harness for CurveEditor, mounted behind a
 * collapsed card at the bottom of the Scenes page. Edits are LOCAL ONLY: the
 * sequencing decisions that say what a curve attaches to are still open, so
 * there is deliberately no attachment or save UI here. The histogram underlay
 * is live: the trigger-intensity census over the whole profile library. */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '../api/client';
import HelpLink from '../help/HelpLink';
import CurveEditor, { type CurvePoint } from './CurveEditor';

interface IntensityHistogram {
  bins: number;
  counts: number[];
  total: number;
}

const DEMO_RAMP: CurvePoint[] = [
  { x: 0, y: 0 },
  { x: 0.65, y: 0.2 },
  { x: 1, y: 1 },
];

export default function CurveLab() {
  const [points, setPoints] = useState<CurvePoint[]>(DEMO_RAMP);
  const { data: hist } = useQuery({
    queryKey: ['sequencer-intensity-histogram'],
    queryFn: () => apiGet<IntensityHistogram>('/sequencer/intensity-histogram'),
    staleTime: 300_000,
  });

  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
        Preview of the sequencer likelihood-curve editor — edits stay on this page;
        curves attach to nothing yet. <HelpLink topic="curve-editor" />
      </div>
      <CurveEditor points={points} onChange={setPoints} histogram={hist?.counts} />
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 11, color: 'var(--text-muted)' }}>
        <span>
          {points.length} point{points.length === 1 ? '' : 's'}
          {hist ? ` · underlay: ${hist.total.toLocaleString()} library trigger intensities` : ''}
        </span>
        <button style={{ fontSize: 11, padding: '2px 8px', marginLeft: 'auto' }}
          onClick={() => setPoints(DEMO_RAMP)}>
          Reset demo curve
        </button>
      </div>
    </div>
  );
}
