from types import SimpleNamespace

import pytest

from mediamaster_api import db, taste
from mediamaster_api.models import Show, ShowCreate, Status
from mediamaster_api.taste import BatchScores, ShowScore


def make_show(i, status=Status.to_watch, rating=None, **kw):
    ts = "2026-01-01T00:00:00+00:00"
    return Show(show_id=f"id{i}", name=f"Show {i}", show_type="tv", status=status,
                rating=rating, created_at=ts, updated_at=ts, status_changed_at=ts, **kw)


class StubUsage:
    input_tokens = 100
    output_tokens = 50
    cache_creation_input_tokens = 10
    cache_read_input_tokens = 5


class StubClient:
    """Mimics the two anthropic call shapes taste.py uses."""

    def __init__(self, profile_text="the profile", scores=None, stop_reason="end_turn"):
        self._profile_text = profile_text
        self._scores = scores or []
        self._stop = stop_reason
        self.parse_calls = []
        self.messages = self

    def create(self, **kwargs):
        return SimpleNamespace(
            stop_reason=self._stop,
            content=[SimpleNamespace(type="text", text=self._profile_text)],
            usage=StubUsage(),
        )

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self._stop,
            parsed_output=BatchScores(scores=self._scores),
            usage=StubUsage(),
        )


def test_generate_profile_returns_text_and_usage():
    rated = [make_show(1, Status.done, rating=3, source="Maria")]
    text, usage = taste.generate_profile(StubClient("great taste"), rated, notes="loves noir")
    assert text == "great taste"
    assert usage["input_tokens"] == 100


def test_generate_profile_refusal_raises():
    with pytest.raises(RuntimeError):
        taste.generate_profile(StubClient(stop_reason="refusal"), [], None)


def test_score_batch_clamps_and_filters_unknown_ids():
    shows = [make_show(1), make_show(2)]
    stub = StubClient(scores=[
        ShowScore(show_id="id1", score=150, reason=" too high "),
        ShowScore(show_id="id2", score=-5, reason="low"),
        ShowScore(show_id="hallucinated", score=50, reason="not ours"),
    ])
    scores, _ = taste.score_batch(stub, "profile", shows)
    assert [(s.show_id, s.score) for s in scores] == [("id1", 100), ("id2", 0)]
    assert scores[0].reason == "too high"
    # system prompt carries the cached profile block
    system = stub.parse_calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "profile" in system[0]["text"]


def test_ratings_hash_changes_with_ratings():
    a = [make_show(1, Status.done, rating=2)]
    b = [make_show(1, Status.done, rating=3)]
    assert taste.ratings_hash(a) != taste.ratings_hash(b)
    # unrated queue changes don't affect it
    assert taste.ratings_hash(a) == taste.ratings_hash(a + [make_show(9)])


def test_board_sort_llm_first_then_stats(client):
    def add(name, **kw):
        resp = client.post("/api/shows", json={"name": name, "show_type": "tv", **kw})
        return resp.json()["show_id"]

    low = add("llm low")
    high = add("llm high")
    unscored_new = add("unscored newer")
    unscored_old = add("unscored older")

    db.write_show_score("test-user", low, 20, "meh", "2026-01-01T00:00:00+00:00", "v1")
    db.write_show_score("test-user", high, 95, "perfect fit", "2026-01-01T00:00:00+00:00", "v1")

    board = client.get("/api/board").json()["columns"]["to_watch"]
    names = [s["name"] for s in board]
    assert names[0] == "llm high"
    assert names[1] == "llm low"
    # unscored shows follow, in stats/recency order
    assert set(names[2:]) == {"unscored newer", "unscored older"}
    assert board[0]["llm_reason"] == "perfect fit"


def test_patch_preserves_llm_score(client):
    resp = client.post("/api/shows", json={"name": "Keeper", "show_type": "tv"})
    show_id = resp.json()["show_id"]
    db.write_show_score("test-user", show_id, 88, "good", "2026-01-01T00:00:00+00:00", "v1")

    client.patch(f"/api/shows/{show_id}", json={"name": "Keeper (renamed)"})
    board = client.get("/api/board").json()["columns"]["to_watch"]
    assert board[0]["llm_score"] == 88


def test_taste_routes_and_rescore_guard(client, monkeypatch):
    resp = client.get("/api/taste")
    assert resp.json()["scoring_status"] == "idle"

    resp = client.put("/api/taste/notes", json={"notes": "more heist movies"})
    assert resp.json()["notes"] == "more heist movies"

    invocations = []
    monkeypatch.setattr("mediamaster_api.main._invoke_scorer", lambda p: invocations.append(p))
    assert client.post("/api/rescore").status_code == 202
    assert invocations == [{"uid": "test-user", "mode": "full", "medium": "show"}]

    # simulate a fresh running lock -> 409
    from mediamaster_api.models import now_iso
    db.put_profile("test-user", {"scoring_status": "running", "started_at": now_iso()})
    assert client.post("/api/rescore").status_code == 409

    # stale lock (>20 min) is ignored
    db.put_profile("test-user", {"started_at": "2020-01-01T00:00:00+00:00"})
    assert client.post("/api/rescore").status_code == 202
