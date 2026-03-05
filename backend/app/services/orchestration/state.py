from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from app.schemas.llm import Citation

InteractionType = Literal[
    "answer",
    "confirmation_required",
    "selection_required",
    "execution_result",
    "error",
]


class ActionOption(TypedDict):
    id: str
    label: str


class ActionContext(TypedDict, total=False):
    action_type: str
    status: str
    account_id: str
    account_label: str
    pending_action_id: str


class GraphState(TypedDict, total=False):
    db: Any
    graph_name: str
    thread_id: str

    tenant_id: str
    user_id: str
    conversation_id: str | None

    inbound_messages: list[dict[str, str]]
    latest_user_message: str
    client_timezone: str | None
    client_now_iso: str | None
    temperature: float
    provider_id_override: str | None
    effective_provider_id: str | None
    retrieval_limit: int

    safety_flags: list[str]
    blocked: bool

    intent: str

    answer: str
    citations: list[Citation]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float

    provider_id: str
    provider_name: str
    model_name: str

    interaction_type: InteractionType
    action_context: ActionContext | None
    options: list[ActionOption]

    pending_action_status: str | None
    pending_action_id: str | None

    conversation_obj: Any
    assistant_message_id: str

    error: str | None


@dataclass
class GraphExecutionResult:
    conversation_id: str
    assistant_message_id: str
    provider_id: str
    provider_name: str
    model_name: str
    answer: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    blocked: bool
    safety_flags: list[str]
    citations: list[Citation]
    interaction_type: InteractionType
    action_context: ActionContext | None
    options: list[ActionOption]
