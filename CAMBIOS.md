# Exmi — limpieza a una sola fuente de datos

## Cómo aplicarlo
1. Detén el servidor y respalda tu `exmi.db` y tu `.env` (este ZIP **no** los incluye; no se tocan).
2. Copia estas carpetas/archivos sobre tu proyecto (sobrescribe).
3. **Rota la clave de Gemini** en Google AI Studio y ponla solo en tu `.env` (ver "Seguridad").
4. Desde `backend/`: `python scripts/drop_documentos.py`  → elimina la tabla muerta `documentos` (hace respaldo y se niega si tuviera filas).
5. Borra `backend/app/ai/claude_service.py` si tu copia aún lo tiene (en este ZIP ya no está).
6. `pip install -r requirements.txt` (sin cambios) y arranca: `python run.py`.

## Qué cambió
**Backend**
- `models/models.py`, `schemas/schemas.py`, `rag/rag_service.py`: eliminados `Documento` / `DocumentoResponse` y el import muerto.
- `crud.py`: quitadas las funciones de `Documento`; añadidas las de `Document`/`DocumentChunk`; historial con filtros (búsqueda, fuente, día local) y estadísticas (por fuente, hora y día, con zona horaria del cliente); `delete_config_value`.
- `routes/public.py` (NUEVO, sin login, solo lectura): `GET /public/horarios | docentes | contactos | kb | config`.
- `routes/admin.py` (reescrito sobre `crud.py`, todo exige rol admin). Nuevo:
  - Config del bot: `GET/PUT /admin/config`, `POST/DELETE /admin/config/avatar`
  - Imágenes: `GET/POST /admin/imagenes`, `DELETE /admin/imagenes/{id}`
  - Documentos RAG: `GET /admin/documents`, `POST /admin/documents/import-json`, `PUT/DELETE /admin/documents/{id}`, `GET /admin/documents/{id}/chunks`
  - Historial: `GET /admin/history` (paginado), `/admin/history/stats`, `/admin/history/export?format=csv|json`, `DELETE /admin/history/{id}`, `DELETE /admin/history`
  - `/admin/data` ya no devuelve el historial (ahora va paginado).
- `main.py`: registra el router público.
- `ai/claude_service.py`: eliminado (nadie lo importaba).
- `seed_data.py`: busca `MANUAL_DE_CONVIVENCIA_2026.json` (el nombre real; antes buscaba uno con espacios y no lo encontraba) y crea la config `sections`.
- `.env.example`: clave real reemplazada por placeholder.
- `schemas/document.py`: quitado `orm_mode` (Pydantic v1); `models/document.py`: arreglado un `SyntaxWarning` en un docstring.
- `scripts/drop_documentos.py` (NUEVO): migración única.

**Frontend (`exmi_sistema_completo.html`)**
- Eliminados: arrays KB/DOCENTES/HORARIOS/CONTACTOS hardcodeados, `DB` (localStorage), historial local, `AUTH`, `detectCat`, `buildContext`, `askAI`, `rulesResponse`. En el navegador solo queda el token de sesión.
- Pestañas Horarios/Docentes/Convivencia/Contactos leen `/public/*` siempre (con o sin admin).
- Nombre, bienvenida, colores, secciones y avatar se guardan en el backend y los ven todos los visitantes.
- Multimedia → imágenes reales (`/admin/imagenes`); nueva sección "Documentos del RAG" (importar JSON, activar/desactivar, ver fragmentos, borrar).
- Historial con búsqueda, filtro por fuente y fecha, paginación y exportación en el servidor.
- Dashboard/Estadísticas salen del backend; "categoría" pasó a ser "fuente de respuesta" (IA+RAG, RAG sin IA, etc.), porque el backend no clasifica por tema.
- Cambiar contraseña usa `/auth/change-password` (se quitó "Nuevo usuario": el backend no lo soporta).
- Todo texto que viene de la BD o del modelo se escapa antes de pintarlo (HTML inyectado ya no se ejecuta).

## Seguridad
La misma clave de Gemini estaba en `.env.example` y en `.env`. Si el ZIP o `.env.example` estuvo en algún repo/chat compartido, rótala ya y deja `.env.example` solo con el placeholder.

## Pendiente / no tocado
- "Difusión" solo pinta el aviso en tu pantalla; no se envía a otros usuarios.
- `ai_mode` ("solo reglas") se guarda pero el backend aún no lo usa.
- Importar PDF directo no está conectado (solo JSON); `pdf_to_json.py` sigue siendo un paso aparte.
- CORS sigue en `*`; restríngelo al dominio real en producción.
