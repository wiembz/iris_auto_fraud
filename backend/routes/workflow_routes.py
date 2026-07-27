"""Workflow gestionnaire endpoints — statut operationnel, affectation, taches."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.services.workflow_service import (
    WorkflowError,
    complete_task,
    create_task,
    get_workflow_history,
    get_workflow_state,
    list_open_tasks,
    record_assignment,
    record_status_change,
)

workflow_bp = Blueprint("workflow", __name__, url_prefix="/api")


def _engine():
    return current_app.config["IRIS_ENGINE"]


def _config():
    return current_app.config["IRIS_API_CONFIG"]


@workflow_bp.get("/claims/<int:claim_sk>/workflow")
def workflow_state(claim_sk: int):
    return jsonify(get_workflow_state(_engine(), claim_sk))


@workflow_bp.get("/claims/<int:claim_sk>/workflow/history")
def workflow_history(claim_sk: int):
    return jsonify({"claim_sk": claim_sk, "items": get_workflow_history(_engine(), claim_sk)})


@workflow_bp.post("/claims/<int:claim_sk>/workflow/status")
def workflow_status_change(claim_sk: int):
    body = request.get_json(silent=True) or {}
    try:
        result = record_status_change(
            _engine(),
            claim_sk=claim_sk,
            status=body.get("status"),
            actor_email=body.get("actor_email"),
            comment=body.get("comment"),
        )
    except WorkflowError as exc:
        return jsonify({"message": str(exc)}), exc.status_code
    return jsonify(result), 201


@workflow_bp.post("/claims/<int:claim_sk>/workflow/assignment")
def workflow_assignment(claim_sk: int):
    body = request.get_json(silent=True) or {}
    try:
        result = record_assignment(
            _engine(),
            claim_sk=claim_sk,
            assignee_email=body.get("assignee_email"),
            actor_email=body.get("actor_email"),
            comment=body.get("comment"),
        )
    except WorkflowError as exc:
        return jsonify({"message": str(exc)}), exc.status_code
    return jsonify(result), 201


@workflow_bp.post("/claims/<int:claim_sk>/workflow/tasks")
def workflow_task_create(claim_sk: int):
    body = request.get_json(silent=True) or {}
    try:
        result = create_task(
            _engine(),
            claim_sk=claim_sk,
            task_label=body.get("task_label"),
            actor_email=body.get("actor_email"),
        )
    except WorkflowError as exc:
        return jsonify({"message": str(exc)}), exc.status_code
    return jsonify(result), 201


@workflow_bp.post("/claims/<int:claim_sk>/workflow/tasks/<int:task_ref_id>/complete")
def workflow_task_complete(claim_sk: int, task_ref_id: int):
    body = request.get_json(silent=True) or {}
    try:
        result = complete_task(
            _engine(),
            claim_sk=claim_sk,
            task_ref_id=task_ref_id,
            actor_email=body.get("actor_email"),
            comment=body.get("comment"),
        )
    except WorkflowError as exc:
        return jsonify({"message": str(exc)}), exc.status_code
    return jsonify(result), 201


@workflow_bp.get("/workflow/tasks")
def workflow_tasks_feed():
    assignee_email = request.args.get("assignee_email")
    limit = request.args.get("limit")
    items = list_open_tasks(
        _engine(),
        _config(),
        assignee_email=assignee_email,
        limit=int(limit) if limit else 50,
    )
    return jsonify({"items": items})
