# PDS-3-Grupo2

Plataforma de salud para los niños y niñas residentes del Hogar Misión de María.
Proyecto 3 de ICC4201 Proyecto de Desarrollo de Software, Universidad de los Andes.

Los profesionales podrán registrar atenciones desde la web y también por Telegram y WhatsApp,
enviando texto o audio. La IA transcribe los audios y extrae los campos del "Registro de Atención
y Control de Salud", que quedan como borradores para que un profesional los revise.

## Reglas del repositorio

El repositorio es público:

- nunca subas tokens, claves ni el archivo `.env`;
- usa solo datos ficticios, nunca datos reales de los niños, del Hogar ni de sus funcionarios;
- los logs registran solo ids y estados, nunca el contenido de los mensajes ni datos clínicos.

## Requisitos

- Python 3.11 o superior.

## Instalación local

Se hace una sola vez, desde la carpeta del repositorio.

1. Crea el entorno virtual:

   ```bash
   python -m venv .venv
   ```

   Es una carpeta `.venv` con un Python propio del proyecto. Ahí se instalan sus librerías sin
   tocar el Python global del computador. Git la ignora.

2. Actívalo, para que `python` y `pip` en esa terminal usen el entorno:

   - Windows (PowerShell): `.venv\Scripts\Activate.ps1`
   - macOS o Linux: `source .venv/bin/activate`

   Si PowerShell responde que "la ejecución de scripts está deshabilitada en este sistema",
   revisa la sección [Error de PowerShell al activar el entorno](#error-de-powershell-al-activar-el-entorno).

3. Instala las librerías:

   ```bash
   pip install -r requirements-dev.txt
   ```

   Se instalan las versiones exactas del proyecto, las mismas que usan el resto del grupo y
   GitHub Actions.

4. Crea tu configuración local (el comando funciona en PowerShell y en bash):

   ```bash
   cp .env.example .env
   ```

   En `.env` van los tokens y las claves. Nunca se sube al repositorio.

### Error de PowerShell al activar el entorno

Windows bloquea por defecto la ejecución de scripts de PowerShell, y `Activate.ps1` es un script.
Para permitir los scripts locales solo en tu usuario (no requiere administrador):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Los scripts descargados de internet siguen necesitando firma. Si prefieres no cambiar nada de
forma permanente:

- solo para la ventana actual: `Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process`;
- sin activar el entorno: usa su Python directamente, por ejemplo `.venv\Scripts\python -m pytest`.

## Ejecutar la aplicación

```bash
uvicorn app.main:app --reload
```

uvicorn es el servidor que ejecuta la aplicación: abre `http://localhost:8000` y le pasa cada
petición a FastAPI. `--reload` la reinicia cada vez que cambia el código. Para comprobar que
funciona, abre <http://localhost:8000/health>.

## Base de datos

En desarrollo se usa SQLite: un archivo en `data/app.db`, que git ignora. Las tablas se crean
con migraciones de Alembic, que dejan registrado cada cambio del esquema.

```bash
alembic upgrade head              # crea o actualiza las tablas
python -m scripts.sembrar_datos   # carga los datos ficticios de demostración
```

El script de datos necesita `SEED_PASSWORD` en `.env`: es la contraseña de los usuarios de
demostración (`directora`, `encargada_salud`, `pediatra`, `nutricionista` y `kinesiologo`). Se
puede correr varias veces sin duplicar nada.

Si cambias un modelo en `app/modelos.py`, crea su migración con
`alembic revision --autogenerate -m "descripción"` y revísala antes de hacer commit. Un test
falla si los modelos y las migraciones no coinciden.

## Bot de Telegram

### Crear el bot

1. En Telegram, abre @BotFather y envía `/newbot`. Elige un nombre y un usuario para el bot; el
   usuario debe terminar en `bot`. BotFather responde con el token del bot.
2. Envía `/setjoingroups`, elige tu bot y selecciona Disable, para que nadie pueda agregarlo a
   un grupo. El bot solo atiende chats privados.
3. Pon el token en tu `.env`, en `TELEGRAM_BOT_TOKEN`. Quien tenga el token controla el bot:
   nunca lo subas al repositorio ni lo compartas.

Conviene que cada integrante cree su propio bot para desarrollar. Con el mismo token no pueden
funcionar dos instancias a la vez: Telegram corta una de ellas.

### Probarlo en local (modo polling)

Con `TELEGRAM_MODE=polling` en `.env`, la aplicación le pide a Telegram los mensajes nuevos con
`getUpdates`, así que no necesita una URL pública. Levanta la aplicación con
`uvicorn app.main:app --reload` y escríbele al bot. Por ahora responde un eco de lo que recibe,
solo para probar la conexión.

## Tests y lint

```bash
pytest
ruff check .
```

`pytest` corre los tests automáticos, y `ruff` revisa errores comunes (por ejemplo, imports o
variables sin usar) y el orden de los imports. GitHub Actions corre ambos en cada push: el
resultado se ve en la pestaña Actions y en el PR. Los tests no usan servicios externos.

## Estructura

```
app/
  main.py         crea la aplicación, define GET /health y arranca la recepción de mensajes
  config.py       configuración leída desde variables de entorno o .env
  logs.py         configuración de los logs
  db.py           conexión a la base de datos
  modelos.py      tablas de la base de datos
  seguridad.py    hash de contraseñas
  canales/
    base.py       tipos comunes a todos los canales: MensajeNormalizado y AdaptadorCanal
    telegram/     cliente de la Bot API, adaptador, polling y eco temporal
  nucleo/         lógica que no depende del canal (por ahora, el registro de mensajes)
migrations/       migraciones de Alembic
scripts/          scripts de desarrollo, como la carga de datos de demostración
tests/            tests automáticos
```
