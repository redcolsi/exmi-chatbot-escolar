"""Servicio de integración con Google Gemini para Exmi."""
from __future__ import annotations

import os
from typing import Tuple

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)

SYSTEM_INSTRUCTION = """Eres Exmi, el asistente virtual oficial del Colegio Albert Einstein de Cúcuta, Colombia.
Responde en español, de forma clara, amable y precisa.

REGLAS IMPORTANTES:
1. La fuente de verdad es exclusivamente el CONTEXTO INSTITUCIONAL que recibes.
2. No inventes datos, nombres, fechas, sanciones, artículos ni procedimientos.
3. Si el contexto no contiene la respuesta, dilo claramente: no tengo esa información en el contexto institucional disponible.
4. Si la pregunta trata sobre convivencia, disciplina, faltas, derechos, deberes, sanciones, debido proceso, uniformes, celulares u otras normas, prioriza los fragmentos del Manual de Convivencia 2026.
5. Cuando sea posible, menciona el título o artículo/sección del manual que respalda la respuesta.
6. Distingue entre una regla del manual y una recomendación general.
7. No completes información faltante con conocimiento general.
"""


class GeminiService:
    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        self.client = None
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as exc:
                print(f"[GeminiService] ERROR inicializando Gemini: {type(exc).__name__}: {exc}")

    async def generate_response(self, query: str, context: str) -> Tuple[str, str]:
        if not self.api_key or self.client is None:
            return self._fallback(context), "RAG (sin IA)"

        prompt = (
            SYSTEM_INSTRUCTION + "\n\n"
            + "CONTEXTO INSTITUCIONAL:\n" + context + "\n\n"
            + "PREGUNTA DEL USUARIO:\n" + query + "\n\n"
            + "Responde únicamente con base en el contexto anterior."
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            text = (getattr(response, "text", None) or "").strip()
            if not text:
                raise RuntimeError("Gemini no devolvió texto")
            return text, "IA+RAG (Gemini)"
        except Exception as exc:
            print(f"[GeminiService] ERROR generando respuesta: {type(exc).__name__}: {exc}")
            return self._fallback(context), "RAG (error IA)"

    def _fallback(self, context: str) -> str:
        if not context:
            return "No encontré información institucional relacionada con tu pregunta."
        lines = [line.strip() for line in context.split("\n") if line.strip() and not line.startswith("===")]
        return " ".join(lines[:5]) if lines else "Encontré información relacionada, pero no puedo procesarla ahora."
