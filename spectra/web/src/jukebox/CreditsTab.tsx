/** THE JUKEBOX'S CREDITS TAB (phase 3 PR 3.3's settings half; the plan's §4
 * "Show settings" and §3.5 presets): the guest page's MODE (credits or free
 * play, PR 3.2 — report §6's "one switch"), the party-size presets, the price check
 * (the current rules on real examples, at a room size he picks) and every
 * economy setting, grouped as §4's cards.
 *
 * The SHOW card names the show and keeps his saved shows (§4: "a 'show' is
 * a saved set of these" — the show, the program and the guest link,
 * SpotFX's services/jukebox/shows.py): save what is in force now under a
 * name, load one back whole, delete one. Loading asks first.
 *
 * Each setting saves on its own (Enter or leaving the field) through
 * SpotFX's one validator (services/jukebox/show.py) — an out-of-range value
 * is refused by name and nothing changes. The cards, labels and ranges are
 * the server's; the words are jukeboxCredits.ts. */
import { useState } from 'react';
import InfoTip from '../components/InfoTip';
import { useToast } from '../components/Toast';
import { checkValue, groupFields, presetTitle, priceRows, rangeLine } from './jukeboxCredits';
import { GUEST_COUNTS } from './jukeboxEditor';
import {
  useApplyPreset, useBonusCodes, useDeleteShow, useJukeboxShow, useLoadShow, useMintBonus, usePriceCheck,
  useSavedShows, useSaveNamedShow, useSaveShow, useVoidBonus,
} from './queries';
import type { EconomyField, ShowConfig } from './types';

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function CreditsTab() {
  const toast = useToast();
  const showQ = useJukeboxShow();
  const [guests, setGuests] = useState<number>(15);
  const pcQ = usePriceCheck(guests);
  const save = useSaveShow();
  const preset = useApplyPreset();
  const data = showQ.data;
  if (!data) {
    return <div className="card jukebox-card">{showQ.isError ? 'The show settings couldn\'t be read from SpotFX.' : 'Reading the show settings…'}</div>;
  }
  const { show, fields, presets } = data;
  const onError = (e: unknown) => toast(errText(e), 'error');

  const mode = show.play_mode ?? 'credits';
  return (
    <div className="jukebox-grid">
      <ShowCard show={show} />

      <section className="card jukebox-card" data-testid="jukebox-mode">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-credits-mode"
            text="Credits: guests earn credits by voting and spend them to add, move and skip songs, with tips and the Shop. Free play: nothing costs anything, and counts keep it fair. Switch at any time — it applies from the next thing a guest does.">
            <span className="card-title jukebox-card-title">Mode</span>
          </InfoTip>
        </div>
        <div className="jukebox-modes" role="radiogroup" aria-label="The guest page's mode">
          {(data.play_modes ?? [{ value: 'free', label: 'Free play' }, { value: 'credits', label: 'Credits' }]).map((m) => (
            <button key={m.value} role="radio" aria-checked={mode === m.value}
              className={mode === m.value ? 'on' : ''}
              onClick={() => mode !== m.value && save.mutate({ play_mode: m.value as 'free' | 'credits' }, {
                onSuccess: () => toast(`The guest page is on ${m.label.toLowerCase()}`, 'success'), onError,
              })}>{m.label}</button>
          ))}
        </div>
        <p className="jukebox-muted">
          {mode === 'credits'
            ? 'Guests see prices, the Shop and their credits; skips and moves are paid, a jailed guest breaks out for credits.'
            : 'Nothing costs anything: the room votes songs off, moves are counted, and jail is a time-out.'}
        </p>
      </section>

      <section className="card jukebox-card" data-testid="jukebox-presets">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-presets"
            text="One set of prices works from 4 to 30 guests; what changes with the crowd is how many slots the jukebox gets. A preset sets the program (and, for Large, approval for new phones). Anything can be changed after.">
            <span className="card-title jukebox-card-title">Party size</span>
          </InfoTip>
        </div>
        <div className="jukebox-presets">
          {presets.map((p) => (
            <button key={p.name} aria-pressed={show.preset === p.name}
              className={`jukebox-preset${show.preset === p.name ? ' on' : ''}`}
              onClick={() => preset.mutate(p.name, {
                onSuccess: () => toast(`${presetTitle(p)}: program set`, 'success'), onError,
              })}>
              <span className="jukebox-preset-name">{presetTitle(p)}</span>
              <span className="jukebox-muted">{p.why}</span>
            </button>
          ))}
        </div>
        <label className="jukebox-check">
          <input type="checkbox" checked={show.approve_new_phones}
            onChange={(e) => save.mutate({ approve_new_phones: e.target.checked }, { onError })} />
          New phones need my approval
        </label>
      </section>

      <section className="card jukebox-card" data-testid="jukebox-price-check">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-price-check"
            text="What each thing costs under the settings below, right now — the same rules a guest's page will charge — at the room size you pick.">
            <span className="card-title jukebox-card-title">Price check</span>
          </InfoTip>
          <label className="jukebox-guests">
            <span>a room of</span>
            <select aria-label="Price check guests" value={guests} onChange={(e) => setGuests(Number(e.target.value))}>
              {GUEST_COUNTS.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </label>
        </div>
        {pcQ.data ? (
          <div className="jukebox-prices">
            {priceRows(pcQ.data).map((g) => (
              <div key={g.title} className="jukebox-price-group">
                <div className="jukebox-price-title">{g.title}</div>
                {g.rows.map((r) => (
                  <div key={r.label} className="jukebox-price-row">
                    <span>{r.label}</span><span className="jukebox-price-value">{r.value}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : <p className="jukebox-muted">Working the prices…</p>}
      </section>

      <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-settings">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-credits"
            text="Every credits setting, with its range. Each one saves on its own; a value outside its range is refused and nothing changes. Credits are free and worth nothing outside the night.">
            <span className="card-title jukebox-card-title">Credits settings</span>
          </InfoTip>
          <span className="jukebox-muted">Enter or leave a field to save it</span>
        </div>
        <div className="jukebox-settings">
          {groupFields(fields).map((c) => (
            <div key={c.card} className="jukebox-settings-card">
              <div className="jukebox-price-title">{c.card}</div>
              {c.fields.map((f) => (
                <FieldRow key={f.key} f={f} value={show.economy[f.key]}
                  onSave={(v) => save.mutate({ economy: { [f.key]: v } }, { onError })}
                  onBad={(reason) => toast(reason, 'error')} />
              ))}
            </div>
          ))}
        </div>
      </section>

      <BonusCards amount={show.economy.qr_bonus as number} />
    </div>
  );
}

const MINT_MAX = 200;   // SpotFX bonus_codes.MINT_MAX

/** THE PRINTED BONUS CARDS (report §1 rule 1, §9's N2): one-time codes, each
 * good for the QR bonus once, ever, and one per phone a night. Made here in
 * batches; printed on the cards (with the join QR); a lost card's code can
 * be voided while it is unused. */
function BonusCards({ amount }: { amount: number }) {
  const toast = useToast();
  const q = useBonusCodes();
  const mint = useMintBonus();
  const voidCode = useVoidBonus();
  const [count, setCount] = useState('10');
  const [batch, setBatch] = useState('');
  const n = Number(count);
  const ok = Number.isInteger(n) && n >= 1 && n <= MINT_MAX;
  const data = q.data;
  return (
    <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-bonus-cards">
      <div className="jukebox-card-head">
        <InfoTip topic="jukebox-bonus-cards"
          text="One-time codes for the printed bonus cards: each is good for the QR bonus once, ever, and a phone can use one a night. Credits mode only.">
          <span className="card-title jukebox-card-title">Bonus cards</span>
        </InfoTip>
        <span className="jukebox-muted">
          {data ? `${data.unused} unused · ${data.used} used · +${amount} credits each` : q.isError ? "The codes couldn't be read." : 'Reading the codes…'}
        </span>
        <InfoTip topic="jukebox-cards" text="The printable guest card: the Wi-Fi QR (typed at print time, never stored), the Jukebox QR and a bonus code on each card.">
          <button type="button" onClick={() => window.open('/spectra/jukebox/cards', 'jukebox-cards')}>Print the cards</button>
        </InfoTip>
      </div>
      <div className="jukebox-bonus-make">
        <label className="jukebox-field">
          <span className="jukebox-field-label">Make</span>
          <input type="number" min={1} max={MINT_MAX} value={count} aria-label="How many codes to make"
            onChange={(e) => setCount(e.target.value)} />
          <span className="jukebox-muted">codes (1-{MINT_MAX})</span>
        </label>
        <label className="jukebox-field">
          <span className="jukebox-field-label">Label</span>
          <input value={batch} maxLength={40} placeholder="e.g. Saturday party" aria-label="A label for this batch"
            onChange={(e) => setBatch(e.target.value)} />
        </label>
        <button type="button" disabled={!ok || mint.isPending}
          onClick={() => mint.mutate({ count: n, batch }, {
            onSuccess: (r) => toast(`Made ${r.made?.length ?? n} codes`, 'success'),
            onError: (e) => toast(errText(e), 'error'),
          })}>Make codes</button>
      </div>
      {data && data.codes.length > 0 && (
        <ul className="jukebox-bonus-codes" data-testid="jukebox-bonus-codes">
          {data.codes.map((c) => (
            <li key={c.code} className={c.used ? 'used' : ''}>
              <code>{c.code}</code>
              <span className="jukebox-muted">{c.used ? `used by ${c.used_name || 'a guest'}` : c.batch}</span>
              {!c.used && (
                <button type="button" aria-label={`Void ${c.code}`}
                  onClick={() => voidCode.mutate(c.code, { onError: (e) => toast(errText(e), 'error') })}>Void</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FieldRow({ f, value, onSave, onBad }: {
  f: EconomyField; value: number | boolean | undefined;
  onSave: (v: number | boolean) => void; onBad: (reason: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  if (f.kind === 'bool') {
    return (
      <label className="jukebox-field jukebox-check" data-testid={`setting-${f.key}`}>
        <input type="checkbox" checked={!!value} aria-label={f.label}
          onChange={(e) => onSave(e.target.checked)} />
        {f.label}
      </label>
    );
  }
  const commit = () => {
    if (draft == null) return;
    const c = checkValue(f, draft);
    setDraft(null);
    if (!c.ok) {
      onBad(c.reason);
      return;
    }
    if (c.value !== value) onSave(c.value);
  };
  return (
    <label className="jukebox-field" data-testid={`setting-${f.key}`}>
      <span className="jukebox-field-label">{f.label}</span>
      <input type="number" step={f.kind === 'int' ? 1 : 'any'} aria-label={f.label}
        value={draft ?? String(value ?? '')}
        onChange={(e) => setDraft(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
      <span className="jukebox-muted jukebox-field-range">{rangeLine(f)}</span>
    </label>
  );
}


// ── the show: its name and his saved shows (§4) ────────────────────────────

function savedWhen(ms: number): string {
  if (!ms) return '';
  const d = new Date(ms);
  return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}, `
    + `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function ShowCard({ show }: { show: ShowConfig }) {
  const toast = useToast();
  const q = useSavedShows();
  const saveAs = useSaveNamedShow();
  const load = useLoadShow();
  const del = useDeleteShow();
  const [name, setName] = useState<string | null>(null);
  const onError = (e: unknown) => toast(errText(e), 'error');
  const current = name ?? show.name ?? 'Saturday party';
  const rows = q.data?.shows ?? [];
  const taken = rows.find((r) => r.name.toLocaleLowerCase() === current.trim().toLocaleLowerCase());
  const save = () => {
    const n = current.trim();
    if (!n) return;
    if (taken && !window.confirm(`Replace the saved show “${taken.name}” with what is set now?`)) return;
    saveAs.mutate(n, {
      onSuccess: (r) => { setName(null); toast(`${r.replaced ? 'Replaced' : 'Saved'} “${r.name}”`, 'success'); },
      onError,
    });
  };
  return (
    <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-show-card">
      <div className="jukebox-card-head">
        <InfoTip topic="jukebox-shows"
          text="A show is every setting on these tabs — the set playlist and slots, the guests' rules, the credits, the board and the guest link — saved under a name and loaded back whole before a party.">
          <span className="card-title jukebox-card-title">The show</span>
        </InfoTip>
      </div>
      <div className="jukebox-show-row">
        <label className="jukebox-field jukebox-rule-wide">
          <span className="jukebox-field-label">Name</span>
          <input type="text" value={current} maxLength={60} aria-label="The show's name"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save(); }} />
        </label>
        <button type="button" disabled={!current.trim() || saveAs.isPending} onClick={save}>
          {taken ? 'Save (replace)' : 'Save this show'}
        </button>
      </div>
      {q.data?.error && <p className="jukebox-error">{q.data.error}</p>}
      {rows.length === 0 ? (
        <p className="jukebox-muted">No saved shows yet. Set everything up, name it and save it.</p>
      ) : (
        <ul className="jukebox-saved-shows" data-testid="jukebox-saved-shows">
          {rows.map((r) => (
            <li key={r.name} className="jukebox-item">
              <span className="jukebox-item-words">
                <span className="jukebox-song-title">{r.name}{r.name === show.name ? ' · in force' : ''}</span>
                <span className="jukebox-song-artist">
                  {[r.play_mode === 'credits' ? 'credits' : 'free play', r.preset ? `${r.preset} preset` : '',
                    r.guest_link ? 'guest link on' : 'guest link off', `saved ${savedWhen(r.saved_ms)}`]
                    .filter(Boolean).join(' · ')}
                </span>
              </span>
              <span className="jukebox-guest-actions">
                <button type="button" onClick={() => {
                  if (!window.confirm(`Load “${r.name}”? Every setting on these tabs becomes that show's, and the guest link goes ${r.guest_link ? 'on' : 'off'}.`)) return;
                  load.mutate(r.name, { onSuccess: () => toast(`Loaded “${r.name}”`, 'success'), onError });
                }}>Load</button>
                <button type="button" onClick={() => {
                  if (!window.confirm(`Delete the saved show “${r.name}”?`)) return;
                  del.mutate(r.name, { onError });
                }}>Delete</button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
