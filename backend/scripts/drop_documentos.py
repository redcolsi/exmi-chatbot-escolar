"""
scripts/drop_documentos.py — Migración única: elimina la tabla muerta `documentos`.

La tabla `documentos` (modelo `Documento`) quedó duplicada por `documents` +
`document_chunks` (RAG). Como `Base.metadata.create_all()` nunca borra tablas,
hay que quitarla a mano en las bases ya existentes.

Uso (desde la carpeta backend, con el servidor detenido):
    python scripts/drop_documentos.py

Seguridad:
  · Hace una copia de respaldo del .db antes de tocar nada (exmi.db.bak-AAAAMMDD-HHMMSS).
  · Se niega a borrar si la tabla tiene filas, salvo que uses --force.
  · Es idempotente: si la tabla ya no existe, no hace nada.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sqlite_path() -> Path:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
    url = url or "sqlite:///./exmi.db"
    if not url.startswith("sqlite:///"):
        sys.exit(f"DATABASE_URL no es SQLite ({url}). Ejecuta manualmente: DROP TABLE documentos;")
    raw = url[len("sqlite:///"):]
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p).resolve()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="borra aunque la tabla tenga filas")
    args = ap.parse_args()

    db = sqlite_path()
    if not db.exists():
        sys.exit(f"No existe la base de datos: {db}")

    con = sqlite3.connect(db)
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documentos'"
        ).fetchone()
        if not exists:
            print("La tabla 'documentos' ya no existe. Nada que hacer.")
            return
        rows = con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]
        if rows and not args.force:
            sys.exit(f"'documentos' tiene {rows} filas. Revísalas o usa --force para borrarla igual.")

        backup = db.with_name(f"{db.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(db, backup)
        print(f"Respaldo creado: {backup}")

        con.execute("DROP TABLE documentos")
        con.commit()
        print("Tabla 'documentos' eliminada.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
