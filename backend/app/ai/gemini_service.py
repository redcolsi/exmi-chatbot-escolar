"""Servicio de integración con Google Gemini para Exmi (actualizado 2026).

Modelos (verificados en https://ai.google.dev/gemini-api/docs/models, sep-2026):
  - Primario : gemini-3.5-flash-lite  (el más rápido y barato de la familia 3.5, estable)
  - Respaldo : gemini-3.1-flash-lite  (estable, frontier-class a fracción del costo)

Cuotas AI Studio del usuario (texto de salida): 15 RPM / 250K TPM / 500 RPD por modelo.
Por eso se usan DOS modelos: si el primario falla (429, 404, red), se intenta el respaldo.

Modo online/offline automático:
  - CON internet + GEMINI_API_KEY válida -> "IA+RAG (Gemini <modelo>)"
  - SIN internet / sin clave / error IA     -> RAG local (fallback) "RAG (sin IA)" o "RAG (error IA)"
  Así funciona local sin internet y en Vercel con internet, sin cambiar código.

Uso correcto SDK 2026 (google-genai >= 1.0):
  from google import genai
  from google.genai import types
  client = genai.Client(api_key=...)
  client.models.generate_content(model=..., contents=..., config=types.GenerateContentConfig(...))

La API key NUNCA sale al frontend; vive solo en el servidor (.env local / env Vercel).
"""
from __future__ import annotations

import logging
import os
from typing import Tuple

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)

logger = logging.getLogger(__name__)

# ── Modelos verificados sep-2026 ─────────────────────────────────────
PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite"

SYSTEM_INSTRUCTION = """Eres Exmi, el asistente virtual oficial del Colegio Albert Einstein de Cúcuta, Colombia.
Responde en español con una voz natural, amable y segura. Redacta con buena elocuencia: organiza primero la respuesta directa y después explica lo necesario, usando frases completas y vocabulario sencillo.

REGLAS IMPORTANTES:
1. La fuente de verdad es exclusivamente el CONTEXTO INSTITUCIONAL que recibes.
2. No inventes datos, nombres, fechas, sanciones, artículos ni procedimientos.
3. Si el contexto no contiene la respuesta, dilo claramente: no tengo esa información en el contexto institucional disponible.
4. Si la pregunta trata sobre convivencia, disciplina, faltas, derechos, deberes, sanciones, debido proceso, uniformes, celulares u otras normas, prioriza los fragmentos del Manual de Convivencia 2026.
5. Cuando sea posible, menciona el título o artículo/sección del manual que respalda la respuesta.
6. Distingue entre una regla del manual y una recomendación general.
7. No completes información faltante con conocimiento general.
8. Evita repetir el contexto literalmente o enumerar fragmentos sin explicarlos. Sintetiza la información pertinente en una respuesta coherente.
9. Sé breve cuando la pregunta sea simple; usa pasos o viñetas cuando aclaren un procedimiento o una lista.
10. Si incluyes una norma, identifica el artículo o sección solo cuando aparezca en el contexto. No presentes una inferencia como cita textual.
"""


class GeminiService:
    """Cliente Gemini con doble modelo + fallback RAG offline."""

    def __init__(self) -> None:
        # Se leen en __init__ pero también se re-leen en cada llamada
        # para que Vercel (env) y .env local funcionen sin reinicio manual.
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
        self.fallback_model = (
            os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip()
            or "gemini-3.1-flash-lite"
        )
        self.client = None
        if self.api_key:
            try:
                from google import genai  # import diferido: permite arrancar sin internet

                self.client = genai.Client(api_key=self.api_key)
                logger.info("[Gemini] Cliente inicializado. Primario=%s Respaldo=%s",
                            self.model, self.fallback_model)
            except Exception as exc:
                logger.error("[Gemini] ERROR inicializando cliente: %s: %s",
                             type(exc).__name__, exc)
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
        """Llamada al modelo con doble vía 2026: generate_content y luego Interactions.

        Nota 2026: en gemini-3.5-flash-lite / 3.1-flash-lite los parámetros
        `temperature`, `top_p` y `top_k` están deprecados e ignorados
        (en futuras generaciones devuelven 400). Por eso NO se envían;
        solo se limita `max_output_tokens` y nivel de pensamiento mínimo.
        """
        from google.genai import types

        last_exc: Exception | None = None
        # Vía 1: generate_content (estándar SDK)
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

        # Vía 2: Interactions API (recomendada para proyectos nuevos 2026)
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
            # Si la vía 2 también falla, se propaga el error más informativo
            raise exc if "PERMISSION_DENIED" in str(exc) or "denied" in str(exc).lower() else (last_exc or exc)

    async def generate_response(self, query: str, context: str) -> Tuple[str, str]:
        """Genera respuesta. Siempre responde algo: IA si hay internet, RAG si no."""
        self._refresh_from_env()

        if not self.api_key or self.client is None:
            logger.info("[Gemini] Offline/sin clave -> RAG local.")
            return self._fallback(context), "RAG (sin IA)"

        prompt = (
            SYSTEM_INSTRUCTION + "\n\n"
            + "CONTEXTO INSTITUCIONAL:\n" + context + "\n\n"
            + "PREGUNTA DEL USUARIO:\n" + query + "\n\n"
            + "Responde únicamente con base en el contexto anterior."
        )

        # 1) Intento con modelo primario (3.5 Flash-Lite)
        try:
            text = self._call_model(self.model, prompt)
            logger.info("[Gemini] OK con %s", self.model)
            return text, "IA+RAG (Gemini)"
        except Exception as exc1:
            logger.warning("[Gemini] Falló primario %s (%s: %s). Probando respaldo %s...",
                           self.model, type(exc1).__name__, exc1, self.fallback_model)

        # 2) Intento con modelo respaldo (3.1 Flash-Lite)
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

        # 3) Sin internet / cuota agotada / error -> RAG local (offline)
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
        """Respuesta 100% local, sin internet. Usa solo el contexto RAG de la BD."""
        if not context:
            return "No encontré información institucional relacionada con tu pregunta."
        blocks = []
        current = []
        for raw_line in context.splitlines():
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
