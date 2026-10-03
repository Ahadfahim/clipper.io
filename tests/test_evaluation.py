from __future__ import annotations

from clipper.evaluation import iou, run_eval, score_source


def test_iou() -> None:
    assert iou((0, 10), (5, 15)) == 5 / 15
    assert iou((0, 10), (20, 30)) == 0


def test_score_rewards_matching_and_penalizes_rejected_lookalikes() -> None:
    approved = [(10.0, 40.0), (100.0, 130.0)]
    rejected = [(200.0, 230.0)]
    perfect = score_source([(11.0, 39.0), (101.0, 131.0)], approved, rejected)
    assert perfect.score == 1.0
    half = score_source([(11.0, 39.0), (500.0, 530.0)], approved, rejected)
    assert half.recall == 0.5 and half.precision == 0.5 and half.score == 0.5
    bad = score_source([(201.0, 229.0)], approved, rejected)
    assert bad.rejected_hits == 1.0 and bad.score == 0.0
    assert score_source([], approved, rejected).score == 0.0


def test_eval_with_empty_manifest_is_a_no_op() -> None:
    assert run_eval() == 0
