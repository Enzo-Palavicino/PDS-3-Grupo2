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
