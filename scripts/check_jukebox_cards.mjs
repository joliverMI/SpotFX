// Executable spec for THE PRINTABLE GUEST CARD (spectra/web/src/jukebox/
// cardQr.ts + JukeboxCardsPage.tsx; the plan's §9 N2 and §8.1): every QR the
// page draws is DECODED BACK (jsQR, a dev-only dependency) and must say
// exactly what the card says — the Wi-Fi code (`WIFI:T:WPA;S:<name>;P:<pw>;;`,
// its escaping, UTF-8 names) and the Jukebox's join link with that card's own
// one-time bonus code — and the Wi-Fi password never leaves the page: no
// request carries it and no storage holds it.
//
// §1 pure, §2 decode round trips, §3 the page mounted (needs the dev-only
// jsdom; skipped, saying so, without it).
//
// Run: node scripts/check_jukebox_cards.mjs (tests/test_jukebox_cards.py).
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const web = join(repo, 'spectra/web');
const require = createRequire(join(web, 'package.json'));
const esbuild = require('esbuild');
const jsQR = require('jsqr');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};
const report = () => {
  console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
  process.exit(failures === 0 ? 0 : 1);
};

async function bundle(entrySrc, name) {
  const tmp = mkdtempSync(join(tmpdir(), `jukebox-cards-${name}-`));
  const entry = join(tmp, 'entry.mjs');
  writeFileSync(entry, entrySrc);
  const out = join(tmp, 'out.cjs');
  const r = await esbuild.build({
    entryPoints: [entry], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
    outfile: out, nodePaths: [join(web, 'node_modules')], logLevel: 'silent', loader: { '.css': 'empty' },
  });
  if (r.errors.length) throw new Error(r.errors.map((e) => e.text).join('; '));
  return require(out);
}

/** Decode a module matrix the way a phone does: an image with the quiet
 *  zone, 4 px a module, through jsQR. Returns the decoded bytes as text. */
function decodeMatrix(m, quiet = 4) {
  const scale = 4;
  const n = m.length + 2 * quiet;
  const w = n * scale;
  const px = new Uint8ClampedArray(w * w * 4).fill(255);
  for (let r = 0; r < m.length; r += 1) {
    for (let c = 0; c < m.length; c += 1) {
      if (!m[r][c]) continue;
      for (let y = 0; y < scale; y += 1) {
        for (let x = 0; x < scale; x += 1) {
          const i = (((r + quiet) * scale + y) * w + (c + quiet) * scale + x) * 4;
          px[i] = px[i + 1] = px[i + 2] = 0;
        }
      }
    }
  }
  const res = jsQR(px, w, w);
  return res ? new TextDecoder().decode(new Uint8Array(res.binaryData)) : null;
}

/** The module matrix an SVG path draws (`M{x} {y}h1v1h-1z` per dark module). */
function matrixFromPath(d, size, quiet = 4) {
  const n = size - 2 * quiet;
  const m = Array.from({ length: n }, () => Array(n).fill(false));
  for (const [, x, y] of d.matchAll(/M(\d+) (\d+)h1v1h-1z/g)) m[Number(y) - quiet][Number(x) - quiet] = true;
  return m;
}

const Q = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/cardQr.ts'))};`, 'qr');

console.log('§1 the Wi-Fi code and the join link, in words');
ok(Q.wifiEscape('a;b,c:d"e\\f') === 'a\\;b\\,c\\:d\\"e\\\\f', 'the Wi-Fi format\'s own escaping: \\ ; , : "');
ok(Q.wifiPayload({ ssid: 'Serenity Guests', password: 'hunter2hunter2', security: 'WPA', hidden: false })
   === 'WIFI:T:WPA;S:Serenity Guests;P:hunter2hunter2;;', 'WPA: the plan\'s WIFI:T:WPA;S:<name>;P:<password>;;');
ok(Q.wifiPayload({ ssid: 'Open Café', password: 'ignored', security: 'nopass', hidden: true })
   === 'WIFI:T:nopass;S:Open Café;H:true;;', 'an open, hidden network: no password in the code');
ok(Q.wifiProblem({ ssid: '', password: 'x', security: 'WPA', hidden: false }).includes('name')
   && Q.wifiProblem({ ssid: 'N', password: '', security: 'WPA', hidden: false }).includes('password')
   && Q.wifiProblem({ ssid: 'N', password: 'short', security: 'WPA', hidden: false }).includes('8 characters')
   && Q.wifiProblem({ ssid: 'N', password: '', security: 'nopass', hidden: false }) === '',
   'what is missing, said before a card is drawn');
const LINK = 'https://serenity.tail1234.ts.net:8443/?t=Tq3vR8mJx2LwP9sZk4YbN7cH1dFgE6aU0iOoKpQrSt';
ok(Q.joinLink(LINK, 'ABCD-EFGH') === `${LINK}&b=ABCD-EFGH` && Q.joinLink(LINK, null) === LINK
   && Q.joinLink('https://h/', 'K7Q2-M9XD') === 'https://h/?b=K7Q2-M9XD', 'the join link carries the card\'s code (?b=)');
ok(JSON.stringify(Q.cardCodes(['A', 'B'], 4, true)) === '["A","B",null,null]'
   && JSON.stringify(Q.cardCodes(['A', 'B'], 2, false)) === '[null,null]' && Q.cardCodes(['A'], 500, true).length === 60,
   'a code per card while they last, none when codes are off, at most 60 cards');

console.log('\n§2 every code decodes back to what the card says (jsQR)');
const payloads = [
  Q.wifiPayload({ ssid: 'Serenity Guests', password: 'hunter2hunter2', security: 'WPA', hidden: false }),
  Q.wifiPayload({ ssid: 'My;Net:"5G"', password: 'p,a;s:s\\word"', security: 'WPA', hidden: true }),
  Q.wifiPayload({ ssid: 'Café ☕ Gäste', password: 'überpasswort', security: 'WPA', hidden: false }),
  Q.joinLink(LINK, 'ABCD-EFGH'),
  Q.joinLink(LINK, null),
];
for (const text of payloads) {
  const m = Q.qrMatrix(text);
  ok(decodeMatrix(m) === text, `decodes to ${JSON.stringify(text.length > 60 ? `${text.slice(0, 57)}…` : text)}`);
  const size = m.length + 2 * Q.QUIET;
  ok(JSON.stringify(matrixFromPath(Q.qrPath(m), size)) === JSON.stringify(m), '  …and the SVG path draws exactly those modules');
}
ok(decodeMatrix(Q.qrMatrix('x').map((row) => row.map(() => false))) === null, 'the decoder can fail (a blank code reads as nothing)');

// ── 3. the page, mounted ──────────────────────────────────────────────────
let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('\njsdom not installed in spectra/web/node_modules (dev-only) — skipping §3.');
  report();
}
const { JSDOM } = jsdomMod;
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/jukebox/cards' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
for (const k of ['HTMLElement', 'HTMLInputElement', 'HTMLSelectElement', 'Node', 'Element', 'MouseEvent', 'KeyboardEvent', 'Event', 'getComputedStyle']) {
  globalThis[k] = dom.window[k];
}
globalThis.localStorage = dom.window.localStorage;
globalThis.sessionStorage = dom.window.sessionStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const PASSWORD = 'Sup3r-Secret;Guest:Pass';
let world;
const requests = [];
globalThis.fetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const body = init.body ? JSON.parse(init.body) : undefined;
  requests.push({ method, url: String(url), raw: `${String(url)} ${init.body || ''}` });
  const json = (b) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
  const u = String(url);
  if (u.startsWith('/api/jukebox/card')) return json(world.card);
  if (u.startsWith('/api/jukebox/guest-link') && method === 'PUT') {
    world.card = { ...world.card, host: body.public_host, link: `https://${body.public_host}:8443/?t=TOKEN123456` };
    return json({ config: {} });
  }
  return json({});
};
let printed = 0;
dom.window.print = () => { printed += 1; };

const P = await bundle(`
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import JukeboxCardsPage from ${JSON.stringify(join(web, 'src/jukebox/JukeboxCardsPage.tsx'))};
let root = null;
const container = document.createElement('div');
document.body.appendChild(container);
export function mount() {
  if (root) act(() => { root.unmount(); });
  root = createRoot(container);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, { initialEntries: ['/jukebox/cards'] }, React.createElement(JukeboxCardsPage))));
  });
  return container;
}
export async function settle(ms = 30) {
  for (let i = 0; i < 6; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
}
export function actSync(fn) { act(fn); }
export function unmount() { if (root) act(() => { root.unmount(); }); root = null; }
`, 'page');
const type = (el, v) => {
  const proto = el.tagName === 'SELECT' ? dom.window.HTMLSelectElement.prototype : dom.window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  P.actSync(() => { setter.call(el, v); el.dispatchEvent(new dom.window.Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
};
const click = async (el) => {
  P.actSync(() => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })));
  await P.settle();
};
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent));
const qrOf = (svg) => decodeMatrix(matrixFromPath(svg.querySelector('path').getAttribute('d'), Number(svg.getAttribute('data-qr-size'))));

console.log('\n§3 the page, mounted — the sheet, the codes, and the password never leaving');
{
  world = { card: { link: LINK, host: 'serenity.tail1234.ts.net', state: 'off', public_port: 8443, token_created_ms: 1,
                    unused: ['ABCD-EFGH', 'K7Q2-M9XD', 'WXYZ-2345'], codes_error: null, qr_bonus: 5, play_mode: 'credits' } };
  const c = P.mount();
  await P.settle();
  ok(!c.querySelector('[data-testid="jukebox-cards-sheet"]') && c.textContent.includes("Wi-Fi's name"),
    'no sheet until the Wi-Fi is typed, and it says what is missing');
  ok(btn(c, /^Print/).disabled, 'Print waits for the Wi-Fi');
  type(c.querySelector('input[aria-label="Wi-Fi network name"]'), 'Serenity Guests');
  type(c.querySelector('input[aria-label="Wi-Fi password"]'), PASSWORD);
  type(c.querySelector('input[aria-label="How many cards"]'), '4');
  await P.settle();
  const cards = [...c.querySelectorAll('[data-testid="jukebox-card"]')];
  ok(cards.length === 4, `four cards (${cards.length})`);
  const wifiText = `WIFI:T:WPA;S:Serenity Guests;P:${PASSWORD.replace(/([\\;,:"])/g, '\\$1')};;`;
  ok(cards.every((card) => qrOf(card.querySelectorAll('svg')[0]) === wifiText), 'every card\'s Wi-Fi QR decodes to the network and password');
  const joins = cards.map((card) => qrOf(card.querySelectorAll('svg')[1]));
  ok(joins[0] === `${LINK}&b=ABCD-EFGH` && joins[1] === `${LINK}&b=K7Q2-M9XD` && joins[2] === `${LINK}&b=WXYZ-2345` && joins[3] === LINK,
    'each card\'s Jukebox QR decodes to the party link with its own code — the fourth, with codes run out, has none');
  ok(cards[0].querySelector('[data-testid="jukebox-card-code"]').textContent.includes('ABCD-EFGH')
    && !cards[3].querySelector('[data-testid="jukebox-card-code"]'), 'the code is printed as text beside its QR');
  ok(!!c.querySelector('[data-testid="jukebox-cards-short"]'), 'it says how many cards will have no code');
  ok(!cards.some((card) => card.textContent.includes(PASSWORD)), 'the password is not printed as text unless asked');
  const asText = [...c.querySelectorAll('label')].find((l) => /password as text/.test(l.textContent)).querySelector('input');
  await click(asText);
  ok([...c.querySelectorAll('[data-testid="jukebox-card"]')].every((card) =>
    card.querySelector('[data-testid="jukebox-card-pw"]')?.textContent.includes(PASSWORD)),
  'asked to, every card prints the password as text too');
  await click(asText);
  ok(!c.querySelector('[data-testid="jukebox-card-pw"]'), '…and unticked, it is off every card again');
  await click(btn(c, /^Print 4 cards$/));
  ok(printed === 1, 'Print prints');
  const leaked = requests.filter((r) => r.raw.includes(PASSWORD) || r.raw.includes(encodeURIComponent(PASSWORD)));
  const stored = [...Object.values({ ...dom.window.localStorage }), ...Object.values({ ...dom.window.sessionStorage })]
    .some((v) => String(v).includes(PASSWORD));
  ok(leaked.length === 0 && !stored && !dom.window.location.href.includes('Secret'),
    'the Wi-Fi password never left the page: no request, no storage, not in the address');
  ok(requests.every((r) => r.method === 'GET' && r.url.startsWith('/api/jukebox/card')), 'the page only ever read the card details');
  P.unmount();
}
{
  world = { card: { link: null, host: null, state: 'off', public_port: 8443, token_created_ms: 1, unused: [],
                    codes_error: null, qr_bonus: 5, play_mode: 'free' } };
  requests.length = 0;
  const c = P.mount();
  await P.settle();
  ok(c.textContent.includes('no address yet') && !!c.querySelector('input[aria-label="The guest link\'s address"]'),
    'with no address yet, it asks for Serenity\'s public address');
  type(c.querySelector('input[aria-label="The guest link\'s address"]'), 'serenity.tail1234.ts.net');
  await click(btn(c, /^Save$/));
  const put = requests.find((r) => r.method === 'PUT');
  ok(!!put && put.url === '/api/jukebox/guest-link' && put.raw.includes('"public_host":"serenity.tail1234.ts.net"')
    && !put.raw.includes('enabled'), 'Save PUTs only the address — it never switches the link on');
  type(c.querySelector('input[aria-label="Wi-Fi network name"]'), 'Guests');
  type(c.querySelector('select[aria-label="Wi-Fi security"]'), 'nopass');
  await P.settle();
  const cards = [...c.querySelectorAll('[data-testid="jukebox-card"]')];
  ok(cards.length === 8 && cards.every((card) => !card.querySelector('[data-testid="jukebox-card-code"]')),
    'in free play the cards carry no bonus codes');
  ok(qrOf(cards[0].querySelectorAll('svg')[0]) === 'WIFI:T:nopass;S:Guests;;', 'an open network\'s code has no password');
  P.unmount();
}

report();
