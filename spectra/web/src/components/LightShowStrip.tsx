/** The Light Show's line in the shared top bar: "Show: 2 holding, 1 level"
 * on every page while the show holds anything, absent otherwise — so he
 * never has to ask what the show is doing to his room. Tapping it opens
 * the Light Show page. Reads the `light_show` key of the engine status the
 * app already polls; no extra request. */
import { Link } from 'react-router-dom';
import { useEngineStatus } from '../queries';
import HelpLink from '../help/HelpLink';
import { stripLine } from '../lightshow/showSummary';
import type { ShowBrief } from '../lightshow/types';

export default function LightShowStrip() {
  const { data } = useEngineStatus();
  const brief = (data as { light_show?: ShowBrief } | undefined)?.light_show;
  const line = stripLine(brief);
  if (!line) return null;
  return (
    <span className="light-show-strip">
      <Link to="/show">◈ {line}</Link>
      <HelpLink topic="show-strip" />
    </span>
  );
}
