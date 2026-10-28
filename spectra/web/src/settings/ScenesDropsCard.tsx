/** Settings → "Scenes & drops" card (UI declutter plan §9, idea 1):
 * every set-and-forget tuning number that used to live behind the Scenes
 * button's own popover — transition times, lull darkness, strip phase
 * strength, breath-hold, drop timing, drop Shockwave + its energy floor,
 * Pulse flash floor, the drop colour change, stale-drop rules, thematic
 * transitions, music devices, the transition placement rule, and the
 * analysed-action rates.
 * The Scenes popover itself (RoomControlsBar.tsx) now keeps only Force
 * Scene (moved to the TOP, his edited ask), the scene-change tier, and
 * recent picks — this card is everything else.
 *
 * SINCE HIS Q4 ANSWER (2026-10-15) it opens as three compact grouped
 * rows — transition low/high, lull darkness/breath-hold, drop timing/
 * Shockwave — with everything else behind a "More" expander. No setting
 * was removed and none changed: the expander holds the same fields with
 * the same bindings, one disclosure deeper.
 *
 * Owns its own draft/commit cycle against `RoomControlState`, same shape
 * as DriftGradientPanel.tsx's — a separate page, so it cannot share
 * RoomControlsBar's local closure, and doesn't need to: every field here
 * already commits on blur/change exactly as it did in the popover. */
import { useEffect, useState } from 'react';
import InfoTip from '../components/InfoTip';
import PowerButton from '../components/PowerButton';
import { useRoomControls, useSaveRoomControls } from '../queries';
import type { RoomControlState } from '../types';

export default function ScenesDropsCard() {
  const { data: room } = useRoomControls();
  const save = useSaveRoomControls();
  const [local, setLocal] = useState<RoomControlState | null>(null);
  const [musicDeviceDraft, setMusicDeviceDraft] = useState<string | null>(null);
  // "More" is collapsed on open (his Q4 answer) and is plain local state:
  // which disclosure he last left open is not worth persisting, and a
  // remembered-open card would defeat the point of the grouping.
  const [more, setMore] = useState(false);

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
    <div className="card settings-drops-card">
      <div className="card-title">Scenes &amp; drops</div>
      {/* THE MOCKUP'S OWN COMPACT GROUPED ROWS (his Q4 answer,
        * 2026-10-15): the six numbers he actually reaches for, as three
        * labelled pairs, with every other setting behind "More". NOTHING
        * IS REMOVED OR CHANGED — the rest of the card is the same fields,
        * the same bindings and the same commit path, one disclosure
        * deeper. The card used to open as a flat grid of ~35 inputs, so
        * the two transition numbers he tunes most sat among stale-drop
        * rules and placement thresholds with no visual grouping at all. */}
      <div className="settings-group-rows">
        <div className="settings-group-row">
          <InfoTip topic="intensity-scaled-transitions"
            text="How long a scene crossfade takes at the quietest moments and at the loudest; the room interpolates between them.">
            <span className="settings-group-row-label">Transition</span>
          </InfoTip>
          <label className="settings-group-cell">
            <span>low</span>
            <input type="number" min={0} max={20000} step={50} {...field('scene_transition_ms_gentle')} />
            <span className="settings-field-unit">ms</span>
          </label>
          <label className="settings-group-cell">
            <span>high</span>
            <input type="number" min={0} max={20000} step={50} {...field('scene_transition_ms_hard')} />
            <span className="settings-field-unit">ms</span>
          </label>
        </div>
        <div className="settings-group-row">
          <InfoTip topic="lull-dark-cap"
            text="How long a lull stays fully dark (half its length, capped here), and how long the lights hold true black right before the drop lands.">
            <span className="settings-group-row-label">Lull</span>
          </InfoTip>
          <label className="settings-group-cell">
            <span>darkness</span>
            <input type="number" min={0} max={30} step={0.5} {...field('lull_dark_max_s')} />
            <span className="settings-field-unit">s</span>
          </label>
          <label className="settings-group-cell">
            <span>breath-hold</span>
            <input type="number" min={0} max={3} step={0.1} {...field('lull_breath_hold_s')} />
            <span className="settings-field-unit">s</span>
          </label>
        </div>
        <div className="settings-group-row">
          <InfoTip topic="drop-timing-offset"
            text="How far off its mark every drop fires (negative = earlier), and whether a drop paints the Shockwave.">
            <span className="settings-group-row-label">Drop</span>
          </InfoTip>
          <label className="settings-group-cell">
            <span>timing</span>
            <input type="number" min={-2000} max={2000} step={50} {...field('drop_timing_offset_ms')} />
            <span className="settings-field-unit">ms</span>
          </label>
          <span className="settings-group-cell">
            <span>shockwave</span>
            <PowerButton
              on={local.drop_shock_enabled}
              onChange={(on) => commit({ ...local, drop_shock_enabled: on })}
              size={22}
              ariaLabel="Drop Shockwave"
            />
          </span>
        </div>
      </div>
      <button type="button" className="settings-more-toggle"
        aria-expanded={more}
        onClick={() => setMore((v) => !v)}>
        {more ? 'Less' : 'More'} — every other scene &amp; drop setting
      </button>
      <div className="settings-field-grid" hidden={!more}>
        <div className="top-bar-group-field">
          <label>Transition</label>
          <input type="number" min={0} max={20000} step={100} {...field('global_transition_ms')} />
          <span className="settings-field-unit">ms (0 = use the two below)</span>
        </div>
        <div className="top-bar-group-field">
          <InfoTip topic="strip-phases" text="How strongly the strip effects answer a charge, lull and drop. Never adds white. 0 = off.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="How strongly the strip effects answer a charge, lull and drop. Never adds white. 0 = off.">Strip phase strength</label>
          </InfoTip>
          <input type="number" min={0} max={1.5} step={0.05} {...field('strip_phase_strength')} />
          <span className="settings-field-unit">×</span>
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
          <InfoTip topic="pulse-flash-energy" text="The Pulse singles' flash flare only fires when the top bar's ⚡ Energy reading is at least this much. 0 = every flash.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="The Pulse singles' flash flare only fires when the top bar's ⚡ Energy reading is at least this much. 0 = every flash.">Pulse flash minimum energy (top-bar Energy)</label>
          </InfoTip>
          <input type="number" min={0} max={1} step={0.05} {...field('pulse_flash_min_energy')} />
        </div>
        <div className="top-bar-group-field">
          <InfoTip topic="energy-lookahead" text="A drop or a scene change this many seconds or less before the next section reads that section's Energy, louder or quieter. 0 = always the present.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="A drop or a scene change this many seconds or less before the next section reads that section's Energy. 0 = always the present.">Energy look-ahead (s)</label>
          </InfoTip>
          <input type="number" min={0} max={4} step={0.5} {...field('energy_lookahead_s')} />
        </div>
        <div className="top-bar-group-field">
          <InfoTip topic="drop-colour-change" text="Every drop arrives in a new colour set, about opposite the one showing on the colour wheel — instantly, on the drop.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <PowerButton
              on={local.drop_colour_change}
              onChange={(on) => commit({ ...local, drop_colour_change: on })}
              size={22}
              ariaLabel="Drop colour change"
            />
            Drops change colour</label>
          </InfoTip>
        </div>
        {local.drop_colour_change && (
          <div className="top-bar-group-field">
            <label title="How far from exactly opposite (180° on the colour wheel) the drop's new set may sit: 30 = anywhere 150–210° away, the sets nearest 180° likeliest.">
              Drop colour spread ±
            </label>
            <input type="number" min={5} max={90} step={5} {...field('drop_colour_spread_deg')} />
            <span className="settings-field-unit">° from opposite</span>
          </div>
        )}
        <div className="top-bar-group-field">
          <InfoTip topic="drop-led-switch" text="A drop can BE the scene change: the cut lands on the drop (or early in the charge if it does not fit at the drop).">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <PowerButton
              on={local.drop_switch_enabled}
              onChange={(on) => commit({ ...local, drop_switch_enabled: on })}
              size={22}
              ariaLabel="Drop-led scene switch"
            />
            Drops change stale scenes</label>
          </InfoTip>
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
              <InfoTip topic="fireworks-melds"
                text="Leaving Fireworks for the Black Hole: the Black Hole cuts in this many seconds after the drop, and the drop's own debris is swallowed.">
                <span className="settings-field-unit">s</span>
              </InfoTip>
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
          <InfoTip topic="transition-programs" text="A registered Matrix effect switch runs its own program — an implosion, an eruption, a shoal break — instead of the plain crossfade.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <PowerButton
              on={local.transition_programs_enabled}
              onChange={(on) => commit({ ...local, transition_programs_enabled: on })}
              size={22}
              ariaLabel="Thematic transitions"
            />
            Thematic transitions</label>
          </InfoTip>
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
            <div className="top-bar-group-field">
              <InfoTip
                topic="shoaling-burst"
                text="Fish, Orbits, Squiggles and the Black Hole's eruption into them: the old object bursts into particles that keep moving as if nothing had happened, and the new one is born on them and gathers them back in. 0 px turns the burst off — and for Orbits into Fish brings back the old transition."
              >
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                  Shoaling burst
                </label>
              </InfoTip>
              <input type="number" min={0} max={20} step={0.5} {...field('transition_burst_px')} />
              <span className="settings-field-unit">px</span>
            </div>
            {local.transition_burst_px > 0 && (
              <>
                <div className="top-bar-group-field">
                  <label title="How fast the burst opens — the only moment a piece moves quickly against the object it is riding.">
                    Shoaling burst opens over
                  </label>
                  <input type="number" min={80} max={700} step={20} {...field('transition_burst_ms')} />
                  <span className="settings-field-unit">ms</span>
                </div>
                <div className="top-bar-group-field">
                  <label title="How far into the transition the pieces start gathering back into the new object.">
                    Shoaling gather begins at
                  </label>
                  <input type="number" min={0.1} max={0.9} step={0.05} {...field('transition_land_at')} />
                </div>
                <div className="top-bar-group-field">
                  <label title="How long a newly born object keeps the velocity it inherited before its own motion takes over.">
                    Shoaling inherited speed
                  </label>
                  <input type="number" min={60} max={800} step={10} {...field('transition_graft_ms')} />
                  <span className="settings-field-unit">ms</span>
                </div>
                <div className="top-bar-group-field">
                  <label title="3 fish become 3 orbits on the way in; the scene's own count wins again this long after the transition ends.">
                    Shoaling matched count holds
                  </label>
                  <input type="number" min={0} max={3000} step={50} {...field('transition_count_hold_ms')} />
                  <span className="settings-field-unit">ms</span>
                </div>
                <div className="top-bar-group-field">
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                    <PowerButton
                      on={local.transition_match_count}
                      onChange={(on) => commit({ ...local, transition_match_count: on })}
                      size={22}
                      ariaLabel="Match the shoaling count"
                    />
                    Match the count
                  </label>
                </div>
              </>
            )}
          </>
        )}
        <div className="top-bar-group-field" style={{ alignItems: 'flex-start' }}>
          <InfoTip topic="music-device-gate" text="The Spotify Connect devices whose playback may drive the lights. Music on anything else leaves the house lighting alone — no show frames, scene changes, flares or Light Show cues.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>Music devices</label>
          </InfoTip>
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
          <InfoTip topic="transition-placement-rule" text="Where a generated cue actually lands: the nearest rhythmic edge within the window, then the nearest downbeat.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <PowerButton
              on={local.midsong_snap_to_beat}
              onChange={(on) => commit({ ...local, midsong_snap_to_beat: on })}
              size={22}
              ariaLabel="Snap generated cues to beat"
            />
            Snap generated cues to beat</label>
          </InfoTip>
        </div>
        <div className="top-bar-group-field">
          <InfoTip topic="transition-placement-rule" text="How far either side of an analysed boundary the placement rule looks for a bass edge to land the cue on, in beats.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>Transition edge window</label>
          </InfoTip>
          <input type="number" min={1} max={16} step={1} {...field('transition_window_beats')} />
          <span className="settings-field-unit">beats</span>
        </div>
        <div className="top-bar-group-field">
          <label>Transition edge sensitivity</label>
          <input type="number" min={0.2} max={1.5} step={0.05} {...field('transition_edge_sensitivity')} />
        </div>
        <div className="top-bar-group-field">
          <InfoTip topic="analysed-flares"
            text="How many analysed actions a minute the planner places on a song: the strongest become real scene changes, the rest fire as analysed flares.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>Total actions per minute</label>
          </InfoTip>
          <input type="number" min={1} max={30} step={0.5} {...field('transitions_per_minute')} />
        </div>
        <div className="top-bar-group-field">
          <InfoTip topic="scene-change-planner" text="An optional ceiling on how many analysed actions become real scene changes. 0 = off.">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}
            title="An optional ceiling on how many analysed actions become real scene changes. 0 = off.">Scene changes per minute</label>
          </InfoTip>
          <input type="number" min={0} max={30} step={0.5} {...field('scene_changes_per_minute')} />
          <span className="settings-field-unit">{local.scene_changes_per_minute > 0 ? 'ceiling' : 'off'}</span>
        </div>
        <div className="top-bar-group-field" style={{ fontSize: '0.85em', opacity: 0.75 }}>
          <InfoTip topic="analysed-refresh"
            text="Changes here re-plan each song's analysed cues the next time it plays — or ask Sonic to refresh them all.">
            <span>Changes here re-plan each song's analysed cues the next time it plays — or ask Sonic to refresh them all.</span>
          </InfoTip>
        </div>
      </div>
    </div>
  );
}
