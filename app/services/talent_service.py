from app.core.firebase import db
from app.core.utils import utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.talent_schema import (
    TalentAvailabilityResponse,
    TalentAvailabilityUpsertRequest,
    TalentProfileResponse,
    TalentProfileUpsertRequest,
)


def get_talent_profile(current_user: CurrentUser) -> TalentProfileResponse:
    profile_doc = db.collection("talent_profiles").document(current_user.uid).get()

    if not profile_doc.exists:
        return TalentProfileResponse(
            user_uid=current_user.uid,
            display_name=current_user.name or "",
            bio="",
            main_specialty="",
            specialties=[],
            location="",
            experience_years=0,
            languages=[],
            skills=[],
            portfolio_links=[],
            profile_completion=0,
            is_public=False,
            updated_at=None,
        )

    profile_data = profile_doc.to_dict() or {}
    return TalentProfileResponse(
        user_uid=profile_data.get("user_uid", current_user.uid),
        display_name=profile_data.get("display_name", current_user.name or ""),
        bio=profile_data.get("bio", ""),
        main_specialty=profile_data.get("main_specialty", ""),
        specialties=profile_data.get("specialties", []),
        location=profile_data.get("location", ""),
        experience_years=profile_data.get("experience_years", 0),
        languages=profile_data.get("languages", []),
        skills=profile_data.get("skills", []),
        portfolio_links=profile_data.get("portfolio_links", []),
        profile_completion=profile_data.get("profile_completion", 0),
        is_public=profile_data.get("is_public", False),
        updated_at=profile_data.get("updated_at"),
    )


def upsert_talent_profile(
    current_user: CurrentUser,
    payload: TalentProfileUpsertRequest,
) -> TalentProfileResponse:
    profile_data = {
        "user_uid": current_user.uid,
        "display_name": payload.display_name or current_user.name or "",
        "bio": payload.bio,
        "main_specialty": payload.main_specialty,
        "specialties": payload.specialties,
        "location": payload.location,
        "experience_years": payload.experience_years,
        "languages": payload.languages,
        "skills": payload.skills,
        "portfolio_links": [item.model_dump() for item in payload.portfolio_links],
        "profile_completion": payload.profile_completion,
        "is_public": payload.is_public,
        "updated_at": utc_now_iso(),
    }

    db.collection("talent_profiles").document(current_user.uid).set(profile_data)
    return TalentProfileResponse(**profile_data)


def get_talent_availability(current_user: CurrentUser) -> TalentAvailabilityResponse:
    availability_doc = db.collection("talent_availability").document(current_user.uid).get()

    if not availability_doc.exists:
        return TalentAvailabilityResponse(
            user_uid=current_user.uid,
            status="",
            travel_availability=False,
            work_modality="",
            work_location="",
            available_from=None,
            notes="",
            updated_at=None,
        )

    availability_data = availability_doc.to_dict() or {}
    return TalentAvailabilityResponse(
        user_uid=availability_data.get("user_uid", current_user.uid),
        status=availability_data.get("status", ""),
        travel_availability=availability_data.get("travel_availability", False),
        work_modality=availability_data.get("work_modality", ""),
        work_location=availability_data.get("work_location", ""),
        available_from=availability_data.get("available_from"),
        notes=availability_data.get("notes", ""),
        updated_at=availability_data.get("updated_at"),
    )


def upsert_talent_availability(
    current_user: CurrentUser,
    payload: TalentAvailabilityUpsertRequest,
) -> TalentAvailabilityResponse:
    availability_data = {
        "user_uid": current_user.uid,
        "status": payload.status,
        "travel_availability": payload.travel_availability,
        "work_modality": payload.work_modality,
        "work_location": payload.work_location,
        "available_from": payload.available_from.isoformat() if payload.available_from else None,
        "notes": payload.notes,
        "updated_at": utc_now_iso(),
    }

    db.collection("talent_availability").document(current_user.uid).set(availability_data)
    return TalentAvailabilityResponse(**availability_data)
