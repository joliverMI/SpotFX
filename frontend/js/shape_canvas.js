/**
 * SpotFX — Shared audio shape canvas module.
 *
 * Usage:
 *   import { createShapeCanvas, computeAverages, MARK_COLOR, MARK_ABBR, SCALE_LABELS }
 *     from '/static/js/shape_canvas.js';
 *   const canvas = createShapeCanvas(canvasEl, resizeHandleEl);
 *   canvas.setData(shapeData, shapeMeta, avgWindowMs);
 *   canvas.setZoom(0, durationMs);
 *   canvas.setProfile(profile, events);
 *   canvas.draw();
 *   canvas.startLoop(25);
 */

// ── Exported constants ────────────────────────────────────────────────────────

export const MARK_COLOR = {
  bass_drop: '#e74c3c', bass_start: '#e67e22', bass_end: '#d35400',
  power_up: '#2ecc71', power_down: '#1abc9c',
  quiet: '#3498db', charging: '#f1c40f', tempo_change: '#9b59b6',
};

export const MARK_ABBR = {
  bass_drop: 'BD', bass_start: 'BS', bass_end: 'BE',
  power_up: 'PU', power_down: 'PD', quiet: 'Q', charging: 'CH', tempo_change: 'TC',
};

export const MARK_DESC = {
  bass_drop:    'Large sudden bass spike — the climactic hit following a buildup and a brief lull.',
  bass_start:   'Rhythmic bass pattern begins — sustained bass energy has entered the main beat.',
  bass_end:     'Rhythmic bass pattern ends — sustained absence of bass after an active section.',
  power_up:     'Overall energy surges to 2× the recent 5s average (chorus, drop, or sudden intensity).',
  power_down:   'Overall energy falls to 40% of the recent 5s average (breakdown, verse, or fade).',
  quiet:        'Sustained volume drop relative to the recent 20s window (intro silence, break, or outro).',
  charging:     'User-placed: buildup or tension phase — not auto-detected.',
  tempo_change: 'User-placed: tempo or key shift — not auto-detected.',
};

export const AVG_COLORS = {
  total: 'rgba(255,255,255,0.7)',
  bass:  'rgba(20,160,70,0.85)',
  mid:   'rgba(180,90,10,0.85)',
  high:  'rgba(25,100,180,0.85)',
};

export const SCALE_LABELS = { total: 'Total', bass: 'Bass', mid: 'Mids', high: 'Highs' };

// ── Exported pure function ────────────────────────────────────────────────────

/**
 * Compute past-only rolling-average RMS arrays.
 * @param {object} data  — { timestamps_ms, rms_total, rms_low, rms_mid, rms_high }
 * @param {number} windowMs
 * @returns {{ rms_total, rms_low, rms_mid, rms_high } | null}
 */
export function computeAverages(data, windowMs) {
  const ts = data.timestamps_ms;
  const n = ts.length;
  if (!n) return null;
  const keys = ['rms_total', 'rms_low', 'rms_mid', 'rms_high'];
  const result = {};
  for (const k of keys) {
    const src = data[k] || [];
    const out = new Array(n);
    let lo = 0, hi = -1, sum = 0;
    for (let i = 0; i < n; i++) {
      const wlo = ts[i] - windowMs, whi = ts[i];
      while (hi + 1 < n && ts[hi + 1] <= whi) { hi++; sum += src[hi] || 0; }
      while (lo <= hi && ts[lo] < wlo)         { sum -= src[lo] || 0; lo++; }
      out[i] = (hi >= lo) ? sum / (hi - lo + 1) : 0;
    }
    result[k] = out;
  }
  return result;
}

// ── Factory ───────────────────────────────────────────────────────────────────

/**
 * Create a reusable audio-shape canvas controller.
 *
 * Encapsulates all canvas state. Both builder.html and ai_triggers.html create
 * one instance each. Internal state is private to the closure.
 *
 * The filter and scale objects are exposed by reference so callers can mutate
 * them directly and then call draw():
 *   ctrl.filters.bass = !ctrl.filters.bass;
 *   ctrl.draw();
 *
 * @param {HTMLCanvasElement} canvasEl
 * @param {HTMLElement|null}  resizeHandleEl  — pass null if no resize handle needed
 * @returns {object} controller
 */
export function createShapeCanvas(canvasEl, resizeHandleEl = null) {

  // ── Private state ───────────────────────────────────────────────────────────
  let _shapeData    = null;
  let _shapeMeta    = null;
  let _shapeAvgData = null;
  let _liveData     = null;    // optional: in-progress xcorr capture for the Debug page,
                                // rendered downward from the midline. Same shape as
                                // _shapeData ({timestamps_ms, rms_total, rms_low, rms_mid, rms_high}).
  let _maxRms       = null;    // null = window-based; number = pinned raw max

  // Exposed by reference so callers can mutate directly
  const _filters    = { total: true, bass: true, mid: true, high: true, marks: true };
  const _avgFilters = { total: true, bass: true, mid: true, high: true };
  const _markFilters = {
    bass_drop: true, bass_start: true, bass_end: true,
    power_up: true, power_down: true, quiet: true,
    charging: true, tempo_change: true,
  };
  const _scales     = { total: 1.0, bass: 1.0, mid: 1.0, high: 1.0 };
  let _scaleOverall = 1.0;

  let _zoomStartMs  = 0;
  let _zoomEndMs    = 20000;
  let _playheadMs   = null;    // null = no playhead drawn; caller applies latency offset
  let _trimMs       = 0;       // perception trim — drawn as a secondary playhead when non-zero
  let _onTrimChange = null;    // (newTrimMs, isFinal:boolean) — called while dragging the orange playhead
  let _trimDragging = false;
  let _trimViewport = { startMs: 0, endMs: 1, W: 1 };  // updated each draw, used by drag handler

  // Custom markers override profile trigger markers (used by ai_triggers.html)
  // Each: { timestamp_ms, color, shape: 'triangle'|'diamond', event_color? }
  let _customMarkers = [];

  // Librosa analysis overlay
  let _librosaAnalysis = null;
  let _librosaOffsetMs = 0;
  const _librosaFilters = { beats: true, onsets: true, sections: true, harmonic: true, bass: true, snare: true, mfcc: true };
  let _mfccDistances = null;  // pre-computed MFCC timbral distances per beat (0-1 normalised)

  // Profile triggers (used by builder.html when no custom markers set)
  let _profile = null;
  let _events  = [];

  // Index of custom marker to highlight (glow + outline), null = none
  let _highlightedMarkerIdx = null;

  let _offsetMs        = 0;    // shape data timestamp offset in ms (shifts RMS + marks display)
  let _triggerOffsetMs = 0;    // preview offset for trigger markers (bulk shift before commit)

  let _calibrationTargetMs  = null;  // primary auto-offset target spike, null = none
  let _calibrationCandidates = [];   // [{ms, confidence, rank}, ...] up to 3

  // ── Advanced overlays (anchor candidates, live match, beat twins) ────────
  // Visibility is gated by `body.advanced-mode`. Pure additions; no impact on
  // the default render path.
  let _anchorCandidates = [];        // [{timestamp_ms, band, uniqueness, rise_magnitude}, ...]
  let _anchorTempoBpm   = null;      // tempo for ±1..4 beat twin lines
  let _liveMatch        = null;      // {offset_ms, r, q, candidate_idx, band}
  let _xcorrWindows     = [];        // [{win_start, win_end, new_offset_ms, new_r, new_quality, old_r, winner, failed}, ...]
  let _spikes           = [];        // [{spike_ms, win_start, win_end, strength}, ...] — mismatch-spike picks (Debug)
  const ANCHOR_BAND_COLOR = {
    rms_total: '#ffffff',
    rms_low:   '#3aa0ff',
    rms_high:  '#ffd84a',
    rms_mid:   '#3ddc87',
  };

  let _loopId       = null;
  let _onZoomChange = null;

  // ── Draw ─────────────────────────────────────────────────────────────────────
  const BEAT_STRIP_H  = 21;   // height of one heat-map strip (1px separator + 20px cells)
  const BASE_BEAT_STRIPS = 5;  // rms_total | rms_bass | onsets | bass onsets | harmonics
  // Snare strip only for librosa v3+ analyses (older songs have no snare_onsets)
  function _hasSnareData() { return !!(_librosaAnalysis?.snare_onsets?.length); }
  function _numStrips() {
    return BASE_BEAT_STRIPS
      + (_librosaFilters.snare && _hasSnareData() ? 1 : 0)
      + (_librosaFilters.mfcc && _mfccDistances ? 1 : 0);
  }
  function _totalStripH() { return BEAT_STRIP_H * _numStrips(); }

  function draw() {
    const ctx = canvasEl.getContext('2d');
    canvasEl.width  = canvasEl.offsetWidth;
    canvasEl.height = canvasEl.offsetHeight || 120;
    const W = canvasEl.width, H = canvasEl.height;
    ctx.clearRect(0, 0, W, H);

    // Reserve bottom strips for beat-energy heat-maps when librosa beats are present
    const hasBeatStrip = !!(_librosaAnalysis?.beats?.length);
    const mainH = hasBeatStrip ? H - _totalStripH() : H;

    if (!_shapeData?.timestamps_ms?.length) return;

    const startMs = _zoomStartMs, endMs = _zoomEndMs;
    const ts   = _shapeData.timestamps_ms;
    const rmsT = _shapeData.rms_total;
    const rmsL = _shapeData.rms_low;
    const rmsM = _shapeData.rms_mid || new Array(ts.length).fill(0);
    const rmsH = _shapeData.rms_high;

    const inWindow = [];
    for (let i = 0; i < ts.length; i++) {
      if (ts[i] >= startMs && ts[i] <= endMs) inWindow.push(i);
    }
    if (!inWindow.length) return;

    const timeToX = t => ((t - startMs) / (endMs - startMs)) * W;
    _trimViewport = { startMs, endMs, W };
    const rawMax  = _maxRms ?? Math.max(...inWindow.map(i => rmsT[i]), 1e-9);
    const maxRms  = rawMax * _scales.total * _scaleOverall;

    // When live xcorr-frame data is present (Debug page), squeeze the saved
    // shape into the upper half and draw the live overlay mirrored in the
    // lower half. The existing overlays (anchors, librosa beats, xcorr
    // windows, playhead) keep using full mainH and remain unchanged.
    const hasLive   = !!(_liveData?.timestamps_ms?.length);
    const savedBase = hasLive ? mainH / 2 : mainH;     // y at which saved bands sit (baseline)
    const rmsToY    = v => savedBase - (v / maxRms) * savedBase * 0.9;

    // Fill bands
    function drawFill(values, scale, fillStyle) {
      ctx.beginPath();
      ctx.moveTo(timeToX(ts[inWindow[0]]), savedBase);
      for (const i of inWindow) ctx.lineTo(timeToX(ts[i]), rmsToY(values[i] * scale * _scaleOverall));
      ctx.lineTo(timeToX(ts[inWindow[inWindow.length - 1]]), savedBase);
      ctx.closePath();
      ctx.fillStyle = fillStyle;
      ctx.fill();
    }
    if (_filters.total) drawFill(rmsT, _scales.total, 'rgba(150,150,150,0.4)');
    if (_filters.bass)  drawFill(rmsL, _scales.bass,  'rgba(46,204,113,0.45)');
    if (_filters.mid)   drawFill(rmsM, _scales.mid,   'rgba(230,126,34,0.4)');
    if (_filters.high)  drawFill(rmsH, _scales.high,  'rgba(52,152,219,0.35)');

    // Down-mirrored live overlay: same band colors, lower alpha, baseline at midline,
    // values increase downward. Uses its own per-band max (live capture levels can
    // differ substantially from the saved shape).
    if (hasLive) {
      const liveTs = _liveData.timestamps_ms;
      const liveT  = _liveData.rms_total || [];
      const liveL  = _liveData.rms_low   || [];
      const liveM  = _liveData.rms_mid   || [];
      const liveH  = _liveData.rms_high  || [];
      const liveInWindow = [];
      for (let i = 0; i < liveTs.length; i++) {
        if (liveTs[i] >= startMs && liveTs[i] <= endMs) liveInWindow.push(i);
      }
      // Divider line at the midline so the eye separates saved (up) from live (down).
      ctx.save();
      ctx.strokeStyle = 'rgba(255,255,255,0.18)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(0, savedBase);
      ctx.lineTo(W, savedBase);
      ctx.stroke();
      ctx.restore();
      if (liveInWindow.length) {
        const liveMax  = Math.max(...liveInWindow.map(i => liveT[i] || 0), maxRms, 1e-9);
        const lowerH   = mainH - savedBase;
        const liveYDown = v => savedBase + (v / liveMax) * lowerH * 0.9;
        function drawFillDown(values, fillStyle) {
          ctx.beginPath();
          ctx.moveTo(timeToX(liveTs[liveInWindow[0]]), savedBase);
          for (const i of liveInWindow) ctx.lineTo(timeToX(liveTs[i]), liveYDown(values[i] || 0));
          ctx.lineTo(timeToX(liveTs[liveInWindow[liveInWindow.length - 1]]), savedBase);
          ctx.closePath();
          ctx.fillStyle = fillStyle;
          ctx.fill();
        }
        if (_filters.total) drawFillDown(liveT, 'rgba(150,150,150,0.32)');
        if (_filters.bass)  drawFillDown(liveL, 'rgba(46,204,113,0.36)');
        if (_filters.mid)   drawFillDown(liveM, 'rgba(230,126,34,0.32)');
        if (_filters.high)  drawFillDown(liveH, 'rgba(52,152,219,0.30)');
      }
    }

    // Time diamonds — small at 15s, larger at 60s
    {
      const cy = mainH / 2;
      ctx.save();
      ctx.fillStyle = 'rgba(255,255,255,0.15)';
      const t15start = Math.ceil(startMs / 15000) * 15000;
      for (let t = t15start; t <= endMs; t += 15000) {
        if (t % 60000 === 0) continue; // drawn larger below
        const x = timeToX(t);
        ctx.beginPath();
        ctx.moveTo(x, cy - 5); ctx.lineTo(x + 3, cy);
        ctx.lineTo(x, cy + 5); ctx.lineTo(x - 3, cy);
        ctx.closePath(); ctx.fill();
      }
      ctx.fillStyle = 'rgba(255,255,255,0.28)';
      const t60start = Math.ceil(startMs / 60000) * 60000;
      for (let t = t60start; t <= endMs; t += 60000) {
        const x = timeToX(t);
        ctx.beginPath();
        ctx.moveTo(x, cy - 8); ctx.lineTo(x + 5, cy);
        ctx.lineTo(x, cy + 8); ctx.lineTo(x - 5, cy);
        ctx.closePath(); ctx.fill();
      }
      ctx.restore();
    }

    // Time-averaged overlay lines
    function drawAvgLine(values, scale, color) {
      if (!values?.length) return;
      ctx.beginPath();
      ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.globalAlpha = 0.85;
      let first = true;
      for (const i of inWindow) {
        const x = timeToX(ts[i]);
        const y = rmsToY((values[i] ?? 0) * scale * _scaleOverall);
        if (first) { ctx.moveTo(x, y); first = false; } else { ctx.lineTo(x, y); }
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    if (_shapeAvgData) {
      if (_avgFilters.total) drawAvgLine(_shapeAvgData.rms_total, _scales.total, AVG_COLORS.total);
      if (_avgFilters.bass)  drawAvgLine(_shapeAvgData.rms_low,   _scales.bass,  AVG_COLORS.bass);
      if (_avgFilters.mid)   drawAvgLine(_shapeAvgData.rms_mid,   _scales.mid,   AVG_COLORS.mid);
      if (_avgFilters.high)  drawAvgLine(_shapeAvgData.rms_high,  _scales.high,  AVG_COLORS.high);
    }

    // Librosa overlay
    if (_librosaAnalysis) {
      const la = _librosaAnalysis;
      const off = _librosaOffsetMs;

      // Section boundaries — full-height dashed blue lines
      if (_librosaFilters.sections && la.sections?.length) {
        ctx.save();
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1;
        ctx.font = '9px monospace';
        for (let si = 0; si < la.sections.length; si++) {
          const t = la.sections[si].start_ms + off;
          if (t < startMs || t > endMs) continue;
          const x = timeToX(t);
          ctx.globalAlpha = 0.45;
          ctx.strokeStyle = '#4488ff';
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, mainH); ctx.stroke();
          ctx.globalAlpha = 0.65;
          ctx.fillStyle = '#4488ff';
          ctx.fillText(`S${si}`, x + 2, mainH - 3);
        }
        ctx.setLineDash([]);
        ctx.restore();
      }

      // Harmonic changes — purple ticks from top; height + opacity scale with novelty
      if (_librosaFilters.harmonic && la.harmonic_changes?.length) {
        const tickMin = Math.round(mainH * 0.06);
        const tickMax = Math.round(mainH * 0.22);
        ctx.save();
        ctx.lineWidth = 1.5;
        for (const hc of la.harmonic_changes) {
          const t = hc.ms + off;
          if (t < startMs || t > endMs) continue;
          const x = timeToX(t);
          const tickH = tickMin + Math.round((tickMax - tickMin) * hc.novelty);
          ctx.globalAlpha = 0.45 + hc.novelty * 0.4;
          ctx.strokeStyle = '#cc66ff';
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, tickH); ctx.stroke();
        }
        ctx.restore();
      }

      // MFCC timbral distance — red-orange ticks from top; height + opacity scale with distance
      if (_librosaFilters.mfcc && _mfccDistances && la.beats?.length) {
        const tickMin = Math.round(mainH * 0.04);
        const tickMax = Math.round(mainH * 0.25);
        ctx.save();
        ctx.lineWidth = 2;
        for (let i = 0; i < la.beats.length; i++) {
          const d = _mfccDistances[i];
          if (d < 0.15) continue;  // skip low-distance beats to reduce clutter
          const t = la.beats[i].ms + off;
          if (t < startMs || t > endMs) continue;
          const x = timeToX(t);
          const tickH = tickMin + Math.round((tickMax - tickMin) * d);
          ctx.globalAlpha = 0.3 + d * 0.6;
          ctx.strokeStyle = '#ff6633';
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, tickH); ctx.stroke();
        }
        ctx.restore();
      }

      // Bass onsets — green ticks from top; height + opacity scale with strength
      if (_librosaFilters.bass && la.bass_onsets?.length) {
        const tickMin = Math.round(mainH * 0.03);
        const tickMax = Math.round(mainH * 0.16);
        ctx.save();
        ctx.lineWidth = 1.5;
        for (const bo of la.bass_onsets) {
          const t = bo.ms + off;
          if (t < startMs || t > endMs) continue;
          const x = timeToX(t);
          const tickH = tickMin + Math.round((tickMax - tickMin) * bo.strength);
          ctx.globalAlpha = 0.25 + bo.strength * 0.6;
          ctx.strokeStyle = '#44dd88';
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, tickH); ctx.stroke();
        }
        ctx.restore();
      }

      // Snare onsets — yellow ticks from top; height + opacity scale with strength
      if (_librosaFilters.snare && la.snare_onsets?.length) {
        const tickMin = Math.round(mainH * 0.03);
        const tickMax = Math.round(mainH * 0.16);
        ctx.save();
        ctx.lineWidth = 1.5;
        for (const so of la.snare_onsets) {
          const t = so.ms + off;
          if (t < startMs || t > endMs) continue;
          const x = timeToX(t);
          const tickH = tickMin + Math.round((tickMax - tickMin) * so.strength);
          ctx.globalAlpha = 0.25 + so.strength * 0.6;
          ctx.strokeStyle = '#ffdd33';
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, tickH); ctx.stroke();
        }
        ctx.restore();
      }

      // Onsets — orange ticks from top; height + opacity scale with strength
      if (_librosaFilters.onsets && la.onsets?.length) {
        const tickMin = Math.round(mainH * 0.04);
        const tickMax = Math.round(mainH * 0.20);
        ctx.save();
        ctx.lineWidth = 1;
        for (const on of la.onsets) {
          const t = on.ms + off;
          if (t < startMs || t > endMs) continue;
          const x = timeToX(t);
          const tickH = tickMin + Math.round((tickMax - tickMin) * on.strength);
          ctx.globalAlpha = 0.2 + on.strength * 0.55;
          ctx.strokeStyle = '#ff8800';
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, tickH); ctx.stroke();
        }
        ctx.restore();
      }

      // Beats — white ticks from bottom; downbeats taller
      if (_librosaFilters.beats && la.beats?.length) {
        ctx.save();
        ctx.lineWidth = 1;
        for (const b of la.beats) {
          const t = b.ms + off;
          if (t < startMs || t > endMs) continue;
          const x = timeToX(t);
          const tickH = b.is_downbeat ? Math.round(mainH * 0.18) : Math.round(mainH * 0.09);
          ctx.globalAlpha = b.is_downbeat ? 0.55 : 0.25;
          ctx.strokeStyle = '#ffffff';
          ctx.beginPath(); ctx.moveTo(x, mainH); ctx.lineTo(x, mainH - tickH); ctx.stroke();
        }
        ctx.restore();
      }
    }

    // Music marks
    if (_filters.marks && _shapeMeta?.music_marks) {
      ctx.font = '9px monospace';
      for (const mark of _shapeMeta.music_marks) {
        if (mark.timestamp_ms < startMs || mark.timestamp_ms > endMs) continue;
        if (!_markFilters[mark.mark_type]) continue;
        const x     = timeToX(mark.timestamp_ms);
        const color = MARK_COLOR[mark.mark_type] || '#fff';
        ctx.globalAlpha = 0.8;
        ctx.strokeStyle = color; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, mainH); ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.fillStyle = color;
        ctx.fillText(MARK_ABBR[mark.mark_type] || '?', x + 2, 18);
      }
    }

    // Trigger / suggestion markers
    // Custom markers (ai_triggers: suggestions) take priority over profile triggers.
    const triH = 8, triW = 7;
    if (_customMarkers.length) {
      for (let mi = 0; mi < _customMarkers.length; mi++) {
        const m = _customMarkers[mi];
        if (m.timestamp_ms < startMs || m.timestamp_ms > endMs) continue;
        const x = timeToX(m.timestamp_ms);
        const isHighlighted = mi === _highlightedMarkerIdx;

        // Event-color vertical scan-line
        if (m.event_color) {
          ctx.save();
          ctx.globalAlpha = 0.45;
          ctx.strokeStyle = m.event_color;
          ctx.lineWidth   = 1;
          ctx.beginPath(); ctx.moveTo(x, triH); ctx.lineTo(x, mainH); ctx.stroke();
          ctx.restore();
        }

        // Triangle or diamond
        ctx.save();
        if (isHighlighted) { ctx.shadowColor = '#fff'; ctx.shadowBlur = 6; }
        ctx.globalAlpha = 0.9;
        ctx.fillStyle   = m.color || '#888';
        ctx.beginPath();
        if (m.shape === 'diamond') {
          ctx.moveTo(x, 0);
          ctx.lineTo(x + triW / 2, triH / 2);
          ctx.lineTo(x, triH);
          ctx.lineTo(x - triW / 2, triH / 2);
        } else {
          ctx.moveTo(x - triW / 2, 0);
          ctx.lineTo(x + triW / 2, 0);
          ctx.lineTo(x, triH);
        }
        ctx.closePath();
        ctx.fill();
        if (isHighlighted) {
          ctx.shadowBlur  = 0;
          ctx.strokeStyle = 'rgba(255,255,255,0.7)';
          ctx.lineWidth   = 1;
          ctx.stroke();
        }
        ctx.restore();
      }
    } else if (_profile?.triggers?.length) {
      for (const t of _profile.triggers) {
        const tMs = t.timestamp_ms + _triggerOffsetMs;
        if (tMs < startMs || tMs > endMs) continue;
        const x  = timeToX(tMs);
        const ev = _events.find(e => e.id === t.event_id);
        const evColor = ev?.color || '#888';

        // Event-color vertical scan-line
        ctx.save();
        ctx.globalAlpha = 0.45;
        ctx.strokeStyle = evColor;
        ctx.lineWidth   = 1;
        ctx.beginPath(); ctx.moveTo(x, triH); ctx.lineTo(x, mainH); ctx.stroke();
        ctx.restore();

        ctx.globalAlpha = 0.9;
        ctx.fillStyle   = evColor;
        ctx.beginPath();
        ctx.moveTo(x - triW / 2, 0);
        ctx.lineTo(x + triW / 2, 0);
        ctx.lineTo(x, triH);
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    }

    // Calibration target markers — inverted triangles from bottom edge
    // Secondary candidates (rank 2 & 3) drawn first, faint and smaller
    for (const c of _calibrationCandidates) {
      if (c.rank === 1) continue;
      const ct = c.ms + _offsetMs;
      ctx.save();
      ctx.globalAlpha = 0.35;
      ctx.fillStyle = '#00bcd4';
      if (ct >= startMs && ct <= endMs) {
        // In viewport — draw normal inverted triangle
        const x = timeToX(ct);
        const sw = Math.round(triW * 0.75), sh = Math.round(triH * 0.75);
        ctx.beginPath();
        ctx.moveTo(x - sw / 2, mainH); ctx.lineTo(x + sw / 2, mainH); ctx.lineTo(x, mainH - sh);
        ctx.closePath(); ctx.fill();
      } else if (ct > endMs) {
        // Off-screen to the right — draw a small right-pointing arrow at the edge
        const ex = W - 4;
        const aw = 6, ah = 8;
        ctx.beginPath();
        ctx.moveTo(ex - aw, mainH - ah); ctx.lineTo(ex, mainH - ah / 2); ctx.lineTo(ex - aw, mainH);
        ctx.closePath(); ctx.fill();
      }
      ctx.restore();
    }
    // Primary target (rank 1) — full opacity + dashed vertical line
    if (_calibrationTargetMs !== null) {
      const ct = _calibrationTargetMs + _offsetMs;
      if (ct >= startMs && ct <= endMs) {
        const x = timeToX(ct);
        ctx.save();
        ctx.globalAlpha = 0.85;
        ctx.strokeStyle = '#00bcd4'; ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, mainH - triH); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#00bcd4';
        ctx.beginPath();
        ctx.moveTo(x - triW / 2, mainH); ctx.lineTo(x + triW / 2, mainH); ctx.lineTo(x, mainH - triH);
        ctx.closePath(); ctx.fill();
        ctx.restore();
      }
    }

    // Anchor overlays — only drawn when the user has enabled advanced mode.
    // Renders:
    //   • each anchor candidate at its stored timestamp (color = band, opacity
    //     scaled by uniqueness),
    //   • for the live-matched candidate, dashed faint lines at ±1..4 beats
    //     using the librosa tempo, so beat-tile traps are visible,
    //   • the live match position with its r/Q label.
    if (typeof document !== 'undefined' &&
        document.body.classList.contains('advanced-mode') &&
        _anchorCandidates.length) {
      ctx.save();
      for (let i = 0; i < _anchorCandidates.length; i++) {
        const c = _anchorCandidates[i];
        const tMs = (c.timestamp_ms || 0) + _offsetMs;
        if (tMs < startMs || tMs > endMs) continue;
        const x = timeToX(tMs);
        const u = Math.max(0, Math.min(1, +c.uniqueness || 0));
        ctx.globalAlpha = 0.25 + 0.55 * u;
        ctx.strokeStyle = ANCHOR_BAND_COLOR[c.band] || '#ffffff';
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 4]);
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, mainH); ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
        ctx.fillStyle = ANCHOR_BAND_COLOR[c.band] || '#ffffff';
        ctx.font = '9px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(`#${i + 1} u=${u.toFixed(2)}`, x + 3, 22 + i * 11);
      }

      if (_liveMatch && _anchorTempoBpm > 0) {
        const idx = +_liveMatch.candidate_idx;
        const beatMs = 60000 / +_anchorTempoBpm;
        const cand = _anchorCandidates[idx];
        if (cand && beatMs > 0) {
          const matchTime = (cand.timestamp_ms || 0) + (_liveMatch.offset_ms || 0) + _offsetMs;
          ctx.save();
          ctx.strokeStyle = ANCHOR_BAND_COLOR[cand.band] || '#ffffff';
          ctx.globalAlpha = 0.20;
          ctx.lineWidth = 1;
          ctx.setLineDash([1, 5]);
          for (const n of [1, 2, 3, 4]) {
            for (const sign of [-1, 1]) {
              const tw = matchTime + sign * n * beatMs;
              if (tw < startMs || tw > endMs) continue;
              const xt = timeToX(tw);
              ctx.beginPath(); ctx.moveTo(xt, 0); ctx.lineTo(xt, mainH); ctx.stroke();
            }
          }
          ctx.setLineDash([]);
          ctx.restore();
        }
      }

      if (_liveMatch) {
        const idx = +_liveMatch.candidate_idx;
        const cand = _anchorCandidates[idx];
        if (cand) {
          const matchTime = (cand.timestamp_ms || 0) + (_liveMatch.offset_ms || 0) + _offsetMs;
          if (matchTime >= startMs && matchTime <= endMs) {
            const x = timeToX(matchTime);
            ctx.save();
            ctx.strokeStyle = '#00ff88';
            ctx.lineWidth = 2;
            ctx.globalAlpha = 0.9;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, mainH); ctx.stroke();
            ctx.fillStyle = '#00ff88';
            ctx.font = '10px monospace';
            ctx.textAlign = 'left';
            const r = (+_liveMatch.r || 0).toFixed(2);
            const q = (+_liveMatch.q || 0).toFixed(2);
            const off = +_liveMatch.offset_ms || 0;
            ctx.fillText(`match ${off >= 0 ? '+' : ''}${off}ms r=${r} Q=${q}`, x + 4, mainH - 4);
            ctx.restore();
          }
        }
      }

      // Per-window xcorr overlay — one bracket per evaluated window. Color
      // encodes outcome: green = NEW won, blue = OLD won, red = window
      // failed (no shift cleared threshold). The bracket's vertical offset
      // shows `new_offset_ms` so visually-misaligned windows stand out.
      if (_xcorrWindows.length) {
        ctx.save();
        for (const w of _xcorrWindows) {
          const ws = (w.win_start || 0) + _offsetMs;
          const we = (w.win_end || 0) + _offsetMs;
          if (we < startMs || ws > endMs) continue;
          const xs = timeToX(Math.max(ws, startMs));
          const xe = timeToX(Math.min(we, endMs));
          let color = '#888';
          if (w.failed) color = '#e74c3c';
          else if (w.winner === 'new') color = '#00ff88';
          else if (w.winner === 'old') color = '#3aa0ff';
          const yTop = 36;
          ctx.globalAlpha = 0.7;
          ctx.strokeStyle = color;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(xs, yTop);
          ctx.lineTo(xs, yTop + 6);
          ctx.lineTo(xe, yTop + 6);
          ctx.lineTo(xe, yTop);
          ctx.stroke();
          if (!w.failed && w.new_offset_ms != null) {
            ctx.fillStyle = color;
            ctx.font = '9px monospace';
            ctx.textAlign = 'left';
            const r = w.new_r != null ? (+w.new_r).toFixed(2) : '—';
            ctx.fillText(`${w.new_offset_ms >= 0 ? '+' : ''}${w.new_offset_ms}ms r=${r}`, xs + 2, yTop + 17);
          }
        }
        ctx.globalAlpha = 1;
        ctx.restore();
      }
      ctx.restore();
    }

    // Mismatch-spike overlay (Debug) — when the monitor confirms a wrong lock
    // it picks a residual spike and a recovery window around it. Draw the
    // chosen window as a translucent magenta band and mark the spike itself
    // with a labelled vertical line, so the user can see WHERE the engine
    // decided to re-measure and WHY. Not gated by advanced-mode; the Debug
    // page relies on this even in its default view.
    if (_spikes.length) {
      ctx.save();
      for (const sp of _spikes) {
        const ws = (sp.win_start ?? 0) + _offsetMs;
        const we = (sp.win_end   ?? 0) + _offsetMs;
        const sm = (sp.spike_ms  ?? 0) + _offsetMs;
        // Window band (clipped to the viewport)
        if (we >= startMs && ws <= endMs) {
          const xs = timeToX(Math.max(ws, startMs));
          const xe = timeToX(Math.min(we, endMs));
          ctx.globalAlpha = 0.12;
          ctx.fillStyle = '#ff2d95';
          ctx.fillRect(xs, 0, Math.max(1, xe - xs), mainH);
          ctx.globalAlpha = 0.6;
          ctx.strokeStyle = '#ff2d95';
          ctx.lineWidth = 1;
          ctx.setLineDash([3, 3]);
          ctx.beginPath(); ctx.moveTo(xs, 0); ctx.lineTo(xs, mainH);
          ctx.moveTo(xe, 0); ctx.lineTo(xe, mainH); ctx.stroke();
          ctx.setLineDash([]);
        }
        // Spike center + label
        if (sm >= startMs && sm <= endMs) {
          const x = timeToX(sm);
          ctx.globalAlpha = 0.95;
          ctx.strokeStyle = '#ff2d95'; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, mainH); ctx.stroke();
          ctx.fillStyle = '#ff2d95';
          ctx.font = '10px monospace';
          ctx.textAlign = 'left';
          const s = sp.strength != null ? ` s=${(+sp.strength).toFixed(2)}` : '';
          ctx.fillText(`spike${s}`, x + 3, 22);
        }
      }
      ctx.globalAlpha = 1;
      ctx.restore();
    }

    // Playhead — caller applies audio_latency_ms; _offsetMs corrects capture timing.
    // When a perception trim is active, draw a second (orange) playhead at
    // _offsetMs + _trimMs so the user can see the effective firing position
    // alongside the xcorr-only baseline.
    if (_playheadMs !== null) {
      const xcorrMs = _playheadMs + _offsetMs;
      if (xcorrMs >= startMs && xcorrMs <= endMs) {
        const x = timeToX(xcorrMs);
        ctx.globalAlpha = 0.85;
        ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2;
        ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, mainH); ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      } else {
        // Off-screen: pin a directional marker to the nearest edge instead of
        // letting the playhead silently vanish. This happens whenever the zoom
        // window doesn't contain it — e.g. a follow anchor lagging the song, or
        // the moment between switching Manual→Follow before the window snaps.
        // The arrowhead points toward the true (off-screen) position.
        const offRight = xcorrMs > endMs;
        const dir  = offRight ? 1 : -1;
        const tipX = offRight ? W - 1 : 1;
        ctx.save();
        ctx.globalAlpha = 0.5;
        ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2;
        ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(tipX, 0); ctx.lineTo(tipX, mainH); ctx.stroke();
        ctx.setLineDash([]);
        // Arrowhead at vertical center, base inset from the edge, tip on it.
        const ay = mainH / 2, aw = 8, ah = 6;
        ctx.globalAlpha = 0.9;
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.moveTo(tipX, ay);
        ctx.lineTo(tipX - dir * aw, ay - ah);
        ctx.lineTo(tipX - dir * aw, ay + ah);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }
      if (_trimMs) {
        const trimDisplayMs = _playheadMs + _offsetMs + _trimMs;
        if (trimDisplayMs >= startMs && trimDisplayMs <= endMs) {
          const x = timeToX(trimDisplayMs);
          ctx.globalAlpha = 0.95;
          ctx.strokeStyle = '#ff9800'; ctx.lineWidth = 2;
          ctx.setLineDash([2, 2]);
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, mainH); ctx.stroke();
          ctx.setLineDash([]);
          // Small label above the line so the user knows what it is
          ctx.fillStyle = '#ff9800';
          ctx.font = '10px monospace';
          ctx.textAlign = 'left';
          const label = `trim ${_trimMs > 0 ? '+' : ''}${_trimMs}ms`;
          ctx.fillText(label, x + 3, 11);
          ctx.globalAlpha = 1;
        }
      }
    }

    // Beat-energy heat-map strip — always drawn when librosa beats are present
    if (hasBeatStrip) {
      const la  = _librosaAnalysis;
      const off = _librosaOffsetMs;
      const minCellH = 5;
      const stripH   = BEAT_STRIP_H - 1;  // usable px per strip (1px separator)

      // Strip definitions: [getValue(beat), baseColor, downbeatColor]
      const STRIPS = [
        { get: b => b.rms_total        ?? 0, color: '#ffffff', dbColor: '#aaccff' },
        { get: b => b.rms_bass         ?? 0, color: '#00ccdd', dbColor: '#66eeff' },
        { get: b => b.onset_score      ?? 0, color: '#ff8800', dbColor: '#ffbb44' },
        { get: b => b.bass_onset_score ?? 0, color: '#44dd88', dbColor: '#88ffbb' },
        { get: b => b.harmonic_score   ?? 0, color: '#cc66ff', dbColor: '#ee99ff' },
      ];
      // Conditionally add snare strip (librosa v3+ analyses only)
      if (_librosaFilters.snare && _hasSnareData()) {
        STRIPS.push({ get: b => b.snare_onset_score ?? 0, color: '#ffdd33', dbColor: '#ffee88' });
      }
      // Conditionally add MFCC distance strip
      if (_librosaFilters.mfcc) {
        if (_mfccDistances) {
          const _md = _mfccDistances;
          STRIPS.push({ get: (_b, idx) => _md[idx] ?? 0, color: '#ff6633', dbColor: '#ff9966' });
        } else {
          // No MFCC data: show a flat placeholder so the row is visible
          STRIPS.push({ get: () => 0.5, color: '#ff6633', dbColor: '#ff9966' });
          console.warn('MFCC filter on but no _mfccDistances — song may lack MFCC data');
        }
      }

      ctx.save();
      ctx.lineWidth = 0;

      for (let s = 0; s < STRIPS.length; s++) {
        const baseY = mainH + s * BEAT_STRIP_H;
        const stripY = baseY + 1;

        // Separator line
        ctx.globalAlpha = 0.25;
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(0, baseY); ctx.lineTo(W, baseY); ctx.stroke();
        ctx.lineWidth = 0;

        // Background
        ctx.globalAlpha = 0.2;
        ctx.fillStyle = '#000000';
        ctx.fillRect(0, stripY, W, stripH);

        const { get, color, dbColor } = STRIPS[s];

        for (let i = 0; i < la.beats.length; i++) {
          const b  = la.beats[i];
          const t  = b.ms + off;
          const x0 = timeToX(t);
          const x1 = i + 1 < la.beats.length
            ? timeToX(la.beats[i + 1].ms + off)
            : x0 + (W / la.beats.length);
          if (x1 < 0 || x0 > W) continue;
          const cx0 = Math.max(0, x0);
          const cx1 = Math.min(W, x1 - 1);
          if (cx1 <= cx0) continue;
          const val   = get(b, i);
          const cellH = Math.round(minCellH + val * (stripH - minCellH));
          ctx.globalAlpha = 0.15 + val * 0.75;
          ctx.fillStyle   = b.is_downbeat ? dbColor : color;
          ctx.fillRect(cx0, stripY, cx1 - cx0, cellH);
        }
      }
      ctx.restore();
    }
  }

  // ── Resize handle ─────────────────────────────────────────────────────────────
  function wireResizeHandle() {
    if (!resizeHandleEl) return;
    let _resizing = false, _startY = 0, _startH = 0;
    resizeHandleEl.addEventListener('mousedown', e => {
      _resizing = true;
      _startY   = e.clientY;
      _startH   = canvasEl.offsetHeight;
      e.preventDefault();
    });
    window.addEventListener('mousemove', e => {
      if (!_resizing) return;
      canvasEl.style.height = Math.max(40, Math.min(400, _startH + (e.clientY - _startY))) + 'px';
      draw();
    });
    window.addEventListener('mouseup', () => { _resizing = false; });
  }

  // ── Perception-trim playhead drag ─────────────────────────────────────────
  // Click within ±6px of the orange (trim) playhead and drag horizontally;
  // each move updates _trimMs and notifies the caller. mouseup fires a final
  // notification so the caller can persist.
  function _xToTime(x) {
    const v = _trimViewport;
    return v.startMs + (x / v.W) * (v.endMs - v.startMs);
  }
  function _trimPlayheadX() {
    if (_playheadMs == null) return null;
    const xcorrMs = _playheadMs + _offsetMs;
    const v = _trimViewport;
    return ((xcorrMs + _trimMs) - v.startMs) / (v.endMs - v.startMs) * v.W;
  }
  canvasEl.addEventListener('mousedown', e => {
    if (e.button !== 0) return;   // left-click only — middle-click is pan
    if (!_onTrimChange || _playheadMs == null) return;
    const rect = canvasEl.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (canvasEl.width / rect.width);
    const tx = _trimPlayheadX();
    if (tx == null) return;
    if (Math.abs(x - tx) > 8) return;
    _trimDragging = true;
    e.preventDefault();
  });
  canvasEl.addEventListener('mousemove', e => {
    if (_trimDragging || !_onTrimChange || _playheadMs == null) return;
    const rect = canvasEl.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (canvasEl.width / rect.width);
    const tx = _trimPlayheadX();
    canvasEl.style.cursor = (tx != null && Math.abs(x - tx) <= 8) ? 'ew-resize' : '';
  });
  window.addEventListener('mousemove', e => {
    if (!_trimDragging || !_onTrimChange || _playheadMs == null) return;
    const rect = canvasEl.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (canvasEl.width / rect.width);
    const t = _xToTime(x);
    const xcorrMs = _playheadMs + _offsetMs;
    const newTrim = Math.round(t - xcorrMs);
    _trimMs = newTrim;
    draw();
    _onTrimChange(newTrim, false);
  });
  window.addEventListener('mouseup', () => {
    if (!_trimDragging) return;
    _trimDragging = false;
    if (_onTrimChange) _onTrimChange(_trimMs, true);
  });

  // ── Zoom handle drag (simple non-follow-mode) ─────────────────────────────────
  /**
   * Wire zoom handle drag for a simple timeline bar.
   * Builder.html keeps its own more complex zoom wiring (follow-mode);
   * this is suitable for ai_triggers.html.
   *
   * @param {HTMLElement}  barEl           — the full-width bar element
   * @param {HTMLElement}  startHandleEl   — left zoom handle
   * @param {HTMLElement}  endHandleEl     — right zoom handle
   * @param {() => number} getDurationMs   — function returning song duration in ms
   * @param {HTMLElement}  [centerHandleEl] — optional center handle to pan whole window
   */
  function wireZoomHandles(barEl, startHandleEl, endHandleEl, getDurationMs, centerHandleEl) {
    let _side = null, _rect = null;
    let _panStartX = null, _panStartZoomStart = null, _panStartZoomEnd = null;

    startHandleEl.addEventListener('mousedown', e => {
      _side = 'start'; _rect = barEl.getBoundingClientRect();
      e.preventDefault(); e.stopPropagation();
    });
    endHandleEl.addEventListener('mousedown', e => {
      _side = 'end'; _rect = barEl.getBoundingClientRect();
      e.preventDefault(); e.stopPropagation();
    });
    if (centerHandleEl) {
      centerHandleEl.addEventListener('mousedown', e => {
        _side = 'center';
        _rect = barEl.getBoundingClientRect();
        _panStartX         = e.clientX;
        _panStartZoomStart = _zoomStartMs;
        _panStartZoomEnd   = _zoomEndMs;
        e.preventDefault(); e.stopPropagation();
      });
    }
    window.addEventListener('mousemove', e => {
      if (!_side) return;
      const minWin = 2000;
      const dur = getDurationMs();
      if (_side === 'center') {
        const dxPct  = (e.clientX - _panStartX) / _rect.width;
        const winMs  = _panStartZoomEnd - _panStartZoomStart;
        const dxMs   = dxPct * dur;
        const newStart = Math.max(0, Math.min(dur - winMs, _panStartZoomStart + dxMs));
        _zoomStartMs = newStart;
        _zoomEndMs   = newStart + winMs;
      } else {
        const pct = Math.max(0, Math.min(1, (e.clientX - _rect.left) / _rect.width));
        const ms  = pct * dur;
        if (_side === 'start') {
          _zoomStartMs = Math.max(0, Math.min(ms, _zoomEndMs - minWin));
        } else {
          _zoomEndMs = Math.min(dur, Math.max(ms, _zoomStartMs + minWin));
        }
      }
      _onZoomChange?.(_zoomStartMs, _zoomEndMs);
      draw();
    });
    window.addEventListener('mouseup', () => {
      _side = null; _panStartX = null;
    });
  }

  // ── Middle-mouse drag-to-pan ──────────────────────────────────────────────
  /**
   * Pan the zoom window by dragging with the middle mouse button on the
   * canvas. Slides the window preserving its width, clamped to
   * [0, duration − window]. Fires _onZoomChange on every move — same
   * semantics as wireZoomHandles drags.
   *
   * @param {() => number} getDurationMs — function returning song duration in ms
   */
  function wireMiddlePan(getDurationMs) {
    let _pan = null;   // { startX, s, e }
    canvasEl.addEventListener('mousedown', e => {
      if (e.button !== 1) return;
      e.preventDefault();                       // suppress browser autoscroll
      _pan = { startX: e.clientX, s: _zoomStartMs, e: _zoomEndMs };
    });
    canvasEl.addEventListener('auxclick', e => { if (e.button === 1) e.preventDefault(); });
    window.addEventListener('mousemove', e => {
      if (!_pan) return;
      const rect  = canvasEl.getBoundingClientRect();
      const winMs = _pan.e - _pan.s;
      const dxMs  = (e.clientX - _pan.startX) / rect.width * winMs;
      const dur   = Math.max(getDurationMs() || 0, winMs);
      const ns    = Math.max(0, Math.min(dur - winMs, _pan.s + dxMs));
      _zoomStartMs = ns;
      _zoomEndMs   = ns + winMs;
      _onZoomChange?.(_zoomStartMs, _zoomEndMs);
      draw();
    });
    window.addEventListener('mouseup', e => { if (e.button === 1) _pan = null; });
  }

  // ── Public API ────────────────────────────────────────────────────────────────
  return {
    // ── Data ─────────────────────────────────────────────────────────────────
    /** Load shape data; computes rolling averages internally. */
    setData(data, meta, avgWindowMs = 500) {
      _shapeData    = data;
      _shapeMeta    = meta;
      _shapeAvgData = data ? computeAverages(data, avgWindowMs) : null;
    },
    /** Optional in-progress xcorr capture overlay rendered downward from the
     *  midline. Pass null to clear. Saved data automatically squeezes to the
     *  upper half whenever live data is present so both fit on one canvas. */
    setLiveShape(data) {
      _liveData = (data && Array.isArray(data.timestamps_ms) && data.timestamps_ms.length) ? data : null;
    },

    // ── View ──────────────────────────────────────────────────────────────────
    setZoom(startMs, endMs) {
      _zoomStartMs = startMs;
      _zoomEndMs   = endMs;
    },
    /** Set playhead position in ms. Pass null to hide. Caller applies latency offset. */
    setPlayhead(ms) { _playheadMs = ms ?? null; },
    /** Custom markers override profile trigger markers in the canvas. */
    setCustomMarkers(markers) { _customMarkers = markers ?? []; },
    /** Highlight a custom marker by index (glow + outline). Pass null to clear. */
    setHighlightedMarker(idx) { _highlightedMarkerIdx = idx ?? null; },
    /** Bulk-assign filter state. Any argument may be null/undefined to leave unchanged. */
    setFilters(shapeFilters, shapeAvgFilters, markTypeFilters) {
      if (shapeFilters)    Object.assign(_filters,     shapeFilters);
      if (shapeAvgFilters) Object.assign(_avgFilters,  shapeAvgFilters);
      if (markTypeFilters) Object.assign(_markFilters, markTypeFilters);
    },
    /** Bulk-assign scale state. */
    setScales(shapeScales, scaleOverall) {
      if (shapeScales)             Object.assign(_scales, shapeScales);
      if (scaleOverall !== undefined) _scaleOverall = scaleOverall;
    },
    /** Pin Y-axis max RMS. Pass null to use window-based max. */
    setMaxRms(v) { _maxRms = v ?? null; },
    /** Shift shape data (RMS + marks) by ms to align capture timing with playhead. Triggers/playhead unaffected. */
    setOffset(ms) { _offsetMs = ms ?? 0; draw(); },
    /** Perception trim — drawn as a secondary (orange) playhead at offset+trim when non-zero. */
    setTrim(ms) { _trimMs = ms ?? 0; draw(); },
    /** Register a callback fired while the user drags the orange playhead.
     *  Signature: (newTrimMs, isFinal:boolean) — isFinal=true on mouseup. */
    setOnTrimChange(fn) { _onTrimChange = fn || null; },
    /** Set auto-offset calibration target. Pass null/[] to clear. */
    setCalibrationTarget(ms, candidates) {
      _calibrationTargetMs   = ms ?? null;
      _calibrationCandidates = candidates ?? [];
    },
    /** Anchor candidates from AudioShapeMeta.anchor_candidates. Drawn only
     *  in advanced mode. Pass [] to clear. tempoBpm enables ±1..4 beat twins. */
    setAnchorCandidates(candidates, tempoBpm) {
      _anchorCandidates = Array.isArray(candidates) ? candidates : [];
      _anchorTempoBpm = (typeof tempoBpm === 'number' && tempoBpm > 0) ? tempoBpm : null;
    },
    /** Live anchor-match info from the WS broadcast. Drawn in advanced mode.
     *  match: {offset_ms, r, q, candidate_idx}. Pass null to clear. */
    setLiveMatch(match) { _liveMatch = match || null; },
    /** Append one per-window xcorr result (advanced overlay).
     *  msg: {win_start, win_end, new_offset_ms, new_r, new_quality, old_r, winner, failed} */
    addXcorrWindow(msg) {
      _xcorrWindows.push(msg);
      if (_xcorrWindows.length > 30) _xcorrWindows.shift();
    },
    /** Clear all per-window xcorr overlay results. Caller should invoke this
     *  on track change so the previous song's windows don't stay visible. */
    clearXcorrWindows() { _xcorrWindows = []; },
    /** Append one mismatch-spike pick (Debug overlay). Draws a magenta window
     *  band + spike marker. msg: {spike_ms, win_start, win_end, strength}.
     *  Keeps only the few most recent so stale picks fade off. */
    addSpike(msg) {
      _spikes.push({
        spike_ms:  msg.spike_ms,
        win_start: msg.win_start,
        win_end:   msg.win_end,
        strength:  msg.strength,
      });
      if (_spikes.length > 4) _spikes.shift();
    },
    /** Clear all spike overlays. Invoke on track change. */
    clearSpikes() { _spikes = []; },
    /** Supply profile triggers + events for drawing trigger markers. */
    setProfile(profile, events) {
      _profile = profile;
      _events  = events ?? [];
    },
    /** Set librosa analysis for graph overlay. Pass null to clear. Initialises offset from analysis.librosa_offset_ms.
     *  Automatically expands / shrinks canvas height by BEAT_STRIP_H to accommodate the beat-energy strip. */
    setLibrosaMarkers(analysis) {
      const hadStrip = !!(_librosaAnalysis?.beats?.length);
      const oldStripH = hadStrip ? _totalStripH() : 0;
      _librosaAnalysis = analysis ?? null;
      _librosaOffsetMs = analysis?.librosa_offset_ms ?? 0;
      // Pre-compute MFCC timbral distances
      _mfccDistances = null;
      if (_librosaAnalysis?.beats?.length) {
        const beats = _librosaAnalysis.beats;
        const WINDOW = 4;  // match scene_mfcc_window default
        if (beats[0]?.mfcc?.length) {
          const dists = new Array(beats.length).fill(0);
          for (let i = WINDOW; i < beats.length; i++) {
            const a = beats[i].mfcc, b = beats[i - WINDOW].mfcc;
            let sum = 0;
            for (let c = 0; c < a.length; c++) sum += (a[c] - b[c]) ** 2;
            dists[i] = Math.sqrt(sum);
          }
          const mx = Math.max(...dists);
          if (mx > 1e-9) for (let i = 0; i < dists.length; i++) dists[i] /= mx;
          _mfccDistances = dists;
        }
      }
      const hasStrip = !!(_librosaAnalysis?.beats?.length);
      const newStripH = hasStrip ? _totalStripH() : 0;
      if (oldStripH !== newStripH) {
        const curH = canvasEl.offsetHeight || 120;
        canvasEl.style.height = (curH - oldStripH + newStripH) + 'px';
      }
    },
    /** True when the loaded analysis includes snare onsets (librosa v3+). */
    hasSnareData() { return _hasSnareData(); },
    /** Override the librosa time offset (ms) without replacing the analysis object. */
    setLibrosaOffset(ms) { _librosaOffsetMs = ms ?? 0; },
    get librosaOffsetMs() { return _librosaOffsetMs; },
    /** Preview offset for trigger markers (bulk-shift before commit). Does not modify profile data. */
    setTriggerOffset(ms) { _triggerOffsetMs = ms ?? 0; },
    get triggerOffsetMs() { return _triggerOffsetMs; },

    // ── Render ────────────────────────────────────────────────────────────────
    draw,
    startLoop(intervalMs = 25) {
      if (_loopId) clearInterval(_loopId);
      _loopId = setInterval(draw, intervalMs);
    },
    stopLoop() { if (_loopId) { clearInterval(_loopId); _loopId = null; } },

    // ── Wiring ────────────────────────────────────────────────────────────────
    wireResizeHandle,
    wireZoomHandles,
    wireMiddlePan,

    // ── Callback ──────────────────────────────────────────────────────────────
    set onZoomChange(fn) { _onZoomChange = fn; },
    get onZoomChange()   { return _onZoomChange; },

    // ── State inspection (exposed by reference for direct mutation) ───────────
    /** Direct reference — mutate freely, then call draw(). */
    get filters()       { return _filters; },
    get avgFilters()    { return _avgFilters; },
    get markFilters()   { return _markFilters; },
    get librosaFilters(){ return _librosaFilters; },
    get scales()     { return _scales; },
    get scaleOverall() { return _scaleOverall; },
    set scaleOverall(v) { _scaleOverall = v; },
    get zoomStart()  { return _zoomStartMs; },
    get zoomEnd()    { return _zoomEndMs; },
    get hasData()    { return !!_shapeData?.timestamps_ms?.length; },
    get shapeMeta()  { return _shapeMeta; },

    /**
     * Snap rawMs to the nearest librosa event based on vertical click position.
     * Beat strip (below audio shape)  → nearest beat
     * Top third of audio shape        → nearest of onsets or harmonics (whichever is closer)
     * Elsewhere on audio shape        → no snap
     * Returns snapped ms, or rawMs if nothing to snap to.
     */
    snapTimestamp(rawMs, clickYCss) {
      if (!_librosaAnalysis?.beats?.length) return rawMs;
      const la = _librosaAnalysis;
      const off = _librosaOffsetMs;
      const canvasHCss = canvasEl.offsetHeight || 120;
      const mainHCss = canvasHCss - _totalStripH();  // all strips present when beats loaded
      const radiusMs = 10 * (_zoomEndMs - _zoomStartMs) / (canvasEl.offsetWidth || 1);

      function _nearest(events) {
        if (!events?.length) return null;
        let best = null, bestDist = radiusMs;
        for (const ev of events) {
          const d = Math.abs((ev.ms + off) - rawMs);
          if (d < bestDist) { bestDist = d; best = ev.ms + off; }
        }
        return best;
      }

      // Beat strip: snap to beats
      if (clickYCss >= mainHCss) {
        return _nearest(la.beats) ?? rawMs;
      }

      const yFrac = clickYCss / mainHCss;

      // Top third of audio shape: nearest of onsets or harmonics
      if (yFrac < 1 / 3) {
        const ho = _nearest(la.harmonic_changes);
        const on = _nearest(la.onsets);
        if (ho !== null && on !== null)
          return Math.abs(ho - rawMs) <= Math.abs(on - rawMs) ? ho : on;
        return ho ?? on ?? rawMs;
      }

      // Bottom third of audio shape: snap to beats
      if (yFrac >= 2 / 3) {
        return _nearest(la.beats) ?? rawMs;
      }

      // Middle third: no snap
      return rawMs;
    },

    /**
     * Return info about the beat-strip cell at a CSS click position, or null
     * if the click is outside the strip area (or no librosa data).
     * Returns { timestamp_ms, value, name } where timestamp_ms is song-relative.
     */
    getBeatAtClick(cssX, cssY) {
      if (!_librosaAnalysis?.beats?.length) return null;
      const la  = _librosaAnalysis;
      const off = _librosaOffsetMs;
      const canvasHCss = canvasEl.offsetHeight || 120;
      const mainHCss   = canvasHCss - _totalStripH();
      if (cssY < mainHCss || cssY >= canvasHCss) return null;

      const stripIndex = Math.min(_numStrips() - 1,
                                  Math.floor((cssY - mainHCss) / BEAT_STRIP_H));
      const STRIP_COLORS = ['#ffffff', '#00ccdd', '#ff8800', '#44dd88', '#cc66ff'];
      const STRIP_GET    = [
        b => b.rms_total        ?? 0,
        b => b.rms_bass         ?? 0,
        b => b.onset_score      ?? 0,
        b => b.bass_onset_score ?? 0,
        b => b.harmonic_score   ?? 0,
      ];
      // Extend for snare strip when active (must mirror the draw-time STRIPS order)
      if (_librosaFilters.snare && _hasSnareData()) {
        STRIP_COLORS.push('#ffdd33');
        STRIP_GET.push(b => b.snare_onset_score ?? 0);
      }
      // Extend for MFCC strip when active
      if (_librosaFilters.mfcc && _mfccDistances) {
        STRIP_COLORS.push('#ff6633');
        const _mfccDists = _mfccDistances;
        STRIP_GET.push((b, _i) => {
          const idx = la.beats.indexOf(b);
          return idx >= 0 ? (_mfccDists[idx] ?? 0) : 0;
        });
      }

      // Map cssX to song time; find beat whose cell contains the click (left-edge ownership)
      const pct     = Math.max(0, Math.min(1, cssX / (canvasEl.offsetWidth || 1)));
      const clickMs = _zoomStartMs + pct * (_zoomEndMs - _zoomStartMs);
      let beat = null;
      for (let i = 0; i < la.beats.length; i++) {
        const cellStart = la.beats[i].ms + off;
        const cellEnd   = i + 1 < la.beats.length ? la.beats[i + 1].ms + off : Infinity;
        if (clickMs >= cellStart && clickMs < cellEnd) { beat = la.beats[i]; break; }
      }
      if (!beat) return null;

      return {
        timestamp_ms: beat.ms + off,
        value:        STRIP_GET[stripIndex](beat),
        color:        STRIP_COLORS[stripIndex],
      };
    },
  };
}
