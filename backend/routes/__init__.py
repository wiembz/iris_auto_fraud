"""Flask route registration for the IRIS read-only API."""
from __future__ import annotations

from backend.routes.claims_routes import claims_bp
from backend.routes.decisions_routes import decisions_bp
from backend.routes.portfolio_routes import portfolio_bp
from backend.routes.powerbi_routes import powerbi_bp
from backend.routes.summary_routes import summary_bp
from backend.routes.vhs_routes import vhs_bp


def register_blueprints(app) -> None:
    app.register_blueprint(summary_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(decisions_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(powerbi_bp)
    app.register_blueprint(vhs_bp)
