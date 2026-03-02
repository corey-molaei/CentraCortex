from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMProviderCreate(BaseModel):
    name: str
    provider_type: str = Field(pattern="^(openai|vllm|ollama|other|codex)$")
    base_url: str
    api_key: str | None = None
    model_name: str
    is_default: bool = False
    is_fallback: bool = False
    rate_limit_rpm: int = Field(default=60, ge=1, le=10000)
    config_json: dict[str, Any] = Field(default_factory=dict)


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    is_default: bool | None = None
    is_fallback: bool | None = None
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=10000)
    config_json: dict[str, Any] | None = None


class LLMProviderRead(BaseModel):
    id: str
    tenant_id: str
    name: str
    provider_type: str
    base_url: str
    model_name: str
    is_default: bool
    is_fallback: bool
    rate_limit_rpm: int
    config_json: dict[str, Any]
    has_api_key: bool
    requires_oauth: bool = False
    oauth_connected: bool = False
    created_at: datetime


class LLMProviderTestResponse(BaseModel):
    success: bool
    message: str


class CodexOAuthStatusRead(BaseModel):
    connected: bool
    connected_email: str | None = None
    token_expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    temperature: float = 0.2
    provider_id_override: str | None = None
    conversation_id: str | None = None
    retrieval_limit: int = Field(default=6, ge=1, le=20)
    client_timezone: str | None = None


class Citation(BaseModel):
    document_id: str
    document_title: str
    document_url: str | None = None
    source_type: str
    chunk_id: str
    chunk_index: int
    snippet: str


class ChatResponse(BaseModel):
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
    blocked: bool = False
    safety_flags: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class ChatActionOption(BaseModel):
    id: str
    label: str


class ChatActionContext(BaseModel):
    action_type: str
    status: str | None = None
    account_id: str | None = None
    account_label: str | None = None
    pending_action_id: str | None = None


class ChatV2Response(BaseModel):
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
    blocked: bool = False
    safety_flags: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    interaction_type: Literal["answer", "confirmation_required", "selection_required", "execution_result", "error"] = (
        "answer"
    )
    action_context: ChatActionContext | None = None
    options: list[ChatActionOption] = Field(default_factory=list)


class ChatActionConfirmRequest(BaseModel):
    conversation_id: str
    confirm: bool
    provider_id_override: str | None = None
    retrieval_limit: int = Field(default=8, ge=1, le=20)
    temperature: float = 0.2
    client_timezone: str | None = None


class ChatActionSelectRequest(BaseModel):
    conversation_id: str
    selection: str
    provider_id_override: str | None = None
    retrieval_limit: int = Field(default=8, ge=1, le=20)
    temperature: float = 0.2
    client_timezone: str | None = None


class ConversationMessageRead(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    citations: list[Citation] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)
    provider_name: str | None = None
    model_name: str | None = None


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime


class ConversationDetail(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    messages: list[ConversationMessageRead]


class ChatReportRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ChatReportResponse(BaseModel):
    status: str
    feedback_id: str
