from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FestivalStatus(str, Enum):
    OPEN = "OPEN"
    UPCOMING = "UPCOMING"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"
    UNKNOWN = "UNKNOWN"


class FestivalResponse(BaseModel):
    id: str
    name: str = ""
    country: str = ""
    website: str = ""
    submission_url: str = ""
    platform: str = ""
    opening_date: str = ""
    deadline: str = ""
    event_date: str = ""
    fee: str = ""
    status: FestivalStatus = FestivalStatus.UNKNOWN
    form_fields: list = Field(default_factory=list)
    edition_year: str = ""
    contact: str = ""
    notes: str = ""
    source: str = "excel"
    last_checked_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class FestivalProducerResponse(BaseModel):
    id: str
    name: str = ""
    country: str = ""
    website: str = ""
    submission_url: str = ""
    platform: str = ""
    opening_date: str = ""
    deadline: str = ""
    event_date: str = ""
    fee: str = ""
    status: FestivalStatus = FestivalStatus.UNKNOWN
    edition_year: str = ""
    notes: str = ""
    source: str = "excel"
    days_until_deadline: int | None = None
    selected_by_me: bool = False


class FestivalSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    festival_id: str

    @field_validator("festival_id")
    @classmethod
    def festival_id_must_be_valid(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("festival_id no debe estar vacio")
        if "/" in normalized:
            raise ValueError("festival_id no es valido")
        return normalized


class FestivalSelectionResponse(BaseModel):
    id: str
    producer_uid: str
    festival_id: str
    status: str = "SELECTED"
    created_at: str = ""
    updated_at: str = ""
    festival: FestivalProducerResponse


class FestivalUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    country: str | None = None
    website: str | None = None
    submission_url: str | None = None
    platform: str | None = None
    opening_date: str | None = None
    deadline: str | None = None
    event_date: str | None = None
    fee: str | None = None
    status: FestivalStatus | None = None
    edition_year: str | None = None
    contact: str | None = None
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("name no debe estar vacio")
        return value


class FestivalImportResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class FestivalStatusCounts(BaseModel):
    OPEN: int = 0
    UPCOMING: int = 0
    CLOSED: int = 0
    ARCHIVED: int = 0
    UNKNOWN: int = 0


class FestivalRefreshStatusResponse(BaseModel):
    updated: int
    counts: FestivalStatusCounts


class FestivalCleanupConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
