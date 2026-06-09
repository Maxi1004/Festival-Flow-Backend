from typing import Literal

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
    category: str = "OTHER"
    category_label: str = "Other"
    task_description: str | None = None
    producer_note: str | None = None
    status: str
    joined_at: str | None = None
    updated_at: str | None = None


class CrewMemberUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    category: str | None = None
    task_description: str | None = None
    status: str | None = None
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


class ProjectCrewMemberResponse(BaseModel):
    id: str
    project_id: str
    user_id: str
    user_uid: str
    talent_user_id: str
    talent_uid: str | None = None
    name: str
    email: str
    photo_url: str | None = None
    main_specialty: str = ""
    specialties: list[str] = Field(default_factory=list)
    profile: dict | None = None
    talent_profile: dict | None = None
    role: str | None = None
    category: str = "OTHER"
    category_label: str = "Other"
    task_description: str | None = None
    status: str
    joined_at: str | None = None
    opportunity_title: str | None = None
    application_status: str | None = None


class ProjectCrewMembersResponse(BaseModel):
    items: list[ProjectCrewMemberResponse] = Field(default_factory=list)


class CrewProjectCrmResponse(BaseModel):
    project_id: str
    project_title: str = ""
    members_count: int = 0
    categories: list[str] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    top_categories: list[str] = Field(default_factory=list)
    status: str = ""
    last_activity: str | None = None
    members: list[ProjectCrewMemberResponse] | None = None


class ProjectMessageCreateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("message no debe estar vacio")
        return message


class ProjectChatMessageResponse(BaseModel):
    id: str
    project_id: str
    sender_uid: str
    sender_name: str
    sender_role: str
    sender_photo_url: str | None = None
    message: str
    created_at: str


class CrewDirectMessageResponse(BaseModel):
    id: str
    project_id: str
    conversation_key: str
    sender_uid: str
    receiver_uid: str
    sender_name: str
    receiver_name: str
    sender_photo_url: str | None = None
    receiver_photo_url: str | None = None
    message: str
    created_at: str


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


class TalentCrewFeedItem(BaseModel):
    id: str
    project_id: str | None = None
    project_title: str
    opportunity_id: str | None = None
    opportunity_title: str
    producer_name: str
    role: str | None = None
    category: str = "OTHER"
    category_label: str = "Other"
    task_description: str | None = None
    producer_note: str | None = None
    status: str
    joined_at: str | None = None
    updated_at: str | None = None
    messages_count: int = 0


class TalentCrewFeedSummary(BaseModel):
    total: int = 0
    active: int = 0
    completed: int = 0
    cancelled: int = 0


class TalentCrewFeedResponse(BaseModel):
    items: list[TalentCrewFeedItem] = Field(default_factory=list)
    next_cursor: str | None = None
    summary: TalentCrewFeedSummary | None = None


class MessageConversationParticipant(BaseModel):
    user_uid: str
    name: str = ""
    avatar_url: str | None = None
    role: str | None = None


class MessageConversationItem(BaseModel):
    id: str
    type: Literal["DIRECT", "TEAM"]
    project_id: str | None = None
    project_title: str = ""
    title: str
    subtitle: str
    avatar_url: str | None = None
    last_message: str = ""
    last_message_at: str | None = None
    unread_count: int = 0
    participants: list[MessageConversationParticipant] = Field(default_factory=list)


class MessageConversationFeedResponse(BaseModel):
    items: list[MessageConversationItem] = Field(default_factory=list)
    next_cursor: str | None = None


class UnifiedConversationMessageResponse(BaseModel):
    id: str
    conversation_id: str
    sender_uid: str
    sender_name: str = ""
    sender_role: str = ""
    sender_photo_url: str | None = None
    message: str
    created_at: str


class TeamChatSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=80)
    photo_url: str | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated. Use POST /messages/me/conversations/{conversation_id}/team-photo.",
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("name no debe estar vacio")
        return name


class TeamChatPhotoResponse(BaseModel):
    photo_url: str


class MessageConversationInfoParticipant(BaseModel):
    uid: str
    name: str = ""
    email: str = ""
    photo_url: str | None = None
    role: str | None = None
    task_description: str | None = None
    status: str = ""


class MessageConversationInfoResponse(BaseModel):
    id: str
    type: Literal["DIRECT", "TEAM"]
    project_id: str | None = None
    project_title: str = ""
    title: str
    avatar_url: str | None = None
    participants: list[MessageConversationInfoParticipant] = Field(default_factory=list)
