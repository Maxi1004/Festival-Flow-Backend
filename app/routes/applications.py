from fastapi import APIRouter, Depends, Query

from app.core.security import require_role
from app.schemas.application_schema import (
    ApplicationCreateRequest,
    ApplicationResponse,
    ApplicationStatusUpdateRequest,
    ApplicationStatusUpdateResponse,
    TalentApplicationFeedResponse,
    TalentApplicationFeedSummary,
)
from app.schemas.auth_schema import CurrentUser, UserRole
from app.services.application_service import (
    create_application,
    get_my_application_summary,
    list_my_application_feed,
    list_my_applications,
    update_application_status,
)

router = APIRouter(tags=["Applications"])


@router.post("/applications", response_model=ApplicationResponse)
async def post_application(
    payload: ApplicationCreateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return create_application(payload, current_user)


@router.get("/applications/me", response_model=list[ApplicationResponse])
async def get_my_applications(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return list_my_applications(current_user)


@router.get("/applications/me/feed", response_model=TalentApplicationFeedResponse)
async def get_my_application_feed(
    limit: int = Query(default=10, ge=1, le=50),
    cursor: str | None = Query(default=None),
    summary: bool = Query(default=True),
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return list_my_application_feed(current_user, limit=limit, cursor=cursor, include_summary=summary)


@router.get("/applications/me/summary", response_model=TalentApplicationFeedSummary)
async def get_my_applications_summary(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_my_application_summary(current_user)


@router.patch("/applications/{application_id}/status", response_model=ApplicationStatusUpdateResponse)
async def patch_application_status(
    application_id: str,
    payload: ApplicationStatusUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_application_status(application_id, payload, current_user)
