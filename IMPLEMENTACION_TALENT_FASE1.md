# Implementacion Talent Fase 1

## Archivos tocados
- app/core/main.py
- app/core/security.py
- app/core/utils.py
- app/schemas/auth_schema.py
- app/schemas/talent_schema.py
- app/schemas/opportunity_schema.py
- app/schemas/application_schema.py
- app/routes/talent.py
- app/routes/opportunities.py
- app/routes/applications.py
- app/services/talent_service.py
- app/services/opportunity_service.py
- app/services/application_service.py

## Codigo completo

### app/core/main.py
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.firebase import db
from app.routes.applications import router as applications_router
from app.routes.auth import router as auth_router
from app.routes.opportunities import router as opportunities_router
from app.routes.talent import router as talent_router

app = FastAPI(title="Festival Flow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Festival Flow API is running"}


@app.get("/test-db")
async def test_db():
    doc_ref = db.collection("test").document("conexion")
    doc_ref.set({"mensaje": "Firebase conectado correctamente"})
    return {"message": "ok"}


app.include_router(auth_router, prefix="/auth")
app.include_router(talent_router, prefix="/talent")
app.include_router(opportunities_router)
app.include_router(applications_router)

```

### app/core/security.py
```python
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException
from firebase_admin import auth

from app.core.firebase import db
from app.schemas.auth_schema import CurrentUser, UserRole


def verify_firebase_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header faltante")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token mal formado")

    token = authorization.replace("Bearer ", "").strip()

    try:
        decoded_token = auth.verify_id_token(token, clock_skew_seconds=30)
        return decoded_token
    except Exception as e:
        print("ERROR VERIFY TOKEN:", e)
        raise HTTPException(status_code=401, detail=f"Token invalido o expirado: {str(e)}")


def get_current_user(decoded_token: dict = Depends(verify_firebase_token)) -> CurrentUser:
    uid = decoded_token.get("uid")

    if not uid:
        raise HTTPException(status_code=401, detail="Token invalido")

    user_doc = db.collection("users").document(uid).get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="Usuario autenticado no encontrado")

    user_data = user_doc.to_dict() or {}
    return CurrentUser(
        uid=uid,
        email=user_data.get("email") or decoded_token.get("email") or "",
        name=user_data.get("name") or decoded_token.get("name") or "",
        role=user_data.get("role") or UserRole.TALENT.value,
        provider=user_data.get("provider"),
        picture=user_data.get("picture") or decoded_token.get("picture"),
        created_at=user_data.get("created_at"),
    )


def require_role(role: UserRole | str) -> Callable:
    required_role = role.value if isinstance(role, UserRole) else role

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role != required_role:
            raise HTTPException(status_code=403, detail="Rol no autorizado para este recurso")

        return current_user

    return dependency

```

### app/core/utils.py
```python
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

```

### app/schemas/auth_schema.py
```python
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
    role: str
    provider: str | None = None
    picture: str | None = None
    created_at: str | None = None

```

### app/schemas/talent_schema.py
```python
from datetime import date

from pydantic import BaseModel, Field


class PortfolioLink(BaseModel):
    label: str
    url: str


class TalentProfileUpsertRequest(BaseModel):
    display_name: str | None = None
    bio: str = ""
    main_specialty: str = ""
    specialties: list[str] = Field(default_factory=list)
    location: str = ""
    experience_years: int = Field(default=0, ge=0)
    languages: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    portfolio_links: list[PortfolioLink] = Field(default_factory=list)
    profile_completion: int = Field(default=0, ge=0, le=100)
    is_public: bool = False


class TalentProfileResponse(BaseModel):
    user_uid: str
    display_name: str
    bio: str
    main_specialty: str
    specialties: list[str]
    location: str
    experience_years: int
    languages: list[str]
    skills: list[str]
    portfolio_links: list[PortfolioLink]
    profile_completion: int
    is_public: bool
    updated_at: str | None = None


class TalentAvailabilityUpsertRequest(BaseModel):
    status: str = ""
    travel_availability: bool = False
    work_modality: str = ""
    work_location: str = ""
    available_from: date | None = None
    notes: str = ""


class TalentAvailabilityResponse(BaseModel):
    user_uid: str
    status: str
    travel_availability: bool
    work_modality: str
    work_location: str
    available_from: str | None = None
    notes: str
    updated_at: str | None = None

```

### app/schemas/opportunity_schema.py
```python
from pydantic import BaseModel, Field


class OpportunityResponse(BaseModel):
    id: str
    project_id: str | None = None
    owner_uid: str
    title: str
    role_needed: str
    specialty: str
    description: str
    location: str
    modality: str
    requirements: list[str] = Field(default_factory=list)
    status: str
    deadline: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

```

### app/schemas/application_schema.py
```python
from pydantic import BaseModel


class ApplicationCreateRequest(BaseModel):
    opportunity_id: str
    message: str = ""


class ApplicationResponse(BaseModel):
    id: str
    opportunity_id: str
    project_id: str | None = None
    producer_uid: str
    talent_uid: str
    talent_name: str
    talent_email: str
    message: str
    status: str
    applied_at: str
    updated_at: str

```

### app/routes/talent.py
```python
from fastapi import APIRouter, Depends

from app.core.security import require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.talent_schema import (
    TalentAvailabilityResponse,
    TalentAvailabilityUpsertRequest,
    TalentProfileResponse,
    TalentProfileUpsertRequest,
)
from app.services.talent_service import (
    get_talent_availability,
    get_talent_profile,
    upsert_talent_availability,
    upsert_talent_profile,
)

router = APIRouter(tags=["Talent"])


@router.get("/profile/me", response_model=TalentProfileResponse)
async def get_my_profile(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_profile(current_user)


@router.put("/profile/me", response_model=TalentProfileResponse)
async def put_my_profile(
    payload: TalentProfileUpsertRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return upsert_talent_profile(current_user, payload)


@router.get("/availability/me", response_model=TalentAvailabilityResponse)
async def get_my_availability(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_availability(current_user)


@router.put("/availability/me", response_model=TalentAvailabilityResponse)
async def put_my_availability(
    payload: TalentAvailabilityUpsertRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return upsert_talent_availability(current_user, payload)

```

### app/routes/opportunities.py
```python
from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.schemas.auth_schema import CurrentUser
from app.schemas.opportunity_schema import OpportunityResponse
from app.services.opportunity_service import get_opportunity_by_id, list_opportunities

router = APIRouter(tags=["Opportunities"])


@router.get("/opportunities", response_model=list[OpportunityResponse])
async def get_opportunities(
    specialty: str | None = Query(default=None),
    location: str | None = Query(default=None),
    modality: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_opportunities(
        specialty=specialty,
        location=location,
        modality=modality,
        status=status,
    )


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def get_opportunity_detail(
    opportunity_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return get_opportunity_by_id(opportunity_id)

```

### app/routes/applications.py
```python
from fastapi import APIRouter, Depends

from app.core.security import require_role
from app.schemas.application_schema import ApplicationCreateRequest, ApplicationResponse
from app.schemas.auth_schema import CurrentUser, UserRole
from app.services.application_service import create_application, list_my_applications

router = APIRouter(tags=["Applications"])


@router.post("/applications", response_model=ApplicationResponse)
async def post_application(
    payload: ApplicationCreateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return create_application(payload, current_user)


@router.get("/applications/me", response_model=list[ApplicationResponse])
async def get_my_applications(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return list_my_applications(current_user)

```

### app/services/talent_service.py
```python
from app.core.firebase import db
from app.core.utils import utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.talent_schema import (
    TalentAvailabilityResponse,
    TalentAvailabilityUpsertRequest,
    TalentProfileResponse,
    TalentProfileUpsertRequest,
)


def get_talent_profile(current_user: CurrentUser) -> TalentProfileResponse:
    profile_doc = db.collection("talent_profiles").document(current_user.uid).get()

    if not profile_doc.exists:
        return TalentProfileResponse(
            user_uid=current_user.uid,
            display_name=current_user.name or "",
            bio="",
            main_specialty="",
            specialties=[],
            location="",
            experience_years=0,
            languages=[],
            skills=[],
            portfolio_links=[],
            profile_completion=0,
            is_public=False,
            updated_at=None,
        )

    profile_data = profile_doc.to_dict() or {}
    return TalentProfileResponse(
        user_uid=profile_data.get("user_uid", current_user.uid),
        display_name=profile_data.get("display_name", current_user.name or ""),
        bio=profile_data.get("bio", ""),
        main_specialty=profile_data.get("main_specialty", ""),
        specialties=profile_data.get("specialties", []),
        location=profile_data.get("location", ""),
        experience_years=profile_data.get("experience_years", 0),
        languages=profile_data.get("languages", []),
        skills=profile_data.get("skills", []),
        portfolio_links=profile_data.get("portfolio_links", []),
        profile_completion=profile_data.get("profile_completion", 0),
        is_public=profile_data.get("is_public", False),
        updated_at=profile_data.get("updated_at"),
    )


def upsert_talent_profile(
    current_user: CurrentUser,
    payload: TalentProfileUpsertRequest,
) -> TalentProfileResponse:
    profile_data = {
        "user_uid": current_user.uid,
        "display_name": payload.display_name or current_user.name or "",
        "bio": payload.bio,
        "main_specialty": payload.main_specialty,
        "specialties": payload.specialties,
        "location": payload.location,
        "experience_years": payload.experience_years,
        "languages": payload.languages,
        "skills": payload.skills,
        "portfolio_links": [item.model_dump() for item in payload.portfolio_links],
        "profile_completion": payload.profile_completion,
        "is_public": payload.is_public,
        "updated_at": utc_now_iso(),
    }

    db.collection("talent_profiles").document(current_user.uid).set(profile_data)
    return TalentProfileResponse(**profile_data)


def get_talent_availability(current_user: CurrentUser) -> TalentAvailabilityResponse:
    availability_doc = db.collection("talent_availability").document(current_user.uid).get()

    if not availability_doc.exists:
        return TalentAvailabilityResponse(
            user_uid=current_user.uid,
            status="",
            travel_availability=False,
            work_modality="",
            work_location="",
            available_from=None,
            notes="",
            updated_at=None,
        )

    availability_data = availability_doc.to_dict() or {}
    return TalentAvailabilityResponse(
        user_uid=availability_data.get("user_uid", current_user.uid),
        status=availability_data.get("status", ""),
        travel_availability=availability_data.get("travel_availability", False),
        work_modality=availability_data.get("work_modality", ""),
        work_location=availability_data.get("work_location", ""),
        available_from=availability_data.get("available_from"),
        notes=availability_data.get("notes", ""),
        updated_at=availability_data.get("updated_at"),
    )


def upsert_talent_availability(
    current_user: CurrentUser,
    payload: TalentAvailabilityUpsertRequest,
) -> TalentAvailabilityResponse:
    availability_data = {
        "user_uid": current_user.uid,
        "status": payload.status,
        "travel_availability": payload.travel_availability,
        "work_modality": payload.work_modality,
        "work_location": payload.work_location,
        "available_from": payload.available_from.isoformat() if payload.available_from else None,
        "notes": payload.notes,
        "updated_at": utc_now_iso(),
    }

    db.collection("talent_availability").document(current_user.uid).set(availability_data)
    return TalentAvailabilityResponse(**availability_data)

```

### app/services/opportunity_service.py
```python
from fastapi import HTTPException

from app.core.firebase import db
from app.schemas.opportunity_schema import OpportunityResponse


def _to_iso(value):
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return value


def _serialize_opportunity(opportunity_id: str, data: dict) -> OpportunityResponse:
    return OpportunityResponse(
        id=data.get("id") or opportunity_id,
        project_id=data.get("project_id"),
        owner_uid=data.get("owner_uid", ""),
        title=data.get("title", ""),
        role_needed=data.get("role_needed", ""),
        specialty=data.get("specialty", ""),
        description=data.get("description", ""),
        location=data.get("location", ""),
        modality=data.get("modality", ""),
        requirements=data.get("requirements", []),
        status=data.get("status", ""),
        deadline=_to_iso(data.get("deadline")),
        created_at=_to_iso(data.get("created_at")),
        updated_at=_to_iso(data.get("updated_at")),
    )


def list_opportunities(
    specialty: str | None = None,
    location: str | None = None,
    modality: str | None = None,
    status: str | None = None,
) -> list[OpportunityResponse]:
    query = db.collection("opportunities")

    if specialty:
        query = query.where("specialty", "==", specialty)
    if location:
        query = query.where("location", "==", location)
    if modality:
        query = query.where("modality", "==", modality)
    if status:
        query = query.where("status", "==", status)

    items = [_serialize_opportunity(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at or "", reverse=True)


def get_opportunity_by_id(opportunity_id: str) -> OpportunityResponse:
    opportunity_doc = db.collection("opportunities").document(opportunity_id).get()

    if not opportunity_doc.exists:
        raise HTTPException(status_code=404, detail="Convocatoria no encontrada")

    return _serialize_opportunity(opportunity_doc.id, opportunity_doc.to_dict() or {})

```

### app/services/application_service.py
```python
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

```

## Requests Postman

### GET /talent/profile/me
```http
GET /talent/profile/me
Authorization: Bearer <FIREBASE_ID_TOKEN>
```

### PUT /talent/profile/me
```http
PUT /talent/profile/me
Authorization: Bearer <FIREBASE_ID_TOKEN>
Content-Type: application/json

{
  "display_name": "Camila Rojas",
  "bio": "Actriz y creadora audiovisual",
  "main_specialty": "Actor",
  "specialties": ["Actor", "Camarografa"],
  "location": "Santiago, Chile",
  "experience_years": 8,
  "languages": ["Español", "Inglés"],
  "skills": ["Premiere", "Casting self tape"],
  "portfolio_links": [
    {
      "label": "Reel",
      "url": "https://ejemplo.com/reel"
    }
  ],
  "profile_completion": 85,
  "is_public": true
}
```

### GET /talent/availability/me
```http
GET /talent/availability/me
Authorization: Bearer <FIREBASE_ID_TOKEN>
```

### PUT /talent/availability/me
```http
PUT /talent/availability/me
Authorization: Bearer <FIREBASE_ID_TOKEN>
Content-Type: application/json

{
  "status": "AVAILABLE",
  "travel_availability": true,
  "work_modality": "FREELANCE",
  "work_location": "Santiago / Remoto",
  "available_from": "2026-04-20",
  "notes": "Disponible para casting, rodajes y proyectos de corta o media duración."
}
```

### GET /opportunities
```http
GET /opportunities?specialty=Actor&location=Santiago&modality=REMOTE&status=OPEN
Authorization: Bearer <FIREBASE_ID_TOKEN>
```

### GET /opportunities/{id}
```http
GET /opportunities/op-123
Authorization: Bearer <FIREBASE_ID_TOKEN>
```

### POST /applications
```http
POST /applications
Authorization: Bearer <FIREBASE_ID_TOKEN>
Content-Type: application/json

{
  "opportunity_id": "op-123",
  "message": "Me interesa participar en este proyecto y tengo disponibilidad desde abril."
}
```

### GET /applications/me
```http
GET /applications/me
Authorization: Bearer <FIREBASE_ID_TOKEN>
```
