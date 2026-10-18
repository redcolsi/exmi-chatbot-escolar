"""Servicio de integración con Google Gemini para Exmi (actualizado 2026).

Modelos (verificados en https://ai.google.dev/gemini-api/docs/models, oct-2026):
  - Primario : gemini-3.5-flash-lite  (el más rápido y barato de la familia 3.5, estable)
  - Respaldo : gemini-3.1-flash-lite  (estable, frontier-class a fracción del costo)

Cuotas AI Studio (texto): ~15 RPM / 250K TPM / 500 RPD por modelo.
Por eso se usan DOS modelos: si el primario falla (429, 403, red), se intenta el respaldo.

Modo online/offline automático:
  - CON internet + GEMINI_API_KEY válida -> "IA+RAG (Gemini)"
  - SIN internet / sin clave / error IA  -> RAG local: "RAG (sin IA)" o "RAG (error IA)"
"""
from __future__ import annotations

import logging
import os
import re
from typing import Tuple

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)

logger = logging.getLogger(__name__)

# ── Modelos verificados oct-2026 ─────────────────────────────────────
PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite"

SYSTEM_INSTRUCTION = """Eres Exmi, el asistente virtual del Colegio Albert Einstein de Cúcuta, Colombia.
Responde en español, con voz natural, amable y segura. Sé breve cuando la pregunta sea simple.

REGLAS:
1. Si recibes información del colegio y es relevante para la pregunta, respóndela basándote en esa información.
2. Si no hay información relevante (por ejemplo, un saludo como "hola"), responde de forma natural: saluda, preséntate brevemente y ofrece ayuda sobre el colegio (horarios, docentes, convivencia, contactos, admisiones).
3. No inventes datos, nombres, fechas ni artículos que no estén en la información recibida.
4. Si la pregunta es sobre convivencia, disciplina, sanciones, derechos, deberes, uniformes o celulares, prioriza esa información.
5. Cuando cites una norma, menciona el artículo o sección solo si aparece en la información.
6. Usa viñetas cuando una respuesta tenga varios puntos. No repitas la información textualmente: sintetiza.
"""


class GeminiService:
    """Cliente Gemini con doble modelo + fallback RAG offline."""

    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
        self.fallback_model = (
            os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip()
            or "gemini-3.1-flash-lite"
        )
        self.client = None
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                logger.info("[Gemini] Cliente inicializado. Primario=%s Respaldo=%s",
                            self.model, self.fallback_model)
            except Exception as exc:
                logger.error("[Gemini] ERROR inicializando cliente: %s: %s", type(exc).__name__, exc)
                self.client = None
        else:
            logger.warning("[Gemini] Sin GEMINI_API_KEY: se usará solo RAG local (offline).")

    def _refresh_from_env(self) -> None:
        """Re-lee env por si cambió (útil en Vercel / tests)."""
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
        self.fallback_model = (
            os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip()
            or "gemini-3.1-flash-lite"
        )
        if self.api_key and self.client is None:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as exc:
                logger.error("[Gemini] ERROR re-inicializando: %s", exc)

    def _call_model(self, model: str, prompt: str) -> str:
        """Llamada al modelo con doble vía 2026: generate_content y luego Interactions."""
        from google.genai import types

        last_exc: Exception | None = None
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=1024,
                    thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                ),
            )
            text = (getattr(response, "text", None) or "").strip()
            if text:
                return text
            last_exc = RuntimeError(f"El modelo {model} no devolvió texto (generate_content)")
        except Exception as exc:
            last_exc = exc

        try:
            interaction = self.client.interactions.create(
                model=model,
                input=prompt,
                store=False,
            )
            text = getattr(interaction, "output_text", None)
            if not text:
                for step in reversed(getattr(interaction, "steps", []) or []):
                    for content in getattr(step, "content", []) or []:
                        candidate = getattr(content, "text", None)
                        if candidate:
                            text = candidate
                            break
                    if text:
                        break
            text = (str(text) if text else "").strip()
            if text:
                return text
            raise RuntimeError(f"El modelo {model} no devolvió texto (interactions)")
        except Exception as exc:
            raise exc if "PERMISSION_DENIED" in str(exc) or "denied" in str(exc).lower() else (last_exc or exc)

    async def generate_response(self, query: str, context: str, history: str = "") -> Tuple[str, str]:
        """Genera respuesta. Siempre responde algo: IA si hay internet, RAG si no.

        history: resumen de conversación previa (para memoria entre mensajes).
        """
        self._refresh_from_env()

        if not self.api_key or self.client is None:
            logger.info("[Gemini] Offline/sin clave -> RAG local.")
            return self._fallback(context), "RAG (sin IA)"

        clean_context = self._clean_context(context) if context else ""

        # Construir prompt con memoria conversacional
        history_section = ""
        if history:
            history_section = (
                "CONVERSACIÓN ANTERIOR (para contexto, no repitas literalmente):\n"
                + history + "\n\n"
            )

        if clean_context:
            prompt = (
                SYSTEM_INSTRUCTION + "\n\n"
                + history_section
                + "INFORMACIÓN DEL COLEGIO:\n" + clean_context + "\n\n"
                + "PREGUNTA DEL USUARIO:\n" + query + "\n\n"
                + "Responde natural. Si la información es relevante, úsala; si no, responde con naturalidad. "
                + "Si la conversación anterior es relevante, tenla en cuenta."
            )
        else:
            prompt = (
                SYSTEM_INSTRUCTION + "\n\n"
                + history_section
                + "PREGUNTA DEL USUARIO:\n" + query + "\n\n"
                + "Responde natural y conversacional. No hay información del colegio relevante. "
                + "Si es un saludo, saluda y ofrece ayuda sobre el colegio."
            )

        try:
            text = self._call_model(self.model, prompt)
            logger.info("[Gemini] OK con %s", self.model)
            return text, "IA+RAG (Gemini)"
        except Exception as exc1:
            logger.warning("[Gemini] Falló primario %s (%s: %s). Probando respaldo %s...",
                           self.model, type(exc1).__name__, exc1, self.fallback_model)

        if self.fallback_model != self.model:
            try:
                text = self._call_model(self.fallback_model, prompt)
                logger.info("[Gemini] OK con respaldo %s", self.fallback_model)
                return text, "IA+RAG (Gemini)"
            except Exception as exc2:
                logger.error("[Gemini] Falló respaldo %s (%s: %s). Usando RAG local.",
                             self.fallback_model, type(exc2).__name__, exc2)
        else:
            logger.error("[Gemini] Primario y respaldo son el mismo; usando RAG local.")

        return self._fallback(context), "RAG (error IA)"

    def status(self) -> dict:
        """Para /health/ai: dice si hay clave y qué modelos están configurados."""
        self._refresh_from_env()
        return {
            "configurado": bool(self.api_key),
            "modelo_primario": self.model,
            "modelo_respaldo": self.fallback_model,
            "modo": "online (IA+RAG)" if (self.api_key and self.client) else "offline (RAG local)",
        }

    def _fallback(self, context: str) -> str:
        """Respuesta 100% local, sin internet. Limpia el contexto RAG y lo presenta bien."""
        if not context:
            return (
                "¡Hola! Soy Exmi, el asistente del Colegio Albert Einstein. "
                "¿En qué puedo ayudarte? Puedo consultarte horarios, docentes, "
                "contactos, convivencia y más."
            )
        cleaned = self._clean_context(context)
        blocks = []
        current: list[str] = []
        for raw_line in cleaned.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("==="):
                continue
            if line.startswith(("[Documento:", "Sección:", "Artículo:", "Página:",
                                 "[", "Nombre:", "Cargo:", "Grado ")):
                if current:
                    blocks.append(" ".join(current))
                    current = []
                current.append(line)
            else:
                current.append(line)
        if current:
            blocks.append(" ".join(current))
        if not blocks:
            return "Encontré información relacionada, pero no puedo redactar una respuesta ahora."
        excerpt = "\n\n".join(blocks[:3])
        return "Encontré esta información institucional relacionada con tu consulta:\n\n" + excerpt

    @staticmethod
    def _clean_context(context: str) -> str:
        """Limpia el formato crudo del RAG para que Gemini lo lea natural."""
        lines = []
        for line in context.splitlines():
            line = line.strip()
            if not line or line.startswith("==="):
                continue
            # [CATEGORIA] Pregunta: ... Respuesta: ...  ->  solo la respuesta
            m = re.match(r"^\[([^\]]+)\]\s*Pregunta:\s*(.*?)\s*Respuesta:\s*(.*)$", line)
            if m:
                cat, pregunta, respuesta = m.groups()
                lines.append(f"- {respuesta.strip()}")
                continue
            # Etiquetas de documentos: quitar corchetes
            line = re.sub(r"^\[Documento:([^\]]+)\]", r"Documento: \1", line)
            line = re.sub(r"^\[Sección:([^\]]+)\]", r"Sección: \1", line)
            line = re.sub(r"^\[Artículo:([^\]]+)\]", r"Artículo: \1", line)
            line = re.sub(r"^\[Página:([^\]]+)\]", r"Página: \1", line)
            lines.append(line)
        return "\n".join(lines)
