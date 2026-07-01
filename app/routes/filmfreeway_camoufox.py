"""
filmfreeway_camoufox.py
========================
Integracion FastAPI del script Camoufox de FilmFreeway
(flimfreeway-scraper-lab/backend/app/camoufox_service.py + main.py).

La logica de scraping/login/rellenado/guardado vive intacta en
app/services/filmfreeway_camoufox_service.py. Este router solo agrega:
  - autenticacion (Depends(get_current_user))
  - el mismo worker de un solo hilo que serializaba los jobs de Camoufox
    en el main.py original, para no ejecutar Playwright sync concurrentemente.
"""

import threading
from dataclasses import dataclass
from queue import Queue
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.schemas.auth_schema import CurrentUser
from app.schemas.filmfreeway_camoufox_schema import FillFormRequest, LoginRequest
from app.services.filmfreeway_camoufox_service import analyze_filmfreeway_form, fill_open_form

router = APIRouter(tags=["FilmFreeway Camoufox"])


@dataclass
class CamoufoxJob:
    fn: Callable[[], Any]
    done: threading.Event
    result: Any = None
    error: BaseException | None = None


_camoufox_jobs: Queue[CamoufoxJob] = Queue()


def _camoufox_worker() -> None:
    while True:
        job = _camoufox_jobs.get()
        try:
            job.result = job.fn()
        except BaseException as exc:
            job.error = exc
        finally:
            job.done.set()
            _camoufox_jobs.task_done()


threading.Thread(target=_camoufox_worker, name="camoufox-worker", daemon=True).start()


def run_camoufox_job(fn: Callable[[], Any]) -> Any:
    job = CamoufoxJob(fn=fn, done=threading.Event())
    _camoufox_jobs.put(job)
    job.done.wait()
    if job.error:
        raise job.error
    return job.result


@router.post("/api/analyze-filmfreeway")
def analyze_filmfreeway(req: LoginRequest, current_user: CurrentUser = Depends(get_current_user)):
    try:
        if not req.username or not req.password:
            raise ValueError("Usuario y contrasena FilmFreeway son obligatorios.")

        return run_camoufox_job(
            lambda: analyze_filmfreeway_form(req.username, req.password, req.festival_url)
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/analyze-filmfreeway-camoufox")
def analyze_filmfreeway_camoufox(req: LoginRequest, current_user: CurrentUser = Depends(get_current_user)):
    return analyze_filmfreeway(req, current_user)


@router.post("/api/fill-open-form")
def fill_form(req: FillFormRequest, current_user: CurrentUser = Depends(get_current_user)):
    try:
        return run_camoufox_job(
            lambda: fill_open_form(req.analyze_batch_id, req.form_values)
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
