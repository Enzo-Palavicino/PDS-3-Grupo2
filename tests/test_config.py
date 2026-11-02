import pytest
from pydantic import ValidationError

from app.config import Config


def test_polling_exige_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(ValidationError, match="requiere TELEGRAM_BOT_TOKEN"):
        Config(_env_file=None, telegram_mode="polling")


def test_transcribir_con_openai_exige_su_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="requiere OPENAI_API_KEY"):
        Config(_env_file=None, stt_provider="openai")


def test_extraer_con_openai_exige_su_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="LLM_PROVIDER=openai requiere OPENAI_API_KEY"):
        Config(_env_file=None, llm_provider="openai")


WEBHOOK = {
    "telegram_mode": "webhook",
    "telegram_bot_token": "123:abc",
    "public_base_url": "https://pds3.example",
}


def test_el_webhook_exige_un_secreto_valido():
    with pytest.raises(ValidationError, match="requiere TELEGRAM_WEBHOOK_SECRET"):
        Config(_env_file=None, **WEBHOOK)
    # Telegram no acepta caracteres como "+" o "/" en el secreto.
    with pytest.raises(ValidationError, match="requiere TELEGRAM_WEBHOOK_SECRET"):
        Config(_env_file=None, telegram_webhook_secret="con+signos/raros", **WEBHOOK)

    assert Config(_env_file=None, telegram_webhook_secret="Secreto_valido-123", **WEBHOOK)


def test_el_webhook_exige_https():
    with pytest.raises(ValidationError, match="PUBLIC_BASE_URL con https"):
        Config(
            _env_file=None,
            **(WEBHOOK | {"public_base_url": "http://pds3.example"}),
            telegram_webhook_secret="secreto",
        )


def test_en_render_la_direccion_publica_se_toma_sola(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://pds3-grupo2.onrender.com")

    assert Config(_env_file=None).public_base_url == "https://pds3-grupo2.onrender.com"


def test_los_dias_sin_actividad_de_un_borrador_se_pueden_configurar(monkeypatch):
    monkeypatch.delenv("DIAS_SIN_ACTIVIDAD_BORRADOR", raising=False)
    assert Config(_env_file=None).dias_sin_actividad_borrador == 30

    monkeypatch.setenv("DIAS_SIN_ACTIVIDAD_BORRADOR", "7")
    assert Config(_env_file=None).dias_sin_actividad_borrador == 7

    with pytest.raises(ValidationError):
        Config(_env_file=None, dias_sin_actividad_borrador=0)


def test_el_token_no_aparece_al_imprimir_la_configuracion():
    config = Config(_env_file=None, telegram_mode="polling", telegram_bot_token="123:secreto")

    assert "secreto" not in repr(config)
    assert config.telegram_bot_token.get_secret_value() == "123:secreto"
