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


def _normalize_status(status: str | None, default: str = "ACTIVE") -> str:
    return (status or default).strip().upper()


def _owner_id_from_data(data: dict) -> str:
    return (
        data.get("owner_uid")
        or data.get("created_by")
        or data.get("producer_id")
        or data.get("owner_id")
        or data.get("user_id")
        or ""
    )


def _is_owned_by_current_user(data: dict, current_user: CurrentUser) -> bool:
    return current_user.uid in {
        data.get("owner_uid"),
        data.get("created_by"),
        data.get("producer_id"),
        data.get("owner_id"),
        data.get("user_id"),
    }


def _serialize_opportunity(opportunity_id: str, data: dict) -> OpportunityResponse:
    owner_id = _owner_id_from_data(data)
    return OpportunityResponse(
        id=data.get("id") or opportunity_id,
        project_id=data.get("project_id"),
        owner_uid=data.get("owner_uid") or owner_id,
        created_by=data.get("created_by") or owner_id,
        producer_id=data.get("producer_id") or owner_id,
        title=data.get("title", ""),
        role_needed=data.get("role_needed", ""),
        specialty=data.get("specialty", ""),
        description=data.get("description", ""),
        location=data.get("location", ""),
        modality=data.get("modality", ""),
        requirements=data.get("requirements", []),
        status=_normalize_status(data.get("status")),
        deadline=_to_iso(data.get("deadline")),
        created_at=_to_iso(data.get("created_at")),
        updated_at=_to_iso(data.get("updated_at")),
    )


def list_opportunities(
    specialty: str | None = None,
    location: str | None = None,
    modality: str | None = None,
    status: str | None = None,
    limit: int = 10,
    cursor: str | None = None,
) -> dict:
    query = db.collection("opportunities")
    requested_status = _normalize_status(status)

    if specialty:
        query = query.where("specialty", "==", specialty)
    if location:
        query = query.where("location", "==", location)
    if modality:
        query = query.where("modality", "==", modality)

    query = query.where("status", "==", requested_status)
    query = query.order_by("__name__")

    if cursor:
        cursor_doc = db.collection("opportunities").document(cursor).get()
        if cursor_doc.exists:
            query = query.start_after(cursor_doc)

    docs = list(query.limit(limit + 1).stream())

    has_more = len(docs) > limit
    page_docs = docs[:limit]

    items = [
        _serialize_opportunity(doc.id, doc.to_dict() or {})
        for doc in page_docs
    ]

    return {
        "items": items,
        "next_cursor": page_docs[-1].id if has_more and page_docs else None,
    }

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

    if not _is_owned_by_current_user(project_data, current_user):
        raise HTTPException(status_code=403, detail="No tienes permisos sobre este proyecto")

    return project_data


def _get_opportunity_owned_by_user(opportunity_id: str, current_user: CurrentUser):
    opportunity_doc = db.collection("opportunities").document(opportunity_id).get()

    if not opportunity_doc.exists:
        raise HTTPException(status_code=404, detail="Convocatoria no encontrada")

    opportunity_data = opportunity_doc.to_dict() or {}

    if not _is_owned_by_current_user(opportunity_data, current_user):
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
        "created_by": current_user.uid,
        "producer_id": current_user.uid,
        "title": payload.title,
        "role_needed": payload.role_needed,
        "specialty": payload.specialty,
        "description": payload.description,
        "location": payload.location,
        "modality": payload.modality,
        "requirements": payload.requirements,
        "status": _normalize_status(payload.status),
        "deadline": serialize_date(payload.deadline),
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    opportunity_ref.set(opportunity_data)
    return OpportunityResponse(**opportunity_data)


def list_my_opportunities(current_user: CurrentUser) -> list[OpportunityResponse]:
    items_by_id: dict[str, OpportunityResponse] = {}

    for owner_field in ("owner_uid", "created_by", "producer_id", "owner_id", "user_id"):
        query = db.collection("opportunities").where(owner_field, "==", current_user.uid)
        for doc in query.stream():
            items_by_id[doc.id] = _serialize_opportunity(doc.id, doc.to_dict() or {})

    items = list(items_by_id.values())
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
        "created_by": existing_data.get("created_by") or current_user.uid,
        "producer_id": existing_data.get("producer_id") or current_user.uid,
        "title": payload.title,
        "role_needed": payload.role_needed,
        "specialty": payload.specialty,
        "description": payload.description,
        "location": payload.location,
        "modality": payload.modality,
        "requirements": payload.requirements,
        "status": _normalize_status(payload.status),
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
        "owner_uid": existing_data.get("owner_uid") or current_user.uid,
        "created_by": existing_data.get("created_by") or current_user.uid,
        "producer_id": existing_data.get("producer_id") or current_user.uid,
        "status": _normalize_status(payload.status),
        "updated_at": utc_now_iso(),
    }

    opportunity_doc.reference.set(updated_data)
    return _serialize_opportunity(opportunity_doc.id, updated_data)
