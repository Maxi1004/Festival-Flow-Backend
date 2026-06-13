from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status as http_status,
)

from app.core.security import require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.festival_schema import (
    FestivalProducerResponse,
    FestivalSelectionRequest,
    FestivalSelectionResponse,
    FestivalStatus,
)
from app.services.producer_festival_service import (
    list_festival_selections,
    list_producer_festivals,
    remove_festival_selection,
    select_festival,
)


router = APIRouter(prefix="/producer", tags=["Producer Festivals"])


@router.get("/festivals", response_model=list[FestivalProducerResponse])
async def get_producer_festivals(
    status: FestivalStatus | None = Query(default=None),
    country: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    search: str | None = Query(default=None),
    deadline_from: date | None = Query(default=None),
    deadline_to: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    if deadline_from and deadline_to and deadline_from > deadline_to:
        raise HTTPException(
            status_code=400,
            detail="deadline_from no puede ser posterior a deadline_to",
        )

    return list_producer_festivals(
        producer_uid=current_user.uid,
        status=status.value if status else None,
        country=country,
        platform=platform,
        search=search,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        limit=limit,
    )


@router.get(
    "/festival-selections",
    response_model=list[FestivalSelectionResponse],
)
async def get_producer_festival_selections(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_festival_selections(current_user.uid)


@router.post(
    "/festival-selections",
    response_model=FestivalSelectionResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def post_producer_festival_selection(
    payload: FestivalSelectionRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return select_festival(current_user.uid, payload.festival_id)


@router.delete(
    "/festival-selections/{festival_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def delete_producer_festival_selection(
    festival_id: str,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    remove_festival_selection(current_user.uid, festival_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
