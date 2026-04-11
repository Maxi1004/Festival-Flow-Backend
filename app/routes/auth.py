from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import auth

from app.core.firebase import db
from app.core.security import verify_firebase_token
from app.schemas.auth_schema import UserRole
from app.schemas.auth_schema import (
    GoogleUserRequest,
    GoogleUserResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.services.auth_service import register_user, sync_google_user

router = APIRouter(tags=["Auth"])


@router.post("/register", response_model=RegisterResponse)
async def register(data: RegisterRequest):
    try:
        return register_user(data)
    except auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=400, detail="El correo ya esta registrado")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/google", response_model=GoogleUserResponse)
async def google_auth(data: GoogleUserRequest):
    try:
        return sync_google_user(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/me")
async def get_me(decoded_token: dict = Depends(verify_firebase_token)):
    uid = decoded_token.get("uid")

    if not uid:
        raise HTTPException(status_code=401, detail="Token invalido")

    user_doc = db.collection("users").document(uid).get()
    user_data = user_doc.to_dict() if user_doc.exists else {}
    role = user_data.get("role") or UserRole.TALENT.value

    return {
        "message": "Token valido",
        "user": {
            "uid": uid,
            "email": user_data.get("email") or decoded_token.get("email"),
            "name": user_data.get("name") or decoded_token.get("name"),
            "picture": user_data.get("picture") or decoded_token.get("picture"),
            "role": role,
            "provider": user_data.get("provider"),
            "created_at": user_data.get("created_at"),
        },
    }
