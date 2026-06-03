from enum import Enum

from pydantic import BaseModel, Field


class ProducerApplicationStatus(str, Enum):
    REVIEWING = "REVIEWING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


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
    opportunity: dict | None = None
    project: dict | None = None


class TalentApplicationFeedItem(BaseModel):
    id: str
    opportunity_id: str
    project_id: str | None = None
    opportunity_title: str
    project_title: str
    status: str
    applied_at: str
    updated_at: str
    message: str
    result_label: str
    opportunity: dict | None = None
    project: dict | None = None


class TalentApplicationFeedSummary(BaseModel):
    total: int = 0
    active: int = 0
    reviewing: int = 0
    accepted: int = 0
    rejected: int = 0
    cancelled: int = 0
    completed: int = 0
    closed: int = 0
    acceptance_rate: int = 0


class TalentApplicationFeedResponse(BaseModel):
    items: list[TalentApplicationFeedItem] = Field(default_factory=list)
    next_cursor: str | None = None
    summary: TalentApplicationFeedSummary | None = None


class ApplicationTalentSummary(BaseModel):
    user_id: str
    name: str
    email: str


class ApplicationTalentProfile(BaseModel):
    specialties: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience_years: int | None = None
    portfolio_url: str | None = None


class OpportunityApplicationResponse(BaseModel):
    id: str
    opportunity_id: str
    status: str
    message: str
    created_at: str | None = None
    talent: ApplicationTalentSummary
    profile: ApplicationTalentProfile


class ApplicationStatusUpdateRequest(BaseModel):
    status: ProducerApplicationStatus


class ApplicationStatusUpdateResponse(BaseModel):
    id: str
    status: ProducerApplicationStatus
    updated_at: str
