"""Generate JPEG previews for imported HEIC STAFIM inspection photos.

The original HEIC files are preserved for audit. The generated JPEG preview is
used by the Angular UI so HEIC photos display like regular photos in browsers.

Usage:
  python backend/migrations/005_add_inspection_image_previews.py
  python scripts/generate_heic_inspection_previews.py --dry-run
  python scripts/generate_heic_inspection_previews.py

If `heif-convert` is not in PATH, set:
  $env:HEIF_CONVERT_BIN="C:\\path\\to\\heif-convert.cmd"
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import load_config
from backend.db import get_engine
from backend.services.inspection_image_service import resolve_asset_path, storage_root


def _converter() -> str:
    import os
    configured = os.getenv("HEIF_CONVERT_BIN")
    if configured:
        return configured
    found = shutil.which("heif-convert") or shutil.which("heif-convert.cmd") or shutil.which("heif-convert.exe")
    if not found:
        raise RuntimeError("heif-convert introuvable. Definir HEIF_CONVERT_BIN ou installer libheif-tools.")
    return found


def _preview_relative_path(original_relative_path: str) -> str:
    path = Path(original_relative_path)
    return (path.parent / f"{path.stem}_preview.jpg").as_posix()


def run(dry_run: bool, quality: int) -> dict[str, int]:
    config = load_config()
    root = storage_root(config)
    converter = _converter()
    engine = get_engine()
    stats = {"candidates": 0, "generated": 0, "skipped": 0, "failed": 0}
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT asset_id, relative_path, preview_relative_path
                FROM app.inspection_image_asset
                WHERE storage_status = 'IMPORTED'
                  AND mime_type IN ('image/heic', 'image/heif')
                  AND relative_path IS NOT NULL
                ORDER BY asset_id
                """
            )
        ).mappings().all()
        stats["candidates"] = len(rows)
        for row in rows:
            source = resolve_asset_path(config, row["relative_path"])
            if source is None or not source.exists():
                stats["failed"] += 1
                print(f"missing source asset {row['asset_id']}: {row['relative_path']}")
                continue
            preview_rel = row.get("preview_relative_path") or _preview_relative_path(row["relative_path"])
            preview = (root / preview_rel).resolve()
            preview.parent.mkdir(parents=True, exist_ok=True)
            if preview.exists() and not dry_run:
                stats["skipped"] += 1
            else:
                print(f"asset {row['asset_id']}: {row['relative_path']} -> {preview_rel}")
                if not dry_run:
                    result = subprocess.run(
                        [converter, "-q", str(quality), str(source), str(preview)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode != 0 or not preview.exists():
                        stats["failed"] += 1
                        print((result.stderr or result.stdout or "conversion failed").strip())
                        continue
                    stats["generated"] += 1
                else:
                    stats["generated"] += 1
            if not dry_run:
                conn.execute(
                    text(
                        """
                        UPDATE app.inspection_image_asset
                        SET preview_relative_path = :preview_relative_path,
                            preview_mime_type = 'image/jpeg',
                            updated_at = (now() AT TIME ZONE 'utc')
                        WHERE asset_id = :asset_id
                        """
                    ),
                    {"asset_id": row["asset_id"], "preview_relative_path": preview_rel},
                )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JPEG previews for HEIC STAFIM photos.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quality", type=int, default=88)
    args = parser.parse_args()
    stats = run(args.dry_run, args.quality)
    print("HEIC preview generation finished: " + ", ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
