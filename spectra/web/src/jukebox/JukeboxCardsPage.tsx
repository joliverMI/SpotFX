/** THE PRINTABLE GUEST CARD (/jukebox/cards; the plan's §9 N2 and §8.1): a
 * sheet of cards, each with the guest Wi-Fi's QR, the Jukebox's QR (the
 * party link with that card's one-time bonus code) and the code as text.
 *
 * THE WI-FI PASSWORD IS TYPED HERE, AT PRINT TIME, AND NEVER LEAVES THIS
 * PAGE: it is React state only — no request carries it, nothing stores it,
 * and the QR is drawn here (cardQr.ts). The plan's rule: the Wi-Fi QR IS
 * the password, so hand the cards out at the party and change the guest
 * password afterwards. The page renders outside SPECTRA's chrome (App.tsx),
 * so what prints is the sheet alone. */
import { useMemo, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { cardCodes, joinLink, qrMatrix, qrPath, QUIET, wifiPayload, wifiProblem, type WifiSecurity } from './cardQr';
import { useJukeboxCard, useSaveLinkHost } from './queries';

const SECURITY: { value: WifiSecurity; label: string }[] = [
  { value: 'WPA', label: 'WPA / WPA2 / WPA3' }, { value: 'WEP', label: 'WEP (old)' },
  { value: 'nopass', label: 'No password' },
];

function QrSvg({ text, label }: { text: string; label: string }) {
  const m = useMemo(() => qrMatrix(text), [text]);
  const size = m.length + 2 * QUIET;
  return (
    <svg className="jukebox-card-qr" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}
         shapeRendering="crispEdges" data-qr-size={size}>
      <rect width={size} height={size} fill="#fff" />
      <path d={qrPath(m)} fill="#000" />
    </svg>
  );
}

export default function JukeboxCardsPage() {
  const q = useJukeboxCard();
  const saveHost = useSaveLinkHost();
  const [ssid, setSsid] = useState('');
  const [password, setPassword] = useState('');
  const [security, setSecurity] = useState<WifiSecurity>('WPA');
  const [hidden, setHidden] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const [printPw, setPrintPw] = useState(false);
  const [count, setCount] = useState('8');
  const [withCodes, setWithCodes] = useState(true);
  const [host, setHost] = useState('');
  const data = q.data;
  const wifi = { ssid, password, security, hidden };
  const wifiWhy = wifiProblem(wifi);
  const wifiText = wifiWhy ? '' : wifiPayload(wifi);
  const codesOn = withCodes && !!data && data.play_mode === 'credits';
  const cards = data?.link ? cardCodes(data.unused, Number(count) || 0, codesOn) : [];
  const short = codesOn && data ? cards.filter((c) => c === null).length : 0;
  const problems = [
    !data?.link ? 'The guest link has no address yet.' : '',
    wifiWhy,
    cards.length === 0 && data?.link ? 'Choose how many cards (1-60).' : '',
  ].filter(Boolean);
  const ready = problems.length === 0;

  return (
    <main className="jukebox-cards-page" data-testid="jukebox-cards-page">
      <section className="jukebox-cards-controls no-print">
        <div className="jukebox-cards-head">
          <h1>Print the guest cards</h1>
          <HelpLink topic="jukebox-cards" />
        </div>
        <p className="jukebox-muted">
          Each card has the guest Wi-Fi&apos;s QR code, the Jukebox&apos;s QR code (tonight&apos;s party link with that
          card&apos;s one-time bonus code) and the code as text. The Wi-Fi password stays on this page — it is never
          sent anywhere or saved. The Wi-Fi QR code <strong>is</strong> the password: hand the cards out at the
          party, and change the guest password afterwards.
        </p>
        {q.isError && <p className="jukebox-error">The card details couldn&apos;t be read from SpotFX.</p>}

        <fieldset className="jukebox-cards-fields">
          <legend>The guest Wi-Fi</legend>
          <label className="jukebox-cards-field">
            <span className="jukebox-field-label">Network name</span>
            <input type="text" value={ssid} maxLength={32} autoComplete="off" spellCheck={false}
                   aria-label="Wi-Fi network name" onChange={(e) => setSsid(e.target.value)} />
          </label>
          <label className="jukebox-cards-field">
            <span className="jukebox-field-label">Security</span>
            <select value={security} aria-label="Wi-Fi security"
                    onChange={(e) => setSecurity(e.target.value as WifiSecurity)}>
              {SECURITY.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
          {security !== 'nopass' && (
            <div className="jukebox-cards-field">
              <span className="jukebox-field-label">Password</span>
              <span className="jukebox-cards-row">
                <input type={showPw ? 'text' : 'password'} value={password} maxLength={63}
                       autoComplete="new-password" spellCheck={false} aria-label="Wi-Fi password"
                       onChange={(e) => setPassword(e.target.value)} />
                <button type="button" onClick={() => setShowPw((v) => !v)}>{showPw ? 'Hide' : 'Show'}</button>
              </span>
            </div>
          )}
          <label className="jukebox-field jukebox-check">
            <input type="checkbox" checked={hidden} onChange={(e) => setHidden(e.target.checked)} />
            The network is hidden
          </label>
          {security !== 'nopass' && (
            <label className="jukebox-field jukebox-check">
              <input type="checkbox" checked={printPw} onChange={(e) => setPrintPw(e.target.checked)} />
              Print the password as text too (for a phone that can&apos;t scan)
            </label>
          )}
        </fieldset>

        <fieldset className="jukebox-cards-fields">
          <legend>The Jukebox link</legend>
          {data?.lan_link && (
            <p className="jukebox-muted" data-testid="jukebox-cards-lan-link">
              On the home Wi-Fi: <code>{data.lan_link}</code> — a phone already on Serenity&apos;s network opens
              this directly, no Tailscale Funnel needed.
            </p>
          )}
          {data?.link ? (
            <p className="jukebox-muted" data-testid="jukebox-cards-link">
              {data.host}{data.public_port === 443 ? '' : `:${data.public_port}`} — tonight&apos;s party link. It
              changes after a party that used it, so print fresh cards for each party.
            </p>
          ) : data && (
            <div className="jukebox-cards-field">
              <span className="jukebox-field-label">Serenity&apos;s public address</span>
              <span className="jukebox-cards-row">
                <input type="text" value={host} placeholder="serenity.<tailnet>.ts.net" aria-label="The guest link's address"
                       onChange={(e) => setHost(e.target.value)} />
                <button type="button" disabled={!host.trim() || saveHost.isPending}
                        onClick={() => saveHost.mutate(host.trim())}>Save</button>
              </span>
              {saveHost.isError && <span className="jukebox-error">{String((saveHost.error as Error)?.message ?? saveHost.error)}</span>}
            </div>
          )}
        </fieldset>

        <fieldset className="jukebox-cards-fields">
          <legend>The cards</legend>
          <label className="jukebox-cards-field">
            <span className="jukebox-field-label">Cards</span>
            <input type="number" min={1} max={60} value={count} aria-label="How many cards"
                   onChange={(e) => setCount(e.target.value)} />
          </label>
          {data?.play_mode === 'credits' ? (
            <label className="jukebox-field jukebox-check">
              <input type="checkbox" checked={withCodes} onChange={(e) => setWithCodes(e.target.checked)} />
              A bonus code on each card (+{data.qr_bonus} credits, once) — {data.unused.length} unused
            </label>
          ) : data && <p className="jukebox-muted">The guest page is on free play, so the cards carry no bonus codes.</p>}
          {short > 0 && (
            <p className="jukebox-muted" data-testid="jukebox-cards-short">
              {short} card{short === 1 ? '' : 's'} will have no bonus code — make more on the Credits tab&apos;s Bonus cards card.
            </p>
          )}
          {data?.codes_error && <p className="jukebox-error">{data.codes_error}</p>}
        </fieldset>

        {problems.length > 0 && (
          <ul className="jukebox-cards-problems" data-testid="jukebox-cards-problems">
            {problems.map((p) => <li key={p}>{p}</li>)}
          </ul>
        )}
        <button type="button" className="jukebox-cards-print" disabled={!ready} onClick={() => window.print()}>
          Print {cards.length || ''} card{cards.length === 1 ? '' : 's'}
        </button>
      </section>

      {ready && data?.link && (
        <section className="jukebox-cards-sheet" data-testid="jukebox-cards-sheet">
          {cards.map((code, i) => (
            <article key={code ?? `card-${i}`} className="jukebox-card-print" data-testid="jukebox-card">
              <div className="jukebox-card-print-title">
                <span>♪ Serenity Jukebox</span>
                <span className="jukebox-card-print-small">Credits are free and only for tonight.</span>
              </div>
              <div className="jukebox-card-print-qrs">
                <figure>
                  <QrSvg text={wifiText} label="Join the Wi-Fi" />
                  <figcaption>
                    <strong>1 · Join the Wi-Fi</strong>
                    <span>{ssid}</span>
                  </figcaption>
                </figure>
                <figure>
                  <QrSvg text={joinLink(data.link as string, code)} label="Open the Jukebox" />
                  <figcaption>
                    <strong>2 · Open the Jukebox</strong>
                    <span>vote and add songs</span>
                  </figcaption>
                </figure>
              </div>
              {printPw && security !== 'nopass' && (
                <div className="jukebox-card-print-pw" data-testid="jukebox-card-pw">
                  Wi-Fi password: <code>{password}</code>
                </div>
              )}
              {code && (
                <div className="jukebox-card-print-bonus" data-testid="jukebox-card-code">
                  Bonus card: +{data.qr_bonus} credits · <code>{code}</code> · works once
                </div>
              )}
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
