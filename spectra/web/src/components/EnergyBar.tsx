/** Energy + Mark, grouped — UI declutter plan §13 Q12 (decided yes): below
 * desktop width, "Mark" folds into the Energy control so the Scenes/Colour
 * name slots get back the pixels Mark used to cost on its own. Both
 * controls are untouched (LiveEnergyReadout.tsx / IntensityMarkControl.tsx
 * keep their own state/hooks) — this is a layout wrapper only, with the
 * actual fold done in CSS (`.energy-mark-group` narrows the Mark half at
 * <=1180px — his two named tablet widths, 1024 and 1180). */
import IntensityMarkControl from './IntensityMarkControl';
import LiveEnergyReadout from './LiveEnergyReadout';

export default function EnergyBar() {
  return (
    <div className="energy-mark-group">
      <LiveEnergyReadout />
      <IntensityMarkControl />
    </div>
  );
}
