import { useEffect } from 'react';
import { Link, Route, Routes, useLocation } from 'react-router-dom';
import RoomControlsBar from './components/RoomControlsBar';
import RoomOwnershipBar from './components/RoomOwnershipBar';
import { ToastProvider } from './components/Toast';
import { confirmLeave } from './lib/unsavedGuard';
import FeedbackPage from './feedback/FeedbackPage';
import HelpPage from './help/HelpPage';
import ReviewPage from './review/ReviewPage';
import ScenesPage from './scenes/ScenesPage';
import StatusPage from './status/StatusPage';
import BuilderPage from './timeline/BuilderPage';

const PAGE_TITLES: [string, string][] = [
  ['/scenes', 'Scenes'],
  ['/timeline', 'Timeline'],
  ['/feedback', 'Feedback'],
  ['/review', 'Review'],
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
      <Link to="/timeline" className={cls((p) => p === '/timeline')}>Timeline</Link>
      <Link to="/feedback" className={cls((p) => p === '/feedback')}>Feedback</Link>
      <Link to="/review" className={cls((p) => p === '/review')}>Review</Link>
      <Link to="/status" className={cls((p) => p === '/status')}>Status</Link>
      <Link to="/help" className="help-link" title="Help" aria-label="Help">?</Link>
    </nav>
  );
}

export default function App() {
  usePageTitle();
  return (
    <ToastProvider>
      <NavBar />
      <RoomControlsBar />
      <RoomOwnershipBar />
      <main>
        <Routes>
          <Route path="/" element={<ScenesPage />} />
          <Route path="/scenes" element={<ScenesPage />} />
          <Route path="/scenes/:id" element={<ScenesPage />} />
          <Route path="/timeline" element={<BuilderPage />} />
          <Route path="/feedback" element={<FeedbackPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/status" element={<StatusPage />} />
          <Route path="/help" element={<HelpPage />} />
        </Routes>
      </main>
    </ToastProvider>
  );
}
