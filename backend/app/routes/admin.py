"""
app/routes/admin.py — Panel de administración (solo rol 'admin').

Todas las rutas exigen JWT de administrador (dependencia a nivel de router) y
delegan el acceso a datos en app/crud.py.

Cubre:
  · CRUD de KB, docentes, horarios y contactos
  · Configuración del bot (nombre, bienvenida, colores, secciones, avatar)
  · Imágenes subidas
  · Documentos del RAG (listar, editar, activar/desactivar, borrar, ver
    fragmentos e importar JSON)
  · Historial de chat (paginado con búsqueda/filtros, estadísticas,
    exportación CSV/JSON, borrado)
"""
import csv
import io
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile,
)
from sqlalchemy.orm import Session

import app.crud as crud
from app.auth.security import require_admin
from app.converters.json_to_db import import_json_to_db
from app.database.database import get_db
from app.models.document import DocumentCategory
from app.models.models import User
from app.routes.public import DEFAULT_SECTIONS
from app.schemas.document import DocumentUpdate
from app.schemas.schemas import (
    ConfigItem,
    ContactoCreate, ContactoUpdate,
    DocenteCreate, DocenteUpdate,
    HorarioCreate, HorarioUpdate,
    KBCreate, KBUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Administración"],
    dependencies=[Depends(require_admin)],
)

IS_VERCEL: bool = os.getenv("VERCEL") == "1" or bool(os.getenv("VERCEL_ENV"))

# En Vercel el sistema de archivos es de solo lectura salvo /tmp: guardar en una
# ruta del repositorio lanzaba "Read-only file system" y rompía la subida de
# imágenes y la importación de documentos (HTTP 500).
_subido = os.getenv("UPLOAD_DIR", "")
UPLOAD_DIR: str = (
    _subido if not IS_VERCEL or _subido.startswith("/tmp") else "/tmp/uploads"
)
DOCUMENTS_DIR: Path = (
    Path("/tmp/documents") if IS_VERCEL else Path(__file__).resolve().parents[1] / "documents"
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 10 * 1024 * 1024
IMAGE_CATEGORIES = {"horarios", "fotografias", "circulares", "comunicados", "promociones"}
AVATAR_CATEGORY = "avatar"


# ══════════════════════════════════════════════════════
#  Utilidades
# ══════════════════════════════════════════════════════

def _dump(x: Any) -> Dict[str, Any]:
    return {c.name: getattr(x, c.name) for c in x.__table__.columns}


def _dump_chunk(c: Any) -> Dict[str, Any]:
    data = _dump(c)
    data["preview"] = c.preview()
    return data


def _or_404(obj: Any, msg: str) -> Any:
    if obj is None:
        raise HTTPException(404, msg)
    return obj


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Lee el archivo subido en bloques y corta si supera el máximo."""
    buf = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(413, f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.")
    return bytes(buf)


def _is_valid_image(ext: str, head: bytes) -> bool:
    """Comprueba la firma real del archivo (no solo la extensión)."""
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def _store_image(data: bytes, filename: Optional[str]) -> Dict[str, Any]:
    """Valida y guarda una imagen en uploads/imagenes. SVG no se admite (riesgo XSS)."""
    original = Path(filename or "imagen").name[:255]
    ext = Path(original).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        raise HTTPException(400, "Formato no permitido. Usa PNG, JPG, GIF o WEBP.")
    if not _is_valid_image(ext, data[:16]):
        raise HTTPException(400, "El contenido del archivo no corresponde a una imagen válida.")
    nombre = f"{uuid.uuid4().hex}{ext}"
    folder = Path(UPLOAD_DIR) / "imagenes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / nombre).write_bytes(data)
    return {
        "nombre": nombre,
        "nombre_original": original,
        "ruta": f"/uploads/imagenes/{nombre}",
        "tamano": len(data),
    }


def _remove_image_file(nombre: Optional[str]) -> None:
    if not nombre or Path(nombre).name != nombre:
        return
    (Path(UPLOAD_DIR) / "imagenes" / nombre).unlink(missing_ok=True)


# ══════════════════════════════════════════════════════
#  Datos generales (carga inicial del panel)
# ══════════════════════════════════════════════════════

@router.get("/data")
def get_admin_data(db: Session = Depends(get_db)):
    return {
        "kb": [_dump(x) for x in crud.get_all_kb(db)],
        "docentes": [_dump(x) for x in crud.get_all_docentes(db)],
        "horarios": [_dump(x) for x in crud.get_all_horarios(db)],
        "contactos": [_dump(x) for x in crud.get_all_contactos(db)],
        "config": crud.get_bot_config_dict(db),
        "documents": [_dump(x) for x in crud.get_all_documents(db)],
        "imagenes": [
            _dump(x) for x in crud.get_all_imagenes(db) if x.categoria != AVATAR_CATEGORY
        ],
    }


# ══════════════════════════════════════════════════════
#  Knowledge base
# ══════════════════════════════════════════════════════

@router.post("/kb")
def create_kb(data: KBCreate, db: Session = Depends(get_db)):
    return _dump(crud.create_kb_item(db, data))


@router.put("/kb/{item_id}")
def update_kb(item_id: int, data: KBUpdate, db: Session = Depends(get_db)):
    return _dump(_or_404(crud.update_kb_item(db, item_id, data), "Entrada no encontrada"))


@router.delete("/kb/{item_id}")
def delete_kb(item_id: int, db: Session = Depends(get_db)):
    _or_404(crud.delete_kb_item(db, item_id) or None, "Entrada no encontrada")
    return {"ok": True}


# ══════════════════════════════════════════════════════
#  Docentes
# ══════════════════════════════════════════════════════

@router.post("/docentes")
def create_docente(data: DocenteCreate, db: Session = Depends(get_db)):
    return _dump(crud.create_docente(db, data))


@router.put("/docentes/{item_id}")
def update_docente(item_id: int, data: DocenteUpdate, db: Session = Depends(get_db)):
    return _dump(_or_404(crud.update_docente(db, item_id, data), "Docente no encontrado"))


@router.delete("/docentes/{item_id}")
def delete_docente(item_id: int, db: Session = Depends(get_db)):
    _or_404(crud.delete_docente(db, item_id) or None, "Docente no encontrado")
    return {"ok": True}


# ══════════════════════════════════════════════════════
#  Horarios
# ══════════════════════════════════════════════════════

@router.post("/horarios")
def create_horario(data: HorarioCreate, db: Session = Depends(get_db)):
    return _dump(crud.create_horario(db, data))


@router.put("/horarios/{item_id}")
def update_horario(item_id: int, data: HorarioUpdate, db: Session = Depends(get_db)):
    return _dump(_or_404(crud.update_horario(db, item_id, data), "Horario no encontrado"))


@router.delete("/horarios/{item_id}")
def delete_horario(item_id: int, db: Session = Depends(get_db)):
    _or_404(crud.delete_horario(db, item_id) or None, "Horario no encontrado")
    return {"ok": True}


# ══════════════════════════════════════════════════════
#  Contactos
# ══════════════════════════════════════════════════════

@router.post("/contactos")
def create_contacto(data: ContactoCreate, db: Session = Depends(get_db)):
    return _dump(crud.create_contacto(db, data))


@router.put("/contactos/{item_id}")
def update_contacto(item_id: int, data: ContactoUpdate, db: Session = Depends(get_db)):
    return _dump(_or_404(crud.update_contacto(db, item_id, data), "Contacto no encontrado"))


@router.delete("/contactos/{item_id}")
def delete_contacto(item_id: int, db: Session = Depends(get_db)):
    _or_404(crud.delete_contacto(db, item_id) or None, "Contacto no encontrado")
    return {"ok": True}


# ══════════════════════════════════════════════════════
#  Configuración del bot (bot_config) — lectura y ESCRITURA
# ══════════════════════════════════════════════════════

_COLOR_KEYS = {"accent_color", "bg_color", "surface_color"}
_EDITABLE_CONFIG_KEYS = {"bot_name", "welcome_msg", "ai_mode", "sections"} | _COLOR_KEYS


def _validate_config_item(item: ConfigItem) -> ConfigItem:
    key, value = item.clave, item.valor
    if key not in _EDITABLE_CONFIG_KEYS:
        raise HTTPException(400, f"Clave de configuración no permitida: {key}")
    if key in _COLOR_KEYS and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise HTTPException(400, f"Color inválido para {key} (usa formato #RRGGBB).")
    if key == "bot_name":
        value = value.strip()
        if not 1 <= len(value) <= 60:
            raise HTTPException(400, "El nombre del bot debe tener entre 1 y 60 caracteres.")
    if key == "welcome_msg" and len(value) > 1000:
        raise HTTPException(400, "El mensaje de bienvenida no puede superar 1000 caracteres.")
    if key == "ai_mode" and value not in ("ia", "reglas"):
        raise HTTPException(400, "Modo de IA inválido (usa 'ia' o 'reglas').")
    if key == "sections":
        try:
            parsed = json.loads(value)
        except ValueError:
            raise HTTPException(400, "El valor de 'sections' no es JSON válido.")
        if (
            not isinstance(parsed, dict)
            or not set(parsed) <= set(DEFAULT_SECTIONS)
            or not all(isinstance(v, bool) for v in parsed.values())
        ):
            raise HTTPException(400, "Formato de 'sections' inválido.")
        value = json.dumps(parsed)
    return ConfigItem(clave=key, valor=value)


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    return crud.get_bot_config_dict(db)


@router.put("/config")
def update_config(items: List[ConfigItem], db: Session = Depends(get_db)):
    validated = [_validate_config_item(i) for i in items]  # valida todo antes de escribir
    crud.set_many_config(db, validated)
    return crud.get_bot_config_dict(db)


@router.post("/config/avatar")
async def upload_avatar(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Sube el avatar del bot, reemplaza el anterior y guarda su URL en bot_config."""
    data = await _read_limited(file, MAX_IMAGE_BYTES)
    saved = _store_image(data, file.filename)
    for old in crud.get_all_imagenes(db, categoria=AVATAR_CATEGORY):
        _remove_image_file(old.nombre)
        crud.delete_imagen(db, old.id)
    crud.create_imagen(
        db,
        nombre=saved["nombre"],
        nombre_original=saved["nombre_original"],
        ruta=saved["ruta"],
        tamano=saved["tamano"],
        descripcion="Avatar del asistente",
        categoria=AVATAR_CATEGORY,
    )
    crud.set_config_value(db, "bot_avatar", saved["ruta"])
    return {"bot_avatar": saved["ruta"]}


@router.delete("/config/avatar")
def reset_avatar(db: Session = Depends(get_db)):
    for old in crud.get_all_imagenes(db, categoria=AVATAR_CATEGORY):
        _remove_image_file(old.nombre)
        crud.delete_imagen(db, old.id)
    crud.delete_config_value(db, "bot_avatar")
    return {"ok": True}


# ══════════════════════════════════════════════════════
#  Imágenes
# ══════════════════════════════════════════════════════

@router.get("/imagenes")
def list_imagenes(categoria: Optional[str] = None, db: Session = Depends(get_db)):
    rows = crud.get_all_imagenes(db, categoria=categoria)
    return [_dump(x) for x in rows if categoria or x.categoria != AVATAR_CATEGORY]


@router.post("/imagenes")
async def upload_imagen(
    file: UploadFile = File(...),
    categoria: str = Form("comunicados"),
    descripcion: Optional[str] = Form(None),
    pregunta_disparadora: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if categoria not in IMAGE_CATEGORIES:
        raise HTTPException(400, f"Categoría inválida. Opciones: {', '.join(sorted(IMAGE_CATEGORIES))}.")
    data = await _read_limited(file, MAX_IMAGE_BYTES)
    saved = _store_image(data, file.filename)
    img = crud.create_imagen(
        db,
        nombre=saved["nombre"],
        nombre_original=saved["nombre_original"],
        ruta=saved["ruta"],
        tamano=saved["tamano"],
        descripcion=(descripcion or "").strip()[:500] or None,
        categoria=categoria,
        pregunta_disparadora=(pregunta_disparadora or "").strip()[:500] or None,
    )
    return _dump(img)


@router.delete("/imagenes/{img_id}")
def delete_imagen(img_id: int, db: Session = Depends(get_db)):
    img = _or_404(crud.get_imagen(db, img_id), "Imagen no encontrada")
    nombre = img.nombre
    crud.delete_imagen(db, img_id)
    _remove_image_file(nombre)
    return {"ok": True}


# ══════════════════════════════════════════════════════
#  Documentos del RAG (documents / document_chunks)
# ══════════════════════════════════════════════════════

@router.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    return [_dump(d) for d in crud.get_all_documents(db)]


@router.post("/documents/import-json", status_code=201)
async def import_document_json(
    file: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form("general"),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Importa un JSON (el mismo formato que json_to_db.py) como documento del RAG.
    Si ya existe un documento con ese nombre, se reemplaza junto con sus fragmentos.
    """
    name = name.strip()
    if not name:
        raise HTTPException(400, "El nombre del documento es obligatorio.")
    try:
        cat = DocumentCategory(category)
    except ValueError:
        raise HTTPException(400, f"Categoría inválida: {category}")
    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(400, "Sube un archivo .json")

    data = await _read_limited(file, MAX_JSON_BYTES)
    try:
        json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "El archivo no es un JSON válido (UTF-8).")

    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCUMENTS_DIR / f"{uuid.uuid4().hex}.json"
    path.write_bytes(data)
    try:
        doc = import_json_to_db(
            db,
            json_path=path,
            name=name,
            description=(description or "").strip() or None,
            category=cat,
            uploaded_by=admin.email,
        )
    except ValueError as exc:
        db.rollback()
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc))
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        logger.exception("[admin] Falló la importación del documento '%s'", name)
        raise HTTPException(500, "No se pudo importar el documento.")
    return _dump(doc)


@router.put("/documents/{doc_id}")
def update_document(doc_id: int, data: DocumentUpdate, db: Session = Depends(get_db)):
    return _dump(_or_404(crud.update_document(db, doc_id, data), "Documento no encontrado"))


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    _or_404(crud.delete_document(db, doc_id) or None, "Documento no encontrado")
    return {"ok": True}


@router.get("/documents/{doc_id}/chunks")
def list_document_chunks(
    doc_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _or_404(crud.get_document(db, doc_id), "Documento no encontrado")
    items, total = crud.get_document_chunks(db, doc_id, page=page, per_page=per_page, search=search)
    return {
        "items": [_dump_chunk(c) for c in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "document_id": doc_id,
    }


# ══════════════════════════════════════════════════════
#  Historial de chat
#  (las rutas fijas /stats y /export van antes que /{entry_id})
# ══════════════════════════════════════════════════════

TzOffset = Annotated[
    int,
    Query(ge=-840, le=840, description="Minutos de diferencia con UTC (Date.getTimezoneOffset() de JS)"),
]


@router.get("/history")
def list_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    search: Optional[str] = None,
    fuente: Optional[str] = None,
    date: Optional[str] = Query(None, description="Día local YYYY-MM-DD"),
    tz_offset: TzOffset = 0,
    db: Session = Depends(get_db),
):
    items, total = crud.get_chat_history(
        db, page=page, per_page=per_page, search=search, fuente=fuente, date=date, tz_offset=tz_offset
    )
    return {
        "items": [_dump(x) for x in items],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/history/stats")
def history_stats(tz_offset: TzOffset = 0, db: Session = Depends(get_db)):
    return crud.get_chat_history_stats(db, tz_offset=tz_offset)


def _csv_safe(value: Any) -> Any:
    """Evita inyección de fórmulas al abrir el CSV en Excel/Sheets."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@router.get("/history/export")
def export_history(
    fmt: str = Query("csv", alias="format", pattern="^(csv|json)$"),
    search: Optional[str] = None,
    fuente: Optional[str] = None,
    date: Optional[str] = None,
    tz_offset: TzOffset = 0,
    db: Session = Depends(get_db),
):
    rows = crud.get_chat_history_all(db, search=search, fuente=fuente, date=date, tz_offset=tz_offset)

    if fmt == "json":
        payload = [
            {
                "id": r.id,
                "fecha_utc": r.created_at.isoformat() if r.created_at else None,
                "usuario": r.usuario,
                "consulta": r.pregunta,
                "respuesta": r.respuesta,
                "fuente": r.fuente,
                "tiempo_respuesta": r.tiempo_respuesta,
            }
            for r in rows
        ]
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="historial_exmi.json"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Fecha (UTC)", "Usuario", "Consulta", "Fuente", "Respuesta", "Tiempo (s)"])
    for r in rows:
        writer.writerow([
            r.created_at.isoformat(sep=" ", timespec="seconds") if r.created_at else "",
            _csv_safe(r.usuario), _csv_safe(r.pregunta), _csv_safe(r.fuente),
            _csv_safe(r.respuesta), r.tiempo_respuesta if r.tiempo_respuesta is not None else "",
        ])
    return Response(
        content="\ufeff" + buf.getvalue(),  # BOM: Excel abre bien los acentos
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="historial_exmi.csv"'},
    )


@router.delete("/history/{entry_id}")
def delete_history_entry(entry_id: int, db: Session = Depends(get_db)):
    _or_404(crud.delete_chat_history_entry(db, entry_id) or None, "Registro no encontrado")
    return {"ok": True}


@router.delete("/history")
def clear_history(db: Session = Depends(get_db)):
    return {"ok": True, "deleted": crud.clear_chat_history(db)}
