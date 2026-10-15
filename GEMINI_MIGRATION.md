# Exmi con Google Gemini (AI Studio) — 2026

Esta versión usa Google Gemini con doble modelo Lite (verificado oct-2026 en https://ai.google.dev/gemini-api/docs/models).

## Modelos

- Primario: `gemini-3.5-flash-lite` (env `GEMINI_MODEL`) — más rápido y barato de la familia 3.5, GA julio 2026.
- Respaldo: `gemini-3.1-flash-lite` (env `GEMINI_FALLBACK_MODEL`) — estable, GA mayo 2026.
- Cuota AI Studio por modelo (texto): 15 RPM / 250K TPM / 500 RPD aprox. Por eso hay DOS modelos: si el primario da 429/404/error de red, se intenta el respaldo.
- SDK oficial 2026: `google-genai>=1.0.0` con `client.models.generate_content(model=..., contents=..., config=GenerateContentConfig(temperature=0.3, max_output_tokens=1024))` + fallback `client.interactions.create(...)`.
- `gemini-2.5-flash` quedó obsoleto para proyectos nuevos: no usar.

## 1. Instalar dependencias

Dentro de `backend`:

```powershell
pip install -r requirements.txt
```

Incluye `psycopg2-binary` (Supabase/Postgres), `google-genai`, `qrcode[pil]`.

## 2. Crear la clave de Gemini

Crea una API key en Google AI Studio y **no la pongas en el HTML/frontend**.

## 3. Configurar `.env`

Copia `.env.example` como `.env` y completa:

```env
GEMINI_API_KEY=TU_CLAVE_DE_AI_STUDIO
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODEL=gemini-3.1-flash-lite
SECRET_KEY=<clave aleatoria 64 hex>
DATABASE_URL=sqlite:///./exmi.db
```

Local = SQLite offline. Vercel = `/tmp/exmi.db` con auto-seed si no hay `DATABASE_URL`.
Supabase Postgres: cambia `DATABASE_URL` a `postgresql://...` (pooler 6543 en serverless).

También debes mantener una `SECRET_KEY` segura para los JWT.

## 4. Inicializar la base de datos si es una instalación nueva

```powershell
python seed_data.py
```

## 5. Ejecutar

```powershell
python run.py
```

Abre:

`http://127.0.0.1:8000/`

## 6. Probar

Inicia sesión con el usuario administrador creado por `seed_data.py` y envía una pregunta al chatbot.

La arquitectura sigue siendo:

`Frontend -> FastAPI /chat/ -> RAG -> Gemini (3.5 lite -> 3.1 lite) -> respuesta`

La API key nunca se envía al navegador. Sin clave o sin internet responde `RAG (sin IA)` / `RAG (error IA)`. Con internet responde `IA+RAG (Gemini)`.

Endpoints de verificación: `/health`, `/health/ai`, `/api/status`, `/connection-test`.
