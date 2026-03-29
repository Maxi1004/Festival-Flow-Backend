from fastapi import APIRouter, HTTPException, Depends
from firebase_admin import auth

from app.core.security import verify_firebase_token
from app.schemas.auth_schema import RegisterRequest, RegisterResponse
from app.services.auth_service import register_user

router = APIRouter(tags=["Auth"])


@router.post("/register", response_model=RegisterResponse)
async def register(data: RegisterRequest):
    try:
        return register_user(data)
    except auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=400, detail="El correo ya está registrado")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/me")
async def get_me(decoded_token: dict = Depends(verify_firebase_token)):
    return {
        "message": "Token válido",
        "user": {
            "uid": decoded_token.get("uid"),
            "email": decoded_token.get("email"),
            "name": decoded_token.get("name"),
            "picture": decoded_token.get("picture"),
        },
    }