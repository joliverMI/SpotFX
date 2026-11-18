/** WORD TEST MODE — the second loud top bar (2026-11-17, the Admiral: "did
 * we implement a system to 'test' where all word flares (shape or color)
 * fire, no matter the confidence? how do i turn that on?", and his own two
 * answers on where the switch lives and whether it expires: "Settings, no
 * auto off").
 *
 * WHY A BAR AT ALL. The switch has NO auto-off by his instruction, so the
 * only thing standing between "I turned it on for an evening" and "every
 * song has behaved oddly for three weeks" is him remembering. A setting
 * that cannot time out has to announce itself instead, on every route, not
 * only on the page where it was flipped.
 *
 * WHY NOT INSIDE TestingBar's OWN FOLD. TestingBar answers one question —
 * "is something USING MY LIGHTS right now?" — off `GET /test-session`,
 * whose every source is a path that HOLDS the room and whose stated
 * contract is that it clears itself (spectra/services/test_session.py's
 * rule 1, and the `testing-bar` Help topic's "a bar cannot outlive the
 * testing that raised it"). Word test mode holds nothing and never
 * expires, so folding it in there would make that bar claim his lights
 * were in use while nothing was playing, and break the one promise that
 * makes it trustworthy. It gets its own bar, in its own colours, saying
 * its own thing — and the two stack when both are true.
 *
 * IT IS ALSO THE REMEDY. "Turn it off" writes the setting straight back
 * through the same PUT /api/room-controls every other direct control uses,
 * so the loudest thing on the screen is one tap from being gone.
 *
 * DEFAULT TO QUIET, unlike TestingBar: the switch's own value is the whole
 * question, and an unreachable backend tells us nothing about it. A field
 * missing from an older server reads as off (optional in the type). */
import HelpLink from '../help/HelpLink';
import { useRoomControls, useSaveRoomControls } from '../queries';

export default function WordTestModeBar() {
  const { data: room } = useRoomControls();
  const save = useSaveRoomControls();

  if (!room?.word_test_mode) return null;

  return (
    <div className="testing-bar testing-bar-word-test" role="status" aria-live="polite">
      <div className="testing-bar-title">Word test mode</div>
      <div className="testing-bar-detail">
        <span className="testing-bar-headline">
          EVERY word flare fires — colour and shape — whatever its confidence
        </span>
        <span className="testing-bar-sub">
          A word you pinned to Never still never plays, and two words closer together than
          the minimum gap (8 s) still cannot both fire. It stays on until you turn it off.
        </span>
      </div>
      <button
        type="button"
        className="testing-bar-action"
        disabled={save.isPending}
        onClick={() => save.mutate({ ...room, word_test_mode: false })}
      >
        Turn it off
      </button>
      <HelpLink topic="word-test-mode" title="What word test mode does" />
    </div>
  );
}
