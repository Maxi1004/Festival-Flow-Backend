from datetime import datetime, timezone

from fastapi import HTTPException
from firebase_admin import auth

from app.core.firebase import db
from app.schemas.auth_schema import GoogleUserRequest, RegisterRequest, UserRole


def register_user(data: RegisterRequest) -> dict:
    user_record = auth.create_user(
        email=data.email,
        password=data.password,
        display_name=data.name,
    )

    user_data = {
        "uid": user_record.uid,
        "name": data.name,
        "email": str(data.email),
        "provider": "password",
        "role": data.role.value,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    db.collection("users").document(user_record.uid).set(user_data)

    return {
        "uid": user_record.uid,
        "name": data.name,
        "email": str(data.email),
        "role": data.role,
        "message": "Usuario registrado correctamente",
    }


def sync_google_user(data: GoogleUserRequest) -> dict:
    users_collection = db.collection("users")
    incoming_email = str(data.email)
    user_doc_ref = users_collection.document(data.uid)
    user_doc = user_doc_ref.get()

    existing_user = user_doc.to_dict() if user_doc.exists else None

    if existing_user is None:
        email_query = users_collection.where("email", "==", incoming_email).limit(1).stream()
        existing_email_doc = next(email_query, None)

        if existing_email_doc is not None:
            existing_user = existing_email_doc.to_dict()
            user_doc_ref = existing_email_doc.reference

    if existing_user is None and data.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="El rol ADMIN no esta disponible para registro publico",
        )

    resolved_role = existing_user.get("role") if existing_user and existing_user.get("role") else data.role.value

    user_data = {
        "uid": data.uid,
        "name": data.name,
        "email": incoming_email,
        "provider": data.provider,
        "picture": data.picture,
        "role": resolved_role,
    }

    if existing_user is None:
        user_data["created_at"] = datetime.now(timezone.utc).isoformat()
        user_doc_ref.set(user_data)
    else:
        if existing_user.get("created_at"):
            user_data["created_at"] = existing_user["created_at"]
        user_doc_ref.set(user_data, merge=True)

    return {
        "message": "Usuario Google sincronizado correctamente",
        "user": {
            "uid": data.uid,
            "name": data.name,
            "email": incoming_email,
            "picture": data.picture,
            "provider": data.provider,
            "role": resolved_role,
        },
    }
