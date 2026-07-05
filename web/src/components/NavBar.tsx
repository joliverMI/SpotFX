import { Link, useLocation } from 'react-router-dom';

/** Mirrors frontend/js/nav.js; classic pages are plain hrefs outside the SPA. */
export default function NavBar() {
  const { pathname } = useLocation();
  return (
    <nav>
      <span className="logo">SpotFX</span>
      <a href="/">Now Playing</a>
      <Link to="/builder" className={pathname === '/builder' ? 'active' : ''}>
        Profile Builder
      </Link>
      <Link to="/" className={pathname === '/' || pathname.startsWith('/event') ? 'active' : ''}>
        Events
      </Link>
      <a href="/color-sets.html">Color Sets</a>
      <a href="/devices.html">Devices</a>
      <a href="/setlist.html">Set Lists</a>
      <a href="/settings.html">Settings</a>
    </nav>
  );
}
