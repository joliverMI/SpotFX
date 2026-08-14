/** THE OWNER'S PANIC HANDLE — mounted once in App.tsx under the nav, on
 * every page, phone-first. Two shapes, one component:
 *   - normal:   a small, always-reachable "Release to HA" button. No
 *               confirmation — the press is the consent, the same
 *               deliberate asymmetry as the scene Fire button.
 *   - released: an unmissable full-width banner replaces the button, with
 *               the way back — the SAME guarded handover to SPECTRA, still
 *               readiness-gated and SPECTRA_HANDOVER_ARMED-gated. */
import HelpLink from '../help/HelpLink';
import { useOwnership, useReleaseRoom, useTakeBackToSpectra } from '../queries';
import { useToast } from './Toast';

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
      onSuccess: () => toast('SPECTRA owns the lights again', 'success'),
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
    <button
      className="panic-release-btn"
      onClick={doRelease}
      disabled={release.isPending || handingOver}
      title="Release ALL lights to Home Assistant — no confirmation, the press is the consent"
    >
      {release.isPending ? 'Releasing…' : '⏻ Release to Home Assistant'}
    </button>
  );
}
