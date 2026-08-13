/** Small button-styled ↗ that opens a referenced entity (event, colour
 * set…) in a new tab — a new tab so unsaved drafts in the current view stay
 * put. A plain anchor, not a router Link: in SPECTRA the reference usually
 * lives in the SpotFX app (/app/…), outside this router's basename. */
export default function OpenRefLink({ to, title }: { to: string; title: string }) {
  return (
    <a
      href={to}
      target="_blank"
      rel="noreferrer"
      title={title}
      onClick={(e) => e.stopPropagation()}
      style={{
        padding: '2px 7px', fontSize: 12, background: 'var(--surface2)',
        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
        color: 'var(--text)', lineHeight: 'normal', textDecoration: 'none', flex: 'none',
      }}
    >
      ↗
    </a>
  );
}
