// Executable spec for the guest page's rules (spectra/web/src/guest/logic.ts,
// data/jukebox-plan/report.md §7, PR 2.1): the "your song" strip's words, the
// "you're next" banner (once per change, never every poll), when a phone
// buzzes (Android only, after a tap), which phones get the Add to Home Screen
// hint (iPhones and iPads, not from the Home Screen already), the tabs, and
// the address that carries a phone's code to its Home Screen icon. The
// mounted page is proven by scripts/render_jukebox_guest.py on four phones.
// Credits mode (PR 3.2): the Shop tab, the paid skip and its pot, tips, play
// next, the move prices, the jail card and its break-out, history amounts.
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

console.log('free play (PR 2.3)');
const jail = L.stripText({ tone: 'jail', title: '', place: null, starts_in_ms: null, held: false, count: 1, jail_left: 3 }, 0, nine, true);
ok(jail.tone === 'jail' && jail.label === "You're in a time-out" && jail.detail === 'Your songs sit out 3 more songs',
   `a time-out turns the strip red with the songs left, on one line (${jail.detail})`);
ok(L.bannerAfter('queued', 'next', null) === 'next' && L.bannerAfter('next', 'playing', 'next') === 'playing',
   'a new "next" or "playing" shows the banner');
ok(L.bannerAfter('playing', 'jail', 'playing') === null && L.bannerAfter('playing', 'queued', 'playing') === null,
   'any other change of the strip takes a stale banner down');
ok(L.bannerAfter('playing', 'playing', 'playing') === 'playing' && L.bannerAfter(null, 'jail', null) === null,
   'no change: the banner stays as it was');
const sk = (o) => ({ downs_at: 3, share: 67, rule: '3 ▼ and two-thirds of the votes skip a song', needed: 3,
                     skipping: false, grace_left_ms: 0, ...o });
ok(L.skipLine(sk({}), 0) === '3 ▼ and two-thirds of the votes skip a song.', 'no ▼ yet: the rule');
ok(L.skipLine(sk({ needed: 1 }), 2) === 'One more ▼ skips this song.', 'one more');
ok(L.skipLine(sk({ needed: 2 }), 1) === '2 more ▼ skip this song.', 'two more');
ok(L.skipLine(sk({ needed: 0, grace_left_ms: 9000 }), 3).includes('in a few seconds'), 'due, waiting out the first seconds');
ok(L.skipLine(sk({ skipping: true, needed: 0 }), 3) === '', 'already skipping: the song\'s own line says so');
ok(L.skipLine(undefined, 0) === '', 'nothing to say for a song that can\'t be skipped');
const song = (o) => ({ kind: 'jukebox', uri: 'u', title: 'T', artist: '', image: '', thumb: '', open_url: '',
                       by: { kind: 'guest', name: 'Ana' }, mine: false, committed: false, starts_in_ms: 1,
                       duration_ms: 1, place: 2, entry_id: 'e', bump: 'down', ...o });
const bumps = (o) => ({ per_hour: 2, left: 2, next_at: null, ...o });
const offer = L.bumpOffer(song({}), bumps({}), { in: false, songs_left: 0, count: 0, at: 5, on: true });
ok(offer.dir === 'down' && offer.can && offer.label === 'Move it down one place', 'someone else\'s song: down');
ok(L.bumpOffer(song({ bump: 'up', mine: true }), bumps({}), undefined).label === 'Move it up one place', 'your own: up');
ok(L.bumpOffer(song({ committed: true }), bumps({}), undefined) === null, 'never the song sent to Spotify');
ok(L.bumpOffer(song({ bump: null }), bumps({}), undefined) === null, 'nothing offered where the server offers nothing');
const used = L.bumpOffer(song({}), bumps({ left: 0, next_at: '9:46' }), undefined);
ok(!used.can && used.why.includes('free at 9:46'), `out of bumps: when the next frees up (${used.why})`);
ok(!L.bumpOffer(song({}), bumps({ per_hour: 0, left: 0 }), undefined).can, 'bumps off');
ok(L.bumpOffer(song({}), bumps({}), { in: true, songs_left: 2, count: 5, at: 5, on: true }).why.includes('after 2 more songs'),
   'in a time-out: no bumps until it ends');
ok(L.bumpsLine(bumps({ left: 1 }), undefined).startsWith('1 bump left this hour'), 'the Queue says how many bumps are left');
ok(!L.addStatus(req({}), true, { in: true, songs_left: 1, count: 5, at: 5, on: true }).canAdd
   && L.addStatus(req({}), true, { in: true, songs_left: 1, count: 5, at: 5, on: true }).text.includes('after 1 more song.'),
   'in a time-out: no adding until it ends');
const mine = (o) => ({ ...song({ mine: true }), state: 'waiting', held: false, known: false, ...o });
ok(L.myStatus(mine({ jailed: true }), 0, nine) === 'Sits out your time-out · keeps its place', 'your song in a time-out');
ok(L.myStatus(mine({ held: true }), 0, nine).startsWith('On hold'), 'your song on hold');
ok(L.myStatus(mine({ state: 'playing' }), 0, nine) === 'Playing now', 'your song playing');
ok(L.myStatus(mine({ starts_in_ms: 120_000, place: 3 }), 0, nine, 'en-US') === '#3 · in 2:00 · ~9:32',
   `your song's place and time (${L.myStatus(mine({ starts_in_ms: 120_000, place: 3 }), 0, nine, 'en-US')})`);

console.log('\ncredits mode (PR 3.2)');
ok(L.credits(1) === '1 credit' && L.credits(4) === '4 credits', 'credits in words');
ok(L.signed(3) === '+3' && L.signed(-4) === '−4' && L.signed(0) === '+0', 'a history row\'s amount, signed');
ok(L.earnedToast(1) === '+1 credit for voting' && L.earnedToast(0) === '' && L.earnedToast(undefined) === '',
   'a vote that paid says so; one that didn\'t says nothing');
ok(JSON.stringify(L.tabsFor({ add: true, board: false, credits: true, shop: true })) === '["now","queue","add","shop"]',
   'credits mode adds the Shop tab, after Add');
ok(JSON.stringify(L.tabsFor({ add: true, board: false, credits: false, shop: false })) === '["now","queue","add"]',
   'free play has no Shop');
const breakout = L.stripText({ tone: 'jail', title: '', place: null, starts_in_ms: null, held: false, count: 1,
                               jail_kind: 'breakout', jail_fee: 10 }, 0, nine, true);
ok(breakout.label === "You're in jail" && breakout.detail.includes('break out (10 credits)'),
   `credits jail: the strip names the way out (${breakout.detail})`);
const paid = (o) => sk({ mode: 'paid', price: 6, pot: 0, pot_mine: 0, need: 6, chip_in: true, per_down_pct: 15,
                         can: true, can_chip: true, why: '', ...o });
const so = L.skipOffer(paid({}), 10);
ok(so.label === 'Skip · 6' && so.can && so.pot.includes('15% with every net ▼') && so.pot.includes('chip in'),
   `a paid skip: its price, and how it falls (${so.label} / ${so.pot})`);
const sp = L.skipOffer(paid({ pot: 4, pot_mine: 2, need: 2 }), 10);
ok(sp.label === 'Skip · 2 more' && sp.pot.startsWith('Pot 4 of 6 · 2 yours') && sp.pot.includes('comes back'),
   `a part-filled pot: the rest, the pot and your share, and the refund (${sp.pot})`);
const sb = L.skipOffer(paid({}), 3);
ok(!sb.can && sb.why === 'That needs 6 credits — you have 3.', `not enough: says what it needs (${sb.why})`);
ok(!L.skipOffer(paid({ can: false, why: 'Not your own song.' }), 10).can, 'the server\'s own refusal wins');
ok(L.skipOffer(sk({}), 10) === null && L.skipOffer(paid({ skipping: true }), 10) === null,
   'nothing to buy in free play, or for a song already skipping');
ok(L.skipLine(paid({}), 0) === '' && L.skipLine(sk({ locked: true }), 0).includes('kept this song from skips'),
   'credits: the button says it all; a kept song says so in either mode');
const tip = (o) => ({ to: 'Ana', unit: 1, can: true, why: '', given: 0, cap: 3, ...o });
ok(L.tipOffer(tip({}), 5).label === 'Tip Ana · 1' && L.tipOffer(tip({}), 5).can, 'tip the guest whose song it is');
ok(!L.tipOffer(tip({}), 0).can && L.tipOffer(tip({}), 0).why.includes('needs 1 credit'), 'no credits, no tip');
ok(L.tipOffer(tip({ to: '', can: false, why: 'Tips go to guests\' songs.' }), 5).label === '',
   'a song with nobody to tip: no button, just why');
ok(L.tipOffer(undefined, 5) === null, 'no tip offer, nothing shown');
const nq = (o) => ({ price: 8, allowed: true, why: '', jump_min: 20, ...o });
ok(L.nextOffer(nq({}), 10).label === 'Play next · 8' && L.nextOffer(nq({}), 10).can, 'play next at its price');
ok(!L.nextOffer(nq({ allowed: false, why: 'It has had its play next.' }), 10).can
   && L.nextOffer(nq({ allowed: false, why: 'It has had its play next.' }), 10).why === 'It has had its play next.',
   'once per song: says why');
ok(!L.nextOffer(nq({}), 4).can, 'not enough credits for play next');
const cj = { in: true, songs_left: 0, count: 6, at: 5, on: true, kind: 'breakout', fee: 10, can_break_out: true };
ok(!L.nextOffer(nq({}), 20, cj).can && L.nextOffer(nq({}), 20, cj).why.includes('break out (10 credits)'),
   'in jail: no play next until you break out');
const card = L.jailCard(cj);
ok(card.fee === 10 && card.text.includes('6 more ▼ than ▲') && card.text.includes('bar at this party is 5'),
   `the jail card: why, and the fee (${card.text})`);
ok(L.jailCard({ ...cj, count: 2 }).text.startsWith('Your songs got too many ▼ tonight (the bar at this party is 5'),
   'a count back under the bar (▲ since) never reads "2 more ▼" as if that were the bar');
ok(L.jailCard({ ...cj, kind: 'timeout' }) === null && L.jailCard(undefined) === null, 'only credits mode\'s jail has a card');
const bo = L.bumpOffer(song({ bump_price: 3 }), bumps({ left: 0 }), undefined, 5);
ok(bo.label === 'Move it down one place · 3' && bo.can, `credits: a move at its price, no hourly count (${bo.label})`);
ok(!L.bumpOffer(song({ bump_price: 3 }), bumps({}), undefined, 2).can, 'credits: a move you can\'t afford');
ok(L.bumpOffer(song({ bump_price: 3 }), bumps({}), cj, 9).why.includes('break out'), 'credits jail: no moves');
ok(L.addOffer({ price: 7, afford: true }).label === 'Add · 7' && !L.addOffer({ price: 7, afford: false }).afford
   && L.addOffer({}).label === 'Add', 'Add shows the price in credits mode, plain in free play');
ok(L.TIP_UNDO_MS === 3000, 'a tip waits three seconds for its undo');

console.log('\nthe Board (phase 3)');
ok(L.boardSongLine({ by: { kind: 'guest', name: 'Ana' }, mine: false, ups: 3, plays: 1 }) === 'Added by Ana · ▲ 3',
   `a board song: who added it and its ▲ (${L.boardSongLine({ by: { kind: 'guest', name: 'Ana' }, mine: false, ups: 3, plays: 1 })})`);
ok(L.boardSongLine({ by: { kind: 'guest', name: 'Ana' }, mine: true, ups: 2, plays: 2 }).endsWith('▲ 2 · played 2 times')
   && L.boardSongLine({ by: { kind: 'guest', name: 'Ana' }, mine: true, ups: 2, plays: 2 }).startsWith(L.byLine({ kind: 'guest', name: 'Ana' }, true)),
   'your own song reads as yours, and a song played twice says so');
ok(JSON.stringify(L.tabsFor({ add: true, board: true, credits: true, shop: true })) === '["now","queue","add","shop","board"]',
   'the bottom bar: Now · Queue · Add · Shop · Board (the plan\'s §7.1 order)');
ok(L.peopleCount(1, { unit: 'songs voted on', unit_one: 'song voted on' }) === '1 song voted on'
   && L.peopleCount(3, { unit: 'songs voted on', unit_one: 'song voted on' }) === '3 songs voted on',
   'a people board counts in words: one song, three songs');
ok(L.BOARD_POLL_MS >= 10000, 'the Board asks again at most every ten seconds or so');

console.log('\nbonus cards (phase 3)');
ok(L.bonusCode(' abcd-efgh ') === 'ABCDEFGH' && L.bonusCode('ABCD EFGH') === 'ABCDEFGH',
   'a typed code folds: case, spaces and dashes');
ok(L.bonusCode('ABCD-EFG') === null && L.bonusCode('ABCD-EFGO') === null && L.bonusCode('ABCD-EFG1') === null
   && L.bonusCode('') === null && L.bonusCode(null) === null,
   'not a code: too short, or a look-alike letter (O, 1) the codes never use');
const withB = L.fromAddress('?t=party-token-123&b=abcd-efgh');
ok(withB.bonus === 'ABCDEFGH' && withB.token === 'party-token-123', 'the join link carries a card\'s code (?b=)');
ok(L.fromAddress('?t=party-token-123&b=nope').bonus === null, 'a bad ?b= is ignored');
ok(L.withoutBonus('?t=party-token-123&b=ABCDEFGH') === '/?t=party-token-123' && L.withoutBonus('?b=ABCDEFGH') === '/',
   'the code is taken out of the address once read (it is used once)');

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
