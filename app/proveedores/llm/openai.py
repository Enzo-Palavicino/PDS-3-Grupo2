"""LLM de OpenAI, con la API key que entregó el curso (permite usar gpt-6-luna).

El texto que recibe ya viene seudonimizado: sin nombres de residentes, RUT, teléfonos ni
correos.
"""

from typing import Any

from openai import OpenAI

from app.proveedores.llm.base import ErrorLLM, ProveedorLLM, ResultadoLLM


class ProveedorLLMOpenAI(ProveedorLLM):
    nombre = "openai"

    def __init__(self, api_key: str, modelo: str, cliente: OpenAI | None = None):
        self.modelo = modelo
        # El SDK reintenta los errores de red y los 429 (límite de uso), esperando lo que indique
        # OpenAI. Los demás reintentos los maneja el worker.
        self._cliente = cliente or OpenAI(api_key=api_key, timeout=60, max_retries=2)

    def generar_json(
        self, instrucciones: str, entrada: str, esquema: dict[str, Any]
    ) -> ResultadoLLM:
        respuesta = self._cliente.chat.completions.create(
            model=self.modelo,
            messages=[
                {"role": "system", "content": instrucciones},
                {"role": "user", "content": entrada},
            ],
            # Salida estructurada en modo estricto: el modelo solo puede generar respuestas que
            # cumplan el esquema.
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "respuesta", "strict": True, "schema": esquema},
            },
            # Extraer datos necesita poco razonamiento, y así el modelo responde más rápido.
            reasoning_effort="low",
            max_completion_tokens=6000,
        )
        opcion = respuesta.choices[0]
        if opcion.message.refusal:
            raise ErrorLLM("el modelo se negó a responder")
        if opcion.finish_reason != "stop":
            raise ErrorLLM(f"respuesta incompleta del LLM ({opcion.finish_reason})")
        return ResultadoLLM(texto=opcion.message.content or "", modelo=self.modelo)
