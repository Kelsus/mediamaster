"""Discovery: propose brand-new titles the taste profile predicts will land.

One request per medium. Shows produce two categories (movie, tv) in a single
call; books one. The model proposes 10 per category; the scorer filters against
the board and keeps the first 5 survivors per category.
"""

from .llm_check import checked_request

PER_CATEGORY_PROPOSED = 10
PER_CATEGORY_KEPT = 5
WEB_SEARCHES_PER_RUN = 6

_COMMON_RULES = """\
Rules:
- Propose titles that are NOT in the person's list below — nothing they have \
watched, read, queued, or discarded, and nothing from the same franchise or \
series as anything on the list (no sequels, spin-offs, or reboots of it — \
propose genuinely new things).
- Choose ONLY titles the profile predicts they will love (a would-be score of \
85+). Quality over novelty-for-its-own-sake; every pick should have a specific \
reason rooted in the profile.
- Mix eras: at least 3 of the 10 in each category released in the last two \
years. Your knowledge has a cutoff — use web search (limited budget: {searches} \
total) to find well-reviewed recent releases matching the profile, and to \
confirm where things stream today.
- score: your honest 0-100 fit prediction. reason: 12 words or fewer, citing \
the profile pattern it matches.
- year: first release year. Do not invent titles; if unsure something exists, \
search or drop it.

Today's date: {today}. Respond with JSON matching the required schema."""

SHOW_SYSTEM = """\
You are a film and TV recommender with one client. Their taste profile:

{profile}

Propose exactly {n} MOVIES (category "movie") and {n} TV SERIES (category \
"tv") they have never seen. For each, also name the streaming service where it \
is currently watchable in the US (field service_or_author; empty string if \
unclear).

""" + _COMMON_RULES

BOOK_SYSTEM = """\
You are a book recommender with one client. Their reading-taste profile:

{profile}

Propose exactly {n} BOOKS (category "book") they have never read. For each, \
give the author (field service_or_author). If a book opens a series, set \
series to the series name and series_index to its position; otherwise leave \
series empty.

""" + _COMMON_RULES

DISCOVER_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string", "enum": ["movie", "tv", "book"]},
                    "service_or_author": {"type": "string"},
                    "series": {"type": "string"},
                    "series_index": {"type": "number"},
                    "year": {"type": "integer"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["name", "category", "service_or_author",
                             "series", "series_index", "year", "score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


def find_candidates(anthropic_client, medium: str, profile: str,
                    board_titles: list[str], today: str) -> tuple[list[dict], dict, int]:
    """Returns (candidates, usage_totals, searches_used)."""
    template = BOOK_SYSTEM if medium == "book" else SHOW_SYSTEM
    system = template.format(profile=profile, n=PER_CATEGORY_PROPOSED,
                             searches=WEB_SEARCHES_PER_RUN, today=today)
    payload = [{"the_persons_complete_list_do_not_recommend_these": board_titles}]
    parsed, totals, searches = checked_request(
        anthropic_client, system, payload, DISCOVER_SCHEMA, WEB_SEARCHES_PER_RUN,
    )
    return parsed.get("candidates", []), totals, searches
