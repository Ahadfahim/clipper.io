"""`clipper seed --fixtures` never writes demo data into the real database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from clipper import cli


def test_demo_seed_refuses_the_real_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CLIPPER_DATA_DIR", raising=False)
    with pytest.raises(SystemExit) as exit_:
        cli.main(["seed", "--fixtures"])
    assert exit_.value.code == 2 and "refusing to put demo data" in capsys.readouterr().err


def test_demo_seed_goes_into_a_scratch_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLIPPER_DATA_DIR", str(tmp_path))
    from clipper import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exit_:
            cli.main(["migrate"])
        assert exit_.value.code == 0
        with pytest.raises(SystemExit) as exit_:
            cli.main(["seed", "--fixtures"])
        assert exit_.value.code == 0
    finally:
        settings_mod.get_settings.cache_clear()
    with sqlite3.connect(tmp_path / "clipper.sqlite") as db:
        assert db.execute("select count(*) from campaign").fetchone()[0] > 0
