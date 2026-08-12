"""Workflow gestionnaire endpoints -- statut operationnel, affectation, taches."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Engine

from backend.api.dependencies import get_api_config, get_db_engine
from backend.api.errors import message_error
from backend.api.schemas import (
    WorkflowAssignmentRequest,
    WorkflowStatusRequest,
    WorkflowTaskCompleteRequest,
    WorkflowTaskCreateRequest,
)
from backend.config import ApiConfig
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

router = APIRouter(prefix="/api", tags=["workflow"])


@router.get("/claims/{claim_sk}/workflow")
def workflow_state(claim_sk: int, engine: Engine = Depends(get_db_engine)):
    return get_workflow_state(engine, claim_sk)


@router.get("/claims/{claim_sk}/workflow/history")
def workflow_history(claim_sk: int, engine: Engine = Depends(get_db_engine)):
    return {"claim_sk": claim_sk, "items": get_workflow_history(engine, claim_sk)}


@router.post("/claims/{claim_sk}/workflow/status", status_code=201)
def workflow_status_change(
    claim_sk: int,
    body: WorkflowStatusRequest = WorkflowStatusRequest(),
    engine: Engine = Depends(get_db_engine),
):
    try:
        return record_status_change(
            engine,
            claim_sk=claim_sk,
            status=body.status,
            actor_email=body.actor_email,
            comment=body.comment,
        )
    except WorkflowError as exc:
        raise message_error(exc.status_code, str(exc))


@router.post("/claims/{claim_sk}/workflow/assignment", status_code=201)
def workflow_assignment(
    claim_sk: int,
    body: WorkflowAssignmentRequest = WorkflowAssignmentRequest(),
    engine: Engine = Depends(get_db_engine),
):
    try:
        return record_assignment(
            engine,
            claim_sk=claim_sk,
            assignee_email=body.assignee_email,
            actor_email=body.actor_email,
            comment=body.comment,
        )
    except WorkflowError as exc:
        raise message_error(exc.status_code, str(exc))


@router.post("/claims/{claim_sk}/workflow/tasks", status_code=201)
def workflow_task_create(
    claim_sk: int,
    body: WorkflowTaskCreateRequest = WorkflowTaskCreateRequest(),
    engine: Engine = Depends(get_db_engine),
):
    try:
        return create_task(
            engine,
            claim_sk=claim_sk,
            task_label=body.task_label,
            actor_email=body.actor_email,
        )
    except WorkflowError as exc:
        raise message_error(exc.status_code, str(exc))


@router.post("/claims/{claim_sk}/workflow/tasks/{task_ref_id}/complete", status_code=201)
def workflow_task_complete(
    claim_sk: int,
    task_ref_id: int,
    body: WorkflowTaskCompleteRequest = WorkflowTaskCompleteRequest(),
    engine: Engine = Depends(get_db_engine),
):
    try:
        return complete_task(
            engine,
            claim_sk=claim_sk,
            task_ref_id=task_ref_id,
            actor_email=body.actor_email,
            comment=body.comment,
        )
    except WorkflowError as exc:
        raise message_error(exc.status_code, str(exc))


@router.get("/workflow/tasks")
def workflow_tasks_feed(
    assignee_email: str | None = None,
    limit: str | None = None,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    items = list_open_tasks(
        engine,
        config,
        assignee_email=assignee_email,
        limit=int(limit) if limit else 50,
    )
    return {"items": items}
