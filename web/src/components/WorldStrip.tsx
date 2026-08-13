/** Route-driven world marker: an always-visible sticky strip telling the user
 * whether the current page belongs to SPECTRA (SceneV2 merged-program world)
 * or the legacy spot-effects world (classic events / profile builder). One
 * source of truth here — pages never mount their own copy, so no V2 surface
 * can be missed. Routes not listed belong to both worlds (shared
 * infrastructure: devices, color sets, settings…) and get no strip. */
import { useLocation } from 'react-router-dom';
import HelpLink from '../help/HelpLink';

const SPECTRA_ROUTES = ['/scenes'];
const LEGACY_ROUTES = ['/event', '/builder'];

const isLegacy = (p: string) =>
  p === '/' || LEGACY_ROUTES.some((r) => p.startsWith(r));

export default function WorldStrip() {
  const { pathname } = useLocation();
  const spectra = SPECTRA_ROUTES.some((r) => pathname.startsWith(r));
  const legacy = !spectra && isLegacy(pathname);
  if (!spectra && !legacy) return null;
  return (
    <div
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '3px 14px',
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.08em',
        color: '#fff',
        background: spectra
          ? 'linear-gradient(90deg, #5b21b6, #7c3aed)'
          : 'linear-gradient(90deg, #92400e, #b45309)',
        borderBottom: '1px solid var(--border)',
      }}
    >
      {spectra ? '◆ SPECTRA' : '■ LEGACY SPOT-EFFECTS'}
      <span style={{ fontWeight: 400, letterSpacing: 'normal', opacity: 0.85 }}>
        {spectra
          ? '— SceneV2 world: device-aware scenes, sequencer, curve profiles'
          : '— classic world: trigger events & profile builder'}
      </span>
      <span style={{ marginLeft: 'auto' }}>
        <HelpLink topic="concept-worlds" />
      </span>
    </div>
  );
}
