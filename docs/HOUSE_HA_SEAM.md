# House lighting ↔ Home Assistant: the seam (phase 2)

The final wire shapes for River's side of the standard-lighting plan
(`/home/javi/fleet-spotfx/data/standard-lighting-plan/report.md` §5, River's
asks R1–R17). Phase 1 shipped `POST/PUT/GET /house/mode`; this document is
everything phase 2 adds. **Nothing here should go live in Home Assistant
until DJ confirms the matching Spectra build is deployed.**

**Base URL:** `http://192.168.40.145:8010/spectra/api` — Spectra's own port
(R11), so a SpotFX restart never cuts Home Assistant off. Every route is open
(no token), JSON in and out, and answers within milliseconds: none of them
waits on a fixture.

## The one rule

Every report is **recorded** whatever the room is doing (a TV Music report
while the room is released is still true later) and **acted on only while a
house mode drives the room**: a mode is set, Spectra holds the room, and
nothing (a preview, a camera run, a night run) has it on standby. Each
response says which: `"acting": false` plus a `note`/`reason` when it was
only recorded. With no modes in the library everything is inert.

**Phase 4 added the CUTOVER SWITCH** (`"enabled"` in the settings below,
OFF as shipped): while it is off nothing is acted on even with a mode set,
so the seeded modes change nothing in the room until River's cutover is
done and house lighting is switched on (the House tab's power button, or
`PUT /house/settings {"enabled": true}`). Everything is still recorded and
mapped, and `GET /house/mode` names the mode HA's word maps to.

## Home Assistant's lighting words (phase 4)

Every value `input_select.lighting_mode` can take reaches a mode:

| HA sends | Spectra mode |
|---|---|
| `Daytime` | Standard |
| `Party` | Standard (there is no Party mode; HA's own crystal script treats Party as Daytime) |
| `Evening` | Evening |
| `Dim` | Dim |
| `Bedtime` | Night light |
| `Travel` | Away |
| `Away` | Away |
| media `playing` | TV (by name) |
| media `paused` / `idle` | TV paused (by name) |

`unknown` / `unavailable` (while HA restarts) are deliberately unmapped: an
unmapped word keeps the current mode, so a restart never flips the house to
Standard in the middle of the night.

## Calls

| Call | Body | Answer | Replaces (R#) |
|---|---|---|---|
| `GET /house/heartbeat` | — | `{"state", "lighting_ok", "house_enabled", "mode", "clock_mode", "ha_value", "phase", "media", "tv_music", "tv_strip", "voice", "withheld", "owner", "uptime_s", "at_ms"}` | R17's fallback read |
| `PUT /house/mode` *(phase 1)* | `{"ha_mode": "<lighting_mode>", "source": "ha"}` | `status`: applied / unchanged / held_manual / unmapped | R1 |
| `PUT /house/tv-music` | `{"on": true \| false}` | `status`: recorded / unchanged; `tv_strip` | R6 |
| `PUT /house/media` | `{"source": "roku" \| "switch" \| "bluray" \| …, "state": "playing" \| "paused" \| "idle" \| "stopped"}` | `status`: applied / recorded / unchanged; `note` when no mode answers | R7 |
| `PUT /house/fixture/{id}` | `{"state": "on" \| "off"}` and/or `{"lent_to": "hyperion" \| null}` | `status`: recorded / unchanged; `override`, `applied`, `acting` | R6, R9 |
| `GET /house/fixtures` | — | every override, what was applied, corrections, rechecks | — |
| `POST /house/voice` | `{"state": "listening" \| "processing" \| "responding" \| "idle"}` | `status`: painted / cleared / skipped / unchanged | R8 |
| `POST /house/recheck` | `{"fixtures": ["sconce-kitchen-left", "sconce-kitchen-right"]}` | `status`: rechecking / skipped / nothing_to_recheck | R16 |
| `PUT /house/mains` *(phase 3)* | `{"fixtures": ["sconce-kitchen-left", "sconce-kitchen-right"], "on": false \| true}` | `status`: recorded / unchanged; `mains_off`; with `on: true` also the recheck's answer | R16 |
| `GET` / `PUT /house/settings` | partial settings object | the settings | — |

`PUT` and `POST` are the same call on every route above that lists `PUT`
(fixture, tv-music, media). A bad request is a 4xx naming the field: an
unknown fixture is 404, an invalid state 422.

### Heartbeat states (R17)

| `state` | meaning | `lighting_ok` |
|---|---|---|
| `driving` | a mode drives the room — leave every Spectra fixture alone | true |
| `standby` | a preview / camera run / night run holds the room for now | true |
| `idle` | Spectra holds the room but no mode drives it: none is set, or house lighting is switched off (`house_enabled: false`) | false |
| `on_paper` | Spectra holds the room with its engine not live (a quiet take) | false |
| `down` | the record says Spectra owns, but its light stack is not up | false |
| `released` | nobody drives the room | false |
| `not_owner` | the older SpotFX process owns, or a handover is in flight | false |

Suggested fallback (River's review, with its hysteresis): apply the old
time-of-day scenes when the heartbeat is unreachable, or `lighting_ok` is
false with `state` in `down` / `released` / `not_owner`, for 2 minutes AND
the WLEDs report `live: false`. Re-assert the mode (R1) when it comes back.

### TV strip (R6)

- `tv-music` OFF lends the TV strip (`settings.tv_strips`, default
  `["tv-backlight"]`) to Hyperion: Spectra sends it **nothing** (not even
  black) and posts `{"live": false}` once. The sconces on the same effect keep
  going. A media source on (`state` playing / paused / idle) lends it too.
- **The lend is honoured only while Hyperion is actually streaming to the
  strip, whenever the current mode's own plan also wants that strip
  powered off** (e.g. Away). Spectra re-checks the strip's own `live` flag
  every few seconds; while the mode wants it off and Hyperion is not
  confirmed streaming, Spectra switches the strip off instead of leaving
  it lit on nobody's signal (fixed 2026-10-05 — Away previously left a
  static dim amber on the TV backlight with Hyperion not running). A mode
  that does not want the strip off is unaffected: "TV Music default on,
  off only for Hyperion" still holds.
- It comes back when TV Music is ON **and** no media source is on: Spectra
  writes `{"on": true}` (power only — see Brightness below), then lets the
  stream resume.
- Recommended HA order: TV Music ON → call `tv-music {"on": true}`; TV Music
  OFF → call it with `false`. The data-line switch is physical either way;
  the call is what stops Spectra streaming to a strip nobody sees.

### Media / TV mode (R7)

- `playing` selects the mode answering to `"TV (<source>)"`, else `"TV"`.
  `paused` / `idle` select the one answering to `"TV paused (<source>)"`,
  else `"TV paused"`. `stopped` returns to the clock's mode.
- It is an overlay: the clock's word (R1) keeps being recorded underneath, so
  a clock change during a film shows when the film ends.
- A media word no mode answers to changes nothing about the mode (the strip
  is still lent). With no clock mode set, media never switches the house on.
- Switch and Blu-ray need new HA triggers (River's media-lights list); the
  call shape is the same for every source.

### Buttons (R9)

- `PUT /house/fixture/crystal {"state": "off"}` → no stream, `{"live":
  false}`, then `{"on": false}` (confirmed by read-back). `"on"` → `{"on":
  true}` (power only — see Brightness below) first, then the stream. `"state": null` hands the fixture
  back to the mode.
- Only a WLED can be switched off here; a Hue area answers 422 (its look is
  the mode's `hue` setting). A single bulb (Kitchen Infuse) is not
  addressable here yet — named, not built.
- Fixture ids: `crystal`, `tv-backlight`, `porch-rail`, `dining-table`,
  `sconce-kitchen-left`, `sconce-kitchen-right`, `hue-lights`, `dining-hues`
  (a fixture's name, e.g. `"Porch Rail"`, works too).

### Brightness is Home Assistant's (2026-10-12)

The Admiral's ruling (data/wled-bri-audit/report.md): **Spectra never writes
a WLED's master brightness** (`json/state` `bri`, nor a segment's, nor
`live.maxbri` / Force max brightness, which stays off). HA — or the WLED's
own web page — owns it, and it scales Spectra's stream: what shows is the
mode's `level` (pixel brightness) x the WLED's `bri`. This replaces R4's
"HA removes its WLED brightness writes" for **brightness** (HA's per-mode /
time-of-day WLED brightness goes back in HA); R4's **preset/effect** half
still stands — HA must not fire WLED presets or effects while Spectra
streams.

- Every power write is exactly `{"on": true}` or `{"on": false}` (plus a
  `{"live": false}` before an off), including every retry, so a WLED comes
  back at its own last brightness. The one WLED transport refuses any body
  carrying `bri` or `maxbri` (`fx/utils.py`, VENDOR #78).
- **Power follows the mode, never re-asserted (D2a).** Spectra switches a
  WLED's power only when the effective house mode changes (a TV source
  starting counts), a lend ends, an override is posted, or the mains come
  back. There is no periodic drift check: an HA "off" stands until the next
  mode change. A Spectra restart under the same mode writes nothing.
- Every WLED row's mode `level` / `music_level` was set to 100% at ship
  (`scripts/migrate_house_wled_levels_full.py`, D3a), so HA carries the
  brightness until the two are tuned together.
- Capture / calibration runs never raise a dim fixture (D1a): they warn
  ("raise it to 100% in Home Assistant") and measure as is; a night run
  records the same request for the morning read. If HA should raise the
  run's WLEDs for a night, do it on the `window_open` ping and restore on
  `window_close`.
- `own_brightness` / `owned_brightness` are retired: a `PUT
  /house/settings` naming either is refused (422) by name.

### Voice (R8)

- `POST /house/voice` paints the crystal and both sconces
  (`settings.voice_fixtures`) in HA's own colours — listening `#0000ff`,
  processing `#26a269`, responding `#613583`, all at 100% — and `idle` fades
  back over 1 s to what each fixture should show now.
- **Never waits**: the route does no I/O. Call it with a short timeout
  (e.g. 2 s) and `continue_on_error`; a missed call is a missed colour.
- Skipped per fixture when the Light Show holds it, it is lent or off, or the
  room is on standby; skipped entirely with no mode. A colour nobody cleared
  lets go after 120 s.

### Sconce mains (R16)

After HA switches `light.dimmer_kitchen_sconce` ON, call
`POST /house/recheck {"fixtures": ["sconce-kitchen-left",
"sconce-kitchen-right"]}`. Spectra re-finds them by hardware identity (a mains
cycle can change the DHCP address), re-inits a driver that never resolved,
and re-applies the mode's power (never a brightness) the moment they answer — looking
for up to 45 s. It returns at once; progress is in `GET /house/fixtures`
`rechecks`.

### Sconce mains OFF (phase 3, energy)

When HA switches `light.dimmer_kitchen_sconce` OFF, call
`PUT /house/mains {"fixtures": ["sconce-kitchen-left", "sconce-kitchen-right"],
"on": false}`. While a mode drives the room Spectra then sends them nothing
and stops searching for them (no 30 s re-checks, no network sweeps — a
fixture with no power cannot answer). When the mains go back ON, either call
`PUT /house/mains {... "on": true}` or keep the existing `POST /house/recheck`
— both clear the report and re-find the sconces at once. If an ON is ever
missed, Spectra knocks once every 10 minutes on the address each sconce last
had and picks it up when it answers. Spectra never switches the mains.
Recommended: send the mains state on every change of the dimmer, and at HA
start.

### Releases hand power back (phase 3)

Before its first power write to a WLED, Spectra records whether it was on;
when the room is RELEASED it writes `{"on": <before>}` back — only where
Spectra's own last switch left it different — and checks it, so a fixture
that was off before Spectra took the room is off after, even one River's
restore does not capture (the dining-table under-glow). No brightness is
ever handed back (Spectra never changed it). A restart keeps the picture and
hands nothing back.

### Restarts

While a mode drives the room a Spectra restart keeps the last picture: WLEDs
are not told to let go, the first frame after the restart carries the mode's
levels, and held Hue areas stay held. The sconces' own realtime timeout is
2.5 s; `scripts/set_wled_realtime_timeout.py --apply` raises it to 50 s
(an operator step on the fixtures, not run by Spectra).

## Settings (`GET/PUT /house/settings`)

```json
{"enabled": false,
 "hue_excluded_lights": [],
 "tv_strips": ["tv-backlight"],
 "voice_fixtures": ["crystal", "sconce-kitchen-left", "sconce-kitchen-right"],
 "voice_looks": {"listening": {"color": "#0000ff", "level": 100},
                 "processing": {"color": "#26a269", "level": 100},
                 "responding": {"color": "#613583", "level": 100}}}
```

A partial `PUT` keeps everything it does not name (one voice state's colour
can be changed alone). `enabled` is the cutover switch; `hue_excluded_lights`
names the Hue bulbs a mode never writes — empty by default, since every bulb
in his Spectra home is an ordinary house-mode bulb; it is the mechanism for
a future bulb he genuinely wants left to Home Assistant, never a standing
exclusion. A `PUT` that changes either applies at once and answers with
the `lighting` status too.
