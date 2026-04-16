"""
SpotFX — Application configuration.
All values can be overridden via .env file.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).parent
PROFILES_DIR = BASE_DIR / "storage" / "profiles"
AUDIO_SHAPES_DIR = BASE_DIR / "storage" / "audio_shapes"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Spotify ──────────────────────────────────────────────────────────────
    # Uses SPOTIPY_ prefix — matches spotipy's own env var names so that
    # SpotifyOAuth will also auto-detect them if needed.
    spotipy_client_id: str = ""
    spotipy_client_secret: str = ""
    spotipy_redirect_uri: str = "http://127.0.0.1:8000/api/spotify/callback"
    spotify_device_name: str = "Serenity"

    # ── LedFX ────────────────────────────────────────────────────────────────
    # Accept either a full base URL (LEDFX_BASE_URL) or separate host/port.
    # If ledfx_base_url is set directly it takes precedence.
    ledfx_base_url: str = ""        # e.g. http://127.0.0.1:8888
    ledfx_host: str = "http://localhost"
    ledfx_port: int = 8888

    @property
    def ledfx_url(self) -> str:
        """Resolved LedFX base URL — prefers explicit ledfx_base_url."""
        if self.ledfx_base_url:
            return self.ledfx_base_url.rstrip("/")
        return f"{self.ledfx_host}:{self.ledfx_port}"

    # ── Home Assistant ────────────────────────────────────────────────────────
    home_assistant_host: str = "http://homeassistant.local"
    home_assistant_token: str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # ── Latency / timing ──────────────────────────────────────────────────────
    # Milliseconds between audio playback and Spotify timestamp
    audio_latency_ms: int = 1000
    # Positive = trigger earlier, negative = trigger later
    ledfx_trigger_buffer_ms: int = 250
    # How many ms before the main scene action to fire pre-brightness / pre-transition
    pre_brightness_lead_ms: int = 200
    pre_transition_lead_ms: int = 200
    # Global default ramp duration for brightness/effect param changes; 0 = instant
    smooth_ramp_ms: int = 500

    # ── Polling intervals (ms) ─────────────────────────────────────────────────
    poll_interval_playing_ms: int = 5000
    poll_interval_paused_ms: int = 10000
    poll_interval_idle_ms: int = 30000   # idle > 10 min
    poll_interval_end_song_ms: int = 500  # max burst near end of song
    poll_end_song_burst_duration_ms: int = 3000  # how long to burst at end
    poll_start_burst_duration_ms: int = 4000  # burst after new song detected

    # ── UI / timeline ─────────────────────────────────────────────────────────
    timeline_update_interval_ms: int = 250
    builder_zoom_window_s: int = 20        # default zoom window in seconds
    builder_future_buffer_s: int = 5       # future audio shape lookahead

    # ── Audio shape display scales (persisted, adjustable in builder) ─────────
    shape_scale_overall: float = 1.0   # multiplies all layers before normalisation
    shape_scale_total: float = 1.0
    shape_scale_bass: float = 1.0
    shape_scale_mid: float = 1.0
    shape_scale_high: float = 1.0

    # ── Audio capture ─────────────────────────────────────────────────────────
    audio_sample_rate: int = 44100
    audio_chunk_size: int = 512
    # "default" uses system default; set to specific device name/index for Pi snapclient
    audio_input_device: str = "default"
    # 0 = unlimited; stop analysis after this many songs captured per session
    audio_analysis_max_songs: int = 0
    # Maximum allowed gap between consecutive audio samples; larger gaps discard the shape
    audio_max_gap_ms: int = 200

    # ── Audio shape display averages ──────────────────────────────────────────
    # Sliding-window average width for the smoothed overlay lines (ms)
    shape_average_window_ms: int = 500

    # ── Mark detection tuning ─────────────────────────────────────────────────
    # Quiet zone: rolling window for "recent average" energy comparison (seconds)
    quiet_baseline_window_s: int = 20
    # Quiet zone: minimum sustained quiet duration before a mark is placed (ms)
    quiet_min_duration_ms: int = 1500

    # ── Shape save threshold ───────────────────────────────────────────────────
    # Minimum fraction of song duration captured before shape is saved (0.0–1.0)
    audio_shape_min_capture_pct: float = 0.90

    # ── Auto-offset detection ─────────────────────────────────────────────────
    # Bass onset must exceed this multiple of the 1-second rolling mean
    auto_offset_spike_threshold: float = 6
    # Lookback window for computing the onset baseline (ms)
    auto_offset_lookback_ms: int = 500
    # Isolation check: preceding window that must be clear of comparable hits (ms)
    auto_offset_isolation_ms: int = 500
    # Spike must be this × the max of the isolation window to be considered isolated
    auto_offset_isolation_ratio: float = 2.0
    # Search window in stored shape around estimated song position (±ms)
    auto_offset_search_window_ms: int = 500
    # How far before the target (in frame time) we will accept an onset.
    # Prevents firing on beats that precede the target spike.
    # E.g. 300ms means we only fire if frame.timestamp_ms >= target_ms - 300.
    auto_offset_pre_gate_ms: int = 5000
    # Give up auto-offset detection after this many ms of listening
    auto_offset_timeout_ms: int = 60000
    # ── Auto-offset relaxed fallback (applied when strict pass finds nothing) ──
    # Multiplier applied to auto_offset_spike_threshold on the relaxed pass.
    # 0.7 → threshold drops from 2.5 to 1.75 — accepts subtler onsets.
    auto_offset_relax_threshold: float = 0.5
    # Multiplier applied to auto_offset_isolation_ratio on the relaxed pass.
    # 0.65 → isolation drops from 2.0 to 1.3 — allows less-isolated spikes.
    auto_offset_relax_isolation: float = 0.9
    # Multiplier applied to auto_offset_isolation_ms on the relaxed pass.
    # 0.5 → look-back window shrinks from 800ms to 400ms — fewer preceding beats disqualify a spike.
    auto_offset_relax_isolation_ms: float = 0.5
    # Live onset-ratio must be at least this fraction of the stored shape onset-ratio.
    # Filters false triggers whose onset strength doesn't match the target spike.
    # Volume-invariant: both sides are rms_low / local_baseline_mean.
    # Set to 0.0 to disable the check.
    auto_offset_onset_ratio_min: float = 0.80

    # ── Cross-correlation window selection ────────────────────────────────────
    xcorr_window_size_ms: int = 5000          # width of each analysis window (ms)
    xcorr_max_test_gap_ms: int = 15000        # max gap (prev window end → next window start)
    xcorr_starting_threshold: float = 0.15    # min difficulty to accept a window (except early mandate)
    xcorr_global_threshold: float = 0.50      # min Pearson r to accept a measurement
    xcorr_max_windows: int = 10               # cap on total windows per song
    xcorr_min_early_windows: int = 2          # mandate: at least N windows in first 20s
    xcorr_csv_logging: bool = True            # DIAGNOSTIC CSV — write per-play CSV log

    # ── Librosa / WAV retention ───────────────────────────────────────────────
    # Max number of WAV files to keep for librosa re-analysis (0 = unlimited)
    audio_wav_max_songs: int = 50

    # ── Librosa analysis tuning ───────────────────────────────────────────────
    # Section detection: novelty score threshold (0.0–1.0) a boundary must reach
    # to be counted as a new section. Higher = fewer, more confident splits
    # (e.g. 0.4). Lower = more splits, including subtle texture changes (e.g. 0.15).
    librosa_section_min_height: float = 0.2

    # Section detection: minimum number of beats that must separate two section
    # boundaries. Raise for coarser (longer) sections; lower for finer splits.
    librosa_section_min_beats: int = 8

    # Harmonic change detection: normalized chroma-distance threshold (0.0–1.0).
    # Higher = only large key/chord shifts reported (e.g. 0.6).
    # Lower = also catches subtle harmonic movement (e.g. 0.25).
    librosa_harmonic_min_height: float = 0.40

    # Harmonic change detection: minimum beats between two harmonic change points.
    # Increase to suppress rapid back-and-forth chord oscillations.
    librosa_harmonic_min_beats: int = 2

    # Full-spectrum onset detection: sensitivity delta above local baseline (librosa default ~0.07).
    # Lower = more onsets detected (catches subtle attacks); higher = only strong hits.
    librosa_onset_delta: float = 0.07

    # Bass onset detection: upper frequency cutoff in Hz for the low-freq onset envelope.
    # 250 Hz captures kick and sub-bass; raise toward 500 Hz to include upper bass/toms.
    librosa_bass_fmax: int = 250

    # Bass onset detection: sensitivity delta (same scale as librosa_onset_delta).
    # Often needs to be lower than full-spectrum delta because bass transients are slower.
    librosa_bass_onset_delta: float = 0.1

    # Downbeat phase: which beat index (0–3) in a bar corresponds to beat 1.
    # -1 = auto-detect from onset strength (picks the phase whose beats have the
    #      strongest average onset — downbeats tend to land on hard kick/chord hits).
    # 0–3 = force a fixed phase (0 = current behavior, 1 = shift one beat forward, etc.)
    librosa_downbeat_phase: int = -1

    # ── Flare fill energy thresholds ──────────────────────────────────────────
    # Above flare_rms_high: flares are placed at the minimum gap (scene_gap_ms).
    # Below flare_rms_low:  flares are placed at the maximum gap (flare_max_gap_beats).
    # Linear interpolation between the two.
    flare_rms_high: float = 0.8
    flare_rms_low:  float = 0.2

    # ── AI trigger generation ─────────────────────────────────────────────────
    anthropic_api_key: str = ""
    # "embedded" = free local KNN (auto-applies); "claude" = paid Claude API (saves suggestion set)
    auto_generate_mode: str = "embedded"
    # Show the AI Triggers page in the nav bar
    show_ai_triggers: bool = False
    # Show advanced controls across all pages
    show_advanced: bool = False

    # ── Last.fm (genre fallback / primary in LedFX mode) ─────────────────────
    lastfm_api_key: str = ""
    lastfm_username: str = ""

    # ── Song source ───────────────────────────────────────────────────────────
    # "spotify" — Spotify Web API polling (default)
    # "ledfx"   — LedFX song_detected WebSocket events (event-driven, faster)
    song_source: str = "spotify"


settings = Settings()
