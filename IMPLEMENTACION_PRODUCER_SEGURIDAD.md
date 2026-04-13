# Implementacion Producer y Seguridad

## Resumen
- Se endurecio la resolucion del usuario autenticado: sin rol en Firestore ahora falla con 403 y `CurrentUser.role` queda tipado como `UserRole`.
- Se agrego el modulo `PRODUCER` para crear, listar, ver y editar proyectos propios.
- Se extendio `opportunities` para que `PRODUCER` pueda crear, listar, editar y cerrar convocatorias reales visibles para TALENT.

## Archivos creados y modificados
- app/core/main.py
- app/core/security.py
- app/core/utils.py
- app/routes/auth.py
- app/routes/opportunities.py
- app/routes/projects.py
- app/schemas/auth_schema.py
- app/schemas/opportunity_schema.py
- app/schemas/project_schema.py
- app/services/opportunity_service.py
- app/services/project_service.py

## Codigo completo

### app/core/main.py
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.firebase import db
from app.routes.applications import router as applications_router
from app.routes.auth import router as auth_router
from app.routes.opportunities import router as opportunities_router
from app.routes.projects import router as projects_router
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
app.include_router(projects_router)
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
    raw_role = user_data.get("role")

    if not raw_role:
        raise HTTPException(status_code=403, detail="El usuario autenticado no tiene un rol configurado")

    try:
        parsed_role = UserRole(raw_role)
    except ValueError:
        raise HTTPException(status_code=403, detail="El rol del usuario autenticado no es valido")

    return CurrentUser(
        uid=uid,
        email=user_data.get("email") or decoded_token.get("email") or "",
        name=user_data.get("name") or decoded_token.get("name") or "",
        role=parsed_role,
        provider=user_data.get("provider"),
        picture=user_data.get("picture") or decoded_token.get("picture"),
        created_at=user_data.get("created_at"),
    )


def require_role(role: UserRole | str) -> Callable:
    required_role = role if isinstance(role, UserRole) else UserRole(role)

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


def serialize_date(value) -> str | None:
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)

```

### app/routes/auth.py
```python
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

```

### app/routes/opportunities.py
```python
from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user, require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.opportunity_schema import (
    OpportunityCreateRequest,
    OpportunityResponse,
    OpportunityStatusUpdateRequest,
    OpportunityUpdateRequest,
)
from app.services.opportunity_service import (
    create_opportunity,
    get_opportunity_by_id,
    list_my_opportunities,
    list_opportunities,
    update_my_opportunity,
    update_my_opportunity_status,
)

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


@router.post("/opportunities", response_model=OpportunityResponse)
async def post_opportunity(
    payload: OpportunityCreateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return create_opportunity(payload, current_user)


@router.get("/opportunities/me", response_model=list[OpportunityResponse])
async def get_my_opportunities(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_my_opportunities(current_user)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def get_opportunity_detail(
    opportunity_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return get_opportunity_by_id(opportunity_id)


@router.put("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def put_opportunity(
    opportunity_id: str,
    payload: OpportunityUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_my_opportunity(opportunity_id, payload, current_user)


@router.patch("/opportunities/{opportunity_id}/status", response_model=OpportunityResponse)
async def patch_opportunity_status(
    opportunity_id: str,
    payload: OpportunityStatusUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_my_opportunity_status(opportunity_id, payload, current_user)

```

### app/routes/projects.py
```python
from fastapi import APIRouter, Depends

from app.core.security import require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.project_schema import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest
from app.services.project_service import (
    create_project,
    get_my_project_by_id,
    list_my_projects,
    update_my_project,
)

router = APIRouter(tags=["Projects"])


@router.post("/projects", response_model=ProjectResponse)
async def post_project(
    payload: ProjectCreateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return create_project(payload, current_user)


@router.get("/projects/me", response_model=list[ProjectResponse])
async def get_projects_me(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_my_projects(current_user)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project_detail(
    project_id: str,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return get_my_project_by_id(project_id, current_user)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def put_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_my_project(project_id, payload, current_user)

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
    role: UserRole
    provider: str | None = None
    picture: str | None = None
    created_at: str | None = None

```

### app/schemas/opportunity_schema.py
```python
from datetime import date

from pydantic import BaseModel, Field


class OpportunityCreateRequest(BaseModel):
    project_id: str
    title: str
    role_needed: str
    specialty: str
    description: str
    location: str
    modality: str
    requirements: list[str] = Field(default_factory=list)
    status: str
    deadline: date | None = None


class OpportunityUpdateRequest(BaseModel):
    title: str
    role_needed: str
    specialty: str
    description: str
    location: str
    modality: str
    requirements: list[str] = Field(default_factory=list)
    status: str
    deadline: date | None = None


class OpportunityStatusUpdateRequest(BaseModel):
    status: str


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

### app/schemas/project_schema.py
```python
from datetime import date

from pydantic import BaseModel


class ProjectCreateRequest(BaseModel):
    title: str
    description: str
    production_type: str
    location: str
    start_date: date | None = None
    end_date: date | None = None
    status: str


class ProjectUpdateRequest(BaseModel):
    title: str
    description: str
    production_type: str
    location: str
    start_date: date | None = None
    end_date: date | None = None
    status: str


class ProjectResponse(BaseModel):
    id: str
    owner_uid: str
    title: str
    description: str
    production_type: str
    location: str
    start_date: str | None = None
    end_date: str | None = None
    status: str
    created_at: str
    updated_at: str

```

### app/services/opportunity_service.py
```python
from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import serialize_date, utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.opportunity_schema import (
    OpportunityCreateRequest,
    OpportunityResponse,
    OpportunityStatusUpdateRequest,
    OpportunityUpdateRequest,
)


def _to_iso(value):
    return serialize_date(value)


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


def _get_project_owned_by_user(project_id: str, current_user: CurrentUser) -> dict:
    project_doc = db.collection("projects").document(project_id).get()

    if not project_doc.exists:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    project_data = project_doc.to_dict() or {}

    if project_data.get("owner_uid") != current_user.uid:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre este proyecto")

    return project_data


def _get_opportunity_owned_by_user(opportunity_id: str, current_user: CurrentUser):
    opportunity_doc = db.collection("opportunities").document(opportunity_id).get()

    if not opportunity_doc.exists:
        raise HTTPException(status_code=404, detail="Convocatoria no encontrada")

    opportunity_data = opportunity_doc.to_dict() or {}

    if opportunity_data.get("owner_uid") != current_user.uid:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre esta convocatoria")

    return opportunity_doc


def create_opportunity(
    payload: OpportunityCreateRequest,
    current_user: CurrentUser,
) -> OpportunityResponse:
    _get_project_owned_by_user(payload.project_id, current_user)
    opportunity_ref = db.collection("opportunities").document()
    timestamp = utc_now_iso()
    opportunity_data = {
        "id": opportunity_ref.id,
        "project_id": payload.project_id,
        "owner_uid": current_user.uid,
        "title": payload.title,
        "role_needed": payload.role_needed,
        "specialty": payload.specialty,
        "description": payload.description,
        "location": payload.location,
        "modality": payload.modality,
        "requirements": payload.requirements,
        "status": payload.status,
        "deadline": serialize_date(payload.deadline),
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    opportunity_ref.set(opportunity_data)
    return OpportunityResponse(**opportunity_data)


def list_my_opportunities(current_user: CurrentUser) -> list[OpportunityResponse]:
    query = db.collection("opportunities").where("owner_uid", "==", current_user.uid)
    items = [_serialize_opportunity(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at or "", reverse=True)


def update_my_opportunity(
    opportunity_id: str,
    payload: OpportunityUpdateRequest,
    current_user: CurrentUser,
) -> OpportunityResponse:
    opportunity_doc = _get_opportunity_owned_by_user(opportunity_id, current_user)
    existing_data = opportunity_doc.to_dict() or {}
    updated_data = {
        "id": existing_data.get("id") or opportunity_doc.id,
        "project_id": existing_data.get("project_id"),
        "owner_uid": current_user.uid,
        "title": payload.title,
        "role_needed": payload.role_needed,
        "specialty": payload.specialty,
        "description": payload.description,
        "location": payload.location,
        "modality": payload.modality,
        "requirements": payload.requirements,
        "status": payload.status,
        "deadline": serialize_date(payload.deadline),
        "created_at": existing_data.get("created_at"),
        "updated_at": utc_now_iso(),
    }

    opportunity_doc.reference.set(updated_data)
    return OpportunityResponse(**updated_data)


def update_my_opportunity_status(
    opportunity_id: str,
    payload: OpportunityStatusUpdateRequest,
    current_user: CurrentUser,
) -> OpportunityResponse:
    opportunity_doc = _get_opportunity_owned_by_user(opportunity_id, current_user)
    existing_data = opportunity_doc.to_dict() or {}
    updated_data = {
        **existing_data,
        "id": existing_data.get("id") or opportunity_doc.id,
        "status": payload.status,
        "updated_at": utc_now_iso(),
    }

    opportunity_doc.reference.set(updated_data)
    return _serialize_opportunity(opportunity_doc.id, updated_data)

```

### app/services/project_service.py
```python
from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import serialize_date, utc_now_iso
from app.schemas.auth_schema import CurrentUser
from app.schemas.project_schema import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest


def _serialize_project(project_id: str, data: dict) -> ProjectResponse:
    return ProjectResponse(
        id=data.get("id") or project_id,
        owner_uid=data.get("owner_uid", ""),
        title=data.get("title", ""),
        description=data.get("description", ""),
        production_type=data.get("production_type", ""),
        location=data.get("location", ""),
        start_date=serialize_date(data.get("start_date")),
        end_date=serialize_date(data.get("end_date")),
        status=data.get("status", ""),
        created_at=serialize_date(data.get("created_at")) or "",
        updated_at=serialize_date(data.get("updated_at")) or "",
    )


def _get_project_owned_by_user(project_id: str, current_user: CurrentUser):
    project_doc = db.collection("projects").document(project_id).get()

    if not project_doc.exists:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    project_data = project_doc.to_dict() or {}

    if project_data.get("owner_uid") != current_user.uid:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre este proyecto")

    return project_doc


def create_project(payload: ProjectCreateRequest, current_user: CurrentUser) -> ProjectResponse:
    project_ref = db.collection("projects").document()
    timestamp = utc_now_iso()
    project_data = {
        "id": project_ref.id,
        "owner_uid": current_user.uid,
        "title": payload.title,
        "description": payload.description,
        "production_type": payload.production_type,
        "location": payload.location,
        "start_date": serialize_date(payload.start_date),
        "end_date": serialize_date(payload.end_date),
        "status": payload.status,
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    project_ref.set(project_data)
    return ProjectResponse(**project_data)


def list_my_projects(current_user: CurrentUser) -> list[ProjectResponse]:
    query = db.collection("projects").where("owner_uid", "==", current_user.uid)
    items = [_serialize_project(doc.id, doc.to_dict() or {}) for doc in query.stream()]
    return sorted(items, key=lambda item: item.created_at, reverse=True)


def get_my_project_by_id(project_id: str, current_user: CurrentUser) -> ProjectResponse:
    project_doc = _get_project_owned_by_user(project_id, current_user)
    return _serialize_project(project_doc.id, project_doc.to_dict() or {})


def update_my_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    current_user: CurrentUser,
) -> ProjectResponse:
    project_doc = _get_project_owned_by_user(project_id, current_user)
    existing_data = project_doc.to_dict() or {}
    updated_data = {
        "id": existing_data.get("id") or project_doc.id,
        "owner_uid": current_user.uid,
        "title": payload.title,
        "description": payload.description,
        "production_type": payload.production_type,
        "location": payload.location,
        "start_date": serialize_date(payload.start_date),
        "end_date": serialize_date(payload.end_date),
        "status": payload.status,
        "created_at": existing_data.get("created_at") or utc_now_iso(),
        "updated_at": utc_now_iso(),
    }

    project_doc.reference.set(updated_data)
    return ProjectResponse(**updated_data)

```

## Requests Postman

### POST /projects
```http
POST /projects
Authorization: Bearer <FIREBASE_ID_TOKEN>
Content-Type: application/json

{
  "title": "Horizonte Sur",
  "description": "Serie de ficcion en etapa de desarrollo",
  "production_type": "Serie",
  "location": "Santiago, Chile",
  "start_date": "2026-05-01",
  "end_date": "2026-08-30",
  "status": "ACTIVE"
}
```

### GET /projects/me
```http
GET /projects/me
Authorization: Bearer <FIREBASE_ID_TOKEN>
```

### GET /projects/{id}
```http
GET /projects/project123
Authorization: Bearer <FIREBASE_ID_TOKEN>
```

### PUT /projects/{id}
```http
PUT /projects/project123
Authorization: Bearer <FIREBASE_ID_TOKEN>
Content-Type: application/json

{
  "title": "Horizonte Sur",
  "description": "Serie de ficcion en etapa de desarrollo avanzada",
  "production_type": "Serie",
  "location": "Santiago, Chile",
  "start_date": "2026-05-01",
  "end_date": "2026-09-15",
  "status": "IN_PRODUCTION"
}
```

### POST /opportunities
```http
POST /opportunities
Authorization: Bearer <FIREBASE_ID_TOKEN>
Content-Type: application/json

{
  "project_id": "project123",
  "title": "Casting actor secundario",
  "role_needed": "Actor secundario",
  "specialty": "Actor",
  "description": "Buscamos actor secundario para serie de ficcion",
  "location": "Santiago, Chile",
  "modality": "Por proyecto",
  "requirements": ["Experiencia en ficcion", "Disponibilidad en mayo"],
  "status": "OPEN",
  "deadline": "2026-05-10"
}
```

### GET /opportunities/me
```http
GET /opportunities/me
Authorization: Bearer <FIREBASE_ID_TOKEN>
```

### PUT /opportunities/{id}
```http
PUT /opportunities/op-123
Authorization: Bearer <FIREBASE_ID_TOKEN>
Content-Type: application/json

{
  "title": "Casting actor secundario",
  "role_needed": "Actor secundario",
  "specialty": "Actor",
  "description": "Buscamos actor secundario para serie de ficcion con disponibilidad flexible",
  "location": "Santiago, Chile",
  "modality": "Por proyecto",
  "requirements": ["Experiencia en ficcion", "Disponibilidad en mayo"],
  "status": "OPEN",
  "deadline": "2026-05-15"
}
```

### PATCH /opportunities/{id}/status
```http
PATCH /opportunities/op-123/status
Authorization: Bearer <FIREBASE_ID_TOKEN>
Content-Type: application/json

{
  "status": "CLOSED"
}
```
