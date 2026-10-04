# Quality test set (PLAN §14)

`clipper eval` re-runs the editor on these sources and scores its picks against your decisions.

`manifest.json`:
```json
{
  "baseline": 0.62,
  "sources": [
    {
      "id": "mrbeast-42-src1",
      "path": "C:\\ClipperData\\golden\\mrbeast-42-src1.mp4",
      "spec": {"duration_min_s": 15, "duration_max_s": 60},
      "approved": [[751.0, 793.0], [1210.5, 1248.0]],
      "rejected": [[300.0, 330.0]]
    }
  ]
}
```

- 10 fixed source videos (kept outside the repo: they're large), each with the clip ranges you approved and some you rejected.
- `baseline` is the score of the current production prompts/model/effort; raise it when a change improves it.
- Scoring (`clipper.evaluation.score_source`): half recall of approved clips, half precision of picks, minus half the share of picks that overlap a rejected clip (IoU >= 0.5).
