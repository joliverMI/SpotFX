/** The grouped top menu (2026-10-14 UI declutter plan, data/ui-layout-
 * plan/report.md §2): his own grouping, verbatim — "top menu becomes
 * Home | Artifacts ▾ (Scenes, Colours, Devices, Rooms, Room FX, Light
 * Show) | Engine ▾ (Debug, Status, Timing, Review, AV Sync, House, Test
 * Bed, Timeline) | Settings." Feedback is in neither of his lists; filed
 * under Engine next to Review (his decided answer, §13 Q4 — Review reads
 * feedback sessions). Absorb (Absorb Music, data/absorb-music-plan/
 * report.md §10) joined Engine later, after Test Bed.
 *
 * Kept as a plain data table (no JSX) so `scripts/check_nav_menu.mjs` can
 * import it directly and prove every route is reachable, with no DOM. */
import type { IconName } from '../components/iconRegistry';

export interface NavItem {
  to: string;
  label: string;
  /** The item's own 16px stroke glyph — the approved mockup draws one per
   * dropdown row (design-fidelity pass, 2026-10-14; without them the
   * dropdown reads as a plain text list). Names come from the mockup's own
   * icon table, lifted into components/iconRegistry.ts. */
  icon: IconName;
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
      { to: '/scenes', label: 'Scenes', match: (p) => p.startsWith('/scenes'), icon: 'scene' },
      { to: '/colorsets', label: 'Colours', match: prefix('/colorsets'), icon: 'palette' },
      { to: '/devices', label: 'Devices', match: exact('/devices'), icon: 'devices' },
      { to: '/rooms', label: 'Rooms', match: exact('/rooms'), icon: 'rooms' },
      { to: '/room-effects', label: 'Room FX', match: exact('/room-effects'), icon: 'roomfx' },
      { to: '/show', label: 'Light Show', match: exact('/show'), icon: 'spark' },
    ],
  },
  {
    id: 'engine',
    label: 'Engine',
    icon: 'gauge',
    items: [
      { to: '/debug', label: 'Debug', match: exact('/debug'), icon: 'bug' },
      { to: '/status', label: 'Status', match: exact('/status'), icon: 'pulse' },
      { to: '/timing', label: 'Timing', match: exact('/timing'), icon: 'clock' },
      { to: '/review', label: 'Review', match: exact('/review'), icon: 'review' },
      { to: '/feedback', label: 'Feedback', match: exact('/feedback'), icon: 'chat' },
      { to: '/avsync', label: 'AV Sync', match: exact('/avsync'), icon: 'sync' },
      { to: '/house', label: 'House', match: exact('/house'), icon: 'home' },
      { to: '/testbed', label: 'Test Bed', match: exact('/testbed'), icon: 'flask' },
      { to: '/absorb', label: 'Absorb', match: exact('/absorb'), icon: 'absorb' },
      { to: '/timeline', label: 'Timeline', match: exact('/timeline'), icon: 'timeline' },
    ],
  },
  { id: 'settings', label: 'Settings', icon: 'settings', to: '/settings' },
];

/** Every route the OLD 16-link NavBar reached, for the "every route still
 * reachable" proof — `/live` is deliberately excluded (it's a pop-out with
 * no menu entry, unchanged) — plus every top-level route added since
 * (`/absorb`, Absorb Music, 2026-10-21, filed under Engine beside Test Bed,
 * Timing and Review: the other library-maintenance surfaces). */
export const ALL_NAV_ROUTES = [
  '/', '/scenes', '/colorsets', '/devices', '/rooms', '/room-effects', '/show',
  '/debug', '/status', '/timing', '/review', '/feedback', '/avsync', '/house',
  '/testbed', '/timeline', '/settings', '/absorb',
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
