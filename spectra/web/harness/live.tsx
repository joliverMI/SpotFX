// Perf harness: mounts the REAL Live view (real WS client, real position table, real renderer).
// localStorage `spectra-live-force-canvas` = '1' draws with the 2D canvas fallback instead of WebGL.
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../src/components/Toast';
import LiveView from '../src/live/LiveView';

const forceCanvas = localStorage.getItem('spectra-live-force-canvas') === '1';
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter><ToastProvider><LiveView forceCanvas={forceCanvas} /></ToastProvider></MemoryRouter>
  </QueryClientProvider>,
);
