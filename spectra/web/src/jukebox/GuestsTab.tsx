/** THE JUKEBOX'S GUESTS TAB (phase 2 PRs 2.2-2.3: the host's controls; the
 * plan's §4 Show/Guests/Free play cards and §12 guards): the guests' own
 * rules (when the night ends and requests close, explicit songs, how many
 * phones, name changes, the word filter), free play's rules (the room's
 * skip, bumps, play next, the jail), the line with Hold, Play next and
 * Remove on each song, and every phone at tonight's party with Approve,
 * Pardon, Block, Rename and Lock name. Every decision is SpotFX's
 * (services/jukebox/guests.py, one show validator); the words are
 * jukeboxGuests.ts. */
import { useState } from 'react';
import InfoTip from '../components/InfoTip';
import { useToast } from '../components/Toast';
import BoardLists from './BoardLists';
import {
  lineRows, mergeCandidates, mergeWords, phoneActions, phoneLine, phoneTakes, sinceWords,
  type PhoneAction,
} from './jukeboxGuests';
import {
  useGift, useGuests, useHoldEntry, useHostPhone, useJukeboxBoard, useJukeboxShow, useMergePhones,
  usePlayNext, useRemoveEntry, useSaveShow, useSkipLock, useZeroPhone,
} from './queries';
import type { GuestField, GuestPhone, JukeboxStatus, ShowConfig } from './types';

const FREE_PLAY = 'Free play';
const BOARD = 'Board';
const ACTION_WORDS: Record<PhoneAction, string> = {
  approve: 'Approve', pardon: 'Pardon', block: 'Block', unblock: 'Unblock', lock: 'Lock name',
  unlock: 'Unlock name', rename: 'Rename',
};

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function GuestsTab({ status }: { status: JukeboxStatus | undefined }) {
  const toast = useToast();
  const running = !!status?.running;
  const guestsQ = useGuests(running);
  const boardQ = useJukeboxBoard(false);
  const showQ = useJukeboxShow();
  const save = useSaveShow();
  const host = useHostPhone();
  const hold = useHoldEntry();
  const remove = useRemoveEntry();
  const playNext = usePlayNext();
  const skipLock = useSkipLock();
  const gift = useGift();
  const zero = useZeroPhone();
  const merge = useMergePhones();
  const giveTo = (to: string, amount: number, who: string) => gift.mutate({ to, amount }, {
    onSuccess: (r) => toast(`Gave ${who} ${amount} credit${amount === 1 ? '' : 's'}${
      to === 'everyone' && r.gift ? ` (${r.gift.phones} phone${r.gift.phones === 1 ? '' : 's'})` : ''}`, 'success'),
    onError,
  });
  const onError = (e: unknown) => toast(errText(e), 'error');
  const phones = guestsQ.data?.phones ?? [];
  const show = showQ.data?.show;
  const credits = show?.play_mode === 'credits';
  const noSkip = status?.no_skip ?? [];
  const rows = lineRows(status?.line ?? [], phones,
                        credits || (show?.free_play_next ?? 'host') === 'host', noSkip);
  const now = status?.running ? status.now : null;
  const nowLocked = !!now?.uri && noSkip.includes(now.uri);
  const allFields = showQ.data?.guest_fields ?? [];
  const fields = allFields.filter((f) => f.card !== FREE_PLAY && f.card !== BOARD);
  const freeFields = allFields.filter((f) => f.card === FREE_PLAY);
  const boardFields = allFields.filter((f) => f.card === BOARD);
  const board = boardQ.data?.board;
  const ruleRows = (list: GuestField[]) => show && list.map((f) => (
    <RuleRow key={f.key} f={f} show={show}
      onSave={(v) => save.mutate({ [f.key]: v }, { onError })}
      onBad={(reason) => toast(reason, 'error')} />
  ));

  return (
    <div className="jukebox-grid">
      <section className="card jukebox-card" data-testid="jukebox-guest-rules">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-guests"
            text="The guests' own rules: when tonight ends and requests close (last call), explicit songs, how many phones, name changes and the word filter. Each saves on its own; a value outside its range is refused.">
            <span className="card-title jukebox-card-title">Guest rules</span>
          </InfoTip>
        </div>
        {show ? <div className="jukebox-settings">{ruleRows(fields)}</div>
          : <p className="jukebox-muted">Reading the rules…</p>}
      </section>

      <section className="card jukebox-card" data-testid="jukebox-free-play">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-free-play"
            text="Nothing costs anything; counts keep it fair. The room skips a song with enough ▼ (and that share of the votes); each guest may move songs a few times an hour; a guest whose songs get too many ▼ sits out a few songs — you can pardon them on the phone's row.">
            <span className="card-title jukebox-card-title">Free play</span>
          </InfoTip>
          {guestsQ.data?.crowd ? (
            <span className="jukebox-muted">{`${guestsQ.data.crowd} phone${guestsQ.data.crowd === 1 ? '' : 's'} here in the last 15 min`}</span>
          ) : null}
        </div>
        {credits && (
          <p className="jukebox-muted" data-testid="jukebox-free-play-off">
            The guest page is on credits (the Credits tab&apos;s Mode card), so these rules wait for free play.
          </p>
        )}
        {show ? <div className="jukebox-settings">{ruleRows(freeFields)}</div>
          : <p className="jukebox-muted">Reading the rules…</p>}
      </section>

      <section className="card jukebox-card" data-testid="jukebox-board-card">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-board"
            text="The guests' Board tab: Tonight's top songs — songs, not people, ranked by ▲ with who added each. The people boards (top pickers, top voters, most generous) ship off: ranking people reads like a game, so they are your call.">
            <span className="card-title jukebox-card-title">Board</span>
          </InfoTip>
          <button type="button" onClick={() => window.open('/spectra/jukebox/tv', 'jukebox-tv')}
                  title="The board full screen, for your TV or the wall kiosk">Open the TV page</button>
        </div>
        {show ? <div className="jukebox-settings">{ruleRows(boardFields)}</div>
          : <p className="jukebox-muted">Reading the rules…</p>}
        {board ? <BoardLists board={board} people={board.people} />
          : <p className="jukebox-muted">{boardQ.data && !boardQ.data.running ? 'The board fills in during a night.' : 'Reading the board…'}</p>}
      </section>

      <section className="card jukebox-card" data-testid="jukebox-guest-line">
        <div className="jukebox-card-head">
          <span className="card-title jukebox-card-title">The line</span>
          <span className="jukebox-muted">{rows.length ? `${rows.length} waiting` : running ? 'empty — slots pass' : 'no night running'}</span>
        </div>
        {now && now.uri && (now.kind === 'set' || now.kind === 'jukebox') && (
          <div className="jukebox-item jukebox-now-row" data-testid="jukebox-now-skip">
            <span className="jukebox-item-words">
              <span className="jukebox-song-title">Now: {now.title || now.uri}</span>
              <span className="jukebox-song-artist">{nowLocked ? 'kept from skips' : 'can be skipped'}</span>
            </span>
            <span className="jukebox-guest-actions">
              <InfoTip topic="jukebox-skip-lock" text="Keep a song from every skip tonight — the room's vote and a paid skip alike.">
                <button onClick={() => skipLock.mutate({ uri: now.uri, locked: !nowLocked }, { onError })}>
                  {nowLocked ? 'Let it be skipped' : 'Keep from skips'}
                </button>
              </InfoTip>
            </span>
          </div>
        )}
        {rows.length > 0 && (
          <ol className="jukebox-next">
            {rows.map((r) => (
              <li key={r.entry.id} className={`jukebox-item ${r.sent ? 'jukebox' : 'set'}`}>
                <span className="jukebox-item-words">
                  <span className="jukebox-song-title">{r.entry.title || r.entry.uri}</span>
                  <span className="jukebox-song-artist">
                    {[r.entry.artist, `added by ${r.by}`, r.round, r.paid ? `paid 🎟 ${r.paid}` : '',
                      r.sent ? 'sent to Spotify' : '',
                      r.held ? 'on hold' : '', r.jailed ? 'sits out a time-out' : '',
                      r.skipLocked ? 'kept from skips' : '',
                      r.doomed ? 'removed: skipped as it starts' : ''].filter(Boolean).join(' · ')}
                  </span>
                </span>
                <span className="jukebox-guest-actions">
                  {r.canPlayNext && (
                    <button onClick={() => playNext.mutate(r.entry.id, { onError })}>Play next</button>
                  )}
                  <button onClick={() => skipLock.mutate({ uri: r.entry.uri, locked: !r.skipLocked }, { onError })}>
                    {r.skipLocked ? 'Allow skips' : 'Keep from skips'}
                  </button>
                  {r.canHold && (
                    <button onClick={() => hold.mutate({ id: r.entry.id, held: !r.held }, { onError })}>
                      {r.held ? 'Let go' : 'Hold'}
                    </button>
                  )}
                  {!r.doomed && (
                    <button onClick={() => remove.mutate(r.entry.id, { onError })}>Remove</button>
                  )}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-phones">
        <div className="jukebox-card-head">
          <span className="card-title jukebox-card-title">Phones</span>
          {running && credits && (
            <InfoTip topic="jukebox-gifts" text="A gift of credits to everyone at the party (joined, approved, not blocked). Gifts are gifts: nothing is asked in return.">
              <button type="button" onClick={() => giveTo('everyone', 2, 'everyone')}>Everyone +2</button>
            </InfoTip>
          )}
          <span className="jukebox-muted">
            {running ? `${phones.length} tonight${guestsQ.data?.pending ? ` · ${guestsQ.data.pending} waiting for you` : ''}${guestsQ.data?.jailed ? ` · ${guestsQ.data.jailed} in a time-out` : ''}` : 'no night running'}
          </span>
        </div>
        {phones.length > 0 ? (
          <ul className="jukebox-phones">
            {phones.map((p) => (
              <PhoneRow key={p.id} p={p} phones={phones} canGift={running && credits && p.joined && p.approved && !p.blocked}
                onSet={(patch) => host.mutate({ id: p.id, ...patch }, { onError })}
                onGift={(amount) => giveTo(p.id, amount, p.name)}
                onZero={() => zero.mutate(p.id, {
                  onSuccess: (r) => toast(`${r.zeroed?.name ?? p.name}: ${r.zeroed?.credits ?? 0} credits taken back`, 'success'),
                  onError,
                })}
                onMerge={(retire) => merge.mutate({ keep: p.id, retire }, {
                  onSuccess: (r) => toast(`One guest now: ${r.merged?.name ?? p.name}`, 'success'),
                  onError,
                })} />
            ))}
          </ul>
        ) : running && <p className="jukebox-muted">No phones yet: they join through tonight's party link.</p>}
      </section>
    </div>
  );
}

function RuleRow({ f, show, onSave, onBad }: {
  f: GuestField; show: ShowConfig; onSave: (v: string | number | boolean) => void;
  onBad: (reason: string) => void;
}) {
  const value = show[f.key];
  const [draft, setDraft] = useState<string | null>(null);
  if (f.key === 'explicit_after' && show.explicit !== 'after') return null;
  if (f.kind === 'bool') {
    return (
      <label className="jukebox-field jukebox-check" data-testid={`rule-${f.key}`}>
        <input type="checkbox" checked={!!value} aria-label={f.label} onChange={(e) => onSave(e.target.checked)} />
        {f.label}
      </label>
    );
  }
  if (f.kind === 'choice') {
    return (
      <label className="jukebox-field jukebox-rule-wide" data-testid={`rule-${f.key}`}>
        <span className="jukebox-field-label">{f.label}</span>
        <select aria-label={f.label} value={String(value ?? f.default)} onChange={(e) => onSave(e.target.value)}>
          {(f.choices ?? []).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </label>
    );
  }
  if (f.kind === 'time') {
    return (
      <label className="jukebox-field jukebox-rule-wide" data-testid={`rule-${f.key}`}>
        <span className="jukebox-field-label">{f.label}</span>
        <input type="time" aria-label={f.label} value={String(value ?? f.default)}
          onChange={(e) => { if (/^\d\d:\d\d$/.test(e.target.value)) onSave(e.target.value); }} />
        <span className="jukebox-muted jukebox-field-range">{f.unit}</span>
      </label>
    );
  }
  const commit = () => {
    if (draft == null) return;
    const t = draft.trim();
    setDraft(null);
    const v = Number(t);
    if (!/^\d+$/.test(t)) { onBad(`${f.label}: a whole number, please`); return; }
    if (f.min != null && v < f.min) { onBad(`${f.label}: at least ${f.min}`); return; }
    if (f.max != null && v > f.max) { onBad(`${f.label}: at most ${f.max}`); return; }
    if (v !== value) onSave(v);
  };
  return (
    <label className="jukebox-field" data-testid={`rule-${f.key}`}>
      <span className="jukebox-field-label">{f.label}</span>
      <input type="number" step={1} aria-label={f.label} value={draft ?? String(value ?? '')}
        onChange={(e) => setDraft(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
      <span className="jukebox-muted jukebox-field-range">{`${f.min ?? '…'}–${f.max ?? '…'} ${f.unit}`}</span>
    </label>
  );
}

const GIFT_MAX = 20;    // SpotFX guests.GIFT_MAX

function PhoneRow({ p, phones, onSet, canGift = false, onGift, onZero, onMerge }: {
  p: GuestPhone; phones: GuestPhone[];
  onSet: (patch: { approved?: boolean; blocked?: boolean; name_locked?: boolean; name?: string;
                   pardon?: boolean }) => void;
  canGift?: boolean; onGift?: (amount: number) => void;
  onZero?: () => void; onMerge?: (retire: string) => void;
}) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const [giving, setGiving] = useState<string | null>(null);
  const [zeroing, setZeroing] = useState(false);
  const [merging, setMerging] = useState<string | null>(null);
  const takes = phoneTakes(p, phones);
  const candidates = mergeCandidates(p, phones);
  const retiring = candidates.find((q) => q.id === merging) ?? null;
  const giveAmount = giving === null ? NaN : Number(giving);
  const giveOk = Number.isInteger(giveAmount) && giveAmount >= 1 && giveAmount <= GIFT_MAX;
  return (
    <li className={`jukebox-phone${p.blocked ? ' jukebox-phone-blocked' : ''}${p.jail_left ? ' jukebox-phone-jailed' : ''}`}
        data-testid="jukebox-phone">
      <span className="jukebox-item-words">
        {renaming === null ? (
          <span className="jukebox-song-title">{p.name}</span>
        ) : (
          <input aria-label={`New name for ${p.name}`} value={renaming} maxLength={20} autoFocus
            onChange={(e) => setRenaming(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { onSet({ name: renaming.trim() }); setRenaming(null); }
              if (e.key === 'Escape') setRenaming(null);
            }} />
        )}
        <span className="jukebox-song-artist">{phoneLine(p)}</span>
        <span className="jukebox-muted jukebox-phone-since" data-testid="jukebox-phone-since">
          {sinceWords(p.created_ms)}
        </span>
        {merging !== null && (
          <span className="jukebox-merge" data-testid="jukebox-merge">
            <label className="jukebox-merge-pick">
              <span>Merge into {p.name}:</span>
              <select aria-label={`The phone that joins ${p.name}`} value={merging}
                onChange={(e) => setMerging(e.target.value)}>
                <option value="">Pick a phone…</option>
                {candidates.map((q) => (
                  <option key={q.id} value={q.id}>{q.name} ({sinceWords(q.created_ms)})</option>
                ))}
              </select>
            </label>
            {retiring && <span className="jukebox-muted" data-testid="jukebox-merge-words">{mergeWords(p, retiring)}</span>}
            <span className="jukebox-guest-actions">
              <button disabled={!retiring} onClick={() => { if (retiring && onMerge) onMerge(retiring.id); setMerging(null); }}>
                Merge
              </button>
              <button onClick={() => setMerging(null)}>Cancel</button>
            </span>
          </span>
        )}
      </span>
      <span className="jukebox-guest-actions">
        {takes.includes('zero') && onZero && (zeroing ? (
          <>
            <button onClick={() => { onZero(); setZeroing(false); }}>Take {p.credits} back</button>
            <button onClick={() => setZeroing(false)}>Keep</button>
          </>
        ) : (
          <button onClick={() => setZeroing(true)}>Zero</button>
        ))}
        {takes.includes('merge') && onMerge && merging === null && (
          <InfoTip topic="jukebox-merge-phones"
            text="Two phones, one guest (a cleared cookie, a second phone): pick the phone that joins this one. Its songs, votes, time-out and credits come here, and both codes keep working as one guest.">
            <button onClick={() => setMerging('')}>Merge…</button>
          </InfoTip>
        )}
        {canGift && onGift && (giving === null ? (
          <button onClick={() => setGiving('2')}>Give…</button>
        ) : (
          <>
            <input type="number" min={1} max={GIFT_MAX} value={giving} aria-label={`Credits to give ${p.name}`}
              className="jukebox-gift-input" autoFocus onChange={(e) => setGiving(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && giveOk) { onGift(giveAmount); setGiving(null); }
                if (e.key === 'Escape') setGiving(null);
              }} />
            <button disabled={!giveOk} onClick={() => { onGift(giveAmount); setGiving(null); }}>Give</button>
          </>
        ))}
        {phoneActions(p).map((a) => (
          <button key={a} onClick={() => {
            if (a === 'approve') onSet({ approved: true });
            else if (a === 'pardon') onSet({ pardon: true });
            else if (a === 'block') onSet({ blocked: true });
            else if (a === 'unblock') onSet({ blocked: false });
            else if (a === 'lock') onSet({ name_locked: true });
            else if (a === 'unlock') onSet({ name_locked: false });
            else if (renaming === null) setRenaming(p.name);
            else { onSet({ name: renaming.trim() }); setRenaming(null); }
          }}>
            {a === 'rename' && renaming !== null ? 'Save' : ACTION_WORDS[a]}
          </button>
        ))}
      </span>
    </li>
  );
}
