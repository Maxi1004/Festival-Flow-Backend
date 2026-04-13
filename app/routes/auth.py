from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import auth

from app.core.security import get_current_user
from app.schemas.auth_schema import (
    CurrentUser,
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
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    return {
        "message": "Token valido",
        "user": {
            "uid": current_user.uid,
            "email": current_user.email,
            "name": current_user.name,
            "picture": current_user.picture,
            "role": current_user.role.value,
            "provider": current_user.provider,
            "created_at": current_user.created_at,
        },
    }
