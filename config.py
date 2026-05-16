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
    # When the remaining time to song-end is less than this, drop to the
    # end-song fast poll rate. Wider than poll_end_song_burst_duration_ms
    # because mix-playlist transitions flip the URI well before the
    # song would have ended naturally.
    pretransition_burst_window_ms: int = 8000

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
    # Always-on PCM ring buffer depth (seconds). Held in memory continuously so
    # force-recapture mode can backfill song-start audio that played before the
    # URI-change handler realized a new song started. Memory cost at 44.1kHz
    # mono float32: ~5.3 MB for 30s.
    pcm_ring_buffer_seconds: int = 30

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
    audio_shape_min_capture_pct: float = 0.80

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
    xcorr_min_early_windows: int = 3          # mandate: at least N windows in first 20s
                                              # (round 6: bumped 2→3 to compensate for retiring
                                              # the rise-detector anchor — more early sweep
                                              # windows give the cluster gate enough data to
                                              # confirm or reject the song-start lock)
    xcorr_csv_logging: bool = False           # DIAGNOSTIC CSV — write per-play CSV log
                                              # (off by default — the per-band detail sweep
                                              # doubles xcorr CPU; flip on only when tuning)
    # Lock-and-stop: halt this play's xcorr loop once the engine has snapped
    # at high Q with several agreeing windows. The trailing windows would
    # only ratify the existing lock — burning worker-thread CPU on
    # diminishing returns. Tune `xcorr_lock_q` down for stricter locks (more
    # confident before halting) or `xcorr_lock_agree_windows` up to require
    # broader cross-window agreement.
    xcorr_lock_q: float = 0.70                # engine play-best-Q threshold to consider "locked"
                                              # 0.55 was too eager — a single high-r sweep
                                              # window (sometimes a beat-tile twin) could
                                              # snap the engine to the wrong offset and
                                              # then lock-and-stop halted xcorr before more
                                              # windows could correct the bad lock. 0.70
                                              # requires a confident match before halting.
    xcorr_lock_agree_windows: int = 3         # weighted confirmation_shifts within tol of best_offset
    # Mix-aware search range: total search window per side =
    #   xcorr_search_ms_base + max(0, captured_duration - polled_duration) + xcorr_cut_buffer_ms
    # The buffer absorbs small inaccuracies in capture vs. poll duration; the
    # delta term grows the search when a Spotify mix transition has trimmed the
    # song's reported duration. Per-Set-List override on Setlist.xcorr_cut_buffer_ms.
    xcorr_search_ms_base: int = 2000
    xcorr_cut_buffer_ms: int = 1500           # was 5000 — that bloated search to ±7s on
                                              # zero-cut songs, ~720 score_at calls per
                                              # fire even when r=0.15 (clear miss).
                                              # 1500 keeps plenty of slack while halving
                                              # the per-fire CPU on the common case.
    # When the search range exceeds this width (one-sided), tighten thresholds
    # to reject ambiguous matches: raise acceptance to >=0.55 r and require
    # top1-top2 r margin >= 0.08.
    xcorr_wide_threshold_ms: int = 4000
    xcorr_wide_min_r: float = 0.50  # was 0.55 — too strict, save-gate handles noise downstream
    xcorr_wide_top1_margin: float = 0.08
    # Above this single-window r, skip the margin (twin-peak) gate — strong
    # peaks shouldn't be discarded just because periodic music produces
    # near-twin coincidences.
    xcorr_high_confidence_r: float = 0.65  # was 0.70
    # Beat-twin rejection. When a per-window xcorr's best peak has a competitor
    # within `xcorr_beat_twin_margin` r at exactly ±1..4 beats (using librosa
    # tempo), the window is genuinely ambiguous between beat-aligned offsets
    # and we reject it. Mirrors the anchor's beat-twin penalty so both
    # calibrators agree on what counts as ambiguous in periodic music.
    xcorr_beat_twin_margin: float = 0.10
    # Single-window high-r escape hatch for the disk-save gate. When the cluster
    # gate (xcorr_save_min_confirm) doesn't fire because no second window
    # confirms, allow a save anyway if this *one* window has very high r AND
    # quality. Justified because the squared-signal correlator + beat-twin
    # gate make r ≥ xcorr_single_window_save_r false matches very rare.
    xcorr_single_window_save_r: float = 0.78
    xcorr_single_window_save_q: float = 0.70
    # Round 8: far-jump tier — when a proposed single-window save is more than
    # `xcorr_far_jump_ms` away from the sweep's current converged best offset,
    # require much stronger evidence before committing. Local refinements
    # stay easy; section-twin section-coincidences at +/-5s away from the
    # truth need to clear a high bar. Closes Pepas (+5200) / Contra (-2275)
    # / 7vFKcXQ (-1875) holes from round 7.
    xcorr_single_window_save_far_r: float = 0.90
    xcorr_single_window_save_far_q: float = 0.85
    # Round 9: dropped 2000 → 1000 to catch Bad Con Nicky's 1150ms shift that
    # slipped under the old gate. Pairs with the engine-snap stickiness gate
    # (engine_snap_far_jump_ms below) so disk and engine paths agree on what
    # "far" means.
    xcorr_far_jump_ms: int = 1000
    # Round 8: OLD-aware displacement floor. When OLD r ≥ xcorr_old_correlating_floor,
    # the loaded baseline is structurally agreeing with this window, so a NEW
    # candidate at a different offset must beat OLD by at least
    # xcorr_old_correlating_margin r-units before it's allowed to displace.
    # Section-twins in periodic music score r=0.85-0.95 against the wrong
    # alignment; without this floor they easily clear the 0.10 default
    # threshold and override correct locks (Pepas, Contra, 7vFKcXQ).
    xcorr_old_correlating_floor: float = 0.50
    xcorr_old_correlating_margin: float = 0.20
    # Anti-correlated baseline rescue threshold. When the stored offset shows
    # OLD r<0 across 3+ consecutive windows, the loaded baseline is provably
    # wrong for this play; lower the cluster save requirement so a single
    # sweep window plus the anchor's weight (or two weak sweep windows) can
    # fire the save and unstick the song.
    xcorr_save_min_confirm_anti: float = 1.5
    # Coarse-then-fine: coarse step (ms) and number of top candidates to refine.
    xcorr_coarse_step_ms: int = 100
    xcorr_top_k_refine: int = 3
    # Song-start sniff: fire a dedicated start-window xcorr after this much
    # accumulated live audio at song load.
    xcorr_start_sniff_ms: int = 5000

    # ── Early-feature anchor alignment ─────────────────────────────────────────
    # At capture time we scan the first `anchor_scan_window_ms` for steep RMS
    # rises and pick the most-unique candidates. At song start the live capture
    # is matched against those candidates to snap-align before the per-window
    # sweep runs.
    # Round 7: rise-detector anchor reinstated as a cold-start fallback. The
    # actual gate is per-Set-List `coarse_locked` (set on `setlist_offsets[id]`):
    # when False (no save has fired for this slot, OR `anti_corr_count >= 3`),
    # anchor runs as a safety net at song start. When True (a confirmed save
    # exists), sweep alone handles calibration. This global flag is a master
    # override; flip to False to disable anchor everywhere regardless of slot
    # state.
    anchor_enabled: bool = True
    anchor_scan_window_ms: int = 90000        # offline scan covers first 90s — wider pool
                                              # ensures candidates are spread across the song,
                                              # not clustered near the start where mix lag and
                                              # transitions can disqualify them all
    anchor_template_radius_ms: int = 1000     # ± slice for template (1s either side of rise)
    anchor_min_uniqueness: float = 0.15       # offline candidate accept threshold (best - second)
    anchor_min_rise_ratio: float = 1.4        # rise magnitude vs local baseline
    anchor_max_candidates: int = 8            # how many to store per song (paired with the
                                              # 90s scan, gives 8 well-spread chances for the
                                              # online matcher to find ≥2 agreeing candidates)
    anchor_search_radius_ms: int = 5000       # ± window during live match
    anchor_min_match_q: float = 0.30          # online match accept threshold (r × uniqueness)
    # Hard floor on the match's raw correlation. Beat-tile false matches in
    # periodic music can score r≈0.75–0.80 against the wrong beat; raising
    # this threshold rejects those and lets the per-window sweep handle them.
    # Confirmed-good matches (CANCIÓN, BAD CON NICKY in mixed playlist) score
    # r≈0.85–0.95, well above the floor.
    anchor_min_match_r: float = 0.75
    # Cross-candidate validation. Single-candidate high-r matches in periodic
    # music can be off by 1-4 beats. Requiring N candidates to agree on the
    # same offset within ±tolerance is much harder for beat-tile twins to
    # spoof: each candidate's twin sits at a different per-candidate shift,
    # so they don't all converge on the same wrong offset.
    anchor_min_agreeing_candidates: int = 2
    anchor_agree_tolerance_ms: int = 200
    # Skip the first `anchor_min_timestamp_ms` of every song in BOTH calibrators
    # (anchor candidate detection AND live-frame matching). Captured intros and
    # live intros frequently diverge due to mix variance / transition carryover,
    # so we don't trust the first few seconds for alignment.
    anchor_min_timestamp_ms: int = 5000

    # In-song engine drift cap. Once a song's baseline offset is loaded
    # (median of recent saves + perception trim), mid-play snaps in the
    # trigger engine are limited to within this many ms of that loaded value.
    # Bigger jumps are almost always beat-tile false matches. Disk writes are
    # NOT affected — large corrections still accumulate in history and shift
    # next play's median across plays. Set to 0 to disable.
    engine_in_song_drift_cap_ms: int = 2000
    # Drift cap bypass: snaps with quality at or above this threshold ignore
    # the cap. Beat-twin / ambiguous gates upstream make Q≥0.70 false matches
    # very rare, so a high-confidence correction is trusted to displace a
    # potentially-wrong loaded baseline.
    engine_drift_bypass_q: float = 0.70
    # Round 8: anti-correlated baseline drift-cap bypass requires this Q floor.
    # Previously, anti-corr unconditionally bypassed the cap; multiple plays
    # showed Q=0.55-0.79 anti-corr-bypass snaps overriding correct locks.
    # With this floor, only really-confident measurements (Q ≥ 0.85) are
    # trusted to far-jump even when the loaded baseline appears anti-correlated.
    engine_anti_corr_bypass_q: float = 0.85
    # Round 9: stickiness gate on the engine-snap path. A per-window measurement
    # whose offset is more than `engine_snap_far_jump_ms` away from the engine's
    # CURRENT offset (not the loaded baseline) is suppressed unless one of:
    # (a) a prior window in this play landed within ±xcorr_save_confirm_tol_ms
    #     of the new offset (cluster-style agreement),
    # (b) the new measurement clears `engine_snap_far_jump_q` on its own,
    # (c) cold-start with anti-corr baseline (loaded median provably wrong).
    # Closes the round-8 ping-pong observed on `3pm4Xtcs…` where four
    # mutually inconsistent offsets each beat the play-best in succession.
    engine_snap_far_jump_ms: int = 1000
    engine_snap_far_jump_q: float = 0.85

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
    # Genre Blending — when ON, suppress song-start triggers if the previous song
    # ended naturally and the new song shares any genre with it.
    genre_blending_enabled: bool = True

    # ── Last.fm (genre fallback / primary in LedFX mode) ─────────────────────
    lastfm_api_key: str = ""
    lastfm_username: str = ""

    # ── Song source ───────────────────────────────────────────────────────────
    # "spotify" — Spotify Web API polling (default)
    # "ledfx"   — LedFX song_detected WebSocket events (event-driven, faster)
    song_source: str = "spotify"


settings = Settings()
