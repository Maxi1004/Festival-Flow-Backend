"""
festival_apply.py
=================
POST /api/festivals/apply
    Enqueue a batch of festival applications.
    Returns {batch_id, total} immediately — processing runs in a background thread.

GET /api/festivals/apply/stream/{batch_id}
    Server-Sent Events stream that emits one JSON payload per festival as the
    background worker processes them, plus a terminal "__done__" event.

SSE event shape:
    data: {"festival_id": "abc123", "status": "processing|LOGIN_OK|LOGIN_FAILED|...", "message": "..."}

Terminal event:
    data: {"festival_id": "__done__", "status": "complete", "message": "Lote ... completado."}
"""

import asyncio
import json
import queue as queue_module

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.security import get_current_user
from app.schemas.auth_schema import CurrentUser
from app.schemas.festival_apply_schema import (
    AnalyzeFormsRequest,
    AnalyzeFormsResponse,
    ApplyBatchRequest,
    ApplyBatchResponse,
    SubmitFormsRequest,
    SubmitFormsResponse,
)
from app.services.festival_apply_service import (
    analyze_batch_exists,
    analyze_festival_forms,
    batch_exists,
    get_event_queue,
    submit_batch,
    submit_forms,
)

router = APIRouter(prefix="/api/festivals", tags=["Festival Apply"])


# ── POST /api/festivals/apply ─────────────────────────────────────────────────

@router.post("/apply", response_model=ApplyBatchResponse)
async def apply_to_festivals(
    payload: ApplyBatchRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Enqueue a batch of festival applications and return immediately.

    The background worker logs in to each festival URL using CaptchaSolver
    (with up to 2 automatic retries on CAPTCHA failures) and emits real-time
    status events consumable via /apply/stream/{batch_id}.

    Credentials in the request body are only held in the worker thread's memory
    during processing and are never logged or persisted.
    """
    # Convert Pydantic items to plain dicts for the service layer.
    # Passwords are never logged — they live as plain dict values for the
    # duration of the worker thread, then set to None.
    festivals_raw = [
        {
            "festival_id": item.festival_id,
            "login_url": item.login_url,
            "username": item.username,
            "password": item.password,
        }
        for item in payload.festivals
    ]

    batch_id = submit_batch(
        festivals=festivals_raw,
        film_data=payload.film_data,
    )

    return ApplyBatchResponse(batch_id=batch_id, total=len(payload.festivals))


# ── GET /api/festivals/apply/stream/{batch_id} ────────────────────────────────

@router.get("/apply/stream/{batch_id}")
async def stream_batch_progress(
    batch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    SSE stream of real-time status updates for a submitted batch.

    Each event is a JSON object: {"festival_id", "status", "message"}.
    The stream closes automatically when the terminal event
    {"festival_id": "__done__"} is emitted by the worker.

    Keepalive SSE comments (": keepalive") are sent every ~300 ms while the
    queue is empty so that proxies and browsers do not close idle connections.
    """
    if not batch_exists(batch_id):
        raise HTTPException(
            status_code=404,
            detail=f"Batch '{batch_id}' no encontrado.",
        )

    q = get_event_queue(batch_id)
    if q is None:
        raise HTTPException(
            status_code=404,
            detail=f"Cola del batch '{batch_id}' no disponible.",
        )

    async def event_generator():
        while True:
            # Run a blocking queue.get (300 ms timeout) in a thread pool so
            # the async event loop is never blocked.
            def _poll() -> dict | None:
                try:
                    return q.get(block=True, timeout=0.3)
                except queue_module.Empty:
                    return None

            event = await asyncio.to_thread(_poll)

            if event is None:
                # Queue was empty — send a keepalive comment to hold the connection.
                yield ": keepalive\n\n"
                continue

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # The worker pushes "__done__" as the final event to signal completion.
            if event.get("festival_id") == "__done__":
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # prevents nginx/uvicorn from buffering SSE
        },
    )


# ── POST /api/festivals/analyze-forms ────────────────────────────────────────

@router.post("/analyze-forms", response_model=AnalyzeFormsResponse)
async def analyze_festival_forms_endpoint(
    payload: AnalyzeFormsRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    For each festival in festival_ids: log in using the supplied credentials,
    scan the authenticated page for an application-form link, navigate to it,
    and extract all form fields (name, id, type, placeholder, label, required).

    Once all festivals are scraped, calls Claude claude-sonnet-4-6 to generate a
    single unified form JSON grouped in 4 categories:
      pelicula / director / tecnico / archivos

    Each unified field includes a `source_fields` list that maps back to the
    per-festival original field names/ids.

    Returns the unified form plus the raw per-festival field lists, and an
    analyze_batch_id that can be passed to POST /submit-forms.

    This endpoint runs Selenium synchronously — expect a multi-second response
    time proportional to the number of festivals.
    """
    credentials_map = {
        festival_id: creds.model_dump()
        for festival_id, creds in payload.credentials_map.items()
    }

    result = await asyncio.to_thread(
        analyze_festival_forms,
        payload.festival_ids,
        credentials_map,
    )

    return AnalyzeFormsResponse(**result)


# ── POST /api/festivals/submit-forms ─────────────────────────────────────────

@router.post("/submit-forms", response_model=SubmitFormsResponse)
async def submit_festival_forms_endpoint(
    payload: SubmitFormsRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Re-authenticates to each festival stored in the given analyze_batch_id,
    navigates to its form URL, and fills every field by mapping the unified
    form_data keys to festival-specific field names/ids (via source_fields).

    Processing runs in a background thread. Stream real-time progress from:
      GET /api/festivals/apply/stream/{submit_batch_id}

    form_data must be a flat dict keyed by the unified field keys returned
    by POST /analyze-forms  (e.g. {"titulo": "Mi Película", "director_nombre": "..."}).
    """
    if not analyze_batch_exists(payload.batch_id):
        raise HTTPException(
            status_code=404,
            detail=f"Análisis '{payload.batch_id}' no encontrado.",
        )

    try:
        submit_batch_id, total = submit_forms(payload.batch_id, payload.form_data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return SubmitFormsResponse(submit_batch_id=submit_batch_id, total=total)
