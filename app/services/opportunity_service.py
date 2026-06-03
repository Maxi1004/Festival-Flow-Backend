import time

from fastapi import HTTPException
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import db
from app.core.utils import serialize_date, utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.opportunity_schema import (
    OpportunityCreateRequest,
    OpportunityCrmResponse,
    OpportunityResponse,
    OpportunityStatusUpdateRequest,
    OpportunityUpdateRequest,
)


def _perf_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


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


def _serialize_opportunity(
    opportunity_id: str,
    data: dict,
    applications_count: int | None = None,
) -> OpportunityResponse:
    owner_id = _owner_id_from_data(data)
    resolved_applications_count = (
        applications_count
        if applications_count is not None
        else int(data.get("applications_count") or data.get("applicants_count") or 0)
    )
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
        applications_count=resolved_applications_count,
        applicants_count=resolved_applications_count,
        deadline=_to_iso(data.get("deadline")),
        created_at=_to_iso(data.get("created_at")),
        updated_at=_to_iso(data.get("updated_at")),
    )


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


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
        f"[PERF] opportunities CRM batch {collection_name} "
        f"(requested={len(document_refs)}, reads={len(documents)}): {_perf_ms(start):.2f} ms"
    )
    return documents


def _application_counts_for_opportunities(
    opportunity_ids: set[str],
    current_user: CurrentUser,
) -> dict[str, int]:
    if not opportunity_ids:
        return {}

    counts: dict[str, int] = {opportunity_id: 0 for opportunity_id in opportunity_ids}
    counted_application_ids: set[str] = set()

    producer_start = time.perf_counter()
    producer_query = db.collection("applications").where(
        filter=FieldFilter("producer_uid", "==", current_user.uid)
    ).select(["opportunity_id"])
    for doc in producer_query.stream():
        data = doc.to_dict() or {}
        opportunity_id = data.get("opportunity_id")
        if opportunity_id in counts and doc.id not in counted_application_ids:
            counts[opportunity_id] += 1
            counted_application_ids.add(doc.id)
    print(
        "[PERF] opportunities CRM applications producer count "
        f"(matched={len(counted_application_ids)}): {_perf_ms(producer_start):.2f} ms"
    )

    fallback_start = time.perf_counter()
    fallback_reads = 0
    for opportunity_id_chunk in _chunks(list(opportunity_ids), 30):
        fallback_query = db.collection("applications").where(
            filter=FieldFilter("opportunity_id", "in", opportunity_id_chunk)
        ).select(["opportunity_id"])
        for doc in fallback_query.stream():
            fallback_reads += 1
            if doc.id in counted_application_ids:
                continue
            data = doc.to_dict() or {}
            opportunity_id = data.get("opportunity_id")
            if opportunity_id in counts:
                counts[opportunity_id] += 1
                counted_application_ids.add(doc.id)
    print(
        "[PERF] opportunities CRM applications fallback count "
        f"(chunks={len(_chunks(list(opportunity_ids), 30))}, reads={fallback_reads}): {_perf_ms(fallback_start):.2f} ms"
    )

    return counts


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
    opportunity_data_by_id: dict[str, dict] = {}

    for owner_field in ("owner_uid", "created_by", "producer_id", "owner_id", "user_id"):
        query = db.collection("opportunities").where(owner_field, "==", current_user.uid)
        for doc in query.stream():
            opportunity_data_by_id[doc.id] = doc.to_dict() or {}

    counts_by_opportunity_id = _application_counts_for_opportunities(
        set(opportunity_data_by_id),
        current_user,
    )
    items = [
        _serialize_opportunity(
            opportunity_id,
            data,
            counts_by_opportunity_id.get(opportunity_id, 0),
        )
        for opportunity_id, data in opportunity_data_by_id.items()
    ]
    return sorted(items, key=lambda item: item.created_at or "", reverse=True)


def _list_my_opportunity_data(current_user: CurrentUser) -> dict[str, dict]:
    start = time.perf_counter()
    opportunity_data_by_id: dict[str, dict] = {}

    for owner_field in ("owner_uid", "created_by", "producer_id", "owner_id", "user_id"):
        query_start = time.perf_counter()
        query = db.collection("opportunities").where(owner_field, "==", current_user.uid)
        docs = list(query.stream())
        print(
            f"[PERF] opportunities CRM owner query {owner_field} "
            f"(reads={len(docs)}): {_perf_ms(query_start):.2f} ms"
        )
        for doc in docs:
            opportunity_data_by_id[doc.id] = doc.to_dict() or {}

    print(
        "[PERF] opportunities CRM owner queries total "
        f"(items={len(opportunity_data_by_id)}): {_perf_ms(start):.2f} ms"
    )
    return opportunity_data_by_id


def list_my_opportunities_crm(current_user: CurrentUser) -> list[OpportunityCrmResponse]:
    start = time.perf_counter()
    opportunity_data_by_id = _list_my_opportunity_data(current_user)
    counts_by_opportunity_id = _application_counts_for_opportunities(
        set(opportunity_data_by_id),
        current_user,
    )
    projects_by_id = _get_documents_by_id(
        "projects",
        {
            data.get("project_id")
            for data in opportunity_data_by_id.values()
            if data.get("project_id")
        },
    )
    serialize_start = time.perf_counter()
    items = [
        OpportunityCrmResponse(
            id=data.get("id") or opportunity_id,
            project_id=data.get("project_id"),
            project_title=projects_by_id.get(data.get("project_id"), {}).get("title", ""),
            title=data.get("title", ""),
            role_needed=data.get("role_needed", ""),
            specialty=data.get("specialty", ""),
            status=_normalize_status(data.get("status")),
            applications_count=counts_by_opportunity_id.get(opportunity_id, 0),
            applicants_count=counts_by_opportunity_id.get(opportunity_id, 0),
            deadline=_to_iso(data.get("deadline")),
            created_at=_to_iso(data.get("created_at")),
            updated_at=_to_iso(data.get("updated_at")),
        )
        for opportunity_id, data in opportunity_data_by_id.items()
    ]
    items.sort(key=lambda item: item.created_at or "", reverse=True)
    print(f"[PERF] opportunities CRM serialize: {_perf_ms(serialize_start):.2f} ms")
    print(f"[PERF] opportunities CRM total: {_perf_ms(start):.2f} ms")
    return items


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
