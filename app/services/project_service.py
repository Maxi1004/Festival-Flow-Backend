from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import serialize_date, utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.project_schema import ProjectCreateRequest, ProjectResponse, ProjectStatusUpdateRequest, ProjectUpdateRequest


def _serialize_project(project_id: str, data: dict) -> ProjectResponse:
    return ProjectResponse(
        id=data.get("id") or project_id,
        owner_uid=data.get("owner_uid", ""),
        title=data.get("title", ""),
        description=data.get("description", ""),
        production_type=data.get("production_type", ""),
        location=data.get("location", ""),
        start_date=serialize_date(data.get("start_date")),
        end_date=serialize_date(data.get("end_date")),
        status=data.get("status", ""),
        created_at=serialize_date(data.get("created_at")) or "",
        updated_at=serialize_date(data.get("updated_at")) or "",
    )


def _get_project_owned_by_user(project_id: str, current_user: CurrentUser):
    project_doc = db.collection("projects").document(project_id).get()

    if not project_doc.exists:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    project_data = project_doc.to_dict() or {}

    if project_data.get("owner_uid") != current_user.uid:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre este proyecto")

    return project_doc


def create_project(payload: ProjectCreateRequest, current_user: CurrentUser) -> ProjectResponse:
    project_ref = db.collection("projects").document()
    timestamp = utc_now_iso()
    project_data = {
        "id": project_ref.id,
        "owner_uid": current_user.uid,
        "title": payload.title,
        "description": payload.description,
        "production_type": payload.production_type,
        "location": payload.location,
        "start_date": serialize_date(payload.start_date),
        "end_date": serialize_date(payload.end_date),
        "status": payload.status,
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    project_ref.set(project_data)
    return ProjectResponse(**project_data)


def list_my_projects(current_user: CurrentUser) -> list[ProjectResponse]:
    query = db.collection("projects").where("owner_uid", "==", current_user.uid)
    items = [_serialize_project(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at, reverse=True)


def get_my_project_by_id(project_id: str, current_user: CurrentUser) -> ProjectResponse:
    project_doc = _get_project_owned_by_user(project_id, current_user)
    return _serialize_project(project_doc.id, project_doc.to_dict() or {})


def update_project_status(
    project_id: str,
    payload: ProjectStatusUpdateRequest,
    current_user: CurrentUser,
) -> ProjectResponse:
    project_doc = _get_project_owned_by_user(project_id, current_user)
    existing_data = project_doc.to_dict() or {}
    old_status = existing_data.get("status", "")
    new_status = payload.status

    project_doc.reference.update({
        "status": new_status,
        "updated_at": utc_now_iso(),
    })

    print(f"[Projects] Estado actualizado", flush=True)
    print(f"[Projects] Proyecto: {project_id}", flush=True)
    print(f"[Projects] Anterior: {old_status}", flush=True)
    print(f"[Projects] Nuevo: {new_status}", flush=True)

    updated = project_doc.reference.get().to_dict() or {}
    return _serialize_project(project_id, updated)


def update_my_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    current_user: CurrentUser,
) -> ProjectResponse:
    project_doc = _get_project_owned_by_user(project_id, current_user)
    existing_data = project_doc.to_dict() or {}
    updated_data = {
        "id": existing_data.get("id") or project_doc.id,
        "owner_uid": current_user.uid,
        "title": payload.title,
        "description": payload.description,
        "production_type": payload.production_type,
        "location": payload.location,
        "start_date": serialize_date(payload.start_date),
        "end_date": serialize_date(payload.end_date),
        "status": payload.status,
        "created_at": existing_data.get("created_at") or utc_now_iso(),
        "updated_at": utc_now_iso(),
    }

    project_doc.reference.set(updated_data)
    return ProjectResponse(**updated_data)
