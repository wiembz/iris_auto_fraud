"""Flask application factory for the IRIS read-only claim review API."""
from __future__ import annotations


from pathlib import Path
import sys
from flask import Flask, jsonify

try:
    from flask_cors import CORS
except ModuleNotFoundError:  # CORS is optional for unit tests and local API checks.
    CORS = None

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import load_config
from backend.db import get_engine
from backend.routes import register_blueprints


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)

    api_config = load_config()
    app.config["IRIS_API_CONFIG"] = api_config
    app.config["IRIS_ENGINE"] = get_engine()
    app.config["JSON_SORT_KEYS"] = False

    if test_config:
        app.config.update(test_config)

    if CORS is not None:
        CORS(app, resources={r"/api/*": {"origins": "*"}})

    register_blueprints(app)

    @app.errorhandler(500)
    def internal_error(error):  # noqa: ARG001
        return jsonify({
            "message": "Erreur technique API. Aucun calcul ou ecriture n'a ete execute.",
        }), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

