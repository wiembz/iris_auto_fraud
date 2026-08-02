"""Inspection image asset service for STAFIM photos.

The raw STAFIM Excel stores image1..image10 as Google Drive URLs. IRIS should not
rely on the reviewer having Drive access, so imported photos are served from a
controlled local storage directory and described by app.inspection_image_asset.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.serialization import rows_to_dicts

IMAGE_COLUMNS = tuple(f"image{i}" for i in range(1, 11))


@dataclass(frozen=True)
class ImageAsset:
    asset_id: int | None
    inspection_key: str
    slot: str
    original_url: str | None
    asset_url: str | None
    storage_status: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    imported_at: str | None = None
    import_error: str | None = None

    @property
    def is_imported(self) -> bool:
        return self.storage_status == "IMPORTED" and self.asset_url is not None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_imported"] = self.is_imported
        return payload


def ensure_image_asset_table(conn) -> None:
    """Create the application metadata table used by the image importer.

    It is intentionally placed in schema app: the files are application assets,
    not DWH facts recalculated by the analytical pipeline.
    """
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS app.inspection_image_asset (
                asset_id          BIGSERIAL PRIMARY KEY,
                inspection_key    TEXT NOT NULL,
                immatriculation   TEXT,
                date_inspection_sk BIGINT,
                slot              TEXT NOT NULL,
                original_url      TEXT,
                storage_status    TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (storage_status IN ('PENDING', 'IMPORTED', 'NOT_IMPORTED', 'ERROR')),
                relative_path     TEXT,
                mime_type         TEXT,
                file_size_bytes   BIGINT,
                preview_relative_path TEXT,
                preview_mime_type TEXT,
                sha256            TEXT,
                import_error      TEXT,
                imported_at       TIMESTAMP,
                created_at        TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
                updated_at        TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
                CONSTRAINT uq_inspection_image_asset_slot UNIQUE (inspection_key, slot)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_inspection_image_asset_inspection
                ON app.inspection_image_asset (inspection_key, slot)
            """
        )
    )


def image_asset_table_exists(conn) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'app'
                      AND table_name = 'inspection_image_asset'
                )
                """
            )
        ).scalar()
    )


def storage_root(config: ApiConfig) -> Path:
    root = Path(config.inspection_image_storage_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parent.parent.parent / root
    return root.resolve()


def resolve_asset_path(config: ApiConfig, relative_path: str) -> Path | None:
    root = storage_root(config)
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def list_image_assets_for_inspection(conn, inspection_key: str) -> list[dict[str, Any]]:
    if not image_asset_table_exists(conn):
        return []
    rows = conn.execute(
        text(
            """
            SELECT
                asset_id,
                inspection_key,
                slot,
                original_url,
                storage_status,
                mime_type,
                file_size_bytes,
                preview_mime_type,
                imported_at,
                import_error
            FROM app.inspection_image_asset
            WHERE inspection_key = :inspection_key
            ORDER BY slot
            """
        ),
        {"inspection_key": inspection_key},
    ).fetchall()
    assets = rows_to_dicts(rows)
    for asset in assets:
        if asset.get("storage_status") == "IMPORTED" and asset.get("asset_id") is not None:
            asset["asset_url"] = f"/api/vhs/inspection-images/{asset['asset_id']}/content"
            asset["display_mime_type"] = asset.get("preview_mime_type") or asset.get("mime_type")
            asset["is_imported"] = True
        else:
            asset["asset_url"] = None
            asset["display_mime_type"] = asset.get("mime_type")
            asset["is_imported"] = False
    return assets


def build_fallback_image_assets(inspection_key: str, raw_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build auditable fallback items from raw Drive columns.

    These are not platform-owned assets yet. They are shown as external evidence
    links only until the importer succeeds.
    """
    links: list[dict[str, Any]] = []
    for column in IMAGE_COLUMNS:
        value = raw_payload.pop(column, None)
        if value is None:
            continue
        url = str(value).strip()
        if not url:
            continue
        links.append(
            ImageAsset(
                asset_id=None,
                inspection_key=inspection_key,
                slot=column,
                original_url=url,
                asset_url=None,
                storage_status="NOT_IMPORTED",
                import_error="Photo source presente dans STAFIM, mais non importee dans le stockage IRIS.",
            ).to_dict()
        )
    return links


def get_image_asset_for_content(conn, asset_id: int) -> dict[str, Any] | None:
    if not image_asset_table_exists(conn):
        return None
    row = conn.execute(
        text(
            """
            SELECT
                asset_id,
                inspection_key,
                slot,
                COALESCE(preview_relative_path, relative_path) AS relative_path,
                COALESCE(preview_mime_type, mime_type) AS mime_type,
                storage_status,
                file_size_bytes
            FROM app.inspection_image_asset
            WHERE asset_id = :asset_id
              AND storage_status = 'IMPORTED'
              AND relative_path IS NOT NULL
            LIMIT 1
            """
        ),
        {"asset_id": asset_id},
    ).first()
    return dict(row._mapping) if row else None
