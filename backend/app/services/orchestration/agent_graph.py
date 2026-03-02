from __future__ import annotations

from sqlalchemy.orm import Session


def run_agent_subgraph(
    db: Session,  # noqa: ARG001
    *,
    tenant_id: str,  # noqa: ARG001
    user_id: str,  # noqa: ARG001
    message: str,
) -> dict:
    lowered = message.lower()
    if "run agent" not in lowered and "agent" not in lowered:
        return {"intent_handled": False}

    return {
        "intent_handled": True,
        "answer": (
            "Agent execution is routed through the agent runtime. "
            "Use /agents/run for explicit runs, or ask a knowledge/calendar/email action in chat."
        ),
        "provider_id": "agent-action",
        "provider_name": "Agent Execution Subgraph",
        "model_name": "agent-action",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "citations": [],
        "interaction_type": "execution_result",
        "action_context": {"action_type": "agent"},
        "options": [],
    }
