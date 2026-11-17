# Base compartida de la entrega 2

`Develop` es la rama de integración. Cada tarea nueva parte de su versión actualizada y vuelve
a ella mediante un PR. E1-01 contiene el modelo compartido y la migración 0004; E2-01 y E2-02
se construyeron inicialmente sobre esa rama, por lo que se integra primero E1-01.

Para E2-03, la base debe incluir también E2-01 (residentes) y E2-02 (profesionales).

## Contratos de los servicios

Los servicios están en `app/nucleo/atenciones.py`, `adjuntos.py`, `fichas.py`, `permisos.py` y
`digitalizacion.py`. Sus firmas y docstrings definen cómo los consume el resto del equipo.
Los servicios pendientes lanzan `NotImplementedError`; las rutas del esqueleto no los ejecutan.
Si hay que cambiar una firma o un campo compartido, se coordina con quienes los usan.

`app/nucleo/campos.py` define los nombres y formatos compartidos por los formularios, la IA y
la digitalización. Los modelos y su migración deben mantenerse sincronizados.

## Rutas compartidas

Cada sección tiene un módulo web propio, registrado en `app/main.py`, y un enlace en el menú
según el rol. Las secciones aún pendientes muestran "Disponible próximamente" y responden 501,
con autenticación y permisos ya aplicados. Se reemplaza el handler de su módulo al implementar
el issue, sin registrar una segunda ruta para la misma URL.

| Módulo web | URL | Tarea |
|---|---|---|
| `residentes.py` | `/residentes` | E2-01 |
| `profesionales.py` | `/profesionales` | E2-02 |
| `fichas.py` | `/fichas`, `/residentes/{residente_id:int}` | E1-02 |
| `atenciones.py` | `/atenciones` | E3-01 y siguientes |
| `adjuntos.py` | `/adjuntos` | E3-04 |
| `digitalizacion.py` | `/digitalizacion` | E4-02 y siguientes |

`/fichas` queda como entrada para elegir la ficha clínica; `/residentes` administra los datos
administrativos. El convertidor `:int` de la ficha evita capturar `/residentes/nuevo`.
Los permisos por residente se completan en E2-03: el esqueleto clínico solo comprueba el rol y
no entrega datos clínicos.

## Validación antes de integrar

Ejecutar `ruff check .` y `pytest`. El workflow de GitHub verifica Python 3.11, Python 3.13 y
las migraciones en PostgreSQL. Antes de integrar un PR dependiente, actualizarlo con `Develop`
y resolver los conflictos conservando las rutas y enlaces de ambas tareas.

## Prueba de lectura de manuscritos (E4-01)

El script no usa la base de datos ni activa los bots. Configurar `LLM_PROVIDER=openai`,
`LLM_MODEL=gpt-6-luna` y `OPENAI_API_KEY` en el `.env` local, sin publicar la clave:

```bash
python -m scripts.probar_lectura_imagen --datos-ficticios /ruta/documento.jpg
```

Admite una imagen JPG o PNG de hasta 10 MB, validada por sus bytes. Devuelve la transcripción
literal, las marcas `[ilegible]`, el modelo solicitado, el modelo usado y el tiempo de respuesta.
No interpreta el documento ni resuelve fechas relativas. Rechazos, respuestas truncadas o
vacías y errores de red/API terminan con código de error; no cuentan como prueba aprobada.

Contrato implementado en OpenAI y fake:

```python
leer_imagen(contenido: bytes, mime: str) -> ResultadoLLM
# ResultadoLLM.texto: transcripción literal; ResultadoLLM.modelo: modelo usado.
```

El flujo propuesto es imagen → texto literal → seudonimización → extractor existente. El texto
literal y su modelo se guardarán antes de extraer, para poder reintentar sin releer la imagen.
La imagen no se puede seudonimizar antes de enviarla: solo se prueban documentos ficticios.
El proveedor fake sirve para tests, no demuestra capacidad del modelo del curso.

**Validación real pendiente:** probar 2 o 3 manuscritos ficticios del equipo y registrar en #17
los tiempos, errores de lectura y una salida de ejemplo. No dar por confirmado el soporte de
imágenes hasta completar esa prueba. Si la API no las acepta, avisar en #17 y acordar el plan B
(OCR local para impresos y transcripción asistida para manuscritos) antes de integrar E4-03.
