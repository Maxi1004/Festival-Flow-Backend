from pydantic import BaseModel


class ProducerProfileUpsertRequest(BaseModel):
    display_name: str | None = None
    company_name: str = ""
    role_title: str = ""
    bio: str = ""
    location: str = ""
    country: str = ""
    phone: str = ""
    website: str = ""


class ProducerProfileResponse(BaseModel):
    user_uid: str
    display_name: str
    company_name: str
    role_title: str
    bio: str
    location: str
    country: str
    phone: str
    website: str
    photo_url: str | None = None
    updated_at: str | None = None


class ProducerProfilePhotoResponse(BaseModel):
    photo_url: str
