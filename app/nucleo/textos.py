"""Textos que envía el bot. Son cortos y nunca incluyen datos clínicos: el detalle de cada
registro se ve en la plataforma web, con inicio de sesión."""

START_SIN_CODIGO = (
    "Hola. Este bot recibe registros de atención del Hogar Misión de María. "
    "Para usarlo, pide a la dirección un enlace de vinculación."
)
VINCULACION_EXITOSA = "Cuenta vinculada. Ya puedes enviar registros de atención por texto o audio."
CODIGO_INVALIDO = "El código no es válido o ya venció. Pide uno nuevo a la dirección."
NO_AUTORIZADO = "Esta cuenta no está autorizada para enviar registros."
TIPO_NO_SOPORTADO = "Solo puedo recibir mensajes de texto o de audio."
RECIBIDO = "Recibido. Estoy procesando el registro."
AUDIO_DEMASIADO_LARGO = "El audio es demasiado largo. Envíalo en partes más cortas."
ERROR = (
    "No pude procesar el mensaje. Inténtalo de nuevo o registra la atención en la plataforma."
)
SOLO_REGISTROS = "Por este canal solo puedo recibir registros. Consulta la ficha en la plataforma."

# Respuestas sobre un borrador. El residente va solo con sus iniciales.
BORRADOR_COMPLETO = "Borrador #{id} creado (residente {iniciales}). Revísalo en la plataforma: {url}"
BORRADOR_CON_FALTANTES = (
    "Borrador #{id} creado (residente {iniciales}). Falta: {faltantes}. Responde a este mensaje "
    "con los datos o complétalos en la plataforma: {url}"
)
RESIDENTE_NO_IDENTIFICADO = (
    "Borrador #{id} creado, pero no pude identificar al residente. Respóndeme con su nombre o "
    "complétalo en la plataforma: {url}"
)
# Cuando el profesional completa un borrador respondiendo: lo que falta ya se pidió una vez, así
# que solo se informa.
BORRADOR_ACTUALIZADO = (
    "Borrador #{id} actualizado (residente {iniciales}). Revísalo en la plataforma: {url}"
)
BORRADOR_ACTUALIZADO_CON_FALTANTES = (
    "Borrador #{id} actualizado (residente {iniciales}). Aún falta: {faltantes}. Complétalo en "
    "la plataforma: {url}"
)
BORRADOR_ACTUALIZADO_SIN_RESIDENTE = (
    "Borrador #{id} actualizado, pero todavía no pude identificar al residente. Complétalo en "
    "la plataforma: {url}"
)
AYUDA = (
    "Envía un texto o un audio con los datos de la atención: residente, fecha, diagnóstico, "
    "indicaciones, próximo control y acompañante."
)
