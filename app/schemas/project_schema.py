from datetime import date

from pydantic import BaseModel, field_validator

ALLOWED_STATUSES = {
    # Inglés
    "draft", "active", "completed", "published",
    "in_development", "post_production", "cancelled",
    # Español
    "borrador", "activo", "finalizado", "completado", "publicado",
    "en_desarrollo", "post_produccion", "cancelado",
}


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


class ProjectStatusUpdateRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in ALLOWED_STATUSES:
            raise ValueError(
                f"Estado '{v}' no válido. Opciones: {sorted(ALLOWED_STATUSES)}"
            )
        return normalized


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
