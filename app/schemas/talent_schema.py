from datetime import date

from pydantic import BaseModel, Field


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
    status: str = ""
    travel_availability: bool = False
    work_modality: str = ""
    work_location: str = ""
    available_from: date | None = None
    notes: str = ""


class TalentAvailabilityResponse(BaseModel):
    user_uid: str
    status: str
    travel_availability: bool
    work_modality: str
    work_location: str
    available_from: str | None = None
    notes: str
    updated_at: str | None = None
