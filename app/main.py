from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.bot.handlers import (
    _announce_to_group,
    _leaderboard_text,
    _settlement_results_for_targets,
    build_router,
)
from app.config import get_settings
from app.database import init_db, make_session_factory
from app.integrations.odds_api import OddsApiClient
from app.models import Match
from app.services.sync import ScoreSettlementResult, sync_odds, sync_scores_with_results


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    session_factory = make_session_factory(settings)
    await init_db(session_factory)
    bot = Bot(settings.telegram_bot_token)

    scheduler = AsyncIOScheduler(timezone="UTC")
    if settings.odds_api_key:
        client = OddsApiClient(settings)
        _schedule_sync_jobs(scheduler, session_factory, client, bot, settings)
        scheduler.start()
        asyncio.create_task(_sync_odds_job(session_factory, client))
        asyncio.create_task(_sync_scores_job(session_factory, client, bot, settings))
    else:
        logger.warning("ODDS_API_KEY is empty; automatic odds sync is disabled.")

    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(session_factory, settings))
    await dispatcher.start_polling(bot)


def _schedule_sync_jobs(scheduler, session_factory, client, bot: Bot, settings) -> None:
    scheduler.add_job(
        _sync_odds_job,
        "interval",
        seconds=settings.odds_poll_seconds,
        args=[session_factory, client],
        max_instances=1,
    )
    scheduler.add_job(
        _sync_scores_job,
        "interval",
        seconds=settings.scores_poll_seconds,
        args=[session_factory, client, bot, settings],
        max_instances=1,
    )


async def _sync_odds_job(session_factory, client: OddsApiClient) -> None:
    try:
        async with session_factory() as session:
            count = await sync_odds(session, client)
            await session.commit()
        logger.info("Synced %s odds snapshots", count)
    except Exception:
        logger.exception("Odds sync failed")


async def _sync_scores_job(session_factory, client: OddsApiClient, bot: Bot, settings) -> None:
    try:
        async with session_factory() as session:
            results = await sync_scores_with_results(session, client)
            await session.commit()
        count = len(results)
        if count:
            logger.info("Auto-settled %s completed matches from scores", count)
            for result in results:
                await _announce_auto_settlement_result(session_factory, bot, settings, result)
    except Exception:
        logger.exception("Scores sync failed")


async def _announce_auto_settlement_result(
    session_factory,
    bot: Bot,
    settings,
    result: ScoreSettlementResult,
) -> None:
    async with session_factory() as session:
        match = await session.scalar(select(Match).where(Match.id == result.match_id))
        details = await _settlement_results_for_targets(
            session,
            match,
            result.single_bet_ids,
            result.express_bet_ids,
        )
    if not match or not details:
        return

    board = await _leaderboard_text(session_factory, settings)
    details_block = f"{details}\n\n" if details else ""
    await _announce_to_group(
        session_factory,
        bot,
        "Матч автоматично розраховано.\n\n"
        f"{match.home_team} {result.home_goals}:{result.away_goals} {match.away_team}\n\n"
        f"{details_block}"
        f"{board}",
        source_chat_id=0,
        settlements_only=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
