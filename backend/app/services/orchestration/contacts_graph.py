from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.chat_pending_action import ChatPendingAction
from app.services.chat_contacts_actions import (
    INTENT_CREATE,
    INTENT_DELETE,
    INTENT_UPDATE,
    maybe_handle_contacts_chat_action,
)


def _latest_pending_contacts_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
) -> ChatPendingAction | None:
    return db.execute(
        select(ChatPendingAction)
        .where(
            ChatPendingAction.tenant_id == tenant_id,
            ChatPendingAction.user_id == user_id,
            ChatPendingAction.conversation_id == conversation_id,
            ChatPendingAction.action_type.in_([INTENT_CREATE, INTENT_UPDATE, INTENT_DELETE]),
            ChatPendingAction.status.in_(["pending_disambiguation", "pending_confirmation"]),
        )
        .order_by(desc(ChatPendingAction.updated_at), desc(ChatPendingAction.created_at))
    ).scalar_one_or_none()


def run_contacts_subgraph(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
) -> dict:
    action = maybe_handle_contacts_chat_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        provider_id_override=provider_id_override,
    )
    if not action or not action.handled:
        return {"intent_handled": False}

    response: dict = {
        "intent_handled": True,
        "answer": action.answer,
        "provider_id": "contacts-action",
        "provider_name": "Contacts Action Engine",
        "model_name": "contacts-action",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "citations": [],
        "interaction_type": "execution_result",
        "action_context": {"action_type": "contacts"},
        "options": [],
    }

    pending = _latest_pending_contacts_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if not pending:
        return response

    response["pending_action_id"] = pending.id
    response["pending_action_status"] = pending.status
    response["action_context"] = {
        "action_type": pending.action_type,
        "status": pending.status,
        "account_id": pending.account_id,
        "pending_action_id": pending.id,
    }

    if pending.status == "pending_confirmation":
        response["interaction_type"] = "confirmation_required"
        response["options"] = [
            {"id": "yes", "label": "Confirm"},
            {"id": "no", "label": "Cancel"},
        ]
        return response

    if pending.status == "pending_disambiguation":
        response["interaction_type"] = "selection_required"
        options: list[dict[str, str]] = []
        for idx, candidate in enumerate(pending.candidates_json or [], start=1):
            label = str(candidate.get("display_name") or "Unnamed")
            email = str(candidate.get("primary_email") or "").strip()
            if email:
                label = f"{label} ({email})"
            options.append({"id": str(idx), "label": label})
        response["options"] = options

    return response
