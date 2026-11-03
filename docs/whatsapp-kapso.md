# WhatsApp con Kapso

## 1. Preparar Kapso

1. Entra en [Kapso](https://app.kapso.ai/) y crea o elige el proyecto del equipo.
2. Conecta un número de WhatsApp desde la sección de números (PHONE NUMBERS- SANDBOX- ADD SESSION). Sigue las instrucciones de activación y destinatarios
   habilitados del panel. Un sandbox que solo simula mensajes no reemplaza la prueba desde un celular.
3. Copia el `Phone Number ID` del número conectado y su número visible. Son distintos: el ID
   identifica la conexión; el número visible sirve para abrir el chat.
4. En `Integrations → API keys`, crea una clave del mismo proyecto. Guárdala solo en `.env`.

## 2. Preparar la aplicación

```bash
source .venv/bin/activate
```

```dotenv
WHATSAPP_ENABLED=true
KAPSO_API_KEY=<clave del proyecto de Kapso>
KAPSO_PHONE_NUMBER_ID=<id numerico de la conexion>
KAPSO_WEBHOOK_SECRET=<secreto aleatorio>
WHATSAPP_PHONE_NUMBER=<numero internacional solo digitos>
PUBLIC_BASE_URL=https://<dominio publico o tunel>
SECRET_KEY=<clave de sesion estable>
SEED_PASSWORD=<contrasena para los usuarios de demostracion>
```

Por ejemplo, un teléfono chileno se escribe `56912345678`, sin `+`, espacios ni guiones.
Genera un secreto para el webhook y otro distinto para la sesión:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Para probar solo WhatsApp, usa `TELEGRAM_MODE=off`.

Para comprobar transporte sin consumir IA, deja `STT_PROVIDER=fake` y `LLM_PROVIDER=fake`.
En ese modo la transcripción es de prueba y los campos quedan vacíos: no sirve para demostrar IA.
Para la demo completa configura `STT_PROVIDER=openai`, `LLM_PROVIDER=openai` y la
`OPENAI_API_KEY` del curso.

Prepara las tablas y los datos ficticios:

```bash
alembic upgrade head
python -m scripts.sembrar_datos
```

## 3. Darle una URL pública

Kapso necesita llegar al computador por HTTPS. Para desarrollo puedes usar un túnel:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

Mantén esa terminal abierta. Copia la URL `https://...trycloudflare.com` que indique el túnel a
`PUBLIC_BASE_URL` en `.env`. En otra terminal, con el entorno activado, inicia la aplicación:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Abre `https://TU-DOMINIO/health`: debe responder `{"estado":"ok"}`. Usa también esa dirección
HTTPS para entrar a la web; con esta configuración la cookie de sesión no se envía por HTTP.

Si reinicias el túnel y cambia su URL, actualiza `.env`, reinicia la aplicación y cambia el webhook
en Kapso. Durante la demo deben seguir abiertos el túnel y el servidor. Usa una sola instancia del servidor/worker.

En Render puedes usar el servicio existente: configura estas mismas variables en Environment,
con la URL pública del servicio, y despliega la rama que contenga la integración. Este cambio
no despliega ni modifica automáticamente el servicio del equipo. WhatsApp queda apagado por defecto.

## 4. Registrar el webhook en Kapso

Con la aplicación accesible desde su URL HTTPS y el `.env` completo, ejecuta una vez:

```bash
python -m scripts.configurar_whatsapp
```

La herramienta consulta los webhooks y crea uno si no existe otro con esa URL. No imprime
credenciales ni envía mensajes. Si ya existe, no lo modifica: revísalo en el panel.

La configuración que debe quedar en Kapso es:

| Campo | Valor |
|---|---|
| Alcance | Webhook del número de WhatsApp conectado |
| Tipo (`kind`) | `kapso` |
| Formato | `v2` (predeterminado para webhooks nuevos) |
| URL | `https://TU-DOMINIO/webhooks/whatsapp` |
| Evento | `whatsapp.message.received` |
| Secret key | El mismo valor de `KAPSO_WEBHOOK_SECRET` |
| Active | Activado |
| Buffering | Desactivado (también se admiten lotes v2) |

No uses un webhook de proyecto/Platform ni el reenvío de tipo `meta`: sus payloads son distintos.
La autenticación usa `X-Webhook-Signature`, una firma HMAC-SHA256 del cuerpo original.
No hay un token de verificación GET que debas completar en esta aplicación.

