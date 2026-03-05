from datetime import datetime

from pydantic import BaseModel, Field


class RecipeRead(BaseModel):
    id: str
    key: str
    name: str
    description: str
    default_config_json: dict = Field(default_factory=dict)


class WorkspaceRecipeStateRead(BaseModel):
    id: str
    tenant_id: str
    recipe_id: str
    enabled: bool
    config_json: dict = Field(default_factory=dict)
    updated_at: datetime


class WorkspaceRecipeStateUpsert(BaseModel):
    enabled: bool
    config_json: dict = Field(default_factory=dict)
