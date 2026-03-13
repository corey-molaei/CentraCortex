import os
import re

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["SKIP_EXTERNAL_HEALTHCHECKS"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ENCRYPTION_KEY"] = "dGVzdC1rZXktZm9yLWZlcm5ldC10ZXN0LXNlY3JldA=="

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.state.db_session_factory = TestingSessionLocal
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    app.state.db_session_factory = TestingSessionLocal


@pytest.fixture(autouse=True)
def local_qdrant_for_tests(monkeypatch, tmp_path):
    from app.services import document_indexing

    client = QdrantClient(path=str(tmp_path / "qdrant"))
    monkeypatch.setattr(document_indexing, "_qdrant_client", lambda: client)
    try:
        yield
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _extract_recipient_name_hint(message: str) -> str | None:
    normalized = " ".join(message.split())
    match = re.search(
        r"\bto\s+(.+?)(?:\s+\b(?:subject|title|body|about|cc|bcc)\b|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1).strip(" .,")
    if not value:
        return None
    if re.search(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", value, re.IGNORECASE):
        return None
    return value


@pytest.fixture(autouse=True)
def mock_tool_plan_parser(monkeypatch, request):
    if request.node.get_closest_marker("use_real_tool_planner"):
        yield
        return

    from app.services import tool_plan_dispatcher

    def _fake_parse_tool_plan_llm(*args, **kwargs):  # noqa: ARG001
        message = str(kwargs.get("message") or "")
        lowered = message.lower()
        tokens = set(re.findall(r"[a-z0-9_]+", lowered))
        steps: list[tool_plan_dispatcher.ToolStep] = []

        if "send" in tokens and ("email" in tokens or "mail" in tokens):
            has_explicit_email = bool(re.search(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", message, re.IGNORECASE))
            if has_explicit_email:
                steps = [tool_plan_dispatcher.ToolStep(tool="email.send_draft", args={})]
            else:
                name_hint = _extract_recipient_name_hint(message) or "contact"
                steps = [
                    tool_plan_dispatcher.ToolStep(tool="contacts.search", args={"query": name_hint}),
                    tool_plan_dispatcher.ToolStep(tool="email.send_draft", args={}),
                ]
        elif tokens.intersection({"contact", "contacts", "people", "person", "addressbook"}) or "email of" in lowered:
            if tokens.intersection({"delete", "remove"}):
                steps = [tool_plan_dispatcher.ToolStep(tool="contacts.delete", args={})]
            elif tokens.intersection({"update", "change", "edit"}):
                steps = [tool_plan_dispatcher.ToolStep(tool="contacts.update", args={})]
            elif tokens.intersection({"find", "search", "lookup"}) or "email of" in lowered:
                steps = [tool_plan_dispatcher.ToolStep(tool="contacts.search", args={})]
            elif "read" in tokens:
                steps = [tool_plan_dispatcher.ToolStep(tool="contacts.read", args={})]
            else:
                steps = [tool_plan_dispatcher.ToolStep(tool="contacts.list", args={})]
        elif tokens.intersection({"calendar", "calendars", "meeting", "meetings", "event", "events", "schedule", "standup"}):
            if tokens.intersection({"delete", "cancel", "remove"}):
                steps = [tool_plan_dispatcher.ToolStep(tool="calendar.delete", args={})]
            elif tokens.intersection({"update", "move", "reschedule"}):
                steps = [tool_plan_dispatcher.ToolStep(tool="calendar.update", args={})]
            elif tokens.intersection({"list", "upcoming", "show"}):
                steps = [tool_plan_dispatcher.ToolStep(tool="calendar.list", args={})]
            else:
                steps = [tool_plan_dispatcher.ToolStep(tool="calendar.create", args={})]
        elif tokens.intersection({"email", "emails", "inbox", "gmail", "mail", "mails"}):
            if "read" in tokens:
                steps = [tool_plan_dispatcher.ToolStep(tool="email.read", args={})]
            else:
                steps = [tool_plan_dispatcher.ToolStep(tool="email.list", args={})]

        plan = tool_plan_dispatcher.ToolPlan(steps=steps, confidence=0.9, reason="test-mock")
        return plan, False

    monkeypatch.setattr(tool_plan_dispatcher, "_parse_tool_plan_llm", _fake_parse_tool_plan_llm)
    yield
