"""yt-dlp: readable errors, how old the install is, the one-click update, and failed download jobs."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlmodel import select

from clipper.core import Core
from clipper.db.models import Job, Source
from clipper.db.types import JobStatus, SourceStatus
from clipper.doctor import check_yt_dlp
from clipper.media.download import DownloadError, clean_ytdlp_error
from clipper.media.ytdlp_update import age_days, release_date, update_ytdlp
from clipper.settings import Settings
from tests.factories import make_campaign

# what yt-dlp printed for the Frame.io share link on 2026-10-03
FRAMEIO_STDERR = """WARNING: Your yt-dlp version (2026.03.17) is older than 90 days!
         It is strongly recommended to always use the latest version.
         You installed yt-dlp with pip or using the wheel from PyPi; Use that to update.
         To suppress this warning, add --no-update to your command/config.
WARNING: [generic] Falling back on generic information extractor
ERROR: Unsupported URL: https://next.frame.io/share/9d3a07f5-9dbf-4acd-8028-86879ad0028b/view/3ea7e8a1
"""


def test_the_error_line_wins_over_the_out_of_date_warning() -> None:
    reason, tail = clean_ytdlp_error(FRAMEIO_STDERR)
    assert reason == "This site isn't supported by the downloader"
    assert tail.endswith("view/3ea7e8a1") and "older than 90 days" in tail  # the full output is kept


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "ERROR: unable to download video data: HTTP Error 403: Forbidden",
            "The host refused the download (403)",
        ),
        ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", "YouTube asked for a sign-in check"),
        (
            "ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
            "The video is private",
        ),
        ("ERROR: something nobody has seen before", "something nobody has seen before"),
        ("WARNING: only a warning\nsome trailing line", "some trailing line"),
        ("", "yt-dlp failed without saying why"),
    ],
)
def test_known_errors_get_a_plain_sentence(stderr: str, expected: str) -> None:
    assert clean_ytdlp_error(stderr)[0] == expected


def test_release_dates_and_age() -> None:
    assert release_date("2026.03.17") == date(2026, 3, 17)
    assert release_date("2026.03.17.232541") == date(2026, 3, 17)  # nightly
    assert release_date("garbage") is None
    assert age_days("2026.03.17", date(2026, 10, 4)) == 201
    assert age_days("nope", date(2026, 10, 4)) is None


def test_the_doctor_warns_when_yt_dlp_is_old(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("clipper.doctor._run", lambda cmd, timeout=20.0: (0, "2026.03.17\n"))
    monkeypatch.setattr("clipper.doctor.shutil.which", lambda name: "deno")
    settings = Settings()
    old = check_yt_dlp(settings, today=date(2026, 10, 4))
    assert old.status == "warn" and "201 days old" in old.detail and "Update yt-dlp" in old.fix
    assert check_yt_dlp(settings, today=date(2026, 4, 1)).status == "ok"


class _Shell:
    """Stands in for the command line: answers by the command it is given."""

    def __init__(self, answers: dict[str, tuple[int, str]]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []
        self.version = "2026.03.17"

    def __call__(self, cmd: list[str]) -> tuple[int, str]:
        self.calls.append(cmd)
        if "--version" in cmd:
            return 0, self.version + "\n"
        if "-U" in cmd:
            return self.answers["-U"]
        if "pip" in cmd:
            self.version = "2026.08.19"
            return self.answers["pip"]
        raise AssertionError(cmd)


def test_update_uses_pip_when_yt_dlp_was_installed_with_pip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    py = tmp_path / "python.exe"
    py.write_text("")
    monkeypatch.setattr("clipper.media.ytdlp_update._owning_python", lambda exe: str(py))
    shell = _Shell(
        {"-U": (1, "ERROR: You installed yt-dlp with pip or using the wheel from PyPi"), "pip": (0, "ok")}
    )
    res = update_ytdlp("yt-dlp", run=shell)
    assert (
        res.ok
        and (res.before, res.after) == ("2026.03.17", "2026.08.19")
        and "updated to 2026.08.19" in res.detail
    )
    assert [str(py), "-m", "pip", "install", "--upgrade", "yt-dlp"] in shell.calls


def test_update_reports_a_failure_and_a_missing_install() -> None:
    shell = _Shell({"-U": (1, "ERROR: no network")})
    res = update_ytdlp("yt-dlp", run=shell)
    assert not res.ok and "no network" in res.detail
    assert not update_ytdlp("yt-dlp", run=lambda cmd: (127, "not found")).ok


def test_a_failed_download_job_stores_the_reason_and_the_full_output(
    core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    camp = make_campaign(core.db)
    assert camp.id is not None

    def boom(url: str, dest: Path) -> None:
        reason, tail = clean_ytdlp_error(FRAMEIO_STDERR)
        raise DownloadError(reason, tail)

    monkeypatch.setattr(core.adapters.downloader, "download", boom)
    res = core.media.request_download(camp.id, "https://f.io/rnWUqe5F")
    asyncio.run(core.jobs.drain(timeout=30))
    with core.db.read() as s:
        job = s.get(Job, res["job_id"])
        src = s.exec(select(Source)).one()
    assert job is not None and job.status == JobStatus.FAILED
    assert job.error is not None and job.error.startswith("This site isn't supported by the downloader")
    assert "older than 90 days" not in job.error and "RuntimeError" not in job.error
    assert "older than 90 days" in job.result_json["raw_tail"]
    assert src.status == SourceStatus.FAILED
