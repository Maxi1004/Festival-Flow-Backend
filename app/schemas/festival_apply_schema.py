from typing import Any

from pydantic import BaseModel, Field


class FestivalApplyItem(BaseModel):
    festival_id: str
    login_url: str
    username: str
    password: str  # only held in memory during processing, never persisted


class ApplyBatchRequest(BaseModel):
    festivals: list[FestivalApplyItem] = Field(..., min_length=1, max_length=50)
    film_data: dict[str, Any] = Field(default_factory=dict)


class ApplyBatchResponse(BaseModel):
    batch_id: str
    total: int


# ── analyze-forms ─────────────────────────────────────────────────────────────

class FestivalCredentials(BaseModel):
    login_url: str
    username: str
    password: str  # only held in memory, never persisted


class AnalyzeFormsRequest(BaseModel):
    festival_ids: list[str] = Field(..., min_length=1, max_length=20)
    credentials_map: dict[str, FestivalCredentials]


class AnalyzeFormsResponse(BaseModel):
    analyze_batch_id: str
    unified_form: dict[str, Any]
    fields_by_festival: dict[str, Any]


# ── submit-forms ──────────────────────────────────────────────────────────────

class SubmitFormsRequest(BaseModel):
    batch_id: str  # analyze_batch_id returned by analyze-forms
    form_data: dict[str, Any] = Field(default_factory=dict)


class SubmitFormsResponse(BaseModel):
    submit_batch_id: str
    total: int
