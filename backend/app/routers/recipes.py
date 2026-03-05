from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.models.automation_recipe import AutomationRecipe
from app.models.tenant_membership import TenantMembership
from app.models.workspace_recipe_state import WorkspaceRecipeState
from app.schemas.recipes import RecipeRead, WorkspaceRecipeStateRead, WorkspaceRecipeStateUpsert

router = APIRouter(prefix="/recipes", tags=["recipes"])


DEFAULT_RECIPES = [
    {
        "key": "faq_drive_sheets",
        "name": "Answer customer FAQs from Drive/Sheets",
        "description": "Use indexed Drive and Sheets sources to answer inbound customer FAQ questions.",
        "default_config_json": {"channels": ["telegram", "whatsapp", "facebook"]},
    },
    {
        "key": "book_meeting",
        "name": "Book a meeting from chat",
        "description": "Collect details then create a calendar meeting after confirmation.",
        "default_config_json": {},
    },
    {
        "key": "check_availability",
        "name": "Check availability and propose times",
        "description": "Look up calendar availability and suggest non-overlapping time slots.",
        "default_config_json": {"slot_minutes": 30},
    },
    {
        "key": "lead_capture",
        "name": "Collect lead details and log to Google Sheet",
        "description": "Capture contact details and write/update a lead row in CRM-lite sheet.",
        "default_config_json": {},
    },
    {
        "key": "post_chat_followup",
        "name": "Send follow-up email after chat conversation",
        "description": "Generate and send follow-up email after successful chat interaction (with confirmation).",
        "default_config_json": {},
    },
]


def _seed_recipes(db: Session) -> None:
    existing = {item.key for item in db.execute(select(AutomationRecipe)).scalars().all()}
    changed = False
    for recipe in DEFAULT_RECIPES:
        if recipe["key"] in existing:
            continue
        db.add(AutomationRecipe(**recipe))
        changed = True
    if changed:
        db.commit()


@router.get("", response_model=list[RecipeRead])
def list_recipes(
    membership: TenantMembership = Depends(get_current_tenant_membership),  # noqa: ARG001
    db: Session = Depends(get_db),
) -> list[RecipeRead]:
    _seed_recipes(db)
    recipes = db.execute(select(AutomationRecipe).order_by(AutomationRecipe.name.asc())).scalars().all()
    return [RecipeRead(**{k: getattr(item, k) for k in RecipeRead.model_fields.keys()}) for item in recipes]


@router.get("/states", response_model=list[WorkspaceRecipeStateRead])
def list_recipe_states(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[WorkspaceRecipeStateRead]:
    _seed_recipes(db)
    states = db.execute(
        select(WorkspaceRecipeState)
        .where(WorkspaceRecipeState.tenant_id == membership.tenant_id)
        .order_by(WorkspaceRecipeState.updated_at.desc())
    ).scalars().all()
    return [WorkspaceRecipeStateRead(**{k: getattr(item, k) for k in WorkspaceRecipeStateRead.model_fields.keys()}) for item in states]


@router.put("/{recipe_id}/state", response_model=WorkspaceRecipeStateRead)
def upsert_recipe_state(
    recipe_id: str,
    payload: WorkspaceRecipeStateUpsert,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> WorkspaceRecipeStateRead:
    _seed_recipes(db)
    recipe = db.get(AutomationRecipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    state = db.execute(
        select(WorkspaceRecipeState).where(
            WorkspaceRecipeState.tenant_id == admin.tenant_id,
            WorkspaceRecipeState.recipe_id == recipe_id,
        )
    ).scalar_one_or_none()
    if state is None:
        state = WorkspaceRecipeState(
            tenant_id=admin.tenant_id,
            recipe_id=recipe_id,
            enabled=payload.enabled,
            config_json=payload.config_json,
        )
        db.add(state)
    else:
        state.enabled = payload.enabled
        state.config_json = payload.config_json

    db.commit()
    db.refresh(state)
    return WorkspaceRecipeStateRead(**{k: getattr(state, k) for k in WorkspaceRecipeStateRead.model_fields.keys()})
