"""THE ANALYSIS DOMAIN — Sonic's one operation over the analysed cues the
room generates for songs without hand-placed triggers: refreshing them
after the analysed settings (or the generator itself) change.

His ask, 2026-10-04: "when i change the analyzed settings, like
transitions per minute, i would like to be able to reanalyze all the
stored songs, or have it reanalyze when the song plays next ... Perhaps
just being able to tell sonic to update all analyzed triggers". The
next-play half needs nothing from him (midsong_generator's RE-ANALYSIS);
this is the "do it now" half, and it is the whole of
spectra/services/analysed_refresh.py behind one SonicOperation.

DRY RUN FIRST is enforced by the mechanism, not this file: the apply needs
the plan_id only a dry run hands out, and applies exactly what that dry run
reported. Scheduling a refresh for later is deliberately not offered (his
choice, recorded in the plan he approved).
"""
from __future__ import annotations

from typing import Optional

from spectra.services import analysed_refresh
from spectra.services.sonic_ops import SonicOperation


async def _op_refresh_analysed_triggers(uri: Optional[str] = None,
                                        dry_run: bool = True,
                                        plan_id: Optional[str] = None) -> dict:
    if not isinstance(dry_run, bool):
        return {"status": "rejected", "reason": "dry_run must be true or false"}
    if uri is not None and (not isinstance(uri, str) or not uri.strip()):
        return {"status": "rejected", "reason": "uri must be a Spotify track URI"}
    return await analysed_refresh.refresh(uri=uri, dry_run=dry_run, plan_id=plan_id)


OPERATIONS: dict[str, SonicOperation] = {
    "refresh_analysed_triggers": SonicOperation(
        name="refresh_analysed_triggers", domain="analysis", kind="write",
        summary="Refresh analysed triggers — re-plan the stored analysed "
                "scene changes for every song (or one song) under the current "
                "settings. Always a dry run first.",
        instructions=(
            "Use when he asks to refresh, update, regenerate or re-analyse his "
            "analysed (generated) triggers, for the whole library or one song "
            "(pass `uri`, a spotify:track: URI, for one song). FIRST call it "
            "with dry_run=true (the default): nothing is written, and the "
            "result says how many songs and cues would change and how far cues "
            "would move. Tell him those numbers in plain words and ask whether "
            "to go ahead. ONLY after he says yes, call it again with "
            "dry_run=false and the plan_id the dry run returned — the apply "
            "does exactly what the dry run showed, backs up his triggers file "
            "first and writes once. Only analysed cues are ever touched: his "
            "own triggers, songs that hold only his own triggers, and any "
            "analysed cue he edited or deleted by hand are left alone. A song "
            "that changed between the dry run and the apply is left as it is "
            "and named. Songs also refresh themselves the next time they play, "
            "so this is only needed to update everything at once. There is no "
            "way to schedule it for later."),
        input_schema={
            "type": "object",
            "properties": {
                "uri": {"type": "string",
                        "description": "One song's spotify:track: URI; omit for "
                                       "the whole library."},
                "dry_run": {"type": "boolean", "default": True},
                "plan_id": {"type": "string",
                            "description": "The plan_id a dry run returned — "
                                           "required when dry_run is false."},
            },
            "additionalProperties": False},
        handler=_op_refresh_analysed_triggers),
}
