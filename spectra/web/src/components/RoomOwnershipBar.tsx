/** THE OWNER'S PANIC HANDLE — mounted once in App.tsx under the nav, on
 * every page, phone-first. Two shapes, one component:
 *   - normal:   a small, always-reachable "Release to HA" button. No
 *               confirmation — the press is the consent, the same
 *               deliberate asymmetry as the scene Fire button.
 *   - released: an unmissable full-width banner replaces the button, with
 *               the way back — the SAME guarded handover to SPECTRA, still
 *               readiness-gated and SPECTRA_HANDOVER_ARMED-gated.
 * Plus, since 2026-08-21 (owner ruling: one unreachable device must not
 * keep the whole room dark — spectra/services/activation_report.py): the
 * ACTIVATION STRIP. A take-back from released now commits over a light it
 * could not reach instead of aborting the whole room to darkness, and a
 * silently partial take-back is its own trap — so while any light the last
 * take-back/resume had to skip is STILL dark, an amber strip on every page
 * names it, says why, and shows how long ago it was last rechecked (the
 * server re-asks every 30 s and retries the light's own driver; the strip
 * disappears on its own the moment the light confirms). The take-back's
 * toast says the same thing once, immediately. */
import HelpLink from '../help/HelpLink';
import { fmtAgo } from '../lib/time';
import { useOwnership, useReleaseRoom, useTakeBackToSpectra, type ActivationReport } from '../queries';
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

export default function RoomOwnershipBar() {
  const { data } = useOwnership();
  const release = useReleaseRoom();
  const takeBack = useTakeBackToSpectra();
  const toast = useToast();

  if (!data) return null;

  const released = data.owner === 'released';
  const handingOver = data.owner === 'handing-over';

  const doRelease = () => {
    release.mutate(undefined, {
      onSuccess: (result) => {
        if (result.result !== 'released') {
          // Loud, not silent: the record moved to released, but a device
          // could not be confirmed dark — it may still be lit.
          toast(
            `Release unverified — these lights may still be lit: ${(result.problems ?? []).join('; ')}`,
            'error',
          );
        }
      },
      onError: (e) => toast(`Release failed: ${(e as Error).message}`, 'error'),
    });
  };

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

  return (
    <>
      <ActivationStrip act={data.activation} />
      <button
        className="panic-release-btn"
        onClick={doRelease}
        disabled={release.isPending || handingOver}
        title="Release ALL lights to Home Assistant — no confirmation, the press is the consent"
      >
        {release.isPending ? 'Releasing…' : '⏻ Release to Home Assistant'}
      </button>
    </>
  );
}
