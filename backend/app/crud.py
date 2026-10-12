"""
app/crud.py — Capa de acceso a datos (CRUD).

REGLA: ningún router accede directamente a los modelos SQLAlchemy.
       Toda operación de BD pasa por las funciones de este módulo.

Nomenclatura:  {accion}_{modelo}
  accion: get | get_all | create | update | delete | clear
  modelo: user | kb_item | docente | horario | contacto |
          document | document_chunk | imagen | chat_history | bot_config
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.models.models import (
    BotConfig,
    ChatHistory,
    Contacto,
    Docente,
    Horario,
    Imagen,
    KnowledgeBase,
    User,
)
from app.models.document import Document, DocumentChunk
from app.schemas.document import DocumentUpdate
from app.schemas.schemas import (
    ConfigItem,
    ContactoCreate, ContactoUpdate,
    DocenteCreate, DocenteUpdate,
    HorarioCreate, HorarioUpdate,
    KBCreate, KBUpdate,
    UserCreate, UserUpdate,
)
from app.auth.security import hash_password

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════
#  USER  (tabla: users)
# ══════════════════════════════════════════════════════

def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def get_all_users(db: Session) -> List[User]:
    return db.query(User).order_by(User.created_at).all()


def create_user(db: Session, data: UserCreate) -> User:
    user = User(
        email=data.email,
        username=data.username,
        hashed_password=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Usuario creado: %s (rol=%s)", user.email, user.role)
    return user


def update_user(db: Session, user_id: int, data: UserUpdate) -> Optional[User]:
    user = get_user_by_id(db, user_id)
    if not user:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    user = get_user_by_id(db, user_id)
    if not user:
        return False
    db.delete(user)
    db.commit()
    return True


# ══════════════════════════════════════════════════════
#  KNOWLEDGE BASE  (tabla: knowledge_base)
# ══════════════════════════════════════════════════════

def get_kb_item(db: Session, item_id: int) -> Optional[KnowledgeBase]:
    return db.query(KnowledgeBase).filter(KnowledgeBase.id == item_id).first()


def get_all_kb(db: Session, categoria: Optional[str] = None) -> List[KnowledgeBase]:
    q = db.query(KnowledgeBase)
    if categoria:
        q = q.filter(KnowledgeBase.categoria == categoria)
    return q.order_by(KnowledgeBase.created_at).all()


def create_kb_item(db: Session, data: KBCreate) -> KnowledgeBase:
    item = KnowledgeBase(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_kb_item(db: Session, item_id: int, data: KBUpdate) -> Optional[KnowledgeBase]:
    item = get_kb_item(db, item_id)
    if not item:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


def delete_kb_item(db: Session, item_id: int) -> bool:
    item = get_kb_item(db, item_id)
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


# ══════════════════════════════════════════════════════
#  DOCENTE  (tabla: docentes)
# ══════════════════════════════════════════════════════

def get_docente(db: Session, docente_id: int) -> Optional[Docente]:
    return db.query(Docente).filter(Docente.id == docente_id).first()


def get_all_docentes(db: Session) -> List[Docente]:
    return db.query(Docente).order_by(Docente.nombre).all()


def create_docente(db: Session, data: DocenteCreate) -> Docente:
    docente = Docente(**data.model_dump())
    db.add(docente)
    db.commit()
    db.refresh(docente)
    return docente


def update_docente(db: Session, docente_id: int, data: DocenteUpdate) -> Optional[Docente]:
    docente = get_docente(db, docente_id)
    if not docente:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(docente, field, value)
    db.commit()
    db.refresh(docente)
    return docente


def delete_docente(db: Session, docente_id: int) -> bool:
    docente = get_docente(db, docente_id)
    if not docente:
        return False
    db.delete(docente)
    db.commit()
    return True


# ══════════════════════════════════════════════════════
#  HORARIO  (tabla: horarios)
# ══════════════════════════════════════════════════════

def get_horario(db: Session, horario_id: int) -> Optional[Horario]:
    return db.query(Horario).filter(Horario.id == horario_id).first()


def get_all_horarios(db: Session, grado: Optional[str] = None) -> List[Horario]:
    q = db.query(Horario)
    if grado:
        q = q.filter(Horario.grado == grado)
    return q.order_by(Horario.grado, Horario.hora).all()


def create_horario(db: Session, data: HorarioCreate) -> Horario:
    horario = Horario(**data.model_dump())
    db.add(horario)
    db.commit()
    db.refresh(horario)
    return horario


def update_horario(db: Session, horario_id: int, data: HorarioUpdate) -> Optional[Horario]:
    horario = get_horario(db, horario_id)
    if not horario:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(horario, field, value)
    db.commit()
    db.refresh(horario)
    return horario


def delete_horario(db: Session, horario_id: int) -> bool:
    horario = get_horario(db, horario_id)
    if not horario:
        return False
    db.delete(horario)
    db.commit()
    return True


# ══════════════════════════════════════════════════════
#  CONTACTO  (tabla: contactos)
# ══════════════════════════════════════════════════════

def get_contacto(db: Session, contacto_id: int) -> Optional[Contacto]:
    return db.query(Contacto).filter(Contacto.id == contacto_id).first()


def get_all_contactos(db: Session) -> List[Contacto]:
    return db.query(Contacto).all()


def create_contacto(db: Session, data: ContactoCreate) -> Contacto:
    contacto = Contacto(**data.model_dump())
    db.add(contacto)
    db.commit()
    db.refresh(contacto)
    return contacto


def update_contacto(db: Session, contacto_id: int, data: ContactoUpdate) -> Optional[Contacto]:
    contacto = get_contacto(db, contacto_id)
    if not contacto:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(contacto, field, value)
    db.commit()
    db.refresh(contacto)
    return contacto


def delete_contacto(db: Session, contacto_id: int) -> bool:
    contacto = get_contacto(db, contacto_id)
    if not contacto:
        return False
    db.delete(contacto)
    db.commit()
    return True


# ══════════════════════════════════════════════════════
#  DOCUMENT / DOCUMENT_CHUNK  (tablas: documents, document_chunks)
#  Fuente documental del RAG (p. ej. Manual de Convivencia 2026)
# ══════════════════════════════════════════════════════

def get_document(db: Session, doc_id: int) -> Optional[Document]:
    return db.query(Document).filter(Document.id == doc_id).first()


def get_all_documents(db: Session) -> List[Document]:
    return db.query(Document).order_by(Document.created_at.desc()).all()


def update_document(db: Session, doc_id: int, data: DocumentUpdate) -> Optional[Document]:
    doc = get_document(db, doc_id)
    if not doc:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    db.commit()
    db.refresh(doc)
    return doc


def delete_document(db: Session, doc_id: int) -> bool:
    """Elimina el documento y (por cascade) todos sus chunks."""
    doc = get_document(db, doc_id)
    if not doc:
        return False
    db.delete(doc)
    db.commit()
    return True


def get_document_chunks(
    db: Session,
    doc_id: int,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
) -> Tuple[List[DocumentChunk], int]:
    """Devuelve (chunks_paginados, total) de un documento."""
    q = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id)
    if search:
        term = f"%{search}%"
        q = q.filter(
            or_(
                DocumentChunk.content.ilike(term),
                DocumentChunk.section_title.ilike(term),
                DocumentChunk.article_title.ilike(term),
                DocumentChunk.keywords.ilike(term),
            )
        )
    total = q.count()
    items = (
        q.order_by(DocumentChunk.chunk_index)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return items, total


# ══════════════════════════════════════════════════════
#  IMAGEN  (tabla: imagenes)
# ══════════════════════════════════════════════════════

def get_imagen(db: Session, img_id: int) -> Optional[Imagen]:
    return db.query(Imagen).filter(Imagen.id == img_id).first()


def get_all_imagenes(db: Session, categoria: Optional[str] = None) -> List[Imagen]:
    q = db.query(Imagen)
    if categoria:
        q = q.filter(Imagen.categoria == categoria)
    return q.order_by(Imagen.created_at.desc()).all()


def create_imagen(
    db: Session,
    nombre: str,
    nombre_original: str,
    ruta: str,
    tamano: int,
    descripcion: Optional[str] = None,
    categoria: Optional[str] = None,
) -> Imagen:
    img = Imagen(
        nombre=nombre,
        nombre_original=nombre_original,
        ruta=ruta,
        tamano=tamano,
        descripcion=descripcion,
        categoria=categoria,
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


def delete_imagen(db: Session, img_id: int) -> Optional[Imagen]:
    """Devuelve el objeto antes de borrar (para eliminar el archivo físico)."""
    img = get_imagen(db, img_id)
    if not img:
        return None
    db.delete(img)
    db.commit()
    return img


# ══════════════════════════════════════════════════════
#  CHAT HISTORY  (tabla: chat_history)
# ══════════════════════════════════════════════════════

def create_chat_history(
    db: Session,
    pregunta: str,
    respuesta: str,
    fuente: str,
    usuario: str = "anonimo",
    tiempo_respuesta: Optional[float] = None,
) -> ChatHistory:
    entry = ChatHistory(
        usuario=usuario,
        pregunta=pregunta,
        respuesta=respuesta,
        fuente=fuente,
        tiempo_respuesta=tiempo_respuesta,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _local_day_range_utc(date_str: str, tz_offset: int) -> Tuple[datetime, datetime]:
    """
    Convierte un día local 'YYYY-MM-DD' a un rango [inicio, fin) en UTC.
    tz_offset = minutos que la hora local está por detrás de UTC
    (lo mismo que devuelve Date.getTimezoneOffset() en JS; Colombia = 300).
    """
    local_start = datetime.strptime(date_str, "%Y-%m-%d")
    utc_start = local_start + timedelta(minutes=tz_offset)
    return utc_start, utc_start + timedelta(days=1)


def _history_query(
    db: Session,
    search: Optional[str] = None,
    fuente: Optional[str] = None,
    date: Optional[str] = None,
    tz_offset: int = 0,
):
    q = db.query(ChatHistory)
    if search:
        term = f"%{search}%"
        q = q.filter(
            or_(
                ChatHistory.pregunta.ilike(term),
                ChatHistory.respuesta.ilike(term),
                ChatHistory.usuario.ilike(term),
            )
        )
    if fuente:
        q = q.filter(ChatHistory.fuente == fuente)
    if date:
        try:
            start, end = _local_day_range_utc(date, tz_offset)
            q = q.filter(ChatHistory.created_at >= start, ChatHistory.created_at < end)
        except ValueError:
            pass  # fecha mal formada: se ignora el filtro
    return q


def get_chat_history(
    db: Session,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    fuente: Optional[str] = None,
    date: Optional[str] = None,
    tz_offset: int = 0,
) -> Tuple[List[ChatHistory], int]:
    """Devuelve (lista_paginada, total) con búsqueda y filtros opcionales."""
    q = _history_query(db, search, fuente, date, tz_offset)
    total = q.count()
    items = (
        q.order_by(ChatHistory.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return items, total


def get_chat_history_all(
    db: Session,
    search: Optional[str] = None,
    fuente: Optional[str] = None,
    date: Optional[str] = None,
    tz_offset: int = 0,
) -> List[ChatHistory]:
    """Todas las filas que cumplen el filtro (para exportar CSV/JSON)."""
    q = _history_query(db, search, fuente, date, tz_offset)
    return q.order_by(ChatHistory.created_at.desc()).all()


def get_chat_history_stats(db: Session, tz_offset: int = 0) -> Dict:
    """
    Estadísticas para dashboard/estadísticas del panel.
    Los agrupamientos por hora y por día usan la hora local del cliente (tz_offset).
    """
    rows = db.query(ChatHistory.created_at, ChatHistory.fuente).all()
    total = len(rows)
    avg_time = db.query(func.avg(ChatHistory.tiempo_respuesta)).scalar() or 0.0

    offset = timedelta(minutes=tz_offset)
    local_now = datetime.utcnow() - offset
    today = local_now.date()
    last7 = [today - timedelta(days=i) for i in range(6, -1, -1)]

    por_fuente: Counter = Counter()
    por_hora: Counter = Counter()
    por_dia: Counter = Counter({d.isoformat(): 0 for d in last7})
    hoy = 0
    for created_at, fuente in rows:
        por_fuente[fuente or "Sin fuente"] += 1
        if not created_at:
            continue
        local = created_at - offset
        por_hora[local.hour] += 1
        key = local.date().isoformat()
        if key in por_dia:
            por_dia[key] += 1
        if local.date() == today:
            hoy += 1

    return {
        "total_consultas": total,
        "hoy": hoy,
        "tiempo_promedio_segundos": round(avg_time, 3),
        "por_fuente": dict(por_fuente.most_common()),
        "por_hora": {str(h): por_hora[h] for h in sorted(por_hora)},
        "por_dia": dict(por_dia),   # últimos 7 días, en orden cronológico
    }


def delete_chat_history_entry(db: Session, entry_id: int) -> bool:
    entry = db.query(ChatHistory).filter(ChatHistory.id == entry_id).first()
    if not entry:
        return False
    db.delete(entry)
    db.commit()
    return True


def clear_chat_history(db: Session) -> int:
    """Elimina todo el historial. Devuelve el número de registros borrados."""
    count = db.query(ChatHistory).count()
    db.query(ChatHistory).delete()
    db.commit()
    return count


# ══════════════════════════════════════════════════════
#  BOT CONFIG  (tabla: bot_config)
# ══════════════════════════════════════════════════════

def get_bot_config_dict(db: Session) -> Dict[str, str]:
    """Devuelve toda la configuración como {clave: valor}."""
    rows = db.query(BotConfig).all()
    return {r.clave: r.valor for r in rows if r.valor is not None}


def get_config_value(db: Session, clave: str) -> Optional[str]:
    row = db.query(BotConfig).filter(BotConfig.clave == clave).first()
    return row.valor if row else None


def set_config_value(db: Session, clave: str, valor: str) -> BotConfig:
    row = db.query(BotConfig).filter(BotConfig.clave == clave).first()
    if row:
        row.valor = valor
    else:
        row = BotConfig(clave=clave, valor=valor)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def set_many_config(db: Session, items: List[ConfigItem]) -> None:
    for item in items:
        set_config_value(db, item.clave, item.valor)


def delete_config_value(db: Session, clave: str) -> bool:
    row = db.query(BotConfig).filter(BotConfig.clave == clave).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
