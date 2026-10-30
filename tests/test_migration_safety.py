from pathlib import Path

import pytest


PROFILE = Path("trading_platform/configs/migration-safety.env.example")


def _read_profile(path: Path = PROFILE) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise AssertionError(f"Invalid environment line: {raw_line!r}")
        values[key.strip()] = value.strip()
    return values


def test_migration_profile_is_fail_closed() -> None:
    profile = _read_profile()

    assert profile["IQ_ACCOUNT_TYPE"] == "PRACTICE"
    assert profile["DRY_RUN"].lower() == "true"
    assert profile["MARTINGALE_ENABLED"].lower() == "false"
    assert profile["SCANNER_ENABLED"].lower() == "false"
    assert profile["TELEGRAM_SIGNALS_ENABLED"].lower() == "false"
    assert profile["TRADING_ENVIRONMENT"] == "SHADOW"
    assert profile["LIVE_TRADING_ENABLED"].lower() == "false"
    assert profile["PLATFORM_SHADOW_ENABLED"].lower() == "false"
    assert profile["ALLOW_TELEGRAM_ACCOUNT_SWITCH"].lower() == "false"
    assert profile["ALLOW_TELEGRAM_MARTINGALE"].lower() == "false"


@pytest.mark.parametrize(
    "forbidden_fragment",
    ("PASSWORD=", "API_KEY=", "API_SECRET=", "TELEGRAM_SESSION="),
)
def test_migration_profile_contains_no_secret_fields(forbidden_fragment: str) -> None:
    content = PROFILE.read_text(encoding="utf-8").upper()
    assert forbidden_fragment not in content


def test_current_config_defaults_remain_practice_and_no_martingale() -> None:
    from trading_platform.legacy.iqoption_bot.config import create_default_config

    config = create_default_config()

    assert config["account_type"] == "PRACTICE"
    assert config["martingale_enabled"] is False
    assert config["platform_shadow_enabled"] is False


def test_core_modules_import_without_starting_external_connections() -> None:
    import trading_platform.legacy.iqoption_bot.config  # noqa: F401
    import trading_platform.legacy.iqoption_bot.models  # noqa: F401
    import trading_platform.legacy.iqoption_bot.session  # noqa: F401
    import trading_platform.legacy.iqoption_bot.sizing  # noqa: F401
