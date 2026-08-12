# SpotFX — Project Plan

> Living document. Updated as we go.

## App Overview
Music-reactive DJ lighting automation. Spotify polling → timestamp tracking → music event triggers → LedFX API.

## Stack
| Layer | Tech |
|---|---|
| Backend | Python 3.11+ / FastAPI / Uvicorn |
| Frontend | Vanilla JS (ES modules); migrate to React later |
| Spotify | Spotipy (Web API OAuth) |
| LedFX | httpx async REST client |
| Audio | sounddevice + numpy + scipy |
| Storage | JSON (profiles), .npz compressed (audio shapes) |

## Project Structure
```
SpotFX/
├── main.py                    FastAPI entry, background tasks
├── config.py                  Settings (pydantic-settings, .env)
├── api/
│   ├── spotify_client.py      OAuth + adaptive polling loop
│   ├── ledfx_client.py        Scene triggers + latency probe
│   ├── home_assistant.py      Pause/resume webhooks
│   └── audio_capture.py      sounddevice stream → AudioFrame
├── models/
│   ├── song_profile.py        SongProfile + MusicTrigger
│   ├── music_event.py         MusicEvent + actions
│   ├── audio_shape.py         AudioShapeMeta + MusicMark
│   └── state.py               Shared in-memory AppState
├── services/
│   ├── profile_manager.py     CRUD for profiles + events JSON
│   ├── trigger_engine.py      50ms tick loop; fires actions
│   ├── audio_analyzer.py      AudioShapeRecorder + MusicMarkDetector
│   └── websocket_manager.py   WS broadcast to browsers
├── routers/
│   ├── spotify.py             /api/spotify/*
│   ├── profiles.py            /api/profiles/*
│   ├── events.py              /api/events/*
│   ├── control.py             /api/control/* (pause/resume, scenes)
│   ├── settings_router.py     /api/settings
│   └── audio_shape_router.py  /api/audio-shape/*
├── storage/
│   ├── profiles/              Artist - Song.json
│   └── audio_shapes/          Artist - Song.npz + .json sidecar
└── frontend/
    ├── index.html             Primary / Now Playing
    ├── builder.html           Song Profile Builder
    ├── events.html            Music Event Builder
    ├── playlist.html          Playlist Absorb
    ├── settings.html          Settings
    ├── css/style.css
    └── js/app.js              Shared WS + utilities
```

## Build Phases

### ✅ Phase 1 — Skeleton (current)
- [x] All files scaffolded with function signatures & comments
- [x] FastAPI app with routing, WebSocket, lifespan
- [x] Pydantic models for all data types
- [x] Frontend pages (HTML/CSS/JS shells)
- [x] .env filled with real Spotify credentials

### Phase 2 — Auth + Basic Playback
- [x] Spotify OAuth flow working (spotipy cache)
- [x] Polling loop running, state broadcasting to WS
- [x] Primary page shows live track info + interpolated timeline
- [x] Pause button functional

### Phase 3 — Profile Storage + Builder UI
- [x] Save/load song profiles by URI
- [x] Profile builder: add/drag/edit triggers
- [x] Timeline markers colored by event color

### Phase 4 — Music Events + LedFX Triggers
- [ ] Music event CRUD in UI
- [ ] Trigger engine firing to LedFX
- [ ] Latency compensation working
- [ ] Trigger flash indicator on primary page

### Phase 5 — Audio Capture + Shape
- [ ] AudioCaptureStream recording per song
- [ ] .npz storage working
- [ ] Audio shape graph in builder
- [ ] MusicMarkDetector finding basic marks

### Phase 6 — Polish + Pi Migration
- [ ] Home Assistant webhook integration
- [ ] Playlist absorb
- [ ] Raspberry Pi audio device config tested
- [ ] Full end-to-end test

## Key Constants / Defaults
| Setting | Default |
|---|---|
| audio_latency_ms | 1000 |
| ledfx_trigger_buffer_ms | 250 (positive = earlier) |
| poll_playing | 5000 ms |
| poll_paused | 10000 ms |
| poll_idle (>10 min) | 30000 ms |
| poll_end_song burst | 500 ms for ≤3 s |
| timeline update | 250 ms (interpolated) |
| trigger engine tick | 50 ms |
| builder zoom default | 20 s |
| live future buffer | 5 s |

## 2026-07-29 — Intensity Chooser, Intensity Scaling, Scene-Group Color Override

### Intensity Chooser (`intensity_chooser` action)
New composite container: the firing trigger's intensity (0–1, after the song's
intensity scale) deterministically selects ONE lane; that lane's actions fire
concurrently. Lanes are ascending lower-bound thresholds; `lanes[0]` is the
default lane (fires below the first threshold, with no intensity context, or
when no other lanes exist). Ties resolve to the later lane. Picks are resolved
at plan time into `resolved_picks` (same map as random groups) so previews
match fires. Editor: `IntensityChooserBody` with a draggable-dot threshold
strip; deleting a lane merges its actions into the lane to its left.

### Intensity scaling (0–200%)
`SongProfile.intensity_scale` (0–2, None = unset) + `intensity_scale_source`
("user" | "auto" | "genre"). Resolution at fire time: song value → matching
training profile's `default_intensity_scale` → 1.0. Applied as a pure
multiplier wherever the intensity signal originates (plan-time gates/picks and
the fire-time `_FIRE_INTENSITY` ContextVar), clamped back to 0–1.
- Now Playing slider saves via `PATCH /api/profiles/by-uri` (source "user");
  `GET /api/profiles/intensity-scale?uri=` returns stored/effective/genre.
- Auto-normalization (`services/intensity_scale_service.py`): on first play of
  an unset song, rank it against the library on mean NPZ RMS (dB), tempo_bpm
  and onset density; map the mean percentile to 60–140% and stamp it as
  source "auto". Features cached in storage/cache/intensity_scale_features.json.
- Genre backfill NOT run — "user" vs inherited sources stay distinguishable.

### Scene-group color override (per trigger)
`MusicTrigger.color_group_override` (ColorSetCard id, kind "group"; None =
unchanged behavior). Carried by `_FIRE_COLOR_GROUP` ContextVar (set alongside
`_FIRE_INTENSITY` at both fire paths + plan-entry prep) and consulted first in
`_resolve_color_ref` for the `__scene_group__` sentinel; deleted/non-group
cards fall back to the designated group. Editor: "Colors" picker in the
builder's trigger dialog. NOTE: scene groups are SpotFX events (not parsed
from LedFX scene names — that idea is obsolete; no parser exists or is needed).

Smoke: `scripts/smoke_intensity_features.py` (24 checks).

### 2026-07-29 (later) — intensity scale v2 + backfill + UI feedback
Auto formula retuned on Javi's references (Dopamine 120%, Let It Be 50%,
Soy Peor ~100%): v1's mean-RMS/tempo/onset-density metrics were wrong (librosa
octave-doubles ballads; onset density anti-correlates with energy). v2:
`genre_to_song_scale(g) = 0.6g + 0.1` (genre slider = relative dial) ×
bass-rank factor (0.9–1.1 from mean rms_low dB, bass ratio, bass-onset
density), clamped 30–125% — only the user slider may exceed 125%. Fire-time
genre fallback + GET endpoint use the same mapping. Backfill applied
2026-07-29: 1069 profiles stamped (684 auto / 385 genre, 1 user kept),
backup storage/backups/profiles-preintensityscale-20260729-143626.
UI: NP shape-graph circles now use real trigger intensity (was hardcoded
0.5), chooser dots show threshold values, Events search/chip persist across
editor back-nav (sessionStorage).
