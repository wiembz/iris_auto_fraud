"""FastAPI application factory for the IRIS read-only claim review API.

Migrated from Flask (see docs/architecture/MIGRATION_FASTAPI_PLAN.md):
same service layer, same `/api/...` endpoints, same JSON response shapes,
same HTTP status codes, same `{"message": "..."}` business-error format.
"""
from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.errors import register_error_handlers
from backend.api.routers import (
    auth,
    claims,
    decisions,
    portfolio,
    powerbi,
    summary,
    vhs,
    workflow,
)
from backend.config import load_config
from backend.db import get_engine


def create_app(test_config: dict | None = None) -> FastAPI:
    app = FastAPI(
        title="IRIS API",
        description="Read-only claim review API for the IRIS auto-fraud decision platform.",
        version="1.0.0",
    )

    app.state.api_config = load_config()
    app.state.engine = get_engine()

    if test_config:
        for key, value in test_config.items():
            setattr(app.state, key, value)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(auth.router)
    app.include_router(summary.router)
    app.include_router(claims.router)
    app.include_router(decisions.router)
    app.include_router(portfolio.router)
    app.include_router(powerbi.router)
    app.include_router(vhs.router)
    app.include_router(workflow.router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5000)
