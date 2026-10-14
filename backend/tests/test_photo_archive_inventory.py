"""File-system-only tests; no personal photos and no image decoding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.photo_archive_inventory import inventory_root, main, scan_roots


def touch(path: Path, size: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_photo_types_and_raw_jpeg_pairs(tmp_path: Path) -> None:
    touch(tmp_path / "Trip" / "DSC_001.CR3", 17)
    touch(tmp_path / "Trip" / "DSC_001.jpg", 9)
    touch(tmp_path / "Trip" / "img2.NEF", 5)
    touch(tmp_path / "Takeout" / "photo.HEIC", 7)
    touch(tmp_path / "Takeout" / "photo.HEIC.supplemental-metadata.json", 2)
    touch(tmp_path / "Takeout" / "IMG_002.JPG.xmp", 2)
    touch(tmp_path / "Trip" / "video.MOV", 11)
    touch(tmp_path / "Takeout" / "takeout-part-1.zip", 60)
    touch(tmp_path / "Trip" / "other.txt", 20)

    stats = inventory_root(tmp_path)
    assert stats["photos"] == 4
    assert stats["raw_photos"] == 2
    assert stats["videos"] == 1
    assert stats["sidecars"] == 2
    assert stats["archive_containers"] == 1
    assert stats["archive_bytes"] == 60
    assert stats["raw_jpeg_pairs"] == 1
    assert stats["media_bytes"] == 49
    assert stats["by_extension"][".cr3"] == 1
    assert stats["by_extension"][".heic"] == 1
    assert stats["truncated"] is False


def test_stat_only_does_not_read_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    touch(tmp_path / "outfit.jpg", 13)

    def reject_read(*args: object, **kwargs: object) -> None:
        raise AssertionError("image bytes must never be read")

    monkeypatch.setattr(Path, "open", reject_read)
    stats = inventory_root(tmp_path)
    assert stats["photos"] == 1
    assert stats["media_bytes"] == 13


def test_skips_symlinks_and_system_directories(tmp_path: Path) -> None:
    touch(tmp_path / "private" / "photo.jpg", 10)
    touch(tmp_path / ".git" / "ignored.jpg", 20)
    (tmp_path / "link.jpg").symlink_to(tmp_path / "private" / "photo.jpg")
    (tmp_path / "recursive").symlink_to(tmp_path, target_is_directory=True)

    stats = inventory_root(tmp_path)
    assert stats["photos"] == 1
    assert stats["skipped_symlinks"] == 2


def test_aggregate_output_does_not_leak_paths_or_exif(tmp_path: Path) -> None:
    touch(tmp_path / "private-family-trip" / "DSC_SECRET.ARW")
    report = json.dumps(scan_roots([tmp_path]))
    assert "source_1" in report
    assert "DSC_SECRET" not in report
    assert "private-family-trip" not in report
    assert str(tmp_path) not in report
    assert "location" not in report


def test_missing_or_symlink_root_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        inventory_root(tmp_path / "missing")
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        inventory_root(tmp_path / "alias")


def test_pilot_cap(tmp_path: Path) -> None:
    for i in range(5):
        touch(tmp_path / f"pic{i:02d}.jpg")
    result = inventory_root(tmp_path, max_files=2)
    assert result["photos"] == 2
    assert result["truncated"] is True
    with pytest.raises(ValueError):
        inventory_root(tmp_path, max_files=-1)


def test_cli_outputs_anonymous_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    touch(tmp_path / "some-private-folder" / "IMG_1.JPG")
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["sources"]["source_1"]["photos"] == 1
    assert "some-private-folder" not in out
