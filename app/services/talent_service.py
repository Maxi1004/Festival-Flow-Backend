from datetime import date, datetime
from typing import Any
from unicodedata import normalize as unicode_normalize

from app.core.firebase import db
from app.core.utils import utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.talent_schema import (
    AvailabilityStatus,
    AvailableTalentProfile,
    AvailableTalentResponse,
    TalentAvailabilityResponse,
    TalentAvailabilityUpsertRequest,
    TalentProfileResponse,
    TalentProfileUpsertRequest,
    WorkModality,
)


DEFAULT_AVAILABILITY_STATUS = AvailabilityStatus.UNAVAILABLE
DEFAULT_WORK_MODALITY = WorkModality.REMOTE


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip().lower()
    return unicode_normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _normalize_availability_status(value: Any) -> AvailabilityStatus:
    if isinstance(value, AvailabilityStatus):
        return value

    raw_value = str(value or "").strip()
    upper_value = raw_value.upper()
    if upper_value in AvailabilityStatus.__members__:
        return AvailabilityStatus(upper_value)

    normalized = _clean_text(raw_value)
    negative_markers = ("unavailable", "no disponible", "indisponible", "no estoy disponible")
    if any(marker in normalized for marker in negative_markers):
        return AvailabilityStatus.UNAVAILABLE
    if "available" in normalized or "disponible" in normalized or normalized.startswith("si"):
        return AvailabilityStatus.AVAILABLE

    return DEFAULT_AVAILABILITY_STATUS


def _normalize_work_modality(value: Any) -> WorkModality:
    if isinstance(value, WorkModality):
        return value

    raw_value = str(value or "").strip()
    upper_value = raw_value.upper()
    if upper_value in WorkModality.__members__:
        return WorkModality(upper_value)

    normalized = _clean_text(raw_value)
    if "hybrid" in normalized or "hibrid" in normalized:
        return WorkModality.HYBRID
    if "onsite" in normalized or "on site" in normalized or "presencial" in normalized:
        return WorkModality.ONSITE
    if "remote" in normalized or "remoto" in normalized:
        return WorkModality.REMOTE
    if "freelance" in normalized:
        return WorkModality.FREELANCE

    return DEFAULT_WORK_MODALITY


def _normalize_travel_availability(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    normalized = _clean_text(value)
    return normalized in {"true", "1", "yes", "y", "si", "s"}


def _serialize_available_from(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return str(value.isoformat()).split("T", maxsplit=1)[0]

    return str(value)


def _get_first_portfolio_url(profile_data: dict) -> str | None:
    if profile_data.get("portfolio_url"):
        return profile_data.get("portfolio_url")

    portfolio_links = profile_data.get("portfolio_links") or []
    if not portfolio_links:
        return None

    first_link = portfolio_links[0]
    if isinstance(first_link, dict):
        return first_link.get("url")

    return None


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
            user_id=current_user.uid,
            status=DEFAULT_AVAILABILITY_STATUS,
            travel_availability=False,
            work_modality=DEFAULT_WORK_MODALITY,
            location=None,
            available_from=None,
            notes=None,
            updated_at=None,
        )

    availability_data = availability_doc.to_dict() or {}
    return TalentAvailabilityResponse(
        user_id=availability_data.get("user_id") or availability_data.get("user_uid", current_user.uid),
        status=_normalize_availability_status(
            availability_data.get("status") or availability_data.get("availability_status")
        ),
        travel_availability=_normalize_travel_availability(
            availability_data.get("travel_availability", availability_data.get("available_to_travel", False))
        ),
        work_modality=_normalize_work_modality(
            availability_data.get("work_modality") or availability_data.get("modality")
        ),
        location=availability_data.get("location") or availability_data.get("work_location"),
        available_from=_serialize_available_from(availability_data.get("available_from")),
        notes=availability_data.get("notes"),
        updated_at=availability_data.get("updated_at"),
    )


def upsert_talent_availability(
    current_user: CurrentUser,
    payload: TalentAvailabilityUpsertRequest,
) -> TalentAvailabilityResponse:
    availability_data = {
        "user_id": current_user.uid,
        "status": payload.status.value,
        "travel_availability": payload.travel_availability,
        "work_modality": payload.work_modality.value,
        "location": payload.location,
        "available_from": _serialize_available_from(payload.available_from),
        "notes": payload.notes,
        "updated_at": utc_now_iso(),
    }

    db.collection("talent_availability").document(current_user.uid).set(availability_data)
    return TalentAvailabilityResponse(**availability_data)


def list_available_talents() -> list[AvailableTalentResponse]:
    items: list[AvailableTalentResponse] = []

    for availability_doc in db.collection("talent_availability").stream():
        availability_data = availability_doc.to_dict() or {}
        status = _normalize_availability_status(
            availability_data.get("status") or availability_data.get("availability_status")
        )

        if status != AvailabilityStatus.AVAILABLE:
            continue

        user_id = availability_data.get("user_id") or availability_data.get("user_uid") or availability_doc.id
        user_doc = db.collection("users").document(user_id).get()
        if not user_doc.exists:
            continue

        user_data = user_doc.to_dict() or {}
        if user_data.get("role") != "TALENT":
            continue

        profile_doc = db.collection("talent_profiles").document(user_id).get()
        profile_data = profile_doc.to_dict() or {} if profile_doc.exists else {}

        items.append(
            AvailableTalentResponse(
                user_id=user_id,
                name=user_data.get("name", ""),
                email=user_data.get("email", ""),
                status=status,
                travel_availability=_normalize_travel_availability(
                    availability_data.get("travel_availability", availability_data.get("available_to_travel", False))
                ),
                work_modality=_normalize_work_modality(
                    availability_data.get("work_modality") or availability_data.get("modality")
                ),
                location=availability_data.get("location") or availability_data.get("work_location"),
                available_from=_serialize_available_from(availability_data.get("available_from")),
                notes=availability_data.get("notes"),
                profile=AvailableTalentProfile(
                    specialties=profile_data.get("specialties", []),
                    skills=profile_data.get("skills", []),
                    experience_years=profile_data.get("experience_years"),
                    portfolio_url=_get_first_portfolio_url(profile_data),
                ),
            )
        )

    return sorted(items, key=lambda item: item.available_from or "")
