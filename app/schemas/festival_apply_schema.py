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
    structured_form: dict[str, Any] = Field(default_factory=dict)


# ── submit-forms ──────────────────────────────────────────────────────────────

class SubmitFormsRequest(BaseModel):
    batch_id: str  # analyze_batch_id returned by analyze-forms
    form_data: dict[str, Any] = Field(default_factory=dict)


class SubmitFormsResponse(BaseModel):
    submit_batch_id: str
    total: int


# ── generate-form-answers ─────────────────────────────────────────────────────

class GenerateFormAnswersRequest(BaseModel):
    analyze_batch_id: str
    project_id: str


class FormFieldValue(BaseModel):
    value: Any
    confidence: float  # 0.0–1.0
    source: str        # "project" | "ai" | "default" | "manual"


class MissingField(BaseModel):
    field: str
    reason: str


class GenerateFormAnswersResponse(BaseModel):
    project: dict[str, Any]
    form_values: dict[str, FormFieldValue]
    missing_fields: list[MissingField]
    mapped_fields: int
    missing_count: int


# ── fill-open-form ────────────────────────────────────────────────────────────

class FillOpenFormRequest(BaseModel):
    analyze_batch_id: str
    form_values: dict[str, Any]


class FillOpenFormResponse(BaseModel):
    status: str
    filled_count: int
    skipped_count: int
    errors: list[dict]
