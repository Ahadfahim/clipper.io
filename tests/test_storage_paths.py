"""Source-video folder: platform default, follows test data folders, validated when saved from the app."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from clipper.api.settings_file import patch_settings_file
from clipper.settings import Settings, load_settings


def test_default_sources_folder_is_on_c_on_windows() -> None:
    expected = Path(r"C:\ClipperData\sources") if os.name == "nt" else None
    assert Settings().paths.sources_dir == expected


def test_a_moved_data_folder_takes_the_default_sources_folder_with_it(tmp_path: Path) -> None:
    moved = Settings().with_data_dir(tmp_path)
    assert moved.paths.sub("sources") == tmp_path / "sources"


def test_a_chosen_sources_folder_stays_put(tmp_path: Path) -> None:
    chosen = tmp_path / "big-drive" / "sources"
    s = load_settings(tmp_path / "none.toml", overrides={"paths": {"sources_dir": str(chosen)}})
    assert s.with_data_dir(tmp_path / "data").paths.sub("sources") == chosen


def test_saving_a_folder_creates_it(tmp_path: Path) -> None:
    folder = tmp_path / "sources"
    target = patch_settings_file({"paths.sources_dir": str(folder)}, tmp_path / "settings.toml")
    assert folder.is_dir() and str(folder).replace("\\", "\\\\") in target.read_text(encoding="utf-8")


def test_saving_a_relative_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="full path"):
        patch_settings_file({"paths.sources_dir": "sources"}, tmp_path / "settings.toml")
    assert not (tmp_path / "settings.toml").exists()


def test_isolated_settings_move_every_folder_even_ones_you_chose(tmp_path: Path) -> None:
    chosen = {
        "sources_dir": str(tmp_path / "real" / "sources"),
        "clips_dir": str(tmp_path / "real" / "clips"),
        "backups_dir": str(tmp_path / "real" / "backups"),
        "chrome_profiles_dir": str(tmp_path / "real" / "chrome"),
    }
    s = load_settings(tmp_path / "none.toml", overrides={"paths": chosen})
    demo = s.isolated(tmp_path / "demo")
    for name in ("sources", "clips", "backups", "work", "previews", "logs", "screenshots"):
        assert demo.paths.sub(name) == tmp_path / "demo" / name
    assert demo.paths.chrome_profiles_dir == tmp_path / "demo" / "chrome"
    assert demo.paths.database == tmp_path / "demo" / "clipper.sqlite"
    assert s.paths.sub("sources") == tmp_path / "real" / "sources"  # the original is untouched


def test_fake_adapters_refuse_a_sources_folder_outside_the_data_folder(tmp_path: Path) -> None:
    from clipper.core import Core

    s = load_settings(
        tmp_path / "none.toml",
        overrides={"paths": {"data_dir": str(tmp_path / "data"), "sources_dir": str(tmp_path / "real")}},
    )
    with pytest.raises(RuntimeError, match="outside the data folder"):
        Core.create(s, fakes=True)
    Core.create(s.isolated(tmp_path / "demo"), fakes=True).close()
