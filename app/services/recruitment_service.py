from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import serialize_date, utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.recruitment_schema import (
    RecruitmentCreateRequest,
    RecruitmentInvitationResponse,
    RecruitmentOpportunitySummary,
    RecruitmentProducerSummary,
    RecruitmentProjectSummary,
    RecruitmentResponse,
    RecruitmentStatusUpdateRequest,
)
from app.services.crew_service import create_or_update_crew_member
from app.services.opportunity_service import _get_opportunity_owned_by_user, _is_owned_by_current_user


def _get_project_owned_by_user(project_id: str, current_user: CurrentUser) -> dict:
    project_doc = db.collection("projects").document(project_id).get()

    if not project_doc.exists:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    project_data = project_doc.to_dict() or {}
    if not _is_owned_by_current_user(project_data, current_user):
        raise HTTPException(status_code=403, detail="No tienes permisos sobre este proyecto")

    return project_data


def _get_opportunity_for_project_owned_by_user(
    opportunity_id: str,
    project_id: str,
    current_user: CurrentUser,
) -> dict:
    opportunity_doc = _get_opportunity_owned_by_user(opportunity_id, current_user)
    opportunity_data = opportunity_doc.to_dict() or {}

    if opportunity_data.get("project_id") != project_id:
        raise HTTPException(
            status_code=400,
            detail="La convocatoria no pertenece al proyecto indicado",
        )

    return opportunity_data


def _validate_talent_user(talent_user_id: str) -> None:
    user_doc = db.collection("users").document(talent_user_id).get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="Talento no encontrado")

    user_data = user_doc.to_dict() or {}
    if user_data.get("role") != "TALENT":
        raise HTTPException(status_code=400, detail="El usuario seleccionado no es TALENT")


def _serialize_recruitment(recruitment_id: str, data: dict) -> RecruitmentResponse:
    return RecruitmentResponse(
        id=data.get("id") or recruitment_id,
        producer_id=data.get("producer_id", ""),
        talent_user_id=data.get("talent_user_id", ""),
        project_id=data.get("project_id"),
        opportunity_id=data.get("opportunity_id"),
        role=data.get("role"),
        message=data.get("message", ""),
        status=data.get("status", "PENDING"),
        created_at=serialize_date(data.get("created_at")) or "",
        updated_at=serialize_date(data.get("updated_at")) or "",
    )


def _project_summary(project_id: str | None) -> RecruitmentProjectSummary | None:
    if not project_id:
        return None

    project_doc = db.collection("projects").document(project_id).get()
    if not project_doc.exists:
        return None

    project_data = project_doc.to_dict() or {}
    return RecruitmentProjectSummary(
        id=project_data.get("id") or project_doc.id,
        title=project_data.get("title", ""),
        status=project_data.get("status"),
    )


def _opportunity_summary(opportunity_id: str | None) -> RecruitmentOpportunitySummary | None:
    if not opportunity_id:
        return None

    opportunity_doc = db.collection("opportunities").document(opportunity_id).get()
    if not opportunity_doc.exists:
        return None

    opportunity_data = opportunity_doc.to_dict() or {}
    return RecruitmentOpportunitySummary(
        id=opportunity_data.get("id") or opportunity_doc.id,
        title=opportunity_data.get("title", ""),
        status=opportunity_data.get("status"),
    )


def _producer_summary(producer_id: str | None) -> RecruitmentProducerSummary | None:
    if not producer_id:
        return None

    producer_doc = db.collection("users").document(producer_id).get()
    if not producer_doc.exists:
        return None

    producer_data = producer_doc.to_dict() or {}
    return RecruitmentProducerSummary(
        user_id=producer_id,
        name=producer_data.get("name", ""),
        email=producer_data.get("email", ""),
    )


def _serialize_invitation(recruitment_id: str, data: dict) -> RecruitmentInvitationResponse:
    recruitment = _serialize_recruitment(recruitment_id, data)
    return RecruitmentInvitationResponse(
        **recruitment.model_dump(),
        project=_project_summary(recruitment.project_id),
        opportunity=_opportunity_summary(recruitment.opportunity_id),
        producer=_producer_summary(recruitment.producer_id),
    )


def create_recruitment(
    payload: RecruitmentCreateRequest,
    current_user: CurrentUser,
) -> RecruitmentResponse:
    _validate_talent_user(payload.talent_user_id)
    _get_project_owned_by_user(payload.project_id, current_user)
    if payload.opportunity_id:
        _get_opportunity_for_project_owned_by_user(payload.opportunity_id, payload.project_id, current_user)

    recruitment_ref = db.collection("recruitments").document()
    timestamp = utc_now_iso()
    recruitment_data = {
        "id": recruitment_ref.id,
        "producer_id": current_user.uid,
        "talent_user_id": payload.talent_user_id,
        "project_id": payload.project_id,
        "opportunity_id": payload.opportunity_id or None,
        "role": payload.role,
        "message": payload.message,
        "status": "PENDING",
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    recruitment_ref.set(recruitment_data)
    return RecruitmentResponse(**recruitment_data)


def list_my_recruitments(current_user: CurrentUser) -> list[RecruitmentInvitationResponse]:
    query = db.collection("recruitments").where("talent_user_id", "==", current_user.uid)
    items = [_serialize_invitation(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at, reverse=True)


def update_my_recruitment_status(
    recruitment_id: str,
    payload: RecruitmentStatusUpdateRequest,
    current_user: CurrentUser,
) -> RecruitmentResponse:
    recruitment_doc = db.collection("recruitments").document(recruitment_id).get()

    if not recruitment_doc.exists:
        raise HTTPException(status_code=404, detail="Invitacion no encontrada")

    recruitment_data = recruitment_doc.to_dict() or {}
    if recruitment_data.get("talent_user_id") != current_user.uid:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre esta invitacion")

    updated_data = {
        **recruitment_data,
        "id": recruitment_data.get("id") or recruitment_doc.id,
        "status": payload.status.value,
        "updated_at": utc_now_iso(),
    }

    recruitment_doc.reference.set(updated_data)

    if payload.status.value == "ACCEPTED":
        opportunity_id = recruitment_data.get("opportunity_id")

        create_or_update_crew_member(
            producer_id=recruitment_data.get("producer_id", ""),
            talent_user_id=current_user.uid,
            project_id=recruitment_data.get("project_id"),
            opportunity_id=opportunity_id,
            application_id=None,
            recruitment_id=recruitment_data.get("id") or recruitment_doc.id,
            source="RECRUITMENT",
            role=recruitment_data.get("role"),
            task_description=recruitment_data.get("message"),
            producer_note=None,
        )

    return _serialize_recruitment(recruitment_doc.id, updated_data)
