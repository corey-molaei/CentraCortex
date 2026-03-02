from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class FileConnectorConfig(BaseModel):
    allowed_extensions: list[str] = Field(default_factory=lambda: ["txt", "pdf", "docx"])
    enabled: bool = True


class FileConnectorRead(BaseModel):
    id: str
    tenant_id: str
    allowed_extensions: list[str]
    status: ConnectorStatus
