"""
Configuración de la base de datos SQLAlchemy.
- SQLite en desarrollo (DATABASE_URL por defecto)
- Migrar a PostgreSQL solo cambiando DATABASE_URL en .env
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker   # ← declarative_base movido a orm en SQLAlchemy 2.x
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./exmi.db")

# SQLite necesita check_same_thread=False para FastAPI (async requests)
connect_args: dict = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependencia de FastAPI: sesión de BD por request, cierre garantizado."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
