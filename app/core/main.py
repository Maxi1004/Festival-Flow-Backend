from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.firebase import db
from app.routes.auth import router as auth_router

app = FastAPI(title="Festival Flow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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