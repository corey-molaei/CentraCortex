from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class SharePointConnectorConfig(BaseModel):
    azure_tenant_id: str
    client_id: str
    client_secret: str
    site_ids: list[str] = Field(default_factory=list)
    drive_ids: list[str] = Field(default_factory=list)
    enabled: bool = True


class SharePointConnectorRead(BaseModel):
    id: str
    tenant_id: str
    azure_tenant_id: str
    client_id: str
    site_ids: list[str]
    drive_ids: list[str]
    status: ConnectorStatus
