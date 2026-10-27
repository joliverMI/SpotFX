import { useEffect } from 'react';
import { Route, Routes, useLocation } from 'react-router-dom';
import RoomOwnershipBar from './components/RoomOwnershipBar';
import TestingBar from './components/TestingBar';
import { ToastProvider } from './components/Toast';
import ColorSetsPage from './colorsets/ColorSetsPage';
import DevicesPage from './devices/DevicesPage';
import LiveView from './live/LiveView';
import FeedbackPage from './feedback/FeedbackPage';
import HelpPage from './help/HelpPage';
import HomePage from './home/HomePage';
import ReviewPage from './review/ReviewPage';
import ScenesPage from './scenes/ScenesPage';
import TestbedPage from './testbed/TestbedPage';
import AbsorbPage from './absorb/AbsorbPage';
import JukeboxPage from './jukebox/JukeboxPage';
import JukeboxCardsPage from './jukebox/JukeboxCardsPage';
import JukeboxTvPage from './jukebox/JukeboxTvPage';
import SettingsConsolePage from './settings/SettingsConsolePage';
import StatusPage from './status/StatusPage';
import BuilderPage from './timeline/BuilderPage';
import TimingVizPage from './timingviz/TimingVizPage';
import AvSyncPage from './avsync/AvSyncPage';
import RoomsPage from './rooms/RoomsPage';
import RoomEffectsPage from './roomeffects/RoomEffectsPage';
import DebugPage from './debug/DebugPage';
import LightShowPage from './lightshow/LightShowPage';
import HousePage from './house/HousePage';
import AppChrome, { showsSongStrip } from './components/AppChrome';
import KioskPage from './kiosk/KioskPage';
import { isKioskRequested } from './kiosk/kioskConfig';
import { useShowClockSeed } from './queries';

const PAGE_TITLES: [string, string][] = [
  ['/scenes', 'Scenes'],
  ['/colorsets', 'Colour Sets'],
  ['/timeline', 'Timeline'],
  ['/feedback', 'Feedback'],
  ['/review', 'Review'],
  ['/testbed', 'Test Bed'],
  ['/absorb', 'Absorb Music'],
  ['/jukebox/tv', 'Jukebox board'],
  ['/jukebox/cards', 'Jukebox cards'],
  ['/jukebox', 'Jukebox'],
  ['/timing', 'Timing'],
  ['/avsync', 'AV Sync'],
  ['/show', 'Light Show'],
  ['/house', 'House'],
  ['/rooms', 'Rooms'],
  ['/room-effects', 'Room Effects'],
  ['/devices', 'Devices'],
  ['/live', 'Live'],
  ['/debug', 'Debug'],
  ['/settings', 'Settings'],
  ['/status', 'Status'],
  ['/help', 'Help'],
];

function usePageTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    // "/" is Home now (§13 decision 10) — matched exactly, before the
    // prefix scan below, since every path is technically a "/" prefix.
    const title = pathname === '/'
      ? 'Home'
      : PAGE_TITLES.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? 'Home';
    document.title = `SPECTRA — ${title}`;
  }, [pathname]);
}

export default function App() {
  usePageTitle();
  useShowClockSeed();
  const { pathname, search } = useLocation();

  // THE KIOSK VIEW (/?kiosk=1 — song-layout-plan's kiosk section): no
  // Spectra menu, just the one bar and Home, for a Home Assistant
  // dashboard tab. Checked before every other route so a kiosk request
  // can never fall through to the ordinary chrome.
  if (isKioskRequested(search)) {
    return (
      <ToastProvider>
        <KioskPage />
      </ToastProvider>
    );
  }

  // The Live view's pop-out window: the stage alone, none of the app's bars
  // (the top strip would hold a second, summary-level view of the same feed).
  if (pathname === '/live') {
    return (
      <ToastProvider>
        <main className="live-popout-page"><LiveView popout /></main>
      </ToastProvider>
    );
  }
  // The Jukebox board for his TV (/jukebox/tv): the board alone, full
  // screen — none of the app's bars on a TV across the room.
  // The printable guest cards (/jukebox/cards): the sheet alone, so what
  // prints is the cards and their controls (hidden in print), no app bars.
  if (pathname === '/jukebox/cards') {
    return (
      <ToastProvider>
        <JukeboxCardsPage />
      </ToastProvider>
    );
  }
  if (pathname === '/jukebox/tv') {
    return (
      <ToastProvider>
        <JukeboxTvPage />
      </ToastProvider>
    );
  }
  // THE GLOBAL SONG TIMELINE (song-layout-plan §4) sits BELOW THE BAR on
  // every page except Timeline, which carries its own full editing
  // toolset — and not on the Live pop-out, handled above. Home shows this
  // same row and edits it through the chrome's own shared view state (the
  // Admiral, 2026-10-15); it no longer draws a second copy. The rule
  // itself lives in AppChrome.tsx so the harness that renders this same
  // chrome uses it too, rather than its own idea of where the strip goes.
  return (
    <ToastProvider>
      {/* FIRST, above NavBar — this must genuinely be the top bar on every
        * route (his ask 2026-08-24). It renders nothing at all on a
        * confirmed "not testing", so it costs no vertical space in normal
        * use; see TestingBar.tsx for why "unknown" still shows. */}
      <TestingBar />
      {/* MENU, BAR, TIMELINE — his own 2026-10-15 order (a deliberate
        * departure from the mockups' nav/timeline/bar), and the ONE
        * composition the design-fidelity gate renders too. The page body
        * is AppChrome's CHILDREN so the shared song-timeline view state
        * covers both the timeline row and the page driving it — see
        * components/AppChrome.tsx on why it is shared, not duplicated. */}
      <AppChrome showSongStrip={showsSongStrip(pathname)}>
      <RoomOwnershipBar />
      <main className={pathname === '/' ? 'home-route' : undefined}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/scenes" element={<ScenesPage />} />
          <Route path="/scenes/:id" element={<ScenesPage />} />
          <Route path="/colorsets" element={<ColorSetsPage />} />
          <Route path="/timeline" element={<BuilderPage />} />
          <Route path="/feedback" element={<FeedbackPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/testbed" element={<TestbedPage />} />
          <Route path="/absorb" element={<AbsorbPage />} />
          <Route path="/jukebox" element={<JukeboxPage />} />
          <Route path="/timing" element={<TimingVizPage />} />
          <Route path="/avsync" element={<AvSyncPage />} />
          <Route path="/show" element={<LightShowPage />} />
          <Route path="/house" element={<HousePage />} />
          <Route path="/rooms" element={<RoomsPage />} />
          <Route path="/room-effects" element={<RoomEffectsPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/debug" element={<DebugPage />} />
          <Route path="/settings" element={<SettingsConsolePage />} />
          <Route path="/status" element={<StatusPage />} />
          <Route path="/help" element={<HelpPage />} />
        </Routes>
      </main>
      </AppChrome>
    </ToastProvider>
  );
}
