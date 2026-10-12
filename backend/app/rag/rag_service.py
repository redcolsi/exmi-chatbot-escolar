"""
RAG (Retrieval-Augmented Generation) Service.
Busca información institucional relevante en la BD y construye
el contexto que se pasará a Gemini para generar la respuesta.
"""
import re
import unicodedata
from typing import List, Tuple
from sqlalchemy.orm import Session

from app.models.models import KnowledgeBase, Docente, Horario, Contacto
from app.models.document import DocumentChunk


class RAGService:
    # Palabras vacías en español que no aportan al filtrado
    STOPWORDS = {
        'el','la','los','las','un','una','y','o','de','en','que','a','del','al',
        'es','se','con','por','para','como','su','sus','no','si','me','te','le',
        'nos','hay','ser','han','tiene','son','esta','esto','mas','pero','muy',
        'ya','todo','sin','sobre','tambien','mi','tu','cual','que','donde','como',
        'cuando','quien','este','ese','esa','esos','esas','uno','dos','tres','ha',
        'lo','les','fue','nos','les','fue','cual','cuales','pues','bien','vez',
    }

    # Palabras numéricas → grado
    GRADO_PALABRAS = {
        'sexto': '6°', 'septimo': '7°', 'octavo': '8°',
        'noveno': '9°', 'decimo': '10°', 'once': '11°', 'undecimo': '11°',
    }

    # Palabras que activan la búsqueda de contactos aunque no haya keywords
    CONTACTO_TRIGGERS = {
        'contacto','telefono','correo','llamar','secretaria','rector','rectora',
        'directivo','directora','director','orientador','emergencia','comunicar',
    }

    # ──────────────────────────────────────────────────────────
    #  Utilidades de texto
    # ──────────────────────────────────────────────────────────

    def normalize(self, text: str) -> str:
        """Minúsculas y sin tildes."""
        if not text:
            return ""
        nfd = unicodedata.normalize("NFD", text.lower())
        return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

    def keywords(self, text: str) -> List[str]:
        """Extrae palabras significativas de la consulta."""
        norm = self.normalize(text)
        words = re.findall(r"\b[a-z]{3,}\b", norm)
        return [w for w in words if w not in self.STOPWORDS]

    def score(self, text: str, kws: List[str]) -> int:
        """Cuenta cuántos keywords aparecen en el texto."""
        if not text or not kws:
            return 0
        norm = self.normalize(text)
        return sum(1 for k in kws if k in norm)

    def detect_grade(self, query: str) -> List[str]:
        """Detecta grados mencionados en la consulta (ej: 10°, noveno)."""
        q = self.normalize(query)
        grades = []
        for match in re.finditer(r"\b(\d{1,2})[°o]?\b", q):
            n = int(match.group(1))
            if 6 <= n <= 11:
                grades.append(f"{n}°")
        for word, grade in self.GRADO_PALABRAS.items():
            if word in q:
                grades.append(grade)
        return list(set(grades))

    # ──────────────────────────────────────────────────────────
    #  Construcción del contexto
    # ──────────────────────────────────────────────────────────

    def build_context(self, query: str, db: Session) -> Tuple[str, List[str]]:
        """Recupera SOLO los datos pertinentes para la pregunta.

        El Manual de Convivencia se trata como fuente documental prioritaria cuando
        la consulta es normativa. Se limita el contexto para que Gemini no reciba
        el manual completo.
        """
        kws = self.keywords(query)
        q_norm = self.normalize(query)
        parts: List[str] = []
        sources: List[str] = []

        # Para convivencia, el Manual va primero y se limita a 4 chunks.
        convivencia_terms = {
            'convivencia','falta','faltas','sancion','sanciones','deber','deberes',
            'derecho','derechos','uniforme','celular','copiar','copia','academico',
            'bimestral','evaluacion','sexual','sexuales','bullying','acoso','disciplina',
            'manual','comportamiento','prohibido','permite','permitido','debido','proceso'
        }
        is_normative = any(k in convivencia_terms for k in kws) or 'manual de convivencia' in q_norm

        if is_normative:
            doc_chunks = self._documentos(kws, db, limit=4)
            if doc_chunks:
                parts.append('=== MANUAL DE CONVIVENCIA 2026 — FRAGMENTOS RELEVANTES ===')
                parts.extend(doc_chunks)
                sources.append('Manual de Convivencia 2026')

        kb = self._kb(kws, db)
        if kb:
            parts.append('=== INFORMACIÓN INSTITUCIONAL ===')
            for item in kb:
                parts.append(f'[{item.categoria.upper()}]\nPregunta: {item.pregunta}\nRespuesta: {item.respuesta}\n')
            sources.append('base de conocimiento')

        docentes = self._docentes(kws, db)
        if docentes:
            parts.append('=== CUERPO DOCENTE ===')
            for d in docentes:
                parts.append(f'Nombre: {d.nombre}\nÁrea: {d.area}\nTítulo: {d.titulo}\nGrados: {d.grados}\nHorario de atención: {d.atencion}\n')
            sources.append('docentes')

        grades = self.detect_grade(query)
        horario_trigger = any(t in q_norm for t in ('horario','clase','jornada','materia','asignatura'))
        if grades or horario_trigger:
            horarios = self._horarios(grades, kws, db)
            if horarios:
                parts.append('=== HORARIOS DE CLASES ===')
                for h in sorted(horarios, key=lambda x: (x.grado, x.hora)):
                    parts.append(f'Grado {h.grado}: {h.hora}: {h.materia} — {h.docente}')
                sources.append('horarios')

        contactos = self._contactos(kws, q_norm, db)
        if contactos:
            parts.append('=== DIRECTORIO DE CONTACTOS ===')
            for c in contactos:
                parts.append(f'Cargo: {c.cargo}\nNombre: {c.nombre}\nContacto: {c.contacto}\nHorario: {c.horario}\n')
            sources.append('contactos')

        # Si no es normativa, también permitimos búsqueda documental normal.
        if not is_normative:
            doc_chunks = self._documentos(kws, db, limit=3)
            if doc_chunks:
                parts.append('=== DOCUMENTOS INSTITUCIONALES — FRAGMENTOS RELEVANTES ===')
                parts.extend(doc_chunks)
                sources.append('documentos')

        return '\n'.join(parts), sources

    # ──────────────────────────────────────────────────────────
    #  Buscadores por tabla
    # ──────────────────────────────────────────────────────────

    def _kb(self, kws: List[str], db: Session) -> List[KnowledgeBase]:
        if not kws:
            return []
        items = db.query(KnowledgeBase).all()
        scored = [
            (item, self.score(item.pregunta + " " + item.respuesta, kws))
            for item in items
        ]
        return [i for i, s in sorted(scored, key=lambda x: -x[1]) if s > 0][:2]

    def _docentes(self, kws: List[str], db: Session) -> List[Docente]:
        if not kws:
            return []
        docentes = db.query(Docente).all()
        scored = [
            (d, self.score(f"{d.nombre} {d.area} {d.titulo} {d.grados}", kws))
            for d in docentes
        ]
        return [d for d, s in sorted(scored, key=lambda x: -x[1]) if s > 0][:5]

    def _horarios(self, grades: List[str], kws: List[str], db: Session) -> List[Horario]:
        q = db.query(Horario)
        if grades:
            q = q.filter(Horario.grado.in_(grades))
        horarios = q.all()
        if not grades and kws:
            scored = [(h, self.score(f"{h.materia} {h.docente}", kws)) for h in horarios]
            return [h for h, s in scored if s > 0][:15]
        return horarios

    def _contactos(self, kws: List[str], q_norm: str, db: Session) -> List[Contacto]:
        # Si la pregunta tiene trigger de contacto, devolver todos
        if any(t in q_norm for t in self.CONTACTO_TRIGGERS):
            return db.query(Contacto).all()
        if not kws:
            return []
        contactos = db.query(Contacto).all()
        scored = [
            (c, self.score(f"{c.cargo} {c.nombre} {c.contacto}", kws))
            for c in contactos
        ]
        return [c for c, s in sorted(scored, key=lambda x: -x[1]) if s > 0][:3]

    def _documentos(self, kws: List[str], db: Session, limit: int = 4) -> List[str]:
        """Busca directamente en los chunks del Manual/documentos importados.

        Prioriza coincidencias en contenido, títulos y palabras clave. Esto evita
        devolver siempre el primer fragmento del PDF y hace que el Manual de
        Convivencia 2026 sea realmente una fuente RAG.
        """
        if not kws:
            return []

        rows = (
            db.query(DocumentChunk)
            .join(DocumentChunk.document)
            .filter(DocumentChunk.document.has(is_active=True))
            .all()
        )
        ranked = []
        for chunk in rows:
            searchable = " ".join(filter(None, [
                chunk.content, chunk.section_title, chunk.article_title, chunk.keywords
            ]))
            norm = self.normalize(searchable)
            score = 0
            matched = 0
            for kw in kws:
                if kw in norm:
                    matched += 1
                    score += 2
                    # coincidencia en título/palabras clave pesa más
                    if kw in self.normalize(chunk.section_title or ""):
                        score += 2
                    if kw in self.normalize(chunk.article_title or ""):
                        score += 2
                    if kw in self.normalize(chunk.keywords or ""):
                        score += 1
            if matched:
                ranked.append((score, matched, chunk))

        ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
        results = []
        for _, _, chunk in ranked[:4]:
            header = [f"[Documento: {chunk.document.name}]"]
            if chunk.section_title:
                header.append(f"Sección: {chunk.section_title}")
            if chunk.article_title:
                header.append(f"Artículo: {chunk.article_title}")
            if chunk.page_number:
                header.append(f"Página: {chunk.page_number}")
            results.append("\n".join(header) + "\n" + chunk.content.strip())
        return results
