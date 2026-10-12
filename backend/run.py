"""
run.py — Arrancar el servidor de desarrollo con un solo comando:

    python run.py

Para producción usa gunicorn:
    gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
"""
import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    reload = os.getenv("ENV", "development") == "development"

    print(f"\n🚀 Iniciando Exmi API en http://{host}:{port}")
    print(f"   Documentación: http://localhost:{port}/docs\n")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
