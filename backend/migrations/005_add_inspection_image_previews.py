"""
Add JPEG preview metadata for imported STAFIM assets.

Original files remain untouched in `relative_path`; browser-friendly generated
previews are referenced through `preview_relative_path` / `preview_mime_type`.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.db import get_engine

DDL_STATEMENTS = [
    """
    ALTER TABLE app.inspection_image_asset
        ADD COLUMN IF NOT EXISTS preview_relative_path TEXT
    """,
    """
    ALTER TABLE app.inspection_image_asset
        ADD COLUMN IF NOT EXISTS preview_mime_type TEXT
    """,
]


def run_migration() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for statement in DDL_STATEMENTS:
            conn.execute(text(statement))
    print("Migration OK : colonnes preview image ajoutees/verifiees.")


if __name__ == "__main__":
    run_migration()
