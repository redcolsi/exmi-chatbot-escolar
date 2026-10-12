# Exmi v2 — corrección del error al cargar el Manual

El error `El JSON no contiene bloques de texto válidos después de normalizar` ocurría porque `json_to_db.py` trataba `secciones` como bloques planos. El Manual 2026 tiene texto dentro de `contenido` y `subsecciones`.

## Pasos

1. Reemplazar la carpeta/proyecto anterior por este proyecto corregido, o copiar este `backend/app/converters/json_to_db.py` sobre el archivo del proyecto.
2. Abrir PowerShell en `backend`.
3. Ejecutar `python seed_data.py`.
4. Debe aparecer una línea similar a `Bloques crudos encontrados:` seguida de un número mayor que 0 y `Bloques válidos:` seguido de un número mayor que 0.
5. Después ejecutar `python run.py`.

No es necesario modificar el JSON del Manual.
