/** Settings → "Room" card (UI declutter plan §3/§9, decided yes): the
 * room-wide Brightness dimmer, the two-dimensional drift gradient editor,
 * and the device-preview strip's Favourites picker — three direct
 * controls that used to sit in the top bar and now live here instead. A
 * UI move only: same writers (PUT /api/room-controls, the gradients
 * store, the favourites PUT) as before. */
import { useEffect, useState } from 'react';
import DriftGradientPanel from '../components/DriftGradientPanel';
import FavoritesPicker from '../components/FavoritesPicker';
import Icon from '../components/Icon';
import HelpLink from '../help/HelpLink';
import { useRoomControls, useSaveRoomControls } from '../queries';

function BrightnessControl() {
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
    <div className="top-bar-group-field">
      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
        <Icon name="bulb" size={15} title="Brightness" />
        Brightness
      </label>
      <input
        type="range" min={0} max={100} step={1}
        value={pct}
        onChange={(e) => setPct(Number(e.target.value))}
        onMouseUp={() => commit(pct)}
        onTouchEnd={() => commit(pct)}
        title="Brightness — dims/undims the whole room uniformly"
      />
      <span className="settings-field-unit">{pct}%</span>
    </div>
  );
}

export default function RoomCard() {
  return (
    <div className="card">
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Room <HelpLink topic="room-controls-bar" title="Room controls" />
      </div>
      <div className="settings-field-grid">
        <BrightnessControl />
        <DriftGradientPanel />
        <div>
          <div className="card-title" style={{ marginTop: 10 }}>Preview favourites</div>
          <FavoritesPicker onClose={() => {}} />
        </div>
      </div>
    </div>
  );
}
