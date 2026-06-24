from app.config import Settings
from app.integrations.odds_api_io import OddsApiIoClient


def _settings():
    return Settings(
        _env_file=None,
        odds_api_io_key="test-key",
        odds_api_io_bookmakers="Unibet",
    )


async def test_fetch_odds_filters_world_cup_and_maps_supported_markets():
    class FakeClient(OddsApiIoClient):
        async def _get(self, path, params):
            if path == "/events":
                return [
                    {
                        "id": 101,
                        "home": "Switzerland",
                        "away": "Canada",
                        "date": "2026-06-24T19:00:00Z",
                        "status": "pending",
                        "league": {"name": "International - FIFA World Cup"},
                    },
                    {
                        "id": 999,
                        "home": "Club A",
                        "away": "Club B",
                        "date": "2026-06-24T19:00:00Z",
                        "status": "pending",
                        "league": {"name": "Club Friendly Games"},
                    },
                ]
            assert path == "/odds/multi"
            return [
                {
                    "id": 101,
                    "home": "Switzerland",
                    "away": "Canada",
                    "date": "2026-06-24T19:00:00Z",
                    "bookmakers": {
                        "Unibet": [
                            {"name": "ML", "odds": [{"home": "2.33", "draw": "3.05", "away": "3.40"}]},
                            {"name": "Spread", "odds": [{"hdp": -0.25, "home": "1.94", "away": "1.84"}]},
                            {"name": "Totals", "odds": [{"hdp": 2.5, "over": "2.06", "under": "1.76"}]},
                            {"name": "Both Teams To Score", "odds": [{"yes": "1.71", "no": "2.00"}]},
                        ]
                    },
                }
            ]

    events = await FakeClient(_settings()).fetch_odds()

    assert len(events) == 1
    event = events[0]
    assert event.api_id == "odds_api_io:101"
    assert [market.key for market in event.markets] == ["h2h", "spreads", "totals"]
    assert [outcome.selection for outcome in event.markets[0].outcomes] == [
        "Switzerland",
        "Draw",
        "Canada",
    ]
    assert event.markets[1].outcomes[0].point == -0.25
    assert event.markets[1].outcomes[1].point == 0.25
    assert event.markets[2].outcomes[0].selection == "Over"


async def test_fetch_odds_batches_ten_events_per_request():
    class FakeClient(OddsApiIoClient):
        def __init__(self, settings):
            super().__init__(settings)
            self.batches = []

        async def _get(self, path, params):
            if path == "/events":
                return [
                    {
                        "id": event_id,
                        "home": f"Home {event_id}",
                        "away": f"Away {event_id}",
                        "date": "2026-06-24T19:00:00Z",
                        "status": "pending",
                        "league": {"name": "FIFA World Cup"},
                    }
                    for event_id in range(21)
                ]
            self.batches.append(params["eventIds"].split(","))
            return []

    client = FakeClient(_settings())
    await client.fetch_odds()

    assert [len(batch) for batch in client.batches] == [10, 10, 1]


async def test_fetch_scores_normalizes_completed_event():
    class FakeClient(OddsApiIoClient):
        async def _get(self, path, params):
            return [
                {
                    "id": 101,
                    "home": "Switzerland",
                    "away": "Canada",
                    "date": "2026-06-24T19:00:00Z",
                    "status": "settled",
                    "league": {"name": "FIFA World Cup"},
                    "scores": {
                        "home": 2,
                        "away": 1,
                        "periods": {"ft": {"home": 2, "away": 1}},
                    },
                }
            ]

    scores = await FakeClient(_settings()).fetch_scores()

    assert len(scores) == 1
    assert scores[0].api_id == "odds_api_io:101"
    assert scores[0].completed is True
    assert scores[0].home_score == 2
    assert scores[0].away_score == 1
