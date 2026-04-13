from enum import Enum

from pydantic import BaseModel, EmailStr


class UserRole(str, Enum):
    PRODUCER = "PRODUCER"
    TALENT = "TALENT"


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: UserRole


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


class CurrentUser(BaseModel):
    uid: str
    email: str
    name: str
    role: UserRole
    provider: str | None = None
    picture: str | None = None
    created_at: str | None = None
