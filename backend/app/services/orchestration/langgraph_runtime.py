from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import delete
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.langgraph_checkpoint import LangGraphCheckpoint
from app.schemas.llm import Citation
from app.services.orchestration.chat_graph import GRAPH_NAME, invoke_chat_graph
from app.services.orchestration.state import GraphExecutionResult, GraphState

logger = structlog.get_logger(__name__)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Citation):
        return value.model_dump()
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _snapshot_state(state: GraphState) -> dict[str, Any]:
    keys = [
        "graph_name",
        "thread_id",
        "tenant_id",
        "user_id",
        "conversation_id",
        "latest_user_message",
        "client_timezone",
        "client_now_iso",
        "temperature",
        "provider_id_override",
        "effective_provider_id",
        "retrieval_limit",
        "safety_flags",
        "blocked",
        "intent",
        "answer",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "provider_id",
        "provider_name",
        "model_name",
        "interaction_type",
        "action_context",
        "options",
        "pending_action_status",
        "pending_action_id",
        "assistant_message_id",
        "error",
    ]
    data = {key: _to_jsonable(state.get(key)) for key in keys}
    data["citations"] = _to_jsonable(state.get("citations", []))

    # Keep payload json-safe for all DB engines.
    try:
        json.dumps(data)
    except TypeError:
        data = {"conversation_id": state.get("conversation_id"), "error": "snapshot_serialization_error"}
    return data


def _record_checkpoint(
    db: Session,
    *,
    state: GraphState,
    node_name: str,
    status: str,
    error_message: str | None,
) -> None:
    conversation_id = state.get("conversation_id")
    if not conversation_id:
        return
    try:
        db.rollback()
    except Exception:  # pragma: no cover - defensive; session may be clean already
        pass
    checkpoint = LangGraphCheckpoint(
        tenant_id=state["tenant_id"],
        user_id=state["user_id"],
        conversation_id=conversation_id,
        thread_id=state.get("thread_id", "pending-thread"),
        graph_name=GRAPH_NAME,
        node_name=node_name,
        status=status,
        state_json=_snapshot_state(state),
        error_message=error_message,
    )
    db.add(checkpoint)
    try:
        db.commit()
    except PendingRollbackError:
        db.rollback()
        db.add(checkpoint)
        db.commit()


def cleanup_expired_checkpoints(db: Session) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=max(1, settings.langgraph_checkpoint_ttl_hours))
    result = db.execute(delete(LangGraphCheckpoint).where(LangGraphCheckpoint.created_at < cutoff))
    db.commit()
    return int(result.rowcount or 0)


def run_chat_graph(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    user_messages: list[dict],
    temperature: float,
    provider_id_override: str | None,
    conversation_id: str | None,
    retrieval_limit: int,
    client_timezone: str | None,
    client_now_iso: str | None,
) -> GraphExecutionResult:
    state: GraphState = {
        "graph_name": GRAPH_NAME,
        "db": db,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "inbound_messages": user_messages,
        "temperature": temperature,
        "provider_id_override": provider_id_override,
        "retrieval_limit": retrieval_limit,
        "client_timezone": client_timezone,
        "client_now_iso": client_now_iso,
        "blocked": False,
        "safety_flags": [],
        "citations": [],
        "options": [],
        "action_context": None,
        "interaction_type": "answer",
        "checkpoint_hook": lambda **kwargs: _record_checkpoint(db, **kwargs),
    }

    try:
        state = invoke_chat_graph(state)
    except Exception as exc:
        logger.exception("chat_graph_failed", tenant_id=tenant_id, user_id=user_id)
        _record_checkpoint(
            db,
            state=state,
            node_name="runtime_exception",
            status="error",
            error_message=str(exc),
        )
        raise

    return GraphExecutionResult(
        conversation_id=str(state["conversation_id"]),
        assistant_message_id=str(state.get("assistant_message_id", "")),
        provider_id=str(state.get("provider_id") or "graph-error"),
        provider_name=str(state.get("provider_name") or "Graph Runtime"),
        model_name=str(state.get("model_name") or "graph"),
        answer=str(state.get("answer") or ""),
        prompt_tokens=int(state.get("prompt_tokens", 0)),
        completion_tokens=int(state.get("completion_tokens", 0)),
        total_tokens=int(state.get("total_tokens", 0)),
        cost_usd=float(state.get("cost_usd", 0.0)),
        blocked=bool(state.get("blocked", False)),
        safety_flags=list(state.get("safety_flags", [])),
        citations=list(state.get("citations", [])),
        interaction_type=state.get("interaction_type", "answer"),
        action_context=state.get("action_context"),
        options=list(state.get("options", [])),
    )
