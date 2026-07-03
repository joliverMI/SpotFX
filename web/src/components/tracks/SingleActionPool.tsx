import type { Action } from '../../types/events';
import ActionCard from '../cards/ActionCard';

/** Weighted random-pick pool: the engine fires ONE of these per trigger. */
export default function SingleActionPool({ actions, title }: { actions: Action[]; title?: string }) {
  return (
    <div className="track">
      <div className="track-header">
        <span>🎲</span>
        <span>{title ?? `Random pick — one of ${actions.length} (weighted)`}</span>
      </div>
      {actions.map((a, i) => (
        <ActionCard key={i} action={a} />
      ))}
      {!actions.length && <p className="empty-note">No actions.</p>}
    </div>
  );
}
