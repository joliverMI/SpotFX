/** THE UP-NEXT CALLOUT (data/tv-display-plan/plan.html PR 1.4, §2.2):
 * "the callout in the last 30 s of a song once the next song is sent to
 * Spotify" — only what guests already see (the next item's title and who
 * added it), no prices, no credits. */
import { NextItem } from './jukeboxTypes';
import { byWords } from './partyLogic';

export default function UpNextCallout({ item }: { item: NextItem }) {
  return (
    <div className="tv-callout" role="status">
      <b>Up next:</b> &ldquo;{item.title}&rdquo; — {byWords(item.by)}
    </div>
  );
}
