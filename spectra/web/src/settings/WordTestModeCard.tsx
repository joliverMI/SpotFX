/** Settings → "Word test mode" card (2026-11-17, the Admiral: "did we
 * implement a system to 'test' where all word flares (shape or color)
 * fire, no matter the confidence? how do i turn that on?"). He chose where
 * it lives and how it ends, verbatim: "Settings, no auto off" — so this is
 * the switch, and there is no timer anywhere behind it.
 *
 * ONE SWITCH, and the card states its boundary rather than leaving him to
 * discover it: what it forces (every match's chance), what it will not
 * touch (a Never pin, a deleted match) and the one rule that still stops a
 * word he will otherwise think is broken (the 8 s minimum gap). The
 * binding statement is spectra/services/lyric_events.py's "WORD TEST MODE";
 * the setting is RoomControlState.word_test_mode, written through the same
 * PUT /api/room-controls as every other direct control on this page.
 *
 * It is a DIRECT control on a page whose standing order is "talk to Sonic"
 * for the same reason RoomCard and ScenesDropsCard are: he asked for this
 * one here, by name. Sonic can still set it — it is an ordinary registry
 * key (settings_console.SETTINGS_REGISTRY), so it also shows in "Current
 * settings" below.
 *
 * WHILE IT IS ON the card says so loudly, and so does the Test Bed's own
 * Word matches row (by his 2026-11-18 word, no top-bar banner for this
 * one — see the night-run doc's "why its own bar" paragraph for the
 * history). A switch that cannot expire has to be impossible to forget. */
import HelpLink from '../help/HelpLink';
import Icon from '../components/Icon';
import { useRoomControls, useSaveRoomControls } from '../queries';

export default function WordTestModeCard() {
  const { data: room } = useRoomControls();
  const save = useSaveRoomControls();
  const on = !!room?.word_test_mode;

  return (
    <div className={`card settings-word-test-card${on ? ' settings-word-test-on' : ''}`}>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Icon name="spark" size={16} /> Word test mode
        <HelpLink topic="word-test-mode" title="What word test mode does" />
      </div>
      <label className="settings-word-test-switch">
        <input
          type="checkbox"
          checked={on}
          disabled={!room || save.isPending}
          onChange={(e) => room && save.mutate({ ...room, word_test_mode: e.target.checked })}
        />
        Every word flare fires, colour and shape, whatever its confidence
      </label>
      <div className={on ? 'settings-word-test-state on' : 'settings-word-test-state'}>
        {on
          ? 'ON — every matched word plays on every play. It stays on until you turn it off.'
          : 'Off — a matched word plays on the share of plays its confidence says.'}
      </div>
      <p className="settings-word-test-note">
        A word you pinned to <strong>Never</strong> still never plays, and a match you deleted
        stays deleted: this overrides a chance, never an explicit no. Nothing else changes —
        two matched words closer together than the <strong>minimum gap</strong> (8 s by
        default) still cannot both fire, a scene still has to allow the word&apos;s colours or
        carry a Words band for its shape, and the shape timings are untouched. Your pins and
        your kept rolls are not written to.
      </p>
    </div>
  );
}
