from app.main import _schedule_sync_jobs


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
