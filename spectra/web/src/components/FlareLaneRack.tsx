/** One band's vertical lane rack — the drag surface a flare kind lands on to
 * attach it (Scenes tab, Flares/Charges-Lulls-Drops tabs). A lane is a
 * POSITION in the band's own kinds dict (spectra/models/scene.py FlareBand.
 * kinds: name -> scale), not a new stored concept — see flareKindOps.ts's
 * header for why position is load-bearing (same-param precedence in
 * spectra/services/scene_response.py). Purely presentational: all pointer
 * tracking and the actual scene mutation live in ResponseTab.tsx, which
 * owns the single drag gesture shared across every band on the page (a
 * card can be dropped on ANY band's rack, not just its own parent's). */
import { NumberInput } from './inputs';
import type { FlareBand, FlareKind, ResponseClass } from '../types';

const kindIcon = (k: FlareKind): string =>
  k.type === 'drift_jump' ? (k.jump === 'color_set' ? '🎨' : '🎲')
    : k.type === 'momentary' ? '↩' : '⚓';

export default function FlareLaneRack({
  cls, bandIdx, band, visibleLanes, canAddLane, kindsByName,
  draggingName, overLaneIdx,
  onAddLane, onStartDrag, onDetach, onSetScale,
}: {
  cls: ResponseClass;
  bandIdx: number;
  band: FlareBand;
  visibleLanes: number;
  canAddLane: boolean;
  kindsByName: Record<string, FlareKind>;
  draggingName: string | null;
  overLaneIdx: number | null;
  onAddLane: () => void;
  onStartDrag: (name: string, source: { cls: ResponseClass; bandIdx: number } | null) =>
    (e: React.PointerEvent) => void;
  onDetach: (name: string) => void;
  onSetScale: (name: string, value: number) => void;
}) {
  const occupants = Object.keys(band.kinds ?? {});
  const lanes = Array.from({ length: visibleLanes }, (_, i) => occupants[i] ?? null);
  const LANE_HEIGHT = 124;

  return (
    <div style={{
      display: 'flex', gap: 6, alignItems: 'flex-start', flexWrap: 'nowrap',
      overflowX: 'auto', paddingBottom: 2, WebkitOverflowScrolling: 'touch',
    }}>
      {lanes.map((occupant, laneIdx) => {
        const kind = occupant ? kindsByName[occupant] : null;
        const hovered = overLaneIdx === laneIdx;
        return (
          <div key={laneIdx}
            data-lane data-cls={cls} data-band={bandIdx} data-lane-idx={laneIdx}
            style={{
              width: 108, minHeight: LANE_HEIGHT, flexShrink: 0, borderRadius: 8, padding: '6px 7px',
              border: `1.5px ${kind ? 'solid' : 'dashed'} ${hovered ? 'var(--accent)' : (kind ? 'var(--border)' : 'var(--text-muted)')}`,
              background: hovered ? 'rgba(168,85,247,0.12)' : (kind ? 'var(--surface2)' : 'transparent'),
              opacity: kind && draggingName === kind.name ? 0.35 : 1,
              display: 'flex', flexDirection: 'column', gap: 6, touchAction: 'none',
            }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
              lane {laneIdx + 1}
            </div>
            {kind ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1, justifyContent: 'space-between' }}>
                <div
                  onPointerDown={onStartDrag(kind.name, { cls, bandIdx })}
                  style={{ fontSize: 11, fontWeight: 600, cursor: 'grab', userSelect: 'none' }}
                  title={`${kind.name} — drag to move to another lane, tap to edit`}>
                  {kindIcon(kind)} {kind.name}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>×</span>
                  <NumberInput value={band.kinds[kind.name]} min={0} step={0.1} width={44}
                    onChange={(v) => onSetScale(kind.name, v ?? 1)} />
                  <button style={{ fontSize: 10, padding: '1px 5px', marginLeft: 'auto' }}
                    title="Detach from this band"
                    onClick={() => onDetach(kind.name)}>✕</button>
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 10, color: 'var(--text-muted)', flex: 1,
                            display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                drop here
              </div>
            )}
          </div>
        );
      })}
      {canAddLane && (
        <button style={{ fontSize: 16, width: 28, height: LANE_HEIGHT, padding: 0, flexShrink: 0, alignSelf: 'flex-start' }}
          title="Add another lane to this band (up to 4)"
          onClick={onAddLane}>
          +
        </button>
      )}
    </div>
  );
}
