/** The 6-most-recent row under a Force Scene / Force Colour searchable
 * picker (owner ask, card force-colour-and-forced-trigger-dialogs-p99a,
 * verbatim: "To fill the empty space, add buttons for the 6 most recently
 * used triggers/colours"). This is an ADDITION beside the search box, never
 * a replacement for it — his own words draw that line.
 *
 * Reserves real vertical space in the panel's normal flow (a fixed
 * `min-height` below) whether or not any recents exist yet, which is what
 * keeps the panel from being exactly as short as it was before this
 * shipped — see RoomControlsBar.tsx's own comment on why that height is
 * what stops the search dropdown from being clipped by the panel's
 * `overflow-y: auto` boundary.
 *
 * A recent button is never a second idea of "what's selected" — it reads
 * its own highlighted state from the SAME `value` the searchable list
 * itself is bound to, and pressing one calls the identical `onPick` the
 * search list's own `onChange` calls, so the two can never disagree. */
export interface RecentChoiceOption {
  value: string;
  label: string;
}

export default function RecentChoiceButtons({
  recentIds,
  options,
  value,
  onPick,
  emptyLabel,
}: {
  recentIds: string[];
  options: RecentChoiceOption[];
  value: string;
  onPick: (v: string) => void;
  emptyLabel: string;
}) {
  const byId = new Map(options.map((o) => [o.value, o]));
  // A recent id whose scene/colour set was since deleted is dropped here,
  // not rendered blank — the options list is the one live source of what
  // still exists.
  const present = recentIds.map((id) => byId.get(id)).filter((o): o is RecentChoiceOption => !!o);

  return (
    <div className="top-bar-recent-choices">
      <div className="top-bar-recent-choices-label">Recent</div>
      {present.length === 0 && (
        <div className="top-bar-recent-choices-empty">{emptyLabel}</div>
      )}
      {present.length > 0 && (
        <div className="top-bar-recent-choices-grid">
          {present.map((o) => (
            <button
              key={o.value}
              type="button"
              className={`top-bar-recent-choice-btn${o.value === value ? ' top-bar-recent-choice-btn-active' : ''}`}
              title={o.label}
              onClick={() => onPick(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
