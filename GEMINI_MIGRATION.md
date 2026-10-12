# Exmi con Google Gemini

Esta versión de Exmi ya está preparada para usar Google Gemini en lugar de Anthropic Claude.

## 1. Instalar dependencias

Dentro de `exmi_backend`:

```powershell
pip install -r requirements.txt
```

## 2. Crear la clave de Gemini

Crea una API key en Google AI Studio y **no la pongas en el HTML/frontend**.

## 3. Configurar `.env`

Copia `.env.example` como `.env` y completa:

```env
GEMINI_API_KEY=TU_CLAVE_DE_GEMINI
GEMINI_MODEL=gemini-2.5-flash
```

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

`Frontend -> FastAPI /chat/ -> RAG -> Gemini -> respuesta`

La API key nunca se envía al navegador.

> Nota: esta versión usa el SDK oficial `google-genai` y la API de Interactions de Gemini. El modelo queda configurable con `GEMINI_MODEL`.
