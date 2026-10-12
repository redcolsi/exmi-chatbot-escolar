EXMI - corrección RAG + BD única

1) La BD institucional ahora vive en el backend. El frontend solo mantiene sesión y preferencias visuales en localStorage.
2) Panel admin: /admin/data y CRUD /admin/kb, /admin/docentes, /admin/horarios, /admin/contactos.
3) El Manual de Convivencia 2026 se recupera por fragmentos relevantes (máximo 4) y se entrega a Gemini.
4) Si Gemini no está configurado, el log mostrará el motivo y el chatbot indicará RAG (sin IA).
5) En .env del backend: GEMINI_API_KEY=... y GEMINI_MODEL=gemini-2.5-flash
