from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user, require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.application_schema import OpportunityApplicationResponse
from app.schemas.opportunity_schema import (
    OpportunityCreateRequest,
    OpportunityCrmResponse,
    OpportunityResponse,
    OpportunityStatusUpdateRequest,
    OpportunityUpdateRequest,
)
from app.services.opportunity_service import (
    create_opportunity,
    get_opportunity_by_id,
    list_my_opportunities_crm,
    list_my_opportunities,
    list_opportunities,
    update_my_opportunity,
    update_my_opportunity_status,
)
from app.services.application_service import list_opportunity_applications

router = APIRouter(tags=["Opportunities"])



@router.get("/opportunities")
async def get_opportunities(
    specialty: str | None = Query(default=None),
    location: str | None = Query(default=None),
    modality: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    cursor: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_opportunities(
        specialty=specialty,
        location=location,
        modality=modality,
        status=status,
        limit=limit,
        cursor=cursor,
    )


@router.get("/opportunities/me", response_model=list[OpportunityResponse])
async def get_my_opportunities(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_my_opportunities(current_user)


@router.get("/opportunities/me/crm", response_model=list[OpportunityCrmResponse])
async def get_my_opportunities_crm(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_my_opportunities_crm(current_user)


@router.get("/producer/opportunities", response_model=list[OpportunityResponse])
async def get_producer_opportunities(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_my_opportunities(current_user)


@router.get("/opportunities/{opportunity_id}/applications", response_model=list[OpportunityApplicationResponse])
async def get_opportunity_applications(
    opportunity_id: str,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_opportunity_applications(opportunity_id, current_user)


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
