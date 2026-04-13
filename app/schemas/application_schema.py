from pydantic import BaseModel


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
