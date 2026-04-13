from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user, require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.opportunity_schema import (
    OpportunityCreateRequest,
    OpportunityResponse,
    OpportunityStatusUpdateRequest,
    OpportunityUpdateRequest,
)
from app.services.opportunity_service import (
    create_opportunity,
    get_opportunity_by_id,
    list_my_opportunities,
    list_opportunities,
    update_my_opportunity,
    update_my_opportunity_status,
)

router = APIRouter(tags=["Opportunities"])


@router.get("/opportunities", response_model=list[OpportunityResponse])
async def get_opportunities(
    specialty: str | None = Query(default=None),
    location: str | None = Query(default=None),
    modality: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_opportunities(
        specialty=specialty,
        location=location,
        modality=modality,
        status=status,
    )


@router.post("/opportunities", response_model=OpportunityResponse)
async def post_opportunity(
    payload: OpportunityCreateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return create_opportunity(payload, current_user)


@router.get("/opportunities/me", response_model=list[OpportunityResponse])
async def get_my_opportunities(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_my_opportunities(current_user)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def get_opportunity_detail(
    opportunity_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return get_opportunity_by_id(opportunity_id)


@router.put("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def put_opportunity(
    opportunity_id: str,
    payload: OpportunityUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_my_opportunity(opportunity_id, payload, current_user)


@router.patch("/opportunities/{opportunity_id}/status", response_model=OpportunityResponse)
async def patch_opportunity_status(
    opportunity_id: str,
    payload: OpportunityStatusUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_my_opportunity_status(opportunity_id, payload, current_user)
