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
                            {
                                "name": "Spread",
                                "odds": [
                                    {"hdp": -2.0, "home": "3.50", "away": "1.30"},
                                    {"hdp": -1.5, "home": "4.60", "away": "1.20"},
                                    {"hdp": -0.25, "home": "1.94", "away": "1.84"},
                                    {"hdp": 0.5, "home": "1.34", "away": "3.25"},
                                    {"hdp": 1.0, "home": "1.16", "away": "5.10"},
                                ],
                            },
                            {
                                "name": "Totals",
                                "odds": [
                                    {"hdp": 4.5, "over": "5.25", "under": "1.14"},
                                    {"hdp": 3.5, "over": "3.25", "under": "1.33"},
                                    {"hdp": 3.0, "over": "2.48", "under": "1.52"},
                                    {"hdp": 2.5, "over": "2.06", "under": "1.76"},
                                    {"hdp": 2.25, "over": "1.80", "under": "2.02"},
                                    {"hdp": 2.0, "over": "1.55", "under": "2.36"},
                                ],
                            },
                            {
                                "name": "Double Chance",
                                "odds": [{"homeDraw": "1.25", "awayDraw": "1.62"}],
                            },
                            {
                                "name": "To Qualify",
                                "odds": [{"home": "1.72", "away": "2.05"}],
                            },
                            {"name": "Both Teams To Score", "odds": [{"yes": "1.71", "no": "2.00"}]},
                        ]
                    },
                }
            ]

    events = await FakeClient(_settings()).fetch_odds()

    assert len(events) == 1
    event = events[0]
    assert event.api_id == "odds_api_io:101"
    assert [market.key for market in event.markets] == [
        "h2h",
        "spreads",
        "totals",
        "double_chance",
        "to_qualify",
        "btts",
    ]
    assert [outcome.selection for outcome in event.markets[0].outcomes] == [
        "Switzerland",
        "Draw",
        "Canada",
    ]
    spread_lines = sorted({abs(outcome.point) for outcome in event.markets[1].outcomes})
    assert spread_lines == [0.25, 0.5, 1.5]
    total_lines = sorted({outcome.point for outcome in event.markets[2].outcomes})
    assert total_lines == [2.0, 2.25, 2.5]
    assert [outcome.selection for outcome in event.markets[3].outcomes] == ["1X", "X2"]
    assert [outcome.selection for outcome in event.markets[4].outcomes] == [
        "Switzerland",
        "Canada",
    ]
    assert [outcome.selection for outcome in event.markets[5].outcomes] == ["Yes", "No"]


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


async def test_fetch_scores_keeps_regulation_score_and_penalty_winner():
    class FakeClient(OddsApiIoClient):
        async def _get(self, path, params):
            return [
                {
                    "id": 202,
                    "home": "Switzerland",
                    "away": "Canada",
                    "date": "2026-06-30T19:00:00Z",
                    "status": "settled",
                    "league": {"name": "FIFA World Cup"},
                    "scores": {
                        "home": 5,
                        "away": 4,
                        "periods": {
                            "ft": {"home": 1, "away": 1},
                            "ap": {"home": 4, "away": 3},
                        },
                    },
                }
            ]

    score = (await FakeClient(_settings()).fetch_scores())[0]

    assert score.home_score == 1
    assert score.away_score == 1
    assert score.advancing_team == "Switzerland"
