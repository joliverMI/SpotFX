/** A .card with a clickable header chevron; collapse state sticky per id. */
import type { ReactNode } from 'react';
import { useSticky } from '../lib/useSticky';

export default function CollapsibleCard({
  id,
  title,
  defaultCollapsed = false,
  headerExtra,
  children,
}: {
  id: string;
  title: ReactNode;
  defaultCollapsed?: boolean;
  /** Rendered in the header row, right side — visible even when collapsed. */
  headerExtra?: ReactNode;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useSticky<boolean>(`collapsed.${id}`, defaultCollapsed);
  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div
          onClick={() => setCollapsed((c) => !c)}
          style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', userSelect: 'none', flex: 1, minWidth: 0 }}
        >
          <span className={`caret ${collapsed ? '' : 'open'}`}>▶</span>
          <span className="card-title" style={{ marginBottom: 0 }}>{title}</span>
        </div>
        {headerExtra}
      </div>
      {!collapsed && <div style={{ marginTop: 10 }}>{children}</div>}
    </div>
  );
}
