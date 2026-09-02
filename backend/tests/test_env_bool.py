"""Strict boolean / value parsing for environment-driven configuration.

Regression cover for BASELINE_FUNCTIONAL_AUDIT SF-8 / KF (the historical
``bool(os.environ.get(...))`` bug where ``"false"`` was truthy).
"""

import pytest

from config import Settings, env_bool, env_float, env_int, env_list


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("  Yes ", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("FALSE", False),
        ("no", False),
        ("off", False),
        ("", False),
    ],
)
def test_env_bool_recognised_tokens(monkeypatch, raw, expected):
    monkeypatch.setenv("SOME_FLAG", raw)
    assert env_bool("SOME_FLAG", default=False) is expected


def test_env_bool_unset_uses_default(monkeypatch):
    monkeypatch.delenv("SOME_FLAG", raising=False)
    assert env_bool("SOME_FLAG", default=False) is False
    assert env_bool("SOME_FLAG", default=True) is True


def test_env_bool_rejects_garbage(monkeypatch):
    monkeypatch.setenv("SOME_FLAG", "flase")
    with pytest.raises(ValueError):
        env_bool("SOME_FLAG")


def test_env_helpers_numeric_and_list(monkeypatch):
    monkeypatch.setenv("N", "7")
    monkeypatch.setenv("F", "2.5")
    monkeypatch.setenv("L", " a , b ,, c ")
    assert env_int("N", 1) == 7
    assert env_float("F", 1.0) == 2.5
    assert env_list("L", []) == ["a", "b", "c"]
    with pytest.raises(ValueError):
        monkeypatch.setenv("N", "seven")
        env_int("N", 1)


def test_settings_from_env_defaults(monkeypatch):
    for name in (
        "IS_PROD",
        "IS_DEBUG_ENABLED",
        "PROMPT_REPORTS_ENABLED",
        "CORS_ALLOWED_ORIGINS",
        "OPERATOR_TOKEN",
        "OPERATOR_ENDPOINTS_PUBLIC",
        "LOG_LEVEL",
        "LOG_FORMAT",
    ):
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert s.is_prod is False
    assert s.is_debug_enabled is False
    assert s.prompt_reports_enabled is False
    assert s.operator_token is None
    assert s.operator_endpoints_public is False
    assert s.log_level == "INFO"
    assert "http://localhost:5173" in s.cors_allowed_origins


def test_settings_from_env_overrides(monkeypatch):
    monkeypatch.setenv("IS_PROD", "true")
    monkeypatch.setenv("IS_DEBUG_ENABLED", "false")  # the historical bug: must be False
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example, https://admin.example")
    monkeypatch.setenv("OPERATOR_TOKEN", "s3cret")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LOG_FORMAT", "json")
    s = Settings.from_env()
    assert s.is_prod is True
    assert s.is_debug_enabled is False
    assert s.cors_allowed_origins == ["https://app.example", "https://admin.example"]
    assert s.operator_token == "s3cret"
    assert s.log_level == "DEBUG"
    assert s.log_format == "json"


def test_settings_rejects_bad_values(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "chatty")
    with pytest.raises(Exception):
        Settings.from_env()
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("OPENAI_BASE_URL", "ftp://nope")
    with pytest.raises(Exception):
        Settings.from_env()
