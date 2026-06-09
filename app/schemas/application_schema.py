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
    user_uid: str
    name: str
    email: str
    photo_url: str | None = None


class ApplicationTalentProfile(BaseModel):
    display_name: str = ""
    bio: str = ""
    main_specialty: str = ""
    specialties: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    experience_years: int | None = None
    photo_url: str | None = None
    portfolio_url: str | None = None
    portfolio_pdf_url: str | None = None


class OpportunityApplicationResponse(BaseModel):
    id: str
    opportunity_id: str
    user_id: str
    talent_user_id: str
    talent_name: str
    talent_email: str
    photo_url: str | None = None
    status: str
    message: str
    created_at: str | None = None
    talent: ApplicationTalentSummary
    profile: ApplicationTalentProfile
    talent_profile: ApplicationTalentProfile


class ApplicationStatusUpdateRequest(BaseModel):
    status: ProducerApplicationStatus
    category: str | None = None
    role: str | None = None
    task_description: str | None = None


class ApplicationStatusUpdateResponse(BaseModel):
    id: str
    status: ProducerApplicationStatus
    updated_at: str
