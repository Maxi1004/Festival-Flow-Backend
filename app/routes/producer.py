from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.security import require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.producer_schema import (
    ProducerProfilePhotoResponse,
    ProducerProfileResponse,
    ProducerProfileUpsertRequest,
)
from app.services.cloudinary_service import (
    CloudinaryUploadError,
    upload_producer_profile_photo,
)
from app.services.producer_service import (
    get_producer_profile,
    update_producer_profile_photo,
    upsert_producer_profile,
)

router = APIRouter(tags=["Producer"])

ALLOWED_PROFILE_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_PROFILE_PHOTO_SIZE = 5 * 1024 * 1024


@router.get("/profile/me", response_model=ProducerProfileResponse)
async def get_my_producer_profile(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return get_producer_profile(current_user)


@router.put("/profile/me", response_model=ProducerProfileResponse)
async def put_my_producer_profile(
    payload: ProducerProfileUpsertRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return upsert_producer_profile(current_user, payload)


@router.post("/profile/photo", response_model=ProducerProfilePhotoResponse)
async def post_my_producer_profile_photo(
    photo: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
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
        photo_url = upload_producer_profile_photo(current_user.uid, image_data)
    except CloudinaryUploadError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    update_producer_profile_photo(current_user, photo_url)
    return ProducerProfilePhotoResponse(photo_url=photo_url)
