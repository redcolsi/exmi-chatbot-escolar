"""
Schemas Pydantic v2 — contratos de request/response de la API.

Regla de Optional:
  Todo campo de BD que es nullable=True (sin nullable=False explícito en el Column)
  debe declararse como Optional[T] en el Response schema para evitar errores de
  validación al serializar filas con NULL.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# ══════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class UpdateAccountRequest(BaseModel):
    current_password: str
    email: str
    username: str


# ══════════════════════════════════════════════════════
#  USUARIO  (model: User, tabla: users)
# ══════════════════════════════════════════════════════

class UserCreate(BaseModel):
    email: str
    username: str
    password: str
    role: str = "user"          # "admin" | "user"


class UserUpdate(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str
    role: str
    is_active: bool
    created_at: datetime


# ══════════════════════════════════════════════════════
#  DOCENTE  (model: Docente, tabla: docentes)
# ══════════════════════════════════════════════════════

class DocenteCreate(BaseModel):
    nombre: str
    area: str
    titulo: str
    grados: str
    atencion: str


class DocenteUpdate(BaseModel):
    nombre: Optional[str] = None
    area: Optional[str] = None
    titulo: Optional[str] = None
    grados: Optional[str] = None
    atencion: Optional[str] = None


class DocenteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    area: Optional[str] = None
    titulo: Optional[str] = None
    grados: Optional[str] = None
    atencion: Optional[str] = None
    created_at: datetime


# ══════════════════════════════════════════════════════
#  HORARIO  (model: Horario, tabla: horarios)
# ══════════════════════════════════════════════════════

class HorarioCreate(BaseModel):
    grado: str
    hora: str
    materia: str
    docente: str
    dia: str = "Lunes–Viernes"


class HorarioUpdate(BaseModel):
    grado: Optional[str] = None
    hora: Optional[str] = None
    materia: Optional[str] = None
    docente: Optional[str] = None
    dia: Optional[str] = None


class HorarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    grado: str
    hora: Optional[str] = None         # nullable en BD
    materia: Optional[str] = None      # nullable en BD
    docente: Optional[str] = None      # nullable en BD
    dia: Optional[str] = None          # nullable en BD


# ══════════════════════════════════════════════════════
#  CONTACTO  (model: Contacto, tabla: contactos)
# ══════════════════════════════════════════════════════

class ContactoCreate(BaseModel):
    cargo: str
    nombre: str
    contacto: str
    horario: str


class ContactoUpdate(BaseModel):
    cargo: Optional[str] = None
    nombre: Optional[str] = None
    contacto: Optional[str] = None
    horario: Optional[str] = None


class ContactoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cargo: Optional[str] = None
    nombre: Optional[str] = None
    contacto: Optional[str] = None
    horario: Optional[str] = None


# ══════════════════════════════════════════════════════
#  BASE DE CONOCIMIENTO  (model: KnowledgeBase, tabla: knowledge_base)
# ══════════════════════════════════════════════════════

class KBCreate(BaseModel):
    categoria: str
    pregunta: str
    respuesta: str


class KBUpdate(BaseModel):
    categoria: Optional[str] = None
    pregunta: Optional[str] = None
    respuesta: Optional[str] = None


class KBResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    categoria: str
    pregunta: str
    respuesta: str
    created_at: datetime


# ══════════════════════════════════════════════════════
#  IMAGEN  (model: Imagen, tabla: imagenes)
# ══════════════════════════════════════════════════════

class ImagenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    nombre_original: Optional[str] = None
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    ruta: str
    tamano: Optional[int] = None        # nullable → Optional
    created_at: datetime


# ══════════════════════════════════════════════════════
#  HISTORIAL DE CHAT  (model: ChatHistory, tabla: chat_history)
# ══════════════════════════════════════════════════════

class HistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario: str
    pregunta: str
    respuesta: Optional[str] = None     # nullable → Optional
    fuente: Optional[str] = None
    tiempo_respuesta: Optional[float] = None
    created_at: datetime


class HistoryListResponse(BaseModel):
    items: List[HistoryResponse]
    total: int
    page: int
    per_page: int


# ══════════════════════════════════════════════════════
#  CHAT
# ══════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    pregunta: str
    usuario: str = "anonimo"


class ImagenRespuesta(BaseModel):
    """Imagen que acompaña la respuesta del chatbot."""
    id: int
    ruta: str
    descripcion: Optional[str] = None


class ChatResponse(BaseModel):
    respuesta: str
    fuente: str     # "IA+RAG" | "RAG (sin IA)" | "Sin información" | "Error"
    imagenes: List[ImagenRespuesta] = []   # imágenes cuya pregunta disparadora coincidió


# ══════════════════════════════════════════════════════
#  CONFIGURACIÓN DEL BOT  (model: BotConfig, tabla: bot_config)
# ══════════════════════════════════════════════════════

class ConfigItem(BaseModel):
    clave: str
    valor: str


class ConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    clave: str
    valor: Optional[str] = None
    updated_at: datetime


# ══════════════════════════════════════════════════════
#  GENÉRICO
# ══════════════════════════════════════════════════════

class MessageResponse(BaseModel):
    message: str
