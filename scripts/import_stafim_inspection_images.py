"""Import STAFIM inspection photos into IRIS-controlled local storage.

Why this exists
---------------
The raw STAFIM workbook stores `image1`..`image10` as Google Drive URLs. A Drive
URL is not a reliable platform asset: only Google accounts with access can open
it. This importer copies accessible photos into `data/inspection_images` and
records metadata in `app.inspection_image_asset`.

If Drive denies access, the row is still recorded as NOT_IMPORTED with the
source URL and error. That makes the UX honest and keeps the audit trail.

Usage examples
--------------
  python scripts/import_stafim_inspection_images.py --limit 20
  python scripts/import_stafim_inspection_images.py --force
  python scripts/import_stafim_inspection_images.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import html
import mimetypes
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import load_config
from backend.db import get_engine
from backend.services.inspection_image_service import ensure_image_asset_table, storage_root

IMAGE_COLUMNS = tuple(f"image{i}" for i in range(1, 11))
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class ImportCandidate:
    inspection_key: str
    immatriculation: str | None
    date_inspection_sk: int | None
    slot: str
    original_url: str


def _safe_part(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "unknown").strip())
    return cleaned.strip("._") or "unknown"


def _google_drive_file_id(url: str) -> str | None:
    parsed = urlparse(url)
    if "drive.google.com" not in parsed.netloc:
        return None
    match = re.search(r"/file/d/([^/]+)", parsed.path)
    if match:
        return match.group(1)
    query_id = parse_qs(parsed.query).get("id")
    return query_id[0] if query_id else None


def _download_url(url: str) -> str:
    file_id = _google_drive_file_id(url)
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


def _detect_content_type(payload: bytes, header_content_type: str | None) -> str:
    """Detect real content type from bytes, not only from Drive headers."""
    head = payload[:16]
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(payload) >= 12 and payload[4:8] == b"ftyp" and payload[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
        return "image/heic"
    ctype = (header_content_type or "").split(";", 1)[0].strip().lower()
    return ctype or "application/octet-stream"


def _guess_extension(content_type: str | None, url: str) -> str:
    if content_type:
        ctype = content_type.split(";", 1)[0].strip().lower()
        if ctype in {"image/jpeg", "image/jpg"}:
            return ".jpg"
        if ctype == "image/png":
            return ".png"
        if ctype == "image/webp":
            return ".webp"
        if ctype == "image/gif":
            return ".gif"
        if ctype in {"image/heic", "image/heif"}:
            return ".heic"
        if ctype == "application/pdf":
            return ".pdf"
        guessed = mimetypes.guess_extension(ctype)
        if guessed and guessed != ".bin":
            return guessed
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".pdf"} else ".jpg"


_SUPPORTED_ASSET_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif", "application/pdf"}


def _read_response(opener, url: str, max_bytes: int, timeout: int) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "IRIS-STAFIM-Image-Importer/1.0",
            "Accept": "image/*,application/pdf,*/*;q=0.8",
        },
    )
    with opener.open(request, timeout=timeout) as response:  # noqa: S310 - controlled source URL from STAFIM raw data
        content_type = response.headers.get("Content-Type", "")
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise RuntimeError(f"image exceeds max size ({max_bytes} bytes)")
    return payload, content_type


def _extract_drive_confirm_url(payload: bytes) -> str | None:
    text = payload[:200000].decode("utf-8", errors="ignore")
    patterns = [
        r'href="([^"]*?/uc\?export=download[^"]+confirm=[^"]+)"',
        r'href="([^"]*?/download\?[^"]+confirm=[^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return html.unescape(urljoin("https://drive.google.com", match.group(1).replace("&amp;", "&")))
    return None


def _download_image(url: str, max_bytes: int, timeout: int) -> tuple[bytes, str]:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    payload, content_type = _read_response(opener, _download_url(url), max_bytes, timeout)
    detected_type = _detect_content_type(payload, content_type)
    if detected_type in _SUPPORTED_ASSET_TYPES:
        return payload, detected_type

    if b"<html" in payload[:500].lower():
        confirm_url = _extract_drive_confirm_url(payload)
        if confirm_url:
            payload, content_type = _read_response(opener, confirm_url, max_bytes, timeout)
            detected_type = _detect_content_type(payload, content_type)
            if detected_type in _SUPPORTED_ASSET_TYPES:
                return payload, detected_type
        raise RuntimeError("Drive returned an HTML page instead of an image/PDF; access is probably restricted")

    return payload, detected_type


def _discover_image_columns(conn) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'staging'
              AND table_name = 'stg_inspection'
              AND column_name IN ('image1','image2','image3','image4','image5','image6','image7','image8','image9','image10')
            ORDER BY ordinal_position
            """
        )
    ).fetchall()
    return [row.column_name for row in rows]


def _load_candidates(conn, limit: int | None) -> list[ImportCandidate]:
    image_cols = _discover_image_columns(conn)
    if not image_cols:
        return []
    selects = [f"i.\"{col}\" AS \"{col}\"" for col in image_cols]
    sql = f"""
        SELECT
            f.inspection_key,
            i.immatriculation,
            CAST(TO_CHAR(i.date_inspection, 'YYYYMMDD') AS bigint) AS date_inspection_sk,
            {', '.join(selects)}
        FROM staging.stg_inspection i
        JOIN dwh.fact_inspection_vehicule f
          ON f.immatriculation_norm = i.immatriculation
         AND f.date_inspection_sk = CAST(TO_CHAR(i.date_inspection, 'YYYYMMDD') AS bigint)
        WHERE {' OR '.join(f'i."{col}" IS NOT NULL' for col in image_cols)}
        ORDER BY f.inspection_key
    """
    if limit:
        sql += "\n        LIMIT :limit"
    rows = conn.execute(text(sql), {"limit": limit} if limit else {}).fetchall()
    candidates: list[ImportCandidate] = []
    for row in rows:
        item = dict(row._mapping)
        for col in image_cols:
            url = str(item.get(col) or "").strip()
            if url:
                candidates.append(
                    ImportCandidate(
                        inspection_key=str(item["inspection_key"]),
                        immatriculation=item.get("immatriculation"),
                        date_inspection_sk=item.get("date_inspection_sk"),
                        slot=col,
                        original_url=url,
                    )
                )
    return candidates


def _existing_imported(conn, candidate: ImportCandidate) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM app.inspection_image_asset
                    WHERE inspection_key = :inspection_key
                      AND slot = :slot
                      AND storage_status = 'IMPORTED'
                      AND relative_path IS NOT NULL
                )
                """
            ),
            {"inspection_key": candidate.inspection_key, "slot": candidate.slot},
        ).scalar()
    )


def _upsert_status(conn, candidate: ImportCandidate, *, status: str, relative_path: str | None = None,
                   mime_type: str | None = None, size: int | None = None, sha256: str | None = None,
                   error: str | None = None) -> None:
    conn.execute(
        text(
            """
            INSERT INTO app.inspection_image_asset (
                inspection_key, immatriculation, date_inspection_sk, slot, original_url,
                storage_status, relative_path, mime_type, file_size_bytes, sha256,
                import_error, imported_at, updated_at
            ) VALUES (
                :inspection_key, :immatriculation, :date_inspection_sk, :slot, :original_url,
                :storage_status, :relative_path, :mime_type, :file_size_bytes, :sha256,
                :import_error,
                CASE WHEN :storage_status = 'IMPORTED' THEN (now() AT TIME ZONE 'utc') ELSE NULL END,
                (now() AT TIME ZONE 'utc')
            )
            ON CONFLICT (inspection_key, slot) DO UPDATE SET
                original_url = EXCLUDED.original_url,
                storage_status = EXCLUDED.storage_status,
                relative_path = EXCLUDED.relative_path,
                mime_type = EXCLUDED.mime_type,
                file_size_bytes = EXCLUDED.file_size_bytes,
                sha256 = EXCLUDED.sha256,
                import_error = EXCLUDED.import_error,
                imported_at = CASE
                    WHEN EXCLUDED.storage_status = 'IMPORTED' THEN (now() AT TIME ZONE 'utc')
                    ELSE app.inspection_image_asset.imported_at
                END,
                updated_at = (now() AT TIME ZONE 'utc')
            """
        ),
        {
            "inspection_key": candidate.inspection_key,
            "immatriculation": candidate.immatriculation,
            "date_inspection_sk": candidate.date_inspection_sk,
            "slot": candidate.slot,
            "original_url": candidate.original_url,
            "storage_status": status,
            "relative_path": relative_path,
            "mime_type": mime_type,
            "file_size_bytes": size,
            "sha256": sha256,
            "import_error": error,
        },
    )


def run_import(limit: int | None, force: bool, dry_run: bool, sleep_seconds: float) -> dict[str, int]:
    config = load_config()
    root = storage_root(config)
    engine = get_engine()
    stats = {"candidates": 0, "imported": 0, "skipped": 0, "failed": 0}
    with engine.begin() as conn:
        ensure_image_asset_table(conn)
        candidates = _load_candidates(conn, limit)
        stats["candidates"] = len(candidates)
        if dry_run:
            print(f"DRY RUN: {len(candidates)} image candidate(s). Storage root: {root}")
            return stats
        root.mkdir(parents=True, exist_ok=True)
        for candidate in candidates:
            if not force and _existing_imported(conn, candidate):
                stats["skipped"] += 1
                continue
            try:
                payload, mime_type = _download_image(
                    candidate.original_url,
                    max_bytes=config.inspection_image_max_bytes,
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                )
                digest = hashlib.sha256(payload).hexdigest()
                ext = _guess_extension(mime_type, candidate.original_url)
                rel_dir = Path(_safe_part(candidate.inspection_key))
                filename = f"{_safe_part(candidate.slot)}_{digest[:12]}{ext}"
                rel_path = rel_dir / filename
                abs_path = root / rel_path
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_bytes(payload)
                _upsert_status(
                    conn,
                    candidate,
                    status="IMPORTED",
                    relative_path=rel_path.as_posix(),
                    mime_type=mime_type,
                    size=len(payload),
                    sha256=digest,
                    error=None,
                )
                stats["imported"] += 1
            except (HTTPError, URLError, TimeoutError, RuntimeError, OSError) as exc:
                _upsert_status(conn, candidate, status="NOT_IMPORTED", error=str(exc)[:1000])
                stats["failed"] += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Import STAFIM Drive image links into IRIS local storage.")
    parser.add_argument("--limit", type=int, default=None, help="Limit source inspections, not final image count.")
    parser.add_argument("--force", action="store_true", help="Re-download images already imported.")
    parser.add_argument("--dry-run", action="store_true", help="Only count candidates and verify DB metadata table.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Pause between downloads to be polite with Drive.")
    args = parser.parse_args()
    stats = run_import(limit=args.limit, force=args.force, dry_run=args.dry_run, sleep_seconds=args.sleep)
    print(
        "STAFIM image import finished: "
        + ", ".join(f"{key}={value}" for key, value in stats.items())
    )


if __name__ == "__main__":
    main()
