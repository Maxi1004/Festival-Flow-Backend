from datetime import date, datetime
import time
from typing import Any
from unicodedata import normalize as unicode_normalize

from google.cloud.firestore_v1.base_query import FieldFilter, Or
from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import get_talent_uid_from_data, utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.talent_schema import (
    AvailabilityStatus,
    AvailableTalentCrmResponse,
    AvailableTalentProfile,
    AvailableTalentResponse,
    TalentAvailabilityResponse,
    TalentAvailabilityUpsertRequest,
    TalentProfileResponse,
    TalentPublicProfileResponse,
    TalentProfileUpsertRequest,
    WorkModality,
    TalentCommitmentResponse,
    TalentCommitmentsResponse,
)


DEFAULT_AVAILABILITY_STATUS = AvailabilityStatus.UNAVAILABLE
DEFAULT_WORK_MODALITY = WorkModality.REMOTE
MAX_AVAILABLE_TALENT_CANDIDATES = 200
MAX_TALENT_COMMITMENT_CANDIDATES = 100
MAX_CREW_ASSIGNMENT_CANDIDATES = 500


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip().lower()
    return unicode_normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []

    raw_items = value if isinstance(value, list) else str(value).split(",")
    items: list[str] = []

    for item in raw_items:
        normalized_item = str(item).strip()
        if normalized_item and normalized_item not in items:
            items.append(normalized_item)

    return items


def _has_positive_number(value: Any) -> bool:
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _calculate_profile_completion(profile_data: dict) -> int:
    requirements = [
        (bool(profile_data.get("photo_url") or profile_data.get("picture") or profile_data.get("avatar_url")), 10),
        (bool(str(profile_data.get("display_name") or "").strip()), 5),
        (bool(str(profile_data.get("location") or "").strip()), 5),
        (bool(str(profile_data.get("main_specialty") or "").strip()), 10),
        (bool(_normalize_text_list(profile_data.get("specialties"))), 10),
        (bool(_normalize_text_list(profile_data.get("skills"))), 10),
        (bool(_normalize_text_list(profile_data.get("languages"))), 10),
        (bool(str(profile_data.get("bio") or "").strip()), 10),
        (_has_positive_number(profile_data.get("experience_years")), 5),
        (bool(profile_data.get("portfolio_items")), 10),
        (bool(str(profile_data.get("portfolio_pdf_url") or "").strip()), 10),
        (profile_data.get("is_public") is True, 5),
    ]

    return sum(weight for is_complete, weight in requirements if is_complete)


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


def _first_present(*values: Any, default: str = "") -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _first_query_match(collection_name: str, field_name: str, value: str):
    docs = list(
        db.collection(collection_name)
        .where(filter=FieldFilter(field_name, "==", value))
        .limit(1)
        .stream()
    )
    return docs[0] if docs else None


def _resolve_talent_documents(identifier: str) -> tuple[str, dict, dict]:
    requested_id = identifier.strip()
    print(f"[DEBUG] profile-public requested id={requested_id}")

    direct_refs = [
        db.collection("talent_profiles").document(requested_id),
        db.collection("users").document(requested_id),
        db.collection("talent_availability").document(requested_id),
    ]
    direct_docs = {
        doc.reference.parent.id: doc
        for doc in db.get_all(direct_refs)
        if doc.exists
    }
    profile_doc = direct_docs.get("talent_profiles")
    user_doc = direct_docs.get("users")
    availability_doc = direct_docs.get("talent_availability")

    if not profile_doc:
        profile_doc = _first_query_match("talent_profiles", "user_uid", requested_id)
    if not user_doc:
        user_doc = _first_query_match("users", "uid", requested_id)
    if not user_doc and "@" in requested_id:
        user_doc = _first_query_match("users", "email", requested_id)
    if not availability_doc:
        availability_doc = (
            _first_query_match("talent_availability", "user_id", requested_id)
            or _first_query_match("talent_availability", "user_uid", requested_id)
        )

    if not profile_doc and not user_doc and not availability_doc:
        legacy_refs = [
            db.collection("crew_members").document(requested_id),
            db.collection("applications").document(requested_id),
            db.collection("recruitments").document(requested_id),
        ]
        legacy_data = next(
            (
                doc.to_dict() or {}
                for doc in db.get_all(legacy_refs)
                if doc.exists
            ),
            {},
        )
        resolved_legacy_uid = get_talent_uid_from_data(legacy_data)
        if resolved_legacy_uid and resolved_legacy_uid != requested_id:
            return _resolve_talent_documents(resolved_legacy_uid)

        for collection_name in ("crew_members", "applications", "recruitments"):
            for field_name in (
                "user_id",
                "user_uid",
                "talent_user_id",
                "talent_uid",
                "talent_id",
            ):
                legacy_doc = _first_query_match(collection_name, field_name, requested_id)
                if not legacy_doc:
                    continue
                resolved_legacy_uid = get_talent_uid_from_data(
                    legacy_doc.to_dict() or {}
                )
                if resolved_legacy_uid and resolved_legacy_uid != requested_id:
                    return _resolve_talent_documents(resolved_legacy_uid)

    profile_data = profile_doc.to_dict() or {} if profile_doc else {}
    user_data = user_doc.to_dict() or {} if user_doc else {}
    availability_data = availability_doc.to_dict() or {} if availability_doc else {}
    resolved_uid = (
        get_talent_uid_from_data(profile_data)
        or get_talent_uid_from_data(user_data)
        or get_talent_uid_from_data(availability_data)
        or (profile_doc.id if profile_doc else None)
        or (user_doc.id if user_doc else None)
        or (availability_doc.id if availability_doc else None)
    )

    if not resolved_uid:
        raise HTTPException(status_code=404, detail="Perfil de talento no encontrado")

    if not profile_doc or profile_doc.id != resolved_uid:
        resolved_profile = db.collection("talent_profiles").document(resolved_uid).get()
        if resolved_profile.exists:
            profile_doc = resolved_profile
            profile_data = resolved_profile.to_dict() or {}
    if not user_doc or user_doc.id != resolved_uid:
        resolved_user = db.collection("users").document(resolved_uid).get()
        if resolved_user.exists:
            user_doc = resolved_user
            user_data = resolved_user.to_dict() or {}

    print(f"[DEBUG] resolved talent uid={resolved_uid}")
    return resolved_uid, user_data, profile_data


def get_talent_public_profile(user_id: str) -> TalentPublicProfileResponse:
    resolved_uid, user_data, profile_data = _resolve_talent_documents(user_id)
    availability_doc = db.collection("talent_availability").document(resolved_uid).get()
    availability_data = availability_doc.to_dict() or {} if availability_doc.exists else {}
    print(
        "[DEBUG] found user/profile/availability "
        f"user={bool(user_data)} profile={bool(profile_data)} "
        f"availability={bool(availability_data)}"
    )

    display_name = _first_present(
        profile_data.get("display_name"),
        user_data.get("name"),
        user_data.get("display_name"),
        user_data.get("email"),
    )
    email = _first_present(user_data.get("email"), profile_data.get("email"))
    photo_url = _first_present(
        profile_data.get("photo_url"),
        profile_data.get("picture"),
        user_data.get("photo_url"),
        user_data.get("picture"),
        user_data.get("avatar_url"),
    ) or None

    return TalentPublicProfileResponse(
        user_id=resolved_uid,
        user_uid=resolved_uid,
        name=display_name,
        email=email,
        photo_url=photo_url,
        picture=photo_url,
        display_name=display_name,
        bio=_first_present(profile_data.get("bio")),
        main_specialty=_first_present(profile_data.get("main_specialty")),
        specialties=_normalize_text_list(profile_data.get("specialties")),
        skills=_normalize_text_list(profile_data.get("skills")),
        languages=_normalize_text_list(profile_data.get("languages")),
        experience_years=int(profile_data.get("experience_years") or 0),
        location=_first_present(
            availability_data.get("location"),
            availability_data.get("work_location"),
            profile_data.get("location"),
        ),
        work_modality=_first_present(
            availability_data.get("work_modality"),
            availability_data.get("modality"),
        ),
        availability_status=_first_present(
            availability_data.get("status"),
            availability_data.get("availability_status"),
        ),
        available_from=_serialize_available_from(availability_data.get("available_from")),
        availability_notes=availability_data.get("notes"),
        portfolio_url=_get_first_portfolio_url(profile_data),
        portfolio_links=profile_data.get("portfolio_links") or [],
        portfolio_items=profile_data.get("portfolio_items") or [],
        portfolio_pdf_url=profile_data.get("portfolio_pdf_url"),
    )


def get_talent_profile(current_user: CurrentUser) -> TalentProfileResponse:
    start = time.perf_counter()
    profile_get_start = time.perf_counter()
    profile_doc = db.collection("talent_profiles").document(current_user.uid).get()
    print(
        "[PERF] talent profile Firestore talent_profiles/{uid}.get "
        f"(reads=1): {(time.perf_counter() - profile_get_start) * 1000:.2f} ms"
    )

    if not profile_doc.exists:
        serialization_start = time.perf_counter()
        response = TalentProfileResponse(
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
            portfolio_items=[],
            photo_url=None,
            portfolio_pdf_url=None,
            profile_completion=0,
            is_public=False,
            updated_at=None,
        )
        print(f"[PERF] talent profile serialize default response: {(time.perf_counter() - serialization_start) * 1000:.2f} ms")
        print(f"[PERF] talent profile service total: {(time.perf_counter() - start) * 1000:.2f} ms")
        return response

    serialization_start = time.perf_counter()
    profile_data = profile_doc.to_dict() or {}
    profile_completion = _calculate_profile_completion(profile_data)
    response = TalentProfileResponse(
        user_uid=profile_data.get("user_uid", current_user.uid),
        display_name=profile_data.get("display_name", current_user.name or ""),
        bio=profile_data.get("bio", ""),
        main_specialty=profile_data.get("main_specialty", ""),
        specialties=_normalize_text_list(profile_data.get("specialties")),
        location=profile_data.get("location", ""),
        experience_years=profile_data.get("experience_years", 0),
        languages=_normalize_text_list(profile_data.get("languages")),
        skills=_normalize_text_list(profile_data.get("skills")),
        portfolio_links=profile_data.get("portfolio_links", []),
        portfolio_items=profile_data.get("portfolio_items", []),
        photo_url=profile_data.get("photo_url") or profile_data.get("picture") or profile_data.get("avatar_url"),
        portfolio_pdf_url=profile_data.get("portfolio_pdf_url"),
        profile_completion=profile_completion,
        is_public=profile_data.get("is_public", False),
        updated_at=profile_data.get("updated_at"),
    )
    print(f"[PERF] talent profile serialize response: {(time.perf_counter() - serialization_start) * 1000:.2f} ms")
    print(f"[PERF] talent profile service total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return response


def upsert_talent_profile(
    current_user: CurrentUser,
    payload: TalentProfileUpsertRequest,
) -> TalentProfileResponse:
    profile_doc_ref = db.collection("talent_profiles").document(current_user.uid)
    existing_profile_doc = profile_doc_ref.get()
    existing_profile_data = existing_profile_doc.to_dict() or {} if existing_profile_doc.exists else {}
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
        "portfolio_items": [item.model_dump() for item in payload.portfolio_items],
        "photo_url": existing_profile_data.get("photo_url"),
        "portfolio_pdf_url": existing_profile_data.get("portfolio_pdf_url"),
        "is_public": payload.is_public,
        "updated_at": utc_now_iso(),
    }
    profile_data["profile_completion"] = _calculate_profile_completion(profile_data)

    profile_doc_ref.set(profile_data, merge=True)
    return TalentProfileResponse(**profile_data)


def update_talent_profile_photo(current_user: CurrentUser, photo_url: str) -> str:
    profile_doc_ref = db.collection("talent_profiles").document(current_user.uid)
    existing_profile_doc = profile_doc_ref.get()
    profile_data = existing_profile_doc.to_dict() or {} if existing_profile_doc.exists else {}
    profile_data.update(
        {
            "user_uid": current_user.uid,
            "photo_url": photo_url,
            "updated_at": utc_now_iso(),
        }
    )
    profile_data["profile_completion"] = _calculate_profile_completion(profile_data)
    profile_doc_ref.set(
        profile_data,
        merge=True,
    )
    return photo_url


def update_talent_profile_portfolio_pdf(current_user: CurrentUser, portfolio_pdf_url: str) -> str:
    profile_doc_ref = db.collection("talent_profiles").document(current_user.uid)
    existing_profile_doc = profile_doc_ref.get()
    profile_data = existing_profile_doc.to_dict() or {} if existing_profile_doc.exists else {}
    profile_data.update(
        {
            "user_uid": current_user.uid,
            "portfolio_pdf_url": portfolio_pdf_url,
            "updated_at": utc_now_iso(),
        }
    )
    profile_data["profile_completion"] = _calculate_profile_completion(profile_data)
    profile_doc_ref.set(profile_data, merge=True)
    return portfolio_pdf_url


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


def _matches_text(value: Any, expected: str | None) -> bool:
    return not expected or _clean_text(expected) in _clean_text(value)


def _matches_any(values: list[Any], expected: str | None) -> bool:
    return not expected or any(_matches_text(value, expected) for value in values)


def _availability_filter(availability: str | None):
    normalized = _clean_text(availability)
    if normalized in {"", "all", "todos", "todas"}:
        return None

    target_status = _normalize_availability_status(availability)
    if target_status == AvailabilityStatus.AVAILABLE:
        values = ["AVAILABLE", "available", "Disponible", "disponible", "Si", "si"]
    else:
        values = ["UNAVAILABLE", "unavailable", "No disponible", "no disponible", "Indisponible", "indisponible"]

    return Or(
        [
            FieldFilter("status", "in", values),
            FieldFilter("availability_status", "in", values),
        ]
    )


def _get_documents_by_id(collection_name: str, document_ids: set[str]) -> dict[str, dict]:
    document_refs = [
        db.collection(collection_name).document(document_id)
        for document_id in document_ids
        if document_id
    ]
    if not document_refs:
        return {}

    start = time.perf_counter()
    documents = {
        doc.id: doc.to_dict() or {}
        for doc in db.get_all(document_refs)
        if doc.exists
    }
    print(
        f"[PERF] talent CRM batch {collection_name} "
        f"(requested={len(document_refs)}, reads={len(documents)}): "
        f"{(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return documents


def _get_crew_project_id(crew_data: dict) -> str | None:
    return (
        crew_data.get("project_id")
        or crew_data.get("projectId")
        or crew_data.get("project_uid")
    )


def _get_crew_opportunity_id(crew_data: dict) -> str | None:
    return crew_data.get("opportunity_id") or crew_data.get("opportunityId")


def _get_crew_user_id(crew_data: dict) -> str | None:
    return (
        crew_data.get("user_uid")
        or crew_data.get("talent_uid")
        or crew_data.get("talent_user_id")
        or crew_data.get("talent_id")
        or crew_data.get("user_id")
    )


def _is_active_crew_member(crew_data: dict) -> bool:
    status = str(crew_data.get("status") or "").strip().upper()
    return status in {"ACTIVE", "ACCEPTED"}


def _is_recruitable_project(project_data: dict) -> bool:
    status = str(project_data.get("status") or "").strip().upper()

    if status in {"CANCELLED", "CANCELED", "CLOSED", "COMPLETED", "FINISHED"}:
        return False

    return True


def _get_assigned_talent_ids() -> set[str]:
    assigned_talent_ids: set[str] = set()
    active_crew_items: list[dict] = []
    project_ids: set[str] = set()

    crew_docs = (
        db.collection("crew_members")
        .where(filter=FieldFilter("status", "in", ["ACTIVE", "ACCEPTED", "active", "accepted"]))
        .limit(MAX_CREW_ASSIGNMENT_CANDIDATES)
        .stream()
    )

    for crew_doc in crew_docs:
        crew_data = crew_doc.to_dict() or {}
        talent_id = _get_crew_user_id(crew_data)
        project_id = _get_crew_project_id(crew_data)

        if not talent_id:
            continue

        if project_id:
            project_ids.add(project_id)

        active_crew_items.append(crew_data)

    projects_by_id = _get_documents_by_id("projects", project_ids)

    for crew_data in active_crew_items:
        talent_id = _get_crew_user_id(crew_data)
        project_id = _get_crew_project_id(crew_data)

        if not talent_id:
            continue

        if not project_id:
            assigned_talent_ids.add(talent_id)
            continue

        project_data = projects_by_id.get(project_id, {})

        if not project_data or _is_recruitable_project(project_data):
            assigned_talent_ids.add(talent_id)

    return assigned_talent_ids


def list_available_talents(
    *,
    search: str | None = None,
    category: str | None = None,
    location: str | None = None,
    language: str | None = None,
    availability: str | None = "AVAILABLE",
    limit: int = 40,
) -> list[AvailableTalentResponse]:
    items: list[AvailableTalentResponse] = []
    assigned_talent_ids = _get_assigned_talent_ids()
    candidate_limit = min(MAX_AVAILABLE_TALENT_CANDIDATES, max(limit * 5, 50))
    query = db.collection("talent_availability")
    availability_filter = _availability_filter(availability)

    if availability_filter is not None:
        query = query.where(filter=availability_filter)

    query = query.order_by("__name__").limit(candidate_limit)

    for availability_doc in query.stream():
        availability_data = availability_doc.to_dict() or {}
        status = _normalize_availability_status(
            availability_data.get("status") or availability_data.get("availability_status")
        )

        if not _matches_text(
            availability_data.get("location") or availability_data.get("work_location"),
            location,
        ):
            continue

        user_id = availability_data.get("user_id") or availability_data.get("user_uid") or availability_doc.id

        if user_id in assigned_talent_ids:
            continue

        user_doc = db.collection("users").document(user_id).get()
        if not user_doc.exists:
            continue

        user_data = user_doc.to_dict() or {}
        if user_data.get("role") != "TALENT":
            continue

        profile_doc = db.collection("talent_profiles").document(user_id).get()
        profile_data = profile_doc.to_dict() or {} if profile_doc.exists else {}
        specialties = _normalize_text_list(profile_data.get("specialties"))
        languages = _normalize_text_list(profile_data.get("languages"))
        skills = _normalize_text_list(profile_data.get("skills"))
        category_values = [
            profile_data.get("main_specialty"),
            *specialties,
            *skills,
        ]
        name_values = [
            user_data.get("name"),
            profile_data.get("display_name"),
        ]

        if not _matches_any(name_values, search):
            continue
        if not _matches_any(category_values, category):
            continue
        if not _matches_any(languages, language):
            continue

        items.append(
            AvailableTalentResponse(
                user_id=user_id,
                name=user_data.get("name", ""),
                email=user_data.get("email", ""),
                picture=profile_data.get("photo_url") or user_data.get("picture") or profile_data.get("picture") or profile_data.get("avatar_url"),
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
                    display_name=profile_data.get("display_name"),
                    main_specialty=profile_data.get("main_specialty"),
                    photo_url=profile_data.get("photo_url"),
                    specialties=specialties,
                    languages=languages,
                    skills=skills,
                    experience_years=profile_data.get("experience_years"),
                    bio=profile_data.get("bio"),
                    portfolio_url=_get_first_portfolio_url(profile_data),
                ),
            )
        )

        if len(items) >= limit:
            break

    return sorted(items, key=lambda item: item.available_from or "")


def list_available_talents_crm(
    *,
    search: str | None = None,
    category: str | None = None,
    location: str | None = None,
    language: str | None = None,
    availability: str | None = "AVAILABLE",
    limit: int = 40,
) -> list[AvailableTalentCrmResponse]:
    start = time.perf_counter()
    assigned_start = time.perf_counter()
    assigned_talent_ids = _get_assigned_talent_ids()
    print(
        "[PERF] talent availability CRM assigned crew filter "
        f"(assigned={len(assigned_talent_ids)}): {(time.perf_counter() - assigned_start) * 1000:.2f} ms"
    )

    candidate_limit = min(MAX_AVAILABLE_TALENT_CANDIDATES, max(limit * 5, 50))
    query = db.collection("talent_availability")
    availability_filter = _availability_filter(availability)
    if availability_filter is not None:
        query = query.where(filter=availability_filter)
    query = query.order_by("__name__").limit(candidate_limit)

    query_start = time.perf_counter()
    availability_rows = [
        (doc.id, doc.to_dict() or {})
        for doc in query.stream()
    ]
    print(
        "[PERF] talent availability CRM availability query "
        f"(reads={len(availability_rows)}, limit={candidate_limit}): "
        f"{(time.perf_counter() - query_start) * 1000:.2f} ms"
    )

    candidate_rows: list[tuple[str, dict]] = []
    for doc_id, availability_data in availability_rows:
        user_id = availability_data.get("user_id") or availability_data.get("user_uid") or doc_id
        if user_id in assigned_talent_ids:
            continue
        if not _matches_text(
            availability_data.get("location") or availability_data.get("work_location"),
            location,
        ):
            continue
        candidate_rows.append((user_id, availability_data))

    candidate_user_ids = {user_id for user_id, _ in candidate_rows}
    users_by_id = _get_documents_by_id("users", candidate_user_ids)
    profiles_by_id = _get_documents_by_id("talent_profiles", candidate_user_ids)

    serialize_start = time.perf_counter()
    items: list[AvailableTalentCrmResponse] = []
    for user_id, availability_data in candidate_rows:
        user_data = users_by_id.get(user_id, {})
        if user_data.get("role") != "TALENT":
            continue

        profile_data = profiles_by_id.get(user_id, {})
        specialties = _normalize_text_list(profile_data.get("specialties"))
        languages = _normalize_text_list(profile_data.get("languages"))
        skills = _normalize_text_list(profile_data.get("skills"))
        category_values = [
            profile_data.get("main_specialty"),
            *specialties,
            *skills,
        ]
        name_values = [
            user_data.get("name"),
            profile_data.get("display_name"),
        ]

        if not _matches_any(name_values, search):
            continue
        if not _matches_any(category_values, category):
            continue
        if not _matches_any(languages, language):
            continue

        items.append(
            AvailableTalentCrmResponse(
                user_id=user_id,
                name=user_data.get("name") or profile_data.get("display_name") or "",
                email=user_data.get("email", ""),
                photo_url=(
                    profile_data.get("photo_url")
                    or user_data.get("photo_url")
                    or user_data.get("picture")
                    or profile_data.get("picture")
                    or profile_data.get("avatar_url")
                ),
                specialty=profile_data.get("main_specialty") or (specialties[0] if specialties else ""),
                location=availability_data.get("location") or availability_data.get("work_location"),
                modality=_normalize_work_modality(
                    availability_data.get("work_modality") or availability_data.get("modality")
                ),
                status=_normalize_availability_status(
                    availability_data.get("status") or availability_data.get("availability_status")
                ),
                available_from=_serialize_available_from(availability_data.get("available_from")),
            )
        )
        if len(items) >= limit:
            break

    items.sort(key=lambda item: item.available_from or "")
    print(
        "[PERF] talent availability CRM serialize "
        f"(items={len(items)}): {(time.perf_counter() - serialize_start) * 1000:.2f} ms"
    )
    print(f"[PERF] talent availability CRM total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return items


def get_talent_availability_commitments(
    current_user: CurrentUser,
) -> TalentCommitmentsResponse:
    commitments: list[TalentCommitmentResponse] = []
    crew_docs = list(
        db.collection("crew_members")
        .where(
            filter=Or(
                [
                    FieldFilter("talent_user_id", "==", current_user.uid),
                    FieldFilter("talent_id", "==", current_user.uid),
                    FieldFilter("talent_uid", "==", current_user.uid),
                    FieldFilter("user_uid", "==", current_user.uid),
                    FieldFilter("user_id", "==", current_user.uid),
                ]
            )
        )
        .limit(MAX_TALENT_COMMITMENT_CANDIDATES)
        .stream()
    )
    crew_items = []
    for crew_doc in crew_docs:
        crew_data = crew_doc.to_dict() or {}
        if _is_active_crew_member(crew_data):
            crew_items.append(crew_data)
    if not crew_items:
        return TalentCommitmentsResponse(commitments=[])

    projects_by_id = _get_documents_by_id(
        "projects",
        {
            project_id
            for crew_data in crew_items
            if (project_id := _get_crew_project_id(crew_data))
        },
    )
    opportunities_by_id = _get_documents_by_id(
        "opportunities",
        {
            opportunity_id
            for crew_data in crew_items
            if (opportunity_id := _get_crew_opportunity_id(crew_data))
        },
    )

    for crew_data in crew_items:
        project_id = _get_crew_project_id(crew_data)
        opportunity_id = _get_crew_opportunity_id(crew_data)
        project_title = crew_data.get("project_title") or crew_data.get("project_name")
        opportunity_title = crew_data.get("opportunity_title")

        start_date = crew_data.get("start_date")
        end_date = crew_data.get("end_date")

        project_data = projects_by_id.get(project_id, {})
        project_title = (
            project_title
            or project_data.get("title")
            or project_data.get("name")
            or project_data.get("project_name")
        )
        start_date = start_date or project_data.get("start_date")
        end_date = end_date or project_data.get("end_date")

        opportunity_data = opportunities_by_id.get(opportunity_id, {})
        opportunity_title = (
            opportunity_title
            or opportunity_data.get("title")
            or opportunity_data.get("name")
        )
        start_date = start_date or opportunity_data.get("start_date")
        end_date = end_date or opportunity_data.get("end_date")

        commitments.append(
            TalentCommitmentResponse(
                project_id=project_id,
                project_title=project_title,
                opportunity_id=opportunity_id,
                opportunity_title=opportunity_title,
                start_date=_serialize_available_from(start_date),
                end_date=_serialize_available_from(end_date),
                status="OCCUPIED",
            )
        )

    return TalentCommitmentsResponse(commitments=commitments)
