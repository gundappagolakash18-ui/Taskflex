"""AI parsing: mock provider output, the confirm-gate (parse never dispatches),
and graceful fallback when the configured provider is unavailable."""

import pytest

from app.ai.schemas import ProviderUnavailableError
from app.ai.task_parser import get_task_parser
from app.core.exceptions import AIParseException
from app.models import Task
from app.services import TaskService

from tests.conftest import auth_headers, make_user

PARSE_TEXT = (
    "I need someone to submit my property documents at the government office "
    "tomorrow morning. My budget is 300 rupees."
)


def test_parse_returns_structured_mock_draft(client, db):
    user = make_user(db, "CUSTOMER")
    resp = client.post("/api/v1/tasks/parse", json={"text": PARSE_TEXT}, headers=auth_headers(user))

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True

    draft = body["data"]["draft"]
    assert draft["provider"] == "mock"
    assert draft["task_type"] in {"document_submission", "government_office"}
    assert draft["budget"] == 300
    assert 0.0 < draft["confidence"] <= 1.0
    assert isinstance(draft["clarification_questions"], list)


def test_parse_is_read_only_never_creates_or_dispatches(client, db):
    user = make_user(db, "CUSTOMER")
    resp = client.post("/api/v1/tasks/parse", json={"text": PARSE_TEXT}, headers=auth_headers(user))
    assert resp.status_code == 200

    assert db.query(Task).count() == 0, "AI interpretation must never save a task"


def test_parse_requires_authentication(client):
    resp = client.post("/api/v1/tasks/parse", json={"text": PARSE_TEXT})
    assert resp.status_code == 401


def test_parse_too_short_text_422(client, db):
    user = make_user(db, "CUSTOMER")
    resp = client.post("/api/v1/tasks/parse", json={"text": "help"}, headers=auth_headers(user))
    assert resp.status_code == 422


def test_empty_text_raises_ai_parse_error(client, db):
    service = TaskService(db)
    with pytest.raises(AIParseException):
        service.parse_request("   ")


def test_falls_back_to_mock_when_provider_down(client, db, monkeypatch):
    class BrokenProvider:
        name = "broken"

        def is_available(self) -> bool:
            return False

        def parse_task(self, text, now=None):
            raise ProviderUnavailableError("provider is down")

    parser = get_task_parser()
    monkeypatch.setattr(parser, "provider", BrokenProvider())

    user = make_user(db, "CUSTOMER")
    resp = client.post("/api/v1/tasks/parse", json={"text": PARSE_TEXT}, headers=auth_headers(user))

    assert resp.status_code == 200
    draft = resp.json()["data"]["draft"]
    assert draft["provider"] == "mock"
    assert draft["confidence"] > 0


def test_mock_provider_survives_garbage_task_shape():
    """The parser boundary validates drafts: a provider returning an invalid
    draft must fall back to mock rather than leak raw output."""
    parser = get_task_parser()

    class GarbageProvider:
        name = "garbage"

        def is_available(self) -> bool:
            return True

        def parse_task(self, text, now=None):
            return "not a draft at all"

    original_provider = parser.provider
    original_fallback = parser.fallback
    try:
        parser.provider = GarbageProvider()
        draft = parser.parse(PARSE_TEXT)
        assert draft.provider == "mock"
    finally:
        parser.provider = original_provider
        parser.fallback = original_fallback
