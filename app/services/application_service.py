from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import serialize_date, utc_now_iso
from app.schemas.application_schema import (
    ApplicationCreateRequest,
    ApplicationResponse,
    ApplicationStatusUpdateRequest,
    ApplicationStatusUpdateResponse,
    ApplicationTalentProfile,
    ApplicationTalentSummary,
    OpportunityApplicationResponse,
)
from app.schemas.auth_schema import CurrentUser
from app.services.crew_service import create_or_update_crew_member, get_project_summary, get_user_identity
from app.services.opportunity_service import _get_opportunity_owned_by_user, _owner_id_from_data


def _get_talent_user_id(data: dict) -> str:
    return (
        data.get("talent_uid")
        or data.get("talent_user_id")
        or data.get("user_id")
        or data.get("user_uid")
        or data.get("talent_id")
        or ""
    )


def _build_application_id(opportunity_id: str, talent_uid: str) -> str:
    return f"{opportunity_id}_{talent_uid}"


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


def _serialize_opportunity_application(application_id: str, data: dict) -> OpportunityApplicationResponse:
    talent_uid = _get_talent_user_id(data)
    talent = get_user_identity(talent_uid, data)

    profile_data = {}
    if talent_uid:
        profile_doc = db.collection("talent_profiles").document(talent_uid).get()
        if profile_doc.exists:
            profile_data = profile_doc.to_dict() or {}

    return OpportunityApplicationResponse(
        id=data.get("id") or application_id,
        opportunity_id=data.get("opportunity_id", ""),
        status=data.get("status", ""),
        message=data.get("message", ""),
        created_at=serialize_date(data.get("created_at") or data.get("applied_at")),
        talent=ApplicationTalentSummary(
            user_id=talent_uid,
            name=talent.name,
            email=talent.email,
        ),
        profile=ApplicationTalentProfile(
            specialties=profile_data.get("specialties", []),
            skills=profile_data.get("skills", []),
            experience_years=profile_data.get("experience_years"),
            portfolio_url=_get_first_portfolio_url(profile_data),
        ),
    )


def create_application(
    payload: ApplicationCreateRequest,
    current_user: CurrentUser,
) -> ApplicationResponse:
    opportunity_doc = db.collection("opportunities").document(payload.opportunity_id).get()

    if not opportunity_doc.exists:
        raise HTTPException(status_code=404, detail="Convocatoria no encontrada")

    opportunity_data = opportunity_doc.to_dict() or {}
    application_id = _build_application_id(payload.opportunity_id, current_user.uid)
    application_ref = db.collection("applications").document(application_id)

    if application_ref.get().exists:
        raise HTTPException(status_code=400, detail="Ya postulaste a esta convocatoria")

    timestamp = utc_now_iso()
    application_data = {
        "id": application_id,
        "opportunity_id": payload.opportunity_id,
        "project_id": opportunity_data.get("project_id"),
        "producer_uid": _owner_id_from_data(opportunity_data),
        "talent_uid": current_user.uid,
        "talent_user_id": current_user.uid,
        "talent_name": current_user.name,
        "talent_email": current_user.email,
        "message": payload.message,
        "status": "SUBMITTED",
        "applied_at": timestamp,
        "updated_at": timestamp,
    }

    application_ref.set(application_data)
    return ApplicationResponse(**application_data)


def _serialize_my_application(application_id: str, data: dict) -> ApplicationResponse:
    opportunity_id = data.get("opportunity_id", "")
    project_id = data.get("project_id")
    opportunity_summary = None

    if opportunity_id:
        opportunity_doc = db.collection("opportunities").document(opportunity_id).get()
        if opportunity_doc.exists:
            opportunity_data = opportunity_doc.to_dict() or {}
            project_id = project_id or opportunity_data.get("project_id")
            opportunity_summary = {
                "id": opportunity_data.get("id") or opportunity_doc.id,
                "title": opportunity_data.get("title", ""),
                "status": opportunity_data.get("status"),
            }

    project_summary = get_project_summary(project_id)

    return ApplicationResponse(
        id=data.get("id") or application_id,
        opportunity_id=opportunity_id,
        project_id=project_id,
        producer_uid=data.get("producer_uid", ""),
        talent_uid=_get_talent_user_id(data),
        talent_name=data.get("talent_name", ""),
        talent_email=data.get("talent_email", ""),
        message=data.get("message", ""),
        status=data.get("status", "SUBMITTED"),
        applied_at=serialize_date(data.get("applied_at") or data.get("created_at")) or "",
        updated_at=serialize_date(data.get("updated_at")) or "",
        opportunity=opportunity_summary,
        project=project_summary.model_dump() if project_summary else None,
    )


def list_my_applications(current_user: CurrentUser) -> list[ApplicationResponse]:
    items_by_id: dict[str, ApplicationResponse] = {}

    for talent_field in ("talent_uid", "talent_user_id", "user_id", "user_uid", "talent_id"):
        query = db.collection("applications").where(talent_field, "==", current_user.uid)
        for doc in query.stream():
            items_by_id[doc.id] = _serialize_my_application(doc.id, doc.to_dict() or {})

    items = list(items_by_id.values())
    return sorted(items, key=lambda item: item.applied_at, reverse=True)


def list_opportunity_applications(
    opportunity_id: str,
    current_user: CurrentUser,
) -> list[OpportunityApplicationResponse]:
    _get_opportunity_owned_by_user(opportunity_id, current_user)

    query = db.collection("applications").where("opportunity_id", "==", opportunity_id)
    items = [_serialize_opportunity_application(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at or "", reverse=True)


def update_application_status(
    application_id: str,
    payload: ApplicationStatusUpdateRequest,
    current_user: CurrentUser,
) -> ApplicationStatusUpdateResponse:
    application_doc = db.collection("applications").document(application_id).get()

    if not application_doc.exists:
        raise HTTPException(status_code=404, detail="Postulacion no encontrada")

    application_data = application_doc.to_dict() or {}
    opportunity_id = application_data.get("opportunity_id")
    if not opportunity_id:
        raise HTTPException(status_code=400, detail="La postulacion no tiene convocatoria asociada")

    opportunity_doc = _get_opportunity_owned_by_user(opportunity_id, current_user)
    opportunity_data = opportunity_doc.to_dict() or {}

    updated_at = utc_now_iso()
    application_doc.reference.update(
        {
            "status": payload.status.value,
            "updated_at": updated_at,
        }
    )

    if payload.status.value == "ACCEPTED":
        talent_user_id = _get_talent_user_id(application_data)
        if not talent_user_id:
            raise HTTPException(status_code=400, detail="La postulacion no tiene talento asociado")

        create_or_update_crew_member(
            producer_id=current_user.uid,
            talent_user_id=talent_user_id,
            project_id=opportunity_data.get("project_id") or application_data.get("project_id"),
            opportunity_id=opportunity_id,
            application_id=application_data.get("id") or application_doc.id,
            recruitment_id=None,
            source="APPLICATION",
            role=opportunity_data.get("title") or opportunity_data.get("role_needed"),
            task_description=opportunity_data.get("description") or application_data.get("message"),
            producer_note=None,
        )

    return ApplicationStatusUpdateResponse(
        id=application_data.get("id") or application_doc.id,
        status=payload.status,
        updated_at=updated_at,
    )
