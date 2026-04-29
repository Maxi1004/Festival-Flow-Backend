from pydantic import BaseModel, ConfigDict, Field, field_validator


class CrewTalentSummary(BaseModel):
    user_id: str
    name: str
    email: str


class CrewProducerSummary(BaseModel):
    user_id: str
    name: str
    email: str


class CrewProjectSummary(BaseModel):
    id: str
    title: str


class CrewOpportunitySummary(BaseModel):
    id: str
    title: str


class CrewMemberResponse(BaseModel):
    id: str
    project_id: str | None = None
    opportunity_id: str | None = None
    talent: CrewTalentSummary
    producer: CrewProducerSummary | None = None
    project: CrewProjectSummary | None = None
    opportunity: CrewOpportunitySummary | None = None
    source: str
    role: str | None = None
    task_description: str | None = None
    producer_note: str | None = None
    status: str
    joined_at: str | None = None
    updated_at: str | None = None


class CrewMemberUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    task_description: str | None = None
    producer_note: str | None = None


class CrewMessageCreateRequest(BaseModel):
    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("message no debe estar vacio")
        return message


class CrewMessageResponse(BaseModel):
    id: str
    crew_member_id: str
    sender_id: str
    sender_role: str
    message: str
    created_at: str


class CrewConversationResponse(BaseModel):
    crew_member_id: str
    project: CrewProjectSummary | None = None
    opportunity: CrewOpportunitySummary | None = None
    talent: CrewTalentSummary
    producer: CrewProducerSummary | None = None
    role: str | None = None
    last_message: CrewMessageResponse | None = None
    last_message_at: str | None = None
    unread_count: int = 0
