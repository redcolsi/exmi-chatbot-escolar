"""
app/routes/chatbot.py — Endpoint principal del chatbot escolar Exmi.

Flujo de cada request:
  1. Validar que la pregunta no esté vacía.
  2. RAGService.build_context()  →  busca contexto en BD (KB, docentes, horarios, contactos, documentos).
  3. GeminiService.generate_response()  →  genera respuesta con IA o fallback.
  4. crud.create_chat_history()  →  persiste la conversación (siempre, incluso con error).
  5. Retornar ChatResponse.

Buenas prácticas aplicadas:
  - Depends(get_db) para la sesión de BD.
  - Logging estructurado en cada etapa.
  - Manejo de errores con respuesta segura al usuario.
  - El historial se guarda en bloque finally para garantizar persistencia.
  - Desacoplado de la IA: si GeminiService falla, el RAG aún responde.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import app.crud as crud
from app.ai.gemini_service import GeminiService
from app.database.database import get_db
from app.rag.rag_service import RAGService
from app.schemas.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chatbot"])

# Instancias de servicios (singleton por proceso)
_rag = RAGService()
_ai = GeminiService()

# ── Rate limit: 50 preguntas por usuario por día ─────────────────
# En Vercel serverless el memorio se resetea entre arranques, pero
# evita abuso masivo en una misma sesión de usuario.
DAILY_LIMIT = 50
_user_calls: dict[str, list[float]] = defaultdict(list)

def _check_rate_limit(usuario: str) -> None:
    now = time.time()
    calls = _user_calls[usuario]
    # Limpiar llamadas de más de 24 horas
    calls[:] = [t for t in calls if now - t < 86400]
    if len(calls) >= DAILY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Límite diario alcanzado ({DAILY_LIMIT} preguntas/día). "
                   f"Contacta al colegio al +57 312 5399542.",
        )
    calls.append(now)

# Respuesta de último recurso cuando todo falla
_FALLBACK_MSG = (
    "En este momento no puedo procesar tu consulta. "
    "Por favor contacta directamente al Colegio Albert Einstein "
    "al +57 312 5399542 o visita www.webcolegios.com/coleinstein."
)


@router.post(
    "/",
    response_model=ChatResponse,
    summary="Enviar pregunta al chatbot",
    description=(
        "Recibe una pregunta en lenguaje natural, la busca en la base de conocimiento "
        "institucional mediante RAG y genera una respuesta con IA. "
        "Toda conversación queda registrada en el historial (solo visible para el docente)."
    ),
)
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
) -> ChatResponse:
    # ── Validación ──────────────────────────────────────────────
    pregunta = (request.pregunta or "").strip()
    if not pregunta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La pregunta no puede estar vacía.",
        )

    usuario = (request.usuario or "anonimo").strip() or "anonimo"
    logger.info("[chatbot] Pregunta de '%s': %s", usuario, pregunta[:120])

    # Rate limit por usuario (protección de cuota Gemini)
    _check_rate_limit(usuario)

    respuesta: str = _FALLBACK_MSG
    fuente: str = "Error"
    start: float = time.perf_counter()

    try:
        # ── Paso 1: RAG — recuperar contexto institucional ───────
        context, sources = _rag.build_context(pregunta, db)
        logger.debug("[chatbot] Fuentes RAG: %s", sources or "ninguna")

        # ── Paso 1.5: Memoria conversacional (últimas 6 interacciones) ──
        try:
            recent = db.query(crud.ChatHistory).filter(
                crud.ChatHistory.usuario == usuario
            ).order_by(crud.ChatHistory.created_at.desc()).limit(6).all()
            history_lines = []
            for h in reversed(recent):  # orden cronológico (más antiguo primero)
                history_lines.append(f"- Usuario: {h.pregunta}")
                if h.respuesta:
                    history_lines.append(f"  Exmi: {h.respuesta[:200]}")
            history_text = "\n".join(history_lines[-10:])  # máx ~10 líneas
        except Exception as hist_err:
            logger.warning("[chatbot] No se pudo cargar historial: %s", hist_err)
            history_text = ""

        # ── Paso 2: Generar respuesta ────────────────────────────
        # SIEMPRE se llama a Gemini (con o sin contexto RAG).
        respuesta, fuente = await _ai.generate_response(pregunta, context, history_text)
        logger.info("[chatbot] Respuesta generada. Fuente: %s", fuente)

    except Exception as exc:  # noqa: BLE001
        logger.exception("[chatbot] Error inesperado al procesar pregunta: %s", exc)
        respuesta = _FALLBACK_MSG
        fuente = "Error"

    finally:
        # ── Paso 3: Persistir en historial (SQLite, base principal) ──
        elapsed = round(time.perf_counter() - start, 3)

        # SQLite (base principal: local exmi.db o Supabase Postgres en Vercel)
        try:
            crud.create_chat_history(
                db=db,
                usuario=usuario,
                pregunta=pregunta,
                respuesta=respuesta,
                fuente=fuente,
                tiempo_respuesta=elapsed,
            )
            logger.debug("[chatbot] Historial guardado en BD (%.3f s)", elapsed)
        except Exception as hist_exc:  # noqa: BLE001
            logger.warning("[chatbot] No se pudo guardar en BD: %s", hist_exc)

    return ChatResponse(respuesta=respuesta, fuente=fuente)

