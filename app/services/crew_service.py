from typing import Any

from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import serialize_date, utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.crew_schema import (
    CrewConversationResponse,
    CrewMemberUpdateRequest,
    CrewMemberResponse,
    CrewMessageCreateRequest,
    CrewMessageResponse,
    CrewOpportunitySummary,
    CrewProducerSummary,
    CrewProjectSummary,
    CrewTalentSummary,
)


def _first_present(data: dict, keys: tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return default


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
    task_description: str | None = None,
    producer_note: str | None = None,
) -> dict:
    crew_member_id = _crew_member_id(producer_id, talent_user_id, project_id, opportunity_id)
    crew_member_ref = db.collection("crew_members").document(crew_member_id)
    existing_doc = crew_member_ref.get()
    existing_data = {}
    if existing_doc.exists:
        existing_data = existing_doc.to_dict() or {}
    timestamp = utc_now_iso()
    joined_at = existing_data.get("joined_at") or timestamp

    crew_member_data = {
        **existing_data,
        "id": crew_member_id,
        "producer_id": producer_id,
        "talent_user_id": talent_user_id,
        "project_id": project_id,
        "opportunity_id": opportunity_id,
        "application_id": application_id,
        "recruitment_id": recruitment_id,
        "source": source,
        "role": existing_data.get("role") or role,
        "task_description": existing_data.get("task_description") or task_description,
        "producer_note": existing_data.get("producer_note") or producer_note,
        "status": "ACTIVE",
        "joined_at": joined_at,
        "created_at": existing_data.get("created_at") or timestamp,
        "updated_at": timestamp,
    }

    crew_member_ref.set(crew_member_data)
    return crew_member_data


def _serialize_crew_member(crew_member_id: str, data: dict) -> CrewMemberResponse:
    project_id = data.get("project_id")
    opportunity_id = data.get("opportunity_id")
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


def list_talent_crew(current_user: CurrentUser) -> list[CrewMemberResponse]:
    query = db.collection("crew_members").where("talent_user_id", "==", current_user.uid).where("status", "==", "ACTIVE")
    items = [_serialize_crew_member(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.joined_at or "", reverse=True)


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
        if key in {"role", "task_description", "producer_note"}
    }
    allowed_updates["updated_at"] = utc_now_iso()

    updated_data = {
        **crew_member_data,
        **allowed_updates,
        "id": crew_member_data.get("id") or crew_member_doc.id,
    }
    crew_member_doc.reference.set(updated_data)
    return _serialize_crew_member(crew_member_doc.id, updated_data)


def create_crew_message(
    crew_member_id: str,
    payload: CrewMessageCreateRequest,
    current_user: CurrentUser,
) -> CrewMessageResponse:
    _validate_crew_access(crew_member_id, current_user)

    message_ref = db.collection("crew_messages").document()
    message_data = {
        "id": message_ref.id,
        "crew_member_id": crew_member_id,
        "sender_id": current_user.uid,
        "sender_role": current_user.role.value,
        "message": payload.message,
        "created_at": utc_now_iso(),
    }

    message_ref.set(message_data)
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
