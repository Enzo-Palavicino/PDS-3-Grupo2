# Integración con Telegram

Esta guía explica cómo funciona el bot de Telegram de la plataforma, de punta a punta, y cómo
probarlo: con los tests automáticos, a mano en local y en el servidor. Para instalar el proyecto,
las variables de entorno y el despliegue en Render, revisa el [README](../README.md).

**En resumen:** un profesional vinculado le envía al bot un texto o una nota de voz con los datos
de una atención. La aplicación guarda el mensaje, transcribe el audio, reemplaza los nombres de
los residentes por códigos, le pide a la IA los campos del Registro de Atención y deja un
**borrador** para revisar en la web. El bot responde con un mensaje corto, sin datos clínicos,
con el enlace al borrador.

## Contenido

1. [Recorrido de un mensaje](#1-recorrido-de-un-mensaje)
2. [Recepción: polling o webhook](#2-recepción-polling-o-webhook)
3. [Qué acepta el bot](#3-qué-acepta-el-bot)
4. [Vinculación de cuentas](#4-vinculación-de-cuentas)
5. [Respuestas inmediatas](#5-respuestas-inmediatas)
6. [Procesamiento en segundo plano](#6-procesamiento-en-segundo-plano)
7. [Borradores y respuestas del bot](#7-borradores-y-respuestas-del-bot)
8. [Seguridad y privacidad](#8-seguridad-y-privacidad)
9. [Configuración](#9-configuración)
10. [Cómo probarlo](#10-cómo-probarlo)
11. [Solución de problemas](#11-solución-de-problemas)
12. [Archivos](#12-archivos)

## 1. Recorrido de un mensaje

```
Telegram
   │  polling (en local) o webhook (en el servidor)
   ▼
AdaptadorTelegram      traduce el update de Telegram a un MensajeNormalizado
   ▼
ingesta                vincula la cuenta, rechaza a quien no está vinculado o guarda el
   │                   mensaje, y responde de inmediato ("Recibido")
   ▼
mensajes_entrantes     la cola: el mensaje queda guardado en la base de datos
   ▼
worker                 en segundo plano:
                         1. descarga y transcribe el audio
                         2. seudonimiza el texto y extrae los campos con la IA
                         3. arma el borrador, o completa uno existente
                         4. responde en el chat con el número del borrador
   ▼
plataforma web         el profesional y la encargada de salud revisan el borrador
```

Todo lo propio de Telegram está en `app/canales/telegram/`. El resto (`app/nucleo/`,
`app/proveedores/` y `app/web/`) no sabe por qué canal llegó el mensaje: solo conoce la interfaz
`AdaptadorCanal` y el `MensajeNormalizado` de `app/canales/base.py`. Por eso agregar WhatsApp
consiste en escribir otro adaptador. Un test (`tests/nucleo/test_independencia.py`) falla si el
núcleo importa algo de un canal en particular.

## 2. Recepción: polling o webhook

`TELEGRAM_MODE` elige cómo llegan los mensajes:

| | `polling` | `webhook` |
|---|---|---|
| Dónde se usa | En local, para desarrollar | En el servidor (Render) |
| Cómo llegan los mensajes | La aplicación le pide a Telegram los nuevos con `getUpdates` | Telegram envía cada uno con un POST a `/webhooks/telegram` |
| Qué necesita | Solo el token | El token, `TELEGRAM_WEBHOOK_SECRET` y una `PUBLIC_BASE_URL` con https |
| Código | `app/canales/telegram/polling.py` | `app/canales/telegram/webhook.py` |

Con `TELEGRAM_MODE=off`, el valor por defecto, la aplicación no recibe mensajes, pero la web
funciona. Es el modo de los tests y de GitHub Actions.

### Polling

Un hilo llama a `getUpdates` una y otra vez. Es *long polling*: si no hay mensajes nuevos,
Telegram mantiene la petición abierta hasta 30 segundos antes de responder. Cada respuesta trae
una lista de *updates*, y el siguiente `getUpdates` lleva `offset` = último `update_id` + 1, que
le confirma a Telegram lo recibido para que no lo vuelva a enviar. Solo se piden los updates de
tipo `message`.

Si Telegram falla, el polling espera y reintenta: 2 s la primera vez y el doble cada vez, hasta
60 s. Si Telegram indica cuánto esperar (error 429, por exceso de peticiones), espera eso. Dos
errores dejan un mensaje propio en el log:

- **401**: Telegram rechazó el token.
- **409**: ese bot tiene un webhook activo, u otra instancia está usando el mismo token.

### Webhook

Al arrancar en modo webhook, la aplicación llama a `setWebhook` con:

- la URL `PUBLIC_BASE_URL` + `/webhooks/telegram` (en Render, `PUBLIC_BASE_URL` se toma sola de
  `RENDER_EXTERNAL_URL`);
- el secreto `TELEGRAM_WEBHOOK_SECRET`, que Telegram devuelve en el encabezado
  `X-Telegram-Bot-Api-Secret-Token` de cada petición;
- `allowed_updates=["message"]`.

Con cada POST a `/webhooks/telegram`, la ruta:

1. responde **404** si la aplicación no está en modo webhook;
2. responde **401** si el encabezado no trae el secreto correcto, sin procesar el contenido (la
   comparación tarda lo mismo acierte o no, con `hmac.compare_digest`);
3. responde **400** si el cuerpo no es JSON;
4. guarda el mensaje (ver [Respuestas inmediatas](#5-respuestas-inmediatas)) y responde
   `{"ok": true}`.

Las respuestas al chat se envían **después** de contestarle a Telegram, y la transcripción y la
IA las hace el worker: así Telegram nunca espera. Si Telegram no recibe un 200, reenvía el mismo
update; la ingesta lo reconoce y no lo guarda dos veces.

Un bot con webhook activo no funciona con polling: Telegram responde 409 a `getUpdates`. Por eso
se usa un bot para el servidor y otro, de cada integrante, para desarrollar. El script
`scripts/telegram_webhook.py` muestra, borra o configura el webhook del bot de
`TELEGRAM_BOT_TOKEN`:

```bash
python -m scripts.telegram_webhook info     # URL configurada, updates pendientes y último error
python -m scripts.telegram_webhook delete   # borra el webhook: el bot vuelve a servir para polling
python -m scripts.telegram_webhook set      # lo configura a mano (en el servidor no hace falta)
```

## 3. Qué acepta el bot

`AdaptadorTelegram.parsear` (`app/canales/telegram/adaptador.py`) traduce cada update:

| Update | Resultado |
|---|---|
| Texto en un chat privado | `texto`; si empieza con `/`, `comando` (`/start`, `/ayuda`, …) |
| Nota de voz (`voice`) o archivo de audio (`audio`) | `audio`, con su `file_id`, tipo, tamaño y duración |
| Sticker, foto, documento, ubicación, etc. | `no_soportado`: el bot responde que solo recibe texto o audio |
| Cualquier mensaje de un grupo o canal | Se ignora, sin respuesta |
| Mensaje de otro bot | Se ignora |
| Mensaje editado y otros tipos de update | Se ignoran |

De cada mensaje se guarda:

- `id_externo` = `"<chat.id>:<message_id>"`: identifica el mensaje y evita guardarlo dos veces;
- `remitente_externo` = `from.id`: la cuenta de Telegram, que se compara con los vínculos;
- `destino_respuesta` = `chat.id`: dónde responder;
- `responde_a_id_externo`: si el mensaje es una respuesta (*reply*), el id del mensaje citado.
  Con él se completan los borradores (ver [sección 7](#7-borradores-y-respuestas-del-bot)).

## 4. Vinculación de cuentas

El bot solo acepta registros de cuentas vinculadas a un profesional, y solo la directora
autoriza cuentas:

1. La directora entra a `/vinculos` y pulsa **Generar enlace** en la fila del profesional. Se
   crea un código de un solo uso que vence en 10 minutos: 32 caracteres al azar
   (`secrets.token_urlsafe(24)`), imposibles de adivinar.
2. La página muestra el enlace `https://t.me/<bot>?start=<código>` y su código QR. Si no pudo
   consultar el nombre del bot (con `getMe`), muestra en su lugar el mensaje `/start <código>`,
   para enviarlo a mano.
3. El profesional abre el enlace (o escanea el QR) y pulsa **Iniciar**. Telegram le envía al bot
   `/start <código>`.
4. La aplicación marca el código como usado en una sola operación, que exige que siga vigente y
   sin usar: si dos personas lo canjean a la vez, solo una lo logra. Después crea el vínculo
   entre la cuenta de Telegram y el profesional, y el bot responde *"Cuenta vinculada…"*.

Además:

- Una cuenta de Telegram queda vinculada a un solo profesional a la vez: si canjea el código de
  otro, el vínculo anterior se cierra.
- La directora puede **revocar** un vínculo en `/vinculos`. Desde ese momento, la cuenta recibe
  *"Esta cuenta no está autorizada…"*; lo que envió antes conserva su autoría.
- La auditoría registra la generación y el canje (exitoso o rechazado) de los códigos, la
  creación y la revocación de los vínculos, y los mensajes rechazados. Nunca guarda el código
  ni el contenido de un mensaje.
- El enlace también se puede generar desde la consola: `python -m scripts.generar_codigo
  pediatra` imprime el del profesional de ese usuario web.

## 5. Respuestas inmediatas

La ingesta (`app/nucleo/ingesta.py`) decide qué hacer con cada mensaje, en este orden y sin
descargar audios ni llamar a la IA:

| Situación | El bot responde | ¿Se guarda? |
|---|---|---|
| `/start <código>` con un código válido | Cuenta vinculada. Ya puedes enviar registros de atención por texto o audio. | Se crea el vínculo |
| `/start <código>` con un código vencido, usado o inexistente | El código no es válido o ya venció. Pide uno nuevo a la dirección. | No |
| `/start` sin código, de una cuenta sin vincular | Hola. Este bot recibe registros de atención del Hogar Misión de María. Para usarlo, pide a la dirección un enlace de vinculación. | No |
| Cualquier otro mensaje de una cuenta sin vincular | Esta cuenta no está autorizada para enviar registros. | No; queda un evento de auditoría, sin el contenido |
| Un comando de una cuenta vinculada (`/start`, `/ayuda` u otro) | Envía un texto o un audio con los datos de la atención: residente, fecha, diagnóstico, indicaciones, próximo control y acompañante. | No |
| Un tipo no soportado | Solo puedo recibir mensajes de texto o de audio. | No |
| Un audio de más de 20 MB (lo máximo que Telegram deja descargar a un bot) | El audio es demasiado largo. Envíalo en partes más cortas. | No |
| Un texto o un audio de una cuenta vinculada | Recibido. Estoy procesando el registro. | Sí, en `mensajes_entrantes`, con estado `recibido` |
| Un mensaje que ya se guardó (Telegram lo reenvió) | Nada | No |

Las respuestas sobre un mensaje aparecen citándolo. Si falla el envío de una respuesta, queda en
el log y se sigue: el mensaje ya está guardado y el worker lo procesa igual.

## 6. Procesamiento en segundo plano

El worker (`app/nucleo/worker.py`) es un hilo dentro de la misma aplicación, que usa la tabla
`mensajes_entrantes` como cola. Revisa la cola cada 5 segundos, o apenas la ingesta le avisa que
llegó algo, y procesa los mensajes de a uno, en orden de llegada. Al empezar cada uno, muestra
"escribiendo…" en el chat.

Los pasos (`app/nucleo/procesamiento.py`) dependen del estado del mensaje, y cada uno guarda su
avance antes del siguiente:

```
recibido ─(audio: descargar y transcribir)─► transcrito ─(IA y borrador)─► extraido ─(responder)─► listo
```

- **Transcripción:** el audio se descarga con `getFile` a un archivo temporal en `AUDIO_DIR`, se
  transcribe con el proveedor de `STT_PROVIDER` y se borra al terminar el intento, aunque haya
  fallado. Si al arrancar queda algún audio de un intento interrumpido, el worker lo borra. La
  transcripción queda en la tabla `transcripciones` y nunca se envía al chat. Un texto se salta
  este paso.
- **IA y borrador:** ver la [sección 7](#7-borradores-y-respuestas-del-bot).
- **Respuesta:** el bot responde citando el mensaje del profesional y guarda en el borrador el id
  de su propio mensaje, para reconocer las respuestas que lo completen.

Antes de cada llamada a Telegram o a OpenAI, el worker cierra su transacción de la base de datos.
Esas llamadas tardan segundos, y en SQLite una transacción abierta bloquearía las escrituras de
la web y de la ingesta.

**Si un paso falla**, el worker guarda solo el tipo de error y lo reintenta desde ese mismo paso:
a los 10 s y a los 60 s, o lo que pida Telegram si es más (por ejemplo, un 429 con
`retry_after`). Así, si falló el envío de la respuesta, no se vuelve a llamar a la IA. Al tercer
fallo, el mensaje queda en estado `error` y el bot avisa: *"No pude procesar el mensaje.
Inténtalo de nuevo o registra la atención en la plataforma."*

## 7. Borradores y respuestas del bot

Con el texto, escrito o transcrito:

1. **Seudonimización** (`app/nucleo/seudonimizacion.py`): los nombres, apellidos y apodos de los
   residentes se reemplazan por su código (`[RES-02]`), y los RUT, teléfonos y correos por
   `[RUT]`, `[TEL]` y `[EMAIL]`. No distingue mayúsculas ni tildes y tolera errores menores de
   transcripción. Un nombre que comparten dos residentes queda como `[RES-01|RES-04]`.
2. **Extracción** (`app/nucleo/extraccion.py`): el LLM de `LLM_PROVIDER` recibe solo el texto
   seudonimizado y devuelve los campos del Registro de Atención en un JSON que tiene que cumplir
   un esquema. Cada dato trae el fragmento del texto que lo respalda, y se descarta lo que no lo
   tiene.
3. **Borrador** (`app/nucleo/borradores.py`): se calcula lo que falta y se guarda el borrador,
   que nunca es una atención registrada.

Las reglas de los borradores están resumidas en el
[README](../README.md#borradores-y-respuestas-del-bot). Lo propio del chat es lo siguiente.

**Qué responde el bot** (`app/nucleo/textos.py`). Nunca envía datos clínicos: solo el número del
borrador, las iniciales del residente, lo que falta y el enlace a la plataforma.

| Caso | Respuesta |
|---|---|
| Borrador completo | Borrador #{id} creado (residente {iniciales}). Revísalo en la plataforma: {url} |
| Faltan datos | Borrador #{id} creado (residente {iniciales}). Falta: {faltantes}. Responde a este mensaje con los datos o complétalos en la plataforma: {url} |
| No se identificó al residente | Borrador #{id} creado, pero no pude identificar al residente. Respóndeme con su nombre o complétalo en la plataforma: {url} |
| Completado por respuesta, sin faltantes | Borrador #{id} actualizado (residente {iniciales}). Revísalo en la plataforma: {url} |
| Completado por respuesta, aún con faltantes | Borrador #{id} actualizado (residente {iniciales}). Aún falta: {faltantes}. Complétalo en la plataforma: {url} |
| Completado por respuesta, aún sin residente | Borrador #{id} actualizado, pero todavía no pude identificar al residente. Complétalo en la plataforma: {url} |
| Una pregunta, como "¿qué alergias tiene…?" | Por este canal solo puedo recibir registros. Consulta la ficha en la plataforma. |

**Completar un borrador respondiendo.** Si el profesional usa **Responder** sobre el mensaje del
bot de un borrador pendiente suyo, su respuesta se suma a ese borrador: la IA recibe los textos
juntos y el borrador se actualiza. Lo que falta se pide una sola vez; las respuestas siguientes
solo lo informan. Crean, en cambio, un borrador nuevo:

- un mensaje enviado sin **Responder**;
- una respuesta al *"Recibido…"* o a cualquier mensaje que no sea el del borrador;
- una respuesta a un borrador ya descartado o de otro profesional.

**Borrado del chat.** Con `TELEGRAM_DELETE_INCOMING=true`, que se usa en el servidor, el bot
borra del chat el mensaje del profesional después de responderle, para que el registro no quede
en el teléfono. Telegram solo permite borrar mensajes de menos de 48 horas; si el borrado falla,
queda en el log y no se reintenta.

## 8. Seguridad y privacidad

- **Token del bot:** va solo en `.env` o en las variables de Render, nunca en el repositorio. La
  configuración lo guarda como `SecretStr` (se imprime como `**********`), los errores de la Bot
  API nunca incluyen la URL, que lo lleva, y los logs de la librería HTTP están silenciados por
  la misma razón.
- **Webhook:** solo se aceptan las peticiones con el secreto; las demás reciben 401.
- **Solo chats privados** de cuentas vinculadas. Al crear el bot, desactiva los grupos en
  @BotFather (`/setjoingroups` → Disable).
- **Logs:** solo ids, estados y tipos de error; nunca el contenido de los mensajes ni datos
  clínicos. Con `LOG_LEVEL=DEBUG` se agregan las trazas completas de los errores, que sí pueden
  traer datos: úsalo solo en desarrollo, con datos ficticios.
- **Audios:** se borran al terminar cada intento de transcripción. Las transcripciones quedan en
  la base de datos, nunca en el chat.
- **IA:** el LLM nunca recibe los nombres de los residentes. El proveedor de transcripción, en
  cambio, recibe el audio tal cual (ver las [limitaciones](../README.md#limitaciones)).

## 9. Configuración

Las variables de la integración (la lista completa está en el
[README](../README.md#variables-de-entorno)):

| Variable | En local | En el servidor |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | El token de tu bot de desarrollo | El token del bot del servidor |
| `TELEGRAM_MODE` | `polling` | `webhook` |
| `TELEGRAM_WEBHOOK_SECRET` | No se usa | 1 a 256 letras, números, `_` o `-` |
| `TELEGRAM_DELETE_INCOMING` | `false` | `true` |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Se toma sola de `RENDER_EXTERNAL_URL` |
| `STT_PROVIDER` y `LLM_PROVIDER` | `fake` u `openai` | `openai` |
| `OPENAI_API_KEY` | La key del curso, si usas `openai` | La key del curso |

Si falta algo obligatorio, la aplicación no arranca y dice qué falta, por ejemplo:
`TELEGRAM_MODE=polling requiere TELEGRAM_BOT_TOKEN`.

## 10. Cómo probarlo

### 10.1 Tests automáticos

```bash
pytest                          # todos los tests
pytest tests/canales            # solo lo propio de Telegram
pytest tests/nucleo tests/web   # el núcleo y la plataforma web
pytest -k webhook -v            # los que tienen "webhook" en el nombre, con detalle
```

Ningún test sale a internet ni usa API keys:

- `tests/canales/updates/` tiene updates de Telegram con datos ficticios: texto, nota de voz,
  archivo de audio, sticker, chat de grupo, `/start <código>`, respuesta a un mensaje y mensaje
  editado.
- El cliente de la Bot API se prueba con un transporte HTTP falso, que guarda cada petición en
  vez de enviarla.
- El núcleo usa un canal falso (`CanalFalso`, en `tests/nucleo/conftest.py`) y los proveedores
  `fake` de transcripción y de LLM.

| Archivo | Qué comprueba |
|---|---|
| `tests/canales/test_telegram_adaptador.py` | El resultado de cada tipo de update; el secreto del webhook; enviar citando un mensaje; borrar; "escribiendo…"; descargar una nota de voz |
| `tests/canales/test_telegram_cliente.py` | Las llamadas a la Bot API; que ningún error, ni siquiera uno de red, exponga el token; el 429 con su espera |
| `tests/canales/test_telegram_polling.py` | El orden de los updates y el offset; que un error no detenga el lote ni registre el contenido; los reintentos |
| `tests/canales/test_telegram_webhook.py` | `setWebhook` al arrancar; 401 sin el secreto o con uno distinto; que un reenvío de Telegram no duplique el mensaje; 400 y 404 |
| `tests/nucleo/test_vinculacion.py` | Códigos válidos, vencidos y reutilizados; revocación; cambio de profesional; auditoría sin el código |
| `tests/nucleo/test_ingesta.py` | Cada fila de la tabla de [respuestas inmediatas](#5-respuestas-inmediatas), y que una respuesta fallida no haga perder el mensaje |
| `tests/nucleo/test_procesamiento.py` | La transcripción, el borrado del audio (también si falla) y el "escribiendo…" |
| `tests/nucleo/test_worker.py` | Los reintentos y sus esperas, también la que pide el canal; el estado `error` con su aviso; que la web pueda escribir mientras la IA responde |
| `tests/nucleo/test_borradores.py` | Los tres guiones de la demo; completar un borrador respondiendo; las consultas; el borrado del chat; los borradores sin actividad |
| `tests/nucleo/test_independencia.py` | Que el núcleo no importe nada propio de Telegram |

### 10.2 Prueba manual en local (polling)

Antes de empezar necesitas:

- el proyecto instalado (ver [Instalación local](../README.md#instalación-local));
- un bot propio para desarrollar, creado con @BotFather (ver
  [Crear el bot](../README.md#crear-el-bot));
- en `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_MODE=polling`, `SEED_PASSWORD` y `SECRET_KEY`; y,
  para usar la IA y la transcripción reales, `STT_PROVIDER=openai`, `LLM_PROVIDER=openai` y
  `OPENAI_API_KEY`.

Con los proveedores `fake`, el flujo completo funciona sin API key, pero el borrador queda casi
vacío: el residente se identifica, porque lo decide la seudonimización, pero los demás campos
no. Además, toda nota de voz se "transcribe" como *Transcripción de prueba*.

1. Crea la base de datos y carga los datos de demostración:

   ```bash
   alembic upgrade head
   python -m scripts.sembrar_datos
   ```

2. Levanta la aplicación con `uvicorn app.main:app --reload`. En la consola debe aparecer
   `Polling de Telegram iniciado para @<tu_bot>`.
3. Vincula tu cuenta. Abre <http://localhost:8000>, entra como `directora` y, en **Vínculos**,
   pulsa **Generar enlace** en la fila de Carolina Fuentes (pediatría). Abre el enlace o escanea
   el QR con el celular y pulsa **Iniciar**. El bot debe responder *"Cuenta vinculada…"*, y al
   recargar **Vínculos** aparece la cuenta.
4. Envía los guiones de la demo de a uno, esperando la respuesta del bot antes de mandar el
   siguiente. Primero llega *"Recibido…"* y, unos segundos después, la respuesta sobre el
   borrador:

   | Guion | Envíalo como | Respuesta esperada (con `openai`) |
   |---|---|---|
   | Hoy atendí a Emilia Soto en el Hogar. Control pediátrico, cuadro de bronquiolitis leve. Indico salbutamol dos puff cada seis horas por cinco días y aseo nasal. Control en dos semanas. La acompañó la educadora María Pérez. | Texto | Borrador #1 creado (residente E. S.). Revísalo en la plataforma: … |
   | Martina Rojas, evaluación nutricional, peso adecuado para su edad, se mantiene la minuta actual. | Nota de voz, leyéndolo en voz alta | Borrador #2 creado (residente M. R.). Falta: fecha de atención, próximo control, acompañante (nombre y cargo). … |
   | Atendí a Tomás por una otitis, amoxicilina cada doce horas por diez días. | Nota de voz | Borrador #3 creado, pero no pude identificar al residente. … (hay dos residentes llamados Tomás) |

5. Completa el borrador #3. Mantén presionado el mensaje del bot *"Borrador #3 creado…"* (o
   deslízalo hacia la izquierda), elige **Responder** y escribe `Tomás Rivas`. Antes de enviar,
   sobre el cuadro de texto debe aparecer la cita del mensaje del bot. Respuesta esperada:
   *"Borrador #3 actualizado (residente T. R.). Aún falta: fecha de atención, próximo control,
   acompañante (nombre y cargo). …"*
6. Envía una pregunta, como *¿Qué alergias tiene Emilia Soto?* Respuesta esperada: *"Por este
   canal solo puedo recibir registros…"*, y no se crea borrador.
7. Revisa la web: entra como `pediatra` (o `encargada_salud`) y abre los borradores. Cada dato
   aparece con su fragmento de origen, los audios muestran su transcripción y "Procesamiento con
   IA" muestra lo que recibió el LLM, ya seudonimizado.
8. Prueba también los casos de rechazo:
   - un sticker o una foto: *"Solo puedo recibir mensajes de texto o de audio."*;
   - `/ayuda`: el mensaje de ayuda;
   - revoca el vínculo en **Vínculos** (como `directora`) y envía otro mensaje: *"Esta cuenta no
     está autorizada para enviar registros."*;
   - desde otra cuenta de Telegram, sin vincular: la misma respuesta.

La numeración de los borradores supone una base de datos nueva. Para partir de cero (por ejemplo,
antes de una demo), detén la aplicación y borra la base de datos local:

```bash
Remove-Item data\app.db*   # PowerShell
rm -f data/app.db*         # bash
```

Después repite el paso 1 y vuelve a vincular tu cuenta.

### 10.3 Prueba en el servidor (webhook)

El despliegue se explica en el README ([Despliegue en Render](../README.md#despliegue-en-render)).
Para comprobar que funciona:

1. Abre `https://<servicio>.onrender.com/health`: debe responder `{"estado":"ok"}`. Si el
   servicio estaba dormido, tarda cerca de un minuto.
2. En los logs del servicio (panel de Render → **Logs**), al arrancar debe aparecer
   `Webhook de Telegram configurado en https://<servicio>.onrender.com/webhooks/telegram`. Si en
   cambio aparece `No se pudo configurar el webhook de Telegram`, revisa `TELEGRAM_BOT_TOKEN`.
3. Repite los pasos 3 a 7 de la prueba local con el bot del servidor, en
   `https://<servicio>.onrender.com`. Ahí `TELEGRAM_DELETE_INCOMING` está activado, así que tus
   mensajes desaparecen del chat después de procesarse: es lo esperado.

Para revisar el webhook desde tu computador, pon el token del bot del servidor solo en esa
terminal, donde tiene prioridad sobre `.env`, y ciérrala al terminar:

```powershell
$env:TELEGRAM_BOT_TOKEN = "<token del bot del servidor>"
python -m scripts.telegram_webhook info
```

Debe mostrar la URL del servidor y ningún error. No uses `delete` con ese token: el bot del
servidor dejaría de recibir mensajes hasta que la aplicación vuelva a arrancar.

### 10.4 Antes de la demo

- Abre `/health` del servidor unos minutos antes, para despertarlo.
- En **Vínculos**, confirma que la cuenta que vas a usar está vinculada al profesional correcto.
  La especialidad del borrador sale del profesional: para que el guion 2 quede como nutrición,
  envíalo desde una cuenta vinculada a Felipe Araya.
- Practica el paso de **Responder** sobre el mensaje *"Borrador #…"*: es el más fácil de
  equivocar.
- Descarta en la web los borradores de prueba que no quieras mostrar.
- Ten a mano los guiones, para leerlos en voz alta.

## 11. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| La aplicación no arranca y dice `requiere TELEGRAM_BOT_TOKEN` (u otra variable) | Falta esa variable para el modo elegido | Complétala en `.env` o en Render |
| Log: `Telegram rechazó el token del bot` | El token está mal copiado o se revocó en @BotFather | Copia el token actual en `TELEGRAM_BOT_TOKEN` |
| Log: `Telegram rechazó getUpdates porque hay un webhook activo…` | Ese bot tiene webhook (por ejemplo, es el del servidor) u otra instancia lo usa | En local, usa tu propio bot; si el webhook sobra, `python -m scripts.telegram_webhook delete` |
| El bot no responde en local | La aplicación no está corriendo o `TELEGRAM_MODE` no es `polling` | Revisa que la consola diga `Polling de Telegram iniciado` |
| El bot del servidor no responde | El servicio estaba dormido o no se configuró el webhook | Espera un minuto y revisa `/health` y los logs (ver [10.3](#103-prueba-en-el-servidor-webhook)) |
| *"Esta cuenta no está autorizada…"* | La cuenta no está vinculada o se revocó su vínculo | Genera un enlace nuevo en **Vínculos** |
| *"El código no es válido o ya venció"* | El enlace tiene más de 10 minutos o ya se usó | Genera otro |
| **Vínculos** muestra `/start <código>` en vez del QR | La aplicación no pudo consultar el bot: token incorrecto o sin conexión | Revisa `TELEGRAM_BOT_TOKEN`; mientras tanto, envía ese mensaje al bot |
| Llegó *"Recibido"*, pero nunca la respuesta sobre el borrador | Un paso está fallando (por ejemplo, la API de OpenAI) y se está reintentando | Busca en los logs `Falló el procesamiento del mensaje N` con el tipo de error. Al tercer fallo, el bot avisa |
| Responder no completó el borrador: se creó otro | Se envió sin **Responder**, o se respondió al *"Recibido…"* | Responde sobre el mensaje *"Borrador #…"* y descarta el borrador que sobra |
| Una nota de voz dio un borrador raro | La transcripción tuvo errores | Abre el borrador: la transcripción está en "Mensajes de origen" |
| El borrador del guion 2 dice pediatría | La especialidad sale del profesional vinculado | Envíalo desde una cuenta vinculada al nutricionista |

## 12. Archivos

```
app/canales/base.py            MensajeNormalizado, Ignorado, ErrorDeCanal y la interfaz AdaptadorCanal
app/canales/telegram/
  cliente.py                   cliente mínimo de la Bot API, que nunca expone el token
  adaptador.py                 update de Telegram → MensajeNormalizado; responder, borrar y descargar
  polling.py                   recepción con getUpdates (en local)
  webhook.py                   recepción con POST /webhooks/telegram (en el servidor)
app/nucleo/
  ingesta.py                   vincular, autorizar, guardar y responder de inmediato
  vinculacion.py               códigos de un solo uso, vínculos y revocación
  worker.py                    cola en segundo plano y reintentos
  procesamiento.py             pasos de cada mensaje: transcribir, extraer y responder
  seudonimizacion.py           reemplazo de los nombres de los residentes antes de la IA
  extraccion.py                pedido al LLM y validación de lo extraído
  borradores.py                reglas de los borradores
  textos.py                    textos que envía el bot
app/web/vinculos.py            /vinculos: enlace, código QR y revocación
scripts/generar_codigo.py      enlace de vinculación desde la consola
scripts/telegram_webhook.py    ver, borrar o configurar el webhook
tests/canales/                 tests de Telegram y updates de ejemplo
```
