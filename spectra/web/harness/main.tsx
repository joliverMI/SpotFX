// Perf harness: mounts the REAL DevicePreviewStrip (real WS client, real decode, real canvas paint)
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../src/components/Toast';
import DevicePreviewStrip from '../src/components/DevicePreviewStrip';

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter><ToastProvider><DevicePreviewStrip /></ToastProvider></MemoryRouter>
  </QueryClientProvider>,
);
