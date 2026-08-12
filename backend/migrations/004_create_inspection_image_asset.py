"""
backend/migrations/004_create_inspection_image_asset.py
========================================================
Cree app.inspection_image_asset, table de metadonnees des photos STAFIM
importees dans le stockage applicatif IRIS.

Les fichiers restent dans data/inspection_images ; PostgreSQL conserve les
metadonnees, le lien source Drive et le statut d'import. C'est volontaire :
la couche DWH reste analytique/read-only, tandis que les photos sont des assets
applicatifs servant l'experience utilisateur et l'audit documentaire.

Usage :
  python backend/migrations/004_create_inspection_image_asset.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.db import get_engine
from backend.services.inspection_image_service import ensure_image_asset_table


def run_migration() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        ensure_image_asset_table(conn)
    print("Migration OK : app.inspection_image_asset creee/verifiee.")


if __name__ == "__main__":
    run_migration()
