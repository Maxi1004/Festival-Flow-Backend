from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
import time

from fastapi import HTTPException
from google.cloud.firestore_v1 import Query
from google.cloud.firestore_v1.base_query import FieldFilter, Or

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
    TalentApplicationFeedItem,
    TalentApplicationFeedResponse,
    TalentApplicationFeedSummary,
)
from app.schemas.auth_schema import CurrentUser
from app.services.crew_service import create_or_update_crew_member, get_user_identity
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


def _talent_filter(talent_uid: str) -> Or:
    return Or(
        [
            FieldFilter("talent_uid", "==", talent_uid),
            FieldFilter("talent_user_id", "==", talent_uid),
            FieldFilter("user_id", "==", talent_uid),
            FieldFilter("user_uid", "==", talent_uid),
            FieldFilter("talent_id", "==", talent_uid),
        ]
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
        f"[PERF] applications feed Firestore batch {collection_name} "
        f"(requested={len(document_refs)}, reads={len(documents)}): "
        f"{(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return documents


def _serialize_my_application(
    application_id: str,
    data: dict,
    opportunities_by_id: dict[str, dict],
    projects_by_id: dict[str, dict],
) -> ApplicationResponse:
    opportunity_id = data.get("opportunity_id", "")
    project_id = data.get("project_id")
    opportunity_summary = None

    if opportunity_id:
        opportunity_data = opportunities_by_id.get(opportunity_id)
        if opportunity_data is not None:
            project_id = project_id or opportunity_data.get("project_id")
            opportunity_summary = {
                "id": opportunity_data.get("id") or opportunity_id,
                "title": opportunity_data.get("title", ""),
                "status": opportunity_data.get("status"),
            }

    project_summary = None
    if project_id and (project_data := projects_by_id.get(project_id)) is not None:
        project_summary = {
            "id": project_data.get("id") or project_id,
            "title": project_data.get("title", ""),
        }

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
        project=project_summary,
    )


def list_my_applications(current_user: CurrentUser) -> list[ApplicationResponse]:
    query = db.collection("applications").where(filter=_talent_filter(current_user.uid))
    applications_by_id = {
        doc.id: doc.to_dict() or {}
        for doc in query.stream()
    }
    opportunities_by_id = _get_documents_by_id(
        "opportunities",
        {
            data.get("opportunity_id")
            for data in applications_by_id.values()
            if data.get("opportunity_id")
        },
    )
    projects_by_id = _get_documents_by_id(
        "projects",
        {
            project_id
            for data in applications_by_id.values()
            if (
                project_id := data.get("project_id")
                or opportunities_by_id.get(data.get("opportunity_id"), {}).get("project_id")
            )
        },
    )
    items = [
        _serialize_my_application(
            application_id,
            data,
            opportunities_by_id,
            projects_by_id,
        )
        for application_id, data in applications_by_id.items()
    ]
    return sorted(items, key=lambda item: item.applied_at, reverse=True)


def _normalize_application_status(status: str | None) -> str:
    return (status or "SUBMITTED").strip().upper()


def _application_result_label(status: str) -> str:
    return {
        "SUBMITTED": "En revisión",
        "REVIEWING": "En revisión",
        "ACCEPTED": "Aceptada",
        "REJECTED": "Rechazada",
        "CANCELLED": "Cancelada",
        "COMPLETED": "Finalizada",
    }.get(status, status.replace("_", " ").title())


def _extract_count(result) -> int | None:
    if result is None:
        return None

    if isinstance(result, (int, float)):
        return int(result)

    if isinstance(result, Mapping):
        for value in result.values():
            count = _extract_count(value)
            if count is not None:
                return count
        return None

    if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
        for item in result:
            count = _extract_count(item)
            if count is not None:
                return count
        return None

    for attribute in ("value", "total", "count"):
        if hasattr(result, attribute):
            count = _extract_count(getattr(result, attribute))
            if count is not None:
                return count

    try:
        return int(result)
    except (TypeError, ValueError):
        return None


def _count_query(query, label: str) -> int:
    start = time.perf_counter()
    count = _extract_count(query.count(alias="total").get()) or 0
    print(
        f"[PERF] applications feed Firestore count {label} "
        f"(result={count}): {(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return count


def _count_applications_with_status(query, statuses: list[str], label: str) -> int:
    operator = "==" if len(statuses) == 1 else "in"
    value = statuses[0] if len(statuses) == 1 else statuses
    return _count_query(query.where(filter=FieldFilter("status", operator, value)), label)


def _get_my_application_summary(query) -> TalentApplicationFeedSummary:
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            "total": executor.submit(_count_query, query, "total"),
            "accepted": executor.submit(_count_applications_with_status, query, ["ACCEPTED"], "accepted"),
            "rejected": executor.submit(_count_applications_with_status, query, ["REJECTED"], "rejected"),
            "cancelled": executor.submit(_count_applications_with_status, query, ["CANCELLED"], "cancelled"),
            "completed": executor.submit(_count_applications_with_status, query, ["COMPLETED"], "completed"),
        }
        counts = {
            label: future.result()
            for label, future in futures.items()
        }
    total = counts["total"]
    accepted = counts["accepted"]
    rejected = counts["rejected"]
    cancelled = counts["cancelled"]
    completed = counts["completed"]
    closed = rejected + cancelled + completed
    reviewing = max(total - accepted - closed, 0)
    decided = accepted + rejected

    summary = TalentApplicationFeedSummary(
        total=total,
        active=max(total - closed, 0),
        reviewing=reviewing,
        accepted=accepted,
        rejected=rejected,
        cancelled=cancelled,
        completed=completed,
        closed=closed,
        acceptance_rate=round(accepted / decided * 100) if decided else 0,
    )
    print(f"[PERF] applications feed summary total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return summary


def get_my_application_summary(current_user: CurrentUser) -> TalentApplicationFeedSummary:
    start = time.perf_counter()
    query = db.collection("applications").where(filter=_talent_filter(current_user.uid))
    summary = _get_my_application_summary(query)
    print(f"[PERF] applications summary endpoint service total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return summary


def _serialize_my_application_feed_item(
    application_id: str,
    data: dict,
    opportunities_by_id: dict[str, dict],
    projects_by_id: dict[str, dict],
) -> TalentApplicationFeedItem:
    application = _serialize_my_application(
        application_id,
        data,
        opportunities_by_id,
        projects_by_id,
    )
    status = _normalize_application_status(application.status)
    opportunity = application.opportunity or {}
    project = application.project or {}

    return TalentApplicationFeedItem(
        id=application.id,
        opportunity_id=application.opportunity_id,
        project_id=application.project_id,
        opportunity_title=opportunity.get("title", ""),
        project_title=project.get("title", ""),
        status=status,
        applied_at=application.applied_at,
        updated_at=application.updated_at,
        message=application.message,
        result_label=_application_result_label(status),
        opportunity=application.opportunity,
        project=application.project,
    )


def list_my_application_feed(
    current_user: CurrentUser,
    limit: int = 10,
    cursor: str | None = None,
    include_summary: bool = True,
) -> TalentApplicationFeedResponse:
    start = time.perf_counter()
    applications = db.collection("applications")
    talent_filter = _talent_filter(current_user.uid)
    base_query = applications.where(filter=talent_filter)
    page_query = (
        base_query
        .order_by("applied_at", direction=Query.DESCENDING)
        .order_by("__name__", direction=Query.DESCENDING)
    )

    if cursor:
        cursor_start = time.perf_counter()
        cursor_doc = applications.document(cursor).get()
        print(
            "[PERF] applications feed Firestore cursor document.get "
            f"(reads=1): {(time.perf_counter() - cursor_start) * 1000:.2f} ms"
        )
        cursor_data = cursor_doc.to_dict() or {} if cursor_doc.exists else {}
        if (
            not cursor_doc.exists
            or _get_talent_user_id(cursor_data) != current_user.uid
            or not cursor_data.get("applied_at")
        ):
            raise HTTPException(status_code=400, detail="Cursor de postulaciones invalido")
        page_query = page_query.start_after(cursor_doc)

    page_start = time.perf_counter()
    docs = list(page_query.limit(limit + 1).stream())
    print(
        "[PERF] applications feed Firestore page query "
        f"(reads={len(docs)}, limit={limit + 1}): {(time.perf_counter() - page_start) * 1000:.2f} ms"
    )
    page_docs = docs[:limit]
    related_start = time.perf_counter()
    opportunities_by_id = _get_documents_by_id(
        "opportunities",
        {
            data.get("opportunity_id")
            for doc in page_docs
            for data in [doc.to_dict() or {}]
            if data.get("opportunity_id")
        },
    )
    projects_by_id = _get_documents_by_id(
        "projects",
        {
            project_id
            for doc in page_docs
            for data in [doc.to_dict() or {}]
            if (
                project_id := data.get("project_id")
                or opportunities_by_id.get(data.get("opportunity_id"), {}).get("project_id")
            )
        },
    )
    print(f"[PERF] applications feed related documents total: {(time.perf_counter() - related_start) * 1000:.2f} ms")

    serialization_start = time.perf_counter()
    items = [
        _serialize_my_application_feed_item(
            doc.id,
            doc.to_dict() or {},
            opportunities_by_id,
            projects_by_id,
        )
        for doc in page_docs
    ]
    print(
        f"[PERF] applications feed serialize items (items={len(items)}): "
        f"{(time.perf_counter() - serialization_start) * 1000:.2f} ms"
    )
    summary_start = time.perf_counter()
    summary = _get_my_application_summary(base_query) if include_summary else None
    if not include_summary:
        print(f"[PERF] applications feed summary skipped: {(time.perf_counter() - summary_start) * 1000:.2f} ms")
    response_start = time.perf_counter()
    response = TalentApplicationFeedResponse(
        items=items,
        next_cursor=page_docs[-1].id if len(docs) > limit and page_docs else None,
        summary=summary,
    )
    print(f"[PERF] applications feed build response: {(time.perf_counter() - response_start) * 1000:.2f} ms")
    print(f"[PERF] applications feed service total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return response


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
            opportunity_title=opportunity_data.get("title"),
            producer_name=current_user.name,
        )

    return ApplicationStatusUpdateResponse(
        id=application_data.get("id") or application_doc.id,
        status=payload.status,
        updated_at=updated_at,
    )
