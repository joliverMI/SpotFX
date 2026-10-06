"""The drop-detection plan's own four-song table, live on the /testbed page
(report section 5.1; plan phase 2: "a Drops lane on the test bed scores it
against your marks on any song, so the two thresholds can be tuned by eye
before anything fires").

The four songs the Admiral named — Contra, Dopamine and Pop Off ("really
good examples") and 100 Millones ("not an EDM song but has a drop") — at
the caller's two thresholds, scored by spectra/services/drop_scoring.py,
the same function scripts/check_drop_detector.py holds the acceptance
numbers with. The EDM flag is what the plan's "nothing false on the three
EDM songs" reads.

Detection here runs at the CALLER'S thresholds with the guards applied and
never reads or writes the drop-sequence store: this is the detector's
proposal against his marks, not the merged view (the stand-down would
score it on nothing where he has a drop). The analysis is memoised per
song (drop_detector.analyse), so a slider drag re-runs only the cheap
half.
"""
from __future__ import annotations

from typing import Optional

from spectra.services import drop_detector, drop_scoring, drop_sequences, trigger_store
from spectra.services.testbed_engines import drop_thresholds

DROP_REFERENCE_SONGS: list[tuple[str, str, bool]] = [
    ("Contra", "spotify:track:2zVg53xdC6RMpthWju6LRT", True),
    ("Dopamine", "spotify:track:7vFKcXQ39f74XNrZmXADIT", True),
    ("Pop Off", "spotify:track:4PolqZLqReEqc3yURJtzc4", True),
    ("100 Millones", "spotify:track:4Ixc50wY5pbUvNEogTQ2wL", False),
]


def compute(*, confident_score: Optional[float] = None,
            suggested_score: Optional[float] = None,
            floor_score: Optional[float] = None) -> dict:
    confident, suggested, floor = drop_thresholds(confident_score, suggested_score, floor_score)
    rows = []
    for name, uri, edm in DROP_REFERENCE_SONGS:
        try:
            det = drop_detector.detect_uri(uri, confident_score=confident,
                                           suggested_score=suggested, drop_floor=floor)
        except drop_detector.Unavailable as exc:
            rows.append({"name": name, "uri": uri, "edm": edm, "available": False,
                         "reason": str(exc), "score": None})
            continue
        marks = drop_sequences.his_marks(trigger_store.list_for_song(uri))
        rows.append({"name": name, "uri": uri, "edm": edm, "available": True,
                     "reason": None, "score": drop_scoring.score_song(det, marks)})
    scored = [r for r in rows if r["available"]]
    return {
        "confident_score": confident,
        "suggested_score": suggested,
        "floor_score": floor,
        "songs": rows,
        "total": drop_scoring.totals([r["score"] for r in scored]) if scored else None,
        "edm_total": (drop_scoring.totals([r["score"] for r in scored],
                                          edm_only=[r["edm"] for r in scored])
                      if scored else None),
    }
