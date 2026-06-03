import os
from typing import Any

from fastapi import HTTPException
import requests

from app.schemas.translation_schema import (
    SUPPORTED_TRANSLATION_LANGUAGES,
    TranslationItemResponse,
    TranslationLanguageResponse,
    TranslationResponse,
)


GOOGLE_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
GOOGLE_TRANSLATE_TIMEOUT_SECONDS = 10


def _google_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if message:
            return str(message)
    return "Google Translate respondio con error"


def translate_texts(
    texts: list[str],
    target_language: str,
    source_language: str | None = "es",
) -> TranslationResponse:
    api_key = os.getenv("GOOGLE_TRANSLATE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Falta configurar GOOGLE_TRANSLATE_API_KEY en el backend",
        )

    payload: dict[str, Any] = {
        "q": texts,
        "target": target_language,
        "format": "text",
    }
    if source_language:
        payload["source"] = source_language

    try:
        response = requests.post(
            GOOGLE_TRANSLATE_URL,
            params={"key": api_key},
            json=payload,
            timeout=GOOGLE_TRANSLATE_TIMEOUT_SECONDS,
        )
    except requests.Timeout as error:
        raise HTTPException(status_code=504, detail="Google Translate no respondio a tiempo") from error
    except requests.RequestException as error:
        raise HTTPException(status_code=502, detail="No se pudo conectar con Google Translate") from error

    try:
        response_payload = response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Google Translate respondio con JSON invalido") from error

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=_google_error_message(response_payload),
        )

    translation_rows = response_payload.get("data", {}).get("translations")
    if not isinstance(translation_rows, list) or len(translation_rows) != len(texts):
        raise HTTPException(status_code=502, detail="Google Translate respondio con formato inesperado")
    if not all(isinstance(translation, dict) for translation in translation_rows):
        raise HTTPException(status_code=502, detail="Google Translate respondio con formato inesperado")

    return TranslationResponse(
        translations=[
            TranslationItemResponse(
                original=original,
                translated=str(translation.get("translatedText") or ""),
                detected_source_language=translation.get("detectedSourceLanguage") or source_language,
            )
            for original, translation in zip(texts, translation_rows, strict=True)
        ]
    )


def list_supported_languages() -> list[TranslationLanguageResponse]:
    return [
        TranslationLanguageResponse(code=code, label=label)
        for code, label in SUPPORTED_TRANSLATION_LANGUAGES.items()
    ]
