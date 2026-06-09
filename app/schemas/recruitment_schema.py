from enum import Enum

from pydantic import BaseModel, Field, field_validator


class RecruitmentStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RecruitmentDecisionStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RecruitmentCreateRequest(BaseModel):
    talent_user_id: str
    project_id: str
    opportunity_id: str | None = None
    role: str | None = None
    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("message no debe estar vacio")
        return message


class RecruitmentStatusUpdateRequest(BaseModel):
    status: RecruitmentDecisionStatus
    category: str | None = None
    role: str | None = None
    task_description: str | None = None


class RecruitmentResponse(BaseModel):
    id: str
    producer_id: str
    talent_user_id: str
    project_id: str | None = None
    opportunity_id: str | None = None
    role: str | None = None
    message: str
    status: RecruitmentStatus
    created_at: str
    updated_at: str


class RecruitmentProjectSummary(BaseModel):
    id: str
    title: str
    status: str | None = None


class RecruitmentOpportunitySummary(BaseModel):
    id: str
    title: str
    status: str | None = None


class RecruitmentProducerSummary(BaseModel):
    user_id: str
    name: str
    email: str


class RecruitmentInvitationResponse(RecruitmentResponse):
    project: RecruitmentProjectSummary | None = None
    opportunity: RecruitmentOpportunitySummary | None = None
    producer: RecruitmentProducerSummary | None = None


class TalentRecruitmentFeedItem(BaseModel):
    id: str
    project_id: str | None = None
    project_title: str
    opportunity_id: str | None = None
    opportunity_title: str
    producer_uid: str
    producer_name: str
    role: str | None = None
    category: str
    message: str
    status: RecruitmentStatus
    created_at: str
    updated_at: str


class TalentRecruitmentFeedSummary(BaseModel):
    total: int = 0
    pending: int = 0
    accepted: int = 0
    rejected: int = 0
    cancelled: int = 0


class TalentRecruitmentFeedResponse(BaseModel):
    items: list[TalentRecruitmentFeedItem] = Field(default_factory=list)
    next_cursor: str | None = None
    summary: TalentRecruitmentFeedSummary | None = None
