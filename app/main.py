from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.handlers import build_router
from app.config import get_settings
from app.database import init_db, make_session_factory
from app.integrations.odds_api import OddsApiClient
from app.services.sync import sync_odds, sync_scores


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    session_factory = make_session_factory(settings)
    await init_db(session_factory)

    scheduler = AsyncIOScheduler(timezone="UTC")
    if settings.odds_api_key:
        client = OddsApiClient(settings)
        scheduler.add_job(
            _sync_odds_job,
            "interval",
            seconds=settings.odds_poll_seconds,
            args=[session_factory, client],
            next_run_time=None,
            max_instances=1,
        )
        scheduler.add_job(
            _sync_scores_job,
            "interval",
            seconds=settings.scores_poll_seconds,
            args=[session_factory, client],
            next_run_time=None,
            max_instances=1,
        )
        scheduler.start()
        asyncio.create_task(_sync_odds_job(session_factory, client))
        asyncio.create_task(_sync_scores_job(session_factory, client))
    else:
        logger.warning("ODDS_API_KEY is empty; automatic odds sync is disabled.")

    bot = Bot(settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(session_factory, settings))
    await dispatcher.start_polling(bot)


async def _sync_odds_job(session_factory, client: OddsApiClient) -> None:
    try:
        async with session_factory() as session:
            count = await sync_odds(session, client)
            await session.commit()
        logger.info("Synced %s odds snapshots", count)
    except Exception:
        logger.exception("Odds sync failed")


async def _sync_scores_job(session_factory, client: OddsApiClient) -> None:
    try:
        async with session_factory() as session:
            count = await sync_scores(session, client)
            await session.commit()
        if count:
            logger.info("Auto-settled %s completed matches from scores", count)
    except Exception:
        logger.exception("Scores sync failed")


if __name__ == "__main__":
    asyncio.run(main())
