/** One band's vertical lane rack — the drag surface a flare kind lands on to
 * attach it (Scenes tab, Flares/Charges-Lulls-Drops tabs). A lane holds ONE
 * OR MORE kinds: a one-kind lane always fires; a lane holding several is a
 * POOL OF ALTERNATIVES — at fire time the engine picks exactly one member
 * (even weights, re-rolled every fire) and every lane's pick fires together
 * (owner ask 2026-08-21, the SpotFX MorphLane shape; FlareBand.kind_lanes in
 * spectra/models/scene.py, pick in scene_response.resolve_lane_picks).
 *
 * Drop targets, hit-tested by ResponseTab via data attributes:
 *   - an occupied lane's body  → JOIN its pool (mode "join", anchor = the
 *     pool's first member as rendered);
 *   - the slim strip before each lane, and any empty trailing lane → land
 *     as the kind's OWN new lane at that position (mode "insert", anchor =
 *     the pool the strip precedes, '' = at the end) — the pre-lanes
 *     shift-not-swap gesture, kept because lane ORDER still decides
 *     same-param precedence (flareKindOps.ts header).
 * Purely presentational: all pointer tracking and the actual scene mutation
 * live in ResponseTab.tsx / flareKindOps.moveKindToLane. */
import { NumberInput } from './inputs';
import { bandPools } from '../scenes/tabs/flareKindOps';
import type { FlareBand, FlareKind, ResponseClass } from '../types';

const kindIcon = (k: FlareKind): string =>
  k.type === 'drift_jump' ? (k.jump === 'color_set' ? '🎨' : '🎲')
    : k.type === 'color_rotate' ? '🔄'
      : k.type === 'firework_burst' ? '🎆'
        : k.type === 'momentary' ? '↩' : '⚓';

export interface RackDropTarget { mode: 'insert' | 'join'; anchor: string | null; }

export default function FlareLaneRack({
  cls, bandIdx, band, visibleLanes, canAddLane, kindsByName,
  draggingName, overTarget,
  onAddLane, onStartDrag, onDetach, onSetScale,
}: {
  cls: ResponseClass;
  bandIdx: number;
  band: FlareBand;
  visibleLanes: number;
  canAddLane: boolean;
  kindsByName: Record<string, FlareKind>;
  draggingName: string | null;
  overTarget: RackDropTarget | null;
  onAddLane: () => void;
  onStartDrag: (name: string, source: { cls: ResponseClass; bandIdx: number } | null) =>
    (e: React.PointerEvent) => void;
  onDetach: (name: string) => void;
  onSetScale: (name: string, value: number) => void;
}) {
  const pools = bandPools(band);
  const emptySlots = Math.max(0, visibleLanes - pools.length);
  const LANE_HEIGHT = 124;
  const dragging = draggingName !== null;

  const insertHovered = (anchor: string | null) =>
    overTarget?.mode === 'insert' && (overTarget.anchor ?? null) === anchor;

  const insertStrip = (anchor: string | null, key: string) => (
    <div key={key}
      data-lane data-cls={cls} data-band={bandIdx}
      data-lane-mode="insert" data-lane-anchor={anchor ?? ''}
      title="Drop here to make this a lane of its own"
      style={{
        width: 10, minHeight: LANE_HEIGHT, flexShrink: 0, borderRadius: 4,
        alignSelf: 'stretch', touchAction: 'none',
        background: insertHovered(anchor) ? 'var(--accent)' : 'transparent',
        border: `1px dashed ${dragging ? 'var(--text-muted)' : 'transparent'}`,
        opacity: insertHovered(anchor) ? 1 : dragging ? 0.5 : 1,
      }} />
  );

  return (
    <div style={{
      display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'nowrap',
      overflowX: 'auto', paddingBottom: 2, WebkitOverflowScrolling: 'touch',
    }}>
      {pools.map((pool, poolIdx) => {
        const joinHovered = overTarget?.mode === 'join'
          && overTarget.anchor === pool.members[0];
        return [
          insertStrip(pool.members[0], `strip-${poolIdx}`),
          <div key={`pool-${poolIdx}`}
            data-lane data-cls={cls} data-band={bandIdx}
            data-lane-mode="join" data-lane-anchor={pool.members[0]}
            style={{
              width: 108, minHeight: LANE_HEIGHT, flexShrink: 0, borderRadius: 8, padding: '6px 7px',
              border: `1.5px solid ${joinHovered ? 'var(--accent)' : 'var(--border)'}`,
              background: joinHovered ? 'rgba(168,85,247,0.12)' : 'var(--surface2)',
              display: 'flex', flexDirection: 'column', gap: 6, touchAction: 'none',
            }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase',
                          letterSpacing: 0.4, display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ whiteSpace: 'nowrap' }}>lane {poolIdx + 1}</span>
              {pool.members.length > 1 && (
                <span className="chip" style={{ fontSize: 9, textTransform: 'none', letterSpacing: 0 }}
                  title={`This lane holds ${pool.members.length} alternatives — each fire picks ONE of them at random (even odds), alongside every other lane's own pick`}>
                  ⚄ picks 1 of {pool.members.length}
                </span>
              )}
            </div>
            {pool.members.map((name, mi) => {
              const kind = kindsByName[name];
              if (!kind) return null;
              return [
                mi > 0 && (
                  <div key={`or-${name}`} style={{ fontSize: 9, color: 'var(--text-muted)',
                                                   textAlign: 'center', lineHeight: '8px' }}>
                    — or —
                  </div>
                ),
                <div key={name}
                  style={{ display: 'flex', flexDirection: 'column', gap: 6,
                           flex: pool.members.length === 1 ? 1 : undefined,
                           justifyContent: 'space-between',
                           opacity: draggingName === name ? 0.35 : 1 }}>
                  <div
                    onPointerDown={onStartDrag(name, { cls, bandIdx })}
                    style={{ fontSize: 11, fontWeight: 600, cursor: 'grab', userSelect: 'none' }}
                    title={`${name} — drag to move to another lane (drop ON a lane to pool with it, on the slim gap before one for a lane of its own), tap to edit`}>
                    {kindIcon(kind)} {name}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>×</span>
                    <NumberInput value={band.kinds[name]} min={0} step={0.1} width={44}
                      onChange={(v) => onSetScale(name, v ?? 1)} />
                    <button style={{ fontSize: 10, padding: '1px 5px', marginLeft: 'auto' }}
                      title="Detach from this band"
                      onClick={() => onDetach(name)}>✕</button>
                  </div>
                </div>,
              ];
            })}
          </div>,
        ];
      })}
      {pools.length > 0 && emptySlots === 0 && insertStrip(null, 'strip-end')}
      {Array.from({ length: emptySlots }, (_, i) => {
        const hovered = insertHovered(null) && i === 0;
        return (
          <div key={`empty-${i}`}
            data-lane data-cls={cls} data-band={bandIdx}
            data-lane-mode="insert" data-lane-anchor=""
            style={{
              width: 108, minHeight: LANE_HEIGHT, flexShrink: 0, borderRadius: 8, padding: '6px 7px',
              marginLeft: 2,
              border: `1.5px dashed ${hovered ? 'var(--accent)' : 'var(--text-muted)'}`,
              background: hovered ? 'rgba(168,85,247,0.12)' : 'transparent',
              display: 'flex', flexDirection: 'column', gap: 6, touchAction: 'none',
            }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
              lane {pools.length + i + 1}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', flex: 1,
                          display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              drop here
            </div>
          </div>
        );
      })}
      {canAddLane && (
        <button style={{ fontSize: 16, width: 28, height: LANE_HEIGHT, padding: 0, flexShrink: 0,
                         alignSelf: 'flex-start', marginLeft: 2 }}
          title="Add another lane to this band (up to 4)"
          onClick={onAddLane}>
          +
        </button>
      )}
    </div>
  );
}
