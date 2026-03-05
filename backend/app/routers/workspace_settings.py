from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.models.tenant_membership import TenantMembership
from app.models.workspace_settings import WorkspaceSettings
from app.schemas.workspace_settings import WorkspaceAllowedActions, WorkspaceSettingsRead, WorkspaceSettingsUpdate

router = APIRouter(prefix="/workspace/settings", tags=["workspace-settings"])


def _get_or_create_settings(db: Session, tenant_id: str) -> WorkspaceSettings:
    settings = db.execute(select(WorkspaceSettings).where(WorkspaceSettings.tenant_id == tenant_id)).scalar_one_or_none()
    if settings:
        return settings
    settings = WorkspaceSettings(tenant_id=tenant_id, timezone="UTC", working_hours_json={}, allowed_actions_json={})
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def _to_schema(settings: WorkspaceSettings) -> WorkspaceSettingsRead:
    return WorkspaceSettingsRead(
        tenant_id=settings.tenant_id,
        business_name=settings.business_name,
        timezone=settings.timezone,
        default_email_signature=settings.default_email_signature,
        fallback_contact=settings.fallback_contact,
        escalation_email=settings.escalation_email,
        working_hours_json=settings.working_hours_json or {},
        allowed_actions=WorkspaceAllowedActions.model_validate(settings.allowed_actions_json or {}),
        updated_at=settings.updated_at,
    )


@router.get("", response_model=WorkspaceSettingsRead)
def get_workspace_settings(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> WorkspaceSettingsRead:
    settings = _get_or_create_settings(db, membership.tenant_id)
    return _to_schema(settings)


@router.put("", response_model=WorkspaceSettingsRead)
def update_workspace_settings(
    payload: WorkspaceSettingsUpdate,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> WorkspaceSettingsRead:
    settings = _get_or_create_settings(db, admin.tenant_id)
    updates = payload.model_dump(exclude_unset=True)

    if "allowed_actions" in updates and updates["allowed_actions"] is not None:
        updates["allowed_actions_json"] = updates.pop("allowed_actions").model_dump()

    for key, value in updates.items():
        setattr(settings, key, value)

    db.commit()
    db.refresh(settings)
    return _to_schema(settings)
