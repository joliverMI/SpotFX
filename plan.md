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
