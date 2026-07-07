import { useEffect } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
import NavBar from './components/NavBar';
import { ToastProvider } from './components/Toast';
import BuilderPage from './builder/BuilderPage';
import EventListPage from './components/EventList/EventListPage';
import EventEditorPage from './components/EventEditor/EventEditorPage';
import NowPlayingPage from './nowplaying/NowPlayingPage';
import DebugPage from './debug/DebugPage';
import DevicesPage from './devices/DevicesPage';
import ColorSetsPage from './colorsets/ColorSetsPage';
import SetlistsPage from './setlists/SetlistsPage';
import SettingsPage from './settings/SettingsPage';
import TriggerlessPage from './triggerless/TriggerlessPage';
import TimingVizPage from './timingviz/TimingVizPage';
import AITriggersPage from './aitriggers/AITriggersPage';
import HelpPage from './help/HelpPage';

const PAGE_TITLES: [string, string][] = [
  ['/event', 'Events'],
  ['/builder', 'Profile Builder'],
  ['/now', 'Now Playing'],
  ['/debug', 'Debug'],
  ['/devices', 'Devices'],
  ['/color-sets', 'Color Sets'],
  ['/setlists', 'Set Lists'],
  ['/settings', 'Settings'],
  ['/triggerless', 'Triggerless'],
  ['/timing', 'Timing'],
  ['/ai-triggers', 'AI Triggers'],
  ['/help', 'Help'],
];

/** The SPA serves one index.html — keep the tab title in sync per route. */
function usePageTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    const hit = PAGE_TITLES.find(([prefix]) => pathname.startsWith(prefix));
    document.title = `SpotFX — ${hit?.[1] ?? 'Events'}`;
  }, [pathname]);
}

export default function App() {
  usePageTitle();
  return (
    <>
      <ToastProvider>
      <NavBar />
      <main>
        <Routes>
          <Route path="/" element={<EventListPage />} />
          <Route path="/event/:id" element={<EventEditorPage />} />
          <Route path="/builder" element={<BuilderPage />} />
          <Route path="/now" element={<NowPlayingPage />} />
          <Route path="/debug" element={<DebugPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/color-sets" element={<ColorSetsPage />} />
          <Route path="/setlists" element={<SetlistsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/triggerless" element={<TriggerlessPage />} />
          <Route path="/timing" element={<TimingVizPage />} />
          <Route path="/ai-triggers" element={<AITriggersPage />} />
          <Route path="/help" element={<HelpPage />} />
        </Routes>
      </main>
      </ToastProvider>
    </>
  );
}
