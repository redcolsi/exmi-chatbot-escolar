"""
app/main.py — Punto de entrada de la aplicación FastAPI.

Al arrancar:
  1. Crea las tablas en SQLite si no existen.
  2. Crea los directorios de uploads.
  3. Registra todos los routers.
  4. Aplica middleware CORS.
  5. Expone archivos estáticos (uploads).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi.responses import FileResponse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database.database import engine
from app.models.models import Base
from app.models.document import Document, DocumentChunk  # noqa: F401 — registra tablas del RAG documental

# ── Rutas disponibles ─────────────────────────────────────────
from app.routes.auth import router as auth_router
from app.routes.chatbot import router as chatbot_router
from app.routes.admin import router as admin_router
from app.routes.public import router as public_router

# Configura logging básico
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Crear tablas en BD ────────────────────────────────────────
Base.metadata.create_all(bind=engine)
logger.info("Tablas de BD verificadas/creadas.")

# ── Crear directorios de uploads ──────────────────────────────
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
for subdir in ("imagenes", "documentos"):
    os.makedirs(os.path.join(UPLOAD_DIR, subdir), exist_ok=True)

# ── Aplicación FastAPI ────────────────────────────────────────
app = FastAPI(
    title="Exmi API — Colegio Albert Einstein",
    description=(
        "Backend del chatbot escolar Exmi.\n\n"
        "Autenticación: Bearer JWT. "
        "Endpoints públicos: /chat/, /public/*, /auth/login, /health.\n"
        "Endpoints de admin: requieren rol 'admin'."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────
# En producción reemplaza "*" con el dominio real del frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Archivos estáticos (imágenes subidas) ─────────────────────
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ── Registrar routers ─────────────────────────────────────────
app.include_router(auth_router)
app.include_router(chatbot_router)
app.include_router(public_router)   # lectura pública: horarios, docentes, contactos, kb, config
app.include_router(admin_router)    # requiere rol admin


# ── Endpoints de utilidad ─────────────────────────────────────


FRONTEND_FILE = Path(__file__).resolve().parents[2] / "frontend" / "exmi_sistema_completo.html"

@app.get("/connection-test", tags=["Info"])
def connection_test():
    """Endpoint usado por el frontend para verificar conectividad real."""
    return {"status": "connected", "backend": "Exmi API", "frontend": FRONTEND_FILE.exists()}

@app.get("/", tags=["Info"])
def root():
    if FRONTEND_FILE.exists():
        return FileResponse(FRONTEND_FILE, media_type="text/html")
    return {
        "app": "Exmi API",
        "version": "1.0.0",
        "colegio": "Albert Einstein — Cúcuta",
        "docs": "/docs",
    }


@app.get("/health", tags=["Info"])
def health():
    """Verificación rápida de que el servidor está activo."""
    return {"status": "ok"}
