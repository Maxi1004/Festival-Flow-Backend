from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Any

from fastapi import HTTPException
from google.cloud.firestore_v1 import Increment, Query
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import db
from app.core.utils import (
    get_crew_category_label,
    get_talent_uid_from_data,
    normalize_crew_category,
    serialize_date,
    utc_now_iso,
)
from app.schemas.auth_schema import CurrentUser
from app.schemas.crew_schema import (
    CrewDirectMessageResponse,
    CrewConversationResponse,
    CrewMemberUpdateRequest,
    CrewMemberResponse,
    CrewMessageCreateRequest,
    CrewMessageResponse,
    CrewOpportunitySummary,
    CrewProducerSummary,
    CrewProjectCrmResponse,
    CrewProjectSummary,
    CrewTalentSummary,
    MessageConversationFeedResponse,
    MessageConversationInfoParticipant,
    MessageConversationInfoResponse,
    MessageConversationItem,
    MessageConversationParticipant,
    ProjectChatMessageResponse,
    ProjectCrewMemberResponse,
    ProjectCrewMembersResponse,
    ProjectMessageCreateRequest,
    TalentCrewFeedItem,
    TalentCrewFeedResponse,
    TalentCrewFeedSummary,
    TeamChatPhotoResponse,
    TeamChatSettingsUpdateRequest,
    UnifiedConversationMessageResponse,
)

ACTIVE_PROJECT_MEMBER_STATUSES = ("ACTIVE", "ACCEPTED", "active", "accepted")


def _first_present(data: dict, keys: tuple[str, ...], default: str | None = "") -> str | None:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return default


def _normalize_text_list(value) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def _crew_category_from_data(data: dict) -> str:
    return normalize_crew_category(
        data.get("category"),
        data.get("role"),
        data.get("specialty")
        or data.get("main_specialty")
        or data.get("task_category"),
    )


def get_user_identity(user_id: str, fallback: dict | None = None) -> CrewTalentSummary:
    fallback_data = fallback or {}
    user_data: dict[str, Any] = {}

    if user_id:
        user_doc = db.collection("users").document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict() or {}

    return CrewTalentSummary(
        user_id=user_id,
        name=_first_present(
            user_data,
            ("name", "display_name", "full_name", "nombre"),
            _first_present(fallback_data, ("name", "display_name", "full_name", "nombre", "talent_name")),
        ),
        email=_first_present(user_data, ("email",), _first_present(fallback_data, ("email", "talent_email"))),
    )


def get_producer_identity(user_id: str, fallback: dict | None = None) -> CrewProducerSummary:
    identity = get_user_identity(user_id, fallback)
    return CrewProducerSummary(
        user_id=identity.user_id,
        name=identity.name,
        email=identity.email,
    )


def get_project_summary(project_id: str | None) -> CrewProjectSummary | None:
    if not project_id:
        return None

    project_doc = db.collection("projects").document(project_id).get()
    if not project_doc.exists:
        return None

    project_data = project_doc.to_dict() or {}
    return CrewProjectSummary(
        id=project_data.get("id") or project_doc.id,
        title=project_data.get("title", ""),
    )


def _legacy_project_summary(data: dict) -> CrewProjectSummary | None:
    legacy_project = data.get("project")
    if isinstance(legacy_project, dict):
        project_id = legacy_project.get("id") or legacy_project.get("project_id")
        title = legacy_project.get("title")
        if project_id or title:
            return CrewProjectSummary(id=project_id or "", title=title or "")

    project_id = data.get("legacy_project_id")
    title = data.get("project_title")
    if project_id or title:
        return CrewProjectSummary(id=project_id or "", title=title or "")

    return None


def get_opportunity_summary(opportunity_id: str | None) -> CrewOpportunitySummary | None:
    if not opportunity_id:
        return None

    opportunity_doc = db.collection("opportunities").document(opportunity_id).get()
    if not opportunity_doc.exists:
        return None

    opportunity_data = opportunity_doc.to_dict() or {}
    return CrewOpportunitySummary(
        id=opportunity_data.get("id") or opportunity_doc.id,
        title=opportunity_data.get("title", ""),
    )


def _legacy_opportunity_summary(data: dict) -> CrewOpportunitySummary | None:
    legacy_opportunity = data.get("opportunity")
    if isinstance(legacy_opportunity, dict):
        opportunity_id = legacy_opportunity.get("id") or legacy_opportunity.get("opportunity_id")
        title = legacy_opportunity.get("title")
        if opportunity_id or title:
            return CrewOpportunitySummary(id=opportunity_id or "", title=title or "")

    opportunity_id = data.get("legacy_opportunity_id")
    title = data.get("opportunity_title")
    if opportunity_id or title:
        return CrewOpportunitySummary(id=opportunity_id or "", title=title or "")

    return None


def _crew_member_id(
    producer_id: str,
    talent_user_id: str,
    project_id: str | None,
    opportunity_id: str | None,
) -> str:
    return "__".join(
        [
            producer_id,
            talent_user_id,
            project_id or "no_project",
            opportunity_id or "no_opportunity",
        ]
    )


def create_or_update_crew_member(
    *,
    producer_id: str,
    talent_user_id: str,
    project_id: str | None,
    opportunity_id: str | None,
    application_id: str | None,
    recruitment_id: str | None,
    source: str,
    role: str | None = None,
    category: str | None = None,
    specialty: str | None = None,
    task_description: str | None = None,
    producer_note: str | None = None,
    project_title: str | None = None,
    opportunity_title: str | None = None,
    producer_name: str | None = None,
    talent_name: str | None = None,
    talent_email: str | None = None,
    talent_photo_url: str | None = None,
) -> dict:
    crew_member_id = _crew_member_id(producer_id, talent_user_id, project_id, opportunity_id)
    crew_member_ref = db.collection("crew_members").document(crew_member_id)
    matched_existing_member = False

    if application_id:
        existing_application_docs = list(
            db.collection("crew_members")
            .where(filter=FieldFilter("application_id", "==", application_id))
            .limit(1)
            .stream()
        )
        if existing_application_docs:
            crew_member_ref = existing_application_docs[0].reference
            crew_member_id = existing_application_docs[0].id
            matched_existing_member = True

    if not matched_existing_member and project_id and talent_user_id:
        existing_project_docs = list(
            db.collection("crew_members")
            .where(filter=FieldFilter("project_id", "==", project_id))
            .stream()
        )
        for existing_project_doc in existing_project_docs:
            existing_project_data = existing_project_doc.to_dict() or {}
            if get_talent_uid_from_data(existing_project_data) == talent_user_id:
                crew_member_ref = existing_project_doc.reference
                crew_member_id = existing_project_doc.id
                break

    existing_doc = crew_member_ref.get()
    existing_data = {}
    if existing_doc.exists:
        existing_data = existing_doc.to_dict() or {}
    timestamp = utc_now_iso()
    joined_at = existing_data.get("joined_at") or timestamp
    resolved_project_title = existing_data.get("project_title") or project_title
    resolved_opportunity_title = existing_data.get("opportunity_title") or opportunity_title
    resolved_producer_name = existing_data.get("producer_name") or producer_name
    identity_refs = [
        db.collection("users").document(talent_user_id),
        db.collection("talent_profiles").document(talent_user_id),
    ]
    identity_docs = {
        doc.reference.parent.id: doc.to_dict() or {}
        for doc in db.get_all(identity_refs)
        if doc.exists
    }
    user_data = identity_docs.get("users", {})
    profile_data = identity_docs.get("talent_profiles", {})
    resolved_talent_name = _first_present(
        profile_data,
        ("display_name", "name"),
        _first_present(
            user_data,
            ("name", "display_name"),
            talent_name or _first_present(existing_data, ("talent_name", "name")),
        ),
    )
    resolved_talent_email = _first_present(
        user_data,
        ("email",),
        talent_email or _first_present(existing_data, ("talent_email", "email")),
    )
    resolved_talent_photo = _first_present(
        profile_data,
        ("photo_url", "picture"),
        _first_present(
            user_data,
            ("photo_url", "picture", "avatar_url"),
            talent_photo_url or _first_present(existing_data, ("talent_photo_url", "photo_url"), None),
        ),
    )
    resolved_role = role if role is not None else existing_data.get("role")
    resolved_specialty = (
        specialty
        or profile_data.get("main_specialty")
        or existing_data.get("specialty")
        or existing_data.get("main_specialty")
        or existing_data.get("task_category")
    )
    resolved_category = normalize_crew_category(
        category if category is not None else existing_data.get("category"),
        resolved_role,
        resolved_specialty,
    )

    if project_id and not resolved_project_title:
        project_doc = db.collection("projects").document(project_id).get()
        if project_doc.exists:
            resolved_project_title = (project_doc.to_dict() or {}).get("title")
    if opportunity_id and not resolved_opportunity_title:
        opportunity_doc = db.collection("opportunities").document(opportunity_id).get()
        if opportunity_doc.exists:
            resolved_opportunity_title = (opportunity_doc.to_dict() or {}).get("title")
    if producer_id and not resolved_producer_name:
        producer_doc = db.collection("users").document(producer_id).get()
        if producer_doc.exists:
            resolved_producer_name = (producer_doc.to_dict() or {}).get("name")

    crew_member_data = {
        **existing_data,
        "id": crew_member_id,
        "producer_id": producer_id,
        "talent_user_id": talent_user_id,
        "talent_uid": talent_user_id,
        "user_id": talent_user_id,
        "user_uid": talent_user_id,
        "talent_name": resolved_talent_name,
        "name": resolved_talent_name,
        "talent_email": resolved_talent_email,
        "email": resolved_talent_email,
        "talent_photo_url": resolved_talent_photo,
        "photo_url": resolved_talent_photo,
        "main_specialty": profile_data.get("main_specialty") or existing_data.get("main_specialty"),
        "specialties": _normalize_text_list(
            profile_data.get("specialties") or existing_data.get("specialties")
        ),
        "project_id": project_id,
        "project_title": resolved_project_title,
        "opportunity_id": opportunity_id,
        "opportunity_title": resolved_opportunity_title,
        "producer_name": resolved_producer_name,
        "application_id": application_id,
        "recruitment_id": recruitment_id,
        "source": source,
        "role": resolved_role,
        "category": resolved_category,
        "category_label": get_crew_category_label(resolved_category),
        "task_description": task_description
        if task_description is not None
        else existing_data.get("task_description"),
        "producer_note": existing_data.get("producer_note") or producer_note,
        "status": "ACTIVE",
        "joined_at": joined_at,
        "created_at": existing_data.get("created_at") or timestamp,
        "updated_at": timestamp,
        "messages_count": existing_data.get("messages_count", 0),
    }
    crew_member_data.pop("removed_at", None)
    crew_member_data.pop("removed_by", None)

    crew_member_ref.set(crew_member_data)
    return crew_member_data


def _serialize_crew_member(crew_member_id: str, data: dict) -> CrewMemberResponse:
    project_id = data.get("project_id")
    opportunity_id = data.get("opportunity_id")
    category = _crew_category_from_data(data)
    return CrewMemberResponse(
        id=data.get("id") or crew_member_id,
        project_id=project_id,
        opportunity_id=opportunity_id,
        talent=get_user_identity(data.get("talent_user_id", ""), data),
        producer=get_producer_identity(data.get("producer_id", "")),
        project=get_project_summary(project_id) if project_id else _legacy_project_summary(data),
        opportunity=get_opportunity_summary(opportunity_id) if opportunity_id else _legacy_opportunity_summary(data),
        source=data.get("source", ""),
        role=data.get("role"),
        category=category,
        category_label=get_crew_category_label(category),
        task_description=data.get("task_description"),
        producer_note=data.get("producer_note"),
        status=data.get("status", ""),
        joined_at=serialize_date(data.get("joined_at")),
        updated_at=serialize_date(data.get("updated_at")),
    )


def _get_crew_member_doc(crew_member_id: str):
    crew_member_doc = db.collection("crew_members").document(crew_member_id).get()
    if not crew_member_doc.exists:
        raise HTTPException(status_code=404, detail="Integrante de equipo no encontrado")
    return crew_member_doc


def _validate_crew_access(crew_member_id: str, current_user: CurrentUser):
    crew_member_doc = _get_crew_member_doc(crew_member_id)
    crew_member_data = crew_member_doc.to_dict() or {}

    if current_user.role.value == "PRODUCER" and crew_member_data.get("producer_id") == current_user.uid:
        return crew_member_doc, crew_member_data
    if current_user.role.value == "TALENT" and crew_member_data.get("talent_user_id") == current_user.uid:
        return crew_member_doc, crew_member_data

    raise HTTPException(status_code=403, detail="No tienes permisos sobre este integrante de equipo")


def list_producer_crew(current_user: CurrentUser) -> list[CrewMemberResponse]:
    query = db.collection("crew_members").where("producer_id", "==", current_user.uid)
    items = [_serialize_crew_member(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.joined_at or "", reverse=True)


def _crew_project_status(member_rows: list[tuple[str, dict]]) -> str:
    statuses = {str(data.get("status") or "").strip().upper() for _, data in member_rows}
    if "ACTIVE" in statuses or "ACCEPTED" in statuses:
        return "ACTIVE"
    if "REMOVED" in statuses and len(statuses) == 1:
        return "REMOVED"
    return next((status for status in statuses if status), "")


def _crew_last_activity(member_rows: list[tuple[str, dict]]) -> str | None:
    values = [
        serialize_date(data.get("updated_at") or data.get("last_activity") or data.get("joined_at") or data.get("created_at"))
        for _, data in member_rows
    ]
    return max([value for value in values if value], default=None)


def _crew_category_summary(
    member_rows: list[tuple[str, dict]],
) -> tuple[list[str], dict[str, int], list[str]]:
    category_counts: dict[str, int] = {}
    for _, data in member_rows:
        category = _crew_category_from_data(data)
        category_counts[category] = category_counts.get(category, 0) + 1

    categories = list(category_counts)
    top_categories = sorted(
        categories,
        key=lambda category: (-category_counts[category], categories.index(category)),
    )
    return categories, category_counts, top_categories


def list_producer_crew_crm(
    current_user: CurrentUser,
    *,
    summary: bool = True,
) -> list[CrewProjectCrmResponse]:
    start = time.perf_counter()
    query_start = time.perf_counter()
    docs = list(db.collection("crew_members").where("producer_id", "==", current_user.uid).stream())
    member_rows = _resolve_crew_talent_uids(
        [(doc.id, doc.to_dict() or {}) for doc in docs]
    )
    print(
        "[PERF] crew CRM crew_members query "
        f"(reads={len(member_rows)}): {(time.perf_counter() - query_start) * 1000:.2f} ms"
    )

    grouped: dict[str, list[tuple[str, dict]]] = {}
    for crew_member_id, data in member_rows:
        project_id = data.get("project_id") or "no_project"
        grouped.setdefault(project_id, []).append((crew_member_id, data))

    projects_by_id = _get_documents_by_id(
        "projects",
        {project_id for project_id in grouped if project_id != "no_project"},
    )

    identities_by_uid: dict[str, dict] = {}
    if not summary:
        fallbacks_by_uid = {
            get_talent_uid_from_data(data) or "": data
            for rows in grouped.values()
            for _, data in rows
            if get_talent_uid_from_data(data)
        }
        identities_by_uid = _get_project_user_identities(fallbacks_by_uid)

    serialize_start = time.perf_counter()
    items: list[CrewProjectCrmResponse] = []
    for project_id, rows in grouped.items():
        active_rows = [
            (crew_member_id, data)
            for crew_member_id, data in rows
            if str(data.get("status") or "").strip().upper() != "REMOVED"
        ]
        project_data = projects_by_id.get(project_id, {})
        project_title = (
            project_data.get("title")
            or next((data.get("project_title") or data.get("project_name") for _, data in rows if data.get("project_title") or data.get("project_name")), "")
        )
        members = None
        if not summary:
            members = [
                ProjectCrewMemberResponse(
                    **_talent_project_participant(
                        project_id,
                        crew_member_id,
                        data,
                        identities_by_uid.get(get_talent_uid_from_data(data) or ""),
                    )
                )
                for crew_member_id, data in rows
            ]
        categories, category_counts, top_categories = _crew_category_summary(active_rows)

        items.append(
            CrewProjectCrmResponse(
                project_id=project_id,
                project_title=project_title or "",
                members_count=len(active_rows),
                categories=categories,
                category_counts=category_counts,
                top_categories=top_categories,
                status=_crew_project_status(active_rows or rows),
                last_activity=_crew_last_activity(rows),
                members=members,
            )
        )

    items.sort(key=lambda item: item.last_activity or "", reverse=True)
    print(
        "[PERF] crew CRM serialize "
        f"(projects={len(items)}, summary={summary}): {(time.perf_counter() - serialize_start) * 1000:.2f} ms"
    )
    print(f"[PERF] crew CRM total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return items


def list_talent_crew(current_user: CurrentUser) -> list[CrewMemberResponse]:
    query = db.collection("crew_members").where("talent_user_id", "==", current_user.uid).where("status", "==", "ACTIVE")
    items = [_serialize_crew_member(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.joined_at or "", reverse=True)


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
        f"[PERF] crew feed Firestore batch {collection_name} "
        f"(requested={len(document_refs)}, reads={len(documents)}): "
        f"{(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return documents


def _chunks(items: list[str], size: int = 30) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def _get_documents_by_field_values(
    collection_name: str,
    field_name: str,
    values: set[str],
) -> list[tuple[str, dict]]:
    normalized_values = sorted({str(value).strip() for value in values if str(value).strip()})
    rows: list[tuple[str, dict]] = []
    for values_chunk in _chunks(normalized_values):
        query = db.collection(collection_name).where(
            filter=FieldFilter(field_name, "in", values_chunk)
        )
        rows.extend((doc.id, doc.to_dict() or {}) for doc in query.stream())
    return rows


def _resolve_crew_talent_uids(
    member_rows: list[tuple[str, dict]],
) -> list[tuple[str, dict]]:
    application_ids = {
        data.get("application_id")
        for _, data in member_rows
        if not get_talent_uid_from_data(data) and data.get("application_id")
    }
    recruitment_ids = {
        data.get("recruitment_id")
        for _, data in member_rows
        if not get_talent_uid_from_data(data) and data.get("recruitment_id")
    }
    applications_by_id = _get_documents_by_id("applications", application_ids)
    recruitments_by_id = _get_documents_by_id("recruitments", recruitment_ids)

    resolved_rows: list[tuple[str, dict]] = []
    unresolved_rows: list[tuple[str, dict]] = []
    for crew_member_id, data in member_rows:
        talent_uid = get_talent_uid_from_data(data)
        if not talent_uid and data.get("application_id"):
            talent_uid = get_talent_uid_from_data(
                applications_by_id.get(data.get("application_id"), {})
            )
        if not talent_uid and data.get("recruitment_id"):
            talent_uid = get_talent_uid_from_data(
                recruitments_by_id.get(data.get("recruitment_id"), {})
            )
        next_data = dict(data)
        if talent_uid:
            next_data.update(
                {
                    "talent_user_id": talent_uid,
                    "talent_uid": talent_uid,
                    "user_id": talent_uid,
                    "user_uid": talent_uid,
                }
            )
            resolved_rows.append((crew_member_id, next_data))
        else:
            unresolved_rows.append((crew_member_id, next_data))

    unresolved_emails = {
        str(data.get("email") or data.get("talent_email") or "").strip()
        for _, data in unresolved_rows
        if data.get("email") or data.get("talent_email")
    }
    users_by_email = {
        str(data.get("email") or "").strip().lower(): get_talent_uid_from_data(data) or doc_id
        for doc_id, data in _get_documents_by_field_values("users", "email", unresolved_emails)
    }
    unresolved_names = {
        str(data.get("name") or data.get("talent_name") or "").strip()
        for _, data in unresolved_rows
        if data.get("name") or data.get("talent_name")
    }
    users_by_name: dict[str, str] = {}
    for field_name in ("name", "display_name"):
        for doc_id, data in _get_documents_by_field_values("users", field_name, unresolved_names):
            name = str(data.get(field_name) or "").strip().lower()
            users_by_name.setdefault(name, get_talent_uid_from_data(data) or doc_id)

    for crew_member_id, data in unresolved_rows:
        email = str(data.get("email") or data.get("talent_email") or "").strip().lower()
        name = str(data.get("name") or data.get("talent_name") or "").strip().lower()
        talent_uid = users_by_email.get(email) or users_by_name.get(name)
        if talent_uid:
            data.update(
                {
                    "talent_user_id": talent_uid,
                    "talent_uid": talent_uid,
                    "user_id": talent_uid,
                    "user_uid": talent_uid,
                }
            )
        resolved_rows.append((crew_member_id, data))

    return resolved_rows


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
        f"[PERF] crew feed Firestore count {label} "
        f"(result={count}): {(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return count


def _get_talent_crew_summary(query) -> TalentCrewFeedSummary:
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            "total": executor.submit(_count_query, query, "total"),
            "active": executor.submit(_count_query, query.where(filter=FieldFilter("status", "==", "ACTIVE")), "active"),
            "completed": executor.submit(_count_query, query.where(filter=FieldFilter("status", "==", "COMPLETED")), "completed"),
            "cancelled": executor.submit(_count_query, query.where(filter=FieldFilter("status", "==", "CANCELLED")), "cancelled"),
        }
        counts = {label: future.result() for label, future in futures.items()}

    summary = TalentCrewFeedSummary(**counts)
    print(f"[PERF] crew feed summary total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return summary


def get_talent_crew_summary(current_user: CurrentUser) -> TalentCrewFeedSummary:
    query = db.collection("crew_members").where("talent_uid", "==", current_user.uid)
    return _get_talent_crew_summary(query)


def _serialize_talent_crew_feed_item(
    crew_member_id: str,
    data: dict,
    projects_by_id: dict[str, dict],
    opportunities_by_id: dict[str, dict],
    producers_by_id: dict[str, dict],
) -> TalentCrewFeedItem:
    project_data = projects_by_id.get(data.get("project_id"), {})
    opportunity_data = opportunities_by_id.get(data.get("opportunity_id"), {})
    producer_data = producers_by_id.get(data.get("producer_id"), {})

    return TalentCrewFeedItem(
        id=data.get("id") or crew_member_id,
        project_id=data.get("project_id"),
        project_title=data.get("project_title") or project_data.get("title", ""),
        opportunity_id=data.get("opportunity_id"),
        opportunity_title=data.get("opportunity_title") or opportunity_data.get("title", ""),
        producer_name=data.get("producer_name") or producer_data.get("name", ""),
        role=data.get("role"),
        category=_crew_category_from_data(data),
        category_label=get_crew_category_label(_crew_category_from_data(data)),
        task_description=data.get("task_description"),
        producer_note=data.get("producer_note"),
        status=data.get("status", "ACTIVE"),
        joined_at=serialize_date(data.get("joined_at") or data.get("created_at")),
        updated_at=serialize_date(data.get("updated_at")),
        messages_count=data.get("messages_count", 0),
    )


def list_talent_crew_feed(
    current_user: CurrentUser,
    limit: int = 10,
    cursor: str | None = None,
    include_summary: bool = True,
) -> TalentCrewFeedResponse:
    start = time.perf_counter()
    crew_members = db.collection("crew_members")
    base_query = crew_members.where("talent_uid", "==", current_user.uid)
    page_query = (
        base_query
        .order_by("joined_at", direction=Query.DESCENDING)
        .order_by("__name__", direction=Query.DESCENDING)
    )

    if cursor:
        cursor_doc = crew_members.document(cursor).get()
        cursor_data = cursor_doc.to_dict() or {} if cursor_doc.exists else {}
        if not cursor_doc.exists or cursor_data.get("talent_uid") != current_user.uid:
            raise HTTPException(status_code=400, detail="Cursor de equipo invalido")
        page_query = page_query.start_after(cursor_doc)

    page_start = time.perf_counter()
    docs = list(page_query.limit(limit + 1).stream())
    print(
        "[PERF] crew feed Firestore page query "
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
            if data.get("opportunity_id") and not data.get("opportunity_title")
        },
    )
    producers_by_id = _get_documents_by_id(
        "users",
        {data.get("producer_id") for _, data in page_data if data.get("producer_id") and not data.get("producer_name")},
    )
    items = [
        _serialize_talent_crew_feed_item(doc.id, data, projects_by_id, opportunities_by_id, producers_by_id)
        for doc, data in page_data
    ]
    summary = _get_talent_crew_summary(base_query) if include_summary else None
    if not include_summary:
        print("[PERF] crew feed summary skipped")
    response = TalentCrewFeedResponse(
        items=items,
        next_cursor=page_docs[-1].id if len(docs) > limit and page_docs else None,
        summary=summary,
    )
    print(f"[PERF] crew feed service total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return response


def update_crew_member(
    crew_member_id: str,
    payload: CrewMemberUpdateRequest,
    current_user: CurrentUser,
) -> CrewMemberResponse:
    crew_member_doc = _get_crew_member_doc(crew_member_id)
    crew_member_data = crew_member_doc.to_dict() or {}

    if crew_member_data.get("producer_id") != current_user.uid:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre este integrante de equipo")

    updates = payload.model_dump(exclude_unset=True)
    allowed_updates = {
        key: value
        for key, value in updates.items()
        if key in {"role", "category", "task_description", "status", "producer_note"}
    }
    if "category" in allowed_updates or "role" in allowed_updates:
        normalized_category = normalize_crew_category(
            allowed_updates.get("category", crew_member_data.get("category")),
            allowed_updates.get("role", crew_member_data.get("role")),
            crew_member_data.get("specialty")
            or crew_member_data.get("main_specialty")
            or crew_member_data.get("task_category"),
        )
        allowed_updates["category"] = normalized_category
        allowed_updates["category_label"] = get_crew_category_label(normalized_category)
    allowed_updates["updated_at"] = utc_now_iso()

    updated_data = {
        **crew_member_data,
        **allowed_updates,
        "id": crew_member_data.get("id") or crew_member_doc.id,
    }
    crew_member_doc.reference.set(updated_data)
    return _serialize_crew_member(crew_member_doc.id, updated_data)


def update_project_crew_member(
    project_id: str,
    crew_member_id: str,
    payload: CrewMemberUpdateRequest,
    current_user: CurrentUser,
) -> ProjectCrewMemberResponse:
    _validate_project_owner(project_id, current_user)
    crew_member_doc, crew_member_data = _get_project_crew_member_doc(project_id, crew_member_id)
    updates = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if key in {"role", "category", "task_description", "status"}
    }
    if not updates:
        raise HTTPException(status_code=400, detail="Debes enviar role, category, task_description o status")
    if "category" in updates or "role" in updates:
        normalized_category = normalize_crew_category(
            updates.get("category", crew_member_data.get("category")),
            updates.get("role", crew_member_data.get("role")),
            crew_member_data.get("specialty")
            or crew_member_data.get("main_specialty")
            or crew_member_data.get("task_category"),
        )
        updates["category"] = normalized_category
        updates["category_label"] = get_crew_category_label(normalized_category)

    updated_data = {
        **crew_member_data,
        **updates,
        "id": crew_member_data.get("id") or crew_member_doc.id,
        "updated_at": utc_now_iso(),
    }
    crew_member_doc.reference.set(updated_data)
    return _project_crew_member_response(project_id, crew_member_doc.id, updated_data)


def remove_project_crew_member(
    project_id: str,
    crew_member_id: str,
    current_user: CurrentUser,
) -> ProjectCrewMemberResponse:
    _validate_project_owner(project_id, current_user)
    crew_member_doc, crew_member_data = _get_project_crew_member_doc(project_id, crew_member_id)
    timestamp = utc_now_iso()
    updated_data = {
        **crew_member_data,
        "id": crew_member_data.get("id") or crew_member_doc.id,
        "status": "REMOVED",
        "removed_at": timestamp,
        "removed_by": current_user.uid,
        "updated_at": timestamp,
    }
    crew_member_doc.reference.set(updated_data)
    return _project_crew_member_response(project_id, crew_member_doc.id, updated_data)


def create_crew_message(
    crew_member_id: str,
    payload: CrewMessageCreateRequest,
    current_user: CurrentUser,
) -> CrewMessageResponse:
    crew_member_doc, crew_member_data = _validate_crew_access(crew_member_id, current_user)

    message_ref = db.collection("crew_messages").document()
    message_data = {
        "id": message_ref.id,
        "crew_member_id": crew_member_id,
        "sender_id": current_user.uid,
        "sender_role": current_user.role.value,
        "message": payload.message,
        "created_at": utc_now_iso(),
    }

    batch = db.batch()
    batch.set(message_ref, message_data)
    _set_conversation_summary(
        batch,
        _legacy_conversation_id(crew_member_id),
        {
            "type": "DIRECT",
            "transport": "LEGACY",
            "crew_member_id": crew_member_id,
            "project_id": crew_member_data.get("project_id"),
            "participant_uids": [
                crew_member_data.get("producer_id", ""),
                crew_member_data.get("talent_user_id") or crew_member_data.get("talent_uid", ""),
            ],
        },
        payload.message,
        message_data["created_at"],
    )
    batch.update(
        crew_member_doc.reference,
        {
            "messages_count": Increment(1),
            "updated_at": utc_now_iso(),
        },
    )
    batch.commit()
    return CrewMessageResponse(**message_data)


def _list_messages_for_crew_member(crew_member_id: str) -> list[CrewMessageResponse]:
    query = db.collection("crew_messages").where("crew_member_id", "==", crew_member_id)
    items = [
        CrewMessageResponse(
            id=(data := (doc.to_dict() or {})).get("id") or doc.id,
            crew_member_id=data.get("crew_member_id", crew_member_id),
            sender_id=data.get("sender_id", ""),
            sender_role=data.get("sender_role", ""),
            message=data.get("message", ""),
            created_at=serialize_date(data.get("created_at")) or "",
        )
        for doc in query.stream()
    ]
    return sorted(items, key=lambda item: item.created_at)


def list_crew_messages(
    crew_member_id: str,
    current_user: CurrentUser,
) -> list[CrewMessageResponse]:
    _validate_crew_access(crew_member_id, current_user)
    return _list_messages_for_crew_member(crew_member_id)


def list_message_conversations(current_user: CurrentUser) -> list[CrewConversationResponse]:
    if current_user.role.value == "PRODUCER":
        query = db.collection("crew_members").where("producer_id", "==", current_user.uid)
    elif current_user.role.value == "TALENT":
        query = db.collection("crew_members").where("talent_user_id", "==", current_user.uid)
    else:
        raise HTTPException(status_code=403, detail="Rol no autorizado para conversaciones")

    conversations: list[CrewConversationResponse] = []
    for doc in query.stream():
        crew_member = _serialize_crew_member(doc.id, doc.to_dict() or {})
        messages = _list_messages_for_crew_member(crew_member.id)
        last_message = messages[-1] if messages else None

        conversations.append(
            CrewConversationResponse(
                crew_member_id=crew_member.id,
                project=crew_member.project,
                opportunity=crew_member.opportunity,
                talent=crew_member.talent,
                producer=crew_member.producer,
                role=crew_member.role,
                last_message=last_message,
                last_message_at=last_message.created_at if last_message else None,
                unread_count=0,
            )
        )

    return sorted(
        conversations,
        key=lambda item: item.last_message_at or "",
        reverse=True,
    )


def _get_project_data(project_id: str) -> dict:
    project_doc = db.collection("projects").document(project_id).get()
    if not project_doc.exists:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project_doc.to_dict() or {}


def _list_active_project_member_docs(
    project_id: str,
    filter_status_in_query: bool = False,
) -> list[tuple[str, dict]]:
    start = time.perf_counter()
    print(f"[PERF] project roster received project_id={project_id}")
    query = db.collection("crew_members").where(filter=FieldFilter("project_id", "==", project_id))
    if filter_status_in_query:
        query = query.where(filter=FieldFilter("status", "in", list(ACTIVE_PROJECT_MEMBER_STATUSES)))
    member_docs = [(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    member_docs = [
        (crew_member_id, data)
        for crew_member_id, data in member_docs
        if str(data.get("status", "")).upper() in {"ACTIVE", "ACCEPTED"}
    ]
    print(
        "[PERF] project roster Firestore crew_members query "
        f"(project_id={project_id}, status_filtered_in_query={filter_status_in_query}, reads={len(member_docs)}): "
        f"{(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return member_docs


def _list_project_member_docs(project_id: str) -> list[tuple[str, dict]]:
    start = time.perf_counter()
    member_docs = [
        (doc.id, doc.to_dict() or {})
        for doc in db.collection("crew_members")
        .where(filter=FieldFilter("project_id", "==", project_id))
        .stream()
    ]
    print(
        "[PERF] project CRM roster Firestore crew_members query "
        f"(project_id={project_id}, reads={len(member_docs)}): "
        f"{(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return member_docs


def _denormalized_project_identity(user_uid: str, fallback: dict | None = None) -> dict:
    fallback_data = fallback or {}
    return {
        "user_uid": user_uid,
        "name": _first_present(
            fallback_data,
            ("name", "display_name", "full_name", "nombre", "talent_name", "producer_name"),
        ),
        "email": _first_present(fallback_data, ("email", "talent_email")),
        "photo_url": _first_present(fallback_data, ("photo_url", "picture", "avatar_url"), None),
        "main_specialty": _first_present(fallback_data, ("main_specialty", "specialty")),
        "specialties": _normalize_text_list(fallback_data.get("specialties")),
    }


def _get_project_user_identity(user_uid: str, fallback: dict | None = None) -> dict:
    fallback_data = fallback or {}
    user_data: dict = {}
    profile_data: dict = {}

    if user_uid:
        user_doc = db.collection("users").document(user_uid).get()
        if user_doc.exists:
            user_data = user_doc.to_dict() or {}

        profile_doc = db.collection("talent_profiles").document(user_uid).get()
        if profile_doc.exists:
            profile_data = profile_doc.to_dict() or {}

    return {
        "user_uid": user_uid,
        "name": _first_present(
            profile_data,
            ("display_name", "name", "full_name", "nombre"),
            _first_present(
                user_data,
                ("name", "display_name", "full_name", "nombre"),
                _first_present(fallback_data, ("name", "display_name", "full_name", "nombre", "talent_name")),
            ),
        ),
        "email": _first_present(user_data, ("email",), _first_present(fallback_data, ("email", "talent_email"))),
        "photo_url": _first_present(
            profile_data,
            ("photo_url", "picture", "avatar_url"),
            _first_present(user_data, ("photo_url", "picture", "avatar_url"), None),
        ),
    }


def _get_project_user_identities(fallbacks_by_uid: dict[str, dict]) -> dict[str, dict]:
    start = time.perf_counter()
    fallbacks_by_uid = {
        user_uid: fallback
        for user_uid, fallback in fallbacks_by_uid.items()
        if user_uid
    }
    users_to_fetch = set(fallbacks_by_uid)
    profiles_to_fetch = set(fallbacks_by_uid)

    refs = [
        *[db.collection("users").document(user_uid) for user_uid in users_to_fetch],
        *[db.collection("talent_profiles").document(user_uid) for user_uid in profiles_to_fetch],
    ]
    users_by_uid: dict[str, dict] = {}
    profiles_by_uid: dict[str, dict] = {}
    for doc in db.get_all(refs) if refs else []:
        if not doc.exists:
            continue
        data = doc.to_dict() or {}
        if doc.reference.parent.id == "users":
            users_by_uid[doc.id] = data
        elif doc.reference.parent.id == "talent_profiles":
            profiles_by_uid[doc.id] = data

    identities: dict[str, dict] = {}
    for user_uid, fallback in fallbacks_by_uid.items():
        denormalized = _denormalized_project_identity(user_uid, fallback)
        user_data = users_by_uid.get(user_uid, {})
        profile_data = profiles_by_uid.get(user_uid, {})
        profile_summary = {
            "display_name": _first_present(profile_data, ("display_name", "name")),
            "bio": _first_present(profile_data, ("bio",)),
            "main_specialty": _first_present(profile_data, ("main_specialty", "specialty")),
            "specialties": _normalize_text_list(profile_data.get("specialties")),
            "skills": _normalize_text_list(profile_data.get("skills")),
            "languages": _normalize_text_list(profile_data.get("languages")),
            "experience_years": profile_data.get("experience_years"),
            "photo_url": _first_present(profile_data, ("photo_url", "picture"), None),
            "portfolio_links": profile_data.get("portfolio_links") or [],
            "portfolio_pdf_url": profile_data.get("portfolio_pdf_url"),
        }
        identities[user_uid] = {
            "user_uid": user_uid,
            "name": _first_present(
                profile_data,
                ("display_name", "name", "full_name", "nombre"),
                _first_present(
                    user_data,
                    ("name", "display_name", "full_name", "nombre"),
                    denormalized["name"],
                ),
            ),
            "email": _first_present(
                user_data,
                ("email",),
                _first_present(profile_data, ("email",), denormalized["email"]),
            ),
            "photo_url": _first_present(
                profile_data,
                ("photo_url", "picture"),
                _first_present(
                    user_data,
                    ("photo_url", "picture", "avatar_url"),
                    denormalized["photo_url"],
                ),
            ),
            "main_specialty": profile_summary["main_specialty"]
            or denormalized["main_specialty"],
            "specialties": profile_summary["specialties"]
            or denormalized["specialties"],
            "profile": profile_summary,
            "talent_profile": profile_summary,
        }

    print(
        "[PERF] project roster Firestore identity batch "
        f"(requested={len(refs)}, users={len(users_by_uid)}, profiles={len(profiles_by_uid)}): "
        f"{(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return identities


def _project_owner_uid(project_data: dict) -> str:
    return (
        project_data.get("owner_uid")
        or project_data.get("created_by")
        or project_data.get("producer_id")
        or project_data.get("owner_id")
        or project_data.get("user_id")
        or ""
    )


def _producer_project_participant(
    project_id: str,
    project_data: dict,
    identity: dict | None = None,
    hydrate_identity: bool = True,
) -> dict:
    owner_uid = _project_owner_uid(project_data)
    resolved_identity = identity or (
        _get_project_user_identity(owner_uid, project_data)
        if hydrate_identity
        else _denormalized_project_identity(owner_uid, project_data)
    )
    return {
        **resolved_identity,
        "id": f"{project_id}__producer__{owner_uid}",
        "project_id": project_id,
        "user_id": owner_uid,
        "talent_user_id": "",
        "talent_uid": None,
        "role": "PRODUCER",
        "category": "PRODUCTION",
        "category_label": get_crew_category_label("PRODUCTION"),
        "task_description": None,
        "status": "ACTIVE",
        "joined_at": serialize_date(project_data.get("created_at")),
        "opportunity_title": None,
        "application_status": None,
    }


def _talent_project_participant(
    project_id: str,
    crew_member_id: str,
    data: dict,
    identity: dict | None = None,
    hydrate_identity: bool = True,
) -> dict:
    talent_uid = get_talent_uid_from_data(data) or ""
    category = _crew_category_from_data(data)
    resolved_identity = identity or (
        _get_project_user_identity(talent_uid, data)
        if hydrate_identity
        else _denormalized_project_identity(talent_uid, data)
    )
    return {
        **resolved_identity,
        "id": data.get("id") or crew_member_id,
        "project_id": project_id,
        "user_id": talent_uid,
        "talent_user_id": talent_uid,
        "talent_uid": talent_uid,
        "role": data.get("role"),
        "category": category,
        "category_label": get_crew_category_label(category),
        "task_description": data.get("task_description"),
        "status": data.get("status", ""),
        "joined_at": serialize_date(data.get("joined_at") or data.get("created_at")),
        "opportunity_title": data.get("opportunity_title"),
        "application_status": data.get("application_status"),
    }


def _get_project_participant(
    project_id: str,
    user_uid: str,
    project_data: dict,
    member_docs: list[tuple[str, dict]],
    hydrate_identity: bool = True,
) -> dict | None:
    if _project_owner_uid(project_data) == user_uid:
        return _producer_project_participant(project_id, project_data, hydrate_identity=hydrate_identity)

    for crew_member_id, data in member_docs:
        if (data.get("talent_user_id") or data.get("talent_uid")) == user_uid:
            return _talent_project_participant(
                project_id,
                crew_member_id,
                data,
                hydrate_identity=hydrate_identity,
            )

    return None


def _validate_project_access(
    project_id: str,
    current_user: CurrentUser,
    hydrate_participant: bool = True,
    filter_member_status_in_query: bool = False,
) -> tuple[dict, list[tuple[str, dict]], dict]:
    project_data = _get_project_data(project_id)
    member_docs = _list_active_project_member_docs(project_id, filter_status_in_query=filter_member_status_in_query)
    participant = _get_project_participant(
        project_id,
        current_user.uid,
        project_data,
        member_docs,
        hydrate_identity=hydrate_participant,
    )

    is_owner = _is_project_owner(project_data, current_user)
    is_active_talent = current_user.role.value == "TALENT" and any(
        (data.get("talent_user_id") or data.get("talent_uid")) == current_user.uid
        for _, data in member_docs
    )
    if not is_owner and not is_active_talent:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre este proyecto")

    return project_data, member_docs, participant


def _is_project_owner(project_data: dict, current_user: CurrentUser) -> bool:
    return current_user.role.value == "PRODUCER" and _project_owner_uid(project_data) == current_user.uid


def _validate_project_owner(project_id: str, current_user: CurrentUser) -> dict:
    project_data = _get_project_data(project_id)
    if not _is_project_owner(project_data, current_user):
        raise HTTPException(status_code=403, detail="Solo el productor dueno puede editar el crew del proyecto")
    return project_data


def _get_project_crew_member_doc(project_id: str, crew_member_id: str):
    crew_member_doc = _get_crew_member_doc(crew_member_id)
    crew_member_data = crew_member_doc.to_dict() or {}
    if crew_member_data.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="Integrante de equipo no encontrado en este proyecto")
    return crew_member_doc, crew_member_data


def _applications_by_id(application_ids: set[str]) -> dict[str, dict]:
    return _get_documents_by_id("applications", application_ids)


def _project_crew_member_response(
    project_id: str,
    crew_member_id: str,
    data: dict,
) -> ProjectCrewMemberResponse:
    talent_uid = get_talent_uid_from_data(data) or ""
    identity = _get_project_user_identities({talent_uid: data}).get(talent_uid)
    application_status = None
    if data.get("application_id"):
        application_status = _applications_by_id({data.get("application_id")}).get(
            data.get("application_id"),
            {},
        ).get("status")

    return ProjectCrewMemberResponse(
        **_talent_project_participant(
            project_id,
            crew_member_id,
            {
                **data,
                "application_status": application_status,
            },
            identity,
        )
    )


def list_project_members(project_id: str, current_user: CurrentUser) -> ProjectCrewMembersResponse:
    start = time.perf_counter()
    project_data = _get_project_data(project_id)
    if _is_project_owner(project_data, current_user):
        member_docs = _list_project_member_docs(project_id)
    else:
        _, member_docs, _ = _validate_project_access(
            project_id,
            current_user,
            hydrate_participant=False,
            filter_member_status_in_query=True,
        )
    member_docs = _resolve_crew_talent_uids(member_docs)
    owner_uid = _project_owner_uid(project_data)
    fallbacks_by_uid = {
        **({owner_uid: project_data} if owner_uid else {}),
        **{
            get_talent_uid_from_data(data) or "": data
            for _, data in member_docs
            if get_talent_uid_from_data(data)
        },
    }
    identities_by_uid = _get_project_user_identities(fallbacks_by_uid)
    applications_by_id = _applications_by_id(
        {
            data.get("application_id")
            for _, data in member_docs
            if data.get("application_id")
        }
    )
    items = [
        ProjectCrewMemberResponse(
            **_producer_project_participant(project_id, project_data, identities_by_uid.get(owner_uid))
        ),
        *[
            ProjectCrewMemberResponse(
                **_talent_project_participant(
                    project_id,
                    crew_member_id,
                    {
                        **data,
                        "application_status": applications_by_id.get(data.get("application_id"), {}).get("status"),
                    },
                    identities_by_uid.get(get_talent_uid_from_data(data) or ""),
                )
            )
            for crew_member_id, data in member_docs
        ],
    ]
    print(
        "[PERF] project roster response "
        f"(project_id={project_id}, crew_members={len(member_docs)}, items={len(items)}): "
        f"{(time.perf_counter() - start) * 1000:.2f} ms"
    )
    return ProjectCrewMembersResponse(items=items)


def _serialize_project_chat_message(message_id: str, data: dict) -> ProjectChatMessageResponse:
    return ProjectChatMessageResponse(
        id=data.get("id") or message_id,
        project_id=data.get("project_id", ""),
        sender_uid=data.get("sender_uid", ""),
        sender_name=data.get("sender_name", ""),
        sender_role=data.get("sender_role", ""),
        sender_photo_url=data.get("sender_photo_url"),
        message=data.get("message", ""),
        created_at=serialize_date(data.get("created_at")) or "",
    )


def list_project_chat_messages(project_id: str, current_user: CurrentUser) -> list[ProjectChatMessageResponse]:
    _validate_project_access(project_id, current_user)
    query = (
        db.collection("crew_project_messages")
        .where("project_id", "==", project_id)
        .order_by("created_at", direction=Query.DESCENDING)
        .limit(50)
    )
    items = [_serialize_project_chat_message(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at)


def create_project_chat_message(
    project_id: str,
    payload: ProjectMessageCreateRequest,
    current_user: CurrentUser,
) -> ProjectChatMessageResponse:
    project_data, member_docs, participant = _validate_project_access(project_id, current_user)
    message_ref = db.collection("crew_project_messages").document()
    message_data = {
        "id": message_ref.id,
        "project_id": project_id,
        "sender_uid": current_user.uid,
        "sender_name": participant.get("name", ""),
        "sender_role": participant.get("role") or current_user.role.value,
        "sender_photo_url": participant.get("photo_url"),
        "message": payload.message,
        "created_at": utc_now_iso(),
    }
    batch = db.batch()
    batch.set(message_ref, message_data)
    _set_conversation_summary(
        batch,
        _team_conversation_id(project_id),
        {
            "type": "TEAM",
            "transport": "TEAM",
            "project_id": project_id,
            "participant_uids": [
                project_data.get("owner_uid", ""),
                *[
                    data.get("talent_user_id") or data.get("talent_uid", "")
                    for _, data in member_docs
                ],
            ],
        },
        payload.message,
        message_data["created_at"],
    )
    batch.commit()
    return ProjectChatMessageResponse(**message_data)


def _conversation_key(project_id: str, first_uid: str, second_uid: str) -> str:
    smaller_uid, larger_uid = sorted((first_uid, second_uid))
    return f"{project_id}__{smaller_uid}__{larger_uid}"


def _validate_direct_message_participants(
    project_id: str,
    other_user_uid: str,
    current_user: CurrentUser,
) -> tuple[dict, dict]:
    project_data, member_docs, sender = _validate_project_access(project_id, current_user)
    if other_user_uid == current_user.uid:
        raise HTTPException(status_code=400, detail="El destinatario debe ser otro integrante del proyecto")

    receiver = _get_project_participant(project_id, other_user_uid, project_data, member_docs)
    if receiver is None:
        raise HTTPException(status_code=403, detail="El destinatario no pertenece al proyecto")

    return sender, receiver


def _serialize_direct_message(message_id: str, data: dict) -> CrewDirectMessageResponse:
    return CrewDirectMessageResponse(
        id=data.get("id") or message_id,
        project_id=data.get("project_id", ""),
        conversation_key=data.get("conversation_key", ""),
        sender_uid=data.get("sender_uid", ""),
        receiver_uid=data.get("receiver_uid", ""),
        sender_name=data.get("sender_name", ""),
        receiver_name=data.get("receiver_name", ""),
        sender_photo_url=data.get("sender_photo_url"),
        receiver_photo_url=data.get("receiver_photo_url"),
        message=data.get("message", ""),
        created_at=serialize_date(data.get("created_at")) or "",
    )


def list_direct_messages(
    project_id: str,
    other_user_uid: str,
    current_user: CurrentUser,
) -> list[CrewDirectMessageResponse]:
    _validate_direct_message_participants(project_id, other_user_uid, current_user)
    conversation_key = _conversation_key(project_id, current_user.uid, other_user_uid)
    query = (
        db.collection("crew_direct_messages")
        .where("conversation_key", "==", conversation_key)
        .order_by("created_at", direction=Query.DESCENDING)
        .limit(50)
    )
    items = [_serialize_direct_message(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at)


def create_direct_message(
    project_id: str,
    other_user_uid: str,
    payload: ProjectMessageCreateRequest,
    current_user: CurrentUser,
) -> CrewDirectMessageResponse:
    sender, receiver = _validate_direct_message_participants(project_id, other_user_uid, current_user)
    message_ref = db.collection("crew_direct_messages").document()
    message_data = {
        "id": message_ref.id,
        "project_id": project_id,
        "conversation_key": _conversation_key(project_id, current_user.uid, other_user_uid),
        "sender_uid": current_user.uid,
        "receiver_uid": other_user_uid,
        "sender_name": sender.get("name", ""),
        "receiver_name": receiver.get("name", ""),
        "sender_photo_url": sender.get("photo_url"),
        "receiver_photo_url": receiver.get("photo_url"),
        "message": payload.message,
        "created_at": utc_now_iso(),
    }
    batch = db.batch()
    batch.set(message_ref, message_data)
    _set_conversation_summary(
        batch,
        _direct_conversation_id(message_data["conversation_key"]),
        {
            "type": "DIRECT",
            "transport": "DIRECT",
            "project_id": project_id,
            "conversation_key": message_data["conversation_key"],
            "participant_uids": [current_user.uid, other_user_uid],
            "participants": [
                _conversation_participant(sender),
                _conversation_participant(receiver),
            ],
        },
        payload.message,
        message_data["created_at"],
    )
    batch.commit()
    return CrewDirectMessageResponse(**message_data)


def _legacy_conversation_id(crew_member_id: str) -> str:
    return f"legacy__{crew_member_id}"


def _team_conversation_id(project_id: str) -> str:
    return f"team__{project_id}"


def _direct_conversation_id(conversation_key: str) -> str:
    return f"direct__{conversation_key}"


def _conversation_participant(identity: dict, role: str | None = None) -> dict:
    return {
        "user_uid": identity.get("user_uid", ""),
        "name": identity.get("name", ""),
        "avatar_url": identity.get("photo_url") or identity.get("avatar_url"),
        "role": role or identity.get("role"),
    }


def _unique_uids(user_uids: list[str]) -> list[str]:
    return list(dict.fromkeys(user_uid for user_uid in user_uids if user_uid))


def _set_conversation_summary(
    batch,
    conversation_id: str,
    summary_data: dict,
    last_message: str,
    last_message_at: str,
) -> None:
    summary_ref = db.collection("crew_conversations").document(conversation_id)
    batch.set(
        summary_ref,
        {
            **summary_data,
            "id": conversation_id,
            "participant_uids": _unique_uids(summary_data.get("participant_uids", [])),
            "last_message": last_message,
            "last_message_at": last_message_at,
            "updated_at": last_message_at,
        },
        merge=True,
    )


def _list_user_crew_member_docs(current_user: CurrentUser) -> list[tuple[str, dict]]:
    if current_user.role.value == "PRODUCER":
        query = db.collection("crew_members").where(filter=FieldFilter("producer_id", "==", current_user.uid))
    elif current_user.role.value == "TALENT":
        query = db.collection("crew_members").where(filter=FieldFilter("talent_user_id", "==", current_user.uid))
    else:
        raise HTTPException(status_code=403, detail="Rol no autorizado para conversaciones")
    return [(doc.id, doc.to_dict() or {}) for doc in query.stream()]


def _list_user_conversation_summaries(current_user: CurrentUser) -> dict[str, dict]:
    query = db.collection("crew_conversations").where(
        filter=FieldFilter("participant_uids", "array_contains", current_user.uid)
    )
    return {
        doc.id: data
        for doc in query.stream()
        if (data := (doc.to_dict() or {}))
    }


def _list_accessible_team_projects(
    current_user: CurrentUser,
    crew_member_docs: list[tuple[str, dict]],
) -> dict[str, dict]:
    projects_by_id: dict[str, dict] = {}
    if current_user.role.value == "PRODUCER":
        query = db.collection("projects").where(filter=FieldFilter("owner_uid", "==", current_user.uid))
        projects_by_id = {doc.id: doc.to_dict() or {} for doc in query.stream()}

    project_ids = {
        data.get("project_id")
        for _, data in crew_member_docs
        if data.get("project_id") and str(data.get("status", "")).upper() in {"ACTIVE", "ACCEPTED"}
    }
    missing_project_ids = project_ids - projects_by_id.keys()
    return {
        **projects_by_id,
        **_get_documents_by_id("projects", missing_project_ids),
    }


def _summary_participants(data: dict) -> list[MessageConversationParticipant]:
    return [
        MessageConversationParticipant(
            user_uid=participant.get("user_uid", ""),
            name=participant.get("name") or "",
            avatar_url=participant.get("avatar_url") or participant.get("photo_url"),
            role=participant.get("role"),
        )
        for participant in data.get("participants", [])
        if participant.get("user_uid")
    ]


def _get_team_chat_settings(project_ids: set[str]) -> dict[str, dict]:
    return _get_documents_by_id("crew_project_chat_settings", project_ids)


def _conversation_identities(
    crew_member_docs: list[tuple[str, dict]],
    summaries_by_id: dict[str, dict],
) -> dict[str, dict]:
    fallbacks_by_uid: dict[str, dict] = {}
    for _, data in crew_member_docs:
        producer_uid = data.get("producer_id")
        talent_uid = data.get("talent_user_id") or data.get("talent_uid")
        if producer_uid:
            fallbacks_by_uid.setdefault(producer_uid, {"name": data.get("producer_name")})
        if talent_uid:
            fallbacks_by_uid.setdefault(
                talent_uid,
                {
                    "name": data.get("talent_name"),
                    "email": data.get("talent_email"),
                    "photo_url": data.get("photo_url"),
                },
            )

    for data in summaries_by_id.values():
        for participant in data.get("participants", []):
            user_uid = participant.get("user_uid")
            if user_uid:
                fallbacks_by_uid.setdefault(user_uid, participant)

    return _get_project_user_identities(fallbacks_by_uid)


def _feed_participant(identity: dict, role: str | None = None) -> MessageConversationParticipant:
    return MessageConversationParticipant(
        user_uid=identity.get("user_uid", ""),
        name=identity.get("name") or "",
        avatar_url=identity.get("photo_url") or identity.get("avatar_url"),
        role=role or identity.get("role"),
    )


def _legacy_conversation_item(
    crew_member_id: str,
    crew_data: dict,
    summary_data: dict,
    project_data: dict,
    current_user: CurrentUser,
    identities_by_uid: dict[str, dict],
) -> MessageConversationItem:
    producer_uid = crew_data.get("producer_id", "")
    talent_uid = crew_data.get("talent_user_id") or crew_data.get("talent_uid", "")
    project_id = crew_data.get("project_id")
    project_title = crew_data.get("project_title") or project_data.get("title", "")
    counterpart_uid = talent_uid if current_user.uid == producer_uid else producer_uid
    counterpart = identities_by_uid.get(counterpart_uid, {})
    title = counterpart.get("name") or "Mensaje directo"
    participants = [
        _feed_participant(identities_by_uid.get(producer_uid, {"user_uid": producer_uid}), role="PRODUCER"),
        _feed_participant(identities_by_uid.get(talent_uid, {"user_uid": talent_uid}), role=crew_data.get("role")),
    ]
    return MessageConversationItem(
        id=_legacy_conversation_id(crew_member_id),
        type="DIRECT",
        project_id=project_id,
        project_title=project_title,
        title=title,
        subtitle=f"Proyecto {project_title}" if project_title else "Mensaje directo",
        avatar_url=counterpart.get("photo_url") or counterpart.get("avatar_url"),
        last_message=summary_data.get("last_message", ""),
        last_message_at=serialize_date(summary_data.get("last_message_at")),
        unread_count=0,
        participants=[participant for participant in participants if participant.user_uid],
    )


def _team_conversation_item(
    project_id: str,
    project_data: dict,
    summary_data: dict,
    settings_data: dict,
) -> MessageConversationItem:
    project_title = project_data.get("title", "")
    return MessageConversationItem(
        id=_team_conversation_id(project_id),
        type="TEAM",
        project_id=project_id,
        project_title=project_title,
        title=settings_data.get("name") or (f"Chat del equipo - {project_title}" if project_title else "Chat del equipo"),
        subtitle=f"Proyecto {project_title}" if project_title else "Proyecto",
        avatar_url=settings_data.get("photo_url"),
        last_message=summary_data.get("last_message", ""),
        last_message_at=serialize_date(summary_data.get("last_message_at")),
        unread_count=0,
        participants=_summary_participants(summary_data),
    )


def _direct_conversation_item(
    data: dict,
    project_data: dict,
    current_user: CurrentUser,
    identities_by_uid: dict[str, dict],
) -> MessageConversationItem:
    participants = [
        _feed_participant(
            identities_by_uid.get(participant.get("user_uid"), participant),
            role=participant.get("role"),
        )
        for participant in data.get("participants", [])
        if participant.get("user_uid")
    ]
    if not participants:
        participants = [
            _feed_participant(identities_by_uid.get(user_uid, {"user_uid": user_uid}))
            for user_uid in data.get("participant_uids", [])
            if user_uid
        ]
    counterpart = next((participant for participant in participants if participant.user_uid != current_user.uid), None)
    project_title = project_data.get("title", "")
    return MessageConversationItem(
        id=data.get("id", ""),
        type="DIRECT",
        project_id=data.get("project_id"),
        project_title=project_title,
        title=counterpart.name if counterpart and counterpart.name else "Mensaje directo",
        subtitle=f"Proyecto {project_title}" if project_title else "Mensaje directo",
        avatar_url=counterpart.avatar_url if counterpart else None,
        last_message=data.get("last_message", ""),
        last_message_at=serialize_date(data.get("last_message_at")),
        unread_count=0,
        participants=participants,
    )


def list_my_message_conversations(
    current_user: CurrentUser,
    limit: int = 20,
    cursor: str | None = None,
) -> MessageConversationFeedResponse:
    crew_member_docs = _list_user_crew_member_docs(current_user)
    summaries_by_id = _list_user_conversation_summaries(current_user)
    team_projects_by_id = _list_accessible_team_projects(current_user, crew_member_docs)
    static_summary_ids = {
        *[_legacy_conversation_id(crew_member_id) for crew_member_id, _ in crew_member_docs],
        *[_team_conversation_id(project_id) for project_id in team_projects_by_id],
    }
    summaries_by_id = {
        **_get_documents_by_id("crew_conversations", static_summary_ids - summaries_by_id.keys()),
        **summaries_by_id,
    }
    project_ids = {
        data.get("project_id")
        for _, data in crew_member_docs
        if data.get("project_id")
    } | {
        data.get("project_id")
        for data in summaries_by_id.values()
        if data.get("project_id")
    }
    projects_by_id = {
        **team_projects_by_id,
        **_get_documents_by_id("projects", project_ids - team_projects_by_id.keys()),
    }
    settings_by_project_id = _get_team_chat_settings(set(team_projects_by_id))
    identities_by_uid = _conversation_identities(crew_member_docs, summaries_by_id)

    new_direct_keys = {
        data.get("conversation_key")
        for data in summaries_by_id.values()
        if data.get("transport") == "DIRECT" and data.get("conversation_key")
    }
    items: list[MessageConversationItem] = []
    for crew_member_id, crew_data in crew_member_docs:
        project_id = crew_data.get("project_id")
        producer_uid = crew_data.get("producer_id", "")
        talent_uid = crew_data.get("talent_user_id") or crew_data.get("talent_uid", "")
        if project_id and producer_uid and talent_uid and _conversation_key(project_id, producer_uid, talent_uid) in new_direct_keys:
            continue
        summary_data = summaries_by_id.get(_legacy_conversation_id(crew_member_id), {})
        items.append(
            _legacy_conversation_item(
                crew_member_id,
                crew_data,
                summary_data,
                projects_by_id.get(project_id, {}),
                current_user,
                identities_by_uid,
            )
        )

    for project_id, project_data in team_projects_by_id.items():
        items.append(
            _team_conversation_item(
                project_id,
                project_data,
                summaries_by_id.get(_team_conversation_id(project_id), {}),
                settings_by_project_id.get(project_id, {}),
            )
        )

    items.extend(
        _direct_conversation_item(
            data,
            projects_by_id.get(data.get("project_id"), {}),
            current_user,
            identities_by_uid,
        )
        for data in summaries_by_id.values()
        if data.get("transport") == "DIRECT" and data.get("project_id") in team_projects_by_id
    )
    items.sort(
        key=lambda item: (
            item.last_message_at or "",
            item.id,
        ),
        reverse=True,
    )

    if cursor:
        cursor_index = next((index for index, item in enumerate(items) if item.id == cursor), None)
        if cursor_index is None:
            raise HTTPException(status_code=400, detail="Cursor de conversaciones invalido")
        items = items[cursor_index + 1:]

    page_items = items[:limit]
    return MessageConversationFeedResponse(
        items=page_items,
        next_cursor=page_items[-1].id if len(items) > limit and page_items else None,
    )


def _conversation_info_participant(
    identity: dict,
    *,
    role: str | None = None,
    task_description: str | None = None,
    status: str = "",
) -> MessageConversationInfoParticipant:
    return MessageConversationInfoParticipant(
        uid=identity.get("user_uid", ""),
        name=identity.get("name") or "",
        email=identity.get("email") or "",
        photo_url=identity.get("photo_url") or identity.get("avatar_url"),
        role=role or identity.get("role"),
        task_description=task_description,
        status=status,
    )


def _team_conversation_info(
    conversation_id: str,
    project_id: str,
    current_user: CurrentUser,
) -> MessageConversationInfoResponse:
    project_data, member_docs, _ = _validate_project_access(
        project_id,
        current_user,
        hydrate_participant=False,
    )
    owner_uid = project_data.get("owner_uid", "")
    fallbacks_by_uid = {
        **({owner_uid: project_data} if owner_uid else {}),
        **{
            data.get("talent_user_id") or data.get("talent_uid", ""): data
            for _, data in member_docs
            if data.get("talent_user_id") or data.get("talent_uid")
        },
    }
    identities_by_uid = _get_project_user_identities(fallbacks_by_uid)
    settings_data = _get_team_chat_settings({project_id}).get(project_id, {})
    project_title = project_data.get("title", "")
    participants = [
        _conversation_info_participant(
            identities_by_uid.get(owner_uid, {"user_uid": owner_uid}),
            role="PRODUCER",
            status="ACTIVE",
        ),
        *[
            _conversation_info_participant(
                identities_by_uid.get(
                    data.get("talent_user_id") or data.get("talent_uid", ""),
                    {"user_uid": data.get("talent_user_id") or data.get("talent_uid", "")},
                ),
                role=data.get("role"),
                task_description=data.get("task_description"),
                status=data.get("status", ""),
            )
            for _, data in member_docs
        ],
    ]
    return MessageConversationInfoResponse(
        id=conversation_id,
        type="TEAM",
        project_id=project_id,
        project_title=project_title,
        title=settings_data.get("name") or (f"Chat del equipo - {project_title}" if project_title else "Chat del equipo"),
        avatar_url=settings_data.get("photo_url"),
        participants=[participant for participant in participants if participant.uid],
    )


def _direct_conversation_info(
    conversation_id: str,
    project_id: str | None,
    participant_uids: list[str],
    fallbacks_by_uid: dict[str, dict],
    current_user: CurrentUser,
) -> MessageConversationInfoResponse:
    project_data = _get_project_data(project_id) if project_id else {}
    identities_by_uid = _get_project_user_identities(fallbacks_by_uid)
    counterpart_uid = next((user_uid for user_uid in participant_uids if user_uid != current_user.uid), "")
    counterpart = identities_by_uid.get(counterpart_uid, {"user_uid": counterpart_uid})
    return MessageConversationInfoResponse(
        id=conversation_id,
        type="DIRECT",
        project_id=project_id,
        project_title=project_data.get("title", ""),
        title=counterpart.get("name") or "Mensaje directo",
        avatar_url=counterpart.get("photo_url") or counterpart.get("avatar_url"),
        participants=[
            _conversation_info_participant(identities_by_uid.get(user_uid, {"user_uid": user_uid}))
            for user_uid in participant_uids
            if user_uid
        ],
    )


def get_unified_conversation_info(
    conversation_id: str,
    current_user: CurrentUser,
) -> MessageConversationInfoResponse:
    if conversation_id.startswith("team__"):
        project_id = conversation_id.removeprefix("team__")
        return _team_conversation_info(conversation_id, project_id, current_user)

    if conversation_id.startswith("legacy__"):
        crew_member_id = conversation_id.removeprefix("legacy__")
        _, crew_data = _validate_crew_access(crew_member_id, current_user)
        producer_uid = crew_data.get("producer_id", "")
        talent_uid = crew_data.get("talent_user_id") or crew_data.get("talent_uid", "")
        return _direct_conversation_info(
            conversation_id,
            crew_data.get("project_id"),
            [producer_uid, talent_uid],
            {
                producer_uid: {"name": crew_data.get("producer_name")},
                talent_uid: {
                    "name": crew_data.get("talent_name"),
                    "email": crew_data.get("talent_email"),
                    "photo_url": crew_data.get("photo_url"),
                },
            },
            current_user,
        )

    if conversation_id.startswith("direct__"):
        summary_data, project_id, _ = _direct_summary_context(conversation_id, current_user)
        participant_uids = summary_data.get("participant_uids", [])
        return _direct_conversation_info(
            conversation_id,
            project_id,
            participant_uids,
            {
                participant.get("user_uid", ""): participant
                for participant in summary_data.get("participants", [])
                if participant.get("user_uid")
            },
            current_user,
        )

    raise HTTPException(status_code=404, detail="Conversacion no encontrada")


def update_team_conversation_settings(
    conversation_id: str,
    payload: TeamChatSettingsUpdateRequest,
    current_user: CurrentUser,
) -> MessageConversationInfoResponse:
    project_id, project_data = _get_active_team_conversation_project(conversation_id, current_user)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Debes enviar name")
    if "photo_url" in updates:
        raise HTTPException(
            status_code=400,
            detail="photo_url esta obsoleto. Usa POST /messages/me/conversations/{conversation_id}/team-photo",
        )
    _validate_team_name_editor(project_data, current_user)

    settings_data = {
        "project_id": project_id,
        **updates,
        "updated_by": current_user.uid,
        "updated_at": utc_now_iso(),
    }
    db.collection("crew_project_chat_settings").document(project_id).set(settings_data, merge=True)
    return _team_conversation_info(conversation_id, project_id, current_user)


def _get_active_team_conversation_project(
    conversation_id: str,
    current_user: CurrentUser,
) -> tuple[str, dict]:
    if not conversation_id.startswith("team__"):
        raise HTTPException(status_code=400, detail="La configuracion solo aplica a chats de equipo")

    project_id = conversation_id.removeprefix("team__")
    project_data, _, _ = _validate_project_access(project_id, current_user, hydrate_participant=False)
    return project_id, project_data


def _validate_team_name_editor(project_data: dict, current_user: CurrentUser) -> None:
    if current_user.role.value != "PRODUCER" or project_data.get("owner_uid") != current_user.uid:
        raise HTTPException(status_code=403, detail="Solo el productor dueno puede editar el nombre del grupo")


def update_team_conversation_photo(
    conversation_id: str,
    photo_url: str,
    current_user: CurrentUser,
) -> TeamChatPhotoResponse:
    project_id, _ = _get_active_team_conversation_project(conversation_id, current_user)
    settings_data = {
        "project_id": project_id,
        "photo_url": photo_url,
        "updated_by": current_user.uid,
        "updated_at": utc_now_iso(),
    }
    db.collection("crew_project_chat_settings").document(project_id).set(settings_data, merge=True)
    return TeamChatPhotoResponse(photo_url=photo_url)


def validate_team_conversation_photo_access(
    conversation_id: str,
    current_user: CurrentUser,
) -> str:
    project_id, _ = _get_active_team_conversation_project(conversation_id, current_user)
    return project_id


def _get_conversation_summary(conversation_id: str) -> dict:
    summary_doc = db.collection("crew_conversations").document(conversation_id).get()
    if not summary_doc.exists:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada")
    return summary_doc.to_dict() or {}


def _list_latest_messages(query, serializer, limit: int) -> list[UnifiedConversationMessageResponse]:
    items = [serializer(doc.id, doc.to_dict() or {}) for doc in query.limit(limit).stream()]
    return sorted(items, key=lambda item: item.created_at)


def _unified_legacy_message(conversation_id: str, message_id: str, data: dict) -> UnifiedConversationMessageResponse:
    return UnifiedConversationMessageResponse(
        id=data.get("id") or message_id,
        conversation_id=conversation_id,
        sender_uid=data.get("sender_id", ""),
        sender_role=data.get("sender_role", ""),
        message=data.get("message", ""),
        created_at=serialize_date(data.get("created_at")) or "",
    )


def _unified_project_message(conversation_id: str, message_id: str, data: dict) -> UnifiedConversationMessageResponse:
    return UnifiedConversationMessageResponse(
        id=data.get("id") or message_id,
        conversation_id=conversation_id,
        sender_uid=data.get("sender_uid", ""),
        sender_name=data.get("sender_name", ""),
        sender_role=data.get("sender_role", ""),
        sender_photo_url=data.get("sender_photo_url"),
        message=data.get("message", ""),
        created_at=serialize_date(data.get("created_at")) or "",
    )


def _direct_summary_context(conversation_id: str, current_user: CurrentUser) -> tuple[dict, str, str]:
    summary_data = _get_conversation_summary(conversation_id)
    participant_uids = summary_data.get("participant_uids", [])
    if current_user.uid not in participant_uids:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre esta conversacion")
    other_user_uid = next((user_uid for user_uid in participant_uids if user_uid != current_user.uid), None)
    project_id = summary_data.get("project_id")
    if not project_id or not other_user_uid:
        raise HTTPException(status_code=400, detail="Conversacion directa invalida")
    _validate_direct_message_participants(project_id, other_user_uid, current_user)
    return summary_data, project_id, other_user_uid


def list_unified_conversation_messages(
    conversation_id: str,
    current_user: CurrentUser,
    limit: int = 50,
) -> list[UnifiedConversationMessageResponse]:
    if conversation_id.startswith("legacy__"):
        crew_member_id = conversation_id.removeprefix("legacy__")
        _validate_crew_access(crew_member_id, current_user)
        query = (
            db.collection("crew_messages")
            .where(filter=FieldFilter("crew_member_id", "==", crew_member_id))
            .order_by("created_at", direction=Query.DESCENDING)
        )
        return _list_latest_messages(
            query,
            lambda message_id, data: _unified_legacy_message(conversation_id, message_id, data),
            limit,
        )

    if conversation_id.startswith("team__"):
        project_id = conversation_id.removeprefix("team__")
        _validate_project_access(project_id, current_user)
        query = (
            db.collection("crew_project_messages")
            .where(filter=FieldFilter("project_id", "==", project_id))
            .order_by("created_at", direction=Query.DESCENDING)
        )
        return _list_latest_messages(
            query,
            lambda message_id, data: _unified_project_message(conversation_id, message_id, data),
            limit,
        )

    if conversation_id.startswith("direct__"):
        summary_data, _, _ = _direct_summary_context(conversation_id, current_user)
        query = (
            db.collection("crew_direct_messages")
            .where(filter=FieldFilter("conversation_key", "==", summary_data.get("conversation_key")))
            .order_by("created_at", direction=Query.DESCENDING)
        )
        return _list_latest_messages(
            query,
            lambda message_id, data: _unified_project_message(conversation_id, message_id, data),
            limit,
        )

    raise HTTPException(status_code=404, detail="Conversacion no encontrada")


def create_unified_conversation_message(
    conversation_id: str,
    payload: ProjectMessageCreateRequest,
    current_user: CurrentUser,
) -> UnifiedConversationMessageResponse:
    if conversation_id.startswith("legacy__"):
        message = create_crew_message(conversation_id.removeprefix("legacy__"), payload, current_user)
        return _unified_legacy_message(conversation_id, message.id, message.model_dump())

    if conversation_id.startswith("team__"):
        message = create_project_chat_message(conversation_id.removeprefix("team__"), payload, current_user)
        return _unified_project_message(conversation_id, message.id, message.model_dump())

    if conversation_id.startswith("direct__"):
        _, project_id, other_user_uid = _direct_summary_context(conversation_id, current_user)
        message = create_direct_message(project_id, other_user_uid, payload, current_user)
        return _unified_project_message(conversation_id, message.id, message.model_dump())

    raise HTTPException(status_code=404, detail="Conversacion no encontrada")
