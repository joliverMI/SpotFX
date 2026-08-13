# SpotFX

Music-reactive lighting automation for [LedFX](https://www.ledfx.app/), powered by Spotify.

SpotFX listens to what you're playing on Spotify, captures and analyzes the audio in real time, and fires precisely-timed lighting events to LedFX — scene changes, color shifts, brightness ramps, and effect tweaks — all synced to the music.

## What It Does

- **Manual song profiles** — Place triggers at exact timestamps in a song, each firing a lighting event you've designed
- **Librosa-analyzed automation** — Automatically detects drops, quiet sections, energy buildups, beat patterns, and harmonic changes, then maps them to lighting events by genre
- **Analytical parameter tuning** — Train triggerless profiles on your manually-built songs, and SpotFX optimizes its detection thresholds to match your style across ~2,400 parameter combinations

## Prerequisites

- **Python 3.11+**
- **[LedFX](https://www.ledfx.app/)** — installed, running, and configured with your LED devices
- **Spotify Premium** — required for the Spotify API playback data
- **Spotify Developer App** — create one at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) to get your Client ID and Secret
- **Audio input** — SpotFX needs to hear the same audio that LedFX is reacting to (see [Audio Setup](#audio-setup))

## Quick Start

```bash
git clone https://github.com/joliverMI/SpotFX.git
cd SpotFX
python -m venv .venv
# Linux/macOS:
.venv/bin/pip install -r requirements.txt
# Windows:
.venv\Scripts\pip install -r requirements.txt
```

Copy the environment template and add your Spotify credentials:

```bash
cp .env.template .env
# Edit .env — fill in SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET
```

Start the server:

```bash
# Linux/macOS:
.venv/bin/python main.py
# Windows:
.venv\Scripts\python main.py
```

Open `http://127.0.0.1:8000` in your browser. You'll be prompted to authorize Spotify on first run.

Then go to **Settings** and configure:
- **Spotify device name** — must match exactly the device name shown in Spotify (e.g., your Spotify Connect speaker name)
- **LedFX host/port** — where LedFX is running (default: `localhost:8888`)

## LedFX Device Setup

SpotFX controls LedFX through its REST API. Your LedFX instance needs to be set up first with your LED devices and virtuals.

### Device Categories (Devices page)

SpotFX groups your LedFX virtuals into **device categories**. Each category defines which virtuals it contains and which LedFX effects they support. Go to the **Devices** page to manage categories.

**Import your virtuals:** Click "Import from LedFX" to fetch all virtuals from your LedFX instance and add them to categories. You can search/filter the list and a virtual can belong to multiple categories.

**Categories control:**
- Which virtuals get polled for state changes
- Which virtuals receive transition time updates
- How effect parameter actions are scoped (by category or specific virtual)

**Roles:** Categories can have a role that gives them special behavior:
- **Ambient** — virtuals in this role receive ambient color changes and complementary color flips. Assign this to your main solid-color virtual(s).

**Default categories** are created on first startup (Matrix, Strips, Singles). You should update these to match your own LedFX virtual names.

### Scenes and Events

Events in SpotFX reference LedFX scenes by their scene ID. Create your scenes in LedFX first, then reference them when building events in SpotFX. The event system is fully customizable — you define your own lighting vocabulary.

## User Guide

### 1. Create Events (Events page)

Events are reusable lighting actions. Each event defines what happens when a trigger fires.

**Event types:**
- **Single** — randomly picks one action from a list (variety across plays)
- **Sequence** — plays multiple actions in order with configurable timing between steps
- **Beat Sequence** — actions synced to detected beat grid (requires librosa analysis)

**Actions you can assign:**
- Switch LedFX scenes
- Set ambient colors (with complementary color support)
- Ramp brightness up/down
- Change transition timing
- Control specific effect parameters (scoped by category or virtual)
- Trigger other events (nesting)

Label your events (e.g., "drop", "chill", "blue") for easy filtering when building profiles.

### 2. Set Up Palettes (Profile Builder)

Palettes are color schemes you can use when building song profiles. Open the palette section in the Profile Builder to:

- Create named palettes with gradient colors
- Assign keyboard shortcuts (QWERTY mapping) for rapid trigger placement
- Duplicate and customize palettes per genre or mood

### 3. Capture Audio Shapes (Profile Builder)

Audio shapes are SpotFX's recording of a song's energy profile over time.

1. Toggle **Audio Analysis** on (in the Now Playing page header)
2. Play a song from start to finish on your target Spotify device
3. SpotFX records frequency-decomposed energy: bass, mids, and highs
4. The audio shape appears on the Profile Builder timeline
5. Click **Librosa** to run deeper analysis — extracts beats, onsets, sections, harmonic changes, and MFCC features

Audio shapes are saved as `.npz` files with `.json` sidecars in `storage/audio_shapes/`.

### 4. Build Song Profiles (Profile Builder)

Once you have an audio shape and librosa analysis:

1. **+ Trigger** — manually place a trigger at any timestamp
2. **+ Scenes** — auto-import librosa-detected scene change moments
3. **+ Flares** — auto-import sudden energy spikes
4. Assign events to each trigger, filter by labels
5. Drag triggers on the timeline or edit timestamps directly
6. Adjust the **audio shape offset** slider to calibrate playback sync
7. **Mark Verified** — flags this profile as human-reviewed (improves training data quality)

### 5. Create Triggerless Profiles (Triggerless page)

Triggerless profiles auto-generate triggers for songs that don't have manually-built profiles.

1. **Create a profile** — give it a name and assign genres (e.g., "reggaeton, trap latino")
2. **Set shared events** — song start, song end, scene fill, and flare events
3. **Choose a mode:**
   - **Simple mode** — fires scenes and flares at fixed intervals (every N seconds)
   - **Analyzed mode** — uses librosa features to detect drops, lulls, energy charges, quiet sections, and beat entries
4. **Add training songs** — select songs you've manually profiled and verified
5. **Click Train** — SpotFX runs a two-tier grid search over ~2,400 parameter combinations, optimizing detection thresholds against your verified triggers using weighted F1 scoring
6. Trained parameters auto-apply when songs with matching genres play

### 6. Settings

- **Spotify device name** — triggers only fire when playing on this device
- **LedFX host/port** — connection to your LedFX instance
- **Audio input device** — for audio shape capture
- **Timing knobs** — audio latency, trigger buffer, brightness/transition lead times, smooth ramp duration
- **Show advanced** — reveals shape display scales, capture thresholds, builder zoom, and more

## Audio Setup

SpotFX needs to capture the same audio stream that LedFX is reacting to. The setup depends on your platform:

**Windows:**
- Install a virtual audio cable (e.g., [VB-Audio Virtual Cable](https://vb-audio.com/Cable/))
- Route your audio player output through the virtual cable
- Set `AUDIO_INPUT_DEVICE` to the virtual cable's input name, or leave as `default` if it's your system default

**Linux (PulseAudio/PipeWire):**
- Use a monitor source to capture audio output:
  ```bash
  pactl set-default-source <your_monitor_source>
  ```
- Set `AUDIO_INPUT_DEVICE=pulse` in your `.env`
- If using Snapcast: create a null sink, point snapclient to it, and capture from its monitor

**macOS:**
- Use [BlackHole](https://github.com/ExistentialAudio/BlackHole) or similar virtual audio device

Configure the audio device in `.env` (`AUDIO_INPUT_DEVICE`) or in the Settings UI under advanced controls.

## Architecture

For anyone looking to fork and modify:

```
api/           External service clients (Spotify, LedFX, audio capture)
services/      Core logic (trigger engine, audio analysis, profile management, librosa)
routers/       FastAPI REST endpoints
models/        Pydantic data models
web/           React SPA (Vite build → web/dist, served at /app)
storage/       Runtime data (profiles, audio shapes, settings) — gitignored
```

**Key components:**

| Component | File | What it does |
|-----------|------|-------------|
| Trigger engine | `services/trigger_engine.py` | 50ms tick loop — fires events based on song progress and profile triggers |
| Audio shape service | `services/audio_shape_service.py` | Captures audio, saves .npz + WAV, schedules librosa analysis |
| Embedded trigger service | `services/embedded_trigger_service.py` | 8-stage analytical pipeline for auto-trigger generation |
| LedFX client | `api/ledfx_client.py` | REST client with command bus (8ms coalesce), latency measurement, smooth ramping |
| Spotify client | `api/spotify_client.py` | Polls Spotify playback state, manages OAuth, tracks device |
| Librosa service | `services/librosa_service.py` | Beat/onset/section/harmonic analysis on captured WAV files |

The frontend communicates via REST API + a WebSocket (`/ws`) for real-time state updates.

## Status & Contributing

This project is shared as-is for the LedFX community. **Forks are encouraged** — take it and make it your own.

The repo is not actively maintained. Issues and PRs may not be reviewed. If you build something cool with it, that's great.

Built with FastAPI, spotipy, sounddevice, librosa, and vanilla JavaScript.

## License

MIT — see [LICENSE](LICENSE)
