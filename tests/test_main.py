from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.main import _schedule_sync_jobs, _sync_scores_job
from app.models import Market, MarketType, Match, MatchStatus


class RecordingScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, function, trigger, **kwargs):
        self.jobs.append((function, trigger, kwargs))


def test_sync_jobs_are_scheduled_to_run_periodically():
    scheduler = RecordingScheduler()

    _schedule_sync_jobs(
        scheduler,
        session_factory=object(),
        client=object(),
        bot=object(),
        settings=type(
            "Settings",
            (),
            {"odds_poll_seconds": 900, "scores_poll_seconds": 300},
        )(),
    )

    assert len(scheduler.jobs) == 2
    assert all(trigger == "interval" for _, trigger, _ in scheduler.jobs)
    assert all(kwargs.get("next_run_time", "active") is not None for _, _, kwargs in scheduler.jobs)


def test_api_polling_defaults_are_credit_efficient():
    assert Settings.model_fields["odds_poll_seconds"].default == 86400
    assert Settings.model_fields["scores_poll_seconds"].default == 900


async def test_scores_job_skips_api_without_overdue_match(session_factory, settings):
    class FakeScoresClient:
        def __init__(self):
            self.fetch_calls = 0

        async def find_worldcup_sport_key(self):
            return "soccer_fifa_world_cup"

        async def fetch_scores(self, sport_key):
            self.fetch_calls += 1
            return []

    async with session_factory() as session:
        session.add(
            Match(
                api_id="future-match",
                sport_key="soccer_fifa_world_cup",
                home_team="Brazil",
                away_team="Japan",
                kickoff_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await session.commit()

    client = FakeScoresClient()
    await _sync_scores_job(session_factory, client, object(), settings)

    assert client.fetch_calls == 0


async def test_scores_job_calls_api_for_overdue_match(session_factory, settings):
    class FakeScoresClient:
        def __init__(self):
            self.fetch_calls = 0

        async def find_worldcup_sport_key(self):
            return "soccer_fifa_world_cup"

        async def fetch_scores(self, sport_key):
            self.fetch_calls += 1
            return []

    async with session_factory() as session:
        session.add(
            Match(
                api_id="overdue-match",
                sport_key="soccer_fifa_world_cup",
                home_team="Colombia",
                away_team="DR Congo",
                kickoff_at=datetime.now(timezone.utc) - timedelta(hours=3),
            )
        )
        await session.commit()

    client = FakeScoresClient()
    await _sync_scores_job(session_factory, client, object(), settings)

    assert client.fetch_calls == 1


async def test_scores_job_retries_finished_match_with_open_qualification(
    session_factory,
    settings,
):
    class FakeScoresClient:
        def __init__(self):
            self.fetch_calls = 0

        async def find_worldcup_sport_key(self):
            return "soccer_fifa_world_cup"

        async def fetch_scores(self, sport_key):
            self.fetch_calls += 1
            return []

    async with session_factory() as session:
        match = Match(
            api_id="finished-qualification",
            sport_key="soccer_fifa_world_cup",
            home_team="Brazil",
            away_team="Japan",
            kickoff_at=datetime.now(timezone.utc) - timedelta(hours=3),
            status=MatchStatus.finished,
            home_score=1,
            away_score=1,
        )
        session.add(match)
        await session.flush()
        session.add(
            Market(
                match_id=match.id,
                type=MarketType.to_qualify,
                source="Unibet",
            )
        )
        await session.commit()

    client = FakeScoresClient()
    await _sync_scores_job(session_factory, client, object(), settings)

    assert client.fetch_calls == 1
