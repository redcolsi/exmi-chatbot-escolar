"""
app/routes/public.py — Endpoints PÚBLICOS de solo lectura (sin JWT).

Sirven los datos institucionales que muestran las pestañas del chatbot
(Horarios, Docentes, Convivencia, Contactos) y la apariencia del bot.
Así cualquier visitante ve SIEMPRE los datos reales de exmi.db, haya o no
un admin con sesión iniciada.

Solo lectura: nada aquí escribe en la base de datos. Las respuestas incluyen
únicamente los campos que necesita la interfaz pública.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import app.crud as crud
from app.database.database import get_db

router = APIRouter(prefix="/public", tags=["Público (solo lectura)"])

# Claves de bot_config que se exponen públicamente (lista blanca).
PUBLIC_CONFIG_KEYS = (
    "bot_name",
    "welcome_msg",
    "accent_color",
    "bg_color",
    "surface_color",
    "bot_avatar",
)

DEFAULT_SECTIONS: Dict[str, bool] = {
    "horarios": True,
    "docentes": True,
    "convivencia": True,
    "contactos": True,
}


def _pick(obj: Any, fields: List[str]) -> Dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


def parse_sections(raw: Optional[str]) -> Dict[str, bool]:
    """Convierte el JSON guardado en bot_config['sections'] (con valores por defecto)."""
    sections = dict(DEFAULT_SECTIONS)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for key in DEFAULT_SECTIONS:
                    if key in data:
                        sections[key] = bool(data[key])
        except (ValueError, TypeError):
            pass
    return sections


@router.get("/horarios", summary="Horarios de clases (opcionalmente por grado)")
def public_horarios(grado: Optional[str] = None, db: Session = Depends(get_db)):
    rows = crud.get_all_horarios(db, grado=grado)
    return [_pick(h, ["id", "grado", "hora", "materia", "docente", "dia"]) for h in rows]


@router.get("/docentes", summary="Cuerpo docente")
def public_docentes(db: Session = Depends(get_db)):
    rows = crud.get_all_docentes(db)
    return [_pick(d, ["id", "nombre", "area", "titulo", "grados", "atencion"]) for d in rows]


@router.get("/contactos", summary="Directorio de contactos")
def public_contactos(db: Session = Depends(get_db)):
    rows = crud.get_all_contactos(db)
    return [_pick(c, ["id", "cargo", "nombre", "contacto", "horario"]) for c in rows]


@router.get("/kb", summary="Base de conocimiento (opcionalmente por categoría)")
def public_kb(categoria: Optional[str] = None, db: Session = Depends(get_db)):
    rows = crud.get_all_kb(db, categoria=categoria)
    return [_pick(k, ["id", "categoria", "pregunta", "respuesta"]) for k in rows]


@router.get("/config", summary="Apariencia pública del bot (nombre, colores, avatar, secciones)")
def public_config(db: Session = Depends(get_db)):
    cfg = crud.get_bot_config_dict(db)
    out: Dict[str, Any] = {k: cfg[k] for k in PUBLIC_CONFIG_KEYS if k in cfg}
    out["sections"] = parse_sections(cfg.get("sections"))
    return out
