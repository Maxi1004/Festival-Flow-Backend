from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.schemas.auth_schema import CurrentUser
from app.schemas.scraper_schema import (
    ExtractFormRequest,
    ExtractFormResponse,
    LoginRequest,
    LoginResponse,
    UnifiedFormRequest,
    UnifiedFormResponse,
)
from app.services.gemini_unified_form_service import generate_unified_form
from app.services.scraper_service import extract_form_from_url, login_and_save_session

router = APIRouter(prefix="/api/scraper", tags=["Scraper"])


@router.post("/login", response_model=LoginResponse)
async def scraper_login(
    payload: LoginRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Log in to an external site and save the browser session for later reuse.

    Returns LOGIN_OK + session_id on success, CAPTCHA_REQUIRED if a captcha
    is detected, or LOGIN_FAILED if credentials are rejected.

    The password is never returned or logged.
    """
    try:
        result = await login_and_save_session(
            login_url=payload.login_url,
            target_url=payload.target_url,
            username=payload.username,
            password=payload.password,
        )
        return LoginResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error durante el login: {type(exc).__name__}: {exc}",
        ) from exc


@router.post("/extract-form", response_model=ExtractFormResponse)
async def scraper_extract_form(
    payload: ExtractFormRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Navigate to target_url and extract all visible form fields.

    If session_id is provided and a saved session exists, it is loaded
    automatically so authenticated pages can be accessed.
    """
    try:
        result = await extract_form_from_url(
            target_url=payload.target_url,
            session_id=payload.session_id,
        )
        return ExtractFormResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error extrayendo formulario: {type(exc).__name__}: {exc}",
        ) from exc


@router.post("/generate-unified-form", response_model=UnifiedFormResponse)
async def scraper_generate_unified_form(
    payload: UnifiedFormRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Generate one normalized master form from fields extracted by Playwright.
    """
    return await generate_unified_form(
        source_url=payload.source_url,
        fields=payload.fields,
    )
