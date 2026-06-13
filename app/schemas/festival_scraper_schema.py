from pydantic import BaseModel
from typing import Any


class ScrapeFormRequest(BaseModel):
    url: str


class ScrapedFormField(BaseModel):
    key: str
    label: str
    type: str
    required: bool = False
    placeholder: str | None = None
    name: str | None = None
    id: str | None = None
    selector: str | None = None
    options: list[str] = []
    max_length: int | None = None
    source: str = "playwright"


class ScrapeFormResponse(BaseModel):
    url: str
    status: str
    fields: list[ScrapedFormField]
    forms_found: int
    fields_found: int
    requires_login: bool
    requires_payment: bool
    requires_captcha: bool
    requires_manual: bool
    message: str | None = None
    raw_flags: dict[str, Any] = {}