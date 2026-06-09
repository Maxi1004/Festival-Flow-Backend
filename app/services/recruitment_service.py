from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
import time

from fastapi import HTTPException
from google.cloud.firestore_v1 import Query
from google.cloud.firestore_v1.base_query import FieldFilter

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
    TalentRecruitmentFeedItem,
    TalentRecruitmentFeedResponse,
    TalentRecruitmentFeedSummary,
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
        f"[PERF] recruitments feed Firestore batch {collection_name} "
        f"(requested={len(document_refs)}, reads={len(documents)}): "
        f"{(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return documents


def _extract_count(result) -> int | None:
    if result is None:
        return None
    if isinstance(result, (int, float)):
        return int(result)
    if isinstance(result, Mapping):
        for value in result.values():
            if (count := _extract_count(value)) is not None:
                return count
        return None
    if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
        for item in result:
            if (count := _extract_count(item)) is not None:
                return count
        return None
    for attribute in ("value", "total", "count"):
        if hasattr(result, attribute):
            if (count := _extract_count(getattr(result, attribute))) is not None:
                return count
    try:
        return int(result)
    except (TypeError, ValueError):
        return None


def _count_query(query, label: str) -> int:
    start = time.perf_counter()
    count = _extract_count(query.count(alias="total").get()) or 0
    print(
        f"[PERF] recruitments feed Firestore count {label} "
        f"(result={count}): {(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return count


def _get_my_recruitment_summary(query) -> TalentRecruitmentFeedSummary:
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            "total": executor.submit(_count_query, query, "total"),
            "pending": executor.submit(_count_query, query.where(filter=FieldFilter("status", "==", "PENDING")), "pending"),
            "accepted": executor.submit(_count_query, query.where(filter=FieldFilter("status", "==", "ACCEPTED")), "accepted"),
            "rejected": executor.submit(_count_query, query.where(filter=FieldFilter("status", "==", "REJECTED")), "rejected"),
            "cancelled": executor.submit(_count_query, query.where(filter=FieldFilter("status", "==", "CANCELLED")), "cancelled"),
        }
        counts = {label: future.result() for label, future in futures.items()}

    summary = TalentRecruitmentFeedSummary(**counts)
    print(f"[PERF] recruitments feed summary total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return summary


def get_my_recruitment_summary(current_user: CurrentUser) -> TalentRecruitmentFeedSummary:
    query = db.collection("recruitments").where("talent_uid", "==", current_user.uid)
    return _get_my_recruitment_summary(query)


def _serialize_recruitment_feed_item(
    recruitment_id: str,
    data: dict,
    projects_by_id: dict[str, dict],
    opportunities_by_id: dict[str, dict],
    producers_by_id: dict[str, dict],
) -> TalentRecruitmentFeedItem:
    project_data = projects_by_id.get(data.get("project_id"), {})
    opportunity_data = opportunities_by_id.get(data.get("opportunity_id"), {})
    producer_uid = data.get("producer_uid") or data.get("producer_id", "")
    producer_data = producers_by_id.get(producer_uid, {})

    return TalentRecruitmentFeedItem(
        id=data.get("id") or recruitment_id,
        project_id=data.get("project_id"),
        project_title=data.get("project_title") or project_data.get("title", ""),
        opportunity_id=data.get("opportunity_id"),
        opportunity_title=data.get("opportunity_title") or opportunity_data.get("title", ""),
        producer_uid=producer_uid,
        producer_name=data.get("producer_name") or producer_data.get("name", ""),
        role=data.get("role"),
        category=data.get("category") or opportunity_data.get("specialty") or "",
        message=data.get("message", ""),
        status=data.get("status", "PENDING"),
        created_at=serialize_date(data.get("created_at")) or "",
        updated_at=serialize_date(data.get("updated_at")) or "",
    )


def list_my_recruitment_feed(
    current_user: CurrentUser,
    limit: int = 10,
    cursor: str | None = None,
    include_summary: bool = True,
) -> TalentRecruitmentFeedResponse:
    start = time.perf_counter()
    recruitments = db.collection("recruitments")
    base_query = recruitments.where("talent_uid", "==", current_user.uid)
    page_query = (
        base_query
        .order_by("created_at", direction=Query.DESCENDING)
        .order_by("__name__", direction=Query.DESCENDING)
    )

    if cursor:
        cursor_doc = recruitments.document(cursor).get()
        cursor_data = cursor_doc.to_dict() or {} if cursor_doc.exists else {}
        if not cursor_doc.exists or cursor_data.get("talent_uid") != current_user.uid:
            raise HTTPException(status_code=400, detail="Cursor de invitaciones invalido")
        page_query = page_query.start_after(cursor_doc)

    page_start = time.perf_counter()
    docs = list(page_query.limit(limit + 1).stream())
    print(
        "[PERF] recruitments feed Firestore page query "
        f"(reads={len(docs)}, limit={limit + 1}): {(time.perf_counter() - page_start) * 1000:.2f} ms"
    )
    page_docs = docs[:limit]
    page_data = [(doc, doc.to_dict() or {}) for doc in page_docs]
    projects_by_id = _get_documents_by_id(
        "projects",
        {data.get("project_id") for _, data in page_data if data.get("project_id") and not data.get("project_title")},
    )
    opportunities_by_id = _get_documents_by_id(
        "opportunities",
        {
            data.get("opportunity_id")
            for _, data in page_data
            if data.get("opportunity_id") and (not data.get("opportunity_title") or not data.get("category"))
        },
    )
    producers_by_id = _get_documents_by_id(
        "users",
        {
            data.get("producer_uid") or data.get("producer_id")
            for _, data in page_data
            if (data.get("producer_uid") or data.get("producer_id")) and not data.get("producer_name")
        },
    )
    items = [
        _serialize_recruitment_feed_item(doc.id, data, projects_by_id, opportunities_by_id, producers_by_id)
        for doc, data in page_data
    ]
    summary = _get_my_recruitment_summary(base_query) if include_summary else None
    if not include_summary:
        print("[PERF] recruitments feed summary skipped")
    response = TalentRecruitmentFeedResponse(
        items=items,
        next_cursor=page_docs[-1].id if len(docs) > limit and page_docs else None,
        summary=summary,
    )
    print(f"[PERF] recruitments feed service total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return response


def create_recruitment(
    payload: RecruitmentCreateRequest,
    current_user: CurrentUser,
) -> RecruitmentResponse:
    _validate_talent_user(payload.talent_user_id)
    project_data = _get_project_owned_by_user(payload.project_id, current_user)
    opportunity_data = {}
    if payload.opportunity_id:
        opportunity_data = _get_opportunity_for_project_owned_by_user(payload.opportunity_id, payload.project_id, current_user)

    recruitment_ref = db.collection("recruitments").document()
    timestamp = utc_now_iso()
    recruitment_data = {
        "id": recruitment_ref.id,
        "producer_id": current_user.uid,
        "producer_uid": current_user.uid,
        "producer_name": current_user.name,
        "talent_user_id": payload.talent_user_id,
        "talent_uid": payload.talent_user_id,
        "project_id": payload.project_id,
        "project_title": project_data.get("title", ""),
        "opportunity_id": payload.opportunity_id or None,
        "opportunity_title": opportunity_data.get("title", ""),
        "category": opportunity_data.get("specialty", ""),
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
            role=payload.role or recruitment_data.get("role"),
            category=payload.category or recruitment_data.get("category"),
            specialty=recruitment_data.get("specialty"),
            task_description=payload.task_description or recruitment_data.get("message"),
            producer_note=None,
            project_title=recruitment_data.get("project_title"),
            opportunity_title=recruitment_data.get("opportunity_title"),
            producer_name=recruitment_data.get("producer_name"),
        )

    return _serialize_recruitment(recruitment_doc.id, updated_data)
