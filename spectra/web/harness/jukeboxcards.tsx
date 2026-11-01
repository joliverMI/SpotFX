/** Harness for the printable guest card (/jukebox/cards): the REAL
 * JukeboxCardsPage against a mocked GET /api/jukebox/card (a party link and
 * eight unused bonus codes). scripts/render_jukebox_cards.py types the Wi-Fi
 * details, prints the sheet to a Letter PDF and measures it. Nothing here
 * reaches SpotFX. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import '../src/styles/tokens.css';
import JukeboxCardsPage from '../src/jukebox/JukeboxCardsPage';

const CARD = {
  link: 'https://serenity.tail1234.ts.net:8443/?t=Tq3vR8mJx2LwP9sZk4YbN7cH1dFgE6aU0iOoKpQrSt',
  lan_link: 'http://192.168.40.145:8020/?t=Tq3vR8mJx2LwP9sZk4YbN7cH1dFgE6aU0iOoKpQrSt',
  host: 'serenity.tail1234.ts.net', state: 'armed', public_port: 8443, token_created_ms: Date.now(),
  unused: ['K7Q2-M9XD', 'ABCD-EFGH', 'WXYZ-2345', 'HJKM-NPQR', 'STVW-XYZ2', '3456-789A', 'BCDE-FGHJ', 'KMNP-QRST'],
  codes_error: null, qr_bonus: 5, play_mode: 'credits',
};
window.fetch = (async (input: RequestInfo | URL) => {
  const url = String(input);
  const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
  if (/\/jukebox\/card/.test(url)) return json(CARD);
  return json({});
}) as typeof fetch;

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/jukebox/cards']}>
      <JukeboxCardsPage />
    </MemoryRouter>
  </QueryClientProvider>,
);
