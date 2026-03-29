from datetime import datetime, timezone

from firebase_admin import auth

from app.core.firebase import db
from app.schemas.auth_schema import RegisterRequest


def register_user(data: RegisterRequest) -> dict:
    user_record = auth.create_user(
        email=data.email,
        password=data.password,
        display_name=data.name,
    )

    user_data = {
        "uid": user_record.uid,
        "name": data.name,
        "email": data.email,
        "provider": "password",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    db.collection("users").document(user_record.uid).set(user_data)

    return {
        "uid": user_record.uid,
        "name": data.name,
        "email": data.email,
        "message": "Usuario registrado correctamente",
    }