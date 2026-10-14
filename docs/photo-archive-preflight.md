# Photo archive preflight (experimental, local-only)

Before importing years of Google Photos or DSLR photos into a wardrobe, establish the formats and scale **without editing, uploading, decoding, or copying originals**.

## Usage (Python 3.11+, no dependencies)

Run on the computer where the archive drives are mounted. Substitute your actual paths, not guessed drive names.

```bash
python backend/scripts/photo_archive_inventory.py --max-files 500 "/path/to/google-photos" "/path/to/dslr-archive"
python backend/scripts/photo_archive_inventory.py "/path/to/google-photos" "/path/to/dslr-archive" > ~/photo-archive-summary.json
```

Only directory listing and file-stat operations are performed. Output is an aggregate JSON summary of counts, file bytes, RAW+JPEG filename-pair candidates, formats, JSON/XMP sidecars, errors and pilot truncation. Symlinks and known OS metadata directories are skipped. This does not require enough free space to copy a multi-terabyte archive.

**Privacy:** The report uses `source_1` and `source_2`, not original file paths or names. It includes no images, EXIF/GPS, faces, or Takeout sidecar contents. Do not publish private image samples or other personal archive metadata in a public issue or PR.

**Limitations:** RAW+JPEG pairs are filename-based *candidates*, not verified duplicates. Google Takeout `.json` sidecars are counted, not parsed or matched. The tool does not perform detection, recognition, or wardrobe imports. A read-only scan can still generate disk I/O; try a limited pilot first. Never use this tool to infer a successful scan if errors > 0 or truncated is true.

## Next research stage

Use a small, consented and non-public pilot (e.g. 100–200 photos) covering phone selfies, group pictures, trip photos, and DSLR RAW+JPEG pairs. Measure correct-person selection, garment recall, same-garment matching across photos, false merging and human review effort. Keep the archive local and evaluate optional Immich read-only external libraries before any full ingest.

This helper is a fork-local prototype, not a claim that upstream maintains a Google Photos/Takeout importer.
