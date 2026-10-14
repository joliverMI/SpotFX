/** Settings → "Scenes & drops" card (UI declutter plan §9, idea 1):
 * every set-and-forget tuning number that used to live behind the Scenes
 * button's own popover — transition times, lull darkness, strip phase
 * strength, breath-hold, drop timing, drop Shockwave + its energy floor,
 * Pulse flash floor, stale-drop rules, thematic transitions, music
 * devices, the transition placement rule, and the analysed-action rates.
 * The Scenes popover itself (RoomControlsBar.tsx) now keeps only Force
 * Scene (moved to the TOP, his edited ask), the scene-change tier, and
 * recent picks — this card is everything else.
 *
 * Owns its own draft/commit cycle against `RoomControlState`, same shape
 * as DriftGradientBar.tsx's — a separate page, so it cannot share
 * RoomControlsBar's local closure, and doesn't need to: every field here
 * already commits on blur/change exactly as it did in the popover. */
import { useEffect, useState } from 'react';
import HelpLink from '../help/HelpLink';
import PowerButton from '../components/PowerButton';
import { useRoomControls, useSaveRoomControls } from '../queries';
import type { RoomControlState } from '../types';

export default function ScenesDropsCard() {
  const { data: room } = useRoomControls();
  const save = useSaveRoomControls();
  const [local, setLocal] = useState<RoomControlState | null>(null);
  const [musicDeviceDraft, setMusicDeviceDraft] = useState<string | null>(null);

  // Adopt server state unless a save is still in flight — the same
  // "don't snap a field back mid-edit" rule RoomControlsBar's own
  // adoption effect documents.
  useEffect(() => {
    if (room && !save.isPending) setLocal(room);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [room, save.isPending]);

  if (!local) return <div className="card"><p className="empty-note">Loading…</p></div>;

  const commit = (next: RoomControlState) => { setLocal(next); save.mutate(next); };
  const field = <K extends keyof RoomControlState>(key: K) => ({
    value: local[key] as unknown as number,
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setLocal({ ...local, [key]: Number(e.target.value) } as RoomControlState),
    onBlur: () => commit(local),
  });

  return (
    <div className="card">
      <div className="card-title">Scenes &amp; drops</div>
      <div className="settings-field-grid">
        <div className="top-bar-group-field">
          <label>Transition</label>
          <input type="number" min={0} max={20000} step={100} {...field('global_transition_ms')} />
          <span className="settings-field-unit">ms (0 = use the two below)</span>
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            Transition @ low intensity
            <HelpLink topic="intensity-scaled-transitions" />
          </label>
          <input type="number" min={0} max={20000} step={50} {...field('scene_transition_ms_gentle')} />
          <span className="settings-field-unit">ms</span>
        </div>
        <div className="top-bar-group-field">
          <label>Transition @ high intensity</label>
          <input type="number" min={0} max={20000} step={50} {...field('scene_transition_ms_hard')} />
          <span className="settings-field-unit">ms</span>
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="The longest a lull stays fully dark on Black Hole, Squiggles, Pulse and Star. A lull is dark for half its length, never longer than this.">
            Lull darkness (max)
            <HelpLink topic="lull-dark-cap" />
          </label>
          <input type="number" min={0} max={30} step={0.5} {...field('lull_dark_max_s')} />
          <span className="settings-field-unit">s</span>
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="How strongly the strip effects answer a charge, lull and drop. Never adds white. 0 = off.">
            Strip phase strength
            <HelpLink topic="strip-phases" />
          </label>
          <input type="number" min={0} max={1.5} step={0.05} {...field('strip_phase_strength')} />
          <span className="settings-field-unit">×</span>
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="How long the lights go to true black right before a drop lands.">
            Breath-hold before drop
            <HelpLink topic="drop-breath-hold" />
          </label>
          <input type="number" min={0} max={3} step={0.1} {...field('lull_breath_hold_s')} />
          <span className="settings-field-unit">s</span>
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="How far off its mark every drop fires, in ms: negative = earlier, 0 = on the mark.">
            Drop timing
            <HelpLink topic="drop-timing-offset" />
          </label>
          <input type="number" min={-2000} max={2000} step={50} {...field('drop_timing_offset_ms')} />
          <span className="settings-field-unit">ms</span>
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <PowerButton
              on={local.drop_shock_enabled}
              onChange={(on) => commit({ ...local, drop_shock_enabled: on })}
              size={22}
              ariaLabel="Drop Shockwave"
            />
            Drop Shockwave
            <HelpLink topic="drop-shockwave-switches" />
          </label>
        </div>
        {local.drop_shock_enabled && (
          <div className="top-bar-group-field">
            <label title="The Shockwave only paints on a drop when the top bar's ⚡ Energy reading is at least this much. 0 = every drop.">
              Shockwave minimum energy (top-bar Energy)
            </label>
            <input type="number" min={0} max={1} step={0.05} {...field('drop_shock_min_energy')} />
          </div>
        )}
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="The Pulse singles' flash flare only fires when the top bar's ⚡ Energy reading is at least this much. 0 = every flash.">
            Pulse flash minimum energy (top-bar Energy)
            <HelpLink topic="pulse-flash-energy" />
          </label>
          <input type="number" min={0} max={1} step={0.05} {...field('pulse_flash_min_energy')} />
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <PowerButton
              on={local.drop_switch_enabled}
              onChange={(on) => commit({ ...local, drop_switch_enabled: on })}
              size={22}
              ariaLabel="Drop-led scene switch"
            />
            Drops change stale scenes
            <HelpLink topic="drop-led-switch" />
          </label>
        </div>
        {local.drop_switch_enabled && (
          <>
            <div className="top-bar-group-field">
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <PowerButton
                  on={local.drop_switch_after_previous_drop}
                  onChange={(on) => commit({ ...local, drop_switch_after_previous_drop: on })}
                  size={22}
                  ariaLabel="Stale after repeating the previous drop"
                />
                Stale after a repeated drop
              </label>
            </div>
            <div className="top-bar-group-field">
              <label title="Seconds beyond the scene's own minimum dwell after which it has overstayed.">
                Overstayed after dwell +
              </label>
              <input type="number" min={0} max={300} step={1} {...field('drop_switch_stale_margin_s')} />
              <span className="settings-field-unit">s</span>
            </div>
            <div className="top-bar-group-field">
              <label title="A scene that has carried this many drops in a row counts as stale. 0 turns the rule off.">
                Stale after drops in a row
              </label>
              <input type="number" min={0} max={16} step={1} {...field('drop_switch_drops_in_a_row')} />
            </div>
            <div className="top-bar-group-field">
              <label title="Leaving Fireworks for the Black Hole: the Black Hole cuts in this many seconds after the drop.">
                Fireworks → Black Hole after
              </label>
              <input type="number" min={0} max={10} step={0.1} {...field('drop_switch_swallow_delay_s')} />
              <span className="settings-field-unit">s</span>
              <HelpLink topic="fireworks-melds" />
            </div>
            <div className="top-bar-group-field">
              <label title="Leaving Fireworks for Fish, Orbits, Squiggles or STAR: the next scene cuts in on the next analysed flare at least this strong.">
                Fireworks: next big hit ≥
              </label>
              <input type="number" min={0} max={1} step={0.05} {...field('drop_switch_hit_threshold')} />
            </div>
          </>
        )}
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <PowerButton
              on={local.transition_programs_enabled}
              onChange={(on) => commit({ ...local, transition_programs_enabled: on })}
              size={22}
              ariaLabel="Thematic transitions"
            />
            Thematic transitions
            <HelpLink topic="transition-programs" />
          </label>
        </div>
        {local.transition_programs_enabled && (
          <>
            <div className="top-bar-group-field">
              <label title="How long a thematic transition takes.">Transition length</label>
              <input type="number" min={600} max={2500} step={100} {...field('transition_program_ms')} />
              <span className="settings-field-unit">ms</span>
            </div>
            <div className="top-bar-group-field">
              <label title="The Infall's last stretch, over which every piece's motion blends into the Black Hole's own.">
                Infall velocity blend
              </label>
              <input type="number" min={100} max={1500} step={50} {...field('transition_velocity_blend_ms')} />
              <span className="settings-field-unit">ms</span>
            </div>
            <div className="top-bar-group-field">
              <label title="Extra turns the pieces make spiralling into the Black Hole.">Infall spiral turns</label>
              <input type="number" min={0} max={3} step={0.05} {...field('transition_infall_spin')} />
            </div>
            <div className="top-bar-group-field">
              <label title="How many pieces the Black Hole's eruption sprays before they implode onto the incoming effect.">
                Eruption pieces
              </label>
              <input type="number" min={10} max={150} step={5} {...field('transition_eruption_count')} />
            </div>
            <div className="top-bar-group-field">
              <label title="How fast the eruption's pieces fly out.">Eruption speed</label>
              <input type="number" min={0.5} max={2} step={0.1} {...field('transition_eruption_speed')} />
              <span className="settings-field-unit">×</span>
            </div>
            <div className="top-bar-group-field">
              <label title="When Sauron or the Eye hands over, this fraction of the eye's lit cells explode as shards.">
                Flame Lick exploding fraction
              </label>
              <input type="number" min={0} max={1} step={0.05} {...field('transition_explode_frac')} />
            </div>
            <div className="top-bar-group-field">
              <label title="How hard the Black Hole bends the Fireworks' sparks into spiral arms.">Lensing pull</label>
              <input type="number" min={0.2} max={3} step={0.1} {...field('transition_lensing_pull')} />
              <span className="settings-field-unit">×</span>
            </div>
            <div className="top-bar-group-field">
              <label title="Turns the arriving pieces make as they gather onto the iris rim.">Ignition vortex turns</label>
              <input type="number" min={0} max={3} step={0.05} {...field('transition_ignition_turns')} />
            </div>
            <div className="top-bar-group-field">
              <label title="How wide a shattered fish's (or an unspooled chain's) dots spread.">
                Shoal Break / Unravel scatter
              </label>
              <input type="number" min={0} max={2} step={0.1} {...field('transition_scatter')} />
              <span className="settings-field-unit">×</span>
            </div>
            <div className="top-bar-group-field">
              <label title="When the Star hands over to another effect, its bands break into this many pieces.">
                Out of Star pieces
              </label>
              <input type="number" min={60} max={220} step={10} {...field('transition_bands_pieces')} />
            </div>
            <div className="top-bar-group-field">
              <label title="How long the Star's pieces keep turning on their rings before they unwind.">
                Out of Star ring hold
              </label>
              <input type="number" min={0} max={800} step={50} {...field('transition_bands_hold_ms')} />
              <span className="settings-field-unit">ms</span>
            </div>
            <div className="top-bar-group-field">
              <label title="How hard the Star's pieces unwind outward on their way to the Orbits.">Out of Star unwind</label>
              <input type="number" min={0} max={40} step={1} {...field('transition_unwind')} />
            </div>
          </>
        )}
        <div className="top-bar-group-field" style={{ alignItems: 'flex-start' }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            Music devices
            <HelpLink topic="music-device-gate" />
          </label>
          <input
            type="text"
            style={{ minWidth: 160 }}
            value={musicDeviceDraft ?? local.music_device_allowlist.join(', ')}
            onChange={(e) => setMusicDeviceDraft(e.target.value)}
            onBlur={() => {
              const parsed = (musicDeviceDraft ?? '').split(',').map((s) => s.trim()).filter(Boolean);
              setMusicDeviceDraft(null);
              if (parsed.length === 0) return;
              if (parsed.join('|') === local.music_device_allowlist.join('|')) return;
              commit({ ...local, music_device_allowlist: parsed });
            }}
            title="Comma-separated Spotify Connect device names."
          />
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <PowerButton
              on={local.midsong_snap_to_beat}
              onChange={(on) => commit({ ...local, midsong_snap_to_beat: on })}
              size={22}
              ariaLabel="Snap generated cues to beat"
            />
            Snap generated cues to beat
          </label>
          <HelpLink topic="transition-placement-rule" />
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            Transition edge window
            <HelpLink topic="transition-placement-rule" />
          </label>
          <input type="number" min={1} max={16} step={1} {...field('transition_window_beats')} />
          <span className="settings-field-unit">beats</span>
        </div>
        <div className="top-bar-group-field">
          <label>Transition edge sensitivity</label>
          <input type="number" min={0.2} max={1.5} step={0.05} {...field('transition_edge_sensitivity')} />
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            Total actions per minute
            <HelpLink topic="transition-placement-rule" />
            <HelpLink topic="analysed-flares" />
          </label>
          <input type="number" min={1} max={30} step={0.5} {...field('transitions_per_minute')} />
        </div>
        <div className="top-bar-group-field">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="An optional ceiling on how many analysed actions become real scene changes. 0 = off.">
            Scene changes per minute
            <HelpLink topic="scene-change-planner" />
          </label>
          <input type="number" min={0} max={30} step={0.5} {...field('scene_changes_per_minute')} />
          <span className="settings-field-unit">{local.scene_changes_per_minute > 0 ? 'ceiling' : 'off'}</span>
        </div>
        <div className="top-bar-group-field" style={{ fontSize: '0.85em', opacity: 0.75 }}>
          <span>Changes here re-plan each song's analysed cues the next time it plays — or ask Sonic to refresh them all.</span>
          <HelpLink topic="analysed-refresh" title="Re-analysing songs after a settings change" />
        </div>
      </div>
    </div>
  );
}
