"""LOCAL-VERIFY checks for the user's Windows machine (HANDOFF.md §4).

Skipped unless ``CLIPPER_LOCAL=1``. They read the real ``config/settings.toml`` (paths, models, GPU
env) and write only into pytest's temp folder:

    $env:CLIPPER_LOCAL = "1"; uv run pytest -m local -v

``test_whisperx_*`` also needs ``CLIPPER_SPEECH_SAMPLE`` (a short local video/audio file with speech).
``test_real_director_turn`` runs one real Claude turn on the plan login against fake adapters (no
marketplace, upload or Discord calls).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from clipper.db.engine import WriteTx
from clipper.media.edl.schema import new_edl
from clipper.settings import Settings, load_settings
from tests.media.conftest import talk_source, talk_words

pytestmark = pytest.mark.local

MEDIA = Path(__file__).parents[1] / "fixtures" / "media"


@pytest.fixture
def real(tmp_path: Path) -> Settings:
    """The machine's settings with the data folder moved into the temp dir."""
    return load_settings().with_data_dir(tmp_path / "data")


def test_ffmpeg_has_nvenc_and_libass(real: Settings) -> None:
    out = subprocess.run(
        [real.paths.ffmpeg("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True, check=True
    ).stdout
    assert "h264_nvenc" in out
    filters = subprocess.run(
        [real.paths.ffmpeg("ffmpeg"), "-hide_banner", "-filters"], capture_output=True, text=True, check=True
    ).stdout
    assert " ass " in filters or " subtitles " in filters


def test_nvenc_final_render(real: Settings, tmp_path: Path) -> None:
    from clipper.media.edl.render import render_edl
    from clipper.media.encode import NvencEncoder, final_profile
    from clipper.media.ffmpeg import probe

    edl = new_edl(talk_source(), 0.0, 10.0, words=talk_words())
    enc = NvencEncoder(real.media.nvenc_preset, real.media.final_bitrate)
    res = render_edl(edl, tmp_path / "final.mp4", final_profile(real.media), enc, real, tmp_path / "work")
    info = probe(res.path, real)
    assert (info.width, info.height, info.video_codec) == (1080, 1920, "h264")
    assert "h264_nvenc" in res.plan_args


def test_gpu_utilization_reads(real: Settings) -> None:
    from clipper.api.views import gpu_util

    util = gpu_util()
    assert util is not None and 0.0 <= util <= 1.0


@pytest.mark.skipif(not os.environ.get("CLIPPER_SPEECH_SAMPLE"), reason="set CLIPPER_SPEECH_SAMPLE")
def test_whisperx_transcribes_speech(real: Settings, tmp_path: Path) -> None:
    from clipper.media.transcribe import WhisperXTranscriber
    from clipper.secrets import get_secret

    sample = Path(os.environ["CLIPPER_SPEECH_SAMPLE"])
    audio = tmp_path / sample.name
    shutil.copy(sample, audio)
    _use_credential_manager()
    t = WhisperXTranscriber(real, hf_token=get_secret("hf_token")).transcribe(audio)
    assert len(t.words) >= 10
    starts = [w.start for w in t.words]
    assert starts == sorted(starts)
    assert all(w.end >= w.start for w in t.words)


def test_tesseract_reads_the_burned_in_watermark(real: Settings, tmp_path: Path) -> None:
    from clipper.media.ocr import TesseractOcr

    frame = tmp_path / "frame.png"
    subprocess.run(
        [real.paths.ffmpeg("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", "1",
         "-i", str(MEDIA / "talk_16x9.mp4"), "-frames:v", "1", str(frame)],
        check=True,
    )  # fmt: skip
    assert "WATERMARK" in TesseractOcr(ffmpeg=real.paths.ffmpeg("ffmpeg")).read(frame).upper()


def test_mediapipe_face_detector_loads(real: Settings) -> None:
    from clipper.media.faces import MediaPipeFaceDetector

    pytest.importorskip("mediapipe", reason="uv sync --all-packages --all-extras")
    # the synthetic test pattern has no faces; this proves the install, the model file and the API
    assert MediaPipeFaceDetector(real).track(MEDIA / "talk_16x9.mp4", 4.0, step=1.0) == []


def test_chrome_and_profiles_folder(real: Settings) -> None:
    from clipper.browser.launch import chrome_command

    assert Path(real.paths.chrome_exe).exists()
    cmd = chrome_command(real, "main", "https://www.youtube.com/")
    assert cmd[0] == str(real.paths.chrome_exe) and "--user-data-dir=" in cmd[1]


def _use_credential_manager() -> None:
    import keyring
    from keyring.backends.Windows import WinVaultKeyring

    keyring.set_keyring(WinVaultKeyring())  # the test session swaps in a memory backend


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager")
def test_credential_manager_round_trip() -> None:
    import keyring

    from clipper.secrets import SERVICE, delete_secret, get_secret

    _use_credential_manager()
    # set_secret only accepts the app's real secret names; write the probe straight through keyring so a
    # real token is never overwritten, then read and delete it through the app's own functions.
    keyring.set_password(SERVICE, "local_verify_probe", "ok")
    try:
        assert get_secret("local_verify_probe") == "ok"
    finally:
        delete_secret("local_verify_probe")
    assert get_secret("local_verify_probe") is None


async def test_real_director_turn(real: Settings, tmp_path: Path) -> None:
    """One Director turn on the Claude plan login: login, --agent main thread, tools, guard hook."""
    from sqlmodel import select

    from clipper.agents.runner import RunRequest, SdkAgentRunner
    from clipper.core import Core
    from clipper.db.models import AgentEvent, AgentSession
    from clipper.db.types import SessionStatus

    assert "ANTHROPIC_API_KEY" not in os.environ  # tests/conftest.py scrubs it; the runner blanks it too
    core = Core.create(real, fakes=True, db_path=tmp_path / "agent.sqlite")

    def new_session(tx: WriteTx) -> int:
        sess = AgentSession(role="director", status=SessionStatus.RUNNING)
        tx.add(sess)
        tx.flush()
        assert sess.id is not None
        return sess.id

    try:
        sid = core.db.write(new_session)
        outcome = await SdkAgentRunner(core).run(
            RunRequest(
                role="director",
                kind="user.chat",
                prompt="Call the get_usage tool once, then reply with one short sentence about it.",
                session_id=sid,
            )
        )
        assert outcome.error is None and not outcome.rate_limited, outcome.error
        assert outcome.sdk_session_id
        with core.db.read() as s:
            events = s.exec(select(AgentEvent).where(AgentEvent.session_id == sid)).all()
    finally:
        core.close()
    calls = [e.tool or "" for e in events if e.type == "tool_call"]
    assert any(c.endswith("get_usage") for c in calls), calls
    assert not [e for e in events if e.type == "blocked"]
