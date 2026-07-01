from pydantic import BaseModel


class LoginRequest(BaseModel):
    festival_url: str = ""
    username: str = ""
    password: str = ""


class FillFormRequest(BaseModel):
    analyze_batch_id: str
    form_values: dict[str, object]
