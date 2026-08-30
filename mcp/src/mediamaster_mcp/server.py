"""MCP server for MediaMaster — a thin client over the deployed API.

Env:
    MEDIAMASTER_API_URL    e.g. https://dxxxx.cloudfront.net
    MEDIAMASTER_API_TOKEN  an mm_... token minted in the app's Settings page
"""

import os
from typing import Any, Literal, Optional

import httpx
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("mediamaster")

VALID_STATUSES = ("to_watch", "watching", "done", "poubelle")


def _client() -> httpx.Client:
    url = os.environ.get("MEDIAMASTER_API_URL")
    token = os.environ.get("MEDIAMASTER_API_TOKEN")
    if not url or not token:
        raise RuntimeError("Set MEDIAMASTER_API_URL and MEDIAMASTER_API_TOKEN")
    return httpx.Client(
        base_url=url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )


def _board(medium: str = "show") -> dict:
    with _client() as c:
        resp = c.get("/api/board", params={"medium": medium})
        resp.raise_for_status()
        return resp.json()


def _brief(show: dict) -> dict:
    out = {k: show[k] for k in ("show_id", "name", "show_type", "status") if k in show}
    for k in ("service", "source", "rating", "predicted_score", "llm_score", "llm_reason",
              "author", "series", "series_index", "unverified"):
        if show.get(k) is not None:
            out[k] = show[k]
    return out


def _resolve(board: dict, show: str) -> dict:
    """Resolve a ULID or (fuzzy) name to a single show; raise with candidates if ambiguous."""
    all_shows = [s for col in board["columns"].values() for s in col]
    for s in all_shows:
        if s["show_id"] == show:
            return s
    needle = show.strip().casefold()
    exact = [s for s in all_shows if s["name"].casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    matches = [s for s in all_shows if needle in s["name"].casefold()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"No show matches '{show}'")
    names = ", ".join(f"{s['name']} ({s['status']})" for s in matches[:10])
    raise ValueError(f"Ambiguous — matches: {names}. Use an exact name or show_id.")


def _patch(show_id: str, patch: dict) -> dict:
    with _client() as c:
        resp = c.patch(f"/api/shows/{show_id}", json=patch)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
def list_shows(status: Optional[str] = None, medium: str = "show") -> Any:
    """List a board. to_watch comes pre-sorted by predicted preference (best first).

    Args:
        status: optionally limit to one column: to_watch | watching | done | poubelle
        medium: "show" (default) for the tv/movie board, "book" for the books board
                (whose columns read To Read / Reading in the UI)
    """
    board = _board(medium)
    if status:
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return [_brief(s) for s in board["columns"][status]]
    return {k: [_brief(s) for s in v] for k, v in board["columns"].items()}


@mcp.tool()
def search_shows(query: str, medium: str = "show") -> Any:
    """Find shows/books by (partial, case-insensitive) name across all columns.

    Args:
        query: name fragment
        medium: "show" (default) or "book"
    """
    board = _board(medium)
    needle = query.strip().casefold()
    hits = [
        _brief(s)
        for col in board["columns"].values()
        for s in col
        if needle in s["name"].casefold()
    ]
    return hits or f"No shows match '{query}'"


@mcp.tool()
def add_show(
    name: str,
    show_type: Literal["tv", "movie", "book"],
    service: Optional[str] = None,
    source: Optional[str] = None,
    status: str = "to_watch",
    author: Optional[str] = None,
    series: Optional[str] = None,
    series_index: Optional[float] = None,
) -> Any:
    """Add a show, movie, or book to a board.

    Args:
        name: title of the show/movie/book
        show_type: tv, movie, or book (book cards land on the books board)
        service: streaming service it's on (optional; shows only)
        source: who or what recommended it (optional)
        status: which column to add it to (default to_watch, which is To Read for books)
        author: book author (books only, optional)
        series: book series name (books only, optional)
        series_index: position in the series, e.g. 3 or 3.5 (books only, optional)
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}")
    with _client() as c:
        resp = c.post(
            "/api/shows",
            json={
                "medium": "book" if show_type == "book" else "show",
                "author": author,
                "series": series,
                "series_index": series_index,
                "name": name,
                "show_type": show_type,
                "service": service,
                "source": source,
                "status": status,
            },
        )
        resp.raise_for_status()
        return _brief(resp.json())


@mcp.tool()
def move_show(show: str, status: str, rating: Optional[int] = None) -> Any:
    """Move a show to another column. Moving to done should include a rating (1-3).

    Args:
        show: show name (fuzzy matched) or show_id
        status: to_watch | watching | done | poubelle
        rating: 1 = it was fine, 2 = pretty good, 3 = absolute favorite (done only)
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}")
    target = _resolve(_board(), show)
    patch: dict = {"status": status}
    if status == "done" and rating is not None:
        patch["rating"] = rating
    return _brief(_patch(target["show_id"], patch))


@mcp.tool()
def rate_show(show: str, rating: int) -> Any:
    """Rate a show that's in done: 1 = fine, 2 = pretty good, 3 = absolute favorite.

    Args:
        show: show name (fuzzy matched) or show_id
        rating: 1-3
    """
    target = _resolve(_board(), show)
    if target["status"] != "done":
        raise ValueError(
            f"'{target['name']}' is in {target['status']} — move it to done first "
            "(or use move_show with a rating)."
        )
    return _brief(_patch(target["show_id"], {"rating": rating}))


@mcp.tool()
def update_show(
    show: str,
    name: Optional[str] = None,
    show_type: Optional[Literal["tv", "movie"]] = None,
    service: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Edit a show's details (name, type, streaming service, recommendation source).

    Args:
        show: show name (fuzzy matched) or show_id
        name/show_type/service/source: fields to change; omitted fields are untouched
    """
    target = _resolve(_board(), show)
    patch = {
        k: v
        for k, v in {
            "name": name,
            "show_type": show_type,
            "service": service,
            "source": source,
        }.items()
        if v is not None
    }
    if not patch:
        raise ValueError("Nothing to update")
    return _brief(_patch(target["show_id"], patch))


@mcp.tool()
def delete_show(show: str, confirm: bool = False) -> Any:
    """Permanently delete a show. Prefer move_show(..., 'poubelle') for disliked shows —
    poubelle keeps the negative signal that trains the To Watch sorting.

    Args:
        show: show name (fuzzy matched) or show_id
        confirm: must be true to actually delete
    """
    target = _resolve(_board(), show)
    if not confirm:
        raise ValueError(
            f"Refusing to delete '{target['name']}' without confirm=true. "
            "Consider move_show to 'poubelle' instead — it feeds the recommendation signal."
        )
    with _client() as c:
        resp = c.delete(f"/api/shows/{target['show_id']}")
        resp.raise_for_status()
    return f"Deleted '{target['name']}'"


@mcp.tool()
def transfer_show(show: str, to_email: str, medium: str = "show") -> Any:
    """Move a card to another household member's board (e.g. a book that turned
    out to be theirs). Their taste engine re-scores it on their side.

    Args:
        show: show/book name (fuzzy matched) or show_id
        to_email: the recipient's login email
        medium: "show" (default) or "book" — which board the card is on
    """
    target = _resolve(_board(medium), show)
    with _client() as c:
        users = c.get("/api/users")
        users.raise_for_status()
        match = [u for u in users.json() if u["email"].lower() == to_email.lower()]
        if not match:
            known = ", ".join(u["email"] for u in users.json()) or "(nobody else registered)"
            raise ValueError(f"No user {to_email}. Known: {known}")
        resp = c.post(f"/api/shows/{target['show_id']}/transfer",
                      json={"to_uid": match[0]["uid"]})
        resp.raise_for_status()
    return f"Sent '{target['name']}' to {match[0]['display_name']}'s board"


@mcp.tool()
def get_taste_profile(medium: str = "show") -> Any:
    """Read Claude's taste profile of the owner, its status, and last scoring run.

    Args:
        medium: "show" (default) or "book" for the reading-taste profile
    """
    with _client() as c:
        resp = c.get("/api/taste", params={"medium": medium})
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
def rescore_board(medium: str = "show") -> Any:
    """Kick off a full taste re-profiling + re-scoring of a board's queue.

    Runs Claude Opus 5 over the owner's rating history (~$1-2, takes a
    couple of minutes, runs in the background). Check get_taste_profile for
    completion status.

    Args:
        medium: "show" (default) re-scores To Watch; "book" re-scores To Read
    """
    with _client() as c:
        resp = c.post("/api/rescore", params={"medium": medium})
        if resp.status_code == 409:
            return "A re-score is already running — check get_taste_profile for status."
        resp.raise_for_status()
        return "Re-scoring started; it finishes in a couple of minutes."


@mcp.tool()
def scout_seasons(medium: str = "show") -> Any:
    """Scan for newly released next installments and queue them.

    medium="show" (default): finished-and-liked tv shows -> missing "Season N"
    cards into To Watch. medium="book": book series you're current on -> the
    real next book into To Read.

    Uses web search for recent releases (a few $ for a full sweep, a few
    minutes, runs in the background). Call again later to see last_run results,
    which include the list of cards it created.
    """
    with _client() as c:
        state = c.get("/api/scout", params={"medium": medium}).json()
        if state.get("scout_status") == "running":
            return {"status": "already_running", "last_run": state.get("last_run")}
        resp = c.post("/api/scout", params={"medium": medium})
        if resp.status_code == 409:
            return {"status": "already_running", "last_run": state.get("last_run")}
        resp.raise_for_status()
        return {"status": "started", "previous_run": state.get("last_run")}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
