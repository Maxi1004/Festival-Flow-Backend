from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user, require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.festival_scraper_schema import ScrapeFormRequest, ScrapeFormResponse
from app.services.festival_scraper_service import (
    scrape_and_save_festival_form,
    scrape_form_from_url,
)

router = APIRouter(tags=["Festival Scraper"])


@router.post("/festival-ai/scrape-form", response_model=ScrapeFormResponse)
async def scrape_form_by_url(
    payload: ScrapeFormRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await scrape_form_from_url(payload.url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo scrapear formulario: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error


@router.post("/admin/festivals/{festival_id}/scrape-form", response_model=ScrapeFormResponse)
async def admin_scrape_festival_form(
    festival_id: str,
    current_user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    try:
        return await scrape_and_save_festival_form(festival_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo scrapear formulario: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error


@router.post("/producer/festivals/{festival_id}/scrape-form", response_model=ScrapeFormResponse)
async def producer_scrape_festival_form(
    festival_id: str,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    try:
        return await scrape_and_save_festival_form(festival_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo scrapear formulario: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error
