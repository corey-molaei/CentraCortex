from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat_message import ChatMessage
from app.models.chat_pending_action import ChatPendingAction
from app.models.chat_pending_email_action import ChatPendingEmailAction
from app.services.chat_calendar_actions import (
    CREATE_ACTION as CALENDAR_CREATE_ACTION,
)
from app.services.chat_calendar_actions import (
    DELETE_ACTION as CALENDAR_DELETE_ACTION,
)
from app.services.chat_calendar_actions import (
    PENDING_CONFIRMATION as CALENDAR_PENDING_CONFIRMATION,
)
from app.services.chat_calendar_actions import (
    PENDING_DISAMBIGUATION as CALENDAR_PENDING_DISAMBIGUATION,
)
from app.services.chat_calendar_actions import (
    UPDATE_ACTION as CALENDAR_UPDATE_ACTION,
)
from app.services.chat_calendar_actions import maybe_handle_calendar_chat_action
from app.services.chat_contacts_actions import (
    INTENT_CREATE as CONTACTS_CREATE_ACTION,
)
from app.services.chat_contacts_actions import (
    INTENT_DELETE as CONTACTS_DELETE_ACTION,
)
from app.services.chat_contacts_actions import (
    INTENT_UPDATE as CONTACTS_UPDATE_ACTION,
)
from app.services.chat_contacts_actions import maybe_handle_contacts_chat_action
from app.services.chat_email_actions import maybe_handle_email_chat_action
from app.services.connectors.google_service import (
    get_primary_account,
    list_user_accounts,
    search_contacts,
)
from app.services.llm_router import LLMRouter

logger = structlog.get_logger(__name__)

ALLOWED_TOOL_NAMES = {
    "contacts.search",
    "contacts.read",
    "contacts.list",
    "contacts.create",
    "contacts.update",
    "contacts.delete",
    "email.send_draft",
    "email.read",
    "email.list",
    "calendar.create",
    "calendar.update",
    "calendar.delete",
    "calendar.list",
}

CONTACT_EMAIL_PICK_ACTION = "tool_contact_email_pick"

EMAIL_PATTERN = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", re.IGNORECASE)
CONTACT_READ_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
CONTACT_WRITE_SCOPE = "https://www.googleapis.com/auth/contacts"

TOOL_PARSE_CLARIFICATION = (
    "I couldn't confidently map this request to a safe tool action. "
    "Please rephrase with the action and target, for example: "
    "'find contact Maryam Asadi' or 'send email to maryam@example.com body: ...'."
)


@dataclass
class ToolStep:
    tool: str
    args: dict[str, Any]


@dataclass
class ToolPlan:
    steps: list[ToolStep]
    needs_confirmation: bool | None = None
    confidence: float | None = None
    reason: str | None = None


@dataclass
class V1ToolDispatchResult:
    handled: bool
    answer: str
    provider_id: str | None = None
    provider_name: str | None = None
    model_name: str | None = None


def _planner_clarification_result(answer: str = TOOL_PARSE_CLARIFICATION) -> V1ToolDispatchResult:
    return V1ToolDispatchResult(
        handled=True,
        answer=answer,
        provider_id="tool-planner",
        provider_name="Tool Planner",
        model_name="tool-planner",
    )


def dispatch_tool_plan_v1(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
    client_timezone: str | None,
    client_now_iso: str | None,
) -> V1ToolDispatchResult | None:
    pending_result = _handle_special_pending_contact_pick_v1(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
    )
    if pending_result is not None:
        return pending_result

    if _has_pending_native_action(db, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id):
        handler_kwargs = {
            "db": db,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message": message,
            "client_timezone": client_timezone,
            "client_now_iso": client_now_iso,
            "provider_id_override": provider_id_override,
        }
        for handler_name, handler in _v1_handler_sequence():
            result = handler(**handler_kwargs)
            if result and result.handled:
                return _v1_result_from_handler(handler_name, result.answer)

    parse_started = time.perf_counter()
    parsed, parse_error = _parse_tool_plan_llm(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        provider_id_override=provider_id_override,
    )
    parse_ms = int((time.perf_counter() - parse_started) * 1000)

    if parse_error or parsed is None:
        logger.debug(
            "tool_parse_clarification_returned",
            tenant_id=tenant_id,
            user_id=user_id,
            parse_ms=parse_ms,
        )
        return V1ToolDispatchResult(
            handled=True,
            answer=TOOL_PARSE_CLARIFICATION,
            provider_id="tool-planner",
            provider_name="Tool Planner",
            model_name="tool-planner",
        )

    logger.debug(
        "tool_plan_parsed",
        tenant_id=tenant_id,
        user_id=user_id,
        parse_ms=parse_ms,
        confidence=parsed.confidence,
        reason=parsed.reason,
        steps=[{"tool": step.tool, "args": step.args} for step in parsed.steps],
    )

    validated = _validate_tool_plan(parsed)
    if validated is None:
        logger.debug("tool_plan_validation_failed", tenant_id=tenant_id, user_id=user_id)
        return V1ToolDispatchResult(
            handled=True,
            answer=TOOL_PARSE_CLARIFICATION,
            provider_id="tool-planner",
            provider_name="Tool Planner",
            model_name="tool-planner",
        )

    if not validated.steps:
        return None

    two_step = _maybe_execute_contact_search_then_send_v1(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
        plan=validated,
    )
    if two_step is not None:
        return two_step

    step = validated.steps[0]
    return _execute_single_step_v1(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
        step=step,
    )


def dispatch_tool_plan_v2(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
    client_timezone: str | None,
    client_now_iso: str | None,
) -> dict:
    pending_result = _handle_special_pending_contact_pick_v2(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
    )
    if pending_result is not None:
        return pending_result

    parse_started = time.perf_counter()
    parsed, parse_error = _parse_tool_plan_llm(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        provider_id_override=provider_id_override,
    )
    parse_ms = int((time.perf_counter() - parse_started) * 1000)

    if parse_error or parsed is None:
        logger.debug(
            "tool_parse_clarification_returned",
            tenant_id=tenant_id,
            user_id=user_id,
            parse_ms=parse_ms,
        )
        return _v2_text_result(answer=TOOL_PARSE_CLARIFICATION, interaction_type="execution_result")

    logger.debug(
        "tool_plan_parsed",
        tenant_id=tenant_id,
        user_id=user_id,
        parse_ms=parse_ms,
        confidence=parsed.confidence,
        reason=parsed.reason,
        steps=[{"tool": step.tool, "args": step.args} for step in parsed.steps],
    )

    validated = _validate_tool_plan(parsed)
    if validated is None:
        logger.debug("tool_plan_validation_failed", tenant_id=tenant_id, user_id=user_id)
        return _v2_text_result(answer=TOOL_PARSE_CLARIFICATION, interaction_type="execution_result")

    if not validated.steps:
        return {"intent_handled": False}

    two_step = _maybe_execute_contact_search_then_send_v2(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
        plan=validated,
    )
    if two_step is not None:
        return two_step

    step = validated.steps[0]
    return _execute_single_step_v2(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
        step=step,
    )


def _v1_handler_sequence():
    return (
        (
            "calendar-action",
            lambda **kwargs: maybe_handle_calendar_chat_action(
                db=kwargs["db"],
                tenant_id=kwargs["tenant_id"],
                user_id=kwargs["user_id"],
                conversation_id=kwargs["conversation_id"],
                message=kwargs["message"],
                client_timezone=kwargs.get("client_timezone"),
                client_now_iso=kwargs.get("client_now_iso"),
                provider_id_override=kwargs.get("provider_id_override"),
            ),
        ),
        (
            "contacts-action",
            lambda **kwargs: maybe_handle_contacts_chat_action(
                db=kwargs["db"],
                tenant_id=kwargs["tenant_id"],
                user_id=kwargs["user_id"],
                conversation_id=kwargs["conversation_id"],
                message=kwargs["message"],
                provider_id_override=kwargs.get("provider_id_override"),
            ),
        ),
        (
            "email-action",
            lambda **kwargs: maybe_handle_email_chat_action(
                db=kwargs["db"],
                tenant_id=kwargs["tenant_id"],
                user_id=kwargs["user_id"],
                conversation_id=kwargs["conversation_id"],
                message=kwargs["message"],
                client_timezone=kwargs.get("client_timezone"),
                client_now_iso=kwargs.get("client_now_iso"),
                provider_id_override=kwargs.get("provider_id_override"),
            ),
        ),
    )


def _v1_result_from_handler(handler_name: str, answer: str) -> V1ToolDispatchResult:
    name_to_provider = {
        "calendar-action": ("google-calendar-action", "Calendar Action Engine", "google-calendar-action"),
        "contacts-action": ("contacts-action", "Contacts Action Engine", "contacts-action"),
        "email-action": ("email-action", "Email Action Engine", "email-action"),
    }
    provider_id, provider_name, model_name = name_to_provider[handler_name]
    return V1ToolDispatchResult(
        handled=True,
        answer=answer,
        provider_id=provider_id,
        provider_name=provider_name,
        model_name=model_name,
    )


def _has_pending_native_action(db: Session, *, tenant_id: str, user_id: str, conversation_id: str) -> bool:
    pending_calendar = db.execute(
        select(ChatPendingAction.id)
        .where(
            ChatPendingAction.tenant_id == tenant_id,
            ChatPendingAction.user_id == user_id,
            ChatPendingAction.conversation_id == conversation_id,
            ChatPendingAction.action_type.in_([CALENDAR_CREATE_ACTION, CALENDAR_UPDATE_ACTION, CALENDAR_DELETE_ACTION]),
            ChatPendingAction.status.in_([CALENDAR_PENDING_CONFIRMATION, CALENDAR_PENDING_DISAMBIGUATION]),
        )
        .limit(1)
    ).scalar_one_or_none()
    if pending_calendar:
        return True

    pending_contacts = db.execute(
        select(ChatPendingAction.id)
        .where(
            ChatPendingAction.tenant_id == tenant_id,
            ChatPendingAction.user_id == user_id,
            ChatPendingAction.conversation_id == conversation_id,
            ChatPendingAction.action_type.in_([CONTACTS_CREATE_ACTION, CONTACTS_UPDATE_ACTION, CONTACTS_DELETE_ACTION]),
            ChatPendingAction.status.in_([CALENDAR_PENDING_CONFIRMATION, CALENDAR_PENDING_DISAMBIGUATION]),
        )
        .limit(1)
    ).scalar_one_or_none()
    if pending_contacts:
        return True

    pending_email = db.execute(
        select(ChatPendingEmailAction.id)
        .where(
            ChatPendingEmailAction.tenant_id == tenant_id,
            ChatPendingEmailAction.user_id == user_id,
            ChatPendingEmailAction.conversation_id == conversation_id,
            ChatPendingEmailAction.status == "pending_confirmation",
        )
        .limit(1)
    ).scalar_one_or_none()
    return bool(pending_email)


def _parse_tool_plan_llm(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
) -> tuple[ToolPlan | None, bool]:
    history = _recent_history(db, conversation_id=conversation_id, limit=4)
    capability = _capability_context(db, tenant_id=tenant_id, user_id=user_id)
    pending = _pending_context(db, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id)

    prompt = (
        "You are a strict JSON tool planner for chat actions.\n"
        "Return JSON only with keys: tool_plan, needs_confirmation, confidence, reason.\n"
        "tool_plan must be either \"none\" or a list (max 2) of objects with keys: tool, args.\n"
        "Allowed tool values: contacts.search, contacts.read, contacts.list, contacts.create, contacts.update, contacts.delete, "
        "email.send_draft, email.read, email.list, "
        "calendar.create, calendar.update, calendar.delete, calendar.list.\n"
        "Rules:\n"
        "- Never invent emails, contact ids, message ids, or event ids.\n"
        "- For send-email with a person name but no explicit email, use two steps: contacts.search then email.send_draft.\n"
        "- For \"email of person\" questions, prefer contacts.read or contacts.search, not email.read.\n"
        "- If request is not a tool action, return tool_plan=\"none\".\n"
        "- Keep args minimal and deterministic.\n"
        f"Capability context: {json.dumps(capability, ensure_ascii=True)}\n"
        f"Pending context: {json.dumps(pending, ensure_ascii=True)}\n"
        f"Recent history: {json.dumps(history, ensure_ascii=True)}\n"
        f"User message: {message}"
    )

    try:
        _, result = LLMRouter(db, tenant_id).chat(
            messages=[
                {"role": "system", "content": "You output strict JSON for tool planning."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            provider_id_override=provider_id_override,
            allow_fallback=False,
        )
    except Exception:
        return None, True

    payload = _parse_json_object(str(result.get("answer") or ""))
    if not isinstance(payload, dict):
        return None, True

    raw_tool_plan = payload.get("tool_plan")
    if isinstance(raw_tool_plan, str) and raw_tool_plan.strip().lower() in {"none", "null", ""}:
        return (
            ToolPlan(
                steps=[],
                needs_confirmation=_coerce_bool(payload.get("needs_confirmation")),
                confidence=_coerce_float(payload.get("confidence")),
                reason=_as_text(payload.get("reason")),
            ),
            False,
        )
    if not isinstance(raw_tool_plan, list):
        return None, True

    steps: list[ToolStep] = []
    for item in raw_tool_plan[:2]:
        if not isinstance(item, dict):
            continue
        tool = _normalize_tool_name(_as_text(item.get("tool")) or "")
        args = item.get("args")
        if tool and isinstance(args, dict):
            steps.append(ToolStep(tool=tool, args=args))
        elif tool:
            steps.append(ToolStep(tool=tool, args={}))

    return ToolPlan(
        steps=steps,
        needs_confirmation=_coerce_bool(payload.get("needs_confirmation")),
        confidence=_coerce_float(payload.get("confidence")),
        reason=_as_text(payload.get("reason")),
    ), False


def _validate_tool_plan(plan: ToolPlan) -> ToolPlan | None:
    steps: list[ToolStep] = []
    for step in plan.steps[:2]:
        if step.tool not in ALLOWED_TOOL_NAMES:
            return None
        steps.append(ToolStep(tool=step.tool, args=dict(step.args)))
    return ToolPlan(
        steps=steps,
        needs_confirmation=plan.needs_confirmation,
        confidence=plan.confidence,
        reason=plan.reason,
    )


def _execute_single_step_v1(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
    client_timezone: str | None,
    client_now_iso: str | None,
    step: ToolStep,
) -> V1ToolDispatchResult:
    tool = step.tool
    synthesized = _synthesize_message_for_step(message=message, step=step)

    if tool.startswith("calendar."):
        result = maybe_handle_calendar_chat_action(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message=synthesized,
            client_timezone=client_timezone,
            client_now_iso=client_now_iso,
            provider_id_override=provider_id_override,
        )
        logger.debug("tool_step_executed", tool=tool, handled=bool(result and result.handled))
        if result and result.handled:
            return _v1_result_from_handler("calendar-action", result.answer)
        return _planner_clarification_result()

    if tool.startswith("contacts."):
        result = maybe_handle_contacts_chat_action(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message=synthesized,
            provider_id_override=provider_id_override,
        )
        logger.debug("tool_step_executed", tool=tool, handled=bool(result and result.handled))
        if result and result.handled:
            return _v1_result_from_handler("contacts-action", result.answer)
        return _planner_clarification_result()

    if tool.startswith("email."):
        result = maybe_handle_email_chat_action(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message=synthesized,
            client_timezone=client_timezone,
            client_now_iso=client_now_iso,
            provider_id_override=provider_id_override,
        )
        logger.debug("tool_step_executed", tool=tool, handled=bool(result and result.handled))
        if result and result.handled:
            return _v1_result_from_handler("email-action", result.answer)
        return _planner_clarification_result()

    return _planner_clarification_result()


def _execute_single_step_v2(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
    client_timezone: str | None,
    client_now_iso: str | None,
    step: ToolStep,
) -> dict:
    tool = step.tool
    synthesized = _synthesize_message_for_step(message=message, step=step)

    if tool.startswith("calendar."):
        from app.services.orchestration.calendar_graph import run_calendar_subgraph

        result = run_calendar_subgraph(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message=synthesized,
            client_timezone=client_timezone,
            client_now_iso=client_now_iso,
            provider_id_override=provider_id_override,
        )
        logger.debug("tool_step_executed", tool=tool, handled=result.get("intent_handled"))
        return result if result.get("intent_handled") else _v2_text_result(TOOL_PARSE_CLARIFICATION, "execution_result")

    if tool.startswith("contacts."):
        from app.services.orchestration.contacts_graph import run_contacts_subgraph

        result = run_contacts_subgraph(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message=synthesized,
            provider_id_override=provider_id_override,
        )
        logger.debug("tool_step_executed", tool=tool, handled=result.get("intent_handled"))
        return result if result.get("intent_handled") else _v2_text_result(TOOL_PARSE_CLARIFICATION, "execution_result")

    if tool.startswith("email."):
        from app.services.orchestration.email_graph import run_email_subgraph

        result = run_email_subgraph(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message=synthesized,
            client_timezone=client_timezone,
            client_now_iso=client_now_iso,
            provider_id_override=provider_id_override,
        )
        logger.debug("tool_step_executed", tool=tool, handled=result.get("intent_handled"))
        return result if result.get("intent_handled") else _v2_text_result(TOOL_PARSE_CLARIFICATION, "execution_result")

    return _v2_text_result(TOOL_PARSE_CLARIFICATION, "execution_result")


def _maybe_execute_contact_search_then_send_v1(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
    client_timezone: str | None,
    client_now_iso: str | None,
    plan: ToolPlan,
) -> V1ToolDispatchResult | None:
    if len(plan.steps) < 2:
        return None
    if plan.steps[0].tool != "contacts.search" or plan.steps[1].tool != "email.send_draft":
        return None

    contact_lookup = _resolve_contact_for_send(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        query=_as_text(plan.steps[0].args.get("query")) or _extract_send_recipient_name(message),
    )
    if contact_lookup["status"] == "error":
        return _planner_clarification_result(str(contact_lookup["answer"]))
    if contact_lookup["status"] == "none":
        return _planner_clarification_result(str(contact_lookup["answer"]))
    if contact_lookup["status"] == "multiple":
        candidates = contact_lookup["candidates"]
        _create_contact_email_pick_pending(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account_id=str(contact_lookup["account_id"]),
            original_message=message,
            candidates=candidates,
        )
        lines = ["I found multiple contacts for that name. Please choose one by number:"]
        for idx, item in enumerate(candidates, start=1):
            lines.append(f"{idx}. {item['display_name']} | {item['email']}")
        return V1ToolDispatchResult(
            handled=True,
            answer="\n".join(lines),
            provider_id="tool-planner",
            provider_name="Tool Planner",
            model_name="tool-planner",
        )

    email_value = str(contact_lookup["email"])
    rewritten = _inject_send_recipient_email(message, email_value, name_hint=contact_lookup.get("name_hint"))
    return _execute_single_step_v1(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=rewritten,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
        step=plan.steps[1],
    )


def _maybe_execute_contact_search_then_send_v2(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
    client_timezone: str | None,
    client_now_iso: str | None,
    plan: ToolPlan,
) -> dict | None:
    if len(plan.steps) < 2:
        return None
    if plan.steps[0].tool != "contacts.search" or plan.steps[1].tool != "email.send_draft":
        return None

    contact_lookup = _resolve_contact_for_send(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        query=_as_text(plan.steps[0].args.get("query")) or _extract_send_recipient_name(message),
    )
    if contact_lookup["status"] in {"error", "none"}:
        return _v2_text_result(answer=str(contact_lookup["answer"]), interaction_type="execution_result")

    if contact_lookup["status"] == "multiple":
        candidates = contact_lookup["candidates"]
        pending = _create_contact_email_pick_pending(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account_id=str(contact_lookup["account_id"]),
            original_message=message,
            candidates=candidates,
        )
        options = []
        for idx, item in enumerate(candidates, start=1):
            options.append({"id": str(idx), "label": f"{item['display_name']} ({item['email']})"})
        return {
            "intent_handled": True,
            "answer": "I found multiple contacts for that name. Please select one.",
            "provider_id": "tool-planner",
            "provider_name": "Tool Planner",
            "model_name": "tool-planner",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "citations": [],
            "interaction_type": "selection_required",
            "action_context": {
                "action_type": CONTACT_EMAIL_PICK_ACTION,
                "status": "pending_disambiguation",
                "pending_action_id": pending.id,
                "account_id": str(contact_lookup["account_id"]),
            },
            "pending_action_id": pending.id,
            "pending_action_status": "pending_disambiguation",
            "options": options,
        }

    email_value = str(contact_lookup["email"])
    rewritten = _inject_send_recipient_email(message, email_value, name_hint=contact_lookup.get("name_hint"))
    return _execute_single_step_v2(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=rewritten,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
        step=plan.steps[1],
    )


def _handle_special_pending_contact_pick_v1(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
    client_timezone: str | None,
    client_now_iso: str | None,
) -> V1ToolDispatchResult | None:
    pending = _get_pending_contact_pick(db, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id)
    if pending is None:
        return None

    lowered = message.strip().lower()
    if lowered in {"no", "n", "cancel", "stop"}:
        pending.status = "cancelled"
        db.commit()
        return V1ToolDispatchResult(
            handled=True,
            answer="Cancelled contact selection.",
            provider_id="tool-planner",
            provider_name="Tool Planner",
            model_name="tool-planner",
        )

    index = _parse_selection_index(message)
    candidates = list(pending.candidates_json or [])
    if index is None or index < 1 or index > len(candidates):
        return V1ToolDispatchResult(
            handled=True,
            answer="Please choose one contact by number (for example: 1).",
            provider_id="tool-planner",
            provider_name="Tool Planner",
            model_name="tool-planner",
        )

    selected = candidates[index - 1]
    original_message = str((pending.payload_json or {}).get("original_message") or "")
    rewritten = _inject_send_recipient_email(original_message, str(selected.get("email") or ""), name_hint=selected.get("display_name"))
    pending.status = "completed"
    db.commit()

    return _execute_single_step_v1(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=rewritten,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
        step=ToolStep(tool="email.send_draft", args={}),
    )


def _handle_special_pending_contact_pick_v2(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None,
    client_timezone: str | None,
    client_now_iso: str | None,
) -> dict | None:
    pending = _get_pending_contact_pick(db, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id)
    if pending is None:
        return None

    lowered = message.strip().lower()
    if lowered in {"no", "n", "cancel", "stop"}:
        pending.status = "cancelled"
        db.commit()
        return _v2_text_result(answer="Cancelled contact selection.", interaction_type="execution_result")

    index = _parse_selection_index(message)
    candidates = list(pending.candidates_json or [])
    if index is None or index < 1 or index > len(candidates):
        options = []
        for idx, item in enumerate(candidates, start=1):
            options.append({"id": str(idx), "label": f"{item.get('display_name') or 'Unknown'} ({item.get('email') or '-'})"})
        return {
            "intent_handled": True,
            "answer": "Please choose one contact by number.",
            "provider_id": "tool-planner",
            "provider_name": "Tool Planner",
            "model_name": "tool-planner",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "citations": [],
            "interaction_type": "selection_required",
            "action_context": {
                "action_type": CONTACT_EMAIL_PICK_ACTION,
                "status": "pending_disambiguation",
                "pending_action_id": pending.id,
                "account_id": pending.account_id,
            },
            "pending_action_id": pending.id,
            "pending_action_status": "pending_disambiguation",
            "options": options,
        }

    selected = candidates[index - 1]
    original_message = str((pending.payload_json or {}).get("original_message") or "")
    rewritten = _inject_send_recipient_email(original_message, str(selected.get("email") or ""), name_hint=selected.get("display_name"))
    pending.status = "completed"
    db.commit()

    return _execute_single_step_v2(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message=rewritten,
        provider_id_override=provider_id_override,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
        step=ToolStep(tool="email.send_draft", args={}),
    )


def _resolve_contact_for_send(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    query: str | None,
) -> dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        return {"status": "none", "answer": "I need the recipient name to look up contacts before sending."}

    accounts = [item for item in list_user_accounts(db, tenant_id=tenant_id, user_id=user_id) if item.enabled]
    if not accounts:
        return {"status": "error", "answer": "No connected Google account found for contact lookup."}

    account = get_primary_account(db, tenant_id=tenant_id, user_id=user_id) or accounts[0]
    if not account.access_token_encrypted:
        return {"status": "error", "answer": "Google account is not connected. Please reconnect in /connectors/google."}
    if not account.contacts_enabled:
        return {"status": "error", "answer": "Contacts capability is disabled. Enable Contacts in /connectors/google."}
    scopes = {str(item).strip() for item in (account.scopes or []) if str(item).strip()}
    if not scopes.intersection({CONTACT_READ_SCOPE, CONTACT_WRITE_SCOPE}):
        return {
            "status": "error",
            "answer": "Contacts read scope is missing. Reconnect in /connectors/google with Contacts enabled.",
        }

    try:
        rows = search_contacts(
            db,
            account,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            query=text,
            limit=8,
        )
    except Exception as exc:
        return {"status": "error", "answer": f"Contacts lookup failed: {exc}"}

    candidates: list[dict[str, str]] = []
    for row in rows:
        email_value = str(row.get("primary_email") or "").strip().lower()
        if not email_value:
            continue
        candidates.append(
            {
                "resource_name": str(row.get("resource_name") or ""),
                "display_name": str(row.get("display_name") or "Unnamed"),
                "email": email_value,
            }
        )

    if not candidates:
        return {
            "status": "none",
            "answer": f"I couldn't find a contact email for '{text}'. Please share the email address.",
        }

    dedup: dict[str, dict[str, str]] = {}
    for item in candidates:
        dedup[item["email"]] = item
    unique = list(dedup.values())
    if len(unique) == 1:
        return {
            "status": "single",
            "email": unique[0]["email"],
            "name_hint": unique[0]["display_name"],
            "account_id": account.id,
        }
    return {
        "status": "multiple",
        "candidates": unique,
        "account_id": account.id,
    }


def _create_contact_email_pick_pending(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account_id: str,
    original_message: str,
    candidates: list[dict[str, Any]],
) -> ChatPendingAction:
    current = _get_pending_contact_pick(db, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id)
    if current is not None:
        current.status = "cancelled"

    pending = ChatPendingAction(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        account_id=account_id,
        action_type=CONTACT_EMAIL_PICK_ACTION,
        status="pending_disambiguation",
        payload_json={"original_message": original_message},
        candidates_json=candidates,
        expires_at=datetime_now_utc_plus(minutes=15),
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)
    return pending


def _get_pending_contact_pick(
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
            ChatPendingAction.action_type == CONTACT_EMAIL_PICK_ACTION,
            ChatPendingAction.status == "pending_disambiguation",
        )
        .order_by(desc(ChatPendingAction.updated_at), desc(ChatPendingAction.created_at))
    ).scalar_one_or_none()


def _synthesize_message_for_step(*, message: str, step: ToolStep) -> str:
    tool = step.tool
    args = step.args

    if tool == "email.read":
        message_id = _as_text(args.get("message_id"))
        if message_id and " id " not in message.lower():
            return f"read email id {message_id}"
    if tool == "contacts.read":
        contact_id = _as_text(args.get("contact_id"))
        query = _as_text(args.get("query"))
        if contact_id:
            return f"read contact {contact_id}"
        if query:
            return f"read contact {query}"
    if tool == "contacts.search":
        query = _as_text(args.get("query"))
        if query:
            return f"find contact {query}"
    return message


def _inject_send_recipient_email(message: str, email_value: str, name_hint: str | None = None) -> str:
    if EMAIL_PATTERN.search(message):
        return message
    text = message.strip()
    name = str(name_hint or "").strip()
    if name:
        pattern = re.compile(rf"\bto\s+{re.escape(name)}\b", flags=re.IGNORECASE)
        replaced = pattern.sub(f"to {email_value}", text)
        if replaced != text:
            return replaced
    to_match = re.search(
        r"\bto\s+(.+?)(?:\s+\b(?:subject|title|body|about|cc|bcc)\b|$)",
        text,
        flags=re.IGNORECASE,
    )
    if to_match:
        recipient_phrase = to_match.group(1).strip()
        if recipient_phrase:
            text = text.replace(f"to {recipient_phrase}", f"to {email_value}", 1)
            return text
    return f"{text} to {email_value}"


def _extract_send_recipient_name(message: str) -> str | None:
    normalized = " ".join(message.split())
    match = re.search(
        r"\bto\s+(.+?)(?:\s+\b(?:subject|title|body|about|cc|bcc)\b|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    candidate = match.group(1).strip(" .,")
    if not candidate or EMAIL_PATTERN.search(candidate):
        return None
    return candidate[:120]


def _pending_context(db: Session, *, tenant_id: str, user_id: str, conversation_id: str) -> dict[str, Any]:
    pending_calendar = db.execute(
        select(ChatPendingAction.action_type, ChatPendingAction.status)
        .where(
            ChatPendingAction.tenant_id == tenant_id,
            ChatPendingAction.user_id == user_id,
            ChatPendingAction.conversation_id == conversation_id,
            ChatPendingAction.action_type.in_([CALENDAR_CREATE_ACTION, CALENDAR_UPDATE_ACTION, CALENDAR_DELETE_ACTION]),
            ChatPendingAction.status.in_([CALENDAR_PENDING_CONFIRMATION, CALENDAR_PENDING_DISAMBIGUATION]),
        )
        .limit(1)
    ).first()
    pending_contacts = db.execute(
        select(ChatPendingAction.action_type, ChatPendingAction.status)
        .where(
            ChatPendingAction.tenant_id == tenant_id,
            ChatPendingAction.user_id == user_id,
            ChatPendingAction.conversation_id == conversation_id,
            ChatPendingAction.action_type.in_([CONTACTS_CREATE_ACTION, CONTACTS_UPDATE_ACTION, CONTACTS_DELETE_ACTION]),
            ChatPendingAction.status.in_([CALENDAR_PENDING_CONFIRMATION, CALENDAR_PENDING_DISAMBIGUATION]),
        )
        .limit(1)
    ).first()
    pending_email = db.execute(
        select(ChatPendingEmailAction.status)
        .where(
            ChatPendingEmailAction.tenant_id == tenant_id,
            ChatPendingEmailAction.user_id == user_id,
            ChatPendingEmailAction.conversation_id == conversation_id,
            ChatPendingEmailAction.status == "pending_confirmation",
        )
        .limit(1)
    ).scalar_one_or_none()
    return {
        "calendar_pending": {"action_type": pending_calendar[0], "status": pending_calendar[1]} if pending_calendar else None,
        "contacts_pending": {"action_type": pending_contacts[0], "status": pending_contacts[1]} if pending_contacts else None,
        "email_pending": {"status": pending_email} if pending_email else None,
    }


def _capability_context(db: Session, *, tenant_id: str, user_id: str) -> dict[str, Any]:
    accounts = list_user_accounts(db, tenant_id=tenant_id, user_id=user_id)
    primary = get_primary_account(db, tenant_id=tenant_id, user_id=user_id)
    account = primary or (accounts[0] if accounts else None)
    if account is None:
        return {"has_google_account": False}
    scopes = {str(item).strip() for item in (account.scopes or []) if str(item).strip()}
    return {
        "has_google_account": True,
        "account_label": account.label or account.google_account_email,
        "enabled": bool(account.enabled),
        "token_connected": bool(account.access_token_encrypted),
        "gmail_enabled": bool(account.gmail_enabled),
        "calendar_enabled": bool(account.calendar_enabled),
        "contacts_enabled": bool(account.contacts_enabled),
        "contacts_read_scope": bool(scopes.intersection({CONTACT_READ_SCOPE, CONTACT_WRITE_SCOPE})),
        "contacts_write_scope": CONTACT_WRITE_SCOPE in scopes,
    }


def _recent_history(db: Session, *, conversation_id: str, limit: int) -> list[dict[str, str]]:
    rows = (
        db.execute(
            select(ChatMessage.role, ChatMessage.content)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        .all()
    )
    history: list[dict[str, str]] = []
    for role, content in reversed(rows):
        history.append({"role": str(role), "content": str(content)[:500]})
    return history


def _normalize_tool_name(value: str) -> str:
    raw = value.strip().lower().replace("-", ".").replace("_", ".")
    aliases = {
        "none": "none",
        "contacts.search": "contacts.search",
        "contacts.find": "contacts.search",
        "contacts.lookup": "contacts.search",
        "contacts.read": "contacts.read",
        "contacts.get": "contacts.read",
        "contacts.list": "contacts.list",
        "contacts.create": "contacts.create",
        "contacts.add": "contacts.create",
        "contacts.update": "contacts.update",
        "contacts.edit": "contacts.update",
        "contacts.delete": "contacts.delete",
        "contacts.remove": "contacts.delete",
        "email.send": "email.send_draft",
        "email.send.draft": "email.send_draft",
        "email.send.drafts": "email.send_draft",
        "email.send_draft": "email.send_draft",
        "email.read": "email.read",
        "email.get": "email.read",
        "email.list": "email.list",
        "calendar.create": "calendar.create",
        "calendar.add": "calendar.create",
        "calendar.update": "calendar.update",
        "calendar.move": "calendar.update",
        "calendar.delete": "calendar.delete",
        "calendar.remove": "calendar.delete",
        "calendar.list": "calendar.list",
    }
    return aliases.get(raw, raw)


def _parse_json_object(value: str) -> dict[str, Any] | None:
    text = value.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None
    try:
        return float(value)
    except Exception:
        return None


def _parse_selection_index(message: str) -> int | None:
    match = re.search(r"\b(\d{1,2})\b", message)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _v2_text_result(answer: str, interaction_type: str) -> dict:
    return {
        "intent_handled": True,
        "answer": answer,
        "provider_id": "tool-planner",
        "provider_name": "Tool Planner",
        "model_name": "tool-planner",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "citations": [],
        "interaction_type": interaction_type,
        "action_context": {"action_type": "tool_planner", "status": "complete"},
        "options": [],
    }


def datetime_now_utc_plus(*, minutes: int) -> Any:
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(minutes=minutes)
