from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class JiraConnectorConfig(BaseModel):
    base_url: str
    email: str
    api_token: str
    project_keys: list[str] = Field(default_factory=list)
    issue_types: list[str] = Field(default_factory=list)
    fields_mapping: dict = Field(default_factory=dict)
    enabled: bool = True


class JiraConnectorRead(BaseModel):
    id: str
    tenant_id: str
    base_url: str
    email: str
    project_keys: list[str]
    issue_types: list[str]
    fields_mapping: dict
    status: ConnectorStatus
