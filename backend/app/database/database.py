"""
Configuración de la base de datos SQLAlchemy.

Orden de prioridad para DATABASE_URL:
  1. `DATABASE_URL` explícita (local .env o env Vercel).
     - Supabase, Session pooler (puerto 6543, recomendado en serverless):

         postgresql://postgres.[REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require

       IMPORTANTE: el parámetro `?pgbouncer=true` que aparece en algunos ejemplos
       de Supabase NO es una opción válida de psycopg2. Provoca un
       `invalid connection option "pgbouncer"` al importar este módulo y tumba
       toda la aplicación (500 en todos los endpoints). Usar `?sslmode=require`.
     - Supabase directa (puerto 5432):

         postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres?sslmode=require
  2. En Vercel sin DATABASE_URL: sqlite:////tmp/exmi.db (solo /tmp es escribible).
     OJO: esa base es efímera; se pierde en cada arranque en frío. Para producción
     hace falta una DATABASE_URL real (por ejemplo, Supabase).
  3. Local sin DATABASE_URL: sqlite:///./exmi.db (desarrollo offline).

Supabase = PostgreSQL estándar: los modelos actuales (Integer/Text/DateTime)
son compatibles sin cambios. El seed es idempotente.
"""
import logging
import os
import re

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker   # ← declarative_base movido a orm en SQLAlchemy 2.x
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

load_dotenv()


def _IS_VERCEL_ENV() -> bool:
    return os.getenv("VERCEL") == "1" or bool(os.getenv("VERCEL_ENV"))


def _resolve_database_url() -> str:
    """
    Obtiene la URL de la base de datos.

    En Vercel se prueba primero `DATABASE_URL_POSTGRES` (Session pooler), porque
    el host directo `db.*` a veces no resuelve por DNS (solo devuelve AAAA).

    Orden:
      - Vercel   → `DATABASE_URL_POSTGRES`, luego `DATABASE_URL`, luego SQLite en /tmp
      - Local    → `DATABASE_URL` (tu .env), luego `DATABASE_URL_POSTGRES`, luego SQLite

    Así el .env de desarrollo sigue mandando, y en producción se prefiera el pooler.
    """
    if _IS_VERCEL_ENV():
        nombres = ("DATABASE_URL_POSTGRES", "DATABASE_URL")
    else:
        nombres = ("DATABASE_URL", "DATABASE_URL_POSTGRES")

    for nombre in nombres:
        url = os.getenv(nombre, "").strip()
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

# SQLAlchemy 2.1 usa el driver `psycopg` (v3) por defecto para postgresql://.
# Aquí el driver instalado es psycopg2 (v2), así que se fija el dialecto de forma
# explícita con el prefijo +psycopg2. Sin esto, Vercel responde
# ModuleNotFoundError: No module named 'psycopg' y la app no arranca.
if IS_POSTGRES and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len("postgresql://"):]


def _sanitize_dsn(url: str) -> str:
    """
    Limpia el DSN de Postgres y devuelve los errores de formato como texto.

    Casos que corrige:
      - `?pgbouncer=true` / `pgmode=...`: no son opciones válidas de psycopg2.
      - Credenciales sin codificar: una contraseña con `#`, `@`, `:` o `/` rompe
        el parseo del DSN. Se percent-encodifican los componentes de user y pass.
      - Falta `sslmode`, que Supabase exige.

    Limitación conocida: una contraseña que contenga `@` es ambigua, porque `@`
    es también el separador entre credenciales y host. Ejemplo:
        ...:a@b@aws-0-...pooler.supabase.com:6543/...
    se interpreta como contraseña "a" y host "b@aws-0-...". Si tu contraseña
    lleva `@`, codifícala como %40 al definir DATABASE_URL.
    """
    try:
        from urllib.parse import quote, unquote

        # `urlsplit` parte el netloc en el ÚLTIMO "@", pero en un connection
        # string la contraseña puede contener "@" (p. ej. "Cla@ve"). Por eso se
        # separa a mano en el PRIMER "@": todo lo anterior son credenciales.
        esquema, resto = url.split("://", 1)
        credenciales_crudas, _, destino = resto.partition("@")

        usuario, _, clave = credenciales_crudas.partition(":")
        # Se decodifica primero: si ya viene codificada, no hay que doble-codificar.
        usuario = quote(unquote(usuario), safe="")
        clave = quote(unquote(clave), safe="")

        credenciales = f"{usuario}:{clave}" if credenciales_crudas.count(":") else usuario
        limpio = f"{esquema}://{credenciales}@{destino}"
        limpio = re.sub(r"[?&]pgbouncer=true", "", limpio)
        limpio = re.sub(r"[?&]pgmode=\w+", "", limpio)
        if "sslmode=" not in limpio:
            limpio += ("&" if "?" in limpio else "?") + "sslmode=require"
        return limpio
    except Exception as exc:  # noqa: BLE001
        return f"postgresql+psycopg2://ERROR_DSN:{type(exc).__name__}@localhost/dummy"


logger = logging.getLogger(__name__)

#: Detalle del error de Postgres, si hubo. Lo consulta /health para diagnosticar
#: sin depender de los logs de Vercel (que salen vacíos cuando la función muere
#: durante la importación del módulo).
DB_ERROR: str | None = None


def _build_engine():
    """Crea el engine de Postgres; si falla, registra el motivo y devuelve None."""
    try:
        return create_engine(
            _sanitize_dsn(DATABASE_URL),
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"sslmode": "require", "connect_timeout": 10},
        )
    except Exception as exc:  # noqa: BLE001
        global DB_ERROR
        DB_ERROR = f"{type(exc).__name__}: {exc}"[:300]
        logger.critical("No se pudo crear el engine de Postgres: %s", DB_ERROR)
        return None


if IS_POSTGRES:
    # Serverless (Vercel): NullPool evita conexiones colgadas entre invocaciones.
    engine = _build_engine()
    if engine is None:
        # La disponibilidad del sitio importa más que la persistencia: si Postgres
        # no es alcanzable, se sigue sirviendo con SQLite en /tmp (efímero, pero
        # funcional) en lugar de devolver 500 en todos los endpoints.
        logger.error("Postgres no disponible; se usa SQLite temporal como respaldo.")
        IS_POSTGRES = False
        engine = create_engine(
            "sqlite:////tmp/exmi.db" if _IS_VERCEL_ENV() else "sqlite:///./exmi.db",
            connect_args={"check_same_thread": False},
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
