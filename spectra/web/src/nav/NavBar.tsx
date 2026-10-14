/** The grouped top menu (UI declutter plan §2): Home | Artifacts ▾ |
 * Engine ▾ | Settings — replacing the old 16-link row. Mounted first in
 * App.tsx, above the one consolidated bar.
 *
 * The unsaved-changes guard is UNCHANGED: a capture-phase click handler on
 * this very `<nav>` (below), reading `a.closest('a')` — every item here,
 * dropdown or not, is a real `<Link>` rendered inside this element (never
 * portalled), so the guard keeps covering every navigation exactly as it
 * did for the flat link row. */
import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import Icon from '../components/Icon';
import HelpLink from '../help/HelpLink';
import { topicForPath } from '../help/routeTopics';
import { confirmLeave } from '../lib/unsavedGuard';
import { activeGroupId, NAV_GROUPS } from './navGroups';
import NavMenu from './NavMenu';

export default function NavBar() {
  const { pathname } = useLocation();
  const [openId, setOpenId] = useState<string | null>(null);
  const activeId = activeGroupId(pathname);
  const helpTopic = topicForPath(pathname);

  return (
    <nav
      onClickCapture={(e) => {
        const a = (e.target as HTMLElement).closest('a');
        if (a && new URL(a.href).pathname !== window.location.pathname && !confirmLeave()) {
          e.preventDefault();
          e.stopPropagation();
        }
      }}
    >
      <span className="logo">◆ SPECTRA</span>
      <HelpLink topic="nav-menu" title="How the grouped menu works" />
      {NAV_GROUPS.map((g) => {
        if (!g.items) {
          // Home / Settings — a plain link, no dropdown.
          return (
            <Link
              key={g.id}
              to={g.to!}
              className={`nav-plain-link${activeId === g.id ? ' active' : ''}`}
            >
              <Icon name={g.icon} size={15} />
              <span className="nav-plain-link-label">{g.label}</span>
            </Link>
          );
        }
        return (
          <NavMenu
            key={g.id}
            group={g}
            pathname={pathname}
            open={openId === g.id}
            anyOpen={openId !== null}
            isActiveGroup={activeId === g.id}
            onOpen={() => setOpenId(g.id)}
            onClose={() => setOpenId((o) => (o === g.id ? null : o))}
          />
        );
      })}
      <HelpLink topic={helpTopic ?? undefined} title="Help for this page" />
    </nav>
  );
}
