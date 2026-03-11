from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db
from app.models.tenant_membership import TenantMembership
from app.schemas.llm import (
    ChatReportRequest,
    ChatReportResponse,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationSummary,
)
from app.services.audit import audit_event
from app.services.chat_runtime import (
    create_feedback,
    delete_conversation,
    get_conversation_detail,
    list_conversations,
    run_chat,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/complete", response_model=ChatResponse)
def complete_chat(
    payload: ChatRequest,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChatResponse:
    if not payload.messages:
        raise HTTPException(status_code=400, detail="At least one message is required")

    try:
        conversation, assistant_message, provider, result = run_chat(
            db,
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            user_messages=[m.model_dump() for m in payload.messages],
            temperature=payload.temperature,
            provider_id_override=payload.provider_id_override,
            conversation_id=payload.conversation_id,
            retrieval_limit=payload.retrieval_limit,
            client_timezone=payload.client_timezone,
            client_now_iso=payload.client_now_iso,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="chat.complete",
        resource_type="chat_conversation",
        action="complete",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=conversation.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={
            "blocked": result["blocked"],
            "safety_flags": result["safety_flags"],
            "provider_id": provider.id if provider else None,
            "retrieval_citations": len(result["citations"]),
        },
    )

    return ChatResponse(
        conversation_id=conversation.id,
        assistant_message_id=assistant_message.id,
        provider_id=provider.id if provider else "blocked",
        provider_name=provider.name if provider else "Safety Guard",
        model_name=provider.model_name if provider else "guardrail",
        answer=result["answer"],
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
        total_tokens=result["total_tokens"],
        cost_usd=result["cost_usd"],
        blocked=result["blocked"],
        safety_flags=result["safety_flags"],
        citations=result["citations"],
    )


@router.get("/conversations", response_model=list[ConversationSummary])
def conversations(
    limit: int = Query(default=50, ge=1, description="Number of conversations to return"),
    offset: int = Query(default=0, ge=0, description="Number of conversations to skip"),
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[ConversationSummary]:
    bounded_limit = min(limit, 100)
    return list_conversations(
        db,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        limit=bounded_limit,
        offset=offset,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def conversation_detail(
    conversation_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ConversationDetail:
    detail = get_conversation_detail(
        db,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        conversation_id=conversation_id,
    )
    if not detail:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.delete("/conversations/{conversation_id}")
def delete_chat_conversation(
    conversation_id: str,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    deleted = delete_conversation(
        db,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        conversation_id=conversation_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    audit_event(
        db,
        event_type="chat.delete_conversation",
        resource_type="chat_conversation",
        action="delete",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=conversation_id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
    )
    return {"message": "Conversation deleted"}


@router.post("/conversations/{conversation_id}/messages/{message_id}/report", response_model=ChatReportResponse)
def report_answer(
    conversation_id: str,
    message_id: str,
    payload: ChatReportRequest,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChatReportResponse:
    try:
        feedback = create_feedback(
            db,
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="chat.report_answer",
        resource_type="chat_feedback",
        action="report",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=feedback.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"conversation_id": conversation_id, "message_id": message_id},
    )
    return ChatReportResponse(status="recorded", feedback_id=feedback.id)
