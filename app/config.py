from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    telegram_bot_token: str = Field(default="")
    database_url: str = Field(default="sqlite+aiosqlite:///./worldcup_bot.db")
    admin_telegram_ids: str = Field(default="")

    odds_provider: str = Field(default="the_odds_api")
    odds_api_key: str = Field(default="")
    odds_api_base_url: str = Field(default="https://api.the-odds-api.com")
    odds_regions: str = Field(default="eu,uk")
    odds_markets: str = Field(default="h2h,spreads,totals,outrights")
    odds_api_io_key: str = Field(default="")
    odds_api_io_base_url: str = Field(default="https://api.odds-api.io/v3")
    odds_api_io_bookmakers: str = Field(default="Unibet")
    odds_poll_seconds: int = Field(default=86400)
    scores_poll_seconds: int = Field(default=900)

    bet_close_minutes: int = Field(default=5)
    min_stake_cents: int = Field(default=100)
    max_stake_cents: int = Field(default=2500)
    starting_balance_cents: int = Field(default=10000)
    app_timezone: str = Field(default="Europe/Kyiv")

    @property
    def admin_ids(self) -> set[int]:
        ids: set[int] = set()
        for raw_id in self.admin_telegram_ids.split(","):
            raw_id = raw_id.strip()
            if raw_id:
                ids.add(int(raw_id))
        return ids


@lru_cache
def get_settings() -> Settings:
    return Settings()

