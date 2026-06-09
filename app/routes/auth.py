import time

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import auth

from app.core.firebase import db
from app.core.security import get_current_user
from app.schemas.auth_schema import (
    AuthMeResponse,
    CurrentUser,
    GoogleUserRequest,
    GoogleUserResponse,
    RegisterRequest,
    RegisterResponse,
    UserRole,
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/me", response_model=AuthMeResponse)
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    start = time.perf_counter()
    user_doc = db.collection("users").document(current_user.uid).get()
    user_data = user_doc.to_dict() or {} if user_doc.exists else {}
    raw_role = user_data.get("role")
    role = UserRole(str(raw_role).strip().upper()) if raw_role else None
    print("[AUTH_ME]", current_user.uid, user_data.get("email"), user_data.get("role"))

    photo_url = None
    if role == UserRole.TALENT:
        profile_get_start = time.perf_counter()
        profile_doc = db.collection("talent_profiles").document(current_user.uid).get()
        print(
            "[PERF] GET /auth/me Firestore talent_profiles/{uid}.get "
            f"(reads=1): {(time.perf_counter() - profile_get_start) * 1000:.2f} ms"
        )
        if profile_doc.exists:
            profile_data = profile_doc.to_dict() or {}
            photo_url = (
                profile_data.get("photo_url")
                or profile_data.get("picture")
                or profile_data.get("avatar_url")
            )
    elif role == UserRole.PRODUCER:
        profile_get_start = time.perf_counter()
        profile_doc = db.collection("producer_profiles").document(current_user.uid).get()
        print(
            "[PERF] GET /auth/me Firestore producer_profiles/{uid}.get "
            f"(reads=1): {(time.perf_counter() - profile_get_start) * 1000:.2f} ms"
        )
        profile_data = profile_doc.to_dict() or {} if profile_doc.exists else {}
        photo_url = (
            profile_data.get("photo_url")
            or current_user.picture
            or current_user.photo_url
        )

    response = {
        "message": "Token valido",
        "user": {
            "uid": current_user.uid,
            "email": user_data.get("email") or current_user.email,
            "name": user_data.get("name") or current_user.name,
            "picture": user_data.get("picture") or current_user.picture,
            "photo_url": photo_url,
            "role": role.value if role else None,
            "provider": user_data.get("provider") or current_user.provider,
            "created_at": user_data.get("created_at") or current_user.created_at,
        },
    }
    print(f"[PERF] GET /auth/me build response: {(time.perf_counter() - start) * 1000:.2f} ms")
    return response
