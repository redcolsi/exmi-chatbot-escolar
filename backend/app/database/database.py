"""
Configuración de la base de datos SQLAlchemy.

Orden de prioridad para DATABASE_URL:
  1. `DATABASE_URL` explícita (local .env o env Vercel).
     - Supabase (pooler recomendado en Vercel serverless, puerto 6543):
       postgresql://postgres.[REF]:[PASSWORD]@aws-0-[region].pooler.supabase.com:6543/postgres?pgbouncer=true
     - Supabase directa (puerto 5432):
       postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres
  2. En Vercel sin DATABASE_URL: sqlite:////tmp/exmi.db (solo /tmp es escribible).
  3. Local sin DATABASE_URL: sqlite:///./exmi.db (desarrollo offline).

Supabase = PostgreSQL estándar: los modelos actuales (Integer/Text/DateTime)
son compatibles sin cambios. El seed es idempotente.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker   # ← declarative_base movido a orm en SQLAlchemy 2.x
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

load_dotenv()


def _resolve_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        # Supabase publica a veces postgres:// — SQLAlchemy prefiere postgresql://
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url
    # Vercel: solo /tmp es escribible
    if os.getenv("VERCEL") == "1" or os.getenv("VERCEL_ENV"):
        return "sqlite:////tmp/exmi.db"
    return "sqlite:///./exmi.db"


DATABASE_URL: str = _resolve_database_url()
IS_POSTGRES: bool = DATABASE_URL.startswith("postgresql")

if IS_POSTGRES:
    # Serverless (Vercel): NullPool evita conexiones colgadas entre invocaciones.
    # Supabase exige SSL; la pooler de Supabase usa sslmode=require.
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"sslmode": "require", "connect_timeout": 10},
    )
else:
    # SQLite necesita check_same_thread=False para FastAPI (async requests)
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependencia de FastAPI: sesión de BD por request, cierre garantizado."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
