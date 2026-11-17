# Flujo de trabajo del equipo

Perfil del proyecto para la skill `team-workflow`. El repositorio es público: aquí van solo
logins, nombres de ramas y reglas, nunca tokens ni datos personales.

## Repositorio y ramas

- Repositorio: [Enzo-Palavicino/PDS-3-Grupo2](https://github.com/Enzo-Palavicino/PDS-3-Grupo2).
- Rama de integración: `Develop`. Todas las ramas de tareas salen de `Develop` y sus PRs
  apuntan a `Develop`.
- Rama por defecto y de entrega: `main`. Se actualiza con un PR de `Develop` a `main`.
- Nombre de rama: `E<épica>-<nn>-<tema>`, por ejemplo `E3-04-adjuntos`.

## Seguimiento de tareas

- Herramienta: GitHub Issues. **No se usa Trello.**
- Título del issue: `[Ex-nn] Descripción`.
- Etiquetas: prioridad (`P0`, `P1`, `P2`), épica (`E1 · Ficha clínica`, `E2 · Administración`,
  `E3 · Atenciones`, `E4 · Digitalización`, `E5 · Despliegue y demo`) y tamaño
  (`talla:S`, `talla:M`, `talla:L`).
- Milestone actual: `Entrega 2 · 18 nov`.
- Cuerpo del issue: Descripción, Épica, Contexto, Historia de usuario, Criterios de
  aceptación, Dependencias funcionales, Dependencias externas, Responsable, Prioridad y Talla.
- Etapas: se ven en el estado del issue y del PR (abierto, PR abierto, PR fusionado, cerrado).

## Equipo

| Rol | GitHub |
| --- | --- |
| Persona A · Núcleo de datos, firma y despliegue | `Forte16` |
| Persona B · Ficha y atenciones (interfaz) | `Enzo-Palavicino` |
| Persona C · IA y digitalización | `matiasghff` |
| Persona D · Administración y archivos | `beatricebretti` |

## Commits y pull requests

- Commits: Conventional Commits en español, con scope cuando aplica,
  por ejemplo `feat(telegram): …`, `fix: …` o `chore: …`.
- Título del PR: `[Ex-nn] Descripción`.
- El PR enlaza su issue con `Closes #<n>`.
- Revisión: por ahora no se exige la aprobación de otra persona, y el autor puede fusionar su
  propio PR. Como buena práctica, pide que alguien del equipo lo revise antes de fusionarlo.

## Verificaciones

El CI (`.github/workflows/tests.yml`) corre en cada push:

```bash
ruff check .
pytest
pytest tests/test_postgres.py   # en CI, contra PostgreSQL 17
```

## Reglas del repositorio

- Nunca subir tokens, claves ni el archivo `.env`.
- Usar solo datos ficticios.
- Los logs guardan solo ids y estados, nunca el contenido de los mensajes ni datos clínicos.

## Definición de terminado

Una tarea está terminada cuando:

1. su PR está fusionado en `Develop`;
2. el CI está en verde en el último commit;
3. se cumplen los criterios de aceptación del issue;
4. el issue está cerrado.
