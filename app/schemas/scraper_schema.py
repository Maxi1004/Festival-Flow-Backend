from pydantic import BaseModel, ConfigDict, Field
from typing import Any, List, Optional


class LoginRequest(BaseModel):
    login_url: str
    target_url: str
    username: str
    password: str


class LoginResponse(BaseModel):
    status: str  # LOGIN_OK | CAPTCHA_REQUIRED | LOGIN_FAILED
    session_id: Optional[str] = None
    message: Optional[str] = None


class ExtractFormRequest(BaseModel):
    target_url: str
    session_id: Optional[str] = None


class ScrapedField(BaseModel):
    label: str
    id: Optional[str] = None
    name: Optional[str] = None
    type: str = "text"
    required: bool = False
    placeholder: Optional[str] = None
    options: List[str] = []


class ExtractFormResponse(BaseModel):
    url: str
    fields: List[ScrapedField]


class UnifiedFormRequest(BaseModel):
    source_url: str
    fields: list[dict[str, Any]]


class UnifiedFormField(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str
    label: str
    type: str
    required: bool = False
    options: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list, alias="sourceFields")


class UnifiedFormSection(BaseModel):
    title: str
    fields: list[UnifiedFormField] = Field(default_factory=list)


class UnifiedForm(BaseModel):
    title: str
    description: str
    sections: list[UnifiedFormSection] = Field(default_factory=list)


class UnifiedFormResponse(BaseModel):
    form: UnifiedForm
