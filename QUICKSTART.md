# SpotFX — Quick Start

## 1. Install dependencies
```bash
pip install -r requirements.txt
```

## 2. Configure credentials
```bash
cp .env.template .env
# Edit .env — add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
```

Get Spotify credentials at https://developer.spotify.com/dashboard
- Create an app
- Set redirect URI to: `http://localhost:8000/auth/callback`

## 3. Run the app
```bash
python main.py
```
First run will open a browser tab for Spotify OAuth. After approving,
the token is cached and the app runs automatically.

## 4. Open the UI
Navigate to `http://localhost:8000` from any machine on your local network.

## Development notes
- `main.py` uses `uvicorn --reload` in dev mode
- Profiles stored in `storage/profiles/`
- Audio shapes stored in `storage/audio_shapes/`
- All settings configurable at `http://localhost:8000/settings.html`
