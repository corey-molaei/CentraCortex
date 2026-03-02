from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class ConfluenceConnectorConfig(BaseModel):
    base_url: str
    email: str
    api_token: str
    space_keys: list[str] = Field(default_factory=list)
    enabled: bool = True


class ConfluenceConnectorRead(BaseModel):
    id: str
    tenant_id: str
    base_url: str
    email: str
    space_keys: list[str]
    status: ConnectorStatus
