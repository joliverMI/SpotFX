import { Link } from 'react-router-dom';

/** Small button-styled ↗ that opens a referenced entity (event, color set…)
 * in a new tab — a new tab so unsaved drafts in the current view stay put. */
export default function OpenRefLink({ to, title }: { to: string; title: string }) {
  return (
    <Link
      to={to}
      target="_blank"
      title={title}
      onClick={(e) => e.stopPropagation()}
      style={{
        padding: '2px 7px', fontSize: 12, background: 'var(--surface2)',
        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
        color: 'var(--text)', lineHeight: 'normal', textDecoration: 'none', flex: 'none',
      }}
    >
      ↗
    </Link>
  );
}
