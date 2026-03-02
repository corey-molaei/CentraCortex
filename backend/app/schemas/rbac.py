from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None


class RoleRead(BaseModel):
    id: str
    tenant_id: str | None = None
    name: str
    description: str | None = None
    is_system: bool
    created_at: datetime


class GroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    description: str | None = None


class GroupRead(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None = None
    created_at: datetime


class InviteUserRequest(BaseModel):
    email: EmailStr
    role: str = Field(min_length=2, max_length=100)


class InviteUserResponse(BaseModel):
    invitation_id: str
    invite_token: str
    status: str


class UserListItem(BaseModel):
    id: str
    email: EmailStr
    full_name: str | None = None
    role: str


class UserDetail(BaseModel):
    id: str
    email: EmailStr
    full_name: str | None = None
    role: str
    groups: list[GroupRead]
    custom_roles: list[RoleRead]


class AssignGroupRequest(BaseModel):
    group_id: str


class AssignRoleRequest(BaseModel):
    role_id: str


class PolicyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    policy_type: str = Field(pattern="^(document|tool|data_source)$")
    resource_id: str = Field(min_length=1, max_length=255)
    allow_all: bool = False
    allowed_user_ids: list[str] = Field(default_factory=list)
    allowed_group_ids: list[str] = Field(default_factory=list)
    allowed_role_names: list[str] = Field(default_factory=list)
    active: bool = True


class PolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    allow_all: bool | None = None
    allowed_user_ids: list[str] | None = None
    allowed_group_ids: list[str] | None = None
    allowed_role_names: list[str] | None = None
    active: bool | None = None


class PolicyRead(BaseModel):
    id: str
    tenant_id: str
    name: str
    policy_type: str
    resource_id: str
    allow_all: bool
    allowed_user_ids: list[str]
    allowed_group_ids: list[str]
    allowed_role_names: list[str]
    active: bool
    created_at: datetime


class DocumentCreate(BaseModel):
    source_type: str = "manual"
    source_id: str
    title: str
    raw_text: str
    acl_policy_id: str | None = None


class DocumentRead(BaseModel):
    id: str
    source_type: str
    source_id: str
    title: str
    acl_policy_id: str | None = None


class ToolExecutionRequest(BaseModel):
    payload: dict = Field(default_factory=dict)
