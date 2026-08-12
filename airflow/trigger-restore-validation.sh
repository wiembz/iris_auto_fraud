#!/usr/bin/env bash
set -euo pipefail

run_id="${1:-iris_restore_validation_$(date -u +%Y%m%d_%H%M%S)}"

airflow dags trigger \
  --run-id "${run_id}" \
  --conf '{
    "confirm_db": "iris_auto_fraud_restore_verify_20260725",
    "reload_staging": false,
    "allow_active_connections": false,
    "skip_exact_checks": false
  }' \
  iris_full_pipeline
