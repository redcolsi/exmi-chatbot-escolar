"""
Modelos SQLAlchemy — todas las tablas del proyecto Exmi.
Diseñados para SQLite (desarrollo) con fácil migración a PostgreSQL.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Float, DateTime
)
from app.database.database import Base


class User(Base):
    """Usuarios del sistema: docentes (admin) y usuarios generales."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="user", nullable=False)  # "admin" | "user"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Docente(Base):
    """Cuerpo docente del colegio."""
    __tablename__ = "docentes"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    area = Column(String(255))
    titulo = Column(String(255))
    grados = Column(String(100))
    atencion = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Horario(Base):
    """Horarios de clases por grado."""
    __tablename__ = "horarios"

    id = Column(Integer, primary_key=True, index=True)
    grado = Column(String(20), nullable=False, index=True)
    hora = Column(String(50))
    materia = Column(String(100))
    docente = Column(String(255))
    dia = Column(String(50), default="Lunes–Viernes")


class Contacto(Base):
    """Directorio de contactos institucionales."""
    __tablename__ = "contactos"

    id = Column(Integer, primary_key=True, index=True)
    cargo = Column(String(100))
    nombre = Column(String(255))
    contacto = Column(String(255))
    horario = Column(String(255))


class KnowledgeBase(Base):
    """
    Base de conocimiento institucional: misión, visión, normas, FAQs, etc.
    Principal fuente de información para el RAG.
    """
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True, index=True)
    categoria = Column(String(50), index=True)  # mision_vision, academico, convivencia…
    pregunta = Column(Text, nullable=False)
    respuesta = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Imagen(Base):
    """
    Imágenes subidas (horarios, circulares, fotografías, comunicados, promociones).

    `pregunta_disparadora` permite que el chatbot muestre la imagen cuando el
    visitante pregunta por un tema concreto (palabras clave separadas por coma).
    Vacío = la imagen solo aparece en la galería, no se responde con ella.
    """
    __tablename__ = "imagenes"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)           # nombre único en disco
    nombre_original = Column(String(255))
    descripcion = Column(String(500))
    categoria = Column(String(50))                         # horarios | fotografias | circulares | comunicados | promociones
    ruta = Column(String(500))                             # URL pública: /uploads/imagenes/xxx
    tamano = Column(Integer)
    pregunta_disparadora = Column(String(500))            # palabras clave que hacen que el bot muestre la imagen
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatHistory(Base):
    """Historial de conversaciones del chatbot (solo visible para el admin)."""
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    usuario = Column(String(255), default="anonimo")
    pregunta = Column(Text, nullable=False)
    respuesta = Column(Text)
    fuente = Column(String(50))        # "IA+RAG" | "Reglas" | "Sin información"
    tiempo_respuesta = Column(Float)   # segundos
    created_at = Column(DateTime, default=datetime.utcnow)


class BotConfig(Base):
    """Configuración del chatbot (nombre, mensaje de bienvenida, colores, etc.)."""
    __tablename__ = "bot_config"

    id = Column(Integer, primary_key=True, index=True)
    clave = Column(String(100), unique=True, nullable=False)
    valor = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow)
