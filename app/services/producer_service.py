from app.core.firebase import db
from app.core.utils import utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.producer_schema import (
    ProducerProfileResponse,
    ProducerProfileUpsertRequest,
)


def _clean_image_url(value: object) -> str | None:
    if isinstance(value, str):
        cleaned_value = value.strip()
        return cleaned_value or None

    return None


def _select_photo_url(profile_data: dict, user_data: dict, current_user: CurrentUser) -> str | None:
    return (
        _clean_image_url(profile_data.get("photo_url"))
        or _clean_image_url(user_data.get("picture"))
        or _clean_image_url(user_data.get("photo_url"))
        or _clean_image_url(current_user.picture)
        or _clean_image_url(current_user.photo_url)
    )


def _build_profile_response(
    current_user: CurrentUser,
    profile_data: dict,
    user_data: dict,
) -> ProducerProfileResponse:
    return ProducerProfileResponse(
        user_uid=profile_data.get("user_uid", current_user.uid),
        display_name=profile_data.get("display_name") or user_data.get("name") or current_user.name or "",
        company_name=profile_data.get("company_name", ""),
        role_title=profile_data.get("role_title", ""),
        bio=profile_data.get("bio", ""),
        location=profile_data.get("location", ""),
        country=profile_data.get("country", ""),
        phone=profile_data.get("phone", ""),
        website=profile_data.get("website", ""),
        photo_url=_select_photo_url(profile_data, user_data, current_user),
        updated_at=profile_data.get("updated_at"),
    )


def get_producer_profile(current_user: CurrentUser) -> ProducerProfileResponse:
    profile_doc = db.collection("producer_profiles").document(current_user.uid).get()
    profile_data = profile_doc.to_dict() or {} if profile_doc.exists else {}

    user_doc = db.collection("users").document(current_user.uid).get()
    user_data = user_doc.to_dict() or {} if user_doc.exists else {}

    return _build_profile_response(current_user, profile_data, user_data)


def upsert_producer_profile(
    current_user: CurrentUser,
    payload: ProducerProfileUpsertRequest,
) -> ProducerProfileResponse:
    profile_doc_ref = db.collection("producer_profiles").document(current_user.uid)
    existing_profile_doc = profile_doc_ref.get()
    existing_profile_data = existing_profile_doc.to_dict() or {} if existing_profile_doc.exists else {}

    profile_data = {
        "user_uid": current_user.uid,
        "display_name": payload.display_name or current_user.name or "",
        "company_name": payload.company_name,
        "role_title": payload.role_title,
        "bio": payload.bio,
        "location": payload.location,
        "country": payload.country,
        "phone": payload.phone,
        "website": payload.website,
        "photo_url": existing_profile_data.get("photo_url"),
        "updated_at": utc_now_iso(),
    }

    profile_doc_ref.set(profile_data, merge=True)

    user_doc = db.collection("users").document(current_user.uid).get()
    user_data = user_doc.to_dict() or {} if user_doc.exists else {}
    return _build_profile_response(current_user, profile_data, user_data)


def update_producer_profile_photo(current_user: CurrentUser, photo_url: str) -> str:
    profile_doc_ref = db.collection("producer_profiles").document(current_user.uid)
    profile_doc_ref.set(
        {
            "user_uid": current_user.uid,
            "photo_url": photo_url,
            "updated_at": utc_now_iso(),
        },
        merge=True,
    )
    db.collection("users").document(current_user.uid).set(
        {
            "photo_url": photo_url,
            "picture": photo_url,
        },
        merge=True,
    )
    return photo_url
