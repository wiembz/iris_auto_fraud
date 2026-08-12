"""FastAPI dependencies for the IRIS API.

Replaces Flask's ``current_app.config["IRIS_ENGINE"]`` / ``["IRIS_API_CONFIG"]``.
The engine and config are created once in ``backend/app.py`` and stored on
``app.state``; these dependencies just hand them to route functions.
"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.engine import Engine

from backend.config import ApiConfig


def get_api_config(request: Request) -> ApiConfig:
    return request.app.state.api_config


def get_db_engine(request: Request) -> Engine:
    return request.app.state.engine
