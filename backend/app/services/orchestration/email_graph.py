from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.chat_pending_email_action import ChatPendingEmailAction
from app.services.chat_email_actions import maybe_handle_email_chat_action


def _latest_pending_email_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
) -> ChatPendingEmailAction | None:
    return db.execute(
        select(ChatPendingEmailAction)
        .where(
            ChatPendingEmailAction.tenant_id == tenant_id,
            ChatPendingEmailAction.user_id == user_id,
            ChatPendingEmailAction.conversation_id == conversation_id,
            ChatPendingEmailAction.status == "pending_confirmation",
        )
        .order_by(desc(ChatPendingEmailAction.updated_at), desc(ChatPendingEmailAction.created_at))
    ).scalar_one_or_none()


def run_email_subgraph(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
) -> dict:
    action = maybe_handle_email_chat_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
    )
    if not action or not action.handled:
        return {"intent_handled": False}

    response: dict = {
        "intent_handled": True,
        "answer": action.answer,
        "provider_id": "email-action",
        "provider_name": "Email Action Engine",
        "model_name": "email-action",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "citations": [],
        "interaction_type": "execution_result",
        "action_context": {"action_type": "email"},
        "options": [],
    }

    pending = _latest_pending_email_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if pending:
        response["interaction_type"] = "confirmation_required"
        response["pending_action_id"] = pending.id
        response["pending_action_status"] = pending.status
        response["action_context"] = {
            "action_type": "email_send",
            "status": pending.status,
            "account_id": pending.account_id,
            "pending_action_id": pending.id,
        }
        response["options"] = [
            {"id": "yes", "label": "Confirm"},
            {"id": "no", "label": "Cancel"},
        ]

    return response
