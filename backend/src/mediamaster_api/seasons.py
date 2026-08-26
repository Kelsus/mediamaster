"""Season Scout: find released-but-untracked seasons of shows Jon liked.

Pure-Python franchise grouping + an Opus 5 check (with web search for
post-training-cutoff releases). Runs inside the scorer Lambda, never in the
request path.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from .models import Show, ShowType, Status

SCOUT_BATCH_SIZE = 40
MAX_CONTINUATIONS = 5
WEB_SEARCHES_PER_BATCH = 4

# "Yellowstone Seasons 1-3", "Suits Seasons 1 and 2", "Lioness Seasons 1 & 2"
_SEASON_RANGE_RE = re.compile(
    r"^(?P<base>.+?)[\s\-–:,]*\(?\bseasons\s*(?P<a>\d{1,2})\s*(?:[-–&+]|,|and|to|through)\s*(?P<b>\d{1,2})\)?$",
    re.IGNORECASE,
)
# "Euphoria Season 2", "Fargo S2", "Slow Horses - Series 4", "Taskmaster (Season 12)"
_SEASON_RE = re.compile(
    r"^(?P<base>.+?)[\s\-–:,]*\(?\b(?:season|series|szn|s)\.?\s*(?P<num>\d{1,2})\)?$",
    re.IGNORECASE,
)
# "The Bear Part 2", "Attack on Titan Part III", "Stranger Things Vol. 2"
_PART_RE = re.compile(
    r"^(?P<base>.+?)[\s\-–:,]*\(?\b(?:part|pt\.?|volume|vol\.?)\s*(?P<num>\d{1,2}|[IVX]{1,4})\)?$",
    re.IGNORECASE,
)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}


def parse_name(name: str) -> tuple[str, Optional[int]]:
    """Split a card name into (base title, season number or None)."""
    cleaned = re.sub(r"\s+", " ", name).strip()
    m = _SEASON_RANGE_RE.match(cleaned)
    if m:
        return m.group("base").rstrip(" -–:,("), max(int(m.group("a")), int(m.group("b")))
    for pattern in (_SEASON_RE, _PART_RE):
        m = pattern.match(cleaned)
        if m:
            raw = m.group("num").lower()
            num = _ROMAN.get(raw) if raw in _ROMAN else int(raw) if raw.isdigit() else None
            if num:
                return m.group("base").rstrip(" -–:,("), num
    return cleaned, None


def _key(base: str) -> str:
    return re.sub(r"\s+", " ", base).strip().casefold()


@dataclass
class Franchise:
    base: str  # display name
    max_season: int = 1
    latest: Optional[Show] = None  # the max-season card
    service: Optional[str] = None
    shows: list[Show] = field(default_factory=list)


def group_franchises(shows: list[Show]) -> dict[str, Franchise]:
    """Group tv cards by base title. Bare titles count as season 1."""
    franchises: dict[str, Franchise] = {}
    for show in shows:
        if show.show_type != ShowType.tv:
            continue
        base, season = parse_name(show.name)
        season = season or 1
        f = franchises.setdefault(_key(base), Franchise(base=base))
        f.shows.append(show)
        if season >= f.max_season or f.latest is None:
            f.max_season = season
            f.latest = show
        if show.service and not f.service:
            f.service = show.service
    for f in franchises.values():
        f.service = f.latest.service or f.service
    return franchises


def eligible(f: Franchise) -> bool:
    """Follow a franchise iff its latest season is finished and not disliked."""
    latest = f.latest
    if latest is None:
        return False
    if latest.status in (Status.to_watch, Status.watching):
        return False  # next step already on the board
    if latest.status == Status.poubelle:
        return False
    return latest.rating is None or latest.rating >= 2  # done: unrated or liked


SCOUT_SYSTEM = """\
You are a television release checker. Today's date is {today}.

You receive a list of TV franchises with the highest season one person has \
watched or queued ("have_season"). For each, determine whether the NEXT season \
(have_season + 1) exists and has actually been RELEASED — meaning its premiere \
episode has aired on or before today's date. "Renewed", "announced", "in \
production", or "premieres next month" all mean released=false.

Use your own knowledge first. Your training data has a cutoff, so for shows \
where a renewal or release decision plausibly happened after your cutoff and \
you are not certain, use web search — but search selectively; you have a \
limited search budget, so spend it on the genuinely uncertain cases, not on \
long-ended shows.

Rules:
- next_season is always have_season + 1 (the next one this person should \
watch), even if later seasons also exist.
- Shows that have ended, were cancelled, or whose next season is unreleased: \
released=false.
- note: one short clause with the decisive fact ("premiered 2026-05-12", \
"cancelled after S2", "renewed, expected 2027").
- Include every input franchise exactly once in your answer.

Respond with JSON matching the required schema."""

SCOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "franchises": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "franchise": {"type": "string"},
                    "have_season": {"type": "integer"},
                    "next_season": {"type": "integer"},
                    "released": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["franchise", "have_season", "next_season", "released", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["franchises"],
    "additionalProperties": False,
}


def check_franchises(anthropic_client, candidates: list[dict], today: str) -> tuple[list[dict], dict, int]:
    """Ask Opus 5 (with web search) which candidates have a released next season.

    candidates: [{"franchise": str, "have_season": int}]
    Returns (results, usage_totals, searches_used).
    """
    from .llm_check import checked_request

    parsed, totals, searches = checked_request(
        anthropic_client, SCOUT_SYSTEM.format(today=today), candidates,
        SCOUT_SCHEMA, WEB_SEARCHES_PER_BATCH,
    )
    return parsed.get("franchises", []), totals, searches
