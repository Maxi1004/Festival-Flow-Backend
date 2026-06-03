from fastapi import APIRouter, Depends

from app.core.security import require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.dashboard_schema import (
    ProducerDashboardDetailsResponse,
    ProducerDashboardQuickResponse,
    ProducerDashboardResponse,
    TalentDashboardDetailsResponse,
    TalentDashboardQuickResponse,
    TalentDashboardResponse,
)
from app.services.dashboard_service import (
    get_producer_dashboard,
    get_producer_dashboard_details,
    get_producer_dashboard_quick,
    get_talent_dashboard,
    get_talent_dashboard_details,
    get_talent_dashboard_quick,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/producer", response_model=ProducerDashboardResponse)
async def get_producer_dashboard_summary(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return get_producer_dashboard(current_user)


@router.get("/producer/quick", response_model=ProducerDashboardQuickResponse)
async def get_producer_dashboard_quick_summary(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return get_producer_dashboard_quick(current_user)


@router.get("/producer/details", response_model=ProducerDashboardDetailsResponse)
async def get_producer_dashboard_details_summary(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return get_producer_dashboard_details(current_user)


@router.get("/talent", response_model=TalentDashboardResponse)
async def get_talent_dashboard_summary(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_dashboard(current_user)


@router.get("/talent/quick", response_model=TalentDashboardQuickResponse)
async def get_talent_dashboard_quick_summary(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_dashboard_quick(current_user)


@router.get("/talent/details", response_model=TalentDashboardDetailsResponse)
async def get_talent_dashboard_details_summary(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_dashboard_details(current_user)
