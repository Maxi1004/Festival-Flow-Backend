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
