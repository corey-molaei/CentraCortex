from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class SlackConnectorConfig(BaseModel):
    workspace_name: str | None = None
    bot_token: str | None = None
    team_id: str | None = None
    channel_ids: list[str] = Field(default_factory=list)
    enabled: bool = True


class SlackConnectorRead(BaseModel):
    id: str
    tenant_id: str
    workspace_name: str | None = None
    team_id: str | None = None
    channel_ids: list[str]
    is_oauth_connected: bool
    status: ConnectorStatus
