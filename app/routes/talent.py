from fastapi import APIRouter, Depends

from app.core.security import require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.talent_schema import (
    AvailableTalentResponse,
    TalentAvailabilityResponse,
    TalentAvailabilityUpsertRequest,
    TalentProfileResponse,
    TalentProfileUpsertRequest,
)
from app.services.talent_service import (
    get_talent_availability,
    get_talent_profile,
    list_available_talents,
    upsert_talent_availability,
    upsert_talent_profile,
)

router = APIRouter(tags=["Talent"])


@router.get("/profile/me", response_model=TalentProfileResponse)
async def get_my_profile(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_profile(current_user)


@router.put("/profile/me", response_model=TalentProfileResponse)
async def put_my_profile(
    payload: TalentProfileUpsertRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return upsert_talent_profile(current_user, payload)


@router.get("/availability/me", response_model=TalentAvailabilityResponse)
async def get_my_availability(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_availability(current_user)


@router.get("/availability", response_model=list[AvailableTalentResponse])
async def get_available_talents(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_available_talents()


@router.put("/availability/me", response_model=TalentAvailabilityResponse)
async def put_my_availability(
    payload: TalentAvailabilityUpsertRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return upsert_talent_availability(current_user, payload)
