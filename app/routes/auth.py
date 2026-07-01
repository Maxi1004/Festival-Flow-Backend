import os
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


def _is_quota_exceeded(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return (
        "resourceexhausted" in text
        or "resource exhausted" in text
        or "quota exceeded" in text
        or "429" in text
    )


@router.get("/me", response_model=AuthMeResponse)
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    start = time.perf_counter()

    # get_current_user already resolved this user from Firestore (or cache / DEV_AUTH_FALLBACK).
    # Re-reading the users collection here would waste a Firestore read and fail under quota.
    role = current_user.role
    print("[AUTH_ME]", current_user.uid, current_user.email, role)

    if os.getenv("DEV_AUTH_FALLBACK", "").strip().lower() == "true":
        print("[Auth Me] Using current_user fallback")

    # photo_url starts from whatever get_current_user already resolved.
    photo_url = current_user.photo_url

    if role == UserRole.TALENT:
        profile_get_start = time.perf_counter()
        try:
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
        except Exception as exc:
            if _is_quota_exceeded(exc):
                print("[Auth Me] Firestore quota exceeded, returning current_user")
            else:
                raise

    elif role == UserRole.PRODUCER:
        profile_get_start = time.perf_counter()
        try:
            profile_doc = db.collection("producer_profiles").document(current_user.uid).get()
            print(
                "[PERF] GET /auth/me Firestore producer_profiles/{uid}.get "
                f"(reads=1): {(time.perf_counter() - profile_get_start) * 1000:.2f} ms"
            )
            if profile_doc.exists:
                profile_data = profile_doc.to_dict() or {}
                photo_url = (
                    profile_data.get("photo_url")
                    or current_user.picture
                    or current_user.photo_url
                )
        except Exception as exc:
            if _is_quota_exceeded(exc):
                print("[Auth Me] Firestore quota exceeded, returning current_user")
            else:
                raise

    response = {
        "message": "Token valido",
        "user": {
            "uid": current_user.uid,
            "email": current_user.email,
            "name": current_user.name,
            "picture": current_user.picture,
            "photo_url": photo_url,
            "role": role.value if role else None,
            "provider": current_user.provider,
            "created_at": current_user.created_at,
        },
    }
    print(f"[PERF] GET /auth/me build response: {(time.perf_counter() - start) * 1000:.2f} ms")
    return response
