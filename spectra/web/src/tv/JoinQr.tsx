/** The join QR, drawn with the ONE shared encoder (../lib/qr.ts — "one QR
 * generator (shared with N2)", PR 1.3) — the same SVG-path approach the
 * printed guest cards already use (JukeboxCardsPage.tsx's own `QrSvg`),
 * not a second implementation. Shown only while `link` is non-null — the
 * plan's own Q5: the TV shows a QR only while the guest link is live. */
import { useMemo } from 'react';
import { qrMatrix, qrPath, QUIET } from '../lib/qr';

export default function JoinQr({ link }: { link: string }) {
  const m = useMemo(() => qrMatrix(link), [link]);
  const size = m.length + 2 * QUIET;
  return (
    <svg className="tv-qr" viewBox={`0 0 ${size} ${size}`} role="img"
         aria-label="Scan to join and add songs" shapeRendering="crispEdges">
      <rect width={size} height={size} fill="#fff" />
      <path d={qrPath(m)} fill="#000" />
    </svg>
  );
}
