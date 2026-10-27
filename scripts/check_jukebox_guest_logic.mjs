// Executable spec for the guest page's rules (spectra/web/src/guest/logic.ts,
// data/jukebox-plan/report.md §7, PR 2.1): the "your song" strip's words, the
// "you're next" banner (once per change, never every poll), when a phone
// buzzes (Android only, after a tap), which phones get the Add to Home Screen
// hint (iPhones and iPads, not from the Home Screen already), the tabs, and
// the address that carries a phone's code to its Home Screen icon. The
// mounted page is proven by scripts/render_jukebox_guest.py on four phones.
//
// Run: node scripts/check_jukebox_guest_logic.mjs (tests/test_jukebox_guest_page.py).
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const web = join(repo, 'spectra/web');
const require = createRequire(join(web, 'package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = join(mkdtempSync(join(tmpdir(), 'guest-logic-')), 'logic.cjs');
await esbuild.build({ entryPoints: [join(web, 'src/guest/logic.ts')], bundle: true, format: 'cjs',
                      platform: 'node', outfile: out, logLevel: 'silent' });
const L = require(out);

console.log('times');
ok(L.mmss(72_000) === '1:12' && L.mmss(-5) === '0:00', 'mm:ss, never negative');
ok(L.inWords(500) === 'now' && L.inWords(72_000) === 'in 1:12' && L.inWords(15 * 60_000) === 'in 15 min',
   '"now", "in 1:12" under ten minutes, "in 15 min" after');
ok(L.progressNow(60_000, 100_000, true, 50_000) === 100_000, 'progress never runs past the song');
ok(L.progressNow(60_000, 100_000, false, 50_000) === 60_000, 'a paused song stays where it is');
const nine = new Date(2026, 9, 27, 21, 30, 0).getTime();
ok(L.clockAt(nine, 16 * 60_000, 'en-US') === '9:46', 'the phone\'s own clock: "9:46"');

console.log('the strip');
const strip = (tone, extra = {}) => ({ tone, title: 'Dopamine', place: 3, starts_in_ms: 15 * 60_000, count: 1, ...extra });
ok(L.stripText(strip('none', { place: null, starts_in_ms: null, title: '', count: 0 }), 0, nine, false).detail.includes('▲'),
   'no songs, no Add: it says how to vote');
ok(L.stripText(strip('none', { place: null, starts_in_ms: null, title: '', count: 0 }), 0, nine, true).detail.includes('＋'),
   'no songs, Add open: it points at ＋');
const q = L.stripText(strip('queued'), 60_000, nine, false, 'en-US');
ok(q.label === 'Your song #3' && q.detail === 'plays ~9:44 (in 14 min)', `queued counts down from receipt: "${q.detail}"`);
ok(L.stripText(strip('next', { starts_in_ms: 72_000 }), 0, nine, false).detail === 'Dopamine · in 1:12', 'next: "in 1:12"');
ok(L.stripText(strip('playing'), 0, nine, false).label === 'Your song is playing', 'playing');

console.log('the banner and the buzz');
ok(L.bannerFor(null, 'next') === null, 'not on the first view (nothing changed)');
ok(L.bannerFor('next', 'next') === null, 'not on every poll');
ok(L.bannerFor('queued', 'next') === 'next' && L.bannerFor('next', 'playing') === 'playing', 'on the change to next, then playing');
ok(L.bannerFor('playing', 'none') === null, 'not when it ends');
ok(JSON.stringify(L.vibration('next', true, true)) === '[180,90,180]', 'Android buzzes for next');
ok(L.vibration('next', false, true) === null, 'no Vibration API (iPhone): never');
ok(L.vibration('next', true, false) === null, 'not before the guest has tapped the page');
ok(L.vibration(null, true, true) === null, 'nothing to say: no buzz');

console.log('Add to Home Screen');
const iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
const ipad = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15';
const chromeIos = iphone.replace('Version/18.0', 'CriOS/131.0');
const android = 'Mozilla/5.0 (Linux; Android 15; SM-S936B) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36';
ok(L.wantsHomeScreenHint(iphone, 5, false), 'iPhone Safari gets the hint');
ok(L.wantsHomeScreenHint(ipad, 5, false), 'iPad (which says Mac) gets it, by its touch screen');
ok(!L.wantsHomeScreenHint(ipad, 0, false), 'a real Mac does not');
ok(!L.wantsHomeScreenHint(iphone, 5, true), 'not when already opened from the Home Screen');
ok(L.wantsHomeScreenHint(chromeIos, 5, false), 'Chrome on iPhone too (every iOS browser can add one since iOS 16.4)');
ok(!L.wantsHomeScreenHint(android, 5, false), 'not on Android (it buzzes instead)');
const addr = L.homeScreenAddress('R'.repeat(22), 'tok_en-1');
const back = L.fromAddress(addr.slice(1));
ok(back.phone === 'R'.repeat(22) && back.token === 'tok_en-1', `the Home Screen address round-trips: ${addr}`);
ok(L.fromAddress('?t=<script>&p=x').token === null && L.fromAddress('?p=x').phone === null,
   'junk in the address is ignored');

console.log('tabs and who added it');
ok(JSON.stringify(L.tabsFor({ add: false, board: false, credits: false })) === '["now","queue"]',
   'free play today: Now and Queue only — no tab that does nothing');
ok(JSON.stringify(L.tabsFor({ add: true, board: true, credits: false })) === '["now","queue","add","board"]',
   'Add and Board appear when SpotFX opens them');
ok(L.byLine({ kind: 'guest', name: 'Disco Ana' }, false) === 'Added by Disco Ana', 'a guest by name');
ok(L.byLine({ kind: 'guest', name: 'Disco Ana' }, true) === 'Added by you', 'your own: "you"');
ok(L.byLine({ kind: 'set', name: "Host's set" }, false) === "Host's set", "the host's set");

console.log('adding a song (PR 2.2)');
const held = L.stripText({ tone: 'queued', title: 'Dopamine', place: 2, starts_in_ms: 60_000, held: true, count: 1 }, 0, nine, false);
ok(held.label === 'Your song is on hold' && held.detail.includes('keeps its place'), 'a held song says so in the strip');
ok(L.stripText({ tone: 'playing', title: 'D', place: null, starts_in_ms: null, held: true, count: 1 }, 0, nine, false).tone === 'playing',
   'a song that is playing is playing, held or not');
const b = L.badges({ known: true, long: true, duration_ms: 372_000, explicit: true, in_line: true });
ok(JSON.stringify(b.map((x) => x.label)) === '["Ready","6:12","Explicit","In line"]', `badges: ${b.map((x) => x.label).join(', ')}`);
ok(L.badges({ known: false, long: false, duration_ms: 200_000, explicit: false, in_line: false }).length === 0, 'a plain song has none');
const req = (o) => ({ open: true, detail: '', closes_at: '11:40', max_waiting: 2, waiting: 0, ...o });
ok(L.addStatus(req({}), true).canAdd && L.addStatus(req({}), true).text === 'You can add 2 more songs · requests close at 11:40',
   'open: how many more, and when requests close');
ok(!L.addStatus(req({ waiting: 2 }), true).canAdd, 'two in line: no more until one plays');
ok(L.addStatus(req({ open: false, detail: 'closed!' }), true).text === 'closed!', 'after last call: the server\'s own sentence');
ok(!L.addStatus(req({}), false).canAdd, 'a phone waiting for approval can\'t add');
ok(L.addedText(25 * 60_000, nine, 'en-US') === 'Added — plays in 25 min (~9:55)', `the confirmation: ${L.addedText(25 * 60_000, nine, 'en-US')}`);
ok(L.addedText(null, nine) === 'Added to the line.', 'no start time: just added');
ok(L.SEARCH_DEBOUNCE_MS >= 300 && L.SEARCH_MIN === 2, 'searches wait for typing to stop, and need two letters');

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
