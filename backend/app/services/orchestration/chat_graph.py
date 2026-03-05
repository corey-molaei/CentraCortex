from __future__ import annotations

from collections.abc import Callable

import structlog
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.chat_pending_action import ChatPendingAction
from app.models.chat_pending_email_action import ChatPendingEmailAction
from app.services.audit import audit_event
from app.services.chat_runtime import (
    _resolve_effective_provider_for_conversation,
    _save_message,
    analyze_user_prompt,
    get_or_create_conversation,
    run_knowledge_generation,
)
from app.services.orchestration.agent_graph import run_agent_subgraph
from app.services.orchestration.calendar_graph import run_calendar_subgraph
from app.services.orchestration.email_graph import run_email_subgraph
from app.services.orchestration.state import GraphState

try:  # pragma: no cover - optional dependency
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    LANGGRAPH_AVAILABLE = False

logger = structlog.get_logger(__name__)

GRAPH_NAME = "chat_main_graph"

CALENDAR_TOKENS = {
    "calendar",
    "calendars",
    "event",
    "events",
    "meeting",
    "meetings",
    "schedule",
}
EMAIL_TOKENS = {
    "email",
    "emails",
    "gmail",
    "inbox",
    "mail",
    "mails",
    "send",
    "smtp",
}
AGENT_TOKENS = {"agent", "tool", "approval", "workflow"}


def _checkpoint(state: GraphState, node_name: str, status: str = "ok", error_message: str | None = None) -> None:
    hook = state.get("checkpoint_hook")
    if callable(hook):
        hook(state=state, node_name=node_name, status=status, error_message=error_message)


def _set_error(state: GraphState, *, message: str) -> GraphState:
    state["error"] = message
    state["answer"] = message
    state["blocked"] = False
    state["safety_flags"] = []
    state["provider_id"] = "graph-error"
    state["provider_name"] = "Graph Runtime"
    state["model_name"] = "graph-error"
    state["prompt_tokens"] = 0
    state["completion_tokens"] = 0
    state["total_tokens"] = 0
    state["cost_usd"] = 0.0
    state["citations"] = []
    state["interaction_type"] = "error"
    state["action_context"] = {"action_type": "graph", "status": "error"}
    state["options"] = []
    return state


def _load_context_node(state: GraphState) -> GraphState:
    db: Session = state["db"]
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    user_messages = state["inbound_messages"]

    if not user_messages:
        return _set_error(state, message="At least one message is required")

    last_user_msg = str(user_messages[-1].get("content", "")).strip()
    if not last_user_msg:
        return _set_error(state, message="Last user message is empty")

    conversation = get_or_create_conversation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=state.get("conversation_id"),
        seed_message=last_user_msg,
    )
    safety = analyze_user_prompt(last_user_msg)

    state["conversation_id"] = conversation.id
    state["conversation_obj"] = conversation
    state["thread_id"] = f"{tenant_id}:{user_id}:{conversation.id}"
    state["latest_user_message"] = last_user_msg
    state["safety_flags"] = safety.flags
    state["blocked"] = bool(safety.blocked)

    if not state["blocked"]:
        effective_provider_id = _resolve_effective_provider_for_conversation(
            db,
            tenant_id=tenant_id,
            conversation=conversation,
            request_override=state.get("provider_id_override"),
        )
        state["effective_provider_id"] = effective_provider_id
        logger.debug(
            "chat_provider_pin_resolved",
            conversation_id=conversation.id,
            request_provider_id_override=state.get("provider_id_override"),
            effective_provider_id=effective_provider_id,
            pinned_model_name=conversation.pinned_model_name,
        )

    _save_message(
        db,
        tenant_id=tenant_id,
        conversation=conversation,
        user_id=user_id,
        role="user",
        content=last_user_msg,
        safety_flags=safety.flags,
    )

    _checkpoint(state, "load_context")
    return state


def _safety_gate_node(state: GraphState) -> GraphState:
    if state.get("error"):
        _checkpoint(state, "safety_gate", status="error", error_message=state["error"])
        return state

    if state.get("blocked"):
        state["answer"] = "I cannot assist with requests to reveal secrets, credentials, or protected system instructions."
        state["provider_id"] = "blocked"
        state["provider_name"] = "Safety Guard"
        state["model_name"] = "guardrail"
        state["prompt_tokens"] = 0
        state["completion_tokens"] = 0
        state["total_tokens"] = 0
        state["cost_usd"] = 0.0
        state["citations"] = []
        state["interaction_type"] = "error"
        state["action_context"] = {"action_type": "safety", "status": "blocked"}
        state["options"] = []

    _checkpoint(state, "safety_gate")
    return state


def _resume_pending_action_node(state: GraphState) -> GraphState:
    if state.get("blocked") or state.get("error"):
        _checkpoint(state, "resume_pending_action")
        return state

    db: Session = state["db"]
    pending_calendar = db.execute(
        select(ChatPendingAction)
        .where(
            ChatPendingAction.tenant_id == state["tenant_id"],
            ChatPendingAction.user_id == state["user_id"],
            ChatPendingAction.conversation_id == state["conversation_id"],
            ChatPendingAction.status.in_(["pending_disambiguation", "pending_confirmation"]),
        )
        .order_by(desc(ChatPendingAction.updated_at), desc(ChatPendingAction.created_at))
    ).scalar_one_or_none()

    pending_email = db.execute(
        select(ChatPendingEmailAction)
        .where(
            ChatPendingEmailAction.tenant_id == state["tenant_id"],
            ChatPendingEmailAction.user_id == state["user_id"],
            ChatPendingEmailAction.conversation_id == state["conversation_id"],
            ChatPendingEmailAction.status == "pending_confirmation",
        )
        .order_by(desc(ChatPendingEmailAction.updated_at), desc(ChatPendingEmailAction.created_at))
    ).scalar_one_or_none()

    if pending_calendar:
        state["intent"] = "calendar"
        state["pending_action_id"] = pending_calendar.id
        state["pending_action_status"] = pending_calendar.status
    elif pending_email:
        state["intent"] = "email"
        state["pending_action_id"] = pending_email.id
        state["pending_action_status"] = pending_email.status

    _checkpoint(state, "resume_pending_action")
    return state


def _intent_router_node(state: GraphState) -> GraphState:
    if state.get("blocked") or state.get("error"):
        _checkpoint(state, "intent_router")
        return state

    if state.get("intent"):
        _checkpoint(state, "intent_router")
        return state

    lowered = state["latest_user_message"].lower()
    tokens = set(lowered.replace("/", " ").replace(",", " ").split())

    if tokens.intersection(CALENDAR_TOKENS):
        state["intent"] = "calendar"
    elif tokens.intersection(EMAIL_TOKENS):
        state["intent"] = "email"
    elif tokens.intersection(AGENT_TOKENS):
        state["intent"] = "agent"
    else:
        state["intent"] = "knowledge"

    _checkpoint(state, "intent_router")
    return state


def _dispatch_node(state: GraphState) -> GraphState:
    if state.get("blocked") or state.get("error"):
        _checkpoint(state, "dispatch")
        return state

    db: Session = state["db"]
    result: dict | None = None
    intent = state.get("intent", "knowledge")

    if intent == "calendar":
        result = run_calendar_subgraph(
            db,
            tenant_id=state["tenant_id"],
            user_id=state["user_id"],
            conversation_id=state["conversation_id"],
            message=state["latest_user_message"],
            client_timezone=state.get("client_timezone"),
            client_now_iso=state.get("client_now_iso"),
            provider_id_override=state.get("effective_provider_id"),
        )
    elif intent == "email":
        result = run_email_subgraph(
            db,
            tenant_id=state["tenant_id"],
            user_id=state["user_id"],
            conversation_id=state["conversation_id"],
            message=state["latest_user_message"],
            client_timezone=state.get("client_timezone"),
            client_now_iso=state.get("client_now_iso"),
            provider_id_override=state.get("effective_provider_id"),
        )
    elif intent == "agent":
        result = run_agent_subgraph(
            db,
            tenant_id=state["tenant_id"],
            user_id=state["user_id"],
            message=state["latest_user_message"],
        )

    if result and result.get("intent_handled"):
        state["answer"] = result["answer"]
        state["provider_id"] = result["provider_id"]
        state["provider_name"] = result["provider_name"]
        state["model_name"] = result["model_name"]
        state["prompt_tokens"] = int(result.get("prompt_tokens", 0))
        state["completion_tokens"] = int(result.get("completion_tokens", 0))
        state["total_tokens"] = int(result.get("total_tokens", 0))
        state["cost_usd"] = float(result.get("cost_usd", 0.0))
        state["citations"] = result.get("citations", [])
        state["interaction_type"] = result.get("interaction_type", "execution_result")
        state["action_context"] = result.get("action_context")
        state["options"] = result.get("options", [])
        state["pending_action_id"] = result.get("pending_action_id")
        state["pending_action_status"] = result.get("pending_action_status")
        _checkpoint(state, "dispatch")
        return state

    provider, knowledge = run_knowledge_generation(
        db,
        tenant_id=state["tenant_id"],
        user_id=state["user_id"],
        conversation=state["conversation_obj"],
        last_user_msg=state["latest_user_message"],
        temperature=state["temperature"],
        provider_id_override=state.get("effective_provider_id"),
        retrieval_limit=state["retrieval_limit"],
        allow_fallback=False,
    )
    state["answer"] = knowledge["answer"]
    state["provider_id"] = provider.id
    state["provider_name"] = provider.name
    state["model_name"] = provider.model_name
    state["prompt_tokens"] = int(knowledge["prompt_tokens"])
    state["completion_tokens"] = int(knowledge["completion_tokens"])
    state["total_tokens"] = int(knowledge["total_tokens"])
    state["cost_usd"] = float(knowledge["cost_usd"])
    state["citations"] = knowledge["citations"]
    state["interaction_type"] = "answer"
    state["action_context"] = None
    state["options"] = []

    _checkpoint(state, "dispatch")
    return state


def _persist_messages_node(state: GraphState) -> GraphState:
    if state.get("assistant_message_id"):
        _checkpoint(state, "persist_messages")
        return state

    db: Session = state["db"]
    provider_id = state.get("provider_id")
    # Only persist FK-backed provider ids for actual model answers.
    # Action engines are synthetic and do not exist in llm_providers.
    if state.get("interaction_type") != "answer":
        provider_id = None
    if provider_id in {"blocked", "graph-error"}:
        provider_id = None

    assistant_message = _save_message(
        db,
        tenant_id=state["tenant_id"],
        conversation=state["conversation_obj"],
        user_id=None,
        role="assistant",
        content=state.get("answer", ""),
        citations=state.get("citations", []),
        safety_flags=state.get("safety_flags", []),
        llm_provider_id=provider_id,
        llm_model_name=state.get("model_name"),
        prompt_tokens=int(state.get("prompt_tokens", 0)),
        completion_tokens=int(state.get("completion_tokens", 0)),
        total_tokens=int(state.get("total_tokens", 0)),
        cost_usd=float(state.get("cost_usd", 0.0)),
    )
    state["assistant_message_id"] = assistant_message.id

    _checkpoint(state, "persist_messages")
    return state


def _emit_audit_node(state: GraphState) -> GraphState:
    db: Session = state["db"]
    try:
        audit_event(
            db,
            event_type="chat.v2.complete",
            resource_type="chat_conversation",
            action="complete",
            tenant_id=state["tenant_id"],
            user_id=state["user_id"],
            resource_id=state["conversation_id"],
            payload={
                "interaction_type": state.get("interaction_type", "answer"),
                "provider_id": state.get("provider_id"),
                "citations": len(state.get("citations", [])),
                "intent": state.get("intent"),
                "pending_action_status": state.get("pending_action_status"),
            },
        )
    except Exception:
        logger.exception("chat_v2_audit_failed", tenant_id=state.get("tenant_id"), user_id=state.get("user_id"))

    _checkpoint(state, "emit_audit")
    return state


def _return_response_node(state: GraphState) -> GraphState:
    _checkpoint(state, "return_response")
    return state


NODES: list[tuple[str, Callable[[GraphState], GraphState]]] = [
    ("load_context", _load_context_node),
    ("safety_gate", _safety_gate_node),
    ("resume_pending_action", _resume_pending_action_node),
    ("intent_router", _intent_router_node),
    ("dispatch", _dispatch_node),
    ("persist_messages", _persist_messages_node),
    ("emit_audit", _emit_audit_node),
    ("return_response", _return_response_node),
]


_COMPILED_GRAPH = None


def _build_langgraph():
    graph = StateGraph(GraphState)
    for node_name, node_fn in NODES:
        graph.add_node(node_name, node_fn)

    graph.set_entry_point("load_context")
    for idx in range(len(NODES) - 1):
        graph.add_edge(NODES[idx][0], NODES[idx + 1][0])
    graph.add_edge("return_response", END)

    return graph.compile()


def invoke_chat_graph(state: GraphState) -> GraphState:
    global _COMPILED_GRAPH

    if LANGGRAPH_AVAILABLE:
        if _COMPILED_GRAPH is None:
            _COMPILED_GRAPH = _build_langgraph()
        return _COMPILED_GRAPH.invoke(state)

    logger.warning("langgraph_unavailable_using_sequential_runtime")
    for _, node_fn in NODES:
        state = node_fn(state)
    return state
