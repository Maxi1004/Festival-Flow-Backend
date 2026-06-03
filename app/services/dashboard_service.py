from collections.abc import Mapping, Sequence

from google.cloud.firestore_v1 import Query
from google.cloud.firestore_v1.base_query import FieldFilter, Or

from app.core.firebase import db
from app.core.utils import serialize_date
from app.schemas.auth_schema import CurrentUser
from app.schemas.dashboard_schema import (
    DashboardApplicationSummary,
    DashboardAvailableTalentSummary,
    DashboardOpportunitySummary,
    DashboardProjectSummary,
    DashboardTalentProfileSummary,
    ProducerDashboardResponse,
    TalentDashboardResponse,
)
from app.services.talent_service import (
    AvailabilityStatus,
    _normalize_travel_availability,
    _normalize_work_modality,
    _serialize_available_from,
)


PRODUCER_TALENT_PREVIEW_LIMIT = 6
RECENT_PROJECTS_LIMIT = 3
DASHBOARD_DETAIL_LIMIT = 5


def _extract_count(result) -> int | None:
    if result is None:
        return None

    if isinstance(result, (int, float)):
        return int(result)

    if isinstance(result, Mapping):
        for key in ("value", "total", "count", "field", "alias"):
            if key in result:
                count = _extract_count(result[key])
                if count is not None:
                    return count

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

    for attribute in ("value", "total", "count", "field", "alias"):
        if hasattr(result, attribute):
            count = _extract_count(getattr(result, attribute))
            if count is not None:
                return count

    try:
        return int(result)
    except (TypeError, ValueError):
        return None


def _count_query(query) -> int:
    result = query.count(alias="total").get()
    return _extract_count(result) or 0


def _owner_filter(user_id: str) -> Or:
    return Or(
        [
            FieldFilter("owner_uid", "==", user_id),
            FieldFilter("created_by", "==", user_id),
            FieldFilter("producer_id", "==", user_id),
            FieldFilter("owner_id", "==", user_id),
            FieldFilter("user_id", "==", user_id),
        ]
    )


def _talent_filter(user_id: str) -> Or:
    return Or(
        [
            FieldFilter("talent_uid", "==", user_id),
            FieldFilter("talent_user_id", "==", user_id),
            FieldFilter("user_id", "==", user_id),
            FieldFilter("user_uid", "==", user_id),
            FieldFilter("talent_id", "==", user_id),
        ]
    )


def _list_recent_projects(current_user: CurrentUser) -> list[DashboardProjectSummary]:
    query = (
        db.collection("projects")
        .where(filter=FieldFilter("owner_uid", "==", current_user.uid))
        .order_by("created_at", direction=Query.DESCENDING)
        .limit(RECENT_PROJECTS_LIMIT)
    )

    return [
        DashboardProjectSummary(
            id=data.get("id") or doc.id,
            title=data.get("title", ""),
            production_type=data.get("production_type", ""),
            location=data.get("location", ""),
            start_date=serialize_date(data.get("start_date")),
        )
        for doc in query.stream()
        for data in [doc.to_dict() or {}]
    ]


def _list_opportunities(query) -> list[DashboardOpportunitySummary]:
    return [
        DashboardOpportunitySummary(
            id=data.get("id") or doc.id,
            project_id=data.get("project_id"),
            title=data.get("title", ""),
            role_needed=data.get("role_needed", ""),
            specialty=data.get("specialty", ""),
            location=data.get("location", ""),
            status=data.get("status", ""),
        )
        for doc in query.order_by("__name__").limit(DASHBOARD_DETAIL_LIMIT).stream()
        for data in [doc.to_dict() or {}]
    ]


def _list_applications(query) -> list[DashboardApplicationSummary]:
    items: list[DashboardApplicationSummary] = []

    for doc in query.order_by("__name__").limit(DASHBOARD_DETAIL_LIMIT).stream():
        data = doc.to_dict() or {}
        opportunity_id = data.get("opportunity_id", "")
        opportunity_data = {}

        if opportunity_id:
            opportunity_doc = db.collection("opportunities").document(opportunity_id).get()
            opportunity_data = opportunity_doc.to_dict() or {} if opportunity_doc.exists else {}

        items.append(
            DashboardApplicationSummary(
                id=data.get("id") or doc.id,
                opportunity_id=opportunity_id,
                opportunity_title=opportunity_data.get("title", ""),
                status=data.get("status", ""),
                message=data.get("message", ""),
                applied_at=serialize_date(data.get("applied_at") or data.get("created_at")),
            )
        )

    return items


def _list_available_talent_previews() -> list[DashboardAvailableTalentSummary]:
    available_values = ["AVAILABLE", "available", "Disponible", "disponible", "Si", "si", "Sí", "sí"]
    query = (
        db.collection("talent_availability")
        .where(
            filter=Or(
                [
                    FieldFilter("status", "in", available_values),
                    FieldFilter("availability_status", "in", available_values),
                ]
            )
        )
        .order_by("__name__")
        .limit(PRODUCER_TALENT_PREVIEW_LIMIT)
    )
    items: list[DashboardAvailableTalentSummary] = []

    for availability_doc in query.stream():
        availability_data = availability_doc.to_dict() or {}
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
            DashboardAvailableTalentSummary(
                user_id=user_id,
                name=user_data.get("name", ""),
                email=user_data.get("email", ""),
                status=AvailabilityStatus.AVAILABLE,
                travel_availability=_normalize_travel_availability(
                    availability_data.get("travel_availability", availability_data.get("available_to_travel", False))
                ),
                work_modality=_normalize_work_modality(
                    availability_data.get("work_modality") or availability_data.get("modality")
                ),
                location=availability_data.get("location") or availability_data.get("work_location"),
                available_from=_serialize_available_from(availability_data.get("available_from")),
                notes=availability_data.get("notes"),
                profile=DashboardTalentProfileSummary(
                    specialties=profile_data.get("specialties", []),
                ),
            )
        )

    return items


def get_producer_dashboard(current_user: CurrentUser) -> ProducerDashboardResponse:
    projects_query = db.collection("projects").where(filter=FieldFilter("owner_uid", "==", current_user.uid))
    opportunities_query = db.collection("opportunities").where(filter=_owner_filter(current_user.uid))
    active_opportunities_query = opportunities_query.where(filter=FieldFilter("status", "in", ["ACTIVE", "OPEN"]))
    closed_opportunities_query = opportunities_query.where(filter=FieldFilter("status", "in", ["CANCELLED", "CLOSED"]))

    return ProducerDashboardResponse(
        projects_count=_count_query(projects_query),
        opportunities_count=_count_query(opportunities_query),
        active_opportunities_count=_count_query(active_opportunities_query),
        closed_opportunities_count=_count_query(closed_opportunities_query),
        latest_projects=_list_recent_projects(current_user),
        active_opportunities=_list_opportunities(active_opportunities_query),
        closed_opportunities=_list_opportunities(closed_opportunities_query),
        available_talents=_list_available_talent_previews(),
    )


def get_talent_dashboard(current_user: CurrentUser) -> TalentDashboardResponse:
    profile_doc = db.collection("talent_profiles").document(current_user.uid).get()
    profile_data = profile_doc.to_dict() or {} if profile_doc.exists else {}
    applications_query = db.collection("applications").where(filter=_talent_filter(current_user.uid))
    opportunities_query = db.collection("opportunities").where(filter=FieldFilter("status", "==", "ACTIVE"))

    return TalentDashboardResponse(
        profile_completion=profile_data.get("profile_completion", 0),
        main_specialty=profile_data.get("main_specialty", ""),
        location=profile_data.get("location", ""),
        applications_count=_count_query(applications_query),
        opportunities_count=_count_query(opportunities_query),
        available_opportunities=_list_opportunities(opportunities_query),
        applications=_list_applications(applications_query),
    )
