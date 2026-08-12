"""Request body models for the IRIS API.

Deliberately permissive (all-optional strings) to match the Flask-era
`request.get_json(silent=True) or {}` + `body.get(...)` behaviour: the
service layer (decision_service, workflow_service, auth_service) already
validates and raises its own business errors on missing/invalid fields.
Tightening these types is a later, separate step -- not part of this
equivalence migration.
"""
from __future__ import annotations

from pydantic import BaseModel


class ResolveRoleRequest(BaseModel):
    email: str | None = None


class DecisionRequest(BaseModel):
    decision: str | None = None
    comment: str | None = None
    reviewer_email: str | None = None
    reviewer_role: str | None = None
    score_version: str | None = None


class WorkflowStatusRequest(BaseModel):
    status: str | None = None
    actor_email: str | None = None
    comment: str | None = None


class WorkflowAssignmentRequest(BaseModel):
    assignee_email: str | None = None
    actor_email: str | None = None
    comment: str | None = None


class WorkflowTaskCreateRequest(BaseModel):
    task_label: str | None = None
    actor_email: str | None = None


class WorkflowTaskCompleteRequest(BaseModel):
    actor_email: str | None = None
    comment: str | None = None
