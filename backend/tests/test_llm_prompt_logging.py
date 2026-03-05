from types import SimpleNamespace

import app.services.llm_router as llm_router_module
from app.core.config import settings
from app.services.llm_router import LLMRouter


class _CaptureLogger:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def debug(self, event: str, **kwargs):  # noqa: ANN003
        self.events.append((event, kwargs))


def _stub_router(monkeypatch, *, result=None):
    provider = SimpleNamespace(
        id="provider-1",
        name="Debug Provider",
        provider_type="openai",
        model_name="debug-model",
    )
    payload = result or {
        "answer": "ok",
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
        "cost_usd": 0.0,
    }

    monkeypatch.setattr(LLMRouter, "select_provider", lambda self, provider_id_override=None: (provider, None))
    monkeypatch.setattr(LLMRouter, "_call_provider", lambda self, provider, messages, temperature: payload)
    monkeypatch.setattr(LLMRouter, "_log_call", lambda self, **kwargs: None)


def test_prompt_debug_logging_emits_when_debug_enabled(db_session, monkeypatch):
    _stub_router(monkeypatch)
    capture = _CaptureLogger()
    monkeypatch.setattr(llm_router_module, "logger", capture)
    monkeypatch.setattr(settings, "log_level", "DEBUG")
    monkeypatch.setattr(settings, "prompt_debug_logging_enabled", True)

    router = LLMRouter(db_session, "tenant-1")
    router.chat(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.1,
    )

    events = [item for item in capture.events if item[0] == "llm_prompt_debug"]
    assert len(events) == 1
    _, payload = events[0]
    assert payload["tenant_id"] == "tenant-1"
    assert payload["provider_id"] == "provider-1"
    assert payload["message_count"] == 1
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["content"] == "hello"


def test_prompt_debug_logging_not_emitted_when_not_debug(db_session, monkeypatch):
    _stub_router(monkeypatch)
    capture = _CaptureLogger()
    monkeypatch.setattr(llm_router_module, "logger", capture)
    monkeypatch.setattr(settings, "log_level", "INFO")
    monkeypatch.setattr(settings, "prompt_debug_logging_enabled", True)

    router = LLMRouter(db_session, "tenant-1")
    router.chat(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.1,
    )

    assert capture.events == []


def test_prompt_debug_logging_redacts_secrets(db_session, monkeypatch):
    _stub_router(monkeypatch)
    capture = _CaptureLogger()
    monkeypatch.setattr(llm_router_module, "logger", capture)
    monkeypatch.setattr(settings, "log_level", "DEBUG")
    monkeypatch.setattr(settings, "prompt_debug_logging_enabled", True)

    router = LLMRouter(db_session, "tenant-1")
    router.chat(
        messages=[
            {
                "role": "user",
                "content": (
                    "Authorization: Bearer supersecrettokenvalue "
                    "api_key=plain-secret sk-1234567890ABCDEF token:raw-token"
                ),
            }
        ],
        temperature=0.1,
    )

    payload = [item[1] for item in capture.events if item[0] == "llm_prompt_debug"][0]
    content = payload["messages"][0]["content"]
    assert "supersecrettokenvalue" not in content
    assert "plain-secret" not in content
    assert "raw-token" not in content
    assert "[REDACTED]" in content


def test_prompt_debug_logging_keeps_emails_visible(db_session, monkeypatch):
    _stub_router(monkeypatch)
    capture = _CaptureLogger()
    monkeypatch.setattr(llm_router_module, "logger", capture)
    monkeypatch.setattr(settings, "log_level", "DEBUG")
    monkeypatch.setattr(settings, "prompt_debug_logging_enabled", True)

    router = LLMRouter(db_session, "tenant-1")
    router.chat(
        messages=[{"role": "user", "content": "email admin@example.com about status update"}],
        temperature=0.1,
    )

    payload = [item[1] for item in capture.events if item[0] == "llm_prompt_debug"][0]
    assert "admin@example.com" in payload["messages"][0]["content"]


def test_prompt_debug_logging_truncates_long_messages(db_session, monkeypatch):
    _stub_router(monkeypatch)
    capture = _CaptureLogger()
    monkeypatch.setattr(llm_router_module, "logger", capture)
    monkeypatch.setattr(settings, "log_level", "DEBUG")
    monkeypatch.setattr(settings, "prompt_debug_logging_enabled", True)
    monkeypatch.setattr(settings, "prompt_debug_logging_max_chars_per_message", 16)

    router = LLMRouter(db_session, "tenant-1")
    router.chat(
        messages=[{"role": "user", "content": "x" * 64}],
        temperature=0.1,
    )

    payload = [item[1] for item in capture.events if item[0] == "llm_prompt_debug"][0]
    message = payload["messages"][0]
    assert message["truncated"] is True
    assert message["content"].endswith("...")
    assert len(message["content"]) == 19
