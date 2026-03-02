from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class DBConnectorConfig(BaseModel):
    connection_uri: str
    table_allowlist: list[str] = Field(default_factory=list)
    enabled: bool = True


class DBConnectorRead(BaseModel):
    id: str
    tenant_id: str
    table_allowlist: list[str]
    status: ConnectorStatus
