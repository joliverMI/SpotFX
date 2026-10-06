/** A .card with a clickable header chevron; collapse state sticky per id. */
import type { ReactNode } from 'react';
import { useSticky } from '../lib/useSticky';

export default function CollapsibleCard({
  id,
  title,
  defaultCollapsed = false,
  headerExtra,
  wrapHeader = false,
  children,
}: {
  id: string;
  title: ReactNode;
  defaultCollapsed?: boolean;
  /** Rendered in the header row, right side — visible even when collapsed. */
  headerExtra?: ReactNode;
  /** When the title and headerExtra do not fit on one line (a phone), drop
   * headerExtra onto its own right-aligned line instead of squeezing the
   * title under it. Opt-in, so no other card's header changes. */
  wrapHeader?: boolean;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useSticky<boolean>(`collapsed.${id}`, defaultCollapsed);
  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: wrapHeader ? 'wrap' : undefined }}>
        <div
          onClick={() => setCollapsed((c) => !c)}
          style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', userSelect: 'none',
                   flex: wrapHeader ? '1 1 auto' : 1, minWidth: 0 }}
        >
          <span className={`caret ${collapsed ? '' : 'open'}`}>▶</span>
          <span className="card-title" style={{ marginBottom: 0 }}>{title}</span>
        </div>
        {wrapHeader && headerExtra
          ? <div style={{ marginLeft: 'auto', minWidth: 0, maxWidth: '100%' }}>{headerExtra}</div>
          : headerExtra}
      </div>
      {!collapsed && <div style={{ marginTop: 10 }}>{children}</div>}
    </div>
  );
}
