"""Attach a local inspection image/PDF file to an IRIS STAFIM asset.

Use this when a Google Drive source is visible to the user in the browser but not
importable by the server/importer because Drive requires an authenticated Google
session. The original source URL remains in app.inspection_image_asset; this
script only provides a platform-owned local copy.

Examples:
  python scripts/import_local_inspection_asset.py --asset-id 791 --file "C:\\Users\\wiem\\Downloads\\20250811_115313 - selection auto.pdf"
  python scripts/import_local_inspection_asset.py --inspection-key 2443TU169_20251002_0 --slot image1 --file "C:\\path\\selection auto.pdf"
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import load_config
from backend.db import get_engine
from backend.services.inspection_image_service import ensure_image_asset_table, storage_root


def _safe_part(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "unknown").strip())
    return cleaned.strip("._") or "unknown"


def detect_type(payload: bytes, source: Path) -> tuple[str, str]:
    head = payload[:16]
    if head.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if head.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if len(payload) >= 12 and payload[4:8] == b"ftyp" and payload[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
        return "image/heic", ".heic"
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf", ".pdf"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg", ".jpg"
    if suffix == ".png":
        return "image/png", ".png"
    if suffix in {".heic", ".heif"}:
        return "image/heic", ".heic"
    return "application/octet-stream", suffix or ".bin"


def _find_asset(conn, asset_id: int | None, inspection_key: str | None, slot: str | None):
    if asset_id is not None:
        row = conn.execute(
            text(
                """
                SELECT asset_id, inspection_key, slot, original_url
                FROM app.inspection_image_asset
                WHERE asset_id = :asset_id
                LIMIT 1
                """
            ),
            {"asset_id": asset_id},
        ).mappings().first()
    else:
        row = conn.execute(
            text(
                """
                SELECT asset_id, inspection_key, slot, original_url
                FROM app.inspection_image_asset
                WHERE inspection_key = :inspection_key
                  AND slot = :slot
                LIMIT 1
                """
            ),
            {"inspection_key": inspection_key, "slot": slot},
        ).mappings().first()
    return dict(row) if row else None


def run(asset_id: int | None, inspection_key: str | None, slot: str | None, file_path: Path) -> dict:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(file_path)
    if asset_id is None and (not inspection_key or not slot):
        raise ValueError("Provide either --asset-id or both --inspection-key and --slot.")

    payload = file_path.read_bytes()
    mime_type, ext = detect_type(payload, file_path)
    digest = hashlib.sha256(payload).hexdigest()

    config = load_config()
    root = storage_root(config)
    root.mkdir(parents=True, exist_ok=True)

    engine = get_engine()
    with engine.begin() as conn:
        ensure_image_asset_table(conn)
        asset = _find_asset(conn, asset_id, inspection_key, slot)
        if asset is None:
            raise RuntimeError("Asset metadata not found. Import Drive candidates first or provide a valid inspection_key/slot.")

        rel_dir = Path(_safe_part(asset["inspection_key"]))
        filename = f"{_safe_part(asset['slot'])}_{digest[:12]}{ext}"
        rel_path = (rel_dir / filename).as_posix()
        abs_path = root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, abs_path)

        conn.execute(
            text(
                """
                UPDATE app.inspection_image_asset
                SET storage_status = 'IMPORTED',
                    relative_path = :relative_path,
                    mime_type = :mime_type,
                    file_size_bytes = :file_size_bytes,
                    sha256 = :sha256,
                    import_error = NULL,
                    preview_relative_path = NULL,
                    preview_mime_type = NULL,
                    imported_at = COALESCE(imported_at, now() AT TIME ZONE 'utc'),
                    updated_at = (now() AT TIME ZONE 'utc')
                WHERE asset_id = :asset_id
                """
            ),
            {
                "asset_id": asset["asset_id"],
                "relative_path": rel_path,
                "mime_type": mime_type,
                "file_size_bytes": len(payload),
                "sha256": digest,
            },
        )

    return {
        "asset_id": asset["asset_id"],
        "inspection_key": asset["inspection_key"],
        "slot": asset["slot"],
        "relative_path": rel_path,
        "mime_type": mime_type,
        "file_size_bytes": len(payload),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Attach a local inspection file to an IRIS image asset.")
    parser.add_argument("--asset-id", type=int)
    parser.add_argument("--inspection-key")
    parser.add_argument("--slot")
    parser.add_argument("--file", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.asset_id, args.inspection_key, args.slot, args.file)
    print("Local inspection asset imported:")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
