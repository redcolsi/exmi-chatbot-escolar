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

    respuesta: str = _FALLBACK_MSG
    fuente: str = "Error"
    start: float = time.perf_counter()

    try:
        # ── Paso 1: RAG — recuperar contexto institucional ───────
        context, sources = _rag.build_context(pregunta, db)
        logger.debug("[chatbot] Fuentes RAG: %s", sources or "ninguna")

        # ── Paso 2: Generar respuesta ────────────────────────────
        if context:
            respuesta, fuente = await _ai.generate_response(pregunta, context)
            logger.info("[chatbot] Respuesta generada. Fuente: %s", fuente)
        else:
            logger.info("[chatbot] Sin contexto relevante para: %s", pregunta[:80])
            respuesta = (
                "No encontré información institucional relacionada con tu pregunta. "
                "Te sugiero contactar al colegio al +57 312 5399542 "
                "o visitar www.webcolegios.com/coleinstein."
            )
            fuente = "Sin información"

    except Exception as exc:  # noqa: BLE001
        logger.exception("[chatbot] Error inesperado al procesar pregunta: %s", exc)
        respuesta = _FALLBACK_MSG
        fuente = "Error"

    finally:
        # ── Paso 3: Persistir en historial ───────────────────────
        elapsed = round(time.perf_counter() - start, 3)
        try:
            crud.create_chat_history(
                db=db,
                usuario=usuario,
                pregunta=pregunta,
                respuesta=respuesta,
                fuente=fuente,
                tiempo_respuesta=elapsed,
            )
            logger.debug("[chatbot] Historial guardado (%.3f s)", elapsed)
        except Exception as hist_exc:  # noqa: BLE001
            # No dejar que un fallo en el historial afecte la respuesta al usuario
            logger.warning("[chatbot] No se pudo guardar historial: %s", hist_exc)

    return ChatResponse(respuesta=respuesta, fuente=fuente)
