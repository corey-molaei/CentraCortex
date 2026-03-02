from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db
from app.models.tenant_membership import TenantMembership
from app.schemas.llm import (
    ChatActionConfirmRequest,
    ChatActionSelectRequest,
    ChatRequest,
    ChatV2Response,
)
from app.services.chat_runtime import run_chat_v2

router = APIRouter(prefix="/chat", tags=["chat-v2"])


@router.post("/complete", response_model=ChatV2Response)
def complete_chat_v2(
    payload: ChatRequest,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChatV2Response:
    if not payload.messages:
        raise HTTPException(status_code=400, detail="At least one message is required")

    try:
        result = run_chat_v2(
            db,
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            user_messages=[m.model_dump() for m in payload.messages],
            temperature=payload.temperature,
            provider_id_override=payload.provider_id_override,
            conversation_id=payload.conversation_id,
            retrieval_limit=payload.retrieval_limit,
            client_timezone=payload.client_timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ChatV2Response(
        conversation_id=result.conversation_id,
        assistant_message_id=result.assistant_message_id,
        provider_id=result.provider_id,
        provider_name=result.provider_name,
        model_name=result.model_name,
        answer=result.answer,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        cost_usd=result.cost_usd,
        blocked=result.blocked,
        safety_flags=result.safety_flags,
        citations=result.citations,
        interaction_type=result.interaction_type,
        action_context=result.action_context,
        options=result.options,
    )


@router.post("/actions/confirm", response_model=ChatV2Response)
def confirm_action_v2(
    payload: ChatActionConfirmRequest,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChatV2Response:
    message = "yes" if payload.confirm else "no"
    try:
        result = run_chat_v2(
            db,
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            user_messages=[{"role": "user", "content": message}],
            temperature=payload.temperature,
            provider_id_override=payload.provider_id_override,
            conversation_id=payload.conversation_id,
            retrieval_limit=payload.retrieval_limit,
            client_timezone=payload.client_timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ChatV2Response(
        conversation_id=result.conversation_id,
        assistant_message_id=result.assistant_message_id,
        provider_id=result.provider_id,
        provider_name=result.provider_name,
        model_name=result.model_name,
        answer=result.answer,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        cost_usd=result.cost_usd,
        blocked=result.blocked,
        safety_flags=result.safety_flags,
        citations=result.citations,
        interaction_type=result.interaction_type,
        action_context=result.action_context,
        options=result.options,
    )


@router.post("/actions/select", response_model=ChatV2Response)
def select_action_v2(
    payload: ChatActionSelectRequest,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChatV2Response:
    if not payload.selection.strip():
        raise HTTPException(status_code=400, detail="selection is required")

    try:
        result = run_chat_v2(
            db,
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            user_messages=[{"role": "user", "content": payload.selection.strip()}],
            temperature=payload.temperature,
            provider_id_override=payload.provider_id_override,
            conversation_id=payload.conversation_id,
            retrieval_limit=payload.retrieval_limit,
            client_timezone=payload.client_timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ChatV2Response(
        conversation_id=result.conversation_id,
        assistant_message_id=result.assistant_message_id,
        provider_id=result.provider_id,
        provider_name=result.provider_name,
        model_name=result.model_name,
        answer=result.answer,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        cost_usd=result.cost_usd,
        blocked=result.blocked,
        safety_flags=result.safety_flags,
        citations=result.citations,
        interaction_type=result.interaction_type,
        action_context=result.action_context,
        options=result.options,
    )
