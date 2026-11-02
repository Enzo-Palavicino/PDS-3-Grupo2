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
AYUDA = (
    "Envía un texto o un audio con los datos de la atención: residente, fecha, diagnóstico, "
    "indicaciones, próximo control y acompañante."
)
