import { Routes, Route } from 'react-router-dom';
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

export default function App() {
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
        </Routes>
      </main>
      </ToastProvider>
    </>
  );
}
