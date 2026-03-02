from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TypedDict

from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.models.agent_definition import AgentDefinition
from app.models.agent_run import AgentRun
from app.models.agent_trace_step import AgentTraceStep
from app.models.tool_approval import ToolApproval
from app.services.acl import is_allowed_for_resource
from app.services.chat_runtime import analyze_user_prompt
from app.services.document_indexing import hybrid_search_chunks

try:  # pragma: no cover - optional dependency
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    LANGGRAPH_AVAILABLE = False


ADMIN_ROLES = {"owner", "admin", "manager"}
ROUTED_AGENT_TYPES = {"knowledge", "comms", "ops", "sql", "guard"}
RISKY_TOOLS = {"send_email", "post_slack_message", "run_script", "create_ticket"}

DEFAULT_TOOLS_BY_AGENT = {
    "knowledge": ["search_knowledge"],
    "comms": ["send_email", "post_slack_message"],
    "ops": ["create_ticket", "run_script"],
    "sql": ["query_sql"],
    "guard": [],
}


class RouterState(TypedDict, total=False):
    text: str
    routed_agent: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_admin_role(role: str) -> bool:
    return role.lower() in ADMIN_ROLES


def serialize_agent(agent: AgentDefinition) -> dict[str, Any]:
    return {
        "id": agent.id,
        "tenant_id": agent.tenant_id,
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "default_agent_type": agent.default_agent_type,
        "allowed_tools": list(agent.allowed_tools_json or []),
        "enabled": agent.enabled,
        "config_json": dict(agent.config_json or {}),
        "created_by_user_id": agent.created_by_user_id,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }


def serialize_run(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "agent_id": run.agent_id,
        "initiated_by_user_id": run.initiated_by_user_id,
        "status": run.status,
        "input_text": run.input_text,
        "output_text": run.output_text,
        "routed_agent": run.routed_agent,
        "error_message": run.error_message,
        "metadata_json": dict(run.metadata_json or {}),
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def serialize_trace(trace: AgentTraceStep) -> dict[str, Any]:
    return {
        "id": trace.id,
        "step_order": trace.step_order,
        "agent_name": trace.agent_name,
        "step_type": trace.step_type,
        "tool_name": trace.tool_name,
        "input_json": dict(trace.input_json or {}),
        "output_json": dict(trace.output_json or {}),
        "reasoning_redacted": trace.reasoning_redacted,
        "status": trace.status,
        "created_at": trace.created_at,
    }


def serialize_approval(approval: ToolApproval) -> dict[str, Any]:
    return {
        "id": approval.id,
        "run_id": approval.run_id,
        "tool_name": approval.tool_name,
        "requested_by_user_id": approval.requested_by_user_id,
        "approved_by_user_id": approval.approved_by_user_id,
        "status": approval.status,
        "request_payload_json": dict(approval.request_payload_json or {}),
        "decision_note": approval.decision_note,
        "created_at": approval.created_at,
        "decided_at": approval.decided_at,
    }


def list_agent_definitions(db: Session, *, tenant_id: str) -> list[AgentDefinition]:
    return (
        db.execute(
            select(AgentDefinition)
            .where(AgentDefinition.tenant_id == tenant_id)
            .order_by(AgentDefinition.created_at.desc())
        )
        .scalars()
        .all()
    )


def get_agent_definition(db: Session, *, tenant_id: str, agent_id: str) -> AgentDefinition | None:
    return db.execute(
        select(AgentDefinition).where(
            AgentDefinition.id == agent_id,
            AgentDefinition.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()


def create_agent_definition(
    db: Session,
    *,
    tenant_id: str,
    created_by_user_id: str,
    name: str,
    description: str | None,
    system_prompt: str,
    default_agent_type: str,
    allowed_tools: list[str],
    enabled: bool,
    config_json: dict[str, Any],
) -> AgentDefinition:
    if default_agent_type not in ROUTED_AGENT_TYPES:
        raise ValueError("Invalid default_agent_type")

    agent = AgentDefinition(
        tenant_id=tenant_id,
        name=name,
        description=description,
        system_prompt=system_prompt,
        default_agent_type=default_agent_type,
        allowed_tools_json=allowed_tools,
        enabled=enabled,
        config_json=config_json,
        created_by_user_id=created_by_user_id,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def update_agent_definition(
    db: Session,
    *,
    tenant_id: str,
    agent_id: str,
    updates: dict[str, Any],
) -> AgentDefinition:
    agent = get_agent_definition(db, tenant_id=tenant_id, agent_id=agent_id)
    if not agent:
        raise ValueError("Agent not found")

    if "default_agent_type" in updates and updates["default_agent_type"] not in ROUTED_AGENT_TYPES:
        raise ValueError("Invalid default_agent_type")

    for key, value in updates.items():
        if key == "allowed_tools":
            agent.allowed_tools_json = list(value)
            continue
        setattr(agent, key, value)

    db.commit()
    db.refresh(agent)
    return agent


def delete_agent_definition(db: Session, *, tenant_id: str, agent_id: str) -> None:
    agent = get_agent_definition(db, tenant_id=tenant_id, agent_id=agent_id)
    if not agent:
        raise ValueError("Agent not found")
    db.delete(agent)
    db.commit()


def _next_trace_order(db: Session, *, run_id: str) -> int:
    count = db.execute(
        select(func.count(AgentTraceStep.id)).where(AgentTraceStep.run_id == run_id)
    ).scalar_one()
    return int(count) + 1


def _add_trace(
    db: Session,
    *,
    tenant_id: str,
    run_id: str,
    agent_name: str,
    step_type: str,
    status: str,
    tool_name: str | None = None,
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    reasoning_redacted: str | None = None,
) -> AgentTraceStep:
    trace = AgentTraceStep(
        tenant_id=tenant_id,
        run_id=run_id,
        step_order=_next_trace_order(db, run_id=run_id),
        agent_name=agent_name,
        step_type=step_type,
        tool_name=tool_name,
        input_json=input_json or {},
        output_json=output_json or {},
        reasoning_redacted=reasoning_redacted,
        status=status,
    )
    db.add(trace)
    db.commit()
    db.refresh(trace)
    return trace


def _route_fallback(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ["select ", "sql", "query", "database", "table"]):
        return "sql"
    if any(word in lowered for word in ["email", "slack", "notify", "message", "announcement"]):
        return "comms"
    if any(word in lowered for word in ["incident", "ticket", "deploy", "ops", "restart", "runbook", "script"]):
        return "ops"
    return "knowledge"


def _route_with_langgraph(text: str) -> str:
    if not LANGGRAPH_AVAILABLE:
        return _route_fallback(text)

    try:  # pragma: no cover - depends on optional package
        graph = StateGraph(RouterState)

        def router_node(state: RouterState) -> RouterState:
            routed = _route_fallback(state.get("text", ""))
            return {"routed_agent": routed}

        graph.add_node("router", router_node)
        graph.set_entry_point("router")
        graph.add_edge("router", END)

        workflow = graph.compile()
        result = workflow.invoke({"text": text})
        routed = str(result.get("routed_agent", "knowledge"))
        return routed if routed in ROUTED_AGENT_TYPES else "knowledge"
    except Exception:
        return _route_fallback(text)


def _pick_tools(agent: AgentDefinition, routed_agent: str, text: str) -> list[str]:
    allowed = list(agent.allowed_tools_json or [])
    if not allowed:
        allowed = list(DEFAULT_TOOLS_BY_AGENT.get(routed_agent, []))

    lowered = text.lower()
    if routed_agent == "comms":
        preferred = "post_slack_message" if "slack" in lowered else "send_email"
        if preferred in allowed:
            return [preferred]

    if routed_agent == "ops":
        preferred = "run_script" if any(token in lowered for token in ["script", "restart", "shell"]) else "create_ticket"
        if preferred in allowed:
            return [preferred]

    if routed_agent == "sql" and "query_sql" in allowed:
        return ["query_sql"]

    if routed_agent == "knowledge" and "search_knowledge" in allowed:
        return ["search_knowledge"]

    return allowed[:1]


def _tool_requires_approval(agent: AgentDefinition, tool_name: str) -> bool:
    config = agent.config_json or {}
    if config.get("require_approval_for_risky_tools", True) is False:
        return False

    configured = set(config.get("approval_required_tools", []))
    if configured:
        return tool_name in configured
    return tool_name in RISKY_TOOLS


def _validate_tool_payload(tool_name: str, payload: dict[str, Any]) -> None:
    required: dict[str, list[str]] = {
        "send_email": ["to", "subject", "body"],
        "post_slack_message": ["channel", "text"],
        "create_ticket": ["title", "description"],
        "run_script": ["script_name"],
        "query_sql": ["query"],
    }
    req = required.get(tool_name, [])
    missing = [field for field in req if not payload.get(field)]
    if missing:
        raise ValueError(f"Missing tool payload fields: {', '.join(missing)}")


def _execute_tool(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    tool_name: str,
    input_text: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if tool_name == "search_knowledge":
        query = str(payload.get("query") or input_text).strip()
        limit = int(payload.get("limit", 5))
        hits = hybrid_search_chunks(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            query=query,
            limit=max(1, min(limit, 10)),
        )
        results = []
        for hit in hits:
            meta = hit.chunk.metadata_json or {}
            results.append(
                {
                    "document_id": hit.chunk.document_id,
                    "chunk_id": hit.chunk.id,
                    "title": meta.get("title"),
                    "url": meta.get("url"),
                    "source_type": meta.get("source_type"),
                    "snippet": hit.chunk.content[:320],
                    "score": round(float(hit.score), 6),
                }
            )
        return {"query": query, "results": results, "result_count": len(results)}

    if tool_name == "send_email":
        _validate_tool_payload(tool_name, payload)
        return {
            "status": "queued",
            "message_id": f"mail-{uuid.uuid4()}",
            "to": payload["to"],
            "subject": payload["subject"],
        }

    if tool_name == "post_slack_message":
        _validate_tool_payload(tool_name, payload)
        return {
            "status": "queued",
            "event_id": f"slack-{uuid.uuid4()}",
            "channel": payload["channel"],
            "text": payload["text"],
        }

    if tool_name == "create_ticket":
        _validate_tool_payload(tool_name, payload)
        return {
            "status": "created",
            "ticket_id": f"TKT-{str(uuid.uuid4())[:8].upper()}",
            "title": payload["title"],
        }

    if tool_name == "run_script":
        _validate_tool_payload(tool_name, payload)
        args = payload.get("args", [])
        return {
            "status": "queued_for_approval",
            "script_name": payload["script_name"],
            "args": args if isinstance(args, list) else [],
        }

    if tool_name == "query_sql":
        _validate_tool_payload(tool_name, payload)
        query = str(payload["query"]).strip()
        lowered = query.lower()
        if not lowered.startswith("select"):
            raise ValueError("Only SELECT queries are allowed")
        if ";" in query.rstrip(";"):
            raise ValueError("Multiple SQL statements are not allowed")

        rows = db.execute(sql_text(query)).mappings().fetchmany(50)
        serialized_rows = [dict(row) for row in rows]
        return {"status": "ok", "row_count": len(serialized_rows), "rows": serialized_rows}

    raise ValueError(f"Unsupported tool: {tool_name}")


def _compose_run_output(
    *,
    routed_agent: str,
    input_text: str,
    tool_name: str | None,
    tool_result: dict[str, Any] | None,
) -> str:
    if routed_agent == "guard":
        return "Request blocked by guard policy due to potential exfiltration or instruction hijacking."

    if not tool_name:
        return f"Routed to {routed_agent} agent with no tool invocation. Input accepted: {input_text[:320]}"

    if tool_name == "search_knowledge":
        snippets = tool_result.get("results", []) if tool_result else []
        if not snippets:
            return "No relevant knowledge documents were found for this request."
        top = snippets[0]
        return f"Found {len(snippets)} relevant chunks. Top source: {top.get('title') or 'Untitled'}"

    if tool_name in {"send_email", "post_slack_message", "create_ticket", "run_script", "query_sql"}:
        return f"Tool {tool_name} executed successfully via {routed_agent} agent."

    return f"Agent run completed through {routed_agent}."


def _check_tool_acl(db: Session, *, tenant_id: str, user_id: str, tool_name: str) -> bool:
    return is_allowed_for_resource(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        policy_type="tool",
        resource_id=tool_name,
        allow_wildcard=True,
        default_allow_if_no_policy=False,
    )


def _create_pending_approval(
    db: Session,
    *,
    tenant_id: str,
    run: AgentRun,
    user_id: str,
    tool_name: str,
    payload: dict[str, Any],
) -> ToolApproval:
    existing = db.execute(
        select(ToolApproval).where(
            ToolApproval.tenant_id == tenant_id,
            ToolApproval.run_id == run.id,
            ToolApproval.tool_name == tool_name,
            ToolApproval.status == "pending",
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    approval = ToolApproval(
        tenant_id=tenant_id,
        run_id=run.id,
        tool_name=tool_name,
        requested_by_user_id=user_id,
        status="pending",
        request_payload_json=payload,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def run_agent(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    input_text: str,
    tool_inputs: dict[str, dict[str, Any]],
    metadata_json: dict[str, Any],
) -> AgentRun:
    agent = get_agent_definition(db, tenant_id=tenant_id, agent_id=agent_id)
    if not agent:
        raise ValueError("Agent not found")
    if not agent.enabled:
        raise ValueError("Agent is disabled")

    run = AgentRun(
        tenant_id=tenant_id,
        agent_id=agent.id,
        initiated_by_user_id=user_id,
        status="running",
        input_text=input_text,
        metadata_json=dict(metadata_json or {}),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    safety = analyze_user_prompt(input_text)
    routed_agent = "guard" if safety.blocked else _route_with_langgraph(input_text)
    orchestrator = "langgraph" if LANGGRAPH_AVAILABLE else "builtin"

    run.routed_agent = routed_agent
    run.metadata_json = {
        **(run.metadata_json or {}),
        "orchestrator": orchestrator,
        "safety_flags": list(safety.flags),
    }
    db.commit()

    _add_trace(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        agent_name="RouterAgent",
        step_type="route",
        status="completed",
        input_json={"input_text": input_text[:500]},
        output_json={"routed_agent": routed_agent, "safety_flags": safety.flags, "orchestrator": orchestrator},
        reasoning_redacted="Classification-only router decision.",
    )

    if routed_agent == "guard":
        run.status = "completed"
        run.output_text = _compose_run_output(
            routed_agent=routed_agent,
            input_text=input_text,
            tool_name=None,
            tool_result=None,
        )
        run.finished_at = utcnow()
        db.commit()
        return run

    tool_plan = _pick_tools(agent, routed_agent, input_text)
    if not tool_plan:
        run.status = "completed"
        run.output_text = _compose_run_output(
            routed_agent=routed_agent,
            input_text=input_text,
            tool_name=None,
            tool_result=None,
        )
        run.finished_at = utcnow()
        db.commit()
        return run

    tool_name = tool_plan[0]
    payload = dict(tool_inputs.get(tool_name, {}))

    _add_trace(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        agent_name=f"{routed_agent.title()}Agent",
        step_type="tool_call",
        status="running",
        tool_name=tool_name,
        input_json={"payload": payload},
        output_json={},
        reasoning_redacted="Tool selected by router and agent configuration.",
    )

    if not _check_tool_acl(db, tenant_id=tenant_id, user_id=user_id, tool_name=tool_name):
        run.status = "failed"
        run.error_message = f"Tool denied by ACL policy: {tool_name}"
        run.finished_at = utcnow()
        db.commit()

        _add_trace(
            db,
            tenant_id=tenant_id,
            run_id=run.id,
            agent_name=f"{routed_agent.title()}Agent",
            step_type="tool_result",
            status="denied",
            tool_name=tool_name,
            input_json={"payload": payload},
            output_json={"error": run.error_message},
            reasoning_redacted="Execution blocked by tool ACL.",
        )
        return run

    if _tool_requires_approval(agent, tool_name):
        approval = _create_pending_approval(
            db,
            tenant_id=tenant_id,
            run=run,
            user_id=user_id,
            tool_name=tool_name,
            payload=payload,
        )
        run.status = "waiting_approval"
        run.metadata_json = {
            **(run.metadata_json or {}),
            "pending_tool": tool_name,
            "pending_approval_id": approval.id,
        }
        db.commit()

        _add_trace(
            db,
            tenant_id=tenant_id,
            run_id=run.id,
            agent_name=f"{routed_agent.title()}Agent",
            step_type="tool_result",
            status="waiting_approval",
            tool_name=tool_name,
            input_json={"payload": payload},
            output_json={"approval_id": approval.id, "status": approval.status},
            reasoning_redacted="Risky tool requires explicit approval.",
        )
        return run

    tool_result = _execute_tool(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        tool_name=tool_name,
        input_text=input_text,
        payload=payload,
    )

    _add_trace(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        agent_name=f"{routed_agent.title()}Agent",
        step_type="tool_result",
        status="completed",
        tool_name=tool_name,
        input_json={"payload": payload},
        output_json=tool_result,
        reasoning_redacted="Tool execution completed.",
    )

    run.status = "completed"
    run.output_text = _compose_run_output(
        routed_agent=routed_agent,
        input_text=input_text,
        tool_name=tool_name,
        tool_result=tool_result,
    )
    run.metadata_json = {
        **(run.metadata_json or {}),
        "tool_name": tool_name,
        "tool_result": tool_result,
    }
    run.finished_at = utcnow()
    db.commit()
    db.refresh(run)
    return run


def _assert_run_visibility(run: AgentRun, *, user_id: str, user_role: str) -> None:
    if run.initiated_by_user_id == user_id:
        return
    if is_admin_role(user_role):
        return
    raise ValueError("Run not found")


def list_agent_runs(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    user_role: str,
    limit: int,
) -> list[AgentRun]:
    stmt = select(AgentRun).where(AgentRun.tenant_id == tenant_id).order_by(AgentRun.started_at.desc()).limit(limit)
    runs = db.execute(stmt).scalars().all()
    if is_admin_role(user_role):
        return runs
    return [run for run in runs if run.initiated_by_user_id == user_id]


def get_agent_run_detail(
    db: Session,
    *,
    tenant_id: str,
    run_id: str,
    user_id: str,
    user_role: str,
) -> tuple[AgentRun, list[AgentTraceStep], list[ToolApproval]]:
    run = db.execute(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not run:
        raise ValueError("Run not found")

    _assert_run_visibility(run, user_id=user_id, user_role=user_role)

    traces = (
        db.execute(
            select(AgentTraceStep)
            .where(AgentTraceStep.tenant_id == tenant_id, AgentTraceStep.run_id == run.id)
            .order_by(AgentTraceStep.step_order.asc())
        )
        .scalars()
        .all()
    )
    approvals = (
        db.execute(
            select(ToolApproval)
            .where(ToolApproval.tenant_id == tenant_id, ToolApproval.run_id == run.id)
            .order_by(ToolApproval.created_at.asc())
        )
        .scalars()
        .all()
    )
    return run, traces, approvals


def list_tool_approvals(db: Session, *, tenant_id: str, status: str | None = None, limit: int = 50) -> list[ToolApproval]:
    stmt = select(ToolApproval).where(ToolApproval.tenant_id == tenant_id).order_by(ToolApproval.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(ToolApproval.status == status)
    return db.execute(stmt).scalars().all()


def _finalize_run_for_approval(
    db: Session,
    *,
    run: AgentRun,
    approval: ToolApproval,
) -> AgentRun:
    agent = db.execute(
        select(AgentDefinition).where(AgentDefinition.id == run.agent_id, AgentDefinition.tenant_id == run.tenant_id)
    ).scalar_one_or_none()
    if not agent:
        run.status = "failed"
        run.error_message = "Agent definition no longer exists"
        run.finished_at = utcnow()
        db.commit()
        return run

    tool_name = approval.tool_name
    payload = dict(approval.request_payload_json or {})

    if not _check_tool_acl(db, tenant_id=run.tenant_id, user_id=run.initiated_by_user_id or "", tool_name=tool_name):
        run.status = "failed"
        run.error_message = f"Tool denied by ACL policy: {tool_name}"
        run.finished_at = utcnow()
        db.commit()
        return run

    try:
        tool_result = _execute_tool(
            db,
            tenant_id=run.tenant_id,
            user_id=run.initiated_by_user_id or "",
            tool_name=tool_name,
            input_text=run.input_text,
            payload=payload,
        )
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = utcnow()
        db.commit()

        _add_trace(
            db,
            tenant_id=run.tenant_id,
            run_id=run.id,
            agent_name=f"{(run.routed_agent or 'agent').title()}Agent",
            step_type="tool_result",
            status="failed",
            tool_name=tool_name,
            input_json={"payload": payload},
            output_json={"error": str(exc)},
            reasoning_redacted="Approved tool failed during execution.",
        )
        return run

    _add_trace(
        db,
        tenant_id=run.tenant_id,
        run_id=run.id,
        agent_name=f"{(run.routed_agent or 'agent').title()}Agent",
        step_type="tool_result",
        status="completed",
        tool_name=tool_name,
        input_json={"payload": payload},
        output_json=tool_result,
        reasoning_redacted="Approved tool executed successfully.",
    )

    run.status = "completed"
    run.output_text = _compose_run_output(
        routed_agent=run.routed_agent or "knowledge",
        input_text=run.input_text,
        tool_name=tool_name,
        tool_result=tool_result,
    )
    run.metadata_json = {
        **(run.metadata_json or {}),
        "tool_name": tool_name,
        "tool_result": tool_result,
    }
    run.finished_at = utcnow()
    db.commit()
    db.refresh(run)
    return run


def decide_tool_approval(
    db: Session,
    *,
    tenant_id: str,
    approval_id: str,
    approver_user_id: str,
    decision: str,
    note: str | None,
) -> tuple[ToolApproval, AgentRun]:
    if decision not in {"approved", "rejected"}:
        raise ValueError("Invalid decision")

    approval = db.execute(
        select(ToolApproval).where(
            ToolApproval.id == approval_id,
            ToolApproval.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if not approval:
        raise ValueError("Approval not found")
    if approval.status != "pending":
        raise ValueError("Approval already decided")

    run = db.execute(
        select(AgentRun).where(
            AgentRun.id == approval.run_id,
            AgentRun.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if not run:
        raise ValueError("Run not found")

    approval.status = decision
    approval.approved_by_user_id = approver_user_id
    approval.decision_note = note
    approval.decided_at = utcnow()
    db.commit()

    if decision == "rejected":
        run.status = "failed"
        run.error_message = f"Approval rejected for tool: {approval.tool_name}"
        run.output_text = None
        run.finished_at = utcnow()
        db.commit()

        _add_trace(
            db,
            tenant_id=tenant_id,
            run_id=run.id,
            agent_name=f"{(run.routed_agent or 'agent').title()}Agent",
            step_type="approval",
            status="rejected",
            tool_name=approval.tool_name,
            input_json={"approval_id": approval.id},
            output_json={"decision": "rejected", "note": note},
            reasoning_redacted="Human approver rejected risky action.",
        )
        return approval, run

    _add_trace(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        agent_name=f"{(run.routed_agent or 'agent').title()}Agent",
        step_type="approval",
        status="approved",
        tool_name=approval.tool_name,
        input_json={"approval_id": approval.id},
        output_json={"decision": "approved", "note": note},
        reasoning_redacted="Human approver accepted risky action.",
    )

    run = _finalize_run_for_approval(db, run=run, approval=approval)
    return approval, run
