"""
etl/dwh/load_all_dwh.py
=======================
Orchestrateur du chargement complet du Data Warehouse.

Execute les loaders dans l'ordre des dependances :

  Phase 1 — dimensions (independantes entre elles, lisent uniquement staging)
  Phase 2 — enrichissement post-dimension (enrich_dim_client_geo apres dim_client)
  Phase 3 — faits (fact_inspection_checkpoint APRES fact_inspection_vehicule,
            dont il importe les regles de normalisation et joint la table)
  Phase 4 — gate qualite (audit_etl_quality_completeness, lecture seule ;
            echoue si au moins un controle FAIL)

Chaque loader est execute comme sous-processus independant : il garde
exactement son comportement standalone (logs, rapports qualite, validations),
et l'orchestrateur n'a aucun couplage avec ses fonctions internes.

Si un loader echoue, les etapes qui en dependent sont sautees avec un message
explicite ; les etapes independantes continuent. Code retour non nul si au
moins une etape a echoue ou a ete sautee.

Usage :
  python etl/dwh/load_all_dwh.py                # pipeline complet
  python etl/dwh/load_all_dwh.py --only load_dim_geo
  python etl/dwh/load_all_dwh.py --from load_fact_contrat
  python etl/dwh/load_all_dwh.py --skip-facts   # dimensions + enrichissement
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent.parent

try:
    from etl.utils.runtime import setup_logging
except ModuleNotFoundError:  # standalone script execution
    sys.path.insert(0, str(BASE_DIR))
    from etl.utils.runtime import setup_logging

# ---------------------------------------------------------------------------
# Pipeline definition
# ---------------------------------------------------------------------------
# (step name, dependencies). A step runs only if all its dependencies
# succeeded in this run (or were not part of the selection).
PIPELINE: list[tuple[str, tuple[str, ...]]] = [
    # Phase 1 — dimensions
    ("load_dim_date", ()),
    ("load_dim_produit", ()),
    ("load_dim_intermediaire", ()),
    ("load_dim_client", ()),
    ("load_dim_camtier", ()),
    ("load_dim_tiers", ()),
    ("load_dim_vehicule", ()),
    ("load_dim_conducteur", ()),
    ("load_dim_sinistre", ()),
    ("load_dim_garantie", ()),
    ("load_dim_contrat", ()),
    ("load_dim_geo", ()),
    # Phase 2 — post-dimension enrichment
    ("enrich_dim_client_geo", ("load_dim_client",)),
    # Phase 3 — facts
    (
        "load_fact_contrat",
        (
            "load_dim_client",
            "load_dim_contrat",
            "load_dim_date",
            "load_dim_intermediaire",
            "load_dim_produit",
        ),
    ),
    (
        "load_fact_sinistre",
        (
            "load_dim_camtier",
            "load_dim_client",
            "load_dim_conducteur",
            "load_dim_contrat",
            "load_dim_date",
            "load_dim_garantie",
            "load_dim_geo",
            "load_dim_sinistre",
            "load_dim_tiers",
            "load_dim_vehicule",
        ),
    ),
    ("load_fact_inspection_vehicule", ("load_dim_date", "load_dim_vehicule")),
    (
        "load_fact_inspection_checkpoint",
        ("load_dim_date", "load_fact_inspection_vehicule"),
    ),
    # Phase 4 — gate qualité : audit lecture seule, exit non nul si FAIL
    (
        "audit_etl_quality_completeness",
        (
            "load_fact_contrat",
            "load_fact_sinistre",
            "load_fact_inspection_vehicule",
            "load_fact_inspection_checkpoint",
        ),
    ),
]

FACT_STEPS = frozenset(
    name for name, _ in PIPELINE if name.startswith("load_fact_")
)
AUDIT_STEP = "audit_etl_quality_completeness"
STEP_NAMES = [name for name, _ in PIPELINE]


def _select_steps(args: argparse.Namespace) -> list[tuple[str, tuple[str, ...]]]:
    if args.only:
        return [(name, deps) for name, deps in PIPELINE if name == args.only]
    selected = PIPELINE
    if args.start_from:
        idx = STEP_NAMES.index(args.start_from)
        selected = PIPELINE[idx:]
    if args.skip_facts:
        # Sans les facts, l'audit comparerait des facts obsolètes aux
        # dimensions rechargées : on le retire aussi.
        selected = [
            (n, d) for n, d in selected
            if n not in FACT_STEPS and n != AUDIT_STEP
        ]
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run all DWH loaders in dependency order."
    )
    parser.add_argument(
        "--only", choices=STEP_NAMES, help="Run a single loader and stop."
    )
    parser.add_argument(
        "--from",
        dest="start_from",
        choices=STEP_NAMES,
        help="Resume the pipeline starting at this loader.",
    )
    parser.add_argument(
        "--skip-facts",
        action="store_true",
        help="Run dimensions and enrichment only.",
    )
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = setup_logging(run_id, log_name="load_all_dwh", namespace="dwh")

    steps = _select_steps(args)
    logger.info(f"[RUN {run_id}] {len(steps)} etape(s) selectionnee(s)")

    succeeded: set[str] = set()
    failed: set[str] = set()
    skipped: set[str] = set()
    durations: dict[str, float] = {}
    selected_names = {name for name, _ in steps}

    for name, deps in steps:
        # A dependency only blocks if it was part of this run and failed/skipped.
        blocking = [
            d for d in deps if d in selected_names and d not in succeeded
        ]
        if blocking:
            logger.warning(
                f"[SKIP] {name} : dependance(s) en echec ou sautee(s) -> "
                f"{', '.join(blocking)}"
            )
            skipped.add(name)
            continue

        script = SCRIPT_DIR / f"{name}.py"
        logger.info(f"[STEP] {name} ...")
        t0 = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(BASE_DIR),
        )
        elapsed = time.monotonic() - t0
        durations[name] = elapsed
        if result.returncode == 0:
            succeeded.add(name)
            logger.info(f"[OK]   {name} ({elapsed:.0f}s)")
        else:
            failed.add(name)
            logger.error(
                f"[FAIL] {name} (exit={result.returncode}, {elapsed:.0f}s)"
            )

    logger.info("=" * 60)
    logger.info(f"  etapes reussies : {len(succeeded)}")
    logger.info(f"  etapes en echec : {len(failed)}"
                + (f" -> {sorted(failed)}" if failed else ""))
    logger.info(f"  etapes sautees  : {len(skipped)}"
                + (f" -> {sorted(skipped)}" if skipped else ""))
    total = sum(durations.values())
    logger.info(f"  duree totale    : {total:.0f}s")
    logger.info("=" * 60)

    return 1 if (failed or skipped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
