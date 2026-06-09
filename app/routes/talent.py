import time

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.core.security import get_current_user, require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.talent_schema import (
    AvailableTalentCrmResponse,
    AvailableTalentResponse,
    TalentAvailabilityResponse,
    TalentAvailabilityUpsertRequest,
    TalentProfileResponse,
    TalentPublicProfileResponse,
    TalentProfilePhotoResponse,
    TalentProfilePortfolioPdfResponse,
    TalentProfileUpsertRequest,
    TalentCommitmentsResponse,
)
from app.services.talent_service import (
    get_talent_availability,
    get_talent_profile,
    get_talent_public_profile,
    list_available_talents,
    list_available_talents_crm,
    upsert_talent_availability,
    upsert_talent_profile,
    update_talent_profile_photo,
    update_talent_profile_portfolio_pdf,
    get_talent_availability_commitments,
)
from app.services.cloudinary_service import (
    CloudinaryUploadError,
    upload_talent_portfolio_pdf,
    upload_talent_profile_photo,
)

router = APIRouter(tags=["Talent"])

ALLOWED_PROFILE_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_PROFILE_PHOTO_SIZE = 5 * 1024 * 1024
MAX_PORTFOLIO_PDF_SIZE = 10 * 1024 * 1024


@router.get("/profile/me", response_model=TalentProfileResponse)
async def get_my_profile(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    start = time.perf_counter()
    response = get_talent_profile(current_user)
    print(f"[PERF] GET /talent/profile/me route total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return response


@router.get("/{user_id}/profile-public", response_model=TalentPublicProfileResponse)
async def get_public_profile(
    user_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return get_talent_public_profile(user_id)


@router.put("/profile/me", response_model=TalentProfileResponse)
async def put_my_profile(
    payload: TalentProfileUpsertRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return upsert_talent_profile(current_user, payload)


@router.post("/profile/photo", response_model=TalentProfilePhotoResponse)
async def post_my_profile_photo(
    photo: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    if photo.content_type not in ALLOWED_PROFILE_PHOTO_TYPES:
        raise HTTPException(
            status_code=415,
            detail="La foto debe ser una imagen JPEG, PNG o WebP.",
        )

    try:
        image_data = await photo.read(MAX_PROFILE_PHOTO_SIZE + 1)
    finally:
        await photo.close()

    if not image_data:
        raise HTTPException(status_code=400, detail="La foto esta vacia.")

    if len(image_data) > MAX_PROFILE_PHOTO_SIZE:
        raise HTTPException(
            status_code=413,
            detail="La foto supera el tamano maximo permitido de 5 MB.",
        )

    try:
        photo_url = upload_talent_profile_photo(current_user.uid, image_data)
    except CloudinaryUploadError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    update_talent_profile_photo(current_user, photo_url)
    return TalentProfilePhotoResponse(photo_url=photo_url)


@router.post("/profile/portfolio-pdf", response_model=TalentProfilePortfolioPdfResponse)
async def post_my_profile_portfolio_pdf(
    portfolio_pdf: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    if portfolio_pdf.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="El archivo debe estar en formato PDF.")

    try:
        pdf_data = await portfolio_pdf.read(MAX_PORTFOLIO_PDF_SIZE + 1)
    finally:
        await portfolio_pdf.close()

    if not pdf_data:
        raise HTTPException(status_code=400, detail="El PDF esta vacio.")

    if not pdf_data.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="El archivo debe ser un PDF valido.")

    if len(pdf_data) > MAX_PORTFOLIO_PDF_SIZE:
        raise HTTPException(
            status_code=413,
            detail="El PDF supera el tamano maximo permitido de 10 MB.",
        )

    try:
        portfolio_pdf_url = upload_talent_portfolio_pdf(current_user.uid, pdf_data)
    except CloudinaryUploadError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    update_talent_profile_portfolio_pdf(current_user, portfolio_pdf_url)
    return TalentProfilePortfolioPdfResponse(portfolio_pdf_url=portfolio_pdf_url)

@router.get("/availability/commitments", response_model=TalentCommitmentsResponse)
async def get_my_availability_commitments(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_availability_commitments(current_user)


@router.get("/availability/me", response_model=TalentAvailabilityResponse)
async def get_my_availability(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_availability(current_user)


@router.get("/availability", response_model=list[AvailableTalentResponse])
async def get_available_talents(
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    location: str | None = Query(default=None),
    language: str | None = Query(default=None),
    availability: str = Query(default="AVAILABLE"),
    limit: int = Query(default=40, ge=1, le=100),
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_available_talents(
        search=search,
        category=category,
        location=location,
        language=language,
        availability=availability,
        limit=limit,
    )


@router.get("/availability/crm", response_model=list[AvailableTalentCrmResponse])
async def get_available_talents_crm(
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    location: str | None = Query(default=None),
    language: str | None = Query(default=None),
    availability: str = Query(default="AVAILABLE"),
    limit: int = Query(default=40, ge=1, le=100),
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_available_talents_crm(
        search=search,
        category=category,
        location=location,
        language=language,
        availability=availability,
        limit=limit,
    )


@router.put("/availability/me", response_model=TalentAvailabilityResponse)
async def put_my_availability(
    payload: TalentAvailabilityUpsertRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return upsert_talent_availability(current_user, payload)
