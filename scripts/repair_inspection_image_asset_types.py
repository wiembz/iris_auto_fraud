"""Repair MIME types/extensions for already imported STAFIM assets.

Some Google Drive files are PDF documents containing inspection photos. If Drive
served them as application/octet-stream, older imports may have stored them as
`.bin`, making browsers download them instead of opening them. This script
inspects file signatures, renames files when needed, and updates
app.inspection_image_asset metadata.

Usage:
  python scripts/repair_inspection_image_asset_types.py --dry-run
  python scripts/repair_inspection_image_asset_types.py
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import load_config
from backend.db import get_engine
from backend.services.inspection_image_service import resolve_asset_path, storage_root


def detect_type(payload: bytes) -> tuple[str, str]:
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
    return "application/octet-stream", ".bin"


def run(dry_run: bool) -> dict[str, int]:
    config = load_config()
    root = storage_root(config)
    engine = get_engine()
    stats = {"checked": 0, "updated": 0, "missing": 0, "unknown": 0}
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT asset_id, relative_path, mime_type
                FROM app.inspection_image_asset
                WHERE storage_status = 'IMPORTED'
                  AND relative_path IS NOT NULL
                ORDER BY asset_id
                """
            )
        ).mappings().all()
        for row in rows:
            stats["checked"] += 1
            current_rel = row["relative_path"]
            path = resolve_asset_path(config, current_rel)
            if path is None or not path.exists():
                stats["missing"] += 1
                continue
            payload = path.read_bytes()
            mime_type, ext = detect_type(payload)
            if mime_type == "application/octet-stream":
                stats["unknown"] += 1
            target = path
            target_rel = current_rel
            if path.suffix.lower() != ext:
                target = path.with_suffix(ext)
                target_rel = target.relative_to(root).as_posix()
            needs_update = (
                row.get("mime_type") != mime_type
                or target_rel != current_rel
                or path.suffix.lower() != ext
            )
            if not needs_update:
                continue
            print(f"asset {row['asset_id']}: {current_rel} -> {target_rel} | {row.get('mime_type')} -> {mime_type}")
            if dry_run:
                stats["updated"] += 1
                continue
            if target != path:
                if target.exists():
                    target.unlink()
                path.rename(target)
            conn.execute(
                text(
                    """
                    UPDATE app.inspection_image_asset
                    SET relative_path = :relative_path,
                        mime_type = :mime_type,
                        file_size_bytes = :file_size_bytes,
                        sha256 = :sha256,
                        updated_at = (now() AT TIME ZONE 'utc')
                    WHERE asset_id = :asset_id
                    """
                ),
                {
                    "asset_id": row["asset_id"],
                    "relative_path": target_rel,
                    "mime_type": mime_type,
                    "file_size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
            )
            stats["updated"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair imported STAFIM image/PDF MIME metadata.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    stats = run(args.dry_run)
    print("repair finished: " + ", ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
