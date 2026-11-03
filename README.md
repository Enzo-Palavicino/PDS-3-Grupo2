# PDS-3-Grupo2

Plataforma de salud para los niños y niñas residentes del Hogar Misión de María.
Proyecto 3 de ICC4201 Proyecto de Desarrollo de Software, Universidad de los Andes.

Los profesionales podrán registrar atenciones desde la web y también por Telegram y WhatsApp,
enviando texto o audio. La IA transcribe los audios y extrae los campos del "Registro de Atención
y Control de Salud", que quedan como borradores para que un profesional los revise.

Cómo funciona el bot de Telegram, de punta a punta, y cómo probarlo (con los tests, en local y
en el servidor) está explicado en [docs/telegram.md](docs/telegram.md).

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

## Variables de entorno

La aplicación lee su configuración de las variables de entorno o del archivo `.env`; si una
variable está en los dos, gana la de entorno. `.env.example` trae todas, con comentarios. En
Render, `render.yaml` fija las que no son secretas, y los secretos se ingresan en el panel.

| Variable | Para qué sirve | Por defecto | En Render |
|---|---|---|---|
| `LOG_LEVEL` | Detalle de los logs: `DEBUG`, `INFO`, `WARNING` o `ERROR`. `DEBUG` agrega las trazas de los errores, que pueden traer datos: solo para desarrollo | `INFO` | El valor por defecto |
| `TELEGRAM_BOT_TOKEN` | Token del bot, entregado por @BotFather. **Secreto** | — | El del bot del servidor |
| `TELEGRAM_MODE` | `off` (no recibe mensajes), `polling` (en local) o `webhook` (en el servidor) | `off` | `webhook` |
| `TELEGRAM_WEBHOOK_SECRET` | Secreto que Telegram envía en cada petición al webhook: de 1 a 256 letras, números, `_` o `-`. **Secreto** | — | Se ingresa en el panel |
| `TELEGRAM_DELETE_INCOMING` | `true`: el bot borra del chat el mensaje del profesional una vez procesado | `false` | `true` |
| `PUBLIC_BASE_URL` | Dirección de la plataforma, para los enlaces que envía el bot | `http://localhost:8000` | Se toma sola de `RENDER_EXTERNAL_URL` |
| `SECRET_KEY` | Firma la cookie de sesión de la web. **Secreto** | Una al azar en cada arranque | La genera Render |
| `DIAS_SIN_ACTIVIDAD_BORRADOR` | Días sin cambios tras los que un borrador pendiente aparece "sin actividad" | `30` | El valor por defecto |
| `DATABASE_URL` | Base de datos | `sqlite:///./data/app.db` | La de PostgreSQL de Render |
| `SEED_PASSWORD` | Contraseña de los usuarios de demostración. **Secreto** | — | Se ingresa en el panel |
| `STT_PROVIDER` y `STT_MODEL` | Transcripción de audios: `fake` u `openai`, y el modelo | `fake` y `gpt-transcribe` | `openai` |
| `AUDIO_DIR` | Carpeta donde está cada audio mientras se transcribe | La carpeta temporal del sistema | El valor por defecto |
| `LLM_PROVIDER` y `LLM_MODEL` | Extracción con IA: `fake` u `openai`, y el modelo | `fake` y `gpt-6-luna` | `openai` |
| `OPENAI_API_KEY` | La API key de OpenAI que entregó el curso. **Secreto** | — | Se ingresa en el panel |

Los secretos nunca se suben al repositorio. Si falta una variable obligatoria para la
configuración elegida (por ejemplo, el token con `TELEGRAM_MODE=polling`), la aplicación no
arranca y dice cuál falta. `TEST_POSTGRES_URL` solo la usan los tests de PostgreSQL (ver
[Tests y lint](#tests-y-lint)).

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

El bot solo acepta registros de cuentas vinculadas a un profesional. Con la base de datos creada,
los datos de demostración cargados y la aplicación corriendo:

1. Abre <http://localhost:8000> y entra como `directora`.
2. En **Vínculos**, pulsa **Generar enlace** en la fila del profesional (por ejemplo, Carolina
   Fuentes, pediatría).
3. Abre el enlace en Telegram, o escanea el código QR con el celular, y pulsa Iniciar: el bot
   responde "Cuenta vinculada".

El enlace es de un solo uso y vence en 10 minutos. También se puede generar desde la consola,
con `python -m scripts.generar_codigo pediatra`.

Desde ese momento, cada texto o audio que envíes queda guardado para procesarse y el bot
responde "Recibido". Una cuenta sin vincular recibe "Esta cuenta no está autorizada para enviar
registros", y su mensaje no se guarda.

### Webhook (en el servidor)

En el servidor, con `TELEGRAM_MODE=webhook`, Telegram le envía cada mensaje a la aplicación en un
POST a `/webhooks/telegram`. La aplicación configura el webhook sola al arrancar (con
`PUBLIC_BASE_URL`, que tiene que usar https) y solo acepta las peticiones que traen el secreto de
`TELEGRAM_WEBHOOK_SECRET` en el encabezado `X-Telegram-Bot-Api-Secret-Token`: cualquier otra
recibe 401 y no se guarda. La ruta responde apenas guarda el mensaje; las respuestas al chat se
envían después, y el worker hace el resto en segundo plano.

```bash
python -m scripts.telegram_webhook info     # URL configurada, pendientes y último error
python -m scripts.telegram_webhook delete   # borra el webhook: el bot vuelve al polling
python -m scripts.telegram_webhook set      # lo configura a mano (normalmente no hace falta)
```

Un bot con webhook activo no funciona en modo polling (Telegram responde 409). Por eso conviene
un bot para el servidor y otro para desarrollar en local.

El recorrido completo de un mensaje, las respuestas del bot, la prueba manual con los guiones de
la demo y la solución de problemas están en [docs/telegram.md](docs/telegram.md).

## Procesamiento de los mensajes

Cada mensaje que el bot guarda lo procesa en segundo plano un worker: un hilo dentro de la misma
aplicación, que usa la tabla `mensajes_entrantes` como cola. Así, recibir un mensaje nunca
espera a la transcripción ni a la IA. Los pasos dependen del estado del mensaje:

```
recibido ─(audio: transcribir)─► transcrito ─(IA y borrador)─► extraido ─(responder)─► listo
```

Cada paso guarda su avance antes del siguiente. Si uno falla, el worker guarda solo el tipo de
error y lo reintenta desde ese mismo paso a los 10 s y a los 60 s, o lo que pida Telegram si es
más (cuando se supera su límite de mensajes): por ejemplo, si falló el envío de la respuesta, no
vuelve a llamar a la IA. Si falla 3 veces, el mensaje queda en `error` y el bot le avisa al
profesional.

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
- Un borrador pendiente que no cambia en 30 días (`DIAS_SIN_ACTIVIDAD_BORRADOR`) aparece marcado
  "sin actividad" en la web, para que alguien lo revise y lo complete o lo descarte. Nunca se
  borra solo.

El bot responde solo con el número del borrador, las iniciales del residente, lo que falta y el
enlace a la plataforma (`PUBLIC_BASE_URL`); nunca envía datos clínicos al chat. Con
`TELEGRAM_DELETE_INCOMING=true`, además borra del chat el mensaje del profesional una vez
procesado.

## Plataforma web

Con la aplicación corriendo, abre <http://localhost:8000> e inicia sesión con un usuario de
demostración (la contraseña es la de `SEED_PASSWORD`). Las páginas son HTML simple renderizado
en el servidor.

| Página | Quién entra | Qué muestra |
|---|---|---|
| `/vinculos` | `directora` | Los profesionales y sus cuentas vinculadas. Genera el enlace de vinculación, con su código QR, y revoca vínculos. |
| `/borradores` | `encargada_salud` (todos) y cada profesional (los suyos) | La lista de borradores con su residente, profesional, canal, faltantes y estado. Marca los que están sin actividad. |
| `/borradores/{id}` | los mismos | Cada dato con su fragmento de origen, los mensajes de origen (con la transcripción), y lo que recibió la IA y qué modelo usó. Permite descartar el borrador. |

- Cada vez que alguien abre un borrador queda un evento de auditoría de lectura, igual que al
  iniciar sesión, descartar un borrador o revocar un vínculo.
- Los fragmentos se guardan seudonimizados (`[RES-02]`); la web, que exige iniciar sesión, los
  muestra con el nombre del residente.
- La sesión vive en una cookie firmada con `SECRET_KEY`, dura 8 horas, y todos los formularios
  llevan un token contra CSRF. Si falta `SECRET_KEY`, se usa una clave temporal y las sesiones
  se cierran al reiniciar la aplicación.
- Los enlaces que envía el bot llevan directo al borrador, después de iniciar sesión. Si la
  página pedida es de otro rol (por ejemplo, la directora abre el enlace de un borrador), se
  entra a la página de inicio del rol.

## Despliegue en Render

El servidor público (HTTPS, necesario para los webhooks de Telegram y WhatsApp) corre en el plan
gratuito de [Render](https://render.com), con PostgreSQL. Todo lo que necesita está descrito en
`render.yaml`.

1. Crea una cuenta en Render. Como el repositorio es público, no hace falta conectar GitHub.
2. En el panel, elige **New → Blueprint**, pega la URL del repositorio y elige la rama. Render
   lee `render.yaml` y crea el servicio web y la base de datos.
3. Completa los secretos que pide:
   - `TELEGRAM_BOT_TOKEN`: el token de un bot para el servidor, distinto del que usas en local;
   - `TELEGRAM_WEBHOOK_SECRET`: genéralo con
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`;
   - `OPENAI_API_KEY`: la key del curso;
   - `SEED_PASSWORD`: la contraseña de los usuarios de demostración.
4. Render instala las dependencias y, en cada arranque, aplica las migraciones, carga los datos
   de demostración (sin duplicarlos) y levanta la aplicación, que configura el webhook. La
   dirección pública la toma sola de `RENDER_EXTERNAL_URL`.
5. Revisa que `https://<tu-servicio>.onrender.com/health` responda `{"estado":"ok"}`. Después
   entra como `directora`, genera un enlace en Vínculos y vincula la cuenta de Telegram.

Cada push a la rama elegida vuelve a desplegar. En el plan gratuito el servicio se duerme tras
un rato sin uso, y la primera petición tarda cerca de un minuto en despertarlo: antes de una
demo, abre `/health`. Los mensajes que lleguen mientras despierta no se pierden, porque Telegram
reintenta y la cola de mensajes está en la base de datos. La base de datos gratuita también
tiene fecha de vencimiento; Render la muestra en su panel.

## Tests y lint

```bash
pytest
ruff check .
```

`pytest` corre los tests automáticos, y `ruff` revisa errores comunes (por ejemplo, imports o
variables sin usar) y el orden de los imports. GitHub Actions corre ambos en cada push: el
resultado se ve en la pestaña Actions y en el PR. Los tests no usan servicios externos.

Los tests de `tests/test_postgres.py` corren solo si `TEST_POSTGRES_URL` apunta a un
PostgreSQL. En GitHub Actions corren en un job aparte, con un PostgreSQL en un contenedor:
revisan lo que cambia respecto de SQLite (el trigger de auditoría, los SAVEPOINT y el índice
único parcial).

## Fundamento normativo

Cómo se relaciona cada medida de este módulo con la normativa (sección 15 de la especificación):

| Medida | Norma | Dónde está |
|---|---|---|
| Solo profesionales vinculados y autorizados por la directora; revocación inmediata | Ley 20.584, art. 13 (acceso solo a quienes participan en la atención); D41, art. 9 | `/vinculos`, `app/nucleo/vinculacion.py` y `app/nucleo/ingesta.py` |
| Registro de auditoría solo de inserción (recepción, procesamiento, lecturas) | D41, art. 9 (registro de accesos) | `app/nucleo/auditoria.py`, y triggers en las migraciones que impiden modificar o borrar los eventos |
| La IA genera borradores; un profesional identificado revisa; trazabilidad a la fuente y al modelo | Ley 21.719, art. 8 bis (decisiones automatizadas); Ley 20.584, art. 9; D41, art. 2 | `app/nucleo/borradores.py`; el detalle de cada borrador muestra el fragmento de cada dato, los mensajes de origen y el modelo usado |
| Seudonimización antes del LLM; proveedores sin retención ni entrenamiento | Ley 21.719, arts. 14 quáter (privacidad desde el diseño), 15 bis (encargados) y 27 (transferencia internacional) | `app/nucleo/seudonimizacion.py`; la retención depende de la cuenta del proveedor (ver [Limitaciones](#limitaciones)) |
| Mensajería solo como canal de ingreso; borrado del chat y del audio | Ley 21.719, arts. 3 (proporcionalidad) y 14 quáter | `TELEGRAM_DELETE_INCOMING`; el audio se borra al transcribirlo (`app/nucleo/procesamiento.py`) |
| HTTPS, secretos fuera del código, webhook verificado, almacenamiento privado | Ley 21.719, art. 14 quinquies (medidas de seguridad) | Render con HTTPS; secretos en `.env` o en el panel de Render; secreto del webhook en `app/canales/telegram/webhook.py` |
| Solo datos sintéticos en desarrollo y pruebas | Medida propuesta por el equipo | `scripts/sembrar_datos.py` y los tests |

"Ley 21.719, art. X" se refiere al artículo X de la Ley 19.628 en el texto fijado por la Ley
21.719.

## Limitaciones

- **Seudonimización:** solo reconoce a los residentes registrados (nombres, apellidos y apodos)
  y los RUT, teléfonos y correos. Los nombres de otras personas, como un acompañante o un
  familiar, llegan al LLM tal cual; en la demo son ficticios. Al revés, el apellido de otra
  persona que coincide con el de un residente se reemplaza igual: en "la acompañó la educadora
  Ana Rojas", "Rojas" se toma como Martina Rojas.
- **Transcripción:** un audio no se puede seudonimizar antes de transcribirlo, así que el
  proveedor de transcripción recibe los nombres reales.
- **Proveedores de IA:** la cuenta de OpenAI del curso no la administra el grupo, así que no
  podemos garantizar que no retenga los datos. En producción habría que usar una cuenta sin
  retención ni entrenamiento, o modelos locales (por ejemplo, Whisper para la transcripción).
- **Completar un borrador por el chat:** solo funciona respondiendo al mensaje del bot sobre ese
  borrador; una respuesta al "Recibido" crea un borrador nuevo.
- **Un solo proceso:** el worker es un hilo dentro de la aplicación. Con varias instancias del
  servicio, dos workers podrían tomar el mismo mensaje: antes de escalar, habría que repartir
  la cola con bloqueos en la base de datos.
- **Plan gratuito de Render:** el servicio se duerme tras unos minutos sin uso, y la primera
  petición tarda cerca de un minuto. La base de datos gratuita vence; Render muestra la fecha en
  su panel.
- **Borradores sin actividad:** solo se marcan en la web; nadie recibe un aviso.
- **WhatsApp:** todavía no está. El núcleo ya está preparado para agregarlo como otro adaptador.

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
    base.py       tipos comunes a todos los canales: MensajeNormalizado, ErrorDeCanal y
                  AdaptadorCanal
    telegram/     cliente de la Bot API, adaptador, polling y webhook
  nucleo/         lógica que no depende del canal: vinculación, ingesta, worker, auditoría,
                  seudonimización y extracción
  proveedores/    proveedores de IA intercambiables por configuración: transcripción y LLM
  web/            plataforma web: inicio de sesión, vínculos, borradores y sus plantillas
docs/             documentación detallada: telegram.md explica el bot y cómo probarlo
migrations/       migraciones de Alembic
scripts/          scripts de desarrollo, como la carga de datos de demostración
tests/            tests automáticos
```
