from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.core.security import require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.festival_schema import (
    FestivalCleanupConfirmRequest,
    FestivalImportResponse,
    FestivalRefreshStatusResponse,
    FestivalResponse,
    FestivalStatus,
    FestivalUpdateRequest,
)
from app.services.admin_festival_service import (
    cleanup_duplicate_festivals,
    cleanup_invalid_festivals,
    get_festival_audit_summary,
    import_festivals_from_excel,
    list_festival_duplicates,
    list_admin_festivals,
    preview_festival_cleanup,
    refresh_festival_statuses,
    update_admin_festival,
)


router = APIRouter(prefix="/admin", tags=["Admin Festivals"])


@router.post("/import-festivals", response_model=FestivalImportResponse)
async def post_import_festivals(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in {".xlsx", ".xls"}:
        raise HTTPException(
            status_code=400,
            detail="El archivo debe tener extension .xlsx o .xls",
        )

    file_bytes = await file.read()
    try:
        return import_festivals_from_excel(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/festivals", response_model=list[FestivalResponse])
async def get_admin_festivals(
    status: FestivalStatus | None = Query(default=None),
    country: str | None = Query(default=None),
    search: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=1500),
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    return list_admin_festivals(
        status=status.value if status else None,
        country=country,
        search=search,
        platform=platform,
        limit=limit,
    )


@router.put("/festivals/{festival_id}", response_model=FestivalResponse)
async def put_admin_festival(
    festival_id: str,
    payload: FestivalUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    try:
        return update_admin_festival(festival_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/festivals/refresh-status",
    response_model=FestivalRefreshStatusResponse,
)
async def post_refresh_festival_statuses(
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    return refresh_festival_statuses()


@router.get("/festivals/audit-summary")
async def get_admin_festival_audit_summary(
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    return get_festival_audit_summary()


@router.get("/festivals/duplicates")
async def get_admin_festival_duplicates(
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    return list_festival_duplicates()


@router.post("/festivals/cleanup-preview")
async def post_admin_festival_cleanup_preview(
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    return preview_festival_cleanup()


@router.post("/festivals/cleanup-duplicates")
async def post_admin_festival_cleanup_duplicates(
    payload: FestivalCleanupConfirmRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    return cleanup_duplicate_festivals(payload.confirm, current_user.uid)


@router.post("/festivals/cleanup-invalid")
async def post_admin_festival_cleanup_invalid(
    payload: FestivalCleanupConfirmRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    return cleanup_invalid_festivals(payload.confirm, current_user.uid)
