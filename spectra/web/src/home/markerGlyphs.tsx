/** The three marker-shaped glyphs Home's own filter toggles draw — lifted
 * verbatim from the approved mockup's `homePage()` (data/ui-layout-plan/
 * explainer-final.html; design-fidelity pass, 2026-10-14, audit H2).
 *
 * They are bespoke rather than registry icons on purpose: a filter whose
 * meaning IS "these markers" reads instantly when the button draws the
 * actual marker — a cyan scene square beside a lime flare dot, the gold/
 * sky/pink charge-lull-drop trio, the white/indigo High-Low flags. The
 * registry's generic stroke icons (`scene`/`pulse`/`arrowUp`) rendered as
 * ~6px squiggles inside their own 24-unit box at this size and read as
 * nothing. Colours are the same KIND_COLOR values every other surface
 * draws these markers with. */
export const AnalysedGlyph = (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <rect x="1.5" y="4" width="7" height="7" rx="1.5" fill="#22d3ee" />
    <circle cx="12" cy="7.5" r="2.8" fill="#a3e635" />
  </svg>
);

export const DropSeqGlyph = (
  <svg width="18" height="16" viewBox="0 0 18 16" aria-hidden="true">
    <rect x="1" y="9" width="6" height="4" rx="1" fill="#fbbf24" />
    <rect x="7.5" y="9" width="4" height="4" rx="1" fill="#38bdf8" />
    <rect x="12" y="4" width="5" height="10" rx="2.5" fill="#ec4899" />
  </svg>
);

export const LightShowGlyph = (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M5 2L9 8H1Z" fill="#f5f5f4" />
    <path d="M11 14L7 8H15Z" fill="#818cf8" />
  </svg>
);
