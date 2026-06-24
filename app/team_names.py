from __future__ import annotations

import unicodedata


ALIASES = {
    "civ": "ivory coast",
    "congo dr": "dr congo",
    "cuw": "curacao",
    "czechia": "czech republic",
    "kor": "south korea",
    "rsa": "south africa",
}


def canonical_team_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name.casefold())
    ascii_name = "".join(char for char in normalized if not unicodedata.combining(char))
    compact = " ".join(ascii_name.replace("-", " ").split())
    return ALIASES.get(compact, compact)
