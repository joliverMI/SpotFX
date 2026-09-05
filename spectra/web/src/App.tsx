import { useEffect } from 'react';
import { Link, Route, Routes, useLocation } from 'react-router-dom';
import RoomControlsBar from './components/RoomControlsBar';
import RoomOwnershipBar from './components/RoomOwnershipBar';
import TestingBar from './components/TestingBar';
import TopBarStrip from './components/TopBarStrip';
import { ToastProvider } from './components/Toast';
import { confirmLeave } from './lib/unsavedGuard';
import ColorSetsPage from './colorsets/ColorSetsPage';
import DevicesPage from './devices/DevicesPage';
import FeedbackPage from './feedback/FeedbackPage';
import HelpPage from './help/HelpPage';
import HelpLink from './help/HelpLink';
import { topicForPath } from './help/routeTopics';
import ReviewPage from './review/ReviewPage';
import ScenesPage from './scenes/ScenesPage';
import SettingsConsolePage from './settings/SettingsConsolePage';
import StatusPage from './status/StatusPage';
import BuilderPage from './timeline/BuilderPage';
import TimingVizPage from './timingviz/TimingVizPage';
import AvSyncPage from './avsync/AvSyncPage';
import RoomsPage from './rooms/RoomsPage';
import RoomEffectsPage from './roomeffects/RoomEffectsPage';
import DebugPage from './debug/DebugPage';

const PAGE_TITLES: [string, string][] = [
  ['/scenes', 'Scenes'],
  ['/colorsets', 'Colour Sets'],
  ['/timeline', 'Timeline'],
  ['/feedback', 'Feedback'],
  ['/review', 'Review'],
  ['/timing', 'Timing'],
  ['/avsync', 'AV Sync'],
  ['/rooms', 'Rooms'],
  ['/room-effects', 'Room Effects'],
  ['/devices', 'Devices'],
  ['/debug', 'Debug'],
  ['/settings', 'Settings'],
  ['/status', 'Status'],
  ['/help', 'Help'],
];

function usePageTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    const hit = PAGE_TITLES.find(([prefix]) => pathname.startsWith(prefix));
    document.title = `SPECTRA — ${hit?.[1] ?? 'Scenes'}`;
  }, [pathname]);
}

function NavBar() {
  const { pathname } = useLocation();
  const cls = (match: (p: string) => boolean) => (match(pathname) ? 'active' : '');
  const helpTopic = topicForPath(pathname);
  return (
    // Capture-phase so the unsaved-changes guard runs before any Link handler.
    <nav onClickCapture={(e) => {
      const a = (e.target as HTMLElement).closest('a');
      if (a && new URL(a.href).pathname !== window.location.pathname && !confirmLeave()) {
        e.preventDefault();
        e.stopPropagation();
      }
    }}>
      <span className="logo">◆ SPECTRA</span>
      <Link to="/scenes" className={cls((p) => p === '/' || p.startsWith('/scenes'))}>Scenes</Link>
      <Link to="/colorsets" className={cls((p) => p.startsWith('/colorsets'))}>Colours</Link>
      <Link to="/timeline" className={cls((p) => p === '/timeline')}>Timeline</Link>
      <Link to="/feedback" className={cls((p) => p === '/feedback')}>Feedback</Link>
      <Link to="/review" className={cls((p) => p === '/review')}>Review</Link>
      <Link to="/timing" className={cls((p) => p === '/timing')}>Timing</Link>
      <Link to="/avsync" className={cls((p) => p === '/avsync')}>AV Sync</Link>
      <Link to="/rooms" className={cls((p) => p === '/rooms')}>Rooms</Link>
      <Link to="/room-effects" className={cls((p) => p === '/room-effects')}>Room FX</Link>
      <Link to="/devices" className={cls((p) => p === '/devices')}>Devices</Link>
      <Link to="/debug" className={cls((p) => p === '/debug')}>Debug</Link>
      <Link to="/settings" className={cls((p) => p === '/settings')}>Settings</Link>
      <Link to="/status" className={cls((p) => p === '/status')}>Status</Link>
      <HelpLink topic={helpTopic ?? undefined} title="Help for this page" />
    </nav>
  );
}

export default function App() {
  usePageTitle();
  return (
    <ToastProvider>
      {/* FIRST, above NavBar — this must genuinely be the top bar on every
        * route (his ask 2026-08-24). It renders nothing at all on a
        * confirmed "not testing", so it costs no vertical space in normal
        * use; see TestingBar.tsx for why "unknown" still shows. */}
      <TestingBar />
      <NavBar />
      <RoomControlsBar />
      <TopBarStrip />
      <RoomOwnershipBar />
      <main>
        <Routes>
          <Route path="/" element={<ScenesPage />} />
          <Route path="/scenes" element={<ScenesPage />} />
          <Route path="/scenes/:id" element={<ScenesPage />} />
          <Route path="/colorsets" element={<ColorSetsPage />} />
          <Route path="/timeline" element={<BuilderPage />} />
          <Route path="/feedback" element={<FeedbackPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/timing" element={<TimingVizPage />} />
          <Route path="/avsync" element={<AvSyncPage />} />
          <Route path="/rooms" element={<RoomsPage />} />
          <Route path="/room-effects" element={<RoomEffectsPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/debug" element={<DebugPage />} />
          <Route path="/settings" element={<SettingsConsolePage />} />
          <Route path="/status" element={<StatusPage />} />
          <Route path="/help" element={<HelpPage />} />
        </Routes>
      </main>
    </ToastProvider>
  );
}
