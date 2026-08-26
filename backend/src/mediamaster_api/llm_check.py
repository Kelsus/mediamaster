"""Shared Opus 5 fact-check request: web search + structured output.

Used by the Season Scout (tv) and Series Scout (books). Handles the
server-side search loop pausing (pause_turn), refusals, and a fallback to
instructed-JSON if the schema+tools combination is ever rejected.
"""

import json

MAX_CONTINUATIONS = 5


def checked_request(anthropic_client, system: str, payload: list[dict],
                    schema: dict, max_searches: int) -> tuple[dict, dict, int]:
    """Returns (parsed_json, usage_totals, searches_used)."""
    from . import taste

    messages = [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

    request = dict(
        model=taste.MODEL,
        max_tokens=16000,
        system=system,
        tools=[{"type": "web_search_20260209", "name": "web_search",
                "max_uses": max_searches}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
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
                    "\nReturn ONLY a JSON object matching the agreed shape — no prose."
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
        raise RuntimeError("Scout batch was refused by the model")

    text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    for candidate_text in reversed(text_blocks):
        try:
            return json.loads(candidate_text), totals, searches
        except json.JSONDecodeError:
            continue
    raise RuntimeError("Scout returned no parseable JSON")
