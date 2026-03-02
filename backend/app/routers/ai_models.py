from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.core.config import settings
from app.core.security import encrypt_secret
from app.models.llm_call_log import LLMCallLog
from app.models.llm_provider import LLMProvider
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.common import OAuthStartResponse
from app.schemas.llm import (
    CodexOAuthStatusRead,
    LLMProviderCreate,
    LLMProviderRead,
    LLMProviderTestResponse,
    LLMProviderUpdate,
)
from app.services.audit import audit_event
from app.services.llm_codex_oauth import (
    complete_oauth_callback,
    get_oauth_start_url,
    get_oauth_status,
)
from app.services.llm_codex_oauth import (
    disconnect as disconnect_codex_oauth,
)
from app.services.llm_router import LLMRouter

router = APIRouter(prefix="/tenant-settings/ai", tags=["ai-models"])


def _provider_requires_oauth(provider_type: str) -> bool:
    return provider_type.lower() == "codex"


def _provider_read(provider: LLMProvider, codex_connected: bool) -> LLMProviderRead:
    requires_oauth = _provider_requires_oauth(provider.provider_type)
    return LLMProviderRead(
        id=provider.id,
        tenant_id=provider.tenant_id,
        name=provider.name,
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        model_name=provider.model_name,
        is_default=provider.is_default,
        is_fallback=provider.is_fallback,
        rate_limit_rpm=provider.rate_limit_rpm,
        config_json=provider.config_json,
        has_api_key=bool(provider.api_key_encrypted),
        requires_oauth=requires_oauth,
        oauth_connected=codex_connected if requires_oauth else False,
        created_at=provider.created_at,
    )


@router.get("/providers", response_model=list[LLMProviderRead])
def list_providers(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[LLMProviderRead]:
    providers = db.execute(
        select(LLMProvider).where(LLMProvider.tenant_id == membership.tenant_id).order_by(LLMProvider.created_at)
    ).scalars().all()
    codex_connected = get_oauth_status(db, membership.tenant_id) is not None
    return [_provider_read(p, codex_connected) for p in providers]


@router.post("/providers", response_model=LLMProviderRead)
def create_provider(
    payload: LLMProviderCreate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> LLMProviderRead:
    if payload.provider_type.lower() == "codex" and payload.api_key:
        raise HTTPException(status_code=400, detail="Codex provider uses OAuth login and does not accept API key.")

    if payload.is_default:
        db.execute(update(LLMProvider).where(LLMProvider.tenant_id == admin.tenant_id).values(is_default=False))
    if payload.is_fallback:
        db.execute(update(LLMProvider).where(LLMProvider.tenant_id == admin.tenant_id).values(is_fallback=False))

    provider = LLMProvider(
        tenant_id=admin.tenant_id,
        name=payload.name,
        provider_type=payload.provider_type,
        base_url=payload.base_url,
        api_key_encrypted=encrypt_secret(payload.api_key) if payload.api_key and payload.provider_type.lower() != "codex" else None,
        model_name=payload.model_name,
        is_default=payload.is_default,
        is_fallback=payload.is_fallback,
        rate_limit_rpm=payload.rate_limit_rpm,
        config_json=payload.config_json,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="ai.provider.create",
        resource_type="llm_provider",
        resource_id=provider.id,
        action="create",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    codex_connected = get_oauth_status(db, admin.tenant_id) is not None
    return _provider_read(provider, codex_connected)


@router.patch("/providers/{provider_id}", response_model=LLMProviderRead)
def update_provider(
    provider_id: str,
    payload: LLMProviderUpdate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> LLMProviderRead:
    provider = db.execute(
        select(LLMProvider).where(LLMProvider.id == provider_id, LLMProvider.tenant_id == admin.tenant_id)
    ).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    updates = payload.model_dump(exclude_unset=True)
    if provider.provider_type.lower() == "codex" and updates.get("api_key"):
        raise HTTPException(status_code=400, detail="Codex provider uses OAuth login and does not accept API key.")

    if updates.get("is_default") is True:
        db.execute(update(LLMProvider).where(LLMProvider.tenant_id == admin.tenant_id).values(is_default=False))
    if updates.get("is_fallback") is True:
        db.execute(update(LLMProvider).where(LLMProvider.tenant_id == admin.tenant_id).values(is_fallback=False))

    for key, value in updates.items():
        if key == "api_key" and value and provider.provider_type.lower() != "codex":
            provider.api_key_encrypted = encrypt_secret(value)
        elif key != "api_key":
            setattr(provider, key, value)

    db.commit()
    db.refresh(provider)

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="ai.provider.update",
        resource_type="llm_provider",
        resource_id=provider.id,
        action="update",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    codex_connected = get_oauth_status(db, admin.tenant_id) is not None
    return _provider_read(provider, codex_connected)


@router.delete("/providers/{provider_id}")
def delete_provider(
    provider_id: str,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    provider = db.execute(
        select(LLMProvider).where(LLMProvider.id == provider_id, LLMProvider.tenant_id == admin.tenant_id)
    ).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    if provider.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Default provider cannot be deleted. Assign another default first.",
        )

    db.delete(provider)
    db.commit()

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="ai.provider.delete",
        resource_type="llm_provider",
        resource_id=provider_id,
        action="delete",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return {"message": "Provider deleted"}


@router.post("/providers/{provider_id}/test", response_model=LLMProviderTestResponse)
def test_provider(
    provider_id: str,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> LLMProviderTestResponse:
    provider = db.execute(
        select(LLMProvider).where(LLMProvider.id == provider_id, LLMProvider.tenant_id == admin.tenant_id)
    ).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    success, message = LLMRouter(db, admin.tenant_id).test_connection(provider)
    return LLMProviderTestResponse(success=success, message=message)


@router.get("/codex/oauth/start", response_model=OAuthStartResponse)
def codex_oauth_start(
    redirect_uri: str = Query(...),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> OAuthStartResponse:
    try:
        auth_url, state = get_oauth_start_url(
            db,
            tenant_id=admin.tenant_id,
            user_id=admin.user_id,
            redirect_uri=redirect_uri,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OAuthStartResponse(auth_url=auth_url, state=state)


@router.get("/codex/oauth/callback")
def codex_oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        token = complete_oauth_callback(
            db,
            tenant_id=admin.tenant_id,
            user_id=admin.user_id,
            code=code,
            state=state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="ai.codex.oauth.connect",
        resource_type="codex_oauth_token",
        resource_id=token.id,
        action="connect",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )
    return {"message": "Codex OAuth completed"}


@router.get("/codex/oauth/status", response_model=CodexOAuthStatusRead)
def codex_oauth_status(
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> CodexOAuthStatusRead:
    token = get_oauth_status(db, admin.tenant_id)
    if token is None:
        return CodexOAuthStatusRead(connected=False, connected_email=None, token_expires_at=None, scopes=[])
    return CodexOAuthStatusRead(
        connected=True,
        connected_email=token.connected_email,
        token_expires_at=token.token_expires_at,
        scopes=token.scopes or [],
    )


@router.post("/codex/oauth/disconnect")
def codex_oauth_disconnect(
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    disconnected = disconnect_codex_oauth(db, admin.tenant_id)
    if disconnected:
        audit_event(
            db,
            tenant_id=admin.tenant_id,
            user_id=admin.user_id,
            event_type="ai.codex.oauth.disconnect",
            resource_type="codex_oauth_token",
            action="disconnect",
            request_id=request.headers.get(settings.request_id_header),
            ip_address=request.client.host if request.client else None,
        )
        return {"message": "Codex OAuth disconnected"}
    return {"message": "Codex OAuth was not connected"}


@router.get("/logs")
def list_llm_logs(
    limit: int = 50,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[dict]:
    logs = db.execute(
        select(LLMCallLog)
        .where(LLMCallLog.tenant_id == membership.tenant_id)
        .order_by(LLMCallLog.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": log.id,
            "provider_id": log.provider_id,
            "model_name": log.model_name,
            "status": log.status,
            "prompt_tokens": log.prompt_tokens,
            "completion_tokens": log.completion_tokens,
            "total_tokens": log.total_tokens,
            "cost_usd": log.cost_usd,
            "response_ms": log.response_ms,
            "error_message": log.error_message,
            "created_at": log.created_at,
        }
        for log in logs
    ]
