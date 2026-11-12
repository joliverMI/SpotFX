/** How often one match plays: Always, Chance (its own confidence, the
 * default), or Never (spectra/services/lyric_matches.py `set_pin`, read by
 * lyric_events.chance_for). A small segmented control, shown only in a
 * selected match's or word's panel so the lanes stay as they were. */
import type { LyricPin } from '../../types';
import { PIN_CHOICES } from '../lyricEvents';

export default function PinControl({
  pin, chance, busy, onPin,
}: {
  pin: LyricPin | null;
  /** the share of plays it gets on Chance: Claude's confidence, 1 for his own */
  chance: number | null;
  busy: boolean;
  onPin: (pin: 'always' | 'chance' | 'never') => void;
}) {
  return (
    <div className="testbed-pin" role="group" aria-label="How often this word plays">
      <span className="testbed-pin-title">Plays</span>
      {PIN_CHOICES.map((choice) => {
        const on = choice.pin === pin;
        return (
          <button
            key={choice.pin ?? 'chance'}
            type="button"
            className={on ? 'on' : ''}
            aria-pressed={on}
            disabled={busy}
            onClick={() => { if (!on) onPin(choice.pin ?? 'chance'); }}
          >
            {choice.words(chance)}
          </button>
        );
      })}
    </div>
  );
}
