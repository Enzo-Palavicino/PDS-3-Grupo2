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
`uvicorn app.main:app --reload`. Para que el bot acepte tus mensajes, primero vincula tu cuenta.

### Vincular tu cuenta

El bot solo acepta registros de cuentas vinculadas a un profesional. Mientras no exista la vista
web de vínculos, el enlace se genera desde la consola, con la base de datos creada y los datos
de demostración cargados:

```bash
python -m scripts.generar_codigo pediatra
```

El script imprime un enlace `https://t.me/<tu_bot>?start=<código>`. Ábrelo en Telegram y pulsa
Iniciar: el bot responde "Cuenta vinculada". El enlace es de un solo uso y vence en 10 minutos.

Desde ese momento, cada texto o audio que envíes queda guardado para procesarse y el bot
responde "Recibido". Una cuenta sin vincular recibe "Esta cuenta no está autorizada para enviar
registros", y su mensaje no se guarda.

## Procesamiento de los mensajes

Cada mensaje que el bot guarda lo procesa en segundo plano un worker: un hilo dentro de la misma
aplicación, que usa la tabla `mensajes_entrantes` como cola. Así, recibir un mensaje nunca
espera a la transcripción ni a la IA. Los pasos dependen del estado del mensaje:

```
recibido ─(audio: transcribir)─► transcrito ─(IA y borrador)─► extraido ─(responder)─► listo
```

Cada paso guarda su avance antes del siguiente. Si uno falla, el worker guarda solo el tipo de
error y lo reintenta desde ese mismo paso a los 10 s y a los 60 s: por ejemplo, si falló el envío
de la respuesta, no vuelve a llamar a la IA. Si falla 3 veces, el mensaje queda en `error` y el
bot le avisa al profesional.

### Transcripción de audios

`STT_PROVIDER` elige el proveedor:

- `fake`, por defecto: devuelve siempre "Transcripción de prueba" y no necesita API key. Sirve
  para los tests y para probar el flujo completo.
- `openai`: usa `gpt-transcribe` (`STT_MODEL`) con la API key de OpenAI que entregó el curso
  (ver [API key de OpenAI](#api-key-de-openai)).

El audio se descarga a un archivo temporal en `AUDIO_DIR` (por defecto, la carpeta temporal del
sistema, fuera del repositorio), se transcribe y se borra apenas termina el intento, aunque haya
fallado. La transcripción queda en la tabla `transcripciones`; el bot nunca la envía al chat.

**Privacidad:** antes de llegar al modelo de lenguaje, el texto se seudonimiza. Un audio, en
cambio, no se puede seudonimizar antes de transcribirlo, así que el proveedor de transcripción
recibe datos identificables. En producción hay que usar una cuenta configurada sin retención de
datos, o un modelo local como Whisper. En desarrollo y en la demo se usan solo datos ficticios.

## Extracción con IA

Un LLM convierte el texto libre del registro (escrito o transcrito) en los campos del "Registro
de Atención y Control de Salud": residente, fecha, lugar, motivo, diagnósticos, indicaciones,
próximo control, acompañante, etc. Cada campo trae el fragmento del texto que lo respalda.

1. **Seudonimización** (`app/nucleo/seudonimizacion.py`): los nombres, apellidos y apodos de los
   residentes se reemplazan por su código (`[RES-02]`), sin importar mayúsculas ni tildes y
   tolerando errores menores de transcripción. Un nombre que comparten dos residentes queda
   como `[RES-01|RES-04]`. RUT, teléfonos y correos se reemplazan por `[RUT]`, `[TEL]` y
   `[EMAIL]`. Limitación: los nombres de quienes no son residentes (familiares, funcionarios)
   no se detectan.
2. **Extracción** (`app/nucleo/extraccion.py`): el LLM recibe el texto seudonimizado, la fecha
   de referencia en hora de Chile y los códigos de los residentes con su nivel y edad (nunca
   nombres). Las instrucciones le prohíben inventar datos.
3. **Validación**: se descarta todo dato cuyo fragmento no aparezca en el texto, y las fechas
   con formato inválido. El residente lo decide el sistema con lo que encontró la
   seudonimización: un nombre ambiguo o dos residentes en un mismo mensaje quedan registrados
   como ambigüedad.

`LLM_PROVIDER` elige el proveedor:

- `fake`, por defecto: no usa IA y deja todos los campos vacíos. Sirve para los tests.
- `openai`: usa `gpt-6-luna` (`LLM_MODEL`) con la API key de OpenAI que entregó el curso, con
  salida estructurada en modo estricto: la API obliga a que la respuesta cumpla el esquema.

### API key de OpenAI

El curso entregó una API key de OpenAI por grupo. Solo permite los modelos `gpt-6-luna`,
`gpt-transcribe`, `text-embedding-3-small` y `text-embedding-3-large`. Va en `.env`:

```
STT_PROVIDER=openai
LLM_PROVIDER=openai
OPENAI_API_KEY=<la key del curso>
```

Nunca la subas al repositorio (es público) ni la compartas por chat: si se filtra, la pueden
desactivar y el grupo se queda sin ella.

Para probar la extracción sin pasar por el bot (con la base de datos creada y los datos de
demostración cargados):

```bash
python -m scripts.probar_extraccion "Hoy atendí a Emilia Soto en el Hogar..."
```

Muestra lo que recibió el LLM y los datos extraídos ya validados.

## Borradores y respuestas del bot

Con los campos extraídos, el worker arma un **borrador de atención**. Nunca es una atención
registrada: siempre la revisa un profesional en la plataforma. Si el profesional le responde al
mensaje del bot sobre un borrador pendiente suyo, su respuesta completa ese mismo borrador; si
no, cada mensaje crea uno nuevo.

Reglas (sección 10 de la especificación):

- Un borrador completo necesita residente, fecha de atención y diagnóstico o motivo. Si falta
  alguno, queda como faltante.
- El próximo control y el acompañante (nombre y cargo) son esperados: si faltan, se informan,
  pero no bloquean el borrador.
- El bot pide lo que falta una sola vez. Si el profesional completa el borrador respondiendo,
  el bot solo confirma la actualización.
- Una pregunta ("¿qué alergias tiene…?") no crea borrador: el bot responde que por este canal
  solo recibe registros. Es pregunta si el LLM la marca como consulta o si tiene "?", siempre
  que el mensaje no traiga datos de una atención (diagnósticos, indicaciones, etc.).
- La especialidad no la extrae la IA: se toma del profesional vinculado.

El bot responde solo con el número del borrador, las iniciales del residente, lo que falta y el
enlace a la plataforma (`PUBLIC_BASE_URL`); nunca envía datos clínicos al chat. Con
`TELEGRAM_DELETE_INCOMING=true`, además borra del chat el mensaje del profesional una vez
procesado.

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
    telegram/     cliente de la Bot API, adaptador y polling
  nucleo/         lógica que no depende del canal: vinculación, ingesta, worker, auditoría,
                  seudonimización y extracción
  proveedores/    proveedores de IA intercambiables por configuración: transcripción y LLM
migrations/       migraciones de Alembic
scripts/          scripts de desarrollo, como la carga de datos de demostración
tests/            tests automáticos
```
