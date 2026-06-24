import pytest

from app.config import Settings
from app.integrations.providers import FallbackOddsProvider, build_odds_provider


def test_odds_api_io_settings_defaults():
    assert Settings.model_fields["odds_provider"].default == "the_odds_api"
    assert Settings.model_fields["odds_api_io_base_url"].default == "https://api.odds-api.io/v3"
    assert Settings.model_fields["odds_api_io_bookmakers"].default == "Unibet"


async def test_fallback_provider_uses_secondary_after_primary_error():
    class Primary:
        async def fetch_odds(self):
            raise RuntimeError("primary failed")

    class Secondary:
        async def fetch_odds(self):
            return ["fallback"]

    provider = FallbackOddsProvider(Primary(), Secondary())

    assert await provider.fetch_odds() == ["fallback"]


async def test_fallback_provider_does_not_fallback_on_empty_success():
    class Primary:
        async def fetch_odds(self):
            return []

    class Secondary:
        async def fetch_odds(self):
            raise AssertionError("fallback must not be called")

    provider = FallbackOddsProvider(Primary(), Secondary())

    assert await provider.fetch_odds() == []


def test_provider_factory_requires_primary_key_for_odds_api_io():
    settings = Settings(
        _env_file=None,
        odds_provider="odds_api_io",
        odds_api_io_key="",
        odds_api_key="fallback-key",
    )

    with pytest.raises(RuntimeError, match="ODDS_API_IO_KEY"):
        build_odds_provider(settings)
