from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.schemas.auth_schema import CurrentUser
from app.schemas.translation_schema import (
    TranslationLanguageResponse,
    TranslationRequest,
    TranslationResponse,
)
from app.services.translation_service import list_supported_languages, translate_texts


router = APIRouter(tags=["Translation"])


@router.get("/languages", response_model=list[TranslationLanguageResponse])
async def get_languages():
    return list_supported_languages()


@router.post("/translate", response_model=TranslationResponse)
async def post_translate(
    payload: TranslationRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return translate_texts(
        texts=payload.texts,
        target_language=payload.target_lang,
        source_language=payload.source_lang,
    )
