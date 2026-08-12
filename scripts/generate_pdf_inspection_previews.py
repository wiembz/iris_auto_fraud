"""Generate JPEG previews for imported PDF STAFIM inspection documents.

Some STAFIM Drive links point to a PDF document containing the inspection photos
instead of a direct JPEG/PNG file. IRIS keeps the original PDF as documentary
evidence and generates a browser-friendly JPEG preview from page 1 so the UI can
show it like the other photos.

Usage:
  python backend/migrations/005_add_inspection_image_previews.py
  python scripts/generate_pdf_inspection_previews.py --dry-run
  python scripts/generate_pdf_inspection_previews.py

If `pdftoppm` is not in PATH, set:
  $env:PDFTOPPM_BIN="C:\\Users\\wiem\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\bin\\override\\pdftoppm.cmd"
"""
from __future__ import annotations

import argparse
import os
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


def _pdftoppm_bin() -> str:
    configured = os.getenv("PDFTOPPM_BIN")
    if configured:
        return configured
    found = shutil.which("pdftoppm") or shutil.which("pdftoppm.cmd") or shutil.which("pdftoppm.exe")
    if not found:
        raise RuntimeError("pdftoppm introuvable. Definir PDFTOPPM_BIN ou installer Poppler.")
    return found


def _preview_relative_path(original_relative_path: str) -> str:
    path = Path(original_relative_path)
    return (path.parent / f"{path.stem}_preview.jpg").as_posix()


def _render_pdf_first_page(pdftoppm: str, source: Path, preview: Path, dpi: int) -> None:
    prefix = preview.with_suffix("")
    result = subprocess.run(
        [
            pdftoppm,
            "-jpeg",
            "-r",
            str(dpi),
            "-f",
            "1",
            "-singlefile",
            str(source),
            str(prefix),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not preview.exists():
        raise RuntimeError((result.stderr or result.stdout or "pdftoppm conversion failed").strip())


def run(dry_run: bool, dpi: int, asset_id: int | None = None) -> dict[str, int]:
    config = load_config()
    root = storage_root(config)
    pdftoppm = _pdftoppm_bin()
    engine = get_engine()
    stats = {"candidates": 0, "generated": 0, "skipped": 0, "failed": 0}
    where_asset = "AND asset_id = :asset_id" if asset_id is not None else ""
    params = {"asset_id": asset_id} if asset_id is not None else {}

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT asset_id, relative_path, preview_relative_path
                FROM app.inspection_image_asset
                WHERE storage_status = 'IMPORTED'
                  AND mime_type = 'application/pdf'
                  AND relative_path IS NOT NULL
                  {where_asset}
                ORDER BY asset_id
                """
            ),
            params,
        ).mappings().all()
        stats["candidates"] = len(rows)
        for row in rows:
            source = resolve_asset_path(config, row["relative_path"])
            if source is None or not source.exists():
                stats["failed"] += 1
                print(f"missing PDF asset {row['asset_id']}: {row['relative_path']}")
                continue

            preview_rel = row.get("preview_relative_path") or _preview_relative_path(row["relative_path"])
            preview = (root / preview_rel).resolve()
            preview.parent.mkdir(parents=True, exist_ok=True)

            if preview.exists() and not dry_run:
                stats["skipped"] += 1
            else:
                print(f"asset {row['asset_id']}: {row['relative_path']} -> {preview_rel}")
                if dry_run:
                    stats["generated"] += 1
                else:
                    try:
                        _render_pdf_first_page(pdftoppm, source, preview, dpi)
                    except RuntimeError as exc:
                        stats["failed"] += 1
                        print(str(exc))
                        continue
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
    parser = argparse.ArgumentParser(description="Generate JPEG previews for PDF STAFIM inspection documents.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dpi", type=int, default=160)
    parser.add_argument("--asset-id", type=int, default=None)
    args = parser.parse_args()
    stats = run(args.dry_run, args.dpi, args.asset_id)
    print("PDF preview generation finished: " + ", ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
