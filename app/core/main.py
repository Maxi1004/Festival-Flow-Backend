import asyncio
import os
import sys
import time

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.firebase import db
from app.routes.admin_festivals import router as admin_festivals_router
from app.routes.applications import router as applications_router
from app.routes.auth import router as auth_router
from app.routes.crew import router as crew_router
from app.routes.dashboard import router as dashboard_router
from app.routes.opportunities import router as opportunities_router
from app.routes.producer import router as producer_router
from app.routes.producer_festivals import router as producer_festivals_router
from app.routes.projects import router as projects_router
from app.routes.recruitments import router as recruitments_router
from app.routes.talent import router as talent_router
from app.routes.translation import router as translation_router
from app.routes.festival_scraper import router as festival_scraper_router
from app.routes.scraper import router as scraper_router
from app.routes.festival_apply import router as festival_apply_router
from app.routes.filmfreeway_camoufox import router as filmfreeway_camoufox_router

app = FastAPI(title="Festival Flow API")
app.include_router(festival_scraper_router)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    FRONTEND_URL,
    "https://festival-flow-frontend.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    if request.url.path in {
        "/auth/me",
        "/me",
        "/applications/me/feed",
        "/applications/me/summary",
        "/crew/me/feed",
        "/crew/me/summary",
        "/recruitments/me/feed",
        "/recruitments/me/summary",
        "/talent/profile/me",
        "/producer/profile/me",
    }:
        print(
            f"[PERF] HTTP {request.method} {request.url.path} total: "
            f"{(time.perf_counter() - start) * 1000:.2f} ms"
        )
    return response


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Festival Flow API is running"}


@app.get("/test-db")
async def test_db():
    doc_ref = db.collection("test").document("conexion")
    doc_ref.set({"mensaje": "Firebase conectado correctamente"})
    return {"message": "ok"}


app.include_router(auth_router, prefix="/auth")
app.include_router(admin_festivals_router)
app.include_router(talent_router, prefix="/talent")
app.include_router(producer_router, prefix="/producer")
app.include_router(producer_festivals_router)
app.include_router(projects_router)
app.include_router(opportunities_router)
app.include_router(applications_router)
app.include_router(recruitments_router)
app.include_router(crew_router)
app.include_router(dashboard_router)
app.include_router(translation_router)
app.include_router(scraper_router)
app.include_router(festival_apply_router)
app.include_router(filmfreeway_camoufox_router)

#7
