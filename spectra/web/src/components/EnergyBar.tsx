/** Energy + Mark, grouped — UI declutter plan §13 Q12 (decided yes): below
 * desktop width, "Mark" folds into the Energy control so the Scenes/Colour
 * name slots get back the pixels Mark used to cost on its own.
 *
 * THE FOLD IS NOW REAL (design-fidelity pass, 2026-10-14): the mockup
 * HIDES the Mark box at <=1180px (`@container sp (max-width: 1180px)
 * { .mark { display: none } }`) and the Energy slot is what opens Mark
 * there. The first build implemented it as "hide the word Mark" only,
 * which left Mark's value and its ⓘ circle dangling after the meter as a
 * loose "ⓘ —" (audit B6). This component owns the one open/closed state
 * so either control can open the one panel; the two children keep their
 * own data hooks, unchanged. */
import { useState } from 'react';
import IntensityMarkControl from './IntensityMarkControl';
import LiveEnergyReadout from './LiveEnergyReadout';

export default function EnergyBar() {
  const [markOpen, setMarkOpen] = useState(false);
  return (
    <div className="energy-mark-group">
      <LiveEnergyReadout onOpenMark={() => setMarkOpen((o) => !o)} />
      <IntensityMarkControl open={markOpen} onOpenChange={setMarkOpen} />
    </div>
  );
}
