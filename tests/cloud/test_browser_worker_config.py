from __future__ import annotations

from nanobot.browser_worker.config import BrowserWorkerSettings


def test_browser_worker_settings_fall_back_to_cloud_env(monkeypatch, tmp_path):
    config_path = tmp_path / "platform.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("NANOBOT_CLOUD_NANOBOT_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("NANOBOT_CLOUD_AUTH__SHARED_SECRET", "test-secret-value-long-enough")
    monkeypatch.setenv("NANOBOT_CLOUD_S3__BUCKET", "test-bucket")
    monkeypatch.setenv("NANOBOT_CLOUD_REDIS__URL", "redis://:123456@127.0.0.1:6379/0")
    monkeypatch.setenv("NANOBOT_CLOUD_REDIS__MODE", "single")
    monkeypatch.setenv("NANOBOT_CLOUD_REDIS__KEY_PREFIX", "nanobot-cloud")

    settings = BrowserWorkerSettings.load()

    assert settings.redis_url == "redis://:123456@127.0.0.1:6379/0"
    assert settings.redis_mode == "single"
    assert settings.redis_key_prefix == "nanobot-cloud"


def test_browser_worker_settings_prefer_worker_specific_env(monkeypatch, tmp_path):
    config_path = tmp_path / "platform.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("NANOBOT_CLOUD_NANOBOT_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("NANOBOT_CLOUD_AUTH__SHARED_SECRET", "test-secret-value-long-enough")
    monkeypatch.setenv("NANOBOT_CLOUD_S3__BUCKET", "test-bucket")
    monkeypatch.setenv("NANOBOT_CLOUD_REDIS__URL", "redis://:cloud@127.0.0.1:6379/0")
    monkeypatch.setenv("NANOBOT_BROWSER_WORKER_REDIS_URL", "redis://:worker@127.0.0.1:6379/1")

    settings = BrowserWorkerSettings.load()

    assert settings.redis_url == "redis://:worker@127.0.0.1:6379/1"
