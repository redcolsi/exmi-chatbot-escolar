"""
api/index.py — Entrypoint FastAPI para Vercel (producción, con internet).

Vercel busca una variable `app` (FastAPI) en api/index.py.
Este archivo solo ajusta sys.path e importa la app real de backend.

Env en Vercel (dashboard o MCP create_project_env):
  GEMINI_API_KEY=<clave AI Studio>
  GEMINI_MODEL=gemini-3.5-flash-lite
  GEMINI_FALLBACK_MODEL=gemini-3.1-flash-lite
  SECRET_KEY=<clave larga aleatoria>
  VERCEL=1  (Vercel la pone sola; activa /tmp para SQLite y uploads)
  SUPABASE_URL / SUPABASE_ANON_KEY (opcional)
"""
import os
import sys
from pathlib import Path

# Raíz del proyecto Vercel (carpeta exmi/ que contiene backend/ y frontend/)
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

for p in (str(ROOT), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Asegura que los imports "from app..." resuelvan a backend/app
os.chdir(str(BACKEND))

from app.main import app  # noqa: E402,F401 — Vercel importa `app` desde aquí
