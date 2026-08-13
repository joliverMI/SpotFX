import { Link, useLocation } from 'react-router-dom';
import { useSettings } from '../api/queries';

/** All pages live in the SPA now; AI Triggers and Timing follow the
 * show_ai_triggers / show_advanced settings like the legacy nav. */
export default function NavBar() {
  const { pathname } = useLocation();
  const { data: settings } = useSettings();
  const cls = (match: (p: string) => boolean) => (match(pathname) ? 'active' : '');
  return (
    <nav>
      <span className="logo">SpotFX</span>
      <Link to="/now" className={cls((p) => p === '/now')}>Now Playing</Link>
      <Link to="/builder" className={cls((p) => p === '/builder')}>Profile Builder</Link>
      <Link to="/" className={cls((p) => p === '/' || p.startsWith('/event'))}>Events</Link>
      <Link to="/color-sets" className={cls((p) => p === '/color-sets')}>Color Sets</Link>
      <Link to="/scenes" className={cls((p) => p === '/scenes')}>Scenes</Link>
      <Link to="/devices" className={cls((p) => p === '/devices')}>Devices</Link>
      {!!settings?.show_ai_triggers && (
        <Link to="/ai-triggers" className={cls((p) => p === '/ai-triggers')}>AI Triggers</Link>
      )}
      <Link to="/triggerless" className={cls((p) => p === '/triggerless')}>Triggerless</Link>
      <Link to="/setlists" className={cls((p) => p === '/setlists')}>Set Lists</Link>
      {!!settings?.show_advanced && (
        <Link to="/timing" className={cls((p) => p === '/timing')}>Timing</Link>
      )}
      <Link to="/debug" className={cls((p) => p === '/debug')}>Debug</Link>
      <Link to="/settings" className={cls((p) => p === '/settings')}>Settings</Link>
      <Link to="/help" className="help-link" title="Help" aria-label="Help">?</Link>
    </nav>
  );
}
