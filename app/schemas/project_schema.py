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
