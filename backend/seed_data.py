"""
seed_data.py — Inicializar la base de datos con datos institucionales.

Ejecutar UNA sola vez antes del primer arranque:
    python seed_data.py

El script es idempotente: no duplica registros si ya existen.
"""
from __future__ import annotations

import os
import sys

# Asegura que Python encuentre el paquete 'app'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.database.database import engine, SessionLocal
from app.models.models import Base, BotConfig, ChatHistory, Contacto, Docente, Horario, KnowledgeBase, User
from app.models.document import Document, DocumentChunk, DocumentCategory
from app.auth.security import hash_password


def run_seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # ── Usuario administrador (docente) ───────────────────────
        if not db.query(User).filter(User.email == "admin@einstein.edu").first():
            db.add(User(
                email="admin@einstein.edu",
                username="admin",
                hashed_password=hash_password("einstein2024"),
                role="admin",
            ))
            print("  ✅ Usuario admin creado  →  admin@einstein.edu / einstein2024")
        else:
            print("  ⏭  Usuario admin ya existe")

        # ── Base de conocimiento ──────────────────────────────────
        if db.query(KnowledgeBase).count() == 0:
            kb_rows = [
                ("mision_vision", "¿Cuál es la misión del colegio?",
                 "El colegio Albert Einstein tiene la misión de formar de manera inclusiva a niños, niñas, "
                 "jóvenes y adolescentes en los niveles de preescolar, primaria, secundaria y media, "
                 "promoviendo el respeto, fomentando la fe y generando espacios de investigación."),
                ("mision_vision", "¿Cuál es la visión del colegio?",
                 "Para el año 2025, el colegio Albert Einstein se destacará en los resultados de las pruebas "
                 "Saber, ampliando la población educativa, fortaleciendo procesos de investigación y "
                 "generando vínculos con instituciones que fortalezcan el proyecto de vida."),
                ("general", "¿Quién es la rectora?",
                 "La rectora del colegio es Fabiola Margarita Caicedo Conde."),
                ("general", "¿Dónde está ubicado el colegio?",
                 "El colegio está ubicado en AV 1 # 9-39, Barrio Latino, Cúcuta, Norte de Santander."),
                ("general", "¿Cómo inscribirse?",
                 "Para inscribirte visita www.webcolegios.com/coleinstein o llama al +57 312 5399542."),
                ("academico", "¿Cuáles son los valores del colegio?",
                 "Los valores institucionales son: Respeto, Responsabilidad, Honestidad y Solidaridad."),
                ("academico", "¿Cuál es el perfil del estudiante?",
                 "Un verdadero estudiante Albert Einstein debe identificarse como persona, teniendo en cuenta "
                 "sus valores y principios. Está llamado a ser agente de cambio de sí mismo y de la sociedad "
                 "en que se desenvuelve."),
                ("administrativo", "Proceso de admisión",
                 "Para la admisión se requiere: cupo disponible, pruebas diagnósticas, certificado de buena "
                 "conducta, paz y salvo, registro civil, 2 fotos, carnet de vacunación, boletín del último "
                 "año, diligenciar hoja de matrícula y contrato de servicios educativos."),
                ("convivencia", "Normas de convivencia - uniforme",
                 "El uso del uniforme completo es obligatorio. El uniforme de educación física solo se usa "
                 "en las clases correspondientes."),
                ("convivencia", "Normas de convivencia - celulares",
                 "El uso de celulares en aulas está prohibido durante clases. Solo se permiten con "
                 "autorización del docente para fines pedagógicos."),
                ("convivencia", "Derechos del estudiante",
                 "Los estudiantes tienen derecho a recibir educación de calidad, ser escuchados en procesos "
                 "disciplinarios, participar en el gobierno escolar y acceder a los recursos pedagógicos."),
                ("convivencia", "Deberes del estudiante",
                 "Los estudiantes deben asistir puntualmente, cumplir con tareas y evaluaciones, cuidar la "
                 "planta física y respetar a compañeros y docentes."),
            ]
            for cat, pregunta, respuesta in kb_rows:
                db.add(KnowledgeBase(categoria=cat, pregunta=pregunta, respuesta=respuesta))
            print(f"  ✅ {len(kb_rows)} entradas de conocimiento creadas")
        else:
            print(f"  ⏭  Base de conocimiento ya tiene {db.query(KnowledgeBase).count()} entradas")

        # ── Docentes ──────────────────────────────────────────────
        if db.query(Docente).count() == 0:
            docentes_rows = [
                ("Castro Velásquez Kevin Sebastián", "Sociales / Ciencias Políticas / Filosofía",
                 "Lic. Ciencias Sociales", "9°, 10°, 11°", "Lun–Mié 10:00–11:00 am"),
                ("Campo Yaruro Gloria Helena", "Cátedra de la Paz / Ética",
                 "Lic. Ciencias Humanas", "6° al 11°", "Mar 9:00–10:00 am"),
                ("Abril García William", "Matemáticas",
                 "Lic. Matemáticas", "6° al 11°", "Jue 8:00–9:00 am"),
                ("Espinel Márquez Adriana del Pilar", "Lengua Castellana",
                 "Lic. Humanidades", "6° al 11°", "Lun 11:00 am–12:00 m"),
                ("Guardiola Valiente Kendri Yaneth", "Inglés",
                 "Lic. Idiomas Modernos", "6° al 11°", "Vie 9:00–10:00 am"),
                ("Esquea Osorio Camilo Andrés", "Física / Tecnología / Investigación",
                 "Ing. de Sistemas", "9°, 10°, 11°", "Mié 8:00–9:00 am"),
                ("Mendoza Gil Constanza Adriana", "Química",
                 "Lic. Química", "9°, 10°, 11°", "Mar 10:00–11:00 am"),
                ("Gallardo Díaz Jean Carlos", "Artística",
                 "Lic. Artes Plásticas", "6° al 11°", "Jue 10:00–11:00 am"),
                ("Fuentes Contreras Jefferson Leonardo", "Ed. Religiosa / Ed. Física",
                 "Lic. Ed. Física", "6° al 11°", "Lun 8:00–9:00 am"),
            ]
            for nombre, area, titulo, grados, atencion in docentes_rows:
                db.add(Docente(nombre=nombre, area=area, titulo=titulo, grados=grados, atencion=atencion))
            print(f"  ✅ {len(docentes_rows)} docentes creados")
        else:
            print(f"  ⏭  Docentes ya existen ({db.query(Docente).count()})")

        # ── Horarios ──────────────────────────────────────────────
        if db.query(Horario).count() == 0:
            horarios_rows = [
                ("6°",  "7:00–7:45",   "Matemáticas",    "Abril García William"),
                ("6°",  "7:45–8:30",   "Lengua Castellana", "Espinel Márquez Adriana"),
                ("6°",  "8:30–9:15",   "Inglés",         "Guardiola Valiente Kendri"),
                ("6°",  "9:15–9:30",   "Descanso",       "—"),
                ("6°",  "9:30–10:15",  "Artística",      "Gallardo Díaz Jean Carlos"),
                ("9°",  "7:00–7:45",   "Física",         "Esquea Osorio Camilo"),
                ("9°",  "7:45–8:30",   "Química",        "Mendoza Gil Constanza"),
                ("9°",  "8:30–9:15",   "Matemáticas",    "Abril García William"),
                ("9°",  "9:15–9:30",   "Descanso",       "—"),
                ("9°",  "9:30–10:15",  "Inglés",         "Guardiola Valiente Kendri"),
                ("10°", "7:00–7:45",   "Filosofía",      "Castro Velásquez Kevin"),
                ("10°", "7:45–8:30",   "Matemáticas",    "Abril García William"),
                ("10°", "8:30–9:15",   "Física",         "Esquea Osorio Camilo"),
                ("10°", "9:15–9:30",   "Descanso",       "—"),
                ("10°", "9:30–10:15",  "Química",        "Mendoza Gil Constanza"),
                ("11°", "7:00–7:45",   "Matemáticas",    "Abril García William"),
                ("11°", "7:45–8:30",   "Filosofía",      "Castro Velásquez Kevin"),
                ("11°", "8:30–9:15",   "Química",        "Mendoza Gil Constanza"),
                ("11°", "9:15–9:30",   "Descanso",       "—"),
                ("11°", "9:30–10:15",  "Investigación",  "Esquea Osorio Camilo"),
            ]
            for grado, hora, materia, docente in horarios_rows:
                db.add(Horario(grado=grado, hora=hora, materia=materia, docente=docente))
            print(f"  ✅ {len(horarios_rows)} horarios creados")
        else:
            print(f"  ⏭  Horarios ya existen ({db.query(Horario).count()})")

        # ── Contactos ─────────────────────────────────────────────
        if db.query(Contacto).count() == 0:
            contactos_rows = [
                ("Rectora",         "Fabiola Margarita Caicedo Conde", "+57 312 5399542",               "Lun–Vie 8:00–12:00 m"),
                ("Secretaría",      "Secretaría general",              "+57 312 5399542",               "Lun–Vie 7:00–1:00 pm"),
                ("Psicoorientación","Orientadora escolar",             "orientacion@einstein.edu",      "Mar y Jue 8:00–11:00 am"),
                ("Emergencias",     "Línea de emergencias",            "123 / 119",                     "24 horas"),
                ("Portal web",      "Página institucional",            "webcolegios.com/coleinstein",   "En línea"),
            ]
            for cargo, nombre, contacto, horario in contactos_rows:
                db.add(Contacto(cargo=cargo, nombre=nombre, contacto=contacto, horario=horario))
            print(f"  ✅ {len(contactos_rows)} contactos creados")
        else:
            print(f"  ⏭  Contactos ya existen ({db.query(Contacto).count()})")

        # ── Manual de Convivencia 2026 (RAG documental) ────────────
        # Importa los 161 bloques del JSON preparado en app/documents/.
        if db.query(Document).filter(Document.name == "Manual de Convivencia 2026").count() == 0 or db.query(DocumentChunk).filter(DocumentChunk.document_id == db.query(Document).filter(Document.name == "Manual de Convivencia 2026").with_entities(Document.id).scalar_subquery()).count() == 0:
            from app.converters.json_to_db import import_json_to_db
            base_dir = os.path.dirname(os.path.abspath(__file__))
            docs_dir = os.path.join(base_dir, "app", "documents")
            # Acepta el nombre con guiones bajos (actual) o con espacios (antiguo)
            json_path = next(
                (os.path.join(docs_dir, n) for n in ("MANUAL_DE_CONVIVENCIA_2026.json", "MANUAL DE CONVIVENCIA 2026.json")
                 if os.path.exists(os.path.join(docs_dir, n))),
                os.path.join(docs_dir, "MANUAL_DE_CONVIVENCIA_2026.json"),
            )
            pdf_path = os.path.join(docs_dir, "MANUAL DE CONVIVENCIA 2026.pdf")
            if os.path.exists(json_path):
                import_json_to_db(
                    db,
                    json_path=json_path,
                    pdf_path=pdf_path if os.path.exists(pdf_path) else None,
                    name="Manual de Convivencia 2026",
                    description="Manual institucional de convivencia del Colegio Albert Einstein.",
                    category=DocumentCategory.CONVIVENCIA,
                    uploaded_by="seed_data",
                )
                print("  ✅ Manual de Convivencia 2026 importado al RAG")
            else:
                print("  ⚠ No se encontró el JSON del Manual de Convivencia 2026")
        else:
            print(f"  ⏭  RAG documental ya tiene {db.query(DocumentChunk).count()} chunks")

        # ── Configuración del bot ─────────────────────────────────
        if db.query(BotConfig).count() == 0:
            configs = [
                ("bot_name",     "Exmi"),
                ("welcome_msg",  "¡Bienvenido al Colegio Albert Einstein! 🎓\nSoy Exmi, tu asistente escolar."),
                ("ai_mode",      "ia"),
                ("accent_color", "#f5a623"),
                ("bg_color",     "#0a0e17"),
                ("surface_color","#111827"),
                ("sections",     '{"horarios": true, "docentes": true, "convivencia": true, "contactos": true}'),
            ]
            for clave, valor in configs:
                db.add(BotConfig(clave=clave, valor=valor))
            print(f"  ✅ {len(configs)} configuraciones de bot creadas")
        else:
            print(f"  ⏭  Configuración del bot ya existe ({db.query(BotConfig).count()} entradas)")

        db.commit()

        print("\n" + "═" * 50)
        print("  ✅ Base de datos lista")
        print("  📧 Admin: admin@einstein.edu")
        print("  🔑 Clave: einstein2024")
        print("  ⚠️  Cambia la contraseña en el panel docente.")
        print("═" * 50)

    except Exception as exc:
        db.rollback()
        print(f"\n  ❌ Error durante el seed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("\nIniciando carga de datos iniciales…\n")
    run_seed()
