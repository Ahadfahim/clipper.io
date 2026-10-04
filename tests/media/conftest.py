from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipper.media.edl.schema import CaptionWord, Edl, SourceInfo, new_edl

MEDIA = Path(__file__).parents[1] / "fixtures" / "media"
TALK = MEDIA / "talk_16x9.mp4"
QA_BAD = MEDIA / "qa_bad.mp4"


def talk_words() -> list[CaptionWord]:
    data = json.loads((MEDIA / "talk_16x9.words.json").read_text())
    return [
        CaptionWord(t=w["start"], end=w["end"], text=w["text"], speaker=w.get("speaker"))
        for w in data["words"]
    ]


def talk_source() -> SourceInfo:
    return SourceInfo(source_id=1, path=str(TALK.resolve()), duration=10.0, width=960, height=540, fps=30.0)


@pytest.fixture
def edl() -> Edl:
    return new_edl(talk_source(), 0.0, 10.0, words=talk_words())


# silences in the fixture audio: the tone is off 1.4-2.0, 3.4-4.0, ... (2 s period)
FIXTURE_SILENCES = [(1.4 + 2 * i, 2.0 + 2 * i) for i in range(5)]
