from enum import Enum

from pydantic import BaseModel, EmailStr, field_validator


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    PRODUCER = "PRODUCER"
    TALENT = "TALENT"


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: UserRole

    @field_validator("role")
    @classmethod
    def admin_cannot_register_publicly(cls, role: UserRole) -> UserRole:
        if role == UserRole.ADMIN:
            raise ValueError("El rol ADMIN no esta disponible para registro publico")
        return role


class RegisterResponse(BaseModel):
    uid: str
    name: str
    email: str
    role: UserRole
    message: str


class GoogleUserRequest(BaseModel):
    uid: str
    name: str
    email: EmailStr
    picture: str | None = None
    provider: str = "google"
    role: UserRole


class GoogleUserData(BaseModel):
    uid: str
    name: str
    email: str
    picture: str | None = None
    provider: str
    role: UserRole


class GoogleUserResponse(BaseModel):
    message: str
    user: GoogleUserData


class AuthMeUserData(BaseModel):
    uid: str
    email: str
    name: str
    picture: str | None = None
    photo_url: str | None = None
    role: UserRole | None = None
    provider: str | None = None
    created_at: str | None = None


class AuthMeResponse(BaseModel):
    message: str
    user: AuthMeUserData


class CurrentUser(BaseModel):
    uid: str
    email: str
    name: str
    role: UserRole | None = None
    provider: str | None = None
    picture: str | None = None
    photo_url: str | None = None
    created_at: str | None = None
