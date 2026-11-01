/** Settings → "Second Spotify account" card: the ONE switch that must be on
 * before the system may do anything with the second Spotify account except
 * read it.
 *
 * The Admiral, 2026-11-01: "a toggle button on settings page ... that must
 * be "enabled" in order for the system to use the second account in any
 * capacity other than reading info ... a solid barrier so that the second
 * user doesn't get their music taken from them by the system." It ships
 * OFF.
 *
 * THIS CARD IS ONLY THE SWITCH. The barrier is server-side and lives below
 * every caller (fx/second_account.py is the binding statement): SpotFX's
 * second-account Spotify client asks the record before each write leaves,
 * fresh from disk, so nothing the system does can play, pause, skip, queue
 * or change anything on that account while this is off — however it was
 * asked. Turned off while the hidden player is learning a song, that song
 * is stopped within a couple of seconds and the system lets go; the second
 * user's own playback is never touched.
 *
 * An unreadable setting reads as OFF here, because that is how the server
 * treats it. One help link, on the card title's own tooltip — no visible
 * circle (the Settings page's "one help '?' per page" rule). */
import { useState } from 'react';
import Icon from '../components/Icon';
import InfoTip from '../components/InfoTip';
import PowerButton from '../components/PowerButton';
import { useSecondAccount, useSetSecondAccount } from '../queries';

const EXPLAIN =
  'Off (the default): the system only ever reads the second Spotify account — what it is playing, '
  + 'its devices — and never plays, pauses, skips, queues or changes anything on it, so the person '
  + 'using that account never has their music taken. On: the hidden player "Serenity Capture" may '
  + 'learn songs on it (the Jukebox and Absorb). Turning it off while it is learning a song stops '
  + 'that song within a few seconds; their own listening is never touched.';

function fmtWhen(ms: number | null): string {
  if (!ms) return '';
  const d = new Date(ms);
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export default function SecondAccountCard() {
  const { data, isError, isLoading } = useSecondAccount();
  const save = useSetSecondAccount();
  const [lettingGo, setLettingGo] = useState<string | null>(null);

  const state = data?.state;
  const on = state === 'on';
  let line: string;
  if (isLoading) line = 'Reading the setting…';
  else if (isError || !state) line = "The setting can't be reached, so the system treats the second account as locked.";
  else line = data.sentence;
  const when = on || state === 'off' ? fmtWhen(data?.changed_at_ms ?? null) : '';

  const flip = (next: boolean) => {
    setLettingGo(null);
    save.mutate(next, { onSuccess: (st) => setLettingGo(st.letting_go ?? null) });
  };

  return (
    <div className="card settings-second-account-card">
      <InfoTip topic="second-account-lock" text={EXPLAIN}>
        <div className="card-title">Second Spotify account</div>
      </InfoTip>
      <div className="settings-row">
        <InfoTip topic="second-account-lock" text={EXPLAIN}>
          <span className="settings-row-label"><Icon name="lock" size={15} /> Let the system use it</span>
        </InfoTip>
        <span>
          <PowerButton
            on={on}
            onChange={(next) => { if (!save.isPending) flip(next); }}
            ariaLabel="the system's use of the second Spotify account"
            title={on
              ? 'On — the system may play on the second Spotify account. Press to lock it.'
              : 'Off — the system only reads the second Spotify account. Press to allow it to play.'}
          />
        </span>
        <span className="settings-row-value">{state === 'unreadable' ? 'Locked' : on ? 'On' : 'Off'}</span>
      </div>
      <p className={`settings-second-account-line${state === 'unreadable' || isError ? ' warn' : ''}`}>
        {line}{when ? ` Since ${when}.` : ''}
      </p>
      {lettingGo && <p className="settings-second-account-line">{lettingGo}</p>}
      {save.isError && (
        <p className="settings-second-account-line warn">
          Couldn't save the change — it is still {on ? 'on' : 'off'}.
        </p>
      )}
    </div>
  );
}
