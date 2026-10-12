"""
app/converters/json_to_db.py
==============================
Fase 2.3 — Importa el JSON generado por pdf_to_json.py a la base de datos.

ESTRATEGIA DE IDEMPOTENCIA:
  Si el documento ya existe (mismo nombre), se REEMPLAZA:
  elimina el Document anterior y sus chunks, luego importa de nuevo.
  Esto garantiza que ejecutar dos veces el comando NO duplica datos.

USO DESDE TERMINAL:
  # Importar por primera vez
  python -m app.converters.json_to_db \\
      --json "app/documents/MANUAL DE CONVIVENCIA 2026.json" \\
      --name "Manual de Convivencia 2026" \\
      --cat  convivencia

  # Reimportar (reemplaza el anterior automáticamente)
  python -m app.converters.json_to_db \\
      --json "app/documents/MANUAL DE CONVIVENCIA 2026.json" \\
      --name "Manual de Convivencia 2026" \\
      --cat  convivencia

  # Con todas las opciones
  python -m app.converters.json_to_db \\
      --json "app/documents/MANUAL DE CONVIVENCIA 2026.json" \\
      --pdf  "app/documents/MANUAL DE CONVIVENCIA 2026.pdf" \\
      --name "Manual de Convivencia 2026" \\
      --cat  convivencia \\
      --desc "Manual institucional 2026" \\
      --by   admin@einstein.edu \\
      --dry-run   # Solo muestra estadísticas sin guardar

USO PROGRAMÁTICO (desde FastAPI):
  from app.converters.json_to_db import import_json_to_db
  from app.database.database import SessionLocal

  db = SessionLocal()
  try:
      doc = import_json_to_db(db, json_path="...", name="...")
  finally:
      db.close()
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Inserta raíz del proyecto en sys.path para ejecución directa con -m
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy.orm import Session

# ── Usa la configuración de base de datos EXISTENTE del proyecto ──────────────
# Si tu SessionLocal está en otro módulo, ajusta solo esta línea:
from app.database.database import SessionLocal       # ← ajusta si es diferente
from app.models.document import (
    Document, DocumentCategory, DocumentChunk, DocumentStatus
)


# ─────────────────────────────────────────────────────────────────────────────
# INSPECTOR DE JSON
# Lee el JSON de pdf_to_json.py y normaliza su estructura.
# Cubre todos los formatos posibles que ese conversor puede producir.
# ─────────────────────────────────────────────────────────────────────────────

def _extract_blocks(raw: Any) -> Tuple[List[Dict], Dict]:
    """
    Extrae la lista de bloques y los metadatos del JSON.

    Formatos soportados:

    FORMATO A — Lista plana de bloques:
        [
          {"content": "...", "section": "...", ...},
          ...
        ]

    FORMATO B — Dict con clave 'blocks' o 'chunks':
        {
          "metadata": {...},
          "blocks": [...]
        }

    FORMATO C — Dict con clave 'pages':
        {
          "pages": [
            {"blocks": [...]},
            ...
          ]
        }

    FORMATO D — Lista de strings (mínimo):
        ["texto bloque 1", "texto bloque 2", ...]

    Retorna: (lista_de_bloques, metadata_dict)
    """
    metadata: Dict = {}

    # FORMATO B / D: el JSON es un dict
    if isinstance(raw, dict):
        metadata = {k: v for k, v in raw.items() if not isinstance(v, (list, dict))}

        # El Manual de Convivencia usa una estructura jerárquica:
        # {"portada": [...], "secciones": [{"titulo": ..., "contenido": [...],
        # "subsecciones": [...]}, ...]}
        # No basta con devolver raw["secciones"] porque cada sección es un
        # diccionario y el texto real está dentro de contenido/subsecciones.
        if "secciones" in raw and isinstance(raw["secciones"], list):
            flattened: List[Dict] = []

            # La portada también contiene texto útil.
            for item in raw.get("portada", []) or []:
                if isinstance(item, dict):
                    flattened.append(dict(item))
                elif isinstance(item, str) and item.strip():
                    flattened.append({"tipo": "parrafo", "texto": item.strip()})

            def walk_section(section: Any, parent_title: Optional[str] = None) -> None:
                if not isinstance(section, dict):
                    return

                title = section.get("titulo") or parent_title

                for item in section.get("contenido", []) or []:
                    if isinstance(item, dict):
                        block = dict(item)
                        if title:
                            block.setdefault("section_title", title)
                        flattened.append(block)
                    elif isinstance(item, str) and item.strip():
                        flattened.append({
                            "tipo": "parrafo",
                            "texto": item.strip(),
                            "section_title": title,
                        })

                for child in section.get("subsecciones", []) or []:
                    walk_section(child, title)

            for section in raw["secciones"]:
                walk_section(section)

            return flattened, metadata

        # Otros formatos planos conocidos.
        for key in ("blocks", "chunks", "sections", "data", "content", "items"):
            if key in raw and isinstance(raw[key], list):
                return raw[key], metadata

        # FORMATO C: páginas con bloques anidados
        if "pages" in raw and isinstance(raw["pages"], list):
            all_blocks = []
            for page in raw["pages"]:
                if isinstance(page, dict):
                    for key in ("blocks", "chunks", "content"):
                        if key in page and isinstance(page[key], list):
                            all_blocks.extend(page[key])
                            break
                elif isinstance(page, list):
                    all_blocks.extend(page)
            return all_blocks, metadata

        # Si el dict no tiene ninguna clave conocida, tratar sus valores como bloques
        lists_in_dict = [v for v in raw.values() if isinstance(v, list)]
        if len(lists_in_dict) == 1:
            return lists_in_dict[0], metadata

        raise ValueError(
            f"JSON tipo dict pero sin clave de bloques reconocida. "
            f"Claves encontradas: {list(raw.keys())}"
        )

    # FORMATO A / D: el JSON es directamente una lista
    if isinstance(raw, list):
        return raw, metadata

    raise ValueError(f"Formato JSON no reconocido. Tipo raíz: {type(raw).__name__}")


def _normalize_block(item: Any, index: int) -> Optional[Dict]:
    """
    Convierte un bloque (sea dict o string) al formato estándar interno.

    Campos que intenta extraer (con múltiples nombres posibles para compatibilidad):
      content       : texto del bloque
      section_title : título del capítulo/sección
      article_title : título del artículo
      block_type    : tipo (paragraph, table, list, title…)
      keywords      : palabras clave (lista o string)
      page_number   : número de página de origen
    """
    # FORMATO D: bloque es un string puro
    if isinstance(item, str):
        content = item.strip()
        return {
            "content":       content,
            "section_title": None,
            "article_title": None,
            "block_type":    "paragraph",
            "keywords":      None,
            "page_number":   None,
        } if content else None

    if not isinstance(item, dict):
        return None  # Tipo desconocido, ignorar

    # ── Extraer contenido (primer campo no vacío encontrado) ──────────────
    content = ""
    for field in ("content", "contenido", "text", "body", "texto", "value", "paragraph"):
        val = item.get(field, "")
        if isinstance(val, str) and val.strip():
            content = val.strip()
            break

    if not content:
        return None  # Bloque vacío, ignorar

    # ── Extraer section_title ─────────────────────────────────────────────
    section_title = None
    for field in ("section", "section_title", "seccion", "titulo_seccion",
                  "chapter", "capitulo", "heading", "titulo"):
        val = item.get(field)
        if isinstance(val, str) and val.strip():
            section_title = val.strip()[:500]
            break

    # ── Extraer article_title ─────────────────────────────────────────────
    article_title = None
    for field in ("article", "article_title", "articulo", "titulo_articulo"):
        val = item.get(field)
        if isinstance(val, str) and val.strip():
            article_title = val.strip()[:500]
            break

    # ── Extraer block_type ────────────────────────────────────────────────
    block_type = None
    for field in ("type", "block_type", "tipo", "kind"):
        val = item.get(field)
        if isinstance(val, str) and val.strip():
            block_type = val.strip()[:50]
            break
    if not block_type:
        block_type = "paragraph"

    # ── Extraer keywords ──────────────────────────────────────────────────
    keywords = None
    for field in ("keywords", "palabras_clave", "tags", "key_terms"):
        val = item.get(field)
        if val:
            if isinstance(val, list):
                keywords = ", ".join(str(k).strip() for k in val if k)
            elif isinstance(val, str) and val.strip():
                keywords = val.strip()
            break

    # ── Extraer page_number ───────────────────────────────────────────────
    page_number = None
    for field in ("page", "page_number", "pagina", "pg"):
        val = item.get(field)
        if isinstance(val, int) and val > 0:
            page_number = val
            break

    return {
        "content":       content,
        "section_title": section_title,
        "article_title": article_title,
        "block_type":    block_type,
        "keywords":      keywords,
        "page_number":   page_number,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def import_json_to_db(
    db:            Session,
    json_path:     str | Path,
    pdf_path:      Optional[str | Path] = None,
    name:          str = "",
    description:   Optional[str] = None,
    category:      DocumentCategory = DocumentCategory.GENERAL,
    uploaded_by:   Optional[str] = None,
    dry_run:       bool = False,
) -> Document:
    """
    Lee el JSON en json_path e importa Document + DocumentChunk a la DB.

    Idempotencia: si ya existe un documento con el mismo nombre,
    se eliminan el documento anterior y sus chunks antes de reimportar.

    Parámetros
    ----------
    db          : Sesión SQLAlchemy activa.
    json_path   : Ruta al JSON producido por pdf_to_json.py.
    pdf_path    : Ruta al PDF original (solo para metadata).
    name        : Nombre legible. Si está vacío usa el stem del archivo.
    description : Descripción opcional.
    category    : DocumentCategory enum.
    uploaded_by : Email del admin que dispara la importación.
    dry_run     : Si True, analiza sin guardar en la DB.

    Retorna
    -------
    Document (con status READY si no es dry_run).
    """
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {json_path}")

    # ── 1. Leer y parsear el JSON ──────────────────────────────────────────
    print(f"\n[json_to_db] Leyendo: {json_path.name}")
    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    raw_blocks, meta = _extract_blocks(raw)
    print(f"[json_to_db] Bloques crudos encontrados: {len(raw_blocks)}")

    # ── 2. Normalizar bloques ──────────────────────────────────────────────
    blocks: List[Dict] = []
    skipped = 0
    for i, item in enumerate(raw_blocks):
        norm = _normalize_block(item, i)
        if norm:
            blocks.append(norm)
        else:
            skipped += 1
            print(f"[json_to_db] ⚠ Bloque #{i} vacío o no reconocido — omitido")

    print(f"[json_to_db] Bloques válidos: {len(blocks)} | Omitidos: {skipped}")

    if not blocks:
        raise ValueError("El JSON no contiene bloques de texto válidos después de normalizar.")

    # ── 3. Estadísticas del JSON ───────────────────────────────────────────
    types_count: Dict[str, int] = {}
    for b in blocks:
        t = b.get("block_type", "unknown")
        types_count[t] = types_count.get(t, 0) + 1

    sections = {b["section_title"] for b in blocks if b.get("section_title")}
    articles = {b["article_title"] for b in blocks if b.get("article_title")}
    with_kw   = sum(1 for b in blocks if b.get("keywords"))

    print(f"[json_to_db] Tipos de bloque: {types_count}")
    print(f"[json_to_db] Secciones distintas: {len(sections)}")
    print(f"[json_to_db] Artículos distintos: {len(articles)}")
    print(f"[json_to_db] Bloques con keywords: {with_kw}")

    # ── 4. Modo dry-run ────────────────────────────────────────────────────
    doc_name = name.strip() or json_path.stem.replace("_", " ").replace("-", " ").title()

    if dry_run:
        print(f"\n[json_to_db] 🔍 DRY-RUN — se importarían:")
        print(f"  Document: '{doc_name}' (categoría: {category.value})")
        print(f"  Chunks:   {len(blocks)}")
        print("[json_to_db] DRY-RUN terminado. Sin cambios en la base de datos.")
        # Retorna objeto temporal para inspección, sin persistir
        return Document(
            name=doc_name, category=category,
            status=DocumentStatus.READY, chunk_count=len(blocks),
            original_filename=json_path.name, file_type="pdf",
        )

    # ── 5. Idempotencia: eliminar documento anterior si existe ─────────────
    existing = db.query(Document).filter(Document.name == doc_name).first()
    if existing:
        print(
            f"[json_to_db] ⚠ Ya existe '{doc_name}' (ID: {existing.id}, "
            f"{existing.chunk_count} chunks) — reemplazando…"
        )
        db.delete(existing)
        db.flush()
        print(f"[json_to_db] Documento anterior eliminado junto con sus chunks.")

    # ── 6. Crear el Document ───────────────────────────────────────────────
    pdf_path = Path(pdf_path) if pdf_path else None
    document = Document(
        name              = doc_name,
        description       = description,
        category          = category,
        original_filename = (pdf_path.name if pdf_path else json_path.stem + ".pdf"),
        file_type         = "pdf",
        source_json_path  = str(json_path),
        status            = DocumentStatus.PROCESSING,
        chunk_count       = 0,
        is_active         = True,
        uploaded_by       = uploaded_by,
    )
    db.add(document)
    db.flush()   # Obtiene document.id sin commit
    print(f"[json_to_db] Document creado con ID: {document.id}")

    # ── 7. Crear los DocumentChunk ─────────────────────────────────────────
    created = 0
    for idx, block in enumerate(blocks):
        chunk = DocumentChunk(
            document_id    = document.id,
            chunk_index    = idx,
            section_title  = block.get("section_title"),
            article_title  = block.get("article_title"),
            page_number    = block.get("page_number"),
            content        = block["content"],
            content_length = len(block["content"]),
            block_type     = block.get("block_type", "paragraph"),
            keywords       = block.get("keywords"),
        )
        db.add(chunk)
        created += 1

        # Progreso cada 50 chunks
        if (idx + 1) % 50 == 0:
            print(f"[json_to_db]   → {idx + 1}/{len(blocks)} chunks creados…")

    # ── 8. Finalizar ──────────────────────────────────────────────────────
    document.mark_ready(created)
    db.commit()
    db.refresh(document)

    print(f"\n[json_to_db] ✅ Importación completada:")
    print(f"   Documento : '{document.name}' (ID: {document.id})")
    print(f"   Categoría : {document.category.value}")
    print(f"   Chunks    : {document.chunk_count}")
    print(f"   Estado    : {document.status.value}")

    return document


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT — ejecución con: python -m app.converters.json_to_db
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Importa un JSON de pdf_to_json.py a la base de datos de Exmi.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Importar Manual de Convivencia
  python -m app.converters.json_to_db \\
      --json "app/documents/MANUAL DE CONVIVENCIA 2026.json" \\
      --pdf  "app/documents/MANUAL DE CONVIVENCIA 2026.pdf" \\
      --name "Manual de Convivencia 2026" \\
      --cat  convivencia

  # Analizar sin guardar
  python -m app.converters.json_to_db \\
      --json "app/documents/MANUAL DE CONVIVENCIA 2026.json" \\
      --name "Manual de Convivencia 2026" \\
      --dry-run
        """,
    )
    p.add_argument("--json",    required=True,  help="Ruta al archivo JSON")
    p.add_argument("--pdf",     default=None,   help="Ruta al PDF original (metadata)")
    p.add_argument("--name",    default="",     help="Nombre del documento")
    p.add_argument("--desc",    default=None,   help="Descripción (opcional)")
    p.add_argument("--cat",     default="general",
                   choices=[c.value for c in DocumentCategory],
                   help="Categoría institucional")
    p.add_argument("--by",      default=None,   help="Email del usuario que importa")
    p.add_argument("--dry-run", action="store_true",
                   help="Solo muestra estadísticas, no guarda en la base de datos")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    db: Session = SessionLocal()
    try:
        import_json_to_db(
            db          = db,
            json_path   = args.json,
            pdf_path    = args.pdf,
            name        = args.name,
            description = args.desc,
            category    = DocumentCategory(args.cat),
            uploaded_by = args.by,
            dry_run     = args.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
