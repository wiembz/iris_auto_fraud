"""Vehicle Health Score endpoints for the IRIS read-only API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.engine import Engine

from backend.api.dependencies import get_api_config, get_db_engine
from backend.api.errors import message_error
from backend.config import ApiConfig
from backend.services.inspection_image_service import get_image_asset_for_content, resolve_asset_path
from backend.services.vhs_service import (
    get_vhs_inspection_detail,
    get_vhs_inspection_detail_by_key,
    get_vhs_overview,
    list_vhs_vehicles,
)

router = APIRouter(prefix="/api", tags=["vhs"])


@router.get("/vhs/overview")
def vhs_overview(engine: Engine = Depends(get_db_engine)):
    return get_vhs_overview(engine)


@router.get("/vhs/vehicles")
def vhs_vehicles(
    decision: str | None = None,
    search: str | None = None,
    limit: str | None = None,
    engine: Engine = Depends(get_db_engine),
):
    return list_vhs_vehicles(
        engine,
        decision=decision,
        search=search,
        limit=int(limit) if limit else 300,
    )


@router.get("/vhs/inspection-images/{asset_id}/content")
def vhs_inspection_image_content(
    asset_id: int,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    """Serve an imported STAFIM photo from IRIS-controlled local storage."""
    with engine.connect() as conn:
        asset = get_image_asset_for_content(conn, asset_id)
    if asset is None:
        raise message_error(404, "Photo inspection introuvable ou non importee dans IRIS.")

    path = resolve_asset_path(config, asset["relative_path"])
    if path is None or not path.exists() or not path.is_file():
        raise message_error(404, "Photo inspection introuvable ou non importee dans IRIS.")

    return FileResponse(
        path,
        media_type=asset.get("mime_type") or "application/octet-stream",
        headers={"Cache-Control": "max-age=3600"},
    )


@router.get("/vhs/inspections/by-key")
def vhs_inspection_detail_by_key(
    immatriculation: str = "",
    date_sk: str = "",
    engine: Engine = Depends(get_db_engine),
):
    """Resolve the latest VHS inspection by immatriculation + date_inspection_sk.

    This endpoint avoids the stale SK problem: the inspection_sk stored in
    fact_post_inspection_attention_signal points to a specific run's row, not
    always to the latest run. Use this endpoint when you have the immatriculation
    and date from the post-inspection signal rather than a reliable vhs_score_sk.
    """
    immatriculation = immatriculation.strip()
    date_sk = date_sk.strip()
    if not immatriculation or not date_sk:
        raise message_error(400, "Paramètres 'immatriculation' et 'date_sk' requis.")
    try:
        date_sk_int = int(date_sk)
    except ValueError:
        raise message_error(400, "'date_sk' doit être un entier (format YYYYMMDD).")

    result = get_vhs_inspection_detail_by_key(engine, immatriculation, date_sk_int)
    if result is None:
        raise message_error(404, "Aucune inspection VHS trouvée pour cette immatriculation et cette date.")
    return result


@router.get("/vhs/inspections/{vhs_score_sk}")
def vhs_inspection_detail(vhs_score_sk: int, engine: Engine = Depends(get_db_engine)):
    result = get_vhs_inspection_detail(engine, vhs_score_sk)
    if result is None:
        raise message_error(404, "Inspection introuvable.")
    return result
