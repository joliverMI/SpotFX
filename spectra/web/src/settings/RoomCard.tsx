/** Settings → "Room" card (UI declutter plan §3/§9, decided yes): the
 * room-wide Brightness dimmer, the two-dimensional drift gradient, and
 * the device-preview strip's Favourites picker — three direct controls
 * that used to sit in the top bar and now live here instead. A UI move
 * only: same writers (PUT /api/room-controls, the gradients store, the
 * favourites PUT) as before.
 *
 * THREE COMPACT ROWS, the approved mockup's own shape (design-fidelity
 * pass, 2026-10-14 — audit S1): a `170px label | control | 60px value`
 * grid, each label carrying its own glyph, with the brightness % right-
 * aligned, the gradient as a dropdown + ＋New, and the favourites as
 * inline chips. The live build reused `DriftGradientPanel` and
 * `FavoritesPicker` VERBATIM in their popover/dialog shapes (four large
 * swatch tiles, two explanatory sentences, a bordered checkbox form with
 * Reset/Cancel/Save), which is why this card looked nothing like the
 * drawing. Each component keeps its own full shape for every other
 * caller and grew a row variant for this one (`compact` / `chips`).
 *
 * NO VISIBLE HELP CIRCLE (audit S3, idea 5's "one help '?' per page"):
 * each row's description — and its Help link — live on the label's own
 * hover/long-press tooltip, so the topics stay linked (AGENTS.md's own
 * orphan rule) with nothing drawn in the card. */
import { useEffect, useState } from 'react';
import DriftGradientPanel from '../components/DriftGradientPanel';
import FavoritesPicker from '../components/FavoritesPicker';
import Icon from '../components/Icon';
import InfoTip from '../components/InfoTip';
import { useRoomControls, useSaveRoomControls } from '../queries';

/** The one setting the drift-gradient panel used to carry inside itself
 * and the compact row no longer shows — kept visible as its own row
 * rather than silently dropped with the panel's long form. */
function RainbowLimitRow() {
  const { data: room } = useRoomControls();
  const save = useSaveRoomControls();
  if (!room) return null;
  return (
    <div className="settings-row">
      <InfoTip
        text="Above this live intensity, automatic colour-set selection is restricted to rainbow-marked sets only; at or below it, to single (non-rainbow) sets only.">
        <span className="settings-row-label"><Icon name="palette" size={15} /> Rainbow select limit</span>
      </InfoTip>
      <input
        type="number" min={0} max={1} step={0.05}
        className="settings-row-number"
        value={room.rainbow_select_limit ?? 0.9}
        onChange={(e) => {
          const v = Math.max(0, Math.min(1, Number(e.target.value)));
          void save.mutateAsync({ ...room, rainbow_select_limit: v });
        }}
      />
      <span className="settings-row-value" />
    </div>
  );
}

function BrightnessRow() {
  const { data: room } = useRoomControls();
  const save = useSaveRoomControls();
  const [pct, setPct] = useState<number | null>(null);

  useEffect(() => {
    if (room && !save.isPending) setPct(Math.round(room.brightness_multiplier * 100));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [room, save.isPending]);

  if (!room || pct === null) return null;

  const commit = (v: number) => save.mutate({ ...room, brightness_multiplier: v / 100 });

  return (
    <div className="settings-row">
      <InfoTip topic="room-controls-bar"
        text="Dims or undims the whole room uniformly — applied at the write seams, so it scales every fixture's brightness without touching any scene's own authored values.">
        <span className="settings-row-label"><Icon name="bulb" size={15} /> Brightness</span>
      </InfoTip>
      <input
        type="range" min={0} max={100} step={1}
        value={pct}
        onChange={(e) => setPct(Number(e.target.value))}
        onMouseUp={() => commit(pct)}
        onTouchEnd={() => commit(pct)}
        title="Brightness — dims/undims the whole room uniformly"
      />
      <span className="settings-row-value tabular-nums">{pct}%</span>
    </div>
  );
}

export default function RoomCard() {
  return (
    <div className="card settings-room-card">
      <InfoTip topic="room-controls-bar"
        text="The room-wide controls that used to sit in the top bar: the brightness dimmer, the drift gradient that can drive the room's colour instead of the colour journey, and which fixtures the preview strip shows.">
        <div className="card-title">Room</div>
      </InfoTip>
      <BrightnessRow />
      <div className="settings-row">
        <InfoTip topic="drift-gradient"
          text="A two-dimensional gradient (time across, intensity up) that replaces the wheel-based colour journey while it is active. On songs without your own triggers the journey instead times itself to arrive on each analysed scene change, and analysed moments jump the colour too.">
          <span className="settings-row-label"><Icon name="layers" size={15} /> Drift gradient</span>
        </InfoTip>
        <DriftGradientPanel compact />
        <span className="settings-row-value" />
      </div>
      <RainbowLimitRow />
      <div className="settings-row settings-row-top">
        <InfoTip topic="device-preview"
          text="Which virtuals the top bar's preview strip shows a live swatch for. Four is a comfortable number for the collapsed strip; each chip saves itself.">
          <span className="settings-row-label"><Icon name="spark" size={15} /> Preview favourites</span>
        </InfoTip>
        <FavoritesPicker chips onClose={() => {}} />
        <span className="settings-row-value" />
      </div>
    </div>
  );
}
