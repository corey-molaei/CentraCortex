from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentDefinitionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    system_prompt: str = Field(min_length=10)
    default_agent_type: str = Field(default="knowledge", pattern="^(knowledge|comms|ops|sql|guard)$")
    allowed_tools: list[str] = Field(default_factory=list)
    enabled: bool = True
    config_json: dict[str, Any] = Field(default_factory=dict)


class AgentDefinitionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    system_prompt: str | None = Field(default=None, min_length=10)
    default_agent_type: str | None = Field(default=None, pattern="^(knowledge|comms|ops|sql|guard)$")
    allowed_tools: list[str] | None = None
    enabled: bool | None = None
    config_json: dict[str, Any] | None = None


class AgentDefinitionRead(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None = None
    system_prompt: str
    default_agent_type: str
    allowed_tools: list[str] = Field(default_factory=list)
    enabled: bool
    config_json: dict[str, Any] = Field(default_factory=dict)
    created_by_user_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentRunRequest(BaseModel):
    agent_id: str
    input_text: str = Field(min_length=1, max_length=12000)
    tool_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class AgentTraceStepRead(BaseModel):
    id: str
    step_order: int
    agent_name: str
    step_type: str
    tool_name: str | None = None
    input_json: dict[str, Any] = Field(default_factory=dict)
    output_json: dict[str, Any] = Field(default_factory=dict)
    reasoning_redacted: str | None = None
    status: str
    created_at: datetime


class ToolApprovalRead(BaseModel):
    id: str
    run_id: str
    tool_name: str
    requested_by_user_id: str | None = None
    approved_by_user_id: str | None = None
    status: str
    request_payload_json: dict[str, Any] = Field(default_factory=dict)
    decision_note: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class AgentRunRead(BaseModel):
    id: str
    tenant_id: str
    agent_id: str
    initiated_by_user_id: str | None = None
    status: str
    input_text: str
    output_text: str | None = None
    routed_agent: str | None = None
    error_message: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None


class AgentRunDetail(BaseModel):
    run: AgentRunRead
    traces: list[AgentTraceStepRead] = Field(default_factory=list)
    approvals: list[ToolApprovalRead] = Field(default_factory=list)


class ToolApprovalDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
