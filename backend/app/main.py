"""
app/main.py — Punto de entrada de la aplicación FastAPI (v2.1.0 local+vercel).

Al arrancar:
  1. Crea las tablas en BD si no existen (SQLite local o Supabase Postgres en Vercel).
  2. Crea los directorios de uploads (en Vercel usa /tmp/uploads).
  3. En Vercel/first-run: si la BD está vacía, ejecuta el seed automáticamente.
  4. Registra todos los routers (auth, chatbot, public, admin).
  5. Aplica middleware CORS.
  6. Expone archivos estáticos (uploads) y sirve el frontend en /.

Funciona SIN internet (RAG local) y CON internet (IA+RAG Gemini 3.5/3.1 lite).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.responses import FileResponse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database.database import engine, SessionLocal, DATABASE_URL
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

# ── ¿Estamos en Vercel? ───────────────────────────────────────
IS_VERCEL: bool = os.getenv("VERCEL") == "1" or bool(os.getenv("VERCEL_ENV"))

# ── Crear tablas en BD ────────────────────────────────────────
# `create_all` solo crea tablas ausentes: no añade columnas nuevas a tablas que ya
# existen. Por eso, tras crearlas, se aplica una migración ligera para que una BD
# previa siga funcionando al añadir campos nuevos (p. ej. imagenes.pregunta_disparadora).
Base.metadata.create_all(bind=engine)


def _apply_light_migrations() -> None:
    """Añade columnas faltantes sin perder datos (idempotente y tolerable a fallos)."""
    additions = [
        ("imagenes", "pregunta_disparadora", "VARCHAR(500)"),
    ]
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, column, coltype in additions:
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if column in cols:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            logger.info("Migración aplicada: %s.%s", table, column)
        except Exception as exc:
            logger.warning("No se pudo añadir %s.%s: %s", table, column, exc)


_apply_light_migrations()
logger.info("Tablas de BD verificadas/creadas. DATABASE_URL=%s", DATABASE_URL)

# ── Crear directorios de uploads ──────────────────────────────
# En Vercel solo /tmp es escribible.
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "/tmp/uploads" if IS_VERCEL else "uploads")
for subdir in ("imagenes", "documentos"):
    try:
        os.makedirs(os.path.join(UPLOAD_DIR, subdir), exist_ok=True)
    except Exception as exc:
        logger.warning("No se pudo crear uploads/%s: %s", subdir, exc)


def _ensure_seed() -> None:
    """Si la BD está vacía (caso Vercel serverless /tmp), carga datos iniciales.

    Es idempotente: seed_data.run_seed() no duplica registros.
    Se ejecuta una sola vez por arranque en frío.
    """
    try:
        from app.models.models import User

        db = SessionLocal()
        try:
            needs_seed = db.query(User).count() == 0
        finally:
            db.close()
        if needs_seed:
            logger.info("BD vacía: ejecutando seed inicial...")
            import sys
            import importlib.util

            backend_root = Path(__file__).resolve().parents[1]
            if str(backend_root) not in sys.path:
                sys.path.insert(0, str(backend_root))
            seed_path = backend_root / "seed_data.py"
            if seed_path.exists():
                spec = importlib.util.spec_from_file_location("seed_data_auto", seed_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.run_seed()
                logger.info("Seed inicial completado.")
            else:
                logger.warning("No se encontró seed_data.py en %s", seed_path)
    except Exception as exc:
        logger.error("Error en auto-seed (el RAG seguirá con lo que haya): %s: %s",
                     type(exc).__name__, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_seed()
    yield


# ── Aplicación FastAPI ────────────────────────────────────────
app = FastAPI(
    title="Exmi API — Colegio Albert Einstein",
    description=(
        "Backend del chatbot escolar Exmi.\n\n"
        "Autenticación: Bearer JWT. "
        "Endpoints públicos: /chat/, /public/*, /auth/login, /health.\n"
        "Endpoints de admin: requieren rol 'admin'."
    ),
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Archivos estáticos (imágenes subidas) ─────────────────────
try:
    app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
except Exception as exc:
    logger.warning("No se pudo montar /uploads: %s", exc)

# ── Registrar routers ─────────────────────────────────────────
app.include_router(auth_router)
app.include_router(chatbot_router)
app.include_router(public_router)   # lectura pública: horarios, docentes, contactos, kb, config
app.include_router(admin_router)    # requiere rol admin


# ── Endpoints de utilidad ─────────────────────────────────────


def _find_frontend() -> Path | None:
    """Busca el HTML del frontend en todas las ubicaciones conocidas.

    Local:  exmi/frontend/exmi_sistema_completo.html
    Vercel: el bundle incluye frontend/ junto al backend según vercel.json.
    Compat: también acepta el nombre antiguo con (2).
    """
    here = Path(__file__).resolve()
    names = ["exmi_sistema_completo.html", "exmi_sistema_completo(2).html"]
    candidates: list[Path] = []
    for n in names:
        candidates += [
            here.parents[2] / "frontend" / n,
            here.parents[1] / "frontend" / n,
            Path.cwd() / "frontend" / n,
            Path.cwd() / "backend" / ".." / "frontend" / n,
            Path("/var/task/frontend") / n,
            Path("/var/task/exmi/frontend") / n,
        ]
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            continue
    return None


FRONTEND_FILE: Path | None = _find_frontend()


@app.get("/connection-test", tags=["Info"])
def connection_test():
    """Endpoint usado por el frontend para verificar conectividad real."""
    return {"status": "connected", "backend": "Exmi API",
            "frontend": bool(FRONTEND_FILE and FRONTEND_FILE.exists())}


@app.get("/", tags=["Info"])
def root():
    if FRONTEND_FILE is not None and FRONTEND_FILE.exists():
        return FileResponse(FRONTEND_FILE, media_type="text/html")
    return {
        "app": "Exmi API",
        "version": "2.1.0",
        "colegio": "Albert Einstein — Cúcuta",
        "docs": "/docs",
    }


@app.get("/health", tags=["Info"])
def health():
    """Verificación rápida de que el servidor está activo."""
    return {"status": "ok"}


@app.get("/health/ai", tags=["Info"])
def health_ai():
    """Dice si la IA está configurada y en qué modo trabaja (online/offline)."""
    try:
        from app.ai.gemini_service import GeminiService

        return {"status": "ok", **GeminiService().status()}
    except Exception as exc:
        return {"status": "ok", "configurado": False,
                "modo": "offline (RAG local)", "error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/status", tags=["Info"])
def api_status():
    """Alias simple para que el frontend muestre 'Conectado / Sin internet'."""
    ai = health_ai()
    online_ia = bool(ai.get("configurado"))
    return {
        "backend": "ok",
        "ia": "online" if online_ia else "offline",
        "modelo_primario": ai.get("modelo_primario", "gemini-3.5-flash-lite"),
        "modelo_respaldo": ai.get("modelo_respaldo", "gemini-3.1-flash-lite"),
        "mensaje": (
            "Conectado: respuestas con IA + RAG."
            if online_ia else
            "Sin IA (offline o sin clave): respuestas con RAG local. Todo sigue funcionando."
        ),
    }
