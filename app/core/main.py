import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.firebase import db
from app.routes.applications import router as applications_router
from app.routes.auth import router as auth_router
from app.routes.crew import router as crew_router
from app.routes.opportunities import router as opportunities_router
from app.routes.projects import router as projects_router
from app.routes.recruitments import router as recruitments_router
from app.routes.talent import router as talent_router

app = FastAPI(title="Festival Flow API")

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


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Festival Flow API is running"}


@app.get("/test-db")
async def test_db():
    doc_ref = db.collection("test").document("conexion")
    doc_ref.set({"mensaje": "Firebase conectado correctamente"})
    return {"message": "ok"}


app.include_router(auth_router, prefix="/auth")
app.include_router(talent_router, prefix="/talent")
app.include_router(projects_router)
app.include_router(opportunities_router)
app.include_router(applications_router)
app.include_router(recruitments_router)
app.include_router(crew_router)

#7
