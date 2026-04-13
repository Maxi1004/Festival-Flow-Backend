from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import utc_now_iso
from app.schemas.application_schema import ApplicationCreateRequest, ApplicationResponse
from app.schemas.auth_schema import CurrentUser


def _build_application_id(opportunity_id: str, talent_uid: str) -> str:
    return f"{opportunity_id}_{talent_uid}"


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
        "producer_uid": opportunity_data.get("owner_uid", ""),
        "talent_uid": current_user.uid,
        "talent_name": current_user.name,
        "talent_email": current_user.email,
        "message": payload.message,
        "status": "SUBMITTED",
        "applied_at": timestamp,
        "updated_at": timestamp,
    }

    application_ref.set(application_data)
    return ApplicationResponse(**application_data)


def list_my_applications(current_user: CurrentUser) -> list[ApplicationResponse]:
    query = db.collection("applications").where("talent_uid", "==", current_user.uid)
    items = [ApplicationResponse(**(doc.to_dict() or {})) for doc in query.stream()]
    return sorted(items, key=lambda item: item.applied_at, reverse=True)
