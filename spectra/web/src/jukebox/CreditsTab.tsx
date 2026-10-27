/** THE JUKEBOX'S CREDITS TAB (phase 3 PR 3.3's settings half; the plan's §4
 * "Show settings" and §3.5 presets): the guest page's MODE (credits or free
 * play, PR 3.2 — report §6's "one switch"), the party-size presets, the price check
 * (the current rules on real examples, at a room size he picks) and every
 * economy setting, grouped as §4's cards.
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
import { useApplyPreset, useJukeboxShow, usePriceCheck, useSaveShow } from './queries';
import type { EconomyField } from './types';

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
    </div>
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
