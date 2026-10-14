"""Read-only, metadata-only inventory of local photo archives.

No image bytes, sidecar contents, EXIF, face data, GPS or file paths leave
this process. Standard-library only. Intended as a safe initial archive pilot.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

JPEG_EXTENSIONS = frozenset({".jpg", ".jpeg"})
RAW_EXTENSIONS = frozenset(
    {".cr2", ".cr3", ".nef", ".arw", ".raf", ".rw2", ".orf", ".dng", ".pef", ".srw", ".3fr", ".iiq"}
)
PHOTO_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".avif", ".tif", ".tiff", ".bmp"}
) | RAW_EXTENSIONS
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".mts", ".m2ts"})
ARCHIVE_EXTENSIONS = frozenset({".zip", ".tar", ".tgz", ".7z", ".rar", ".zst"})
SIDECAR_EXTENSIONS = frozenset({".json", ".xmp"})
SKIP_DIRECTORIES = frozenset({".git", ".spotlight-v100", "$recycle.bin", "@eadir", "@__thumb"})


def inventory_root(root: Path, max_files: int = 0) -> dict[str, object]:
    """Return aggregate metadata, never source filenames or paths.

    Symlinks are not traversed. This only calls filesystem directory/stat
    operations, not open()/read() on any archive file. max_files=0 is unlimited.
    """
    if max_files < 0:
        raise ValueError("max_files must not be negative")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("root must be an accessible non-symlink directory")

    stats: dict[str, object] = {
        "photos": 0,
        "raw_photos": 0,
        "videos": 0,
        "archive_containers": 0,
        "archive_bytes": 0,
        "sidecars": 0,
        "media_bytes": 0,
        "raw_jpeg_pairs": 0,
        "directories": 0,
        "skipped_symlinks": 0,
        "errors": 0,
        "truncated": False,
    }
    extensions: Counter[str] = Counter()
    pending = [root]
    scanned_media = 0

    while pending:
        directory = pending.pop()
        if max_files and scanned_media >= max_files:
            stats["truncated"] = True
            break
        try:
            with os.scandir(directory) as entries:
                # Track only stems within one directory; do not retain names.
                raw_stems: set[str] = set()
                jpeg_stems: set[str] = set()
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            stats["skipped_symlinks"] += 1
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.casefold() not in SKIP_DIRECTORIES:
                                pending.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        suffix = Path(entry.name).suffix.lower()
                        if suffix in SIDECAR_EXTENSIONS:
                            stats["sidecars"] += 1
                            continue
                        if suffix in ARCHIVE_EXTENSIONS:
                            stats["archive_containers"] += 1
                            stats["archive_bytes"] += entry.stat(follow_symlinks=False).st_size
                            continue
                        if suffix not in PHOTO_EXTENSIONS and suffix not in VIDEO_EXTENSIONS:
                            continue
                        if max_files and scanned_media >= max_files:
                            stats["truncated"] = True
                            break
                        size = entry.stat(follow_symlinks=False).st_size
                        extensions[suffix] += 1
                        stats["media_bytes"] += size
                        scanned_media += 1
                        if suffix in PHOTO_EXTENSIONS:
                            stats["photos"] += 1
                            if suffix in RAW_EXTENSIONS:
                                stats["raw_photos"] += 1
                                raw_stems.add(Path(entry.name).stem.casefold())
                            elif suffix in JPEG_EXTENSIONS:
                                jpeg_stems.add(Path(entry.name).stem.casefold())
                        else:
                            stats["videos"] += 1
                    except OSError:
                        stats["errors"] += 1
                stats["raw_jpeg_pairs"] += len(raw_stems & jpeg_stems)
            stats["directories"] += 1
        except OSError:
            stats["errors"] += 1

    stats["by_extension"] = dict(sorted(extensions.items()))
    return stats


def scan_roots(roots: Sequence[Path], max_files: int = 0) -> dict[str, object]:
    """Label sources by position, not potentially private mount/album names."""
    if not roots:
        raise ValueError("provide at least one directory")
    result: dict[str, object] = {
        "version": 1,
        "mode": "stat-only; no photo files opened or uploaded",
        "sources": {},
    }
    for number, root in enumerate(roots, 1):
        result["sources"][f"source_{number}"] = inventory_root(root, max_files=max_files)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only photo archive preflight (aggregate counts only)"
    )
    parser.add_argument(
        "roots", nargs="+", type=Path, help="mounted photo directories; never altered"
    )
    parser.add_argument(
        "--max-files", type=int, default=0, help="limit media files per root for a pilot (0=all)"
    )
    args = parser.parse_args(argv)
    try:
        result = scan_roots(args.roots, max_files=args.max_files)
    except (OSError, ValueError) as exc:
        print(f"Archive scan failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
