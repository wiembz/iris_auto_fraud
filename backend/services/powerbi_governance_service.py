"""Read-only governance snapshot for the Power BI analytics space.

Reads powerbi_v.v_governance — the same view the Power BI report consumes —
so the Angular portal displays exactly what the report is built on
(component, locked score version, resolved run, row count).
"""
from __future__ import annotations

from sqlalchemy import text

from backend.services.serialization import rows_to_dicts

_GOVERNANCE_SQL = """
    SELECT component, version, run_id, row_count
    FROM powerbi_v.v_governance
    ORDER BY component
"""


def get_powerbi_governance(engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(text(_GOVERNANCE_SQL)).fetchall()
    return {"components": rows_to_dicts(rows)}
