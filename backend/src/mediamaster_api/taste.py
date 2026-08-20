"""Opus 5 taste engine: profile generation + batch scoring.

Stage A distills the full rating history (plus Jon's freeform notes) into a
taste profile document. Stage B scores unwatched shows 0-100 against that
profile, leaning on the model's own knowledge of each title. Both stages run
in the scorer Lambda, never in the request path.
"""

import hashlib
import json
import os
from typing import Optional

from pydantic import BaseModel, Field

from .models import Show, Status

MODEL = "claude-opus-5"
BATCH_SIZE = 60

_client = None


def client():
    """Anthropic client with the API key from SSM, cached across invocations."""
    global _client
    if _client is None:
        import boto3
        from anthropic import Anthropic

        param = boto3.client("ssm").get_parameter(
            Name=os.environ["ANTHROPIC_KEY_PARAM"], WithDecryption=True
        )
        _client = Anthropic(api_key=param["Parameter"]["Value"])
    return _client


class ShowScore(BaseModel):
    show_id: str
    score: int = Field(description="0-100 likelihood this person will love the show")
    reason: str = Field(description="Concrete reason, 12 words or fewer")


class BatchScores(BaseModel):
    scores: list[ShowScore]


def ratings_hash(shows: list[Show]) -> str:
    """Stable hash of the rated history, to tell when a profile is stale."""
    rated = sorted(
        (s.show_id, s.status.value, s.rating or 0)
        for s in shows
        if s.status == Status.poubelle or (s.status == Status.done and s.rating)
    )
    return hashlib.sha256(json.dumps(rated).encode()).hexdigest()[:16]


def _show_line(show: Show) -> str:
    parts = [f"{show.name} ({show.show_type.value}"]
    if show.service:
        parts.append(f", on {show.service}")
    if show.source:
        parts.append(f", recommended by {show.source}")
    return "".join(parts) + ")"


def _history_document(shows: list[Show]) -> str:
    groups: dict[str, list[str]] = {"3": [], "2": [], "1": [], "poubelle": []}
    for s in shows:
        if s.status == Status.poubelle:
            groups["poubelle"].append(_show_line(s))
        elif s.status == Status.done and s.rating:
            groups[str(s.rating)].append(_show_line(s))

    sections = [
        ("Absolute favorites (3 stars)", groups["3"]),
        ("Pretty good (2 stars)", groups["2"]),
        ("Just fine (1 star)", groups["1"]),
        ("Strongly disliked / abandoned (La Poubelle)", groups["poubelle"]),
    ]
    out = []
    for title, lines in sections:
        out.append(f"## {title} — {len(lines)} shows")
        if lines:
            out.extend(f"- {line}" for line in lines)
        else:
            out.append("(none yet)")
    return "\n".join(out)


PROFILE_SYSTEM = """\
You are a film and television taste analyst. You will receive one person's \
complete watch history with their ratings, and optionally their own notes about \
their taste. Using your knowledge of these actual shows and films — their \
genres, tones, themes, pacing, creators, and reception — write a taste profile \
for this person.

The profile will be used as context by a scoring system that ranks their \
watchlist, so write it to be maximally useful for predicting whether they will \
love a given title. Include:

- Themes, tones, and genres they gravitate to, with the evidence
- What separates their 3-star favorites from their merely-good 2-star picks
- Patterns in what they dislike or abandon (anti-preferences matter as much)
- Pacing / format preferences (prestige serialized vs procedural, docs, non-English, etc.)
- Reliability of each recurring recommendation source, judged by outcomes
- Anything their own notes emphasize

Write 600-900 words of tight, declarative markdown. No hedging filler. State \
patterns as hypotheses with confidence when evidence is thin."""


def generate_profile(anthropic_client, shows: list[Show], notes: Optional[str]) -> tuple[str, dict]:
    """Stage A. Returns (profile_markdown, usage_dict)."""
    user_content = _history_document(shows)
    if notes:
        user_content += f"\n\n## The person's own notes about their taste\n{notes}"

    response = anthropic_client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=PROFILE_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Profile generation was refused by the model")
    text = next(b.text for b in response.content if b.type == "text")
    return text, _usage_dict(response)


SCORING_SYSTEM = """\
You are ranking a personal watchlist. Below is the owner's taste profile, \
distilled from their complete rating history.

For each candidate show you receive, output a score from 0 to 100: the \
likelihood this person will LOVE it (a 3-star "absolute favorite" is ~90+, a \
solid 2-star fit is ~60-75, "they'd find it just fine" is ~40-55, likely \
abandonment is below 25). Use everything you know about the actual title — \
plot, tone, pacing, craft, critical and audience reception — combined with the \
profile. Recommendation sources mentioned on a candidate are evidence: weigh \
them by the reliability notes in the profile. If you don't recognize a title, \
score from metadata alone and stay near 50.

If a candidate is a later season of a show whose earlier seasons appear in the \
profile's rating history, the person's OWN verdict on those earlier seasons is \
the strongest evidence there is — weight it above general reception. A new \
season of a 3-star favorite should rank near the top of the queue.

For each show give a concrete reason of 12 words or fewer that cites the \
decisive factor (e.g. "slow-burn crime saga, same vein as your 3-star picks").

# Taste profile

"""


def score_batch(anthropic_client, profile: str, shows: list[Show]) -> tuple[list[ShowScore], dict]:
    """Stage B for one batch. Returns (scores, usage_dict)."""
    candidates = [
        {
            "show_id": s.show_id,
            "name": s.name,
            "type": s.show_type.value,
            "service": s.service,
            "recommended_by": s.source,
        }
        for s in shows
    ]
    response = anthropic_client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        system=[
            {
                "type": "text",
                "text": SCORING_SYSTEM + profile,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": "Score these candidates:\n" + json.dumps(candidates, ensure_ascii=False),
            }
        ],
        output_format=BatchScores,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Scoring batch was refused by the model")
    parsed: BatchScores = response.parsed_output
    known_ids = {s.show_id for s in shows}
    scores = [
        ShowScore(show_id=s.show_id, score=max(0, min(100, s.score)), reason=s.reason.strip())
        for s in parsed.scores
        if s.show_id in known_ids
    ]
    return scores, _usage_dict(response)


def _usage_dict(response) -> dict:
    u = response.usage
    return {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }
