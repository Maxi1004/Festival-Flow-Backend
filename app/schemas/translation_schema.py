from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


SUPPORTED_TRANSLATION_LANGUAGES = {
    "es": "Español",
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "zh": "中文",
    "ko": "한국어",
    "ja": "日本語",
}


def _normalize_language_code(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower()


def _validate_supported_language(value: str, field_name: str) -> str:
    language = _normalize_language_code(value)
    if not language:
        raise ValueError(f"{field_name} no debe estar vacio")
    if language not in SUPPORTED_TRANSLATION_LANGUAGES:
        supported_codes = ", ".join(SUPPORTED_TRANSLATION_LANGUAGES)
        raise ValueError(f"{field_name} debe ser uno de: {supported_codes}")
    return language


class TranslationRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=100)
    target_lang: str = Field(min_length=1, max_length=16)
    source_lang: str | None = Field(default="es", max_length=16)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_language_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = data.copy()
        if "target_lang" not in normalized and "target_language" in normalized:
            normalized["target_lang"] = normalized["target_language"]
        if "source_lang" not in normalized and "source_language" in normalized:
            normalized["source_lang"] = normalized["source_language"]
        return normalized

    @field_validator("texts")
    @classmethod
    def texts_must_be_valid(cls, values: list[str]) -> list[str]:
        cleaned_values: list[str] = []
        for value in values:
            text = value.strip()
            if not text:
                raise ValueError("texts no debe contener textos vacios")
            if len(text) > 5000:
                raise ValueError("cada texto debe tener como maximo 5000 caracteres")
            cleaned_values.append(text)
        return cleaned_values

    @field_validator("target_lang")
    @classmethod
    def target_language_must_be_supported(cls, value: str) -> str:
        return _validate_supported_language(value, "target_lang")

    @field_validator("source_lang")
    @classmethod
    def source_language_must_be_supported(cls, value: str | None) -> str:
        return _validate_supported_language(value or "es", "source_lang")


class TranslationItemResponse(BaseModel):
    original: str
    translated: str
    detected_source_language: str | None = None


class TranslationResponse(BaseModel):
    translations: list[TranslationItemResponse]


class TranslationLanguageResponse(BaseModel):
    code: str
    label: str
