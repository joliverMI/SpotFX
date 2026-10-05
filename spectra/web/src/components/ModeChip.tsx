/** HOUSE LIGHTING's chip — first in the shared top bar on every page:
 * "Mode: Evening · HA", "Mode: Evening · ♪" while music has the room,
 * "· not applied" when SPECTRA does not hold the room. Tapping it opens the
 * House page. Reads the `lighting` key of the engine status the app
 * already polls; no extra request. The words live in house/houseSummary.ts
 * so the chip and the House page's Now panel can never disagree. */
import { Link } from 'react-router-dom';
import HelpLink from '../help/HelpLink';
import { chipLine } from '../house/houseSummary';
import type { LightingStatus } from '../house/types';
import { useEngineStatus } from '../queries';

export default function ModeChip() {
  const { data } = useEngineStatus();
  const lighting = (data as { lighting?: LightingStatus } | undefined)?.lighting;
  const { text, tone, title } = chipLine(lighting);
  return (
    <span className={`mode-chip mode-chip-${tone}`}>
      <Link to="/house" title={title}>⌂ {text}</Link>
      <HelpLink topic="house-chip" />
    </span>
  );
}
