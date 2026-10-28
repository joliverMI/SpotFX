// Executable spec for the Jukebox page (/jukebox — spectra/web/src/jukebox/,
// data/jukebox-plan/report.md §5 and phase 1 PR 1.3). The jsdom real-mount
// pattern of check_absorb_page.mjs: bundle the REAL source with esbuild,
// mount it under jsdom against a RECORDING fake of SpotFX's own
// /api/jukebox routes (no network — every request lands in `world.requests`
// and nothing else), and drive real events.
//
// Three things proven:
//   1. The editor's click rules (jukeboxEditor.ts, pure): a set song gets a
//      slot after it, a slot gets another right after it — never more than
//      three — and × removes one; the inputs are never mutated; the slot
//      counts and the program bar read the SERVER's projection; a song
//      within two of the playing one can't move; and the words.
//   2. The page, mounted: clicking a set song / a slot / × in Manual PUTs
//      exactly the slots the rule says; Auto → Manual copies the server's
//      own `manual_equivalent`; the sign-in warning shows; the Live tab is
//      read-only (no control in it writes) and shows the night.
//   3. Help: every topic is a real HELP_SECTIONS entry, the menu row's "?"
//      maps /jukebox to `jukebox`, /jukebox is in the Engine menu — and,
//      behaviourally, hovering the page's own controls opens each topic,
//      and the page's 💬 Sonic opens `sonic-jukebox`.
// Plus the Guests tab (§1e pure, §2d mounted, phases 2.2-2.3: the rules, the
// free-play rules, Hold, Play next and Remove on the line, Approve/Pardon/
// Block/Rename/Lock on a phone), the Credits tab (§1b, §2b, phase 3.3) and the party simulator's
// playback (§1c pure, §2c mounted against the harness's own snapshot of the
// server's answer, phase 3.4): it only ever POSTs /api/jukebox/simulate.
//
// Run: node scripts/check_jukebox_editor.mjs (tests/test_jukebox_editor.py).
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
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
const report = () => {
  console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
  process.exit(failures === 0 ? 0 : 1);
};

async function bundle(entrySrc, name) {
  const tmp = mkdtempSync(join(tmpdir(), `jukebox-${name}-`));
  const entry = join(tmp, 'entry.mjs');
  writeFileSync(entry, entrySrc);
  const out = join(tmp, 'out.cjs');
  const r = await esbuild.build({
    entryPoints: [entry], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
    outfile: out, nodePaths: [join(web, 'node_modules')], logLevel: 'silent',
    loader: { '.css': 'empty' },
  });
  if (r.errors.length) throw new Error(r.errors.map((e) => e.text).join('; '));
  return require(out);
}

function loadData(file, name) {
  const code = esbuild.transformSync(readFileSync(file, 'utf8'), { loader: 'ts', format: 'cjs' }).code;
  const tmp = mkdtempSync(join(tmpdir(), `jukebox-${name}-`));
  const outFile = join(tmp, 'out.cjs');
  writeFileSync(outFile, code);
  return require(outFile);
}

const t = (n) => `spotify:track:jukeboxcheck${String(n).padStart(8, '0')}`;
const setItem = (i, title) => ({ uri: t(i), title, artist: `Artist ${i}`, duration_ms: (200 + i) * 1000 });
const open = { kind: 'open', uri: '', title: '', artist: '', duration_ms: 0, set_index: null, entry_id: '', committed: false, starts_in_ms: null };
const setPI = (it, i) => ({ kind: 'set', uri: it.uri, title: it.title, artist: it.artist, duration_ms: it.duration_ms, set_index: i, entry_id: '', committed: false, starts_in_ms: null });

// ── 1. the pure rules ─────────────────────────────────────────────────────
console.log('§1 jukeboxEditor.ts — the click rules and the words');
const E = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/jukeboxEditor.ts'))};`, 'editor');
{
  const none = [];
  const a = E.clickSetSong(none, t(1));
  ok(a.length === 1 && a[0].after_uri === t(1) && a[0].count === 1, 'click a set song: one slot after it');
  ok(none.length === 0, 'the input list is never mutated');
  ok(E.clickSetSong(a, t(1)) === a, 'clicking a song that already has a slot changes nothing');
  const b = E.clickSlot(a, t(1));
  ok(E.slotsAfter(b, t(1)) === 2 && E.slotsAfter(a, t(1)) === 1, 'click a slot: another right after it (two in a row)');
  const c = E.clickSlot(b, t(1));
  ok(E.slotsAfter(c, t(1)) === 3, 'click again: three in a row');
  ok(E.clickSlot(c, t(1)) === c && E.slotsAfter(c, t(1)) === E.MAX_RUN, 'never more than three in a row');
  ok(E.clickSlot(none, t(9)) === none, 'clicking a slot that is not there changes nothing');
  const d = E.removeSlot(c, t(1));
  ok(E.slotsAfter(d, t(1)) === 2, '× removes one slot of a run');
  const e = E.removeSlot(E.removeSlot(d, t(1)), t(1));
  ok(e.length === 0, 'removing the last slot takes the run away');
  const other = E.clickSetSong(E.clickSetSong(none, t(1)), t(2));
  ok(E.slotsAfter(E.clickSlot(other, t(2)), t(1)) === 1, 'a click touches only its own song\'s run');

  const set = [setItem(0, 'A'), setItem(1, 'B'), setItem(2, 'C')];
  const lap = [setPI(set[0], 0), open, open, setPI(set[1], 1), setPI(set[2], 2), open];
  ok(JSON.stringify(E.slotsByIndex(lap, 3)) === '[2,0,1]', 'slot counts come from the server\'s projection');
  const segs = E.barSegments(lap, 1);
  ok(segs.length === 6 && segs.filter((s) => s.kind === 'slot').length === 3, 'the bar has one segment per item');
  ok(segs.find((s) => s.current)?.index === 1, 'the playing set song is marked on the bar');
  ok(E.canMove(5, null) && E.canMove(4, 2) && !E.canMove(3, 2) && !E.canMove(1, 2),
    'during a night only songs two or more ahead can move');
  ok(JSON.stringify(E.moved(['a', 'b', 'c', 'd'], 3, 1)) === '["a","d","b","c"]', 'moved() reorders a copy');

  ok(E.countLine({ set_songs: 38, slots: 21, unbounded: false, notes: [] }, 15)
    === '38 set songs · 21 jukebox slots ≈ 1.4 per guest at 15 guests', 'the count line, the plan\'s own example');
  ok(/as many slots as the line holds/.test(E.countLine({ set_songs: 5, slots: 0, unbounded: true, notes: [] }, 8)),
    'jukebox first has no fixed slot count');
  ok(/every set song/.test(E.ruleLine({ mode: 'auto', every: 1, run: 1, manual: [] }))
    && /2 jukebox slots in a row after every 3 set songs/.test(E.ruleLine({ mode: 'auto', every: 3, run: 2, manual: [] })),
  'the auto rule in words');
  ok(/click a set song/i.test(E.ruleLine({ mode: 'manual', every: 1, run: 1, manual: [] })), 'an empty manual program says how to start');

  ok(E.signInView({ state: 'ok', warning: null }) === null, 'no sign-in line while the sign-in is fine');
  ok(E.signInView({ state: 'soon', warning: 'w' })?.tone === 'warn', 'running out soon is a warning');
  ok(E.signInView({ state: 'refresh_failed', warning: 'x' })?.tone === 'danger', 'a refused sign-in is red');
  ok(JSON.stringify(E.nightWarnings({ warnings: ['sign', 'shuffle'], spotify_auth: { warning: 'sign' } }))
    === '["shuffle"]', 'the night\'s warnings without the sign-in line shown apart');
  ok(E.itemView({ ...open }).title === 'Open slot', 'an open slot reads as one');
  ok(E.itemView({ ...setPI(set[1], 1), kind: 'jukebox', committed: true }).sub.includes('sent to Spotify'),
    'a committed song says it was sent');
  ok(E.startsIn(0) === 'next' && E.startsIn(200_000) === 'in 3:20' && E.mmss(3_725_000) === '1:02:05', 'times');
}

// ── 1b. the Credits tab's words ─────────────────────────────────────────
console.log('\n§1b jukeboxCredits.ts — the settings checks and the price-check words');
const C = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/jukeboxCredits.ts'))};`, 'credits');
const FIELDS = [
  { key: 'start_credits', card: 'Free credits', label: 'Starting credits', unit: 'credits', kind: 'int', default: 8, min: 0, max: 20 },
  { key: 'add_base', card: 'Add a song', label: 'Base price', unit: 'credits', kind: 'int', default: 4, min: 1, max: 20 },
  { key: 'skip_down_pct', card: 'Skip', label: 'Each net ▼ takes off', unit: '%', kind: 'float', default: 15, min: 0, max: 30 },
  { key: 'tips', card: 'Earning', label: 'Tips', unit: '', kind: 'bool', default: true, min: null, max: null },
];
const PC = {
  guests: 15, add: [{ wait_min: 0, price: 4 }, { wait_min: 30, price: 8 }], add_long: { duration_min: 6.5, price: 6 },
  add_not_learned: 5, skip: [{ line_min: 0, downs: 0, price: 55 }, { line_min: 10, downs: 2, price: 30 }],
  play_next: [{ jump_min: 10, price: 11 }], bump_up: [{ behind: 4, price: 3 }], bump_down: [{ ahead: 4, price: 4 }],
  jail: { threshold: 8, fee: 10 }, start: { now: 4, later: 4, after_min: 20 }, topup: { every_min: 45, pauses_at: 10 },
  tips: { on: true, max_per_song: 3, double_first: 5 }, songs_in_line: 2,
};
{
  ok(JSON.stringify(C.groupFields(FIELDS).map((g) => g.card)) === '["Free credits","Add a song","Skip","Earning"]',
    'settings group as their cards, in the server\'s order');
  const f = FIELDS[1];
  ok(C.checkValue(f, '5').ok && C.checkValue(f, '5').value === 5, 'a whole number in range is accepted');
  ok(!C.checkValue(f, '5.5').ok && /whole number/.test(C.checkValue(f, '5.5').reason), 'an int setting refuses a fraction');
  ok(!C.checkValue(f, '0').ok && /at least 1/.test(C.checkValue(f, '0').reason), 'below the range is refused, naming it');
  ok(!C.checkValue(f, '21').ok && /at most 20/.test(C.checkValue(f, '21').reason), 'above the range is refused, naming it');
  ok(!C.checkValue(f, 'x').ok && !C.checkValue(f, '').ok, 'not a number is refused');
  ok(C.checkValue(FIELDS[2], '12.5').ok, 'a decimal is fine for a decimal setting');
  ok(C.rangeLine(f) === '1–20 credits' && C.rangeLine(FIELDS[3]) === '', 'the range line');
  const groups = C.priceRows(PC);
  const flat = groups.flatMap((g) => g.rows.map((r) => `${r.label}=${r.value}`));
  ok(flat.includes('nothing waiting, 0 net ▼=55') && flat.includes('a 10 min line, 2 net ▼=30'), 'the skip rows read the server\'s prices');
  ok(flat.includes('First visit=4 now + 4 after 20 min') && flat.includes('songs in line per guest=2'), 'free credits and the line in words');
  ok(groups.some((g) => g.title === 'Skip (a room of 15)'), 'the skip group names the room size');
}

// ── 1c. the party simulator's playback ──────────────────────────────────
console.log('\n§1c jukeboxSim.ts — the playback arithmetic and its words');
const S = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/jukeboxSim.ts'))};`, 'sim');
const NIGHT = {
  minutes: 240, last_call: 220,
  guests: [
    { id: 0, kind: 'regular', arrive: 0, leave: 241, played: 1, added: 1, earned: 10, spent: 4, tips_given: 0, jails: 0, end_credits: 6 },
    { id: 1, kind: 'quiet', arrive: 30, leave: 120, played: 0, added: 0, earned: 2, spent: 0, tips_given: 0, jails: 1, end_credits: 2 },
  ],
  songs: [{ t: 0, dur: 4, by: null, ups: 1, downs: 0, skipped: null }, { t: 4, dur: 4, by: 0, ups: 0, downs: 3, skipped: 6 }],
  frames: [
    { t: 0, song: 0, cr: [8, 0], back: 0, price: 4, line: 0, jailed: [] },
    { t: 5, song: 1, cr: [4, 0], back: 12, price: 4, line: 1, jailed: [] },
    { t: 40, song: 1, cr: [6, 8], back: 30, price: 8, line: 2, jailed: [1] },
  ],
  events: [
    { t: 2, kind: 'add', g: 0, price: 4, wait: 3.2, rnd: 1 },
    { t: 6, kind: 'skip', price: 14, payers: [1, 0], of: 0 },
    { t: 7, kind: 'tip', g: 1, to: 0, amt: 1, bonus: 1 },
    { t: 41, kind: 'jail', g: 1, downs: 5 },
  ],
  summary: {},
};
{
  ok(S.clock(0) === '0:00' && S.clock(130.7) === '2:10' && S.clock(-3) === '0:00', 'party minutes read as h:mm');
  ok(S.frameAt(NIGHT.frames, 4.9).t === 0 && S.frameAt(NIGHT.frames, 5).t === 5 && S.frameAt(NIGHT.frames, 999).t === 40,
    'the frame at a moment is the last one at or before it');
  ok(S.eventLine(NIGHT.events[0]) === 'Guest 1 added a song for 4 credits (plays in about 3 min)', 'an add in words');
  ok(S.eventLine(NIGHT.events[1]) === "2 guests chipped in 14 credits to skip Guest 1's song", 'a chip-in skip in words');
  ok(S.eventLine(NIGHT.events[2]) === 'Guest 2 tipped Guest 1 1 credit (+1 bonus)', 'a tip, singular, with its bonus');
  ok(S.eventLine({ t: 1, kind: 'skip', price: 20, payers: [1], of: null }) === 'Guest 2 skipped a set song for 20 credits',
    'a lone skip of a set song');
  ok(S.eventLine({ t: 1, kind: 'add', g: 1, price: 9, wait: 0.2, rnd: 2 }).includes('a 2nd song') , 'a 2nd song says so');
  const recent = S.eventsUpTo(NIGHT.events, 7, 2);
  ok(recent.length === 2 && recent[0].t === 7 && recent[1].t === 6, 'recent events are newest first, none from the future');
  const now = S.nowView(NIGHT, 41);
  ok(now.present === 2 && now.line === 2 && now.price === 8 && now.jailed === 1 && now.heldPerGuest === 7,
    `what is true at 0:41 (${JSON.stringify(now)})`);
  ok(S.nowView(NIGHT, 6.5).songLine === "Guest 1's song · 0 ▲ 3 ▼ · skipped", 'a skipped guest song is named and marked');
  ok(S.nowView(NIGHT, 240).songLine === 'The party is over', 'after the last minute the party is over');
  ok(S.playedBy(NIGHT, 0, 3) === 0 && S.playedBy(NIGHT, 0, 4) === 1, 'a guest\'s songs count once they start');
  ok(S.fmtValue('share', 0.374) === '37%' && S.fmtValue('min', 29.4) === '29 min' && S.fmtValue('rate', 0.18) === '0.18'
    && S.fmtValue('count', 41.5) === '41.5' && S.fmtValue('credits', null) === '–', 'values read in their units');
  const row = { key: 'price_mid', label: 'Price', unit: 'credits', yours: 12, tuned: 18.2 };
  const same = S.rowCells(row, true);
  const diff = S.rowCells(row, false);
  ok(same.tuned === null && !same.moved && diff.tuned === '18.2' && diff.moved, 'one column when tuned; a moved row is marked');
  ok(S.checkLine({ key: 'wait_to_play_median', label: 'Wait', target: '≤ 30 min', value: 31.4, ok: false }).text
    === 'Wait — 31 min (wanted ≤ 30 min)', 'a missed promise in words');
  ok(S.checkLine({ key: 'songs_per_lurk', label: 'Quiet', target: '≥ 1 song', value: null, ok: null }).mark === 'none',
    'a promise with nobody to measure is neither met nor missed');
  const res = { guests: 20, plan_preset: 'large', mix_is_plans: false,
    checks: [{ key: 'x', label: 'x', target: '', value: 1, ok: false }] };
  ok(/Large \(jukebox first\)/.test(S.presetHint(res)), 'a miss on a mix that is not the plan\'s names the preset');
  ok(S.presetHint({ ...res, mix_is_plans: true }) === null && S.presetHint({ ...res, checks: [] }) === null,
    'no hint when the night ran the plan\'s mix or nothing was missed');
  const pts = S.chartPoints(NIGHT);
  const g = S.chartGeometry(pts, 240, 600, 200);
  ok(Math.abs(g.tAt(g.x(130)) - 130) < 1e-9 && g.tAt(-50) === 0 && g.tAt(10_000) === 240, 'the chart\'s x and its minute are inverses, clamped');
  ok(g.yMax >= 8 && g.ticks[0] === 0 && g.ticks.at(-1) === g.yMax, 'one credits axis from 0 to a round top');
  const [a, b] = g.labels;
  ok(g.labels.length === 2 && Math.abs(a.y - b.y) >= 12, 'the two line labels never sit on each other');
  ok(S.pointAt(pts, 6).t === 5, 'the hover reads the point at or before the pointer');
}

// ── 1d. the night's report words ──────────────────────────────────────────
console.log('\n§1d jukeboxReport.ts — the report in words, "–" never 0');
const REP = JSON.parse(readFileSync(join(web, 'harness/jukeboxReportSnapshot.json'), 'utf8'));
{
  const RW = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/jukeboxReport.ts'))};`, 'report');
  const facts = Object.fromEntries(RW.nightFacts(REP.night).map((f) => [f.label, f.value]));
  ok(facts['Jukebox songs played'] === '3' && facts['Set songs played'] === '4' && facts['Length'] === '2 h',
    `the night's facts read the server's numbers (${JSON.stringify(facts)})`);
  ok(facts['Add to play (median)'] === '30 min', 'the add-to-play median in minutes');
  ok(facts['Removed / playing / still waiting'] === '1 / 0 / 1', 'removed, still-playing and still-waiting counts');
  const credits = Object.fromEntries(RW.creditFacts(REP.credits).map((f) => [f.label, f.value]));
  ok(credits['Held at the end'] === '8 (30%)' && credits['Guests who used credits'] === '3', 'the credits in words');
  const jail = REP.comparison.rows.find((r) => r.key === 'jails');
  const c = RW.compareCells(jail);
  ok(c.night === '–' && c.why && c.model !== '–', 'a measure the night could not take is "–" with its reason, beside the model');
  ok(RW.endLine({ ...REP.night, state: 'running' }).startsWith('Still running'), 'a running night is a report so far');
}

// ── 1e. the Guests tab's words ───────────────────────────────────────────
console.log('\n§1e jukeboxGuests.ts — how a phone stands, its buttons, who added a song');
const PHONES = [
  { id: 'pa', name: 'Disco Ana', joined: true, created_ms: 1, joined_ms: 1, renames: 0, approved: true, blocked: false, name_locked: false, waiting: 1, played: 2, votes: 1 },
  { id: 'pb', name: 'Velvet Moose', joined: true, created_ms: 2, joined_ms: 2, renames: 0, approved: false, blocked: false, name_locked: false, waiting: 0, played: 0, votes: 0 },
  { id: 'pc', name: 'Witty Gecko', joined: false, created_ms: 3, joined_ms: null, renames: 0, approved: true, blocked: true, name_locked: true, waiting: 0, played: 0, votes: 0 },
  { id: 'pd', name: 'Lucky Otter', joined: true, created_ms: 4, joined_ms: 4, renames: 0, approved: true, blocked: false, name_locked: false, waiting: 1, played: 1, votes: 3, jail_left: 3, jail_count: 5, jail_at: 5, jails: 1 },
];
{
  const GW = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/jukeboxGuests.ts'))};`, 'guests');
  ok(GW.ordinal(1) === '1st' && GW.ordinal(2) === '2nd' && GW.ordinal(3) === '3rd' && GW.ordinal(11) === '11th', 'ordinals');
  ok(GW.phoneLine(PHONES[0]) === 'in · 1 in line · 2 played · 1 vote', `a phone in words (${GW.phoneLine(PHONES[0])})`);
  ok(GW.phoneState(PHONES[1]) === 'waiting' && GW.phoneState(PHONES[2]) === 'blocked', 'waiting and blocked phones');
  ok(JSON.stringify(GW.phoneActions(PHONES[1])) === '["approve","block","lock","rename"]', 'only a waiting phone can be approved');
  ok(JSON.stringify(GW.phoneActions(PHONES[2])) === '["unblock","unlock","rename"]', 'a blocked phone unblocks; a locked name unlocks');
  const line = [
    { id: 'e1', uri: 'u1', title: 'A', artist: '', duration_ms: 1, added_by: 'host', state: 'committed', doomed: false, commit_check: 'next' },
    { id: 'e2', uri: 'u2', title: 'B', artist: '', duration_ms: 1, added_by: 'pa', state: 'queued', doomed: false, commit_check: '', round: 2, held: true },
    { id: 'e3', uri: 'u3', title: 'C', artist: '', duration_ms: 1, added_by: 'gone', state: 'queued', doomed: false, commit_check: '' },
    { id: 'e4', uri: 'u4', title: 'D', artist: '', duration_ms: 1, added_by: 'pa', state: 'played', doomed: false, commit_check: '' },
  ];
  const rows = GW.lineRows(line, PHONES);
  ok(rows.length === 3, 'only songs still to play are listed');
  ok(rows[0].sent && !rows[0].canHold && rows[0].by === 'the host', 'a song sent to Spotify can be removed, not held');
  ok(rows[1].by === 'Disco Ana' && rows[1].round === '2nd song' && rows[1].held && rows[1].canHold, 'a held 2nd song, by name');
  ok(rows[2].by === 'a guest', 'an unknown phone reads "a guest"');
  // free play (PR 2.3): the time-out, Pardon, Play next
  ok(GW.phoneState(PHONES[3]) === 'jailed'
    && GW.phoneLine(PHONES[3]) === 'in a time-out (3 songs to go) · 1 in line · 1 played · 3 votes',
    `a phone in a time-out says how many songs are left (${GW.phoneLine(PHONES[3])})`);
  ok(JSON.stringify(GW.phoneActions(PHONES[3])) === '["pardon","block","lock","rename"]', 'only a phone in a time-out can be pardoned');
  ok(GW.phoneLine({ ...PHONES[0], jail_count: 2, jail_at: 5 }).includes('net ▼ 2 of 5'), 'a phone shows its ▼ count against the bar');
  ok(!rows.some((r) => r.canPlayNext), 'no Play next unless the show lets the host');
  const jl = GW.lineRows([...line, { id: 'e5', uri: 'u5', title: 'E', artist: '', duration_ms: 1, added_by: 'pd', state: 'queued', doomed: false, commit_check: '' }], PHONES, true);
  ok(!jl[1].canPlayNext && jl[2].canPlayNext && jl[3].canPlayNext && !jl[0].canPlayNext,
    'Play next on every waiting song but the first (never on the one sent to Spotify)');
  ok(jl[3].jailed && !jl[1].jailed, 'a song whose guest is in a time-out says so');
  // credits mode (PR 3.2): a phone's credits, the jail until break-out, the skip lock
  ok(GW.phoneLine({ ...PHONES[0], credits: 7 }).includes('🎟 7'), 'a phone shows the credits it holds');
  ok(GW.phoneLine({ ...PHONES[3], jail_kind: 'breakout' })
    === 'in jail (until they break out) · 1 in line · 1 played · 3 votes',
    `credits mode's jail says it lasts until they break out (${GW.phoneLine({ ...PHONES[3], jail_kind: 'breakout' })})`);
  // jail status and the net ▼ count are never shown together; the credits
  // balance rides alongside either one (review-3's fix)
  ok(GW.phoneLine({ ...PHONES[3], credits: 7 })
    === 'in a time-out (3 songs to go) · 🎟 7 · 1 in line · 1 played · 3 votes',
    `the credits chip shows beside a time-out, never the ▼ count too (${GW.phoneLine({ ...PHONES[3], credits: 7 })})`);
  // zero and merge (§4's host buttons, §12's cookie-reset guard)
  ok(/^since \d\d:\d\d$/.test(GW.sinceWords(Date.UTC(2026, 9, 27, 1, 42))), 'a phone says when it first opened the page');
  ok(JSON.stringify(GW.phoneTakes({ ...PHONES[0], credits: 4 }, PHONES)) === '["zero","merge"]'
    && JSON.stringify(GW.phoneTakes(PHONES[0], PHONES)) === '["merge"]'
    && JSON.stringify(GW.phoneTakes({ ...PHONES[0], credits: 0 }, PHONES)) === '["merge"]',
    'Zero only while a phone holds credits; Merge while another phone could join');
  ok(JSON.stringify(GW.phoneTakes({ ...PHONES[2], credits: 4 }, PHONES)) === '[]', 'a blocked phone gets neither');
  ok(JSON.stringify(GW.phoneTakes(PHONES[0], [PHONES[0], PHONES[2]])) === '[]', 'no Merge with only a blocked phone to join it');
  ok(JSON.stringify(GW.mergeCandidates(PHONES[0], PHONES).map((p) => p.id)) === '["pb","pd"]',
    'the phones that could join: every other, not blocked');
  const mw = GW.mergeWords({ ...PHONES[3], created_ms: 9 }, { ...PHONES[0], credits: 6 });
  ok(mw.includes('Disco Ana becomes part of Lucky Otter') && mw.includes('6 credits') && mw.endsWith("they're called Disco Ana."),
    `a merge says what moves and that the guest keeps the first phone's name (${mw})`);
  ok(GW.phoneLine({ ...PHONES[0], merged_from: ['Lucky Otter'] }).endsWith('merged with Lucky Otter'),
    'a kept phone names the phones merged into it');
  const EW = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/jukeboxEconomy.ts'))};`, 'econ');
  ok(EW.signed(3) === '+3' && EW.signed(-6) === '−6' && EW.signed(0) === '', 'credits read signed, nothing for none');
  ok(EW.freePlayLine({ votes: 1, time_outs: 2 }) === 'Free play: nothing costs anything — 1 vote and 2 time-outs so far tonight.',
    'free play says what the room did instead of an economy');
  ok(EW.roomLine({ crowd: 1, joined: 1, jailed: 0 }) === '1 phone here in the last 15 min · 1 joined', 'who is here');
  ok(EW.activityLine({ adds: 1, skips_hr: null, nexts_hr: 0.5, tips_hr: null, votes: 1, free: 8 })
    === '1 song added · play next 0.5/h · 1 vote paid · 8 free credits handed out', 'an hourly rate the night can\'t measure yet is left out');
  ok(EW.priceRows({ add_first: 4, add_back: 4, back_wait_min: null, skip_now: null, next_from: 11, jail_fee: 10 })
    .map((r) => `${r.label}=${r.value}`).join('|')
    === 'A 1st song, now=4|At the back of the line=4|Skip the song playing=nothing playing|Play next=from 11|Break out of jail=10',
  'the prices, with nothing playing to skip');
  const waiting = { ...line[1], state: 'queued', held: true, paid: 5, round: 2 };
  ok(EW.liveLineWords(waiting, PHONES) === `waiting · added by ${GW.adderName(waiting, PHONES)} · 2nd song · on hold · paid 🎟 5`,
    `a held song in the Live line (${EW.liveLineWords(waiting, PHONES)})`);
  ok(EW.liveLineWords({ ...waiting, added_by: 'nobody-here', held: false, paid: 0 }, PHONES).includes('added by a guest'),
    'a guest the page no longer knows is "a guest", never their code');
  const kl = GW.lineRows(line, PHONES, false, ['u2']);
  ok(kl[1].skipLocked && !kl[0].skipLocked && !kl[2].skipLocked, 'a song the host kept from skips is marked, by its song');
  ok(GW.lineRows([{ ...line[1], paid: 6 }], PHONES)[0].paid === 6, 'what a guest paid for a song rides on its row');
}

console.log('\n§1f jukeboxBoard.ts — the board\'s words (songs, not people; people boards his switches)');
const BOARD_SONG = (o) => ({ uri: 'spotify:track:a', title: 'Dopamine', artist: 'Wooli', image: '', thumb: '',
  open_url: 'https://open.spotify.com/track/a', by: { kind: 'guest', name: 'Disco Ana' }, ups: 3, downs: 0, plays: 1, ...o });
const PEOPLE_BOARDS = [
  { id: 'pickers', title: 'Top pickers', unit: '▲ on the songs they added', shown: false, rows: [{ name: 'Disco Ana', value: 3 }] },
  { id: 'voters', title: 'Top voters', unit: 'songs voted on', shown: true, rows: [{ name: 'Lucky Otter', value: 5 }] },
];
{
  const BW = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/jukeboxBoard.ts'))};`, 'board');
  ok(BW.boardSongLine(BOARD_SONG({})) === 'added by Disco Ana · ▲ 3', `a song's line (${BW.boardSongLine(BOARD_SONG({}))})`);
  ok(BW.boardSongLine(BOARD_SONG({ by: { kind: 'set', name: "Host's set" }, plays: 2 })) === "the host's set · ▲ 3 · played 2 times",
    'a set song played twice');
  ok(BW.peopleHeading(PEOPLE_BOARDS[0]).endsWith("(guests don't see this)") && !BW.peopleHeading(PEOPLE_BOARDS[1]).includes('see this'),
    'the host is told which people boards guests don\'t see');
  ok(JSON.stringify(BW.tvPeople(PEOPLE_BOARDS).map((p) => p.id)) === '["voters"]', 'the TV shows only the people boards guests see');
  ok(BW.tvOffLine({ board_on_tv: false }).includes('On the TV') && BW.tvOffLine({ board_on_tv: true }) === '',
    'the TV page says how to turn it on, and nothing once it is on');
}

// ── 2. the page, mounted ──────────────────────────────────────────────────
let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('\njsdom not installed in spectra/web/node_modules (dev-only) — skipping §2-3.');
  report();
}
const { JSDOM } = jsdomMod;
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/jukebox' });
// jsdom lays nothing out, so it has no Element.scrollTo (the 💬 panel's
// message list calls it) — check_absorb_page.mjs's own stand-in.
if (!dom.window.HTMLElement.prototype.scrollTo) dom.window.HTMLElement.prototype.scrollTo = () => {};
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
for (const k of ['HTMLElement', 'HTMLInputElement', 'Node', 'Element', 'MouseEvent', 'KeyboardEvent', 'FocusEvent', 'Event', 'getComputedStyle']) {
  globalThis[k] = dom.window[k];
}
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SET = [setItem(0, 'Mr. Brightside'), setItem(1, 'Dancing Queen'), setItem(2, 'September'), setItem(3, 'Hey Ya!')];
const GF = JSON.parse(readFileSync(join(web, 'harness/jukeboxShowSnapshot.json'), 'utf8')).guest_fields;
let world;
// the Simulate tab's mock: the harness's own snapshot of the server's answer
// (tests/test_jukebox_simulator.py holds it to the real route)
const SIM = JSON.parse(readFileSync(join(web, 'harness/jukeboxSimSnapshot.json'), 'utf8'));
function newWorld(kind) {
  const manual = kind === 'manual';
  const running = kind === 'running';
  return {
    config: { playlist: 'spotify:playlist:check', mode: manual ? 'manual' : 'auto', every: 2, run: 1,
              manual: manual ? [{ after_uri: t(1), count: 2 }] : [], run_out: 'again', commit_lead_s: 45 },
    running,
    show: { preset: null, approve_new_phones: false, economy: { start_credits: 8, add_base: 4, skip_down_pct: 15, tips: true },
            night_ends: '00:00', last_call_min: 20, explicit: 'no', explicit_after: '22:00', max_phones: 40,
            renames_per_night: 3, word_filter: true, free_skip_downs: 3, free_skip_share: 67,
            free_bumps_per_hour: 2, free_play_next: 'host', free_jail_songs: 5, play_mode: 'credits',
            board_on: true, board_top_pickers: false, board_top_voters: false, board_most_generous: false,
            board_on_tv: false },
    phones: running ? JSON.parse(JSON.stringify(PHONES)) : [],
    noSkip: new Set(),
    codes: [{ code: 'ABCD-EFGH', batch: 'Saturday', created_ms: 1, used: false, used_ms: null, used_name: '' },
            { code: 'WXYZ-2345', batch: 'Saturday', created_ms: 1, used: true, used_ms: 5, used_name: 'Disco Ana' }],
    requests: [],
  };
}
const PRESETS = [
  { name: 'small', guests: '4-8', why: 'Every other song is the jukebox\'s.', approve_new_phones: false },
  { name: 'medium', guests: '9-16', why: 'Two jukebox songs per set song.', approve_new_phones: false },
  { name: 'large', guests: '17-30', why: 'Jukebox first.', approve_new_phones: true },
];
function lapFor(cfg) {
  const out = [];
  let since = 0;
  SET.forEach((it, i) => {
    out.push(setPI(it, i));
    let gap = 0;
    if (cfg.mode === 'manual') gap = cfg.manual.find((m) => m.after_uri === it.uri)?.count ?? 0;
    else { since += 1; if (since >= cfg.every) { gap = cfg.run; since = 0; } }
    for (let k = 0; k < gap; k += 1) out.push(open);
  });
  return out;
}
const sign = { state: 'soon', warning: 'SpotFX\'s Spotify sign-in runs out by 2026-11-05 (9 days left) — sign in again before then.', days_left: 9 };
const ECON = { running: true, play_mode: 'credits', crowd: 4, joined: 3, jailed: 1, votes: 12, time_outs: 1,
  credits: { minted: 60, held: 25, held_per_guest: 8.3, unspent_share: 0.417, by_kind: {}, adds: 3, skips_hr: 1.2,
             nexts_hr: null, tips_hr: 2, add_price_median: 5, votes: 12, free: 24 },
  prices: { add_first: 4, add_back: 9, back_wait_min: 31.6, skip_now: 21, next_from: 11, jail_fee: 10 },
  events: [{ at_ms: Date.UTC(2026, 9, 28, 1, 42), kind: 'add', who: 'Disco Ana', what: 'added “Take On Me”', credits: -6 },
           { at_ms: Date.UTC(2026, 9, 28, 1, 40), kind: 'host_gift', who: 'the host', what: 'gave 3 guests 2 each', credits: 2, phones: 3 }] };
function statusOf() {
  if (!world.running) return { night: null, running: false, now: null, next: [], line: [], warnings: [sign.warning], spotify_auth: sign, log: [], history: [] };
  return {
    night: { id: 'n', state: 'running', started_ms: 1, started_by: 'press', ended_ms: null, end_reason: '', end_detail: '', playlist_name: 'Saturday set', playlist_uri: '', played: 3, jukebox_played: 1 },
    running: true,
    now: { kind: 'set', uri: SET[1].uri, title: 'Dancing Queen', set_index: 1, entry_id: '', started_ms: 1 },
    remaining_ms: 40_000,
    next: [{ kind: 'jukebox', uri: 'spotify:track:j', title: 'Bad Romance', artist: 'Lady Gaga', duration_ms: 1, set_index: null, entry_id: 'e1', committed: true, starts_in_ms: 40_000 }],
    line: [{ id: 'e1', uri: 'spotify:track:j', title: 'Bad Romance', artist: 'Lady Gaga', duration_ms: 1, added_by: 'host', state: 'committed', doomed: false, commit_check: 'next' },
           { id: 'e2', uri: 'spotify:track:k', title: 'Take On Me', artist: 'a-ha', duration_ms: 1, added_by: 'pa', state: 'queued', doomed: false, commit_check: '', round: 1, paid: 6 },
           { id: 'e3', uri: 'spotify:track:m', title: 'Vogue', artist: 'Madonna', duration_ms: 1, added_by: 'pd', state: 'queued', doomed: false, commit_check: '', round: 1 }],
    warnings: [sign.warning, 'Shuffle is on in Spotify, so the set won\'t play in order.'], spotify_auth: sign,
    log: ['started'], history: [], no_skip: [...world.noSkip],
  };
}

globalThis.fetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const body = init.body ? JSON.parse(init.body) : undefined;
  world.requests.push({ method, url: String(url), body });
  const json = (b) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
  const u = String(url);
  if (u.startsWith('/api/jukebox/config')) {
    if (method === 'PUT') { world.config = { ...world.config, ...body }; return json({ dry_run: false, config: world.config }); }
    return json(world.config);
  }
  if (u.startsWith('/api/jukebox/show/preset')) {
    world.show = { ...world.show, preset: body.preset, approve_new_phones: body.preset === 'large' };
    return json({ show: world.show, fields: FIELDS, guest_fields: GF, presets: PRESETS, config: world.config });
  }
  if (u.startsWith('/api/jukebox/show')) {
    if (method === 'PUT') {
      const { economy, ...rest } = body;
      world.show = { ...world.show, ...rest, economy: { ...world.show.economy, ...(economy || {}) } };
    }
    return json({ show: world.show, fields: FIELDS, guest_fields: GF, presets: PRESETS });
  }
  if (u.startsWith('/api/jukebox/guests')) {
    const id = u.split('/api/jukebox/guests/')[1];
    if (method === 'POST' && id?.endsWith('/zero')) {
      const pid = decodeURIComponent(id.split('/')[0]);
      const was = world.phones.find((p) => p.id === pid)?.credits ?? 0;
      world.phones = world.phones.map((p) => (p.id === pid ? { ...p, credits: 0 } : p));
      return json({ status: 'ok', zeroed: { name: pid, credits: was }, running: world.running, phones: world.phones });
    }
    if (method === 'POST' && id?.endsWith('/merge')) {
      const keep = decodeURIComponent(id.split('/')[0]);
      const gone = world.phones.find((p) => p.id === body.retire);
      world.phones = world.phones.filter((p) => p.id !== body.retire)
        .map((p) => (p.id === keep ? { ...p, merged_from: [gone.name] } : p));
      return json({ status: 'ok', merged: { name: keep, songs: 2, credits: 0 }, running: world.running, phones: world.phones });
    }
    if (method === 'POST' && id) {
      const { pardon, ...patch } = body || {};
      world.phones = world.phones.map((p) => (p.id === decodeURIComponent(id)
        ? { ...p, ...patch, ...(pardon ? { jail_left: 0, jail_count: 0 } : {}) } : p));
    }
    return json({ running: world.running, phones: world.phones, pending: world.phones.filter((p) => !p.approved && !p.blocked).length });
  }
  if (u.startsWith('/api/jukebox/line/')) {
    if (u.endsWith('/move')) return json({ status: 'moved', line: [] });
    return json(method === 'DELETE' ? { status: 'removed' } : { status: body?.held ? 'held' : 'released' });
  }
  if (u.startsWith('/api/jukebox/board')) {
    const sh = world.show;
    const settings = { board_on: sh.board_on ?? true, board_top_pickers: !!sh.board_top_pickers,
      board_top_voters: !!sh.board_top_voters, board_most_generous: !!sh.board_most_generous, board_on_tv: !!sh.board_on_tv };
    if (!world.running) return json({ running: false, settings });
    return json({ running: true, settings,
      board: { title: "Tonight's top songs", empty: 'No ▲ yet tonight.',
               songs: [BOARD_SONG({}), BOARD_SONG({ uri: 'spotify:track:b', title: 'Dancing Queen', by: { kind: 'set', name: "Host's set" }, ups: 2, downs: 1 })],
               people: PEOPLE_BOARDS.map((p) => ({ ...p, shown: !!settings[p.id === 'pickers' ? 'board_top_pickers' : 'board_top_voters'] })) },
      now: { ...BOARD_SONG({ title: 'Ready to Run', by: { kind: 'set', name: "Host's set" } }), up: 4, down: 1 } });
  }
  if (u.startsWith('/api/jukebox/gift')) {
    return json({ status: 'ok', gift: { amount: body.amount, phones: body.to === 'everyone' ? 2 : 1, names: [] } });
  }
  if (u.startsWith('/api/jukebox/bonus-codes')) {
    if (method === 'POST') {
      const made = Array.from({ length: body.count }, (_, i) => `MADE-${String(i).padStart(4, '2')}`);
      world.codes = [...made.map((code) => ({ code, batch: body.batch || 'today', created_ms: 2, used: false, used_ms: null, used_name: '' })), ...world.codes];
      const out = { unused: world.codes.filter((c) => !c.used).length, used: world.codes.filter((c) => c.used).length, codes: world.codes };
      return json({ made, ...out });
    }
    if (method === 'DELETE') world.codes = world.codes.filter((c) => c.code !== decodeURIComponent(u.split('/').pop()));
    return json({ unused: world.codes.filter((c) => !c.used).length, used: world.codes.filter((c) => c.used).length, codes: world.codes });
  }
  if (u.startsWith('/api/jukebox/skip-lock')) {
    if (body.locked) world.noSkip.add(body.uri); else world.noSkip.delete(body.uri);
    return json({ status: body.locked ? 'locked' : 'unlocked', uri: body.uri });
  }
  if (u.startsWith('/api/jukebox/price-check')) return json(PC);
  if (u.startsWith('/api/jukebox/simulate')) return json(SIM);
  if (u.startsWith('/api/jukebox/report')) return json(REP);
  if (u.startsWith('/api/jukebox/status')) return json(statusOf());
  if (u.startsWith('/api/jukebox/economy')) return json(world.running ? ECON : { running: false, play_mode: 'credits' });
  if (u.startsWith('/api/jukebox/preview')) {
    return json({ status: 'ok', playlist_name: 'Saturday set', set_songs: SET.length, set: SET,
      lap_items: lapFor(world.config), next: [], playhead: world.running ? 1 : null,
      manual_equivalent: [{ after_uri: t(1), count: 1 }, { after_uri: t(3), count: 1 }],
      lap: { set_songs: SET.length, slots: lapFor(world.config).filter((x) => x.kind === 'open').length, unbounded: false, notes: [] } });
  }
  return json({});
};

const P = await bundle(`
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import JukeboxPage from ${JSON.stringify(join(web, 'src/jukebox/JukeboxPage.tsx'))};
import { ToastProvider } from ${JSON.stringify(join(web, 'src/components/Toast.tsx'))};
let root = null;
const container = document.createElement('div');
document.body.appendChild(container);
export function mount() {
  if (root) act(() => { root.unmount(); });
  root = createRoot(container);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(ToastProvider, null,
        React.createElement(MemoryRouter, { initialEntries: ['/jukebox'] }, React.createElement(JukeboxPage)))));
  });
  return container;
}
export async function settle(ms = 30) {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
  }
}
export function actSync(fn) { act(fn); }
export function unmount() { if (root) act(() => { root.unmount(); }); root = null; }
`, 'page');

const $ = (c, sel) => c.querySelector(sel);
const text = (el) => (el ? el.textContent : '');
const click = async (el) => {
  P.actSync(() => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })));
  await P.settle();
};
const buttonByText = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent));
const puts = () => world.requests.filter((r) => r.method === 'PUT');
const writes = () => world.requests.filter((r) => r.method !== 'GET');

console.log('\n§2 the editor, mounted — every click PUTs the slots the rule says');
{
  world = newWorld('manual');
  const c = P.mount();
  await P.settle();
  ok(!!$(c, '[data-testid="jukebox-set-list"]'), 'the running order renders');
  ok(c.querySelectorAll('.jukebox-slot').length === 2, 'Dancing Queen shows its two hand-placed slots');
  ok(text($(c, '[data-testid="jukebox-sign-in"]')).includes('runs out by'), 'the Spotify sign-in line shows its date');

  await click($(c, '[data-testid="set-song-2"]'));
  let last = puts().at(-1)?.body;
  ok(JSON.stringify(last) === JSON.stringify({ manual: [{ after_uri: t(1), count: 2 }, { after_uri: t(2), count: 1 }] }),
    `clicking September PUTs a slot after it (${JSON.stringify(last)})`);

  await click($(c, '[data-testid="slot-1-0"]'));
  last = puts().at(-1)?.body;
  ok(JSON.stringify(last.manual.find((m) => m.after_uri === t(1))) === JSON.stringify({ after_uri: t(1), count: 3 }),
    'clicking a slot PUTs another right after it (three in a row)');

  const x = c.querySelector('.jukebox-slot-x');
  await click(x);
  last = puts().at(-1)?.body;
  ok(last.manual.find((m) => m.after_uri === t(1))?.count === 2, '× PUTs one slot fewer');
  P.unmount();
}
{
  world = newWorld('auto');
  const c = P.mount();
  await P.settle();
  ok(c.querySelectorAll('.jukebox-slot-btn').length === 0, 'in Auto the slots are shown, not clickable');
  ok(!$(c, '[data-testid="set-song-0"]'), 'in Auto a set song is not a slot button');
  await click(buttonByText(c, /^Manual$/));
  const last = puts().at(-1)?.body;
  ok(last?.mode === 'manual' && JSON.stringify(last.manual) === JSON.stringify([{ after_uri: t(1), count: 1 }, { after_uri: t(3), count: 1 }]),
    'Auto → Manual copies the server\'s own manual_equivalent');
  const sel = c.querySelector('select[aria-label="When the set runs out"]');
  ok(!!sel, 'the run-out choice is on the page');
  P.unmount();
}
{
  world = newWorld('running');
  const c = P.mount();
  await P.settle();
  ok(c.querySelector('input[aria-label="Set playlist link"]')?.disabled === true,
    'the set playlist can\'t be swapped under a running night');
  ok(c.querySelectorAll('.jukebox-handle-off').length === 3,
    'the playing song and the one after it (and every earlier one) can\'t be dragged');
  const before = writes().length;
  await click(buttonByText(c, /^Live$/));
  ok(text($(c, '[data-testid="jukebox-night"]')).includes('Running since') && text($(c, '[data-testid="jukebox-night"]')).includes('Saturday set'),
    'the Live tab names the night');
  ok(text($(c, '[data-testid="jukebox-now"]')).includes('Dancing Queen') && text($(c, '[data-testid="jukebox-now"]')).includes('Set 2'),
    'and what is playing');
  ok(text($(c, '[data-testid="jukebox-next"]')).includes('sent to Spotify'), 'the committed song says it was sent');
  await P.settle();
  const liveRows = [...c.querySelectorAll('[data-testid="jukebox-line"] .jukebox-item')].map(text);
  ok(liveRows[1]?.includes('added by Disco Ana') && liveRows[1].includes('1st song') && liveRows[1].includes('paid 🎟 6')
    && !liveRows.some((r) => / pa\b| pd\b/.test(r)),
    `the Live line names who added each song (never a phone's code) and what they paid (${liveRows[1]})`);
  ok(liveRows[2]?.includes('added by Lucky Otter') && liveRows[2].includes('sits out a time-out')
    && liveRows[0]?.includes('added by the host'), 'and which songs sit out a time-out');
  const econ = $(c, '[data-testid="jukebox-economy"]');
  ok(!!econ && text($(c, '[data-testid="jukebox-economy-credits"]')) === '25 credits held · 8.3 a guest · 60 made tonight · 42% still unspent',
    `the economy card says the credits right now (${text($(c, '[data-testid="jukebox-economy-credits"]'))})`);
  ok(text($(c, '[data-testid="jukebox-economy-prices"]')).includes('At the back of the line (~32 min)9')
    && text($(c, '[data-testid="jukebox-economy-prices"]')).includes('Skip the song playing21'), 'and the prices a guest sees now');
  const evs = [...c.querySelectorAll('[data-testid="jukebox-economy-events"] li')].map(text);
  ok(evs.length === 2 && evs[0].includes('Disco Ana added “Take On Me”') && evs[0].includes('−6')
    && evs[1].includes('the host gave 3 guests 2 each') && evs[1].includes('+2'), `and what happened lately (${evs.join(' | ')})`);
  ok(text($(c, '[data-testid="jukebox-live-card"]')).includes('Shuffle is on')
    && !text($(c, '[data-testid="jukebox-live-card"]')).includes('runs out by'),
  'the night\'s own warning shows on Live; the sign-in line is not shown twice');
  ok(text($(c, '[data-testid="jukebox-report-summary"]')) === REP.summary, 'the night\'s report closes the Live tab');
  ok(c.querySelectorAll('[data-testid="jukebox-report-compare"] .jukebox-sim-tr:not(.head)').length === REP.comparison.rows.length,
    'a guest night sits beside the model\'s nights, row for row');
  const sizeSel = c.querySelector('select[aria-label="Compare with a party of"]');
  P.actSync(() => { sizeSel.value = '8'; sizeSel.dispatchEvent(new dom.window.Event('change', { bubbles: true })); });
  await P.settle();
  ok(world.requests.some((r) => r.method === 'GET' && r.url === '/api/jukebox/report?guests=8'),
    'picking a party size asks for the report at that size');
  const live = c.querySelector('[data-testid="jukebox-live-card"]')?.parentElement;
  for (const b of live ? [...live.querySelectorAll('button')] : []) await click(b);
  ok(writes().length === before, 'nothing on the Live tab writes — it is read-only');
  P.unmount();
}

console.log('\n§2b the Credits tab, mounted — presets, the price check, each setting');
{
  world = newWorld('auto');
  const c = P.mount();
  await P.settle();
  await click(buttonByText(c, /^Credits$/));
  ok(c.querySelectorAll('.jukebox-preset').length === 3, 'the three party-size presets render');
  ok(text($(c, '[data-testid="jukebox-price-check"]')).includes('55'), 'the price check shows the server\'s prices');
  await click(buttonByText(c, /Medium/));
  const pre = world.requests.filter((r) => r.method === 'POST' && r.url.startsWith('/api/jukebox/show/preset')).at(-1);
  ok(pre?.body?.preset === 'medium', 'a preset button POSTs its name');
  ok($(c, '.jukebox-preset.on')?.textContent.includes('Medium'), 'the applied preset is marked');
  const input = c.querySelector('input[aria-label="Base price"]');
  const setVal = (el, v) => {
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set;
    P.actSync(() => { setter.call(el, v); el.dispatchEvent(new dom.window.Event('input', { bubbles: true })); });
  };
  const blur = (el) => P.actSync(() => el.dispatchEvent(new dom.window.FocusEvent('focusout', { bubbles: true })));
  const before = puts().length;
  setVal(input, '21');
  blur(input);
  await P.settle();
  ok(puts().length === before, 'an out-of-range value is refused on the page — nothing is sent');
  setVal(input, '5');
  blur(input);
  await P.settle();
  ok(JSON.stringify(puts().at(-1)?.body) === JSON.stringify({ economy: { add_base: 5 } }),
    `a valid value PUTs exactly that setting (${JSON.stringify(puts().at(-1)?.body)})`);
  const tips = c.querySelector('input[aria-label="Tips"]');
  await click(tips);
  ok(JSON.stringify(puts().at(-1)?.body) === JSON.stringify({ economy: { tips: false } }), 'a switch PUTs its new value');
  const modeCard = $(c, '[data-testid="jukebox-mode"]');
  const modeOn = () => [...modeCard.querySelectorAll('button[role="radio"]')].find((b) => b.getAttribute('aria-checked') === 'true');
  ok(text(modeOn()) === 'Credits' && text(modeCard).includes('the Shop'), 'the Mode card shows the night\'s mode: credits');
  const beforeMode = puts().length;
  await click(buttonByText(modeCard, /^Credits$/));
  ok(puts().length === beforeMode, 'pressing the mode already on sends nothing');
  await click(buttonByText(modeCard, /^Free play$/));
  ok(JSON.stringify(puts().at(-1)?.body) === '{"play_mode":"free"}', `Free play PUTs exactly {play_mode: "free"} (${JSON.stringify(puts().at(-1)?.body)})`);
  await P.settle();
  ok(text(modeOn()) === 'Free play' && text(modeCard).includes('Nothing costs anything'), 'the Mode card shows free play once saved');
  // the printed bonus cards (phase 3)
  const bonusCard = $(c, '[data-testid="jukebox-bonus-cards"]');
  ok(text(bonusCard).includes('1 unused · 1 used') && text(bonusCard).includes('used by Disco Ana'),
    `the Bonus cards card counts the codes and names who used one (${text(bonusCard).slice(0, 80)})`);
  ok([...bonusCard.querySelectorAll('li')].filter((li) => li.querySelector('button')).length === 1,
    'only an unused code can be voided');
  await click(buttonByText(bonusCard, /^Make codes$/));
  const mintReq = world.requests.filter((r) => r.method === 'POST' && r.url === '/api/jukebox/bonus-codes').at(-1);
  ok(JSON.stringify(mintReq?.body) === '{"count":10,"batch":""}', `Make codes POSTs the count and label (${JSON.stringify(mintReq?.body)})`);
  await P.settle();
  ok(text($(c, '[data-testid="jukebox-bonus-cards"]')).includes('11 unused'), 'the new codes are listed, unused first');
  await click(c.querySelector('[data-testid="jukebox-bonus-cards"] button[aria-label="Void ABCD-EFGH"]'));
  ok(world.requests.some((r) => r.method === 'DELETE' && r.url === '/api/jukebox/bonus-codes/ABCD-EFGH'), 'Void DELETEs that code');
  P.unmount();
}

console.log('\n§2c the Simulate tab, mounted — run a night, play it back, compare');
{
  world = newWorld('auto');
  const c = P.mount();
  await P.settle();
  await click(buttonByText(c, /^Simulate$/));
  ok(!!$(c, '[data-testid="jukebox-sim-controls"]') && !$(c, '[data-testid="jukebox-sim-now"]'),
    'the tab opens on its controls, with no night until one is run');
  const sel = c.querySelector('select[aria-label="Simulated guests"]');
  P.actSync(() => { sel.value = '15'; sel.dispatchEvent(new dom.window.Event('change', { bubbles: true })); });
  await click(buttonByText(c, /Run the night/));
  const sims = () => world.requests.filter((r) => r.url.startsWith('/api/jukebox/simulate'));
  ok(JSON.stringify(sims().at(-1)?.body) === JSON.stringify({ nights: 20, guests: 15, seed: 1, program: 'saved' }),
    `Run the night POSTs the party size and the saved program (${JSON.stringify(sims().at(-1)?.body)})`);
  ok(!!$(c, '[data-testid="jukebox-sim-now"]') && !!c.querySelector('[aria-label="Pause"]'), 'the night plays back at once');
  await click(c.querySelector('[aria-label="Pause"]'));
  const range = c.querySelector('input[aria-label="Party time"]');
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set;
  P.actSync(() => { setter.call(range, '130'); range.dispatchEvent(new dom.window.Event('input', { bubbles: true })); });
  await P.settle();
  ok(text($(c, '[data-testid="jukebox-sim-clock"]')).startsWith('2:10'), 'the scrubber moves the clock');
  ok(c.querySelectorAll('.jukebox-sim-guest').length === SIM.night.guests.length, 'every guest has a chip');
  ok(c.querySelectorAll('[data-testid="jukebox-sim-events"] .jukebox-item').length === 8, 'the latest eight happenings show');
  const rows = c.querySelectorAll('.jukebox-sim-tr:not(.head)');
  ok(rows.length === SIM.rows.length && c.querySelector('.jukebox-sim-table.one'), 'the averages table: one column when the settings are the tuned ones');
  ok(!!$(c, '[data-testid="jukebox-sim-hint"]'), 'a missed promise on a mix that is not the plan\'s names the preset');
  await click(buttonByText(c, /Another night/));
  ok(sims().at(-1)?.body?.seed === 2, 'Another night is the next seed');
  await click(buttonByText(c, /preset for this size/));
  await click(buttonByText(c, /Run the night/));
  ok(sims().at(-1)?.body?.program === 'preset', 'the preset switch asks for the plan\'s mix');
  ok(writes().every((r) => r.url.startsWith('/api/jukebox/simulate')), 'the Simulate tab never writes a setting or starts anything');
  P.unmount();
}

console.log('\n§2d the Guests tab, mounted — the rules, the line, the phones');
{
  world = newWorld('running');
  const c = P.mount();
  await P.settle();
  await click(buttonByText(c, /^Guests$/));
  await P.settle();
  const rows = [...c.querySelectorAll('[data-testid="jukebox-guest-line"] .jukebox-next .jukebox-item')];
  ok(rows.length === 3 && rows[1].textContent.includes('added by Disco Ana') && rows[1].textContent.includes('1st song'),
    'the line shows each song with who added it and their round');
  ok(rows[2].textContent.includes('sits out a time-out'), 'a song whose guest is in a time-out says so');
  // the host's draggable line (§7): a waiting song drags to a new place; the
  // song already sent to Spotify has no handle — nothing passes it
  ok(!rows[0].querySelector('.light-show-step-handle') && !!rows[1].querySelector('.light-show-step-handle')
    && !!rows[2].querySelector('.light-show-step-handle'), 'only the waiting songs carry a ⠿ handle');
  const rectAt = (i) => ({ x: 0, y: i * 60, left: 0, top: i * 60, right: 400, bottom: i * 60 + 50, width: 400, height: 50, toJSON() {} });
  rows.slice(1).forEach((li, i) => { li.getBoundingClientRect = () => rectAt(i); });
  const pev = (type, y) => {
    const ev = new dom.window.MouseEvent(type, { bubbles: true, cancelable: true, clientX: 200, clientY: y, button: 0 });
    Object.defineProperty(ev, 'pointerId', { value: 3 });
    Object.defineProperty(ev, 'isPrimary', { value: true });
    Object.defineProperty(ev, 'pointerType', { value: 'touch' });
    return ev;
  };
  P.actSync(() => rows[2].querySelector('.light-show-step-handle').dispatchEvent(pev('pointerdown', 85)));
  for (const y of [80, 70, 45, 20, 10]) P.actSync(() => document.dispatchEvent(pev('pointermove', y)));
  P.actSync(() => document.dispatchEvent(pev('pointerup', 10)));
  await P.settle();
  const dragMove = world.requests.filter((r) => r.url === '/api/jukebox/line/e3/move').at(-1);
  ok(dragMove?.method === 'POST' && JSON.stringify(dragMove.body) === '{"to":0}',
    `dragging the 2nd waiting song to the top moves it to place 0 among the waiting (${JSON.stringify(dragMove?.body)})`);
  world.requests = [];
  ok(!buttonByText(rows[1], /^Play next$/) && !!buttonByText(rows[2], /^Play next$/), 'Play next on a waiting song behind the first');
  await click(buttonByText(rows[2], /^Play next$/));
  const mv = world.requests.filter((r) => r.url === '/api/jukebox/line/e3/move').at(-1);
  ok(mv?.method === 'POST' && JSON.stringify(mv.body) === '{"to":0}', 'Play next POSTs {to: 0} for that song');
  ok(!rows[0].textContent.includes('Hold') && rows[1].textContent.includes('Hold'), 'only a waiting song can be held');
  await click(buttonByText(rows[1], /^Hold$/));
  const holdReq = world.requests.filter((r) => r.url === '/api/jukebox/line/e2/hold').at(-1);
  ok(holdReq?.method === 'POST' && holdReq.body.held === true, 'Hold POSTs exactly {held: true} for that song');
  await click(buttonByText(rows[0], /^Remove$/));
  ok(world.requests.some((r) => r.method === 'DELETE' && r.url === '/api/jukebox/line/e1'), 'Remove DELETEs that song');
  // the skip lock (PR 3.2): the song playing has its own row; any waiting song too
  const nowRow = c.querySelector('[data-testid="jukebox-now-skip"]');
  ok(!!nowRow && text(nowRow).includes('Now: Dancing Queen') && text(nowRow).includes('can be skipped'),
    'the song playing has its own row above the line, saying it can be skipped');
  await click(buttonByText(nowRow, /^Keep from skips$/));
  const lockReq = world.requests.filter((r) => r.url === '/api/jukebox/skip-lock').at(-1);
  ok(lockReq?.method === 'POST' && JSON.stringify(lockReq.body) === JSON.stringify({ uri: SET[1].uri, locked: true }),
    `Keep from skips POSTs exactly {uri, locked: true} for the song playing (${JSON.stringify(lockReq?.body)})`);
  await P.settle();
  const nowRow2 = c.querySelector('[data-testid="jukebox-now-skip"]');
  ok(text(nowRow2).includes('kept from skips') && !!buttonByText(nowRow2, /^Let it be skipped$/),
    'once the night reports it, the row says it is kept from skips');
  const rowsL = [...c.querySelectorAll('[data-testid="jukebox-guest-line"] .jukebox-next .jukebox-item')];
  await click(buttonByText(rowsL[2], /^Keep from skips$/));
  ok(JSON.stringify(world.requests.filter((r) => r.url === '/api/jukebox/skip-lock').at(-1)?.body)
    === JSON.stringify({ uri: 'spotify:track:m', locked: true }), 'a waiting song can be kept from skips too');
  const phones = [...c.querySelectorAll('[data-testid="jukebox-phone"]')];
  ok(phones.length === 4 && text(phones[1]).includes('waiting for your approval'), 'every phone, with how it stands');
  ok(text(phones[3]).includes('in a time-out (3 songs to go)'), 'a phone in a time-out, with the songs left');
  await click(buttonByText(phones[3], /^Pardon$/));
  const pard = world.requests.filter((r) => r.url === '/api/jukebox/guests/pd').at(-1);
  ok(pard?.method === 'POST' && JSON.stringify(pard.body) === '{"pardon":true}', 'Pardon POSTs {pardon: true} for that phone');
  await P.settle();
  ok(!buttonByText([...c.querySelectorAll('[data-testid="jukebox-phone"]')][3], /^Pardon$/), 'the pardoned phone loses its Pardon button');
  const fp = c.querySelector('[data-testid="jukebox-free-play"]');
  ok(!!fp && !!fp.querySelector('input[aria-label="Skip by vote: at least"]')
    && !c.querySelector('[data-testid="jukebox-guest-rules"] input[aria-label="Skip by vote: at least"]'),
    'the free-play rules have their own card');
  ok(!!c.querySelector('[data-testid="jukebox-free-play-off"]'), 'on credits, the Free play card says its rules wait for free play');
  // the host's gifts (phase 3): Everyone +2, and Give… on a phone at the party
  const phonesCard = c.querySelector('[data-testid="jukebox-phones"]');
  await click(buttonByText(phonesCard, /^Everyone \+2$/));
  const g1 = world.requests.filter((r) => r.url === '/api/jukebox/gift').at(-1);
  ok(g1?.method === 'POST' && JSON.stringify(g1.body) === '{"to":"everyone","amount":2}', 'Everyone +2 POSTs a gift of 2 to everyone');
  const rowsP = [...c.querySelectorAll('[data-testid="jukebox-phone"]')];
  ok(!!buttonByText(rowsP[0], /^Give…$/) && !buttonByText(rowsP[1], /^Give…$/) && !buttonByText(rowsP[2], /^Give…$/),
    'Give… only on a phone at the party (joined, approved, not blocked)');
  await click(buttonByText(rowsP[0], /^Give…$/));
  const amt = rowsP[0].querySelector('input[aria-label="Credits to give Disco Ana"]');
  const numSet = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set;
  P.actSync(() => { numSet.call(amt, '5'); amt.dispatchEvent(new dom.window.Event('input', { bubbles: true })); });
  await click(buttonByText(rowsP[0], /^Give$/));
  const g2 = world.requests.filter((r) => r.url === '/api/jukebox/gift').at(-1);
  ok(JSON.stringify(g2?.body) === '{"to":"pa","amount":5}', `Give… POSTs that phone and amount (${JSON.stringify(g2?.body)})`);
  await click(buttonByText(phones[1], /^Approve$/));
  const appr = world.requests.filter((r) => r.url === '/api/jukebox/guests/pb').at(-1);
  ok(appr?.method === 'POST' && JSON.stringify(appr.body) === '{"approved":true}', 'Approve POSTs {approved: true} for that phone');
  await P.settle();
  ok(!buttonByText([...c.querySelectorAll('[data-testid="jukebox-phone"]')][1], /^Approve$/), 'the approved phone loses its Approve button');
  world.phones = world.phones.map((p) => (p.id === 'pa' ? { ...p, credits: 6 } : p));
  await click(buttonByText(phones[0], /^Lock name$/));
  ok(JSON.stringify(world.requests.filter((r) => r.url === '/api/jukebox/guests/pa').at(-1)?.body) === '{"name_locked":true}',
    'Lock name POSTs {name_locked: true}');
  // zero and merge (§4, §12): Zero asks once; Merge… picks the phone that joins
  await P.settle();
  const rowsZ = [...c.querySelectorAll('[data-testid="jukebox-phone"]')];
  ok(rowsZ.every((r) => /^since \d\d:\d\d$/.test(text(r.querySelector('[data-testid="jukebox-phone-since"]')))),
    'every phone says when it first opened the page');
  ok(!!buttonByText(rowsZ[0], /^Zero$/) && !buttonByText(rowsZ[3], /^Zero$/) && !buttonByText(rowsZ[2], /^Merge…$/),
    'Zero only on a phone holding credits; neither on a blocked one');
  await click(buttonByText(rowsZ[0], /^Zero$/));
  ok(!world.requests.some((r) => r.url === '/api/jukebox/guests/pa/zero') && !!buttonByText(rowsZ[0], /^Keep$/),
    'Zero asks once before taking anything back');
  await click(buttonByText(rowsZ[0], /^Take 6 back$/));
  ok(world.requests.filter((r) => r.url === '/api/jukebox/guests/pa/zero').at(-1)?.method === 'POST',
    'Take 6 back POSTs that phone\'s zero');
  await P.settle();
  ok(!buttonByText([...c.querySelectorAll('[data-testid="jukebox-phone"]')][0], /^Zero$/), 'a zeroed phone loses its Zero button');
  const rowA = [...c.querySelectorAll('[data-testid="jukebox-phone"]')][0];
  await click(buttonByText(rowA, /^Merge…$/));
  const pick = rowA.querySelector('select[aria-label="The phone that joins Disco Ana"]');
  ok(!!pick && [...pick.options].map((o) => o.value).join(',') === ',pb,pd', 'the picker offers every other phone not blocked');
  ok(buttonByText(rowA, /^Merge$/).disabled, 'nothing merges until a phone is picked');
  const selSet = Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype, 'value').set;
  P.actSync(() => { selSet.call(pick, 'pd'); pick.dispatchEvent(new dom.window.Event('change', { bubbles: true })); });
  ok(text(rowA.querySelector('[data-testid="jukebox-merge-words"]')).startsWith('Lucky Otter becomes part of Disco Ana'),
    'it says what the merge will do before he confirms');
  await click(buttonByText(rowA, /^Merge$/));
  const mr = world.requests.filter((r) => r.url === '/api/jukebox/guests/pa/merge').at(-1);
  ok(mr?.method === 'POST' && JSON.stringify(mr.body) === '{"retire":"pd"}', `Merge POSTs the phone that joins (${JSON.stringify(mr?.body)})`);
  await P.settle();
  const after = [...c.querySelectorAll('[data-testid="jukebox-phone"]')];
  ok(after.length === 3 && text(after[0]).includes('merged with Lucky Otter'), 'one guest now: the merged phone leaves the list, the kept one names it');
  const puts2 = () => world.requests.filter((r) => r.method === 'PUT' && r.url.startsWith('/api/jukebox/show'));
  const lc = c.querySelector('input[aria-label="Requests close before the end (last call)"]');
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set;
  P.actSync(() => { setter.call(lc, '90'); lc.dispatchEvent(new dom.window.Event('input', { bubbles: true })); });
  P.actSync(() => lc.dispatchEvent(new dom.window.FocusEvent('focusout', { bubbles: true })));
  await P.settle();
  ok(puts2().length === 0, 'a last call past its range is refused on the page — nothing is sent');
  P.actSync(() => { setter.call(lc, '30'); lc.dispatchEvent(new dom.window.Event('input', { bubbles: true })); });
  P.actSync(() => lc.dispatchEvent(new dom.window.FocusEvent('focusout', { bubbles: true })));
  await P.settle();
  ok(JSON.stringify(puts2().at(-1)?.body) === '{"last_call_min":30}', `a guest rule PUTs exactly that rule (${JSON.stringify(puts2().at(-1)?.body)})`);
  ok(!c.querySelector('[data-testid="rule-explicit_after"]'), 'the explicit-after time hides unless explicit is "after"');
  // the board (phase 3): its switches, a preview of what guests see, the TV page
  const bc = c.querySelector('[data-testid="jukebox-board-card"]');
  const boardBoxes = [...bc.querySelectorAll('input[type="checkbox"]')].map((i) => [i.getAttribute('aria-label'), i.checked]);
  ok(boardBoxes.length === 5 && boardBoxes[0][1] === true && boardBoxes.slice(1).every(([, on]) => !on),
    `the Board card: show the board on, the people boards and the TV off (${JSON.stringify(boardBoxes)})`);
  ok(!c.querySelector('[data-testid="jukebox-guest-rules"] input[aria-label="On the TV"]'), 'the board switches have their own card');
  const songsShown = [...bc.querySelectorAll('[data-testid="jukebox-board-songs"] li')].map((li) => li.textContent);
  ok(songsShown.length === 2 && songsShown[0].includes('Dopamine') && songsShown[0].includes('added by Disco Ana · ▲ 3')
    && songsShown[1].includes("the host's set"), 'the card previews tonight\'s top songs with who added each');
  ok(text(bc.querySelector('[data-testid="jukebox-board-pickers"]')).includes("(guests don't see this)"),
    'a people board guests don\'t see is marked so on the host\'s card');
  P.actSync(() => bc.querySelector('input[aria-label="People board: top voters"]').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
  await P.settle();
  const showPut = world.requests.filter((r) => r.method === 'PUT' && r.url.startsWith('/api/jukebox/show')).at(-1);
  ok(JSON.stringify(showPut?.body) === '{"board_top_voters":true}', `a people board switch PUTs exactly that switch (${JSON.stringify(showPut?.body)})`);
  ok(!!buttonByText(bc, /^Open the TV page$/), 'the card opens the TV page');
  P.unmount();
}

console.log('\n§2e the TV page (/jukebox/tv), mounted — nothing until "On the TV", then the board');
{
  const TV = await bundle(`
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import JukeboxTvPage from ${JSON.stringify(join(web, 'src/jukebox/JukeboxTvPage.tsx'))};
let root = null;
const container = document.createElement('div');
document.body.appendChild(container);
export function mount() {
  if (root) act(() => { root.unmount(); });
  root = createRoot(container);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => { root.render(React.createElement(QueryClientProvider, { client: qc }, React.createElement(JukeboxTvPage))); });
  return container;
}
export async function settle(ms = 30) {
  for (let i = 0; i < 6; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
}
export function unmount() { if (root) act(() => { root.unmount(); }); root = null; }
`, 'tv');
  world = newWorld('running');
  let c = TV.mount();
  await TV.settle();
  ok(!!c.querySelector('[data-testid="jukebox-tv-off"]') && !c.querySelector('[data-testid="jukebox-tv-now"]'),
    'with "On the TV" off the TV page shows nothing of the night, and says how to turn it on');
  ok(document.body.classList.contains('jukebox-tv-body') && !c.querySelector('nav'), 'full screen: none of SPECTRA\'s bars');
  world.show = { ...world.show, board_on_tv: true, board_top_voters: true };
  c = TV.mount();
  await TV.settle();
  const now = c.querySelector('[data-testid="jukebox-tv-now"]');
  ok(!!now && text(now).includes('Ready to Run') && text(now).includes('▲ 4') && text(now).includes('▼ 1'),
    'on: the song playing with its live ▲▼');
  ok(c.querySelectorAll('[data-testid="jukebox-board-songs"] li').length === 2, 'on: tonight\'s top songs');
  ok(!!c.querySelector('[data-testid="jukebox-board-voters"]') && !c.querySelector('[data-testid="jukebox-board-pickers"]'),
    'the TV shows only the people boards guests see (top voters on, top pickers off)');
  ok(!text(c).includes("guests don't see this"), 'the TV never carries the host\'s own notes');
  TV.unmount();
}

// ── 3. help ───────────────────────────────────────────────────────────────
console.log('\n§3 help — every topic is real and reachable from the page');
{
  const topics = ['jukebox', 'jukebox-set-list', 'jukebox-slots', 'jukebox-live', 'jukebox-sign-in',
    'jukebox-credits', 'jukebox-presets', 'jukebox-price-check', 'jukebox-simulator', 'sonic-jukebox',
    'jukebox-report', 'jukebox-guest-page', 'jukebox-guests', 'jukebox-free-play', 'jukebox-credits-mode',
    'jukebox-skip-lock', 'jukebox-board', 'jukebox-gifts', 'jukebox-bonus-cards', 'jukebox-cards',
    'jukebox-merge-phones', 'jukebox-economy'];
  const { HELP_SECTIONS } = loadData(join(web, 'src/help/helpContent.ts'), 'help');
  const knownIds = new Set();
  for (const section of HELP_SECTIONS) {
    knownIds.add(section.id);
    for (const e of section.entries ?? []) knownIds.add(e.id);
    for (const sub of section.subsections ?? []) {
      knownIds.add(sub.id);
      for (const e of sub.entries ?? []) knownIds.add(e.id);
    }
  }
  for (const id of topics) ok(knownIds.has(id), `"${id}" is a real section/entry in HELP_SECTIONS`);
  const { topicForPath } = loadData(join(web, 'src/help/routeTopics.ts'), 'routes');
  ok(topicForPath('/jukebox') === 'jukebox', 'the menu row\'s "?" opens jukebox on /jukebox');
  const { NAV_GROUPS, activeGroupId, ALL_NAV_ROUTES } = loadData(join(web, 'src/nav/navGroups.ts'), 'nav');
  const item = NAV_GROUPS.find((g) => g.id === 'engine')?.items?.find((it) => it.to === '/jukebox');
  ok(!!item && item.icon === 'note' && activeGroupId('/jukebox') === 'engine' && ALL_NAV_ROUTES.includes('/jukebox'),
    '/jukebox is in the Engine menu');

  const reached = new Set();
  const hoverAll = (c) => {
    for (const tip of [...c.querySelectorAll('.info-tip')]) {
      P.actSync(() => tip.dispatchEvent(new dom.window.MouseEvent('mouseover', { bubbles: true, cancelable: true })));
    }
    for (const a of [...document.querySelectorAll('.info-tip-panel a.help-link')]) {
      const id = new URLSearchParams((a.getAttribute('href') || '').split('?')[1] || '').get('topic');
      if (id) reached.add(id);
    }
  };
  world = newWorld('running');
  const c = P.mount();
  await P.settle();
  hoverAll(c);
  await click(buttonByText(c, /^Live$/));
  hoverAll(c);
  await click(buttonByText(c, /^Guests$/));
  await P.settle();
  hoverAll(c);
  await click(buttonByText(c, /^Credits$/));
  await P.settle();
  hoverAll(c);
  await click(buttonByText(c, /^Simulate$/));
  await click(buttonByText(c, /Run the night/));
  hoverAll(c);
  await click(c.querySelector('.sonic-popover-fab'));
  // the panel's title link is the page's scope; its shared "↺ Undo last"
  // button carries the chat's own sonic-scene-backups link on every page
  for (const a of [...c.querySelectorAll('.sonic-popover-panel a.help-link')]) {
    const id = new URLSearchParams((a.getAttribute('href') || '').split('?')[1] || '').get('topic');
    if (id && id !== 'sonic-scene-backups') reached.add(id);
  }
  ok(topics.every((id) => reached.has(id)) && reached.size === topics.length,
    `the page's own controls and its 💬 Sonic open exactly the twenty-two jukebox topics (${[...reached].sort().join(', ')})`);
  P.unmount();
}

report();
