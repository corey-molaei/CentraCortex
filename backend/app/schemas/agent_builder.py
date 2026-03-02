from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentSpecTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=3, max_length=500)
    requires_approval: bool = True


class AgentSpecDataSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=3, max_length=500)


class AgentSpecTone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice: str = Field(min_length=1, max_length=64)
    formality: str = Field(pattern="^(low|medium|high)$")
    style_rules: list[str] = Field(default_factory=list)
    few_shot_examples: list[str] = Field(default_factory=list)


class AgentSpecOutputContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = Field(min_length=1, max_length=64)
    max_length: int = Field(default=1200, ge=100, le=8000)
    include_citations: bool = True


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=255)
    goal: str = Field(min_length=8, max_length=2000)
    system_prompt: str = Field(min_length=16)
    agent_type: str = Field(pattern="^(knowledge|comms|ops|sql|guard)$")
    risk_level: str = Field(pattern="^(low|medium|high|critical)$")
    tools: list[AgentSpecTool] = Field(default_factory=list)
    data_sources: list[AgentSpecDataSource] = Field(default_factory=list)
    tone: AgentSpecTone
    guardrails: list[str] = Field(default_factory=list)
    output_contract: AgentSpecOutputContract


class GeneratedTestCase(BaseModel):
    prompt: str
    expected_behavior: str
    policy_focus: str


class BuilderAgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class GenerateSpecRequest(BaseModel):
    prompt: str = Field(min_length=8, max_length=12000)
    selected_tools: list[str] = Field(default_factory=list)
    selected_data_sources: list[str] = Field(default_factory=list)
    risk_level: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    example_texts: list[str] = Field(default_factory=list)
    generate_tests_count: int = Field(default=6, ge=3, le=20)


class StyleExampleRead(BaseModel):
    id: str
    filename: str | None = None
    content: str
    profile_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SpecVersionRead(BaseModel):
    id: str
    tenant_id: str
    agent_id: str
    version_number: int
    status: str
    source_prompt: str
    spec_json: AgentSpec
    risk_level: str
    selected_tools_json: list[str] = Field(default_factory=list)
    selected_data_sources_json: list[str] = Field(default_factory=list)
    tone_profile_json: dict[str, Any] = Field(default_factory=dict)
    generated_tests_json: list[GeneratedTestCase] = Field(default_factory=list)
    created_by_user_id: str | None = None
    created_at: datetime
    deployed_at: datetime | None = None
    rollback_note: str | None = None


class SpecVersionDetail(BaseModel):
    version: SpecVersionRead
    style_examples: list[StyleExampleRead] = Field(default_factory=list)


class UpdateSpecRequest(BaseModel):
    spec_json: AgentSpec


class DeploySpecResponse(BaseModel):
    status: str
    version: SpecVersionRead


class RollbackRequest(BaseModel):
    target_version_id: str
    note: str | None = Field(default=None, max_length=2000)


class UploadStyleExamplesResponse(BaseModel):
    uploaded_count: int
    message: str
