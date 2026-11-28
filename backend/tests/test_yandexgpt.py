import pytest
from app import yandexgpt
from app.config import settings
from pydantic import SecretStr


def test_yandexgpt_request_uses_server_credentials_and_minimal_russian_context(monkeypatch):
    monkeypatch.setattr(settings, "yandexgpt_enabled", True)
    monkeypatch.setattr(settings, "yandexgpt_api_key", SecretStr("synthetic-test-api-key"))
    monkeypatch.setattr(settings, "yandexgpt_folder_id", "synthetic-folder-123")
    monkeypatch.setattr(settings, "yandexgpt_model_version", "latest")
    monkeypatch.setattr(
        settings,
        "yandexgpt_model_uri",
        "gpt://synthetic-folder-123/yandexgpt-4-lite/latest",
    )

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        @staticmethod
        def json():
            return {
                "choices": [{
                    "message": {"content": "Черновик заключения: Жалобы не указаны."},
                    "finish_reason": "stop",
                }]
            }

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(yandexgpt.httpx, "post", fake_post)

    result = yandexgpt.generate_conclusion(
        diagnosis_code="B18.2",
        nosology="HCV",
        complaints="Жалоб нет.",
        instructions="Оформить коротко.",
        next_step="Плановый визит — 2027-01-15.",
    )

    assert result == "Черновик заключения: Жалобы не указаны."
    assert captured["url"] == yandexgpt.CHAT_COMPLETIONS_URL
    assert captured["headers"]["Authorization"] == "Api-Key synthetic-test-api-key"
    assert captured["headers"]["x-data-logging-enabled"] == "false"
    assert captured["payload"]["model"] == "gpt://synthetic-folder-123/yandexgpt-4-lite/latest"
    assert captured["payload"]["stream"] is False
    user_message = captured["payload"]["messages"][1]["content"]
    assert "Жалоб нет." in user_message
    assert "Оформить коротко." in user_message
    assert "B18.2" in user_message
    assert "2027-01-15" in user_message
    assert "synthetic-test-api-key" not in user_message


def test_yandexgpt_uses_legacy_uri_when_instance_uri_is_not_set(monkeypatch):
    monkeypatch.setattr(settings, "yandexgpt_enabled", True)
    monkeypatch.setattr(settings, "yandexgpt_api_key", SecretStr("synthetic-test-api-key"))
    monkeypatch.setattr(settings, "yandexgpt_folder_id", "synthetic-folder-123")
    monkeypatch.setattr(settings, "yandexgpt_model_uri", None)
    monkeypatch.setattr(settings, "yandexgpt_model_version", "latest")

    _, model_uri = yandexgpt._provider_configuration()

    assert model_uri == "gpt://synthetic-folder-123/yandexgpt/latest"


def test_yandexgpt_rejects_model_uri_from_another_folder(monkeypatch):
    monkeypatch.setattr(settings, "yandexgpt_enabled", True)
    monkeypatch.setattr(settings, "yandexgpt_api_key", SecretStr("synthetic-test-api-key"))
    monkeypatch.setattr(settings, "yandexgpt_folder_id", "synthetic-folder-123")
    monkeypatch.setattr(
        settings,
        "yandexgpt_model_uri",
        "gpt://another-folder/yandexgpt-4-lite/latest",
    )

    with pytest.raises(yandexgpt.YandexGPTConfigurationError, match="ID указанного каталога"):
        yandexgpt._provider_configuration()


def test_yandexgpt_missing_credentials_fails_before_network(monkeypatch):
    monkeypatch.setattr(settings, "yandexgpt_enabled", True)
    monkeypatch.setattr(settings, "yandexgpt_api_key", None)
    monkeypatch.setattr(settings, "yandexgpt_folder_id", None)

    with pytest.raises(yandexgpt.YandexGPTConfigurationError, match="учётные данные"):
        yandexgpt.generate_conclusion(
            diagnosis_code="B18.2",
            nosology="HCV",
            complaints=None,
            instructions=None,
            next_step="План не задан.",
        )
