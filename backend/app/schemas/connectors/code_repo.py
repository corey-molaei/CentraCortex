from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class CodeRepoConnectorConfig(BaseModel):
    provider: str = Field(pattern="^(github|gitlab)$")
    base_url: str
    token: str
    repositories: list[str] = Field(default_factory=list)
    include_readme: bool = True
    include_issues: bool = True
    include_prs: bool = True
    include_wiki: bool = True
    enabled: bool = True


class CodeRepoConnectorRead(BaseModel):
    id: str
    tenant_id: str
    provider: str
    base_url: str
    repositories: list[str]
    include_readme: bool
    include_issues: bool
    include_prs: bool
    include_wiki: bool
    status: ConnectorStatus
