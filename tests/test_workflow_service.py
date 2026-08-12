"""Unit tests for backend/services/workflow_service.py validation logic.

These exercise the pure validation paths (invalid status/email/comment/label)
that raise WorkflowError BEFORE any database connection is opened, using a
DummyEngine that fails loudly if touched — proving validation short-circuits
before reaching the DB, the same way test_backend_readonly_api.py verifies
other services avoid unnecessary database access.
"""
import pytest

from backend.services.workflow_service import (
    ALLOWED_STATUSES,
    MAX_COMMENT_LENGTH,
    MAX_TASK_LABEL_LENGTH,
    WorkflowError,
    complete_task,
    create_task,
    record_assignment,
    record_status_change,
)


class DummyEngine:
    def begin(self):
        raise AssertionError("validation should reject before opening a DB transaction")

    def connect(self):
        raise AssertionError("validation should reject before opening a DB connection")


def test_allowed_statuses_cover_the_eight_stage_workflow():
    assert ALLOWED_STATUSES == {
        "NOUVEAU",
        "AFFECTE",
        "EN_COURS",
        "EN_ATTENTE_PIECES",
        "PRET_POUR_DECISION",
        "TRANSMIS_INVESTIGATION",
        "RETOUR_INVESTIGATION",
        "CLOTURE",
    }


def test_record_status_change_rejects_unknown_status():
    with pytest.raises(WorkflowError) as exc_info:
        record_status_change(
            DummyEngine(), claim_sk=1, status="INVALID", actor_email="a@bna.tn"
        )
    assert exc_info.value.status_code == 400


def test_record_status_change_rejects_missing_actor_email():
    with pytest.raises(WorkflowError):
        record_status_change(
            DummyEngine(), claim_sk=1, status="NOUVEAU", actor_email=""
        )


def test_record_status_change_rejects_actor_email_without_at_sign():
    with pytest.raises(WorkflowError):
        record_status_change(
            DummyEngine(), claim_sk=1, status="NOUVEAU", actor_email="not-an-email"
        )


def test_record_status_change_rejects_comment_too_long():
    with pytest.raises(WorkflowError):
        record_status_change(
            DummyEngine(),
            claim_sk=1,
            status="NOUVEAU",
            actor_email="a@bna.tn",
            comment="x" * (MAX_COMMENT_LENGTH + 1),
        )


def test_record_assignment_rejects_missing_actor_email():
    with pytest.raises(WorkflowError):
        record_assignment(
            DummyEngine(), claim_sk=1, assignee_email="gestionnaire@bna.tn", actor_email=None
        )


def test_record_assignment_rejects_invalid_assignee_email():
    with pytest.raises(WorkflowError):
        record_assignment(
            DummyEngine(), claim_sk=1, assignee_email="not-an-email", actor_email="a@bna.tn"
        )


def test_record_assignment_allows_empty_assignee_email_to_unassign():
    # Unassigning is a valid business case (claim goes back to the pool),
    # so an empty assignee_email must pass validation and only fail once it
    # tries to reach the (dummy, unreachable) database.
    with pytest.raises(AssertionError):
        record_assignment(
            DummyEngine(), claim_sk=1, assignee_email="", actor_email="a@bna.tn"
        )


def test_create_task_rejects_empty_label():
    with pytest.raises(WorkflowError):
        create_task(DummyEngine(), claim_sk=1, task_label="   ", actor_email="a@bna.tn")


def test_create_task_rejects_label_too_long():
    with pytest.raises(WorkflowError):
        create_task(
            DummyEngine(),
            claim_sk=1,
            task_label="x" * (MAX_TASK_LABEL_LENGTH + 1),
            actor_email="a@bna.tn",
        )


def test_create_task_rejects_missing_actor_email():
    with pytest.raises(WorkflowError):
        create_task(DummyEngine(), claim_sk=1, task_label="Relancer l'assure", actor_email="")


def test_complete_task_rejects_missing_task_ref_id():
    with pytest.raises(WorkflowError) as exc_info:
        complete_task(DummyEngine(), claim_sk=1, task_ref_id=None, actor_email="a@bna.tn")
    assert exc_info.value.status_code == 400


def test_complete_task_rejects_missing_actor_email():
    with pytest.raises(WorkflowError):
        complete_task(DummyEngine(), claim_sk=1, task_ref_id=42, actor_email="")
