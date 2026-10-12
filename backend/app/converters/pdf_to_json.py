"""
app/converters/pdf_to_json.py

Conversor de PDF a JSON para el sistema RAG del chatbot Exmi.

Este módulo lee un documento institucional del Colegio Albert Einstein en
formato PDF (por defecto, el Manual de Convivencia) y lo transforma en un
archivo JSON estructurado en bloques lógicos (títulos, capítulos, secciones
y artículos), conservando la totalidad del contenido y su estructura
jurídica interna (parágrafos, literales, numerales, incisos y viñetas),
listo para ser importado a la base de datos SQLite que alimenta el sistema
RAG.

Solo utiliza librerías locales: PyMuPDF (fitz), json, re, pathlib,
collections, dataclasses, logging y typing. No depende de APIs externas,
IA, OCR ni servicios en línea.

El módulo está pensado para reutilizarse con otros documentos
institucionales con una estructura jurídica similar (PEI, SIEE, circulares,
reglamentos), sin más cambios que indicar la ruta del PDF y, opcionalmente,
el prefijo de los identificadores de bloque.

Uso interactivo:
    python pdf_to_json.py

Uso programático (por ejemplo, desde un endpoint de FastAPI):
    from app.converters.pdf_to_json import procesar_pdf
    resultado = procesar_pdf(Path("Manual Convivencia.pdf"))
    print(resultado.ruta_json)
    print(resultado.informe.resumen_texto())
"""

from __future__ import annotations

import io
import json
import logging
import re
from collections import Counter
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


# ======================================================
# EXCEPCIONES PROPIAS
# ======================================================
# Heredan también de la excepción estándar equivalente para no romper
# código existente que capture FileNotFoundError / ValueError / OSError,
# y a la vez permitir capturas más precisas vía ErrorConversionPDF.

class ErrorConversionPDF(Exception):
    """Excepción base para errores propios del conversor PDF → JSON de Exmi."""


class PDFNoEncontradoError(ErrorConversionPDF, FileNotFoundError):
    """El archivo PDF indicado no existe en la ruta dada."""


class PDFInvalidoError(ErrorConversionPDF, ValueError):
    """La ruta no corresponde a un PDF válido, o el archivo está corrupto."""


class PDFProtegidoError(ErrorConversionPDF, ValueError):
    """El PDF está protegido con contraseña y no fue posible abrirlo."""


class PDFVacioError(ErrorConversionPDF, ValueError):
    """El PDF no contiene páginas, o no tiene texto extraíble."""


class GuardadoJSONError(ErrorConversionPDF, OSError):
    """No fue posible guardar o verificar el archivo JSON de salida."""


# ======================================================
# CONSTANTES Y EXPRESIONES REGULARES
# ======================================================

# Una línea se considera "entrada de índice / tabla de contenido" cuando
# termina en puntos suspensivos (u otro relleno) seguidos de un número de
# página, p. ej.: "OBJETIVOS.................... 8"
PATRON_ENTRADA_INDICE = re.compile(r"[.\-\s]{4,}\d{1,4}\s*$")

# Proporción mínima de líneas de una página que deben lucir como entradas
# de índice para considerar que toda la página es tabla de contenido.
UMBRAL_DENSIDAD_INDICE = 0.20
MINIMO_LINEAS_PARA_EVALUAR = 4

# Línea compuesta únicamente por un número de página (con adornos
# opcionales), p. ej.: "12", "- 12 -", "145"
PATRON_SOLO_NUMERO_PAGINA = re.compile(r"^\s*[-–—•]*\s*\d{1,4}\s*[-–—•]*\s*$")

# Línea compuesta únicamente por puntos (líneas decorativas de relleno)
PATRON_SOLO_PUNTOS = re.compile(r"^[.\s]{3,}$")

# Títulos, capítulos, secciones, anexos, apéndices y disposiciones finales.
PATRON_SECCION = re.compile(
    r"^(?P<tipo>T[ÍI]TULO|CAP[ÍI]TULO|SECCI[ÓO]N|ANEXO|AP[ÉE]NDICE|DISPOSICIONES\s+FINALES)"
    r"(?:\s+(?P<numero>[IVXLCDM]+|\d+))?"
    r"\s*[:\.\-–—]?\s*(?P<titulo_resto>.*)$",
    re.IGNORECASE,
)

# Detección robusta de artículos: "Artículo 1", "ARTÍCULO 5", "Artículo
# No. 8", "Artículo N° 9", "Artículo 10.", "Artículo 11:" y numeración
# decimal ("Artículo 4.1").
PATRON_ARTICULO = re.compile(
    r"^ART[ÍI]CULO\s*(?:N[°ºO]\.?\s*)?(?P<numero>\d+(?:\.\d+)?)"
    r"\s*(?:[°ºªO])?\s*[:\.\-–—]?\s*(?P<titulo_resto>.*)$",
    re.IGNORECASE,
)

# Subelementos jurídicos que NO inician un bloque nuevo, pero que sí son
# puntos de corte preferidos al dividir un bloque demasiado extenso.
PATRON_SUBELEMENTO = re.compile(
    r"^(PAR[ÁA]GRAFO(\s+\d+)?\b|LITERAL\s+[a-záéíóú]\)|[a-záéíóú]\)|\d+[.\)]|"
    r"INCISO(\s+\d+)?\b|[-•▪●])",
    re.IGNORECASE,
)

# Conectores gramaticales que, al final de un título detectado, indican que
# el renglón se cortó a mitad de frase (común en encabezados de Word
# exportados a PDF) y que el título continúa en la línea siguiente.
CONECTORES_TITULO_INCOMPLETO: FrozenSet[str] = frozenset(
    {
        "de", "del", "la", "el", "los", "las", "y", "o", "en", "al", "para",
        "con", "por", "a", "que", "su", "sus", "un", "una", "e", "u", "sin",
        "sobre", "the",
    }
)

LIMITE_PALABRAS_BLOQUE = 800
CANTIDAD_MAXIMA_PALABRAS_CLAVE = 6
MAXIMO_LINEAS_EXTRA_TITULO = 2  # tope de líneas adicionales al fusionar un título cortado

# Umbral de densidad multi-columna para aceptar una tabla detectada por
# PyMuPDF como "genuina" (evita falsos positivos sobre párrafos comunes).
UMBRAL_TABLA_GENUINA = 0.5

_TABLA_ACENTOS = str.maketrans("áéíóúÁÉÍÓÚñÑüÜ", "aeiouAEIOUnNuU")

PALABRAS_VACIAS_ES: FrozenSet[str] = frozenset(
    {
        "para", "con", "sus", "por", "una", "los", "las", "del", "que", "esta",
        "este", "estas", "estos", "esa", "ese", "esas", "esos", "aquel",
        "aquella", "aquellos", "aquellas", "como", "cuando", "donde", "quien",
        "quienes", "cual", "cuales", "sobre", "entre", "hasta", "desde", "hacia",
        "durante", "mediante", "respecto", "conforme", "segun", "salvo", "excepto",
        "ademas", "asimismo", "igualmente", "dentro", "fuera", "tras", "bajo",
        "cada", "debe", "deben", "podra", "podran", "cualquier", "misma", "mismo",
        "mismos", "mismas", "dicho", "dicha", "dichos", "dichas", "tal", "tales",
        "cuyo", "cuya", "cuyos", "cuyas", "todo", "toda", "todos", "todas", "otro",
        "otra", "otros", "otras", "algun", "alguna", "algunos", "algunas", "ningun",
        "ninguna", "ningunos", "ningunas", "mucho", "mucha", "muchos", "muchas",
        "poco", "poca", "pocos", "pocas", "tanto", "tanta", "tantos", "tantas",
        "solo", "sola", "solos", "solas", "mas", "menos", "muy", "tan", "asi",
        "aqui", "alli", "alla", "ahora", "antes", "despues", "luego", "siempre",
        "nunca", "tambien", "tampoco", "sino", "pero", "aunque", "porque",
        "pues", "sera", "seran", "seria", "serian", "fue", "fueron",
        "han", "hay", "habia", "habian", "hace", "hacen", "tiene", "tienen",
        "tenia", "tenian", "puede", "pueden", "podia", "podian", "debera",
        "deberan", "sido", "siendo", "estar", "estara", "estan", "estaba",
        "estaban", "cuenta", "manera", "forma", "parte", "partes", "caso",
        "casos", "presente", "presentes",
    }
)

# Términos estructurales del propio documento (etiquetas jurídicas) que no
# aportan valor como palabra clave para la recuperación en el RAG.
PALABRAS_ESTRUCTURALES: FrozenSet[str] = frozenset(
    {
        "articulo", "capitulo", "titulo", "seccion", "paragrafo", "literal",
        "inciso", "numeral", "anexo", "apendice", "disposiciones", "finales",
        "parte", "resolucion", "decreto", "ley",
    }
)


# ======================================================
# ESTRUCTURAS DE DATOS
# ======================================================

@dataclass
class Bloque:
    """
    Bloque lógico de contenido durante el procesamiento interno, antes de
    convertirse en un registro del JSON final.

    Attributes:
        titulo: Título del bloque (p. ej. "Artículo 15. Consideraciones Generales").
        contenido: Texto completo del bloque.
        tipo_marcador: Tipo de encabezado que originó el bloque ("Introducción",
            "Título", "Capítulo", "Sección", "Anexo", "Apéndice",
            "Disposiciones Finales" o "Artículo"). Es información interna
            para el informe; no se exporta como campo del JSON final.
    """

    titulo: str
    contenido: str
    tipo_marcador: str


@dataclass
class ExtraccionPDF:
    """Resultado de extraer el texto de un PDF página por página."""

    paginas: List[str]
    tablas_preservadas: int


@dataclass
class TextoLimpio:
    """Resultado de limpiar y consolidar el texto extraído de un PDF."""

    texto: str
    paginas_totales: int
    paginas_descartadas_por_indice: int


@dataclass
class InformeConversion:
    """Resumen estadístico y de calidad de una conversión PDF → JSON."""

    archivo_origen: str
    paginas_totales: int = 0
    paginas_descartadas_por_indice: int = 0
    capitulos_detectados: int = 0
    articulos_detectados: int = 0
    bloques_creados: int = 0
    bloques_divididos_por_longitud: int = 0
    tablas_preservadas: int = 0
    tamano_promedio_caracteres: float = 0.0
    promedio_palabras_por_bloque: float = 0.0
    advertencias: List[str] = field(default_factory=list)

    def resumen_texto(self) -> str:
        """Genera una representación legible del informe para consola o log."""
        lineas = [
            "===== INFORME DE CONVERSIÓN (Exmi) =====",
            f"Archivo procesado: {self.archivo_origen}",
            f"Páginas totales: {self.paginas_totales}",
            f"Páginas descartadas por ser tabla de contenido: {self.paginas_descartadas_por_indice}",
            f"Capítulos/secciones detectados: {self.capitulos_detectados}",
            f"Artículos detectados: {self.articulos_detectados}",
            f"Bloques JSON creados: {self.bloques_creados}",
            f"Bloques divididos por superar {LIMITE_PALABRAS_BLOQUE} palabras: {self.bloques_divididos_por_longitud}",
            f"Tablas/listas estructuradas preservadas en formato legible: {self.tablas_preservadas}",
            f"Tamaño promedio por bloque: {self.tamano_promedio_caracteres:.0f} caracteres",
            f"Promedio de palabras por bloque: {self.promedio_palabras_por_bloque:.1f}",
        ]
        if self.advertencias:
            lineas.append(f"Advertencias ({len(self.advertencias)}):")
            lineas.extend(f"  - {advertencia}" for advertencia in self.advertencias)
        else:
            lineas.append("Advertencias: ninguna.")
        lineas.append(
            "Nota sobre tablas: las tablas con al menos dos columnas de "
            "contenido real (p. ej. cuadros de Derechos/Deberes) se detectan "
            "con PyMuPDF y se preservan como tablas Markdown dentro de "
            "'contenido'. Los horarios y listas de una sola columna ya se "
            "extraen en orden de lectura línea por línea y no requieren este "
            "tratamiento especial."
        )
        lineas.append("==========================================")
        return "\n".join(lineas)


@dataclass
class ResultadoConversion:
    """Resultado completo de una conversión: ruta del JSON generado e informe asociado."""

    ruta_json: Path
    informe: InformeConversion


class _RecolectorAdvertencias(logging.Handler):
    """
    Handler de logging que recolecta en memoria los mensajes de nivel
    WARNING o superior emitidos durante una conversión, para incluirlos en
    el InformeConversion sin necesidad de pasar listas de advertencias
    entre funciones.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.mensajes: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.mensajes.append(record.getMessage())


# ======================================================
# UTILIDADES DE TEXTO
# ======================================================

def _sin_acentos(texto: str) -> str:
    """Devuelve el texto sin tildes ni diéresis, para comparaciones robustas."""
    return texto.translate(_TABLA_ACENTOS)


def _normalizar_marcador(texto: str) -> str:
    """Normaliza el tipo de sección detectado a su forma canónica de presentación."""
    clave = _sin_acentos(re.sub(r"\s+", " ", texto.strip().lower()))
    equivalencias = {
        "titulo": "Título",
        "capitulo": "Capítulo",
        "seccion": "Sección",
        "anexo": "Anexo",
        "apendice": "Apéndice",
        "disposiciones finales": "Disposiciones Finales",
    }
    return equivalencias.get(clave, texto.strip().title())


def _termina_en_conector(texto: str) -> bool:
    """True si el texto parece cortado a mitad de frase (termina en una
    preposición o conjunción común), señal de que el título continúa en la
    línea siguiente del PDF."""
    texto_limpio = texto.strip(" .,:;-–—")
    if not texto_limpio:
        return False
    ultima_palabra = texto_limpio.split()[-1]
    return _sin_acentos(ultima_palabra.lower()) in CONECTORES_TITULO_INCOMPLETO


def _construir_titulo(marcador: str, numero: str, resto: str, longitud_maxima: int = 110) -> str:
    """Construye el título final de un bloque a partir del tipo de marcador,
    su número y el texto descriptivo detectado, recortando con prudencia los
    títulos demasiado extensos sin alterar el contenido del bloque."""
    numero = (numero or "").strip()
    base = f"{marcador} {numero}".strip()

    resto_limpio = resto.strip(" .:-–—")
    if not resto_limpio:
        return base

    fragmento = re.split(r"[.:;]", resto_limpio, maxsplit=1)[0].strip()
    if not fragmento:
        fragmento = resto_limpio

    if len(fragmento) > longitud_maxima:
        recorte = fragmento[:longitud_maxima].rsplit(" ", 1)[0]
        fragmento = f"{recorte}..." if recorte else f"{fragmento[:longitud_maxima]}..."

    return f"{base}. {fragmento}"


def _es_pagina_de_indice(texto_pagina: str) -> bool:
    """Determina si una página completa corresponde a la tabla de contenido,
    a partir de la proporción de líneas que terminan en el patrón típico de
    una entrada de índice (relleno + número de página)."""
    lineas = [linea.strip() for linea in texto_pagina.splitlines() if linea.strip()]
    if len(lineas) < MINIMO_LINEAS_PARA_EVALUAR:
        return False
    coincidencias = sum(1 for linea in lineas if PATRON_ENTRADA_INDICE.search(linea))
    return (coincidencias / len(lineas)) >= UMBRAL_DENSIDAD_INDICE


# ======================================================
# DETECCIÓN Y PRESERVACIÓN DE TABLAS
# ======================================================
# PyMuPDF extrae el texto en modo "text" en orden de lectura por columnas,
# lo que basta para listas de una sola columna (horarios, viñetas) pero
# desordena tablas reales de dos o más columnas (p. ej. cuadros de
# Derechos/Deberes), intercalando mal las celdas. Para esos casos se
# detectan las tablas con find_tables() y se reinsertan como tabla Markdown
# en el lugar donde aparecían, en lugar de dejar el texto de celdas
# desordenado.

def _celda_vacia(valor: object) -> bool:
    return valor is None or not str(valor).strip()


def _tabla_es_genuina(filas: List[List[object]]) -> bool:
    """Filtra falsos positivos de find_tables(): un párrafo normal de una
    sola columna suele detectarse como 'tabla' de una celda por fila. Solo
    se acepta como tabla real si la mayoría de sus filas tienen contenido
    en dos o más columnas."""
    filas_con_contenido = [fila for fila in filas if any(not _celda_vacia(c) for c in fila)]
    if len(filas_con_contenido) < 2 or len(filas_con_contenido[0]) < 2:
        return False
    filas_multi_columna = sum(
        1 for fila in filas_con_contenido if sum(0 if _celda_vacia(c) else 1 for c in fila) >= 2
    )
    return (filas_multi_columna / len(filas_con_contenido)) >= UMBRAL_TABLA_GENUINA


def _bbox_contenido_en(interior: Tuple[float, float, float, float],
                        exterior: Tuple[float, float, float, float],
                        tolerancia: float = 5.0) -> bool:
    """True si el rectángulo `interior` está (casi) contenido en `exterior`."""
    ix0, iy0, ix1, iy1 = interior
    ex0, ey0, ex1, ey1 = exterior
    return (
        ix0 >= ex0 - tolerancia and iy0 >= ey0 - tolerancia
        and ix1 <= ex1 + tolerancia and iy1 <= ey1 + tolerancia
    )


def _buscar_tablas_silencioso(pagina: "fitz.Page"):
    """Invoca find_tables() suprimiendo el aviso informativo que PyMuPDF
    imprime por stdout, para no interferir con la salida de la CLI."""
    with redirect_stdout(io.StringIO()):
        return pagina.find_tables()


def _detectar_tablas_genuinas(
    pagina: "fitz.Page",
) -> List[Tuple[Tuple[float, float, float, float], List[List[object]]]]:
    """Detecta las tablas reales de una página (bbox + filas ya filtradas de
    vacíos), descartando falsos positivos y tablas anidadas duplicadas."""
    try:
        deteccion = _buscar_tablas_silencioso(pagina)
    except Exception as error:  # noqa: BLE001 - la detección de tablas nunca debe abortar la extracción
        logger.warning("No se pudo analizar tablas en una página: %s", error)
        return []

    candidatas = []
    for tabla in deteccion.tables:
        filas = [fila for fila in tabla.extract() if any(not _celda_vacia(c) for c in fila)]
        if _tabla_es_genuina(filas):
            candidatas.append((tabla.bbox, filas))

    # Descartar tablas anidadas: cuando una tabla detectada queda casi
    # totalmente contenida dentro de otra más grande, se conserva solo la
    # de mayor área (evita fragmentos duplicados del mismo cuadro).
    candidatas.sort(key=lambda item: (item[0][2] - item[0][0]) * (item[0][3] - item[0][1]), reverse=True)
    finales: List[Tuple[Tuple[float, float, float, float], List[List[object]]]] = []
    for bbox, filas in candidatas:
        if any(_bbox_contenido_en(bbox, otro_bbox) for otro_bbox, _ in finales):
            continue
        finales.append((bbox, filas))

    finales.sort(key=lambda item: item[0][1])  # orden de lectura: de arriba a abajo
    return finales


def _celda_a_markdown(valor: object) -> str:
    if valor is None:
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip().replace("|", "/")


def _tabla_a_markdown(filas: List[List[object]]) -> str:
    """Convierte las filas extraídas de una tabla en una tabla Markdown
    legible, usando la primera fila como encabezado."""
    encabezado = [_celda_a_markdown(c) for c in filas[0]]
    lineas = ["| " + " | ".join(encabezado) + " |", "|" + "|".join(["---"] * len(encabezado)) + "|"]
    for fila in filas[1:]:
        lineas.append("| " + " | ".join(_celda_a_markdown(c) for c in fila) + " |")
    return "\n".join(lineas)


def _bloque_de_texto_en_tabla(
    bbox_bloque: Tuple[float, float, float, float],
    bbox_tabla: Tuple[float, float, float, float],
    tolerancia: float = 3.0,
) -> bool:
    """True si el centro del bloque de texto cae dentro del área de la tabla."""
    x0, y0, x1, y1 = bbox_bloque
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    tx0, ty0, tx1, ty1 = bbox_tabla
    return (tx0 - tolerancia <= cx <= tx1 + tolerancia) and (ty0 - tolerancia <= cy <= ty1 + tolerancia)


def _extraer_texto_pagina(pagina: "fitz.Page") -> Tuple[str, int]:
    """
    Extrae el texto de una página. Si la página no contiene tablas
    genuinas, se usa la extracción de texto plano estándar (idéntica al
    comportamiento original). Si contiene una o más tablas reales, estas se
    reinsertan en su posición como tablas Markdown y el resto de la página
    se extrae normalmente alrededor de ellas.

    Returns:
        Tupla (texto_pagina, cantidad_de_tablas_preservadas).
    """
    tablas = _detectar_tablas_genuinas(pagina)
    if not tablas:
        return pagina.get_text("text"), 0

    bloques = sorted(pagina.get_text("blocks"), key=lambda b: (round(b[1], 1), round(b[0], 1)))
    partes: List[str] = []
    tablas_emitidas: Set[int] = set()

    for bloque in bloques:
        bbox_bloque = bloque[:4]
        texto_bloque = bloque[4]

        indice_tabla = next(
            (i for i, (bbox_tabla, _filas) in enumerate(tablas) if _bloque_de_texto_en_tabla(bbox_bloque, bbox_tabla)),
            None,
        )
        if indice_tabla is None:
            partes.append(texto_bloque.rstrip("\n"))
            continue
        if indice_tabla not in tablas_emitidas:
            partes.append(_tabla_a_markdown(tablas[indice_tabla][1]))
            tablas_emitidas.add(indice_tabla)

    return "\n".join(partes), len(tablas_emitidas)


# ======================================================
# FUNCIÓN 1: EXTRAER TEXTO DEL PDF
# ======================================================

def extraer_texto_pdf(ruta_pdf: Path) -> ExtraccionPDF:
    """
    Extrae el texto de todas las páginas de un PDF, en su orden original,
    usando PyMuPDF (fitz). Las tablas genuinas de dos o más columnas se
    preservan como tablas Markdown legibles (ver _extraer_texto_pagina).

    Args:
        ruta_pdf: Ruta al archivo PDF de origen.

    Returns:
        ExtraccionPDF con el texto por página y la cantidad de tablas
        preservadas en toda la extracción.

    Raises:
        PDFNoEncontradoError: si el archivo no existe en la ruta indicada.
        PDFInvalidoError: si la ruta no es un PDF, o el archivo está corrupto.
        PDFProtegidoError: si el PDF está protegido con contraseña.
        PDFVacioError: si el PDF no tiene páginas o texto extraíble.
    """
    if not ruta_pdf.exists():
        raise PDFNoEncontradoError(f"El archivo no existe: {ruta_pdf}")
    if not ruta_pdf.is_file():
        raise PDFInvalidoError(f"La ruta indicada no corresponde a un archivo: {ruta_pdf}")
    if ruta_pdf.suffix.lower() != ".pdf":
        raise PDFInvalidoError(f"La ruta indicada no corresponde a un archivo PDF: {ruta_pdf}")

    try:
        documento = fitz.open(ruta_pdf)
    except Exception as error:  # noqa: BLE001 - se traduce a un error propio y claro
        raise PDFInvalidoError(f"No se pudo abrir el PDF (posiblemente esté corrupto): {error}") from error

    try:
        if documento.is_encrypted and not documento.authenticate(""):
            raise PDFProtegidoError("El PDF está protegido con contraseña y no fue posible abrirlo.")

        if documento.page_count == 0:
            raise PDFVacioError("El PDF no contiene páginas (archivo vacío).")

        paginas_texto: List[str] = []
        tablas_preservadas = 0
        for pagina in documento:
            texto_pagina, tablas_en_pagina = _extraer_texto_pagina(pagina)
            paginas_texto.append(texto_pagina)
            tablas_preservadas += tablas_en_pagina
    finally:
        documento.close()

    if not any(texto.strip() for texto in paginas_texto):
        raise PDFVacioError(
            "El PDF no contiene texto extraíble. Puede tratarse de un documento "
            "escaneado sin capa de texto (esta herramienta no realiza OCR)."
        )

    return ExtraccionPDF(paginas=paginas_texto, tablas_preservadas=tablas_preservadas)


# ======================================================
# FUNCIÓN 2: LIMPIAR TEXTO
# ======================================================

def _normalizar_linea_comparacion(linea: str) -> str:
    """Normaliza una línea (mayúsculas, dígitos genéricos) para comparar encabezados/pies repetidos."""
    return re.sub(r"\d+", "#", linea.strip().upper())


def _detectar_encabezados_pies(paginas: List[str], zona: int = 3, umbral: float = 0.4) -> Set[str]:
    """Detecta líneas que se repiten sistemáticamente al inicio o al final de
    muchas páginas (encabezados y pies de página institucionales)."""
    total_paginas = len(paginas)
    if total_paginas == 0:
        return set()

    contador: Counter = Counter()
    for texto_pagina in paginas:
        lineas = [linea for linea in texto_pagina.splitlines() if linea.strip()]
        zona_revisar = lineas[:zona] + lineas[-zona:]
        vistas_en_pagina: Set[str] = set()
        for linea in zona_revisar:
            normalizada = _normalizar_linea_comparacion(linea)
            if normalizada and normalizada not in vistas_en_pagina:
                contador[normalizada] += 1
                vistas_en_pagina.add(normalizada)

    minimo_paginas = max(3, int(total_paginas * umbral))
    return {linea for linea, veces in contador.items() if veces >= minimo_paginas}


def _limpiar_caracteres_extranos(texto: str) -> str:
    """Elimina caracteres de control y símbolos no imprimibles (p. ej. glifos
    de fuentes decorativas tipo Wingdings mal codificados), conservando
    letras, tildes, ñ y la puntuación propia de un texto jurídico en español."""
    texto = texto.replace("\xa0", " ").replace("\x0c", " ")
    texto = re.sub(r"[^\w\sÁÉÍÓÚÑÜáéíóúñü.,;:()°ºª\-\/%\"'¿?¡!|]", "", texto)
    return texto.strip()


def limpiar_texto(paginas: List[str]) -> TextoLimpio:
    """
    Limpia el texto extraído del PDF, eliminando ruido sin perder contenido
    útil: descarta por completo las páginas de tabla de contenido (índice),
    y dentro de las páginas restantes elimina números de página aislados,
    líneas de puntos decorativas, encabezados/pies repetidos y caracteres
    extraños, colapsando espacios y líneas vacías.

    Args:
        paginas: Lista de textos por página, tal como los devuelve
            extraer_texto_pdf().paginas.

    Returns:
        TextoLimpio con el texto consolidado y estadísticas de páginas
        descartadas por pertenecer al índice.
    """
    paginas_utiles = [pagina for pagina in paginas if not _es_pagina_de_indice(pagina)]
    descartadas = len(paginas) - len(paginas_utiles)

    patrones_repetidos = _detectar_encabezados_pies(paginas_utiles)

    lineas_limpias: List[str] = []
    for texto_pagina in paginas_utiles:
        for linea in texto_pagina.splitlines():
            contenido = linea.strip()
            if not contenido:
                continue
            if _normalizar_linea_comparacion(contenido) in patrones_repetidos:
                continue
            if PATRON_SOLO_NUMERO_PAGINA.match(contenido):
                continue
            if PATRON_SOLO_PUNTOS.match(contenido):
                continue

            contenido = _limpiar_caracteres_extranos(contenido)
            contenido = re.sub(r"[ \t]{2,}", " ", contenido).strip()
            if contenido:
                lineas_limpias.append(contenido)

    return TextoLimpio(
        texto="\n".join(lineas_limpias),
        paginas_totales=len(paginas),
        paginas_descartadas_por_indice=descartadas,
    )


# ======================================================
# FUNCIÓN 3: DETECTAR BLOQUES (capítulos, secciones y artículos)
# ======================================================

def _coincidencia_de_marcador(linea: str):
    """Devuelve (marcador, numero, resto) si la línea inicia un capítulo,
    título, sección, anexo, apéndice, disposiciones finales o artículo; de
    lo contrario, devuelve None."""
    coincidencia_seccion = PATRON_SECCION.match(linea)
    if coincidencia_seccion:
        marcador = _normalizar_marcador(coincidencia_seccion.group("tipo"))
        numero = coincidencia_seccion.group("numero") or ""
        resto = (coincidencia_seccion.group("titulo_resto") or "").strip()
        return marcador, numero, resto

    coincidencia_articulo = PATRON_ARTICULO.match(linea)
    if coincidencia_articulo:
        numero = coincidencia_articulo.group("numero")
        resto = (coincidencia_articulo.group("titulo_resto") or "").strip()
        return "Artículo", numero, resto

    return None


def _fusionar_encabezado(lineas: List[str], indice: int, resto: str) -> Tuple[str, List[str], int]:
    """
    Completa el título de un bloque cuando el renglón detectado no trae su
    texto descriptivo completo en la misma línea (frecuente al exportar
    Word a PDF). Primero intenta tomar la línea siguiente completa si el
    marcador llegó sin ningún texto; luego, si el resultado aún parece
    cortado a mitad de frase (termina en una preposición o conjunción),
    intenta completar hasta MAXIMO_LINEAS_EXTRA_TITULO líneas más. Nunca
    avanza sobre una línea que sea, a su vez, un nuevo marcador o una
    entrada de índice.

    Returns:
        Tupla (resto_completo, lineas_de_encabezado_consumidas, avance).
    """
    total_lineas = len(lineas)
    linea_inicial = lineas[indice]
    lineas_encabezado = [linea_inicial]
    avance = 1

    def _es_linea_utilizable(candidata: str) -> bool:
        return not (
            PATRON_ENTRADA_INDICE.search(candidata)
            or _coincidencia_de_marcador(candidata) is not None
        )

    if not resto and indice + 1 < total_lineas:
        siguiente = lineas[indice + 1]
        if PATRON_ENTRADA_INDICE.search(siguiente):
            # El encabezado y la línea siguiente son, en conjunto, una
            # entrada de índice de dos líneas: se señaliza con avance=2 y
            # resto vacío para que el llamador la descarte por completo.
            return "", lineas_encabezado, 2
        if _es_linea_utilizable(siguiente):
            resto = siguiente
            lineas_encabezado.append(siguiente)
            avance = 2

    intentos = 0
    indice_prueba = indice + avance
    while intentos < MAXIMO_LINEAS_EXTRA_TITULO and indice_prueba < total_lineas and _termina_en_conector(resto):
        candidata = lineas[indice_prueba]
        if not _es_linea_utilizable(candidata):
            break
        resto = f"{resto} {candidata}".strip()
        lineas_encabezado.append(candidata)
        avance += 1
        indice_prueba += 1
        intentos += 1

    return resto, lineas_encabezado, avance


def detectar_bloques(texto: str) -> List[Bloque]:
    """
    Detecta títulos, capítulos, secciones, anexos, apéndices, disposiciones
    finales y artículos dentro del texto limpio, organizándolos en bloques
    lógicos independientes. Los elementos internos de un artículo o
    capítulo (parágrafos, literales, numerales, incisos y viñetas)
    permanecen siempre dentro del mismo bloque, en su orden original, y
    nunca inician uno nuevo ni se mueven a otro bloque.

    Args:
        texto: Texto limpio devuelto por limpiar_texto().texto.

    Returns:
        Lista de bloques (Bloque), en el orden exacto del documento.
    """
    lineas = [linea.strip() for linea in texto.split("\n") if linea.strip()]
    bloques: List[Bloque] = []

    titulo_actual: Optional[str] = None
    tipo_actual: str = "Introducción"
    contenido_actual: List[str] = []

    indice = 0
    total_lineas = len(lineas)

    while indice < total_lineas:
        linea = lineas[indice]

        if PATRON_ENTRADA_INDICE.search(linea):
            # Salvaguarda adicional ante una entrada de índice que haya
            # sobrevivido a limpiar_texto().
            indice += 1
            continue

        coincidencia = _coincidencia_de_marcador(linea)
        if coincidencia is not None:
            marcador, numero, resto = coincidencia
            resto_completo, lineas_encabezado, avance = _fusionar_encabezado(lineas, indice, resto)

            if avance == 2 and not resto_completo and len(lineas_encabezado) == 1:
                # Entrada de índice de dos líneas detectada en _fusionar_encabezado: se descarta.
                indice += 2
                continue

            if titulo_actual is not None and contenido_actual:
                bloques.append(
                    Bloque(titulo=titulo_actual, contenido="\n".join(contenido_actual).strip(), tipo_marcador=tipo_actual)
                )

            titulo_actual = _construir_titulo(marcador, numero, resto_completo)
            tipo_actual = marcador
            contenido_actual = lineas_encabezado
            indice += avance
            continue

        # Línea de contenido normal: incluye parágrafos, literales,
        # numerales, incisos, viñetas y filas de tablas Markdown, que deben
        # permanecer en el bloque del artículo o capítulo al que pertenecen.
        if titulo_actual is None:
            titulo_actual = "Introducción"
            tipo_actual = "Introducción"
            contenido_actual = [linea]
        else:
            contenido_actual.append(linea)
        indice += 1

    if titulo_actual is not None and contenido_actual:
        bloques.append(Bloque(titulo=titulo_actual, contenido="\n".join(contenido_actual).strip(), tipo_marcador=tipo_actual))

    return bloques


# ======================================================
# FUNCIÓN 4: DIVIDIR BLOQUES MUY GRANDES
# ======================================================

def _dividir_por_subelementos(lineas: List[str], limite_palabras: int) -> List[List[str]]:
    """Divide una lista de líneas cortando únicamente al inicio de un
    subelemento jurídico (parágrafo, literal, numeral, inciso o viñeta),
    para no partir uno de estos elementos por la mitad."""
    partes: List[List[str]] = []
    parte_actual: List[str] = []
    conteo_palabras = 0

    for linea in lineas:
        if conteo_palabras >= limite_palabras and parte_actual and PATRON_SUBELEMENTO.match(linea):
            partes.append(parte_actual)
            parte_actual = []
            conteo_palabras = 0
        parte_actual.append(linea)
        conteo_palabras += len(linea.split())

    if parte_actual:
        partes.append(parte_actual)
    return partes


def _dividir_forzado_por_palabras(lineas: List[str], limite_palabras: int) -> List[List[str]]:
    """Divide por conteo de palabras cuando el bloque no tiene subelementos
    jurídicos detectables. Nunca corta el contenido de una línea, solo entre líneas."""
    partes: List[List[str]] = []
    parte_actual: List[str] = []
    conteo = 0
    for linea in lineas:
        palabras_linea = len(linea.split())
        if conteo + palabras_linea > limite_palabras and parte_actual:
            partes.append(parte_actual)
            parte_actual = []
            conteo = 0
        parte_actual.append(linea)
        conteo += palabras_linea
    if parte_actual:
        partes.append(parte_actual)
    return partes


def dividir_bloques_largos(bloques: List[Bloque], limite_palabras: int = LIMITE_PALABRAS_BLOQUE) -> List[Bloque]:
    """
    Divide automáticamente los bloques cuyo contenido supera el límite de
    palabras indicado, sin resumir ni eliminar información. La división
    prioriza los límites naturales de parágrafos, literales, numerales,
    incisos y viñetas; solo si el bloque no contiene ninguno de estos
    puntos de corte se recurre a una división forzada por conteo de
    palabras. Verifica, para cada bloque dividido, que no se haya perdido
    ni una palabra del contenido original.

    Args:
        bloques: Lista de bloques detectados por detectar_bloques().
        limite_palabras: Cantidad aproximada de palabras a partir de la
            cual un bloque se considera "muy grande".

    Returns:
        Lista de bloques, con los bloques grandes divididos en
        "(Parte 1)", "(Parte 2)", etc.
    """
    resultado: List[Bloque] = []

    for bloque in bloques:
        palabras_originales = bloque.contenido.split()
        if len(palabras_originales) <= limite_palabras:
            resultado.append(bloque)
            continue

        lineas = bloque.contenido.split("\n")
        partes_lineas = _dividir_por_subelementos(lineas, limite_palabras)
        if len(partes_lineas) == 1:
            partes_lineas = _dividir_forzado_por_palabras(lineas, limite_palabras)

        palabras_resultantes = sum(len(" ".join(parte).split()) for parte in partes_lineas)
        if palabras_resultantes != len(palabras_originales):
            logger.warning(
                "Posible pérdida de texto al dividir el bloque '%s': %d palabras originales vs %d en las partes generadas.",
                bloque.titulo, len(palabras_originales), palabras_resultantes,
            )

        total_partes = len(partes_lineas)
        for indice_parte, lineas_parte in enumerate(partes_lineas, start=1):
            titulo_parte = f"{bloque.titulo} (Parte {indice_parte})" if total_partes > 1 else bloque.titulo
            resultado.append(
                Bloque(titulo=titulo_parte, contenido="\n".join(lineas_parte).strip(), tipo_marcador=bloque.tipo_marcador)
            )

    return resultado


# ======================================================
# FUNCIÓN 5: EXTRAER PALABRAS CLAVE
# ======================================================

def extraer_palabras_clave(titulo: str, contenido: str, cantidad_maxima: int = CANTIDAD_MAXIMA_PALABRAS_CLAVE) -> List[str]:
    """
    Extrae automáticamente las palabras clave más representativas de un
    bloque, a partir de la frecuencia de términos relevantes en su título y
    contenido, excluyendo palabras vacías del español y términos
    estructurales del documento. Las palabras presentes en el título
    reciben un mayor peso, ya que suelen resumir mejor el tema del bloque.

    Args:
        titulo: Título del bloque.
        contenido: Contenido completo del bloque.
        cantidad_maxima: Número máximo de palabras clave a devolver.

    Returns:
        Lista de palabras clave (con tildes), ordenadas de mayor a menor relevancia.
    """
    patron_palabra = re.compile(r"[a-zA-ZÁÉÍÓÚÑÜáéíóúñü]{4,}")
    conteo: Counter = Counter()

    for token in patron_palabra.findall(contenido.lower()):
        clave = _sin_acentos(token)
        if clave not in PALABRAS_VACIAS_ES and clave not in PALABRAS_ESTRUCTURALES:
            conteo[token] += 1

    for token in patron_palabra.findall(titulo.lower()):
        clave = _sin_acentos(token)
        if clave not in PALABRAS_VACIAS_ES and clave not in PALABRAS_ESTRUCTURALES:
            conteo[token] += 3  # impulso para palabras presentes en el título

    palabras_clave: List[str] = []
    vistas: Set[str] = set()
    for palabra, _frecuencia in conteo.most_common(cantidad_maxima * 3):
        clave = _sin_acentos(palabra)
        if clave in vistas:
            continue
        vistas.add(clave)
        palabras_clave.append(palabra)
        if len(palabras_clave) >= cantidad_maxima:
            break

    return palabras_clave


# ======================================================
# VALIDACIÓN DEL RESULTADO
# ======================================================

def _contar_marcadores_en_texto(texto: str) -> Tuple[int, int]:
    """Cuenta, de forma independiente al ensamblado de bloques, cuántas
    líneas del texto limpio inician con un marcador de sección o de
    artículo. Sirve como verificación cruzada de cobertura frente a los
    bloques realmente creados por detectar_bloques()."""
    lineas = [linea.strip() for linea in texto.split("\n") if linea.strip()]
    secciones = 0
    articulos = 0
    for linea in lineas:
        if PATRON_ENTRADA_INDICE.search(linea):
            continue
        coincidencia = _coincidencia_de_marcador(linea)
        if coincidencia is None:
            continue
        marcador = coincidencia[0]
        if marcador == "Artículo":
            articulos += 1
        else:
            secciones += 1
    return secciones, articulos


def validar_bloques(bloques: List[Bloque], texto_limpio: str) -> Dict[str, int]:
    """
    Valida el resultado de la conversión y registra advertencias (vía
    logging.warning, recolectadas para el informe final) ante cualquier
    problema de calidad: bloques vacíos, duplicados, bloques con
    prácticamente solo el título, posibles fugas de la tabla de contenido,
    y discrepancias de cobertura frente a un reconteo independiente de
    marcadores en el texto.

    Args:
        bloques: Lista final de bloques (ya divididos por longitud).
        texto_limpio: Texto limpio usado por detectar_bloques(), para el
            reconteo independiente de cobertura.

    Returns:
        Diccionario con el conteo de cada tipo de problema encontrado.
    """
    problemas = {"vacios": 0, "duplicados": 0, "solo_titulo": 0, "posible_fuga_indice": 0}
    vistos: Set[Tuple[str, str]] = set()

    for bloque in bloques:
        if not bloque.contenido.strip():
            problemas["vacios"] += 1
            logger.warning("Bloque vacío detectado: '%s'.", bloque.titulo)
            continue

        clave = (bloque.titulo, bloque.contenido)
        if clave in vistos:
            problemas["duplicados"] += 1
            logger.warning("Bloque duplicado detectado: '%s'.", bloque.titulo)
        vistos.add(clave)

        if len(bloque.contenido.split()) <= 4:
            problemas["solo_titulo"] += 1
            logger.warning("Bloque con contenido mínimo (posible bloque de solo título): '%s'.", bloque.titulo)

        if PATRON_ENTRADA_INDICE.search(bloque.contenido):
            problemas["posible_fuga_indice"] += 1
            logger.warning("Posible fuga de la tabla de contenido dentro de un bloque: '%s'.", bloque.titulo)

    secciones_esperadas, articulos_esperados = _contar_marcadores_en_texto(texto_limpio)
    secciones_detectadas = sum(1 for b in bloques if b.tipo_marcador not in ("Introducción", "Artículo") and "(Parte" not in b.titulo)
    articulos_detectados = sum(1 for b in bloques if b.tipo_marcador == "Artículo" and "(Parte" not in b.titulo)

    if secciones_detectadas != secciones_esperadas:
        logger.warning(
            "Discrepancia en la cobertura de capítulos/secciones: %d esperados según el texto, %d bloques creados.",
            secciones_esperadas, secciones_detectadas,
        )
    if articulos_detectados != articulos_esperados:
        logger.warning(
            "Discrepancia en la cobertura de artículos: %d esperados según el texto, %d bloques creados.",
            articulos_esperados, articulos_detectados,
        )

    return problemas


# ======================================================
# FUNCIÓN 6: GUARDAR JSON
# ======================================================

def guardar_json(bloques: List[Dict[str, object]], ruta_salida: Path) -> None:
    """
    Guarda la lista de bloques en un archivo JSON codificado en UTF-8,
    preservando tildes y caracteres especiales sin escapar, y verifica
    inmediatamente que el archivo resultante pueda releerse con
    json.load() sin errores.

    Args:
        bloques: Lista de bloques ya en su forma final de diccionario
            (id, orden, categoria, titulo, palabras_clave, contenido).
        ruta_salida: Ruta donde se guardará el archivo JSON resultante.

    Raises:
        GuardadoJSONError: si no se puede escribir el archivo, o si el
            archivo escrito no puede releerse correctamente.
    """
    try:
        with ruta_salida.open("w", encoding="utf-8") as archivo:
            json.dump(bloques, archivo, ensure_ascii=False, indent=4)
    except PermissionError as error:
        raise GuardadoJSONError(f"Permisos insuficientes para guardar el archivo JSON en '{ruta_salida}': {error}") from error
    except OSError as error:
        raise GuardadoJSONError(f"No se pudo guardar el archivo JSON en '{ruta_salida}': {error}") from error

    try:
        with ruta_salida.open("r", encoding="utf-8") as archivo:
            bloques_releidos = json.load(archivo)
    except (OSError, json.JSONDecodeError) as error:
        raise GuardadoJSONError(
            f"El archivo JSON se guardó en '{ruta_salida}' pero no pudo releerse correctamente: {error}"
        ) from error

    if len(bloques_releidos) != len(bloques):
        raise GuardadoJSONError(
            f"El archivo JSON guardado en '{ruta_salida}' tiene {len(bloques_releidos)} bloques, "
            f"pero se esperaban {len(bloques)}."
        )


# ======================================================
# ORQUESTACIÓN DEL FLUJO COMPLETO
# ======================================================

def _bloque_a_diccionario(bloque: Bloque, indice: int, prefijo_id: str) -> Dict[str, object]:
    """Convierte un Bloque interno en el diccionario final que se guarda en
    el JSON, con el orden de campos id/orden/categoria/titulo/palabras_clave/contenido."""
    return {
        "id": f"{prefijo_id}_{indice:04d}",
        "orden": indice,
        "categoria": "MANUAL",
        "titulo": bloque.titulo,
        "palabras_clave": extraer_palabras_clave(bloque.titulo, bloque.contenido),
        "contenido": bloque.contenido,
    }


def procesar_pdf(ruta_pdf: Path, ruta_salida: Optional[Path] = None, prefijo_id: str = "manual") -> ResultadoConversion:
    """
    Ejecuta el flujo completo de conversión de un PDF institucional a un
    archivo JSON estructurado para el sistema RAG del chatbot Exmi:
    extracción de texto (con preservación de tablas), limpieza, detección
    de bloques, división de bloques extensos, extracción de palabras
    clave, validación de calidad, guardado del JSON y generación de un
    informe final.

    Esta función puede invocarse tanto desde la línea de comandos (ver
    main()) como de forma programática desde otros módulos del backend
    —por ejemplo, un endpoint de FastAPI— sin depender de la entrada
    estándar. Al no asumir un formato fijo de artículos más allá de las
    expresiones regulares genéricas ya soportadas, puede reutilizarse para
    otros documentos institucionales (PEI, SIEE, circulares, reglamentos)
    solo cambiando la ruta del PDF y, si se desea, el prefijo de los ids.

    Args:
        ruta_pdf: Ruta al archivo PDF de origen.
        ruta_salida: Ruta donde guardar el JSON resultante. Si no se
            indica, se usa el mismo nombre del PDF con extensión .json, en
            la misma carpeta.
        prefijo_id: Prefijo para los identificadores únicos de cada bloque
            (p. ej. "manual" produce "manual_0001").

    Returns:
        ResultadoConversion con la ruta del JSON generado y el informe de
        la conversión.
    """
    recolector = _RecolectorAdvertencias()
    logger.addHandler(recolector)
    try:
        logger.info("Leyendo PDF...")
        logger.info("Extrayendo texto...")
        extraccion = extraer_texto_pdf(ruta_pdf)

        logger.info("Limpiando texto...")
        texto_limpio = limpiar_texto(extraccion.paginas)

        logger.info("Detectando capítulos...")
        logger.info("Detectando artículos...")
        logger.info("Creando bloques...")
        bloques_crudos = detectar_bloques(texto_limpio.texto)
        bloques = dividir_bloques_largos(bloques_crudos)

        logger.info("Extrayendo palabras clave...")
        bloques_finales = [_bloque_a_diccionario(bloque, indice, prefijo_id) for indice, bloque in enumerate(bloques, start=1)]

        logger.info("Validando resultado...")
        validar_bloques(bloques, texto_limpio.texto)

        logger.info("Guardando JSON...")
        if ruta_salida is None:
            ruta_salida = ruta_pdf.with_suffix(".json")
        guardar_json(bloques_finales, ruta_salida)

        capitulos_detectados = sum(1 for b in bloques_crudos if b.tipo_marcador not in ("Introducción", "Artículo"))
        articulos_detectados = sum(1 for b in bloques_crudos if b.tipo_marcador == "Artículo")
        divididos_por_longitud = sum(1 for b in bloques if "(Parte" in b.titulo)
        tamanos = [len(b["contenido"]) for b in bloques_finales]
        palabras = [len(b["contenido"].split()) for b in bloques_finales]

        informe = InformeConversion(
            archivo_origen=str(ruta_pdf),
            paginas_totales=texto_limpio.paginas_totales,
            paginas_descartadas_por_indice=texto_limpio.paginas_descartadas_por_indice,
            capitulos_detectados=capitulos_detectados,
            articulos_detectados=articulos_detectados,
            bloques_creados=len(bloques_finales),
            bloques_divididos_por_longitud=divididos_por_longitud,
            tablas_preservadas=extraccion.tablas_preservadas,
            tamano_promedio_caracteres=(sum(tamanos) / len(tamanos)) if tamanos else 0.0,
            promedio_palabras_por_bloque=(sum(palabras) / len(palabras)) if palabras else 0.0,
            advertencias=list(recolector.mensajes),
        )
    finally:
        logger.removeHandler(recolector)

    logger.info("Proceso finalizado correctamente.")
    return ResultadoConversion(ruta_json=ruta_salida, informe=informe)


# ======================================================
# FUNCIÓN 7: PUNTO DE ENTRADA (CLI)
# ======================================================

class _FormateadorSimple(logging.Formatter):
    """Formateador de consola: los mensajes INFO se muestran tal cual (para
    conservar el flujo de estados original de la herramienta); WARNING y
    ERROR se marcan con un prefijo para distinguirlos con claridad."""

    def format(self, record: logging.LogRecord) -> str:
        mensaje = record.getMessage()
        if record.levelno >= logging.WARNING:
            return f"[{record.levelname}] {mensaje}"
        return mensaje


def _configurar_logging_cli() -> None:
    """Configura logging para uso interactivo por consola. Solo se invoca
    desde main(); al importar este módulo como librería no se modifica la
    configuración de logging de la aplicación anfitriona."""
    manejador = logging.StreamHandler()
    manejador.setFormatter(_FormateadorSimple())
    logging.basicConfig(level=logging.INFO, handlers=[manejador])


def main() -> None:
    """Punto de entrada de línea de comandos del conversor PDF → JSON para Exmi."""
    _configurar_logging_cli()

    print("-" * 38)
    print("Conversor PDF → JSON para Exmi")
    print("-" * 38)
    print()

    ruta_texto = input("Ruta completa del PDF: ").strip().strip('"').strip("'")
    ruta_pdf = Path(ruta_texto)

    print()
    try:
        resultado = procesar_pdf(ruta_pdf)
    except ErrorConversionPDF as error:
        logger.error(str(error))
        return
    except Exception as error:  # noqa: BLE001 - último recurso para no exponer trazas al usuario
        logger.error("Error inesperado durante el procesamiento: %s", error)
        return

    print()
    print(f"Archivo guardado en: {resultado.ruta_json}")
    print()
    print(resultado.informe.resumen_texto())


if __name__ == "__main__":
    main()
