"""
SpotFX — AI-assisted trigger generation.

Uses librosa audio analysis (beats, onsets, harmonic changes, sections) as the
primary data source.

Training songs must have:
  - a verified song profile with at least one trigger
  - a librosa analysis JSON  (songs without one are skipped with a warning)

The target song must have a librosa analysis; if absent, generation raises ValueError.

Claude receives per-beat scores (onset_score, bass_onset_score, harmonic_score) that
encode event density directly in the beats table — no separate onset/harmonic tables.
Claude returns beat_index values; the backend maps them to ms timestamps.
"""
from __future__ import annotations
import json
import logging

from pydantic import BaseModel

from config import settings, AUDIO_SHAPES_DIR
from models.librosa_analysis import LibrosaAnalysis
from services.profile_manager import load_profile_by_uri, get_event_map
from services.audio_analyzer import load_audio_shape_meta

logger = logging.getLogger(__name__)

# Pricing (USD per million tokens)
_MODEL               = "claude-sonnet-4-6"
_INPUT_COST_PER_M    = 3.00
_OUTPUT_COST_PER_M   = 15.00

_HAIKU_MODEL             = "claude-haiku-4-5-20251001"
_HAIKU_INPUT_COST_PER_M  = 0.80
_HAIKU_OUTPUT_COST_PER_M = 4.00

_EST_OUTPUT_TOKENS   = 1_000   # conservative per-song output estimate for pre-call cost


def _tokens_cost(
    input_tok: int,
    output_tok: int,
    input_rate: float = _INPUT_COST_PER_M,
    output_rate: float = _OUTPUT_COST_PER_M,
) -> float:
    return (input_tok * input_rate + output_tok * output_rate) / 1_000_000


# ── Public data model ─────────────────────────────────────────────────────────

class SuggestedTrigger(BaseModel):
    timestamp_ms: int
    event_id: str
    event_name: str = ""
    confidence: float
    reasoning: str


# ── Librosa formatting helpers ────────────────────────────────────────────────

def _fmt_sections(la: LibrosaAnalysis) -> str:
    if not la.sections:
        return "  (none)"
    lines = ["  start–end        label       energy  density/s"]
    for s in la.sections:
        start = f"{s.start_ms // 1000}s"
        end   = f"{s.end_ms // 1000}s"
        lines.append(
            f"  {start:>5}–{end:<6}  {s.label:<10}  {s.energy_rms:.3f}   {s.onset_density_per_s:.2f}"
        )
    return "\n".join(lines)


def _fmt_beats(la: LibrosaAnalysis) -> str:
    if not la.beats:
        return "  (none)"
    lines = ["  #   * T B O Q H"]
    for i, b in enumerate(la.beats):
        db = "*" if b.is_downbeat else " "
        t  = format(round(b.rms_total        * 15), 'x')
        bv = format(round(b.rms_bass         * 15), 'x')
        o  = format(round(b.onset_score      * 15), 'x')
        q  = format(round(b.bass_onset_score * 15), 'x')
        h  = format(round(b.harmonic_score   * 15), 'x')
        lines.append(f"  {i:>4} {db} {t} {bv} {o} {q} {h}")
    return "\n".join(lines)


def _fmt_trigger_rows(trigger_rows: list[dict], la: LibrosaAnalysis) -> str:
    """
    Show each training trigger with its librosa context:
    beat index of nearest beat (offset + DB flag) and enclosing section label.
    """
    if not trigger_rows:
        return "  (none)"

    off = la.librosa_offset_ms

    def _section_at(ms: int) -> str:
        for s in la.sections:
            if s.start_ms + off <= ms < s.end_ms + off:
                return s.label
        return "?"

    def _nearest_beat_info(ms: int) -> tuple[int, bool]:
        """Return (beat_index, is_downbeat)."""
        if not la.beats:
            return -1, False
        idx = min(range(len(la.beats)), key=lambda i: abs(la.beats[i].ms + off - ms))
        b = la.beats[idx]
        return idx, b.is_downbeat

    lines = ["  beat#  DB  section     event"]
    for tr in sorted(trigger_rows, key=lambda t: t["timestamp_ms"]):
        ms  = tr["timestamp_ms"]
        sec = _section_at(ms)
        idx, is_db = _nearest_beat_info(ms)
        if idx >= 0:
            db_str = "DB" if is_db else "  "
            lines.append(f"  {idx:>5}  {db_str}  {sec:<10}  {tr['event_name']}")
        else:
            lines.append(f"      ?       {sec:<10}  {tr['event_name']}")
    return "\n".join(lines)


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(
    training: list[dict],
    target: dict,
    description: str,
    regular_events: list[dict],
    song_start_events: list[dict],
) -> str:
    lines: list[str] = []

    if description.strip():
        lines.append(f"Playlist vibe: {description.strip()}\n")

    if song_start_events:
        lines.append("## Song Start Event (select exactly one — will be placed at 0:00.0 automatically):")
        for ev in song_start_events:
            energy_str = f"  energy={ev['energy_level']}/10" if ev.get("energy_level") is not None else ""
            lines.append(f'  id="{ev["id"]}"  name="{ev["name"]}"{energy_str}')

    lines.append("\n## Available Events (use these exact IDs in triggers):")
    for ev in regular_events:
        energy_str = f"  energy={ev['energy_level']}/10" if ev.get("energy_level") is not None else ""
        lines.append(f'  id="{ev["id"]}"  name="{ev["name"]}"{energy_str}')

    lines.append("\n## Training Songs (librosa analysis + verified trigger placements):")
    for i, song in enumerate(training, 1):
        la: LibrosaAnalysis = song["librosa"]
        tr = song["trigger_rows"]
        lines.append(
            f"\n### Training {i}: {song['artist']} — {song['title']}\n"
            f"Duration: {song['duration_ms'] // 1000}s | "
            f"Tempo: {la.tempo_bpm:.1f} BPM | {la.beats_per_bar}/4 | "
            f"Triggers: {song['trigger_count']}"
        )
        lines.append("\n#### Sections")
        lines.append(_fmt_sections(la))
        lines.append("\n#### Beats  (* = bar-1 downbeat; T B O Q H on 0–f hex scale)")
        lines.append(_fmt_beats(la))
        lines.append("\n#### Verified Trigger Placements")
        lines.append(_fmt_trigger_rows(tr, la))

    la_t: LibrosaAnalysis = target["librosa"]
    lines.append(
        f"\n## Target Song: {target['artist']} — {target['title']}\n"
        f"Duration: {target['duration_ms'] // 1000}s | "
        f"Tempo: {la_t.tempo_bpm:.1f} BPM | {la_t.beats_per_bar}/4"
    )
    lines.append("\n#### Sections")
    lines.append(_fmt_sections(la_t))
    lines.append(
        "\n#### Beats  (DB = bar-1 downbeat; rms_t/rms_b normalised 0–1 across song; "
        "onset/bass/harm = per-beat event density 0–1)"
    )
    lines.append(_fmt_beats(la_t))
    if target["trigger_rows"]:
        lines.append("\n#### Existing Trigger Placements (already in this song — avoid duplicating these)")
        lines.append(_fmt_trigger_rows(target["trigger_rows"], la_t))

    lines.append("""
## Task
Based on the training song patterns above, suggest trigger placements for the target song.
Study WHERE the verified triggers landed in each training song relative to the musical
structure — which beat index, which section, whether it was a downbeat, what the
onset/bass/harmonic density was — then find analogous beats in the target.

Output ONLY a JSON object (no prose, no markdown fences):
{
  "song_start_event_id": "exact-uuid-from-Song-Start-list",
  "triggers": [
    {"beat_index": 112, "event_id": "exact-uuid-from-Available-Events", "confidence": 0.85}
  ]
}

Rules:
- song_start_event_id: choose from the Song Start list based on the target song's genre/energy
- triggers: beat_index must be a valid beat number from the target beats table (0-indexed)
- event_id must be one of the IDs from the Available Events list (do NOT use Song Start event IDs here)
- Song End must appear exactly once in triggers, at the beat where the outro energy begins to fade
- confidence: 0.0–1.0
- Do NOT include a "reasoning" field — omit it entirely
- Match the trigger density of the training songs
- Do NOT suggest triggers that duplicate existing placements (same beat index or within 2 beats)
""")
    return "\n".join(lines)


def _call_claude(system_prompt: str, user_prompt: str, model: str = _MODEL) -> tuple[dict, dict]:
    """Call Claude and return (parsed_result, usage_dict).

    parsed_result keys:
      song_start_event_id: str  — the chosen Song Start event ID
      triggers: list[dict]      — the per-beat trigger suggestions
    """
    import re
    import anthropic
    in_rate  = _HAIKU_INPUT_COST_PER_M  if model == _HAIKU_MODEL else _INPUT_COST_PER_M
    out_rate = _HAIKU_OUTPUT_COST_PER_M if model == _HAIKU_MODEL else _OUTPUT_COST_PER_M
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    usage = {
        "input_tokens":  message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "cost_usd":      _tokens_cost(message.usage.input_tokens, message.usage.output_tokens, in_rate, out_rate),
        "model":         model,
    }
    text = message.content[0].text.strip()

    # Extract JSON from inside a code fence if present
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Find the first {...} or [...] block
    if not text.startswith(('{', '[')):
        obj_match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
        if obj_match:
            text = obj_match.group(0)

    if not text:
        logger.error("Claude returned no parseable JSON. Raw: %r", message.content[0].text[:300])
        return {"song_start_event_id": "", "triggers": []}, usage

    # Strip control characters (bare newlines/tabs inside strings) that break json.loads
    import re as _re
    text = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Claude JSON parse error at char %d: %s | snippet: %r",
                     exc.pos, exc.msg, text[max(0, exc.pos - 40):exc.pos + 40])
        return {"song_start_event_id": "", "triggers": []}, usage

    # Normalise: accept both the new {song_start_event_id, triggers} format and a legacy raw array
    if isinstance(parsed, list):
        logger.warning("Claude returned legacy array format — no song_start_event_id")
        return {"song_start_event_id": "", "triggers": parsed}, usage

    return parsed, usage


# ── Public API ────────────────────────────────────────────────────────────────

def generate_suggestions(
    training_uris: list[str],
    target_uri: str,
    description: str = "",
    model: str = _MODEL,
) -> list[SuggestedTrigger]:
    """
    Load training + target librosa data, call Claude, return structured suggestions.
    Training songs without a librosa analysis are skipped with a warning.
    Raises ValueError if the target has no librosa analysis or no valid training songs.
    """
    from services.librosa_service import get_analysis_by_uri

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    event_map = get_event_map()  # {event_id: {name, color, ...}}
    all_events = [
        {"id": eid, **info}
        for eid, info in event_map.items()
        if info.get("ai_exposed", False)
    ]
    if not all_events:
        raise ValueError(
            "No AI-exposed events found — open the Events page and enable "
            "'Expose to AI generation' on at least one event"
        )
    song_start_events = [e for e in all_events if "song start" in e["name"].lower()]
    regular_events    = [e for e in all_events if "song start" not in e["name"].lower()]

    # ── Training songs ────────────────────────────────────────────────────────
    training_data: list[dict] = []
    for uri in training_uris:
        profile = load_profile_by_uri(uri)
        meta    = load_audio_shape_meta(uri)
        la      = get_analysis_by_uri(uri)
        if not profile or not meta:
            logger.warning("Skipping training URI (missing profile/shape): %s", uri)
            continue
        if la is None:
            logger.warning("Skipping training URI (no librosa analysis): %s", uri)
            continue

        trigger_rows = [
            {"timestamp_ms": tr.timestamp_ms,
             "event_name": event_map.get(tr.event_id, {}).get("name", tr.event_id)}
            for tr in profile.triggers
        ]
        training_data.append({
            "uri":           uri,
            "title":         profile.title,
            "artist":        profile.artist,
            "duration_ms":   profile.duration_ms,
            "trigger_count": len(profile.triggers),
            "trigger_rows":  trigger_rows,
            "librosa":       la,
        })

    if not training_data:
        raise ValueError(
            "No valid training songs found — each training song needs a song profile with "
            "triggers AND a librosa analysis"
        )

    # ── Target song ───────────────────────────────────────────────────────────
    target_meta = load_audio_shape_meta(target_uri)
    if not target_meta:
        raise ValueError(f"No audio shape found for target URI: {target_uri}")
    la_target = get_analysis_by_uri(target_uri)
    if la_target is None:
        raise ValueError(
            f"No librosa analysis found for target song '{target_meta.title}' — "
            "run Librosa analysis first"
        )

    target_profile = load_profile_by_uri(target_uri)
    target_trigger_rows = [
        {"timestamp_ms": tr.timestamp_ms,
         "event_name": event_map.get(tr.event_id, {}).get("name", tr.event_id)}
        for tr in target_profile.triggers
    ] if target_profile and target_profile.triggers else []

    target_data = {
        "uri":          target_uri,
        "title":        target_meta.title,
        "artist":       target_meta.artist,
        "duration_ms":  target_meta.duration_ms,
        "librosa":      la_target,
        "trigger_rows": target_trigger_rows,
    }

    system_prompt = (
        "You are a music trigger placement assistant for a music-reactive lighting system.\n\n"
        "You receive detailed librosa audio analysis for reference (training) songs alongside "
        "their verified trigger placements, then must suggest trigger placements for a new target song.\n\n"
        "Data schema:\n"
        "- Sections: structural segments detected via self-similarity. Labels are inferred "
        "  (intro / verse / chorus / bridge / drop / outro). Each has mean RMS energy (0–1, "
        "  normalised across sections) and onset density per second.\n"
        "- Beats: every detected beat with a 0-based index (#). * = bar-1 downbeat (beat 1 of a bar). "
        "  Columns T B O Q H are hex digits 0–f (0=min, f=max across all beats in this song):\n"
        "  T = total-band RMS energy for that beat; B = bass (<250 Hz) RMS;\n"
        "  O = full-spectrum onset strength; Q = bass onset strength; H = harmonic novelty.\n"
        "- Events: each has an energy_level (1–10) indicating visual intensity. "
        "  Match event energy to the musical moment — use high-energy events at peaks, "
        "  low-energy events during quiet or transitional passages.\n"
        "- Verified Trigger Placements (training only): the beat index where a human placed each "
        "  trigger. Use these to learn both placement style AND "
        "  trigger density — your output should match the training songs' density closely.\n\n"
        "Song Start is handled automatically — you only select which Song Start event to use; "
        "it will be placed at 0:00.0 by the system. Song End must appear exactly once in your "
        "triggers output, placed at the beat where the outro energy begins to fade.\n"
        "Focus on musically meaningful moments: section entries (especially drops/choruses), "
        "bar-1 downbeats with high bass energy and onset density, harmonic shifts. "
        "Match the trigger density of the training songs.\n\n"
        "Output beat_index values from the target beats table. The system will resolve each "
        "beat_index to the exact millisecond timestamp."
    )
    user_prompt = _build_prompt(training_data, target_data, description, regular_events, song_start_events)

    logger.info(
        "Calling Claude for trigger suggestions: %d training songs → %s",
        len(training_data), target_meta.title,
    )
    result, usage = _call_claude(system_prompt, user_prompt, model=model)

    song_start_eid = result.get("song_start_event_id", "")
    raw = result.get("triggers", [])

    target_beats = la_target.beats
    suggestions: list[SuggestedTrigger] = []

    # Inject Song Start at 0ms using Claude's chosen event
    if song_start_eid and song_start_eid in event_map:
        ev_info = event_map[song_start_eid]
        suggestions.append(SuggestedTrigger(
            timestamp_ms=0,
            event_id=song_start_eid,
            event_name=ev_info.get("name", song_start_eid),
            confidence=1.0,
            reasoning="Song start — placed at 0:00.0",
        ))
    elif song_start_events:
        # Fallback: use first available song start event
        fallback = song_start_events[0]
        logger.warning("Claude returned no valid song_start_event_id; using fallback %s", fallback["name"])
        suggestions.append(SuggestedTrigger(
            timestamp_ms=0,
            event_id=fallback["id"],
            event_name=fallback["name"],
            confidence=0.5,
            reasoning="Song start — placed at 0:00.0 (fallback, Claude did not select an event)",
        ))

    for item in raw:
        beat_idx = item.get("beat_index")
        if beat_idx is not None:
            beat_idx = max(0, min(int(beat_idx), len(target_beats) - 1))
            timestamp_ms = max(0, target_beats[beat_idx].ms + la_target.librosa_offset_ms)
        else:
            # Graceful fallback if model returns timestamp_ms instead of beat_index
            ts = item.get("timestamp_ms")
            if ts is None:
                logger.warning("Skipping suggestion with no beat_index or timestamp_ms: %r", item)
                continue
            timestamp_ms = int(ts)
            logger.warning("Claude returned timestamp_ms instead of beat_index for item: %r", item)

        ev_info = event_map.get(item.get("event_id", ""), {})
        suggestions.append(SuggestedTrigger(
            timestamp_ms=timestamp_ms,
            event_id=item.get("event_id", ""),
            event_name=ev_info.get("name", item.get("event_id", "")),
            confidence=float(item.get("confidence", 0.7)),
            reasoning=item.get("reasoning", ""),
        ))

    suggestions.sort(key=lambda s: s.timestamp_ms)
    logger.info(
        "Claude returned %d suggestions for %s | cost=$%.4f (%d in / %d out tokens)",
        len(suggestions), target_meta.title,
        usage["cost_usd"], usage["input_tokens"], usage["output_tokens"],
    )
    return suggestions, usage


def estimate_generation_cost(
    training_uris: list[str],
    target_uris: list[str],
    description: str = "",
) -> dict:
    """
    Estimate token cost for generating suggestions for one or more target songs.
    Builds the full prompt for each target but does NOT call Claude.
    Returns {per_song: [...], total_input_tokens, total_output_tokens, total_cost_usd}.
    """
    from services.librosa_service import get_analysis_by_uri

    event_map = get_event_map()
    all_events        = [{"id": eid, **info} for eid, info in event_map.items() if info.get("ai_exposed", False)]
    song_start_events = [e for e in all_events if "song start" in e["name"].lower()]
    regular_events    = [e for e in all_events if "song start" not in e["name"].lower()]

    # Build system prompt (same for all songs)
    system_prompt = (
        "You are a music trigger placement assistant for a music-reactive lighting system.\n\n"
        "You receive detailed librosa audio analysis for reference (training) songs alongside "
        "their verified trigger placements, then must suggest trigger placements for a new target song.\n\n"
        "Data schema: (omitted for estimation)"
    )

    training_data: list[dict] = []
    for uri in training_uris:
        profile = load_profile_by_uri(uri)
        meta    = load_audio_shape_meta(uri)
        la      = get_analysis_by_uri(uri)
        if not profile or not meta or la is None:
            continue
        trigger_rows = [
            {"timestamp_ms": tr.timestamp_ms,
             "event_name": event_map.get(tr.event_id, {}).get("name", tr.event_id)}
            for tr in profile.triggers
        ]
        training_data.append({
            "uri":           uri,
            "title":         profile.title,
            "artist":        profile.artist,
            "duration_ms":   profile.duration_ms,
            "trigger_count": len(profile.triggers),
            "trigger_rows":  trigger_rows,
            "librosa":       la,
        })

    per_song = []
    total_in = 0
    total_out = 0

    for target_uri in target_uris:
        target_meta = load_audio_shape_meta(target_uri)
        la_target   = get_analysis_by_uri(target_uri)
        if not target_meta or la_target is None:
            per_song.append({"uri": target_uri, "title": "?", "error": "missing analysis"})
            continue

        target_profile = load_profile_by_uri(target_uri)
        target_trigger_rows = [
            {"timestamp_ms": tr.timestamp_ms,
             "event_name": event_map.get(tr.event_id, {}).get("name", tr.event_id)}
            for tr in target_profile.triggers
        ] if target_profile and target_profile.triggers else []

        target_data = {
            "uri":          target_uri,
            "title":        target_meta.title,
            "artist":       target_meta.artist,
            "duration_ms":  target_meta.duration_ms,
            "librosa":      la_target,
            "trigger_rows": target_trigger_rows,
        }
        user_prompt = _build_prompt(training_data, target_data, description, regular_events, song_start_events)
        full_text   = system_prompt + user_prompt
        in_tok  = max(1, len(full_text) // 2)
        out_tok = _EST_OUTPUT_TOKENS
        sonnet_cost = _tokens_cost(in_tok, out_tok)
        haiku_cost  = _tokens_cost(in_tok, out_tok, _HAIKU_INPUT_COST_PER_M, _HAIKU_OUTPUT_COST_PER_M)
        total_in  += in_tok
        total_out += out_tok
        per_song.append({
            "uri":             target_uri,
            "title":           target_meta.title,
            "artist":          target_meta.artist,
            "input_tokens":    in_tok,
            "output_tokens":   out_tok,
            "cost_usd":        sonnet_cost,      # backward compat
            "sonnet_cost_usd": sonnet_cost,
            "haiku_cost_usd":  haiku_cost,
        })

    total_sonnet = _tokens_cost(total_in, total_out)
    total_haiku  = _tokens_cost(total_in, total_out, _HAIKU_INPUT_COST_PER_M, _HAIKU_OUTPUT_COST_PER_M)
    return {
        "per_song":              per_song,
        "total_input_tokens":    total_in,
        "total_output_tokens":   total_out,
        "total_cost_usd":        total_sonnet,   # backward compat
        "total_sonnet_cost_usd": total_sonnet,
        "total_haiku_cost_usd":  total_haiku,
        "sonnet_model":          _MODEL,
        "haiku_model":           _HAIKU_MODEL,
    }


def analyze_learning(current_description: str, feedback: list[dict]) -> str:
    """
    Given approval/rejection feedback across multiple songs, ask Claude to refine
    the vibe description so future generations better match user preferences.

    feedback items: [
      {song, song_comment,
       approved:  [{timestamp_ms, event_name, reasoning, comment}],
       rejected:  [{timestamp_ms, event_name, reasoning, comment}],
       manually_added: [{timestamp_ms, event_name, comment}]}
    ]
    Returns a refined description string.
    """
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    def _fmt_ts(ms: int) -> str:
        s = ms // 1000
        return f"{s // 60}:{s % 60:02d}"

    lines: list[str] = [
        "You are helping refine a music-trigger generation prompt.",
        "The prompt is used to instruct an AI to place lighting-system trigger points in songs.",
    ]
    lines.append("\n## Current description used for generation:")
    lines.append(current_description.strip() or "(none)")

    lines.append("\n## User feedback on generated triggers:")
    for item in feedback:
        lines.append(f"\n### Song: {item['song']}")
        if item.get("song_comment", "").strip():
            lines.append(f"  Overall comment: {item['song_comment'].strip()}")

        approved      = item.get("approved", [])
        rejected      = item.get("rejected", [])
        manually_added = item.get("manually_added", [])

        if approved:
            lines.append("  Approved triggers:")
            for t in approved:
                extra = f" | User note: {t['comment']}" if t.get("comment", "").strip() else ""
                lines.append(
                    f"    ✓ {_fmt_ts(t.get('timestamp_ms', 0))}  [{t.get('event_name', '?')}]"
                    f"  — {t.get('reasoning', '')}{extra}"
                )
        if rejected:
            lines.append("  Rejected triggers:")
            for t in rejected:
                extra = f" | User note: {t['comment']}" if t.get("comment", "").strip() else ""
                lines.append(
                    f"    ✕ {_fmt_ts(t.get('timestamp_ms', 0))}  [{t.get('event_name', '?')}]"
                    f"  — {t.get('reasoning', '')}{extra}"
                )
        if manually_added:
            lines.append("  Triggers the user added manually (AI missed these moments):")
            for t in manually_added:
                extra = f" — {t['comment']}" if t.get("comment", "").strip() else ""
                lines.append(
                    f"    + {_fmt_ts(t.get('timestamp_ms', 0))}  [{t.get('event_name', '?')}]{extra}"
                )
        if not approved and not rejected and not manually_added:
            lines.append("  (no feedback recorded)")

    lines.append(
        "\n## Task\n"
        "Based on the feedback above, write an improved version of the description that will "
        "make future trigger generations more closely match what the user wants.\n\n"
        "Guidelines:\n"
        "- Focus on QUALITATIVE musical descriptions: types of moments, song structure, energy arcs,\n"
        "  the feel of the music. Do NOT specify exact numerical RMS values or delta thresholds —\n"
        "  keep those implicit. Describe what to listen for, not what to measure.\n"
        "- Emphasise the types of acoustic moments that were approved or manually added.\n"
        "- Describe what to avoid based on rejected triggers and user notes.\n"
        "- If the user manually added triggers Claude missed, note what kind of moment those were.\n"
        "- Keep it concise (3–6 sentences) and actionable for a future AI generation pass.\n"
        "Output ONLY the refined description text — no labels, no preamble, no markdown."
    )

    prompt = "\n".join(lines)
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=768,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def list_songs_with_shapes() -> list[dict]:
    """All songs with a complete audio shape capture."""
    from services.suggestion_store import AI_SUGGESTIONS_DIR
    result = []
    for path in AUDIO_SHAPES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("capture_complete"):
                continue
            track_id = data["spotify_uri"].split(":")[-1]
            result.append({
                "uri":             data["spotify_uri"],
                "title":           data["title"],
                "artist":          data["artist"],
                "duration_ms":     data["duration_ms"],
                "mark_count":      len(data.get("music_marks", [])),
                "genres":          data.get("genres", []),
                "has_suggestions": (AI_SUGGESTIONS_DIR / f"{track_id}.json").exists(),
                "npz_file":        data.get("npz_file", ""),
            })
        except Exception:
            pass
    return result


def list_songs_with_librosa() -> list[dict]:
    """All songs with a complete audio shape AND a librosa analysis (suitable as generation targets).
    Includes trigger_count from the song profile (0 if no profile exists)."""
    from pathlib import Path as _Path
    from config import PROFILES_DIR as _PROFILES_DIR

    # Build profile trigger-count lookup in one pass (avoids per-song glob)
    profile_triggers: dict[str, int] = {}
    for path in _PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profile_triggers[data["spotify_uri"]] = len(data.get("triggers", []))
        except Exception:
            pass

    # Filter shapes to those with a librosa file (exists check, no full read)
    result = []
    for s in list_songs_with_shapes():
        npz_file = s.get("npz_file", "")
        if not npz_file:
            continue
        base = _Path(npz_file).stem
        if not (AUDIO_SHAPES_DIR / f"{base}.librosa.json").exists():
            continue
        s["trigger_count"] = profile_triggers.get(s["uri"], 0)
        result.append(s)
    return result


def list_training_songs() -> list[dict]:
    """Songs with a complete audio shape AND at least one trigger in their profile."""
    from config import PROFILES_DIR as _PROFILES_DIR

    all_shapes = {s["uri"]: s for s in list_songs_with_shapes()}
    result = []
    for path in _PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            uri = data.get("spotify_uri", "")
            triggers = data.get("triggers", [])
            if not triggers or uri not in all_shapes:
                continue
            row = dict(all_shapes[uri])
            row["trigger_count"] = len(triggers)
            result.append(row)
        except Exception:
            pass
    return result
