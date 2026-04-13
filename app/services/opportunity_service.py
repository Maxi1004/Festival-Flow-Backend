from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import serialize_date, utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.opportunity_schema import (
    OpportunityCreateRequest,
    OpportunityResponse,
    OpportunityStatusUpdateRequest,
    OpportunityUpdateRequest,
)


def _to_iso(value):
    return serialize_date(value)


def _serialize_opportunity(opportunity_id: str, data: dict) -> OpportunityResponse:
    return OpportunityResponse(
        id=data.get("id") or opportunity_id,
        project_id=data.get("project_id"),
        owner_uid=data.get("owner_uid", ""),
        title=data.get("title", ""),
        role_needed=data.get("role_needed", ""),
        specialty=data.get("specialty", ""),
        description=data.get("description", ""),
        location=data.get("location", ""),
        modality=data.get("modality", ""),
        requirements=data.get("requirements", []),
        status=data.get("status", ""),
        deadline=_to_iso(data.get("deadline")),
        created_at=_to_iso(data.get("created_at")),
        updated_at=_to_iso(data.get("updated_at")),
    )


def list_opportunities(
    specialty: str | None = None,
    location: str | None = None,
    modality: str | None = None,
    status: str | None = None,
) -> list[OpportunityResponse]:
    query = db.collection("opportunities")

    if specialty:
        query = query.where("specialty", "==", specialty)
    if location:
        query = query.where("location", "==", location)
    if modality:
        query = query.where("modality", "==", modality)
    if status:
        query = query.where("status", "==", status)

    items = [_serialize_opportunity(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at or "", reverse=True)


def get_opportunity_by_id(opportunity_id: str) -> OpportunityResponse:
    opportunity_doc = db.collection("opportunities").document(opportunity_id).get()

    if not opportunity_doc.exists:
        raise HTTPException(status_code=404, detail="Convocatoria no encontrada")

    return _serialize_opportunity(opportunity_doc.id, opportunity_doc.to_dict() or {})


def _get_project_owned_by_user(project_id: str, current_user: CurrentUser) -> dict:
    project_doc = db.collection("projects").document(project_id).get()

    if not project_doc.exists:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    project_data = project_doc.to_dict() or {}

    if project_data.get("owner_uid") != current_user.uid:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre este proyecto")

    return project_data


def _get_opportunity_owned_by_user(opportunity_id: str, current_user: CurrentUser):
    opportunity_doc = db.collection("opportunities").document(opportunity_id).get()

    if not opportunity_doc.exists:
        raise HTTPException(status_code=404, detail="Convocatoria no encontrada")

    opportunity_data = opportunity_doc.to_dict() or {}

    if opportunity_data.get("owner_uid") != current_user.uid:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre esta convocatoria")

    return opportunity_doc


def create_opportunity(
    payload: OpportunityCreateRequest,
    current_user: CurrentUser,
) -> OpportunityResponse:
    _get_project_owned_by_user(payload.project_id, current_user)
    opportunity_ref = db.collection("opportunities").document()
    timestamp = utc_now_iso()
    opportunity_data = {
        "id": opportunity_ref.id,
        "project_id": payload.project_id,
        "owner_uid": current_user.uid,
        "title": payload.title,
        "role_needed": payload.role_needed,
        "specialty": payload.specialty,
        "description": payload.description,
        "location": payload.location,
        "modality": payload.modality,
        "requirements": payload.requirements,
        "status": payload.status,
        "deadline": serialize_date(payload.deadline),
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    opportunity_ref.set(opportunity_data)
    return OpportunityResponse(**opportunity_data)


def list_my_opportunities(current_user: CurrentUser) -> list[OpportunityResponse]:
    query = db.collection("opportunities").where("owner_uid", "==", current_user.uid)
    items = [_serialize_opportunity(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at or "", reverse=True)


def update_my_opportunity(
    opportunity_id: str,
    payload: OpportunityUpdateRequest,
    current_user: CurrentUser,
) -> OpportunityResponse:
    opportunity_doc = _get_opportunity_owned_by_user(opportunity_id, current_user)
    existing_data = opportunity_doc.to_dict() or {}
    updated_data = {
        "id": existing_data.get("id") or opportunity_doc.id,
        "project_id": existing_data.get("project_id"),
        "owner_uid": current_user.uid,
        "title": payload.title,
        "role_needed": payload.role_needed,
        "specialty": payload.specialty,
        "description": payload.description,
        "location": payload.location,
        "modality": payload.modality,
        "requirements": payload.requirements,
        "status": payload.status,
        "deadline": serialize_date(payload.deadline),
        "created_at": existing_data.get("created_at"),
        "updated_at": utc_now_iso(),
    }

    opportunity_doc.reference.set(updated_data)
    return OpportunityResponse(**updated_data)


def update_my_opportunity_status(
    opportunity_id: str,
    payload: OpportunityStatusUpdateRequest,
    current_user: CurrentUser,
) -> OpportunityResponse:
    opportunity_doc = _get_opportunity_owned_by_user(opportunity_id, current_user)
    existing_data = opportunity_doc.to_dict() or {}
    updated_data = {
        **existing_data,
        "id": existing_data.get("id") or opportunity_doc.id,
        "status": payload.status,
        "updated_at": utc_now_iso(),
    }

    opportunity_doc.reference.set(updated_data)
    return _serialize_opportunity(opportunity_doc.id, updated_data)
