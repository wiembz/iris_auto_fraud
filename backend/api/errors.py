"""Business-error helpers that keep the Flask-era `{"message": "..."}` JSON
shape the Angular frontend already expects, instead of FastAPI's default
`{"detail": "..."}`.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raise to return `{"message": "..."}` with the given HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def message_error(status_code: int, message: str) -> ApiError:
    """Build (not raise) an ApiError -- lets call sites write
    `raise message_error(404, "...")`, mirroring the old `return jsonify(...), 404`."""
    return ApiError(status_code, message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"message": exc.message})

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"message": "Erreur technique API. Aucun calcul ou ecriture n'a ete execute."},
        )
