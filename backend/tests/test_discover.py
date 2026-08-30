from unittest.mock import patch

import pytest

from mediamaster_api import db, scorer
from mediamaster_api.models import Medium, Show, ShowCreate, ShowType, Status, now_iso

from conftest import TEST_UID


def _seed(client, name, status="done", medium="show", show_type="tv", series=None):
    resp = client.post("/api/shows", json={
        "name": name, "show_type": show_type, "medium": medium,
        "status": status, "series": series,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stub_candidates(cands):
    return lambda c, medium, profile, titles, today: (cands, {
        "input_tokens": 100, "output_tokens": 50,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}, 2)


def _cand(name, category, score=90, **kw):
    return {"name": name, "category": category, "service_or_author": kw.get("extra", "Netflix"),
            "series": kw.get("series", ""), "series_index": kw.get("series_index", 0),
            "year": 2025, "score": score, "reason": "fits the profile"}


@pytest.fixture()
def profiled(client):
    db.put_profile(TEST_UID, {"profile_text": "loves slow-burn crime", "ratings_hash": "h1"},
                   "show")
    db.put_profile(TEST_UID, {"profile_text": "loves hard sf", "ratings_hash": "h2"}, "book")
    return client


def test_discover_creates_pinned_scored_cards(profiled, monkeypatch):
    monkeypatch.setattr(scorer.discover, "find_candidates",
                        _stub_candidates([_cand("Dept. Q", "tv"), _cand("Blue Ruin", "movie")]))
    monkeypatch.setattr(scorer.taste, "client", lambda: None)
    result = scorer.run_discover(TEST_UID, "show")
    assert set(result["created"]) == {"Dept. Q", "Blue Ruin"}

    board = profiled.get("/api/board?medium=show").json()["columns"]["to_watch"]
    assert {s["name"] for s in board} == {"Dept. Q", "Blue Ruin"}
    for s in board:
        assert s["discovered_at"] is not None
        assert s["llm_score"] == 90
        assert s["source"] == "Discovery"


def test_discover_dedupes_against_board_and_franchises(profiled, monkeypatch):
    _seed(profiled, "Breaking Bad Season 2", status="done")
    _seed(profiled, "Dept. Q", status="poubelle")
    monkeypatch.setattr(scorer.discover, "find_candidates", _stub_candidates([
        _cand("Breaking Bad", "tv"),          # franchise collision with S2 card
        _cand("Dept. Q", "tv"),               # exact collision (poubelle counts!)
        _cand("Slow Horses", "tv"),
    ]))
    monkeypatch.setattr(scorer.taste, "client", lambda: None)
    result = scorer.run_discover(TEST_UID, "show")
    assert result["created"] == ["Slow Horses"]


def test_discover_caps_at_five_per_category(profiled, monkeypatch):
    cands = [_cand(f"Movie {i}", "movie") for i in range(8)] + \
            [_cand(f"Series {i}", "tv") for i in range(8)]
    monkeypatch.setattr(scorer.discover, "find_candidates", _stub_candidates(cands))
    monkeypatch.setattr(scorer.taste, "client", lambda: None)
    result = scorer.run_discover(TEST_UID, "show")
    assert len(result["created"]) == 10
    assert sum(1 for n in result["created"] if n.startswith("Movie")) == 5


def test_board_pins_discoveries_above_higher_scores(profiled, monkeypatch):
    old = _seed(profiled, "Old Favorite Queued", status="to_watch")
    db.write_show_score(TEST_UID, old["show_id"], 99, "amazing", now_iso(), "h1")
    monkeypatch.setattr(scorer.discover, "find_candidates",
                        _stub_candidates([_cand("Fresh Find", "tv", score=70)]))
    monkeypatch.setattr(scorer.taste, "client", lambda: None)
    scorer.run_discover(TEST_UID, "show")

    names = [s["name"] for s in profiled.get("/api/board?medium=show").json()["columns"]["to_watch"]]
    assert names == ["Fresh Find", "Old Favorite Queued"]  # pin beats score 99


def test_rescore_unpins(profiled, monkeypatch):
    monkeypatch.setattr(scorer.discover, "find_candidates",
                        _stub_candidates([_cand("Fresh Find", "tv", score=70)]))
    monkeypatch.setattr(scorer.taste, "client", lambda: None)
    scorer.run_discover(TEST_UID, "show")
    board = profiled.get("/api/board?medium=show").json()["columns"]["to_watch"]
    show_id = board[0]["show_id"]

    # a full re-score writes fresh scores with no discovered_at -> pin removed
    db.write_show_score(TEST_UID, show_id, 71, "re-ranked", now_iso(), "h1")
    board = profiled.get("/api/board?medium=show").json()["columns"]["to_watch"]
    assert board[0].get("discovered_at") is None


def test_discover_requires_profile(client, monkeypatch):
    monkeypatch.setattr(scorer.taste, "client", lambda: None)
    with pytest.raises(RuntimeError, match="taste profile"):
        scorer.run_discover(TEST_UID, "book")
    state = db.get_scout_state(TEST_UID)
    assert state["discover_status_book"] == "idle"
    assert "taste profile" in state["last_discover_error_book"]


def test_discover_endpoint_guard(profiled):
    db.put_scout_state(TEST_UID, {"discover_status_show": "running",
                                  "discover_started_at_show": now_iso()})
    with patch("mediamaster_api.main._invoke_scorer") as invoke:
        assert profiled.post("/api/discover?medium=show").status_code == 409
        invoke.assert_not_called()
    db.put_scout_state(TEST_UID, {"discover_status_show": "idle", "discover_started_at_show": None})
    with patch("mediamaster_api.main._invoke_scorer") as invoke:
        assert profiled.post("/api/discover?medium=book").status_code == 202
        assert invoke.call_args[0][0]["mode"] == "discover"
