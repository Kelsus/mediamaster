"""Series Scout: find the next unowned book in series Jon is reading.

Groups book cards by their `series` field (set at import/classification time),
asks Opus 5 (with web search for post-cutoff releases) for the next book in
order after the highest owned entry, and queues it in To Read.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from .models import Medium, Show, Status

SERIES_BATCH_SIZE = 25
WEB_SEARCHES_PER_BATCH = 4


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


@dataclass
class SeriesGroup:
    name: str  # display name of the series
    author: Optional[str] = None
    max_index: float = 0.0
    frontier: Optional[Show] = None  # the highest-index (or latest) card
    books: list[Show] = field(default_factory=list)


def group_series(shows: list[Show]) -> dict[str, SeriesGroup]:
    """Group book cards by series name. Unindexed books rank below indexed ones."""
    groups: dict[str, SeriesGroup] = {}
    for show in shows:
        if show.medium != Medium.book or not show.series:
            continue
        g = groups.setdefault(_key(show.series), SeriesGroup(name=show.series))
        g.books.append(show)
        idx = show.series_index or 0.0
        if idx >= g.max_index or g.frontier is None:
            g.max_index = idx
            g.frontier = show
        if show.author and not g.author:
            g.author = show.author
    return groups


def eligible(g: SeriesGroup) -> bool:
    """Follow a series iff its frontier book is finished and not disliked."""
    frontier = g.frontier
    if frontier is None:
        return False
    if frontier.status in (Status.to_watch, Status.watching):
        return False  # next step already queued / mid-read
    if frontier.status == Status.poubelle:
        return False
    return frontier.rating is None or frontier.rating >= 2


SCOUT_SYSTEM = """\
You are a book-series release checker. Today's date is {today}.

You receive a list of book series. For each, "owned" lists the entries one \
person already has (with series position numbers where known — trust the \
titles over the numbers if they conflict with your knowledge of the series). \
Determine the NEXT book in series order after the highest entry they own, and \
whether it has actually been RELEASED (published on or before today's date). \
"Announced", "forthcoming", or "expected later this year" mean released=false.

Use your own knowledge first; use web search only for series where a release \
plausibly happened after your training cutoff and you are not certain. Your \
search budget is limited — spend it on active series, not long-completed ones.

Rules:
- next_title must be the book's REAL published title, exactly as published.
- next_index is its position in the series' primary reading order.
- If the series is complete and they own the final book: released=false, \
next_title="".
- Novellas and side stories count only if part of the primary reading order.
- note: one short clause with the decisive fact ("published 2026-03-04", \
"series complete", "book 6 expected 2027").
- Include every input series exactly once.

Respond with JSON matching the required schema."""

SCOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "series": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "series": {"type": "string"},
                    "next_title": {"type": "string"},
                    "next_index": {"type": "number"},
                    "author": {"type": "string"},
                    "released": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["series", "next_title", "next_index", "author",
                             "released", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["series"],
    "additionalProperties": False,
}


def check_series(anthropic_client, candidates: list[dict], today: str) -> tuple[list[dict], dict, int]:
    """candidates: [{"series", "author", "owned": [{"title", "index"}]}]"""
    from .llm_check import checked_request

    parsed, totals, searches = checked_request(
        anthropic_client, SCOUT_SYSTEM.format(today=today), candidates,
        SCOUT_SCHEMA, WEB_SEARCHES_PER_BATCH,
    )
    return parsed.get("series", []), totals, searches


def candidate_payload(g: SeriesGroup) -> dict:
    return {
        "series": g.name,
        "author": g.author,
        "owned": [
            {"title": b.name, "index": b.series_index}
            for b in sorted(g.books, key=lambda b: b.series_index or 0.0)
        ],
    }
