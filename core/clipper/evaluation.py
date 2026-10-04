"""``clipper eval``: the quality test set (PLAN §14).

``tests/golden/manifest.json`` lists fixed source videos with the clips the user approved and rejected.
The editor re-picks moments for each source; the score says how well its picks overlap the approved
clips and how often rejected-style moments come back. Any change to prompts, model or effort must not
lower it before going live (the Settings -> Agents "Save" button runs this).

Scoring is pure (``score_source``); picking needs a real agent run (LOCAL-VERIFY).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clipper.settings import REPO_ROOT

GOLDEN = REPO_ROOT / "tests" / "golden" / "manifest.json"
Range = tuple[float, float]


def iou(a: Range, b: Range) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


@dataclass(frozen=True)
class SourceScore:
    recall: float  # share of approved clips matched by a pick (IoU >= threshold)
    precision: float  # share of picks that match an approved clip
    rejected_hits: float  # share of picks that look like a rejected clip
    score: float  # recall*0.5 + precision*0.5 - rejected_hits*0.5, clamped to 0..1


def score_source(
    picks: list[Range], approved: list[Range], rejected: list[Range], threshold: float = 0.5
) -> SourceScore:
    if not picks:
        return SourceScore(0.0, 0.0, 0.0, 0.0)
    matched_approved = sum(1 for a in approved if any(iou(a, p) >= threshold for p in picks))
    good_picks = sum(1 for p in picks if any(iou(a, p) >= threshold for a in approved))
    bad_picks = sum(1 for p in picks if any(iou(r, p) >= threshold for r in rejected))
    recall = matched_approved / len(approved) if approved else 1.0
    precision = good_picks / len(picks)
    rejected_hits = bad_picks / len(picks)
    total = max(0.0, min(1.0, 0.5 * recall + 0.5 * precision - 0.5 * rejected_hits))
    return SourceScore(round(recall, 3), round(precision, 3), round(rejected_hits, 3), round(total, 3))


def load_manifest(path: Path = GOLDEN) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("sources", []))


def run_eval(picker: Any = None, path: Path = GOLDEN) -> int:
    """Re-pick every golden source and print the scores. Exit code 1 when below the baseline."""
    sources = load_manifest(path)
    if not sources:
        print(
            f"no golden sources in {path}; add the 10 fixed videos and your approved/rejected clips (README there)"
        )
        return 0
    if picker is None:
        print("clipper eval needs a real editor run on the Claude plan login (LOCAL-VERIFY); see HANDOFF §7")
        return 2
    scores: list[float] = []
    for src in sources:
        picks = [tuple(p) for p in picker(src)]
        s = score_source(
            picks, [tuple(a) for a in src["approved"]], [tuple(r) for r in src.get("rejected", [])]
        )  # type: ignore[arg-type]
        scores.append(s.score)
        print(
            f"{src['id']:24s} score {s.score:.2f}  recall {s.recall:.2f}  precision {s.precision:.2f}  rejected-like {s.rejected_hits:.2f}"
        )
    mean = sum(scores) / len(scores)
    baseline = float(json.loads(path.read_text(encoding="utf-8")).get("baseline", 0.0))
    print(f"mean {mean:.3f} (baseline {baseline:.3f})")
    return 0 if mean >= baseline else 1
