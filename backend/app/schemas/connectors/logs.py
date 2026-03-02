from pydantic import BaseModel

from app.schemas.connectors.common import ConnectorStatus


class LogsConnectorConfig(BaseModel):
    folder_path: str
    file_glob: str = "*.log"
    parser_type: str = "plain"
    enabled: bool = True


class LogsConnectorRead(BaseModel):
    id: str
    tenant_id: str
    folder_path: str
    file_glob: str
    parser_type: str
    status: ConnectorStatus
