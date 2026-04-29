from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, StrictBool, model_validator


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class WorkModality(str, Enum):
    FREELANCE = "FREELANCE"
    REMOTE = "REMOTE"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"


class PortfolioLink(BaseModel):
    label: str
    url: str


class TalentProfileUpsertRequest(BaseModel):
    display_name: str | None = None
    bio: str = ""
    main_specialty: str = ""
    specialties: list[str] = Field(default_factory=list)
    location: str = ""
    experience_years: int = Field(default=0, ge=0)
    languages: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    portfolio_links: list[PortfolioLink] = Field(default_factory=list)
    profile_completion: int = Field(default=0, ge=0, le=100)
    is_public: bool = False


class TalentProfileResponse(BaseModel):
    user_uid: str
    display_name: str
    bio: str
    main_specialty: str
    specialties: list[str]
    location: str
    experience_years: int
    languages: list[str]
    skills: list[str]
    portfolio_links: list[PortfolioLink]
    profile_completion: int
    is_public: bool
    updated_at: str | None = None


class TalentAvailabilityUpsertRequest(BaseModel):
    status: AvailabilityStatus
    travel_availability: StrictBool
    work_modality: WorkModality
    location: str | None = None
    available_from: date | None = None
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_field_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = data.copy()
        if "location" not in normalized and "work_location" in normalized:
            normalized["location"] = normalized["work_location"]
        if "work_modality" not in normalized and "modality" in normalized:
            normalized["work_modality"] = normalized["modality"]
        if "status" not in normalized and "availability_status" in normalized:
            normalized["status"] = normalized["availability_status"]
        if "travel_availability" not in normalized and "available_to_travel" in normalized:
            normalized["travel_availability"] = normalized["available_to_travel"]

        return normalized


class TalentAvailabilityResponse(BaseModel):
    user_id: str
    status: AvailabilityStatus
    travel_availability: bool
    work_modality: WorkModality
    location: str | None = None
    available_from: str | None = None
    notes: str | None = None
    updated_at: str | None = None


class AvailableTalentProfile(BaseModel):
    specialties: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience_years: int | None = None
    portfolio_url: str | None = None


class AvailableTalentResponse(BaseModel):
    user_id: str
    name: str
    email: str
    status: AvailabilityStatus
    travel_availability: bool
    work_modality: WorkModality
    location: str | None = None
    available_from: str | None = None
    notes: str | None = None
    profile: AvailableTalentProfile
