"""Flask route registration for the IRIS read-only API."""
from __future__ import annotations

from backend.routes.claims_routes import claims_bp
from backend.routes.summary_routes import summary_bp


def register_blueprints(app) -> None:
    app.register_blueprint(summary_bp)
    app.register_blueprint(claims_bp)
