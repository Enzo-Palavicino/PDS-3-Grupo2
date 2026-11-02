import pytest
from pydantic import ValidationError

from app.config import Config


def test_polling_exige_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(ValidationError, match="requiere TELEGRAM_BOT_TOKEN"):
        Config(_env_file=None, telegram_mode="polling")


def test_el_token_no_aparece_al_imprimir_la_configuracion():
    config = Config(_env_file=None, telegram_mode="polling", telegram_bot_token="123:secreto")

    assert "secreto" not in repr(config)
    assert config.telegram_bot_token.get_secret_value() == "123:secreto"
