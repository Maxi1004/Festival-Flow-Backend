from fastapi import APIRouter, Depends

from app.core.security import require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.recruitment_schema import (
    RecruitmentCreateRequest,
    RecruitmentInvitationResponse,
    RecruitmentResponse,
    RecruitmentStatusUpdateRequest,
)
from app.services.recruitment_service import (
    create_recruitment,
    list_my_recruitments,
    update_my_recruitment_status,
)

router = APIRouter(tags=["Recruitments"])


@router.post("/recruitments", response_model=RecruitmentResponse)
async def post_recruitment(
    payload: RecruitmentCreateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return create_recruitment(payload, current_user)


@router.get("/recruitments/me", response_model=list[RecruitmentInvitationResponse])
async def get_my_recruitments(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return list_my_recruitments(current_user)


@router.patch("/recruitments/{recruitment_id}/status", response_model=RecruitmentResponse)
async def patch_recruitment_status(
    recruitment_id: str,
    payload: RecruitmentStatusUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return update_my_recruitment_status(recruitment_id, payload, current_user)
