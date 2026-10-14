/** THE OWNER'S PANIC HANDLE — mounted once in App.tsx under the one bar,
 * on every page, phone-first.
 *   - normal:   RENDERS NOTHING — the three amber strips below
 *               (ActivationStrip/DarkFixtureStrip/HueScopeStrip) moved
 *               into WarningChip.tsx's small "⚠ N" popover in the bar
 *               (UI declutter plan §13 Q8, decided yes: shrink the
 *               full-width warning to a chip). They're exported from
 *               here, unchanged in content, so WarningChip can draw them
 *               inside its own panel — this module just stops rendering
 *               them itself. The small, always-reachable "Release to HA"
 *               control lives at the right end of the bar (ReleaseButton.tsx,
 *               his ask 2026-10-06).
 *   - released: an unmissable full-width banner, with the way back — the
 *               SAME guarded handover to SPECTRA, still readiness-gated
 *               and SPECTRA_HANDOVER_ARMED-gated. UNCHANGED by either move
 *               above (his own "its behaviour after release is
 *               unchanged").
 * Plus, since 2026-08-21 (owner ruling: one unreachable device must not
 * keep the whole room dark — spectra/services/activation_report.py): the
 * ACTIVATION STRIP. A take-back from released now commits over a light it
 * could not reach instead of aborting the whole room to darkness, and a
 * silently partial take-back is its own trap — so while any light the last
 * take-back/resume had to skip is STILL dark, WarningChip's panel names it,
 * says why, and shows how long ago it was last rechecked (the server
 * re-asks every 30 s and retries the light's own driver; it disappears on
 * its own the moment the light confirms). The take-back's toast says the
 * same thing once, immediately. */
import HelpLink from '../help/HelpLink';
import { fmtAgo, fmtDuration } from '../lib/time';
import {
  useOwnership,
  useTakeBackToSpectra,
  type ActivationReport,
  type DarkFixtureStatus,
} from '../queries';
import { useToast } from './Toast';

function partialToast(act: ActivationReport): string {
  const dark = act.skipped.filter((d) => d.still_dark);
  const names = dark.map((d) => `${d.name} — ${d.why}`).join('; ');
  const gaps = Object.keys(act.virtual_gaps).length;
  const head = `SPECTRA owns the lights again — the show is up on ${act.devices_total - dark.length}/${act.devices_total} lights`;
  const tail = gaps > 0 ? ` · ${gaps} virtual(s) never came up` : '';
  return `${head}; skipped ${dark.length}: ${names}${tail}. Rechecking every ${Math.round(act.recheck_interval_s)}s.`;
}

export function ActivationStrip({ act }: { act: ActivationReport | null | undefined }) {
  if (!act || !act.partial) return null;
  const dark = act.skipped.filter((d) => d.still_dark);
  const gaps = Object.entries(act.virtual_gaps);
  if (dark.length === 0 && gaps.length === 0) return null;
  const source = act.source === 'resume' ? 'restart' : 'take-back';
  return (
    <div className="activation-strip" role="status">
      <span className="activation-strip-lead">
        ⚠ {source === 'take-back' ? 'Take-back' : 'Restart'} skipped {dark.length + gaps.length} light{dark.length + gaps.length === 1 ? '' : 's'}
        {' '}— the show is running on the rest
      </span>
      <ul>
        {dark.map((d) => (
          <li key={d.device_id} title={`${d.device_id}: ${d.reason}`}>
            <strong>{d.name}</strong> <span className="activation-strip-why">— {d.why}</span>
            {' '}<span className="activation-strip-age">· rechecked {fmtAgo(d.last_checked_age_s)}{d.retries > 0 ? `, retried ×${d.retries}` : ''}</span>
          </li>
        ))}
        {gaps.map(([vid, why]) => (
          <li key={vid}>
            <strong>{vid}</strong> <span className="activation-strip-why">— virtual never came up: {why}</span>
          </li>
        ))}
      </ul>
      <HelpLink topic="take-back-skipped-light" title="A light the take-back had to skip" />
    </div>
  );
}

/** THE DARK FIXTURE STRIP — a light SPECTRA is streaming to RIGHT NOW that
 * is not lit (spectra/services/dark_fixture_watch.py). Deliberately the
 * SAME amber strip as the activation one above, because to him it is the
 * same question — "which of my lights isn't working, and why" — and the
 * two answers arrive from different mechanisms only by accident of when
 * the light went. This one is the continuous half: the activation strip
 * can only ever speak about lights that were already dark when SPECTRA
 * took the room, which is exactly why his tv-backlight going dark
 * mid-show was invisible. Nothing is being written to fix it — this is a
 * report, and it says so. */
export function DarkFixtureStrip({ dark }: { dark: DarkFixtureStatus | null | undefined }) {
  if (!dark || dark.fault_count === 0) return null;
  return (
    <div className="activation-strip" role="status">
      <span className="activation-strip-lead">
        ⚠ {dark.fault_count} light{dark.fault_count === 1 ? ' is' : 's are'} dark or not answering
        {' '}while SPECTRA streams to {dark.fault_count === 1 ? 'it' : 'them'}
      </span>
      <ul>
        {dark.faults.map((d) => (
          <li key={d.device_id} title={`${d.device_id}: ${d.reason}`}>
            <strong>{d.name}</strong> <span className="activation-strip-why">— {d.why}</span>
            {' '}
            <span className="activation-strip-age">
              · dark for {fmtDuration(d.dark_for_s)}, last confirmed dark {fmtAgo(d.last_checked_age_s)}
              {dark.last_sweep_age_s !== null && <>, watch swept {fmtAgo(dark.last_sweep_age_s)}</>}
            </span>
          </li>
        ))}
      </ul>
      <HelpLink topic="dark-fixture-watch" title="A light that is dark or not answering while being streamed to" />
    </div>
  );
}

/** THE HUE SCOPE STRIP — a Hue area SPECTRA is deliberately NOT streaming,
 * because it holds a bulb off fx/hue_scope.py's allow-list (a generic
 * safety net for a bulb genuinely outside the room — today none of his
 * real bulbs are excluded, his Music Group area included). Starting a Hue
 * entertainment session switches on every bulb in the area, so the whole
 * area stays out of the show until those bulbs are taken out of it in the
 * Hue app — and that has to be said, or the area just looks broken. */
export function HueScopeStrip({ refusals }: { refusals: Record<string, string> | null | undefined }) {
  const entries = Object.entries(refusals ?? {});
  if (entries.length === 0) return null;
  return (
    <div className="activation-strip" role="status">
      <span className="activation-strip-lead">
        ⚠ {entries.length} Hue area{entries.length === 1 ? ' is' : 's are'} not in the show
        {' '}— {entries.length === 1 ? 'it holds' : 'they hold'} bulbs Spectra may not light
      </span>
      <ul>
        {entries.map(([did, why]) => (
          <li key={did}>
            <strong>{did}</strong> <span className="activation-strip-why">— {why}</span>
          </li>
        ))}
      </ul>
      <HelpLink topic="hue-scope-stream" title="A Hue area left out of the show" />
    </div>
  );
}

export default function RoomOwnershipBar() {
  const { data } = useOwnership();
  const takeBack = useTakeBackToSpectra();
  const toast = useToast();

  if (!data) return null;

  const released = data.owner === 'released';

  const doTakeBack = () => {
    takeBack.mutate(undefined, {
      onSuccess: (result) => {
        if (result.result === 'committed-partial' && result.activation) {
          // The room came up — minus the named light(s). Say so now, and
          // keep saying so on the strip until they come back.
          toast(partialToast(result.activation), 'error');
        } else {
          toast('SPECTRA owns the lights again', 'success');
        }
      },
      onError: (e) => toast(`Take-back failed: ${(e as Error).message}`, 'error'),
    });
  };

  if (released) {
    return (
      <div className="release-banner">
        <span className="release-banner-msg">
          ⚠ Room released to Home Assistant — SpotFX and SPECTRA have let go
        </span>
        <button className="primary" onClick={doTakeBack} disabled={takeBack.isPending}>
          {takeBack.isPending ? 'Taking back…' : '← Take back (SPECTRA)'}
        </button>
        <HelpLink topic="panic-release" />
      </div>
    );
  }

  // The normal path's own strips moved into WarningChip.tsx's "⚠ N" chip
  // in the bar — see this module's own docstring.
  return null;
}
