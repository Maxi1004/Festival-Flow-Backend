from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
import time

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
    ProducerDashboardDetailsResponse,
    ProducerDashboardQuickResponse,
    ProducerDashboardResponse,
    TalentDashboardDetailsResponse,
    TalentDashboardQuickResponse,
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


def _perf_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


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


def _list_recent_projects(
    current_user: CurrentUser,
    perf_label: str | None = None,
) -> list[DashboardProjectSummary]:
    query = (
        db.collection("projects")
        .where(filter=FieldFilter("owner_uid", "==", current_user.uid))
        .order_by("created_at", direction=Query.DESCENDING)
        .limit(RECENT_PROJECTS_LIMIT)
    )

    query_start = time.perf_counter()
    docs = list(query.stream())
    if perf_label:
        print(f"[PERF] {perf_label} latest projects query: {_perf_ms(query_start):.2f} ms")

    serialize_start = time.perf_counter()
    items = [
        DashboardProjectSummary(
            id=data.get("id") or doc.id,
            title=data.get("title", ""),
            production_type=data.get("production_type", ""),
            location=data.get("location", ""),
            start_date=serialize_date(data.get("start_date")),
        )
        for doc in docs
        for data in [doc.to_dict() or {}]
    ]
    if perf_label:
        print(f"[PERF] {perf_label} latest projects serialize: {_perf_ms(serialize_start):.2f} ms")

    return items


def _list_opportunities(query, perf_label: str | None = None) -> list[DashboardOpportunitySummary]:
    start = time.perf_counter()
    docs = list(query.order_by("__name__").limit(DASHBOARD_DETAIL_LIMIT).stream())
    if perf_label:
        print(f"[PERF] {perf_label} list opportunities query: {_perf_ms(start):.2f} ms")

    serialize_start = time.perf_counter()
    items = [
        DashboardOpportunitySummary(
            id=data.get("id") or doc.id,
            project_id=data.get("project_id"),
            title=data.get("title", ""),
            role_needed=data.get("role_needed", ""),
            specialty=data.get("specialty", ""),
            location=data.get("location", ""),
            status=data.get("status", ""),
        )
        for doc in docs
        for data in [doc.to_dict() or {}]
    ]
    if perf_label:
        print(f"[PERF] {perf_label} list opportunities serialize: {_perf_ms(serialize_start):.2f} ms")

    return items


def _list_applications(query, perf_label: str | None = None) -> list[DashboardApplicationSummary]:
    query_start = time.perf_counter()
    docs = list(query.order_by("__name__").limit(DASHBOARD_DETAIL_LIMIT).stream())
    application_rows = [(doc, doc.to_dict() or {}) for doc in docs]
    if perf_label:
        print(f"[PERF] {perf_label} list applications query: {_perf_ms(query_start):.2f} ms")

    opportunity_ids = {
        opportunity_id
        for _, data in application_rows
        for opportunity_id in [data.get("opportunity_id")]
        if opportunity_id
    }
    opportunity_by_id = {}

    batch_start = time.perf_counter()
    if opportunity_ids:
        opportunity_refs = [
            db.collection("opportunities").document(opportunity_id)
            for opportunity_id in opportunity_ids
        ]
        for opportunity_doc in db.get_all(opportunity_refs):
            if opportunity_doc.exists:
                opportunity_by_id[opportunity_doc.id] = opportunity_doc.to_dict() or {}

    if perf_label:
        print(
            f"[PERF] {perf_label} batch opportunities "
            f"(count={len(opportunity_ids)}): {_perf_ms(batch_start):.2f} ms"
        )

    serialize_start = time.perf_counter()
    items: list[DashboardApplicationSummary] = []
    for doc, data in application_rows:
        opportunity_id = data.get("opportunity_id", "")
        opportunity_data = opportunity_by_id.get(opportunity_id, {})

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

    if perf_label:
        print(f"[PERF] {perf_label} list applications serialize: {_perf_ms(serialize_start):.2f} ms")

    return items


def _list_available_talent_previews(perf_label: str | None = None) -> list[DashboardAvailableTalentSummary]:
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

    query_start = time.perf_counter()
    availability_docs = list(query.stream())
    availability_rows = [(doc, doc.to_dict() or {}) for doc in availability_docs]
    if perf_label:
        print(f"[PERF] {perf_label} available talents query: {_perf_ms(query_start):.2f} ms")

    user_ids = {
        user_id
        for availability_doc, availability_data in availability_rows
        for user_id in [
            availability_data.get("user_id")
            or availability_data.get("user_uid")
            or availability_doc.id
        ]
        if user_id
    }
    users_by_id = {}
    profiles_by_id = {}

    users_start = time.perf_counter()
    if user_ids:
        user_refs = [db.collection("users").document(user_id) for user_id in user_ids]
        for user_doc in db.get_all(user_refs):
            if user_doc.exists:
                users_by_id[user_doc.id] = user_doc.to_dict() or {}

    if perf_label:
        print(
            f"[PERF] {perf_label} available talents users batch "
            f"(count={len(user_ids)}): {_perf_ms(users_start):.2f} ms"
        )

    talent_user_ids = {
        user_id
        for user_id, user_data in users_by_id.items()
        if user_data.get("role") == "TALENT"
    }

    profiles_start = time.perf_counter()
    if talent_user_ids:
        profile_refs = [db.collection("talent_profiles").document(user_id) for user_id in talent_user_ids]
        for profile_doc in db.get_all(profile_refs):
            if profile_doc.exists:
                profiles_by_id[profile_doc.id] = profile_doc.to_dict() or {}

    if perf_label:
        print(
            f"[PERF] {perf_label} available talents profiles batch "
            f"(count={len(talent_user_ids)}): {_perf_ms(profiles_start):.2f} ms"
        )

    serialize_start = time.perf_counter()
    items: list[DashboardAvailableTalentSummary] = []

    for availability_doc, availability_data in availability_rows:
        user_id = availability_data.get("user_id") or availability_data.get("user_uid") or availability_doc.id
        user_data = users_by_id.get(user_id)
        if not user_data:
            continue

        if user_data.get("role") != "TALENT":
            continue

        profile_data = profiles_by_id.get(user_id, {})
        profile_summary_data = availability_data.get("profile") or {}
        specialties = (
            availability_data.get("specialties")
            or profile_summary_data.get("specialties")
            or profile_data.get("specialties", [])
        )
        profile_photo_url = _clean_image_url(profile_data.get("photo_url"))
        user_picture = _clean_image_url(user_data.get("picture"))
        profile_picture = _clean_image_url(profile_data.get("picture"))
        profile_avatar_url = _clean_image_url(profile_data.get("avatar_url"))
        photo_url = profile_photo_url or user_picture or profile_picture or profile_avatar_url

        items.append(
            DashboardAvailableTalentSummary(
                user_id=user_id,
                name=availability_data.get("name") or user_data.get("name", ""),
                email=availability_data.get("email") or user_data.get("email", ""),
                photo_url=photo_url,
                picture=user_picture or profile_picture,
                avatar_url=profile_avatar_url,
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
                    specialties=specialties,
                ),
            )
        )

    if perf_label:
        print(f"[PERF] {perf_label} available talents serialize: {_perf_ms(serialize_start):.2f} ms")

    return items


def _clean_image_url(value: object) -> str | None:
    if isinstance(value, str):
        cleaned_value = value.strip()
        return cleaned_value or None

    return None


def _build_producer_queries(current_user: CurrentUser):
    projects_query = db.collection("projects").where(filter=FieldFilter("owner_uid", "==", current_user.uid))
    opportunities_query = db.collection("opportunities").where(filter=_owner_filter(current_user.uid))
    active_opportunities_query = opportunities_query.where(filter=FieldFilter("status", "in", ["ACTIVE", "OPEN"]))
    closed_opportunities_query = opportunities_query.where(filter=FieldFilter("status", "in", ["CANCELLED", "CLOSED"]))
    return projects_query, opportunities_query, active_opportunities_query, closed_opportunities_query


def get_producer_dashboard_quick(current_user: CurrentUser) -> ProducerDashboardQuickResponse:
    start = time.perf_counter()
    (
        projects_query,
        opportunities_query,
        active_opportunities_query,
        closed_opportunities_query,
    ) = _build_producer_queries(current_user)

    with ThreadPoolExecutor(max_workers=4) as executor:
        projects_count_future = executor.submit(
            _count_query_with_perf,
            projects_query,
            "producer dashboard quick projects count",
        )
        opportunities_count_future = executor.submit(
            _count_query_with_perf,
            opportunities_query,
            "producer dashboard quick opportunities count",
        )
        active_opportunities_count_future = executor.submit(
            _count_query_with_perf,
            active_opportunities_query,
            "producer dashboard quick active opportunities count",
        )
        closed_opportunities_count_future = executor.submit(
            _count_query_with_perf,
            closed_opportunities_query,
            "producer dashboard quick closed opportunities count",
        )
        projects_count = projects_count_future.result()
        opportunities_count = opportunities_count_future.result()
        active_opportunities_count = active_opportunities_count_future.result()
        closed_opportunities_count = closed_opportunities_count_future.result()

    serialize_start = time.perf_counter()
    response = ProducerDashboardQuickResponse(
        projects_count=projects_count,
        opportunities_count=opportunities_count,
        active_opportunities_count=active_opportunities_count,
        closed_opportunities_count=closed_opportunities_count,
    )
    print(f"[PERF] producer dashboard quick serialize: {_perf_ms(serialize_start):.2f} ms")
    print(f"[PERF] producer dashboard quick total: {_perf_ms(start):.2f} ms")
    return response


def get_producer_dashboard_details(current_user: CurrentUser) -> ProducerDashboardDetailsResponse:
    start = time.perf_counter()
    _, _, active_opportunities_query, closed_opportunities_query = _build_producer_queries(current_user)

    with ThreadPoolExecutor(max_workers=4) as executor:
        latest_projects_future = executor.submit(
            _list_recent_projects,
            current_user,
            "producer dashboard details",
        )
        active_opportunities_future = executor.submit(
            _list_opportunities,
            active_opportunities_query,
            "producer dashboard details active opportunities",
        )
        closed_opportunities_future = executor.submit(
            _list_opportunities,
            closed_opportunities_query,
            "producer dashboard details closed opportunities",
        )
        available_talents_future = executor.submit(
            _list_available_talent_previews,
            "producer dashboard details",
        )
        latest_projects = latest_projects_future.result()
        active_opportunities = active_opportunities_future.result()
        closed_opportunities = closed_opportunities_future.result()
        available_talents = available_talents_future.result()

    serialize_start = time.perf_counter()
    response = ProducerDashboardDetailsResponse(
        latest_projects=latest_projects,
        active_opportunities=active_opportunities,
        closed_opportunities=closed_opportunities,
        available_talents=available_talents,
    )
    print(f"[PERF] producer dashboard details serialize: {_perf_ms(serialize_start):.2f} ms")
    print(f"[PERF] producer dashboard details total: {_perf_ms(start):.2f} ms")
    return response


def get_producer_dashboard(current_user: CurrentUser) -> ProducerDashboardResponse:
    start = time.perf_counter()
    quick = get_producer_dashboard_quick(current_user)
    details = get_producer_dashboard_details(current_user)

    serialize_start = time.perf_counter()
    response = ProducerDashboardResponse(
        projects_count=quick.projects_count,
        opportunities_count=quick.opportunities_count,
        active_opportunities_count=quick.active_opportunities_count,
        closed_opportunities_count=quick.closed_opportunities_count,
        latest_projects=details.latest_projects,
        active_opportunities=details.active_opportunities,
        closed_opportunities=details.closed_opportunities,
        available_talents=details.available_talents,
    )
    print(f"[PERF] producer dashboard full serialize: {_perf_ms(serialize_start):.2f} ms")
    print(f"[PERF] producer dashboard full total: {_perf_ms(start):.2f} ms")
    return response


def _build_talent_queries(current_user: CurrentUser):
    applications_query = db.collection("applications").where(filter=_talent_filter(current_user.uid))
    opportunities_query = db.collection("opportunities").where(filter=FieldFilter("status", "==", "ACTIVE"))
    return applications_query, opportunities_query


def _count_query_with_perf(query, label: str) -> int:
    start = time.perf_counter()
    count = _count_query(query)
    print(f"[PERF] {label}: {_perf_ms(start):.2f} ms")
    return count


def _read_talent_profile_with_perf(user_id: str, label: str) -> dict:
    start = time.perf_counter()
    profile_doc = db.collection("talent_profiles").document(user_id).get()
    profile_data = profile_doc.to_dict() or {} if profile_doc.exists else {}
    print(f"[PERF] {label}: {_perf_ms(start):.2f} ms")
    return profile_data


def _get_talent_dashboard_quick_data(current_user: CurrentUser, perf_label: str) -> TalentDashboardQuickResponse:
    applications_query, opportunities_query = _build_talent_queries(current_user)

    with ThreadPoolExecutor(max_workers=3) as executor:
        profile_future = executor.submit(
            _read_talent_profile_with_perf,
            current_user.uid,
            f"{perf_label} profile read",
        )
        applications_count_future = executor.submit(
            _count_query_with_perf,
            applications_query,
            f"{perf_label} applications count",
        )
        opportunities_count_future = executor.submit(
            _count_query_with_perf,
            opportunities_query,
            f"{perf_label} opportunities count",
        )
        profile_data = profile_future.result()
        applications_count = applications_count_future.result()
        opportunities_count = opportunities_count_future.result()

    serialize_start = time.perf_counter()
    response = TalentDashboardQuickResponse(
        profile_completion=profile_data.get("profile_completion", 0),
        main_specialty=profile_data.get("main_specialty", ""),
        location=profile_data.get("location", ""),
        applications_count=applications_count,
        opportunities_count=opportunities_count,
    )
    print(f"[PERF] {perf_label} serialize: {_perf_ms(serialize_start):.2f} ms")
    return response


def get_talent_dashboard_quick(current_user: CurrentUser) -> TalentDashboardQuickResponse:
    start = time.perf_counter()
    response = _get_talent_dashboard_quick_data(current_user, "talent dashboard quick")
    print(f"[PERF] talent dashboard quick total: {_perf_ms(start):.2f} ms")
    return response


def get_talent_dashboard_details(current_user: CurrentUser) -> TalentDashboardDetailsResponse:
    start = time.perf_counter()
    applications_query, opportunities_query = _build_talent_queries(current_user)
    available_opportunities = _list_opportunities(opportunities_query, "talent dashboard details")
    applications = _list_applications(applications_query, "talent dashboard details")

    serialize_start = time.perf_counter()
    response = TalentDashboardDetailsResponse(
        available_opportunities=available_opportunities,
        applications=applications,
    )
    print(f"[PERF] talent dashboard details serialize: {_perf_ms(serialize_start):.2f} ms")
    print(f"[PERF] talent dashboard details total: {_perf_ms(start):.2f} ms")
    return response


def get_talent_dashboard(current_user: CurrentUser) -> TalentDashboardResponse:
    start = time.perf_counter()
    quick = _get_talent_dashboard_quick_data(current_user, "talent dashboard full")
    details = get_talent_dashboard_details(current_user)

    serialize_start = time.perf_counter()
    response = TalentDashboardResponse(
        profile_completion=quick.profile_completion,
        main_specialty=quick.main_specialty,
        location=quick.location,
        applications_count=quick.applications_count,
        opportunities_count=quick.opportunities_count,
        available_opportunities=details.available_opportunities,
        applications=details.applications,
    )
    print(f"[PERF] talent dashboard full serialize: {_perf_ms(serialize_start):.2f} ms")
    print(f"[PERF] talent dashboard full total: {_perf_ms(start):.2f} ms")
    return response
