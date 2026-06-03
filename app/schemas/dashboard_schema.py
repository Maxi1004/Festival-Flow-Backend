from pydantic import BaseModel, Field

from app.schemas.talent_schema import AvailabilityStatus, WorkModality


class DashboardProjectSummary(BaseModel):
    id: str
    title: str
    production_type: str
    location: str
    start_date: str | None = None


class DashboardOpportunitySummary(BaseModel):
    id: str
    project_id: str | None = None
    title: str
    role_needed: str
    specialty: str
    location: str
    status: str


class DashboardApplicationSummary(BaseModel):
    id: str
    opportunity_id: str
    opportunity_title: str
    status: str
    message: str
    applied_at: str | None = None


class DashboardTalentProfileSummary(BaseModel):
    specialties: list[str] = Field(default_factory=list)


class DashboardAvailableTalentSummary(BaseModel):
    user_id: str
    name: str
    email: str
    photo_url: str | None = None
    picture: str | None = None
    avatar_url: str | None = None
    status: AvailabilityStatus
    travel_availability: bool
    work_modality: WorkModality
    location: str | None = None
    available_from: str | None = None
    notes: str | None = None
    profile: DashboardTalentProfileSummary


class ProducerDashboardResponse(BaseModel):
    projects_count: int
    opportunities_count: int
    active_opportunities_count: int
    closed_opportunities_count: int
    latest_projects: list[DashboardProjectSummary]
    active_opportunities: list[DashboardOpportunitySummary]
    closed_opportunities: list[DashboardOpportunitySummary]
    available_talents: list[DashboardAvailableTalentSummary]


class ProducerDashboardQuickResponse(BaseModel):
    projects_count: int
    opportunities_count: int
    active_opportunities_count: int
    closed_opportunities_count: int


class ProducerDashboardDetailsResponse(BaseModel):
    latest_projects: list[DashboardProjectSummary]
    active_opportunities: list[DashboardOpportunitySummary]
    closed_opportunities: list[DashboardOpportunitySummary]
    available_talents: list[DashboardAvailableTalentSummary]


class TalentDashboardResponse(BaseModel):
    profile_completion: int
    main_specialty: str
    location: str
    applications_count: int
    opportunities_count: int
    available_opportunities: list[DashboardOpportunitySummary]
    applications: list[DashboardApplicationSummary]


class TalentDashboardQuickResponse(BaseModel):
    profile_completion: int
    main_specialty: str
    location: str
    applications_count: int
    opportunities_count: int


class TalentDashboardDetailsResponse(BaseModel):
    available_opportunities: list[DashboardOpportunitySummary]
    applications: list[DashboardApplicationSummary]
