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
    from . import taste

    system = SCOUT_SYSTEM.format(today=today)
    messages = [{"role": "user", "content": json.dumps(candidates, ensure_ascii=False)}]
    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

    request = dict(
        model=taste.MODEL,
        max_tokens=16000,
        system=system,
        tools=[{"type": "web_search_20260209", "name": "web_search",
                "max_uses": WEB_SEARCHES_PER_BATCH}],
        output_config={"format": {"type": "json_schema", "schema": SCOUT_SCHEMA}},
    )

    response = None
    searches = 0
    for _ in range(1 + MAX_CONTINUATIONS):
        try:
            response = anthropic_client.messages.create(**request, messages=messages)
        except Exception as e:  # e.g. schema+tools combination rejected
            if "output_config" in str(e) and "format" in request.get("output_config", {}):
                request.pop("output_config")
                request["system"] = system + (
                    "\nReturn ONLY a JSON object of the shape "
                    '{"franchises": [{"franchise", "have_season", "next_season", '
                    '"released", "note"}]} — no prose.'
                )
                response = anthropic_client.messages.create(**request, messages=messages)
            else:
                raise
        for k in totals:
            totals[k] += getattr(response.usage, k, 0) or 0
        searches += sum(
            1 for b in response.content if getattr(b, "type", "") == "server_tool_use"
        )
        if response.stop_reason == "pause_turn":
            # server-side search loop paused; resend with the assistant turn appended
            messages = messages + [{"role": "assistant", "content": response.content}]
            continue
        break

    if response.stop_reason == "refusal":
        raise RuntimeError("Season scout batch was refused by the model")

    text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    parsed = None
    for candidate_text in reversed(text_blocks):
        try:
            parsed = json.loads(candidate_text)
            break
        except json.JSONDecodeError:
            continue
    if parsed is None:
        raise RuntimeError("Season scout returned no parseable JSON")
    return parsed.get("franchises", []), totals, searches
