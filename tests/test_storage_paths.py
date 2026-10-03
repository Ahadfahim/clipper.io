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
