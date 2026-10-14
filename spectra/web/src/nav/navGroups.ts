/** The grouped top menu (2026-10-14 UI declutter plan, data/ui-layout-
 * plan/report.md §2): his own grouping, verbatim — "top menu becomes
 * Home | Artifacts ▾ (Scenes, Colours, Devices, Rooms, Room FX, Light
 * Show) | Engine ▾ (Debug, Status, Timing, Review, AV Sync, House, Test
 * Bed, Timeline) | Settings." Feedback is in neither of his lists; filed
 * under Engine next to Review (his decided answer, §13 Q4 — Review reads
 * feedback sessions).
 *
 * Kept as a plain data table (no JSX) so `scripts/check_nav_menu.mjs` can
 * import it directly and prove every route is reachable, with no DOM. */
import type { IconName } from '../components/iconRegistry';

export interface NavItem {
  to: string;
  label: string;
  /** True when `pathname` is "on" this item — matches the existing
   * per-link `cls()` rules in the old NavBar (e.g. '/' and '/scenes' both
   * highlight Scenes). */
  match: (pathname: string) => boolean;
}

export interface NavGroup {
  id: string;
  label: string;
  icon: IconName;
  /** A single item with no dropdown (Home, Settings) renders as a plain
   * link; a group with `items` renders a dropdown. */
  to?: string;
  items?: NavItem[];
}

const prefix = (p: string) => (pathname: string) => pathname.startsWith(p);
const exact = (p: string) => (pathname: string) => pathname === p;

export const NAV_GROUPS: NavGroup[] = [
  { id: 'home', label: 'Home', icon: 'dash', to: '/' },
  {
    id: 'artifacts',
    label: 'Artifacts',
    icon: 'cube',
    items: [
      { to: '/scenes', label: 'Scenes', match: (p) => p.startsWith('/scenes') },
      { to: '/colorsets', label: 'Colours', match: prefix('/colorsets') },
      { to: '/devices', label: 'Devices', match: exact('/devices') },
      { to: '/rooms', label: 'Rooms', match: exact('/rooms') },
      { to: '/room-effects', label: 'Room FX', match: exact('/room-effects') },
      { to: '/show', label: 'Light Show', match: exact('/show') },
    ],
  },
  {
    id: 'engine',
    label: 'Engine',
    icon: 'gauge',
    items: [
      { to: '/debug', label: 'Debug', match: exact('/debug') },
      { to: '/status', label: 'Status', match: exact('/status') },
      { to: '/timing', label: 'Timing', match: exact('/timing') },
      { to: '/review', label: 'Review', match: exact('/review') },
      { to: '/feedback', label: 'Feedback', match: exact('/feedback') },
      { to: '/avsync', label: 'AV Sync', match: exact('/avsync') },
      { to: '/house', label: 'House', match: exact('/house') },
      { to: '/testbed', label: 'Test Bed', match: exact('/testbed') },
      { to: '/timeline', label: 'Timeline', match: exact('/timeline') },
    ],
  },
  { id: 'settings', label: 'Settings', icon: 'settings', to: '/settings' },
];

/** Every route the OLD 16-link NavBar reached, for the "every route still
 * reachable" proof — `/live` is deliberately excluded (it's a pop-out with
 * no menu entry, unchanged). */
export const ALL_NAV_ROUTES = [
  '/', '/scenes', '/colorsets', '/devices', '/rooms', '/room-effects', '/show',
  '/debug', '/status', '/timing', '/review', '/feedback', '/avsync', '/house',
  '/testbed', '/timeline', '/settings',
];

/** Which group (if any) contains the current route — for highlighting the
 * group trigger itself (surface2 + accent underline) when a dropdown item
 * inside it is the active page. A single-item group (Home/Settings) is
 * its own group for this purpose. */
export function activeGroupId(pathname: string): string | null {
  for (const g of NAV_GROUPS) {
    if (g.to != null && pathname === g.to) return g.id;
    if (g.items?.some((it) => it.match(pathname))) return g.id;
  }
  return null;
}
