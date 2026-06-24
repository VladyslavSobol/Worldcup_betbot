from datetime import datetime, timedelta, timezone

from app.bot.handlers import _dedupe_matches
from app.models import Match
from app.team_names import canonical_team_name


def test_canonical_team_aliases():
    assert canonical_team_name("Czechia") == canonical_team_name("Czech Republic")
    assert canonical_team_name("RSA") == canonical_team_name("South Africa")
    assert canonical_team_name("KOR") == canonical_team_name("South Korea")
    assert canonical_team_name("CIV") == canonical_team_name("Ivory Coast")
    assert canonical_team_name("CUW") == canonical_team_name("Curaçao")
    assert canonical_team_name("Congo DR") == canonical_team_name("DR Congo")
    assert canonical_team_name("Curaçao") == canonical_team_name("Curacao")


def test_match_list_deduplication_prefers_current_provider_row():
    kickoff = datetime.now(timezone.utc) + timedelta(days=1)
    old = Match(
        id=13,
        api_id="legacy",
        home_team="Czech Republic",
        away_team="Mexico",
        kickoff_at=kickoff,
    )
    duplicate = Match(
        id=34,
        api_id="odds_api_io:34",
        home_team="Czechia",
        away_team="Mexico",
        kickoff_at=kickoff + timedelta(minutes=2),
    )

    assert _dedupe_matches([duplicate, old]) == [duplicate]


def test_additional_provider_team_aliases():
    assert canonical_team_name("Turkiye") == canonical_team_name("Turkey")
    assert canonical_team_name("Türkiye") == canonical_team_name("Turkey")
    assert canonical_team_name("Korea Republic") == canonical_team_name("South Korea")
    assert canonical_team_name("Bosnia & Herzegovina") == canonical_team_name(
        "Bosnia and Herzegovina"
    )
