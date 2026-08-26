import json
from types import SimpleNamespace

import pytest

from mediamaster_api import seasons
from mediamaster_api.models import Show, ShowType, Status
from mediamaster_api.seasons import (
    Franchise,
    check_franchises,
    eligible,
    group_franchises,
    parse_name,
)

N = 0


def make_show(name, status=Status.done, rating=None, show_type=ShowType.tv, service=None):
    global N
    N += 1
    ts = f"2024-01-{N:02d}T00:00:00+00:00"
    return Show(
        show_id=f"id{N}", name=name, show_type=show_type, service=service,
        status=status, rating=rating, created_at=ts, updated_at=ts, status_changed_at=ts,
    )


@pytest.mark.parametrize("name,base,num", [
    ("Euphoria Season 2", "Euphoria", 2),
    ("Euphoria", "Euphoria", None),
    ("Animal Kingdom season 3", "Animal Kingdom", 3),
    ("Fargo S2", "Fargo", 2),
    ("Slow Horses - Series 4", "Slow Horses", 4),
    ("Taskmaster (Season 12)", "Taskmaster", 12),
    ("The Bear Part 2", "The Bear", 2),
    ("Attack on Titan Part III", "Attack on Titan", 3),
    ("Stranger Things Vol. 2", "Stranger Things", 2),
    ("Yellowstone Seasons 1-3", "Yellowstone", 3),
    ("Suits Seasons 1 and 2", "Suits", 2),
    ("Lioness Seasons 1 & 2", "Lioness", 2),
    ("Fauda Seasons 2 through 4", "Fauda", 4),
    ("Cars 2", "Cars 2", None),           # 's 2' inside a word is not a season
    ("The Four Seasons", "The Four Seasons", None),  # 'Seasons' is not 'Season N'
    ("Severance", "Severance", None),
])
def test_parse_name(name, base, num):
    assert parse_name(name) == (base, num)


def test_grouping_bare_title_counts_as_season_one():
    shows = [
        make_show("Euphoria", rating=3),
        make_show("Euphoria Season 2", rating=2, service="HBO"),
        make_show("Only Murders", show_type=ShowType.movie),  # movies ignored
    ]
    fr = group_franchises(shows)
    assert set(fr) == {"euphoria"}
    f = fr["euphoria"]
    assert f.max_season == 2
    assert f.latest.name == "Euphoria Season 2"
    assert f.service == "HBO"


def test_eligibility_matrix():
    def f(status, rating=None):
        fr = Franchise(base="X")
        fr.latest = make_show("X", status=status, rating=rating)
        return fr

    assert eligible(f(Status.done, 3))
    assert eligible(f(Status.done, 2))
    assert eligible(f(Status.done, None))      # unrated Done follows
    assert not eligible(f(Status.done, 1))     # 'it was fine' doesn't
    assert not eligible(f(Status.poubelle))
    assert not eligible(f(Status.to_watch))    # next step already queued
    assert not eligible(f(Status.watching))


def test_eligibility_uses_latest_season_verdict():
    shows = [
        make_show("Dark Season 1", status=Status.poubelle),
        make_show("Dark Season 2", rating=3),
    ]
    f = group_franchises(shows)["dark"]
    assert eligible(f)  # latest verdict (S2: 3 stars) wins over old poubelle


class FakeResponses:
    """Stub anthropic client yielding canned responses in order."""

    def __init__(self, responses):
        self._iter = iter(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self._iter)


def _resp(stop_reason, blocks, searches=0):
    content = [SimpleNamespace(type="server_tool_use") for _ in range(searches)]
    content += [SimpleNamespace(type="text", text=t) for t in blocks]
    usage = SimpleNamespace(input_tokens=10, output_tokens=5,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(stop_reason=stop_reason, content=content, usage=usage)


def test_check_franchises_handles_pause_turn():
    payload = {"franchises": [
        {"franchise": "Euphoria", "have_season": 2, "next_season": 3,
         "released": True, "note": "premiered 2026"},
    ]}
    client = FakeResponses([
        _resp("pause_turn", [], searches=2),
        _resp("end_turn", [json.dumps(payload)], searches=1),
    ])
    results, usage, searches = check_franchises(
        client, [{"franchise": "Euphoria", "have_season": 2}], "2026-08-02")
    assert len(client.requests) == 2
    # continuation resends with the assistant turn appended, no extra user msg
    assert client.requests[1]["messages"][-1]["role"] == "assistant"
    assert results[0]["released"] is True
    assert searches == 3
    assert usage["input_tokens"] == 20


def test_check_franchises_refusal_raises():
    client = FakeResponses([_resp("refusal", [])])
    with pytest.raises(RuntimeError, match="refused"):
        check_franchises(client, [{"franchise": "X", "have_season": 1}], "2026-08-02")


def test_scout_creates_deduped_cards(monkeypatch):
    from mediamaster_api import scorer

    shows = [
        make_show("Euphoria", rating=3),
        make_show("Euphoria Season 2", rating=2, service="HBO"),
        make_show("Euphoria Season 3", status=Status.watching),  # already tracked
        make_show("Severance", rating=3, service="Apple TV+"),
    ]
    created_payloads = []
    scored = []

    monkeypatch.setattr(scorer.db, "list_shows", lambda uid: shows)
    monkeypatch.setattr(scorer.db, "get_scout_state", lambda uid: None)
    monkeypatch.setattr(scorer.db, "put_scout_state", lambda uid, u: None)
    monkeypatch.setattr(scorer.db, "get_profile",
                        lambda uid: {"profile_text": "profile", "ratings_hash": "h"})
    monkeypatch.setattr(scorer.db, "create_show",
                        lambda uid, p: created_payloads.append(p) or make_show(p.name, status=p.status, service=p.service))
    monkeypatch.setattr(scorer.db, "write_show_score",
                        lambda uid, sid, score, reason, ts, v: scored.append((score, reason)))
    monkeypatch.setattr(scorer.taste, "client", lambda: None)
    monkeypatch.setattr(scorer.taste, "score_batch",
                        lambda c, p, s: ([SimpleNamespace(show_id=s[0].show_id, score=88, reason="loved prior seasons")], {}))

    def fake_check(client, candidates, today):
        # Euphoria ineligible (S3 in watching), so only Severance arrives
        assert [c["franchise"] for c in candidates] == ["Severance"]
        return ([{"franchise": "Severance", "have_season": 1, "next_season": 2,
                  "released": True, "note": "premiered 2025-01-17"}],
                {"input_tokens": 1, "output_tokens": 1,
                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}, 1)

    monkeypatch.setattr(scorer.seasons, "check_franchises", fake_check)

    result = scorer.run_scout("uid")
    assert result["created"] == ["Severance Season 2"]
    assert created_payloads[0].service == "Apple TV+"
    assert created_payloads[0].source == "Season Scout"
    assert scored and scored[0][0] == 88
    assert "premiered 2025-01-17" in scored[0][1]


def test_single_scout_never_touches_the_full_sweep_lock(monkeypatch):
    from mediamaster_api import scorer

    shows = [make_show("Severance", rating=3)]
    state_writes = []
    monkeypatch.setattr(scorer.db, "list_shows", lambda uid: shows)
    monkeypatch.setattr(scorer.db, "get_scout_state",
                        lambda uid: {"scout_status": "running", "started_at": "2026-01-01T00:00:00+00:00"})
    monkeypatch.setattr(scorer.db, "put_scout_state", lambda uid, u: state_writes.append(u))
    monkeypatch.setattr(scorer.db, "get_profile", lambda uid: None)
    monkeypatch.setattr(scorer.taste, "client", lambda: None)
    monkeypatch.setattr(
        scorer.seasons, "check_franchises",
        lambda c, cands, t: ([], {"input_tokens": 0, "output_tokens": 0,
                                  "cache_creation_input_tokens": 0,
                                  "cache_read_input_tokens": 0}, 0))

    scorer.run_scout("uid", franchise="Severance")
    assert all("scout_status" not in w and "started_at" not in w for w in state_writes)
    assert any("last_single_run_show" in w for w in state_writes)


def test_scout_skips_when_next_season_already_on_board(monkeypatch):
    from mediamaster_api import scorer

    shows = [make_show("Slow Horses Season 4", rating=3, service="Apple TV+")]
    monkeypatch.setattr(scorer.db, "list_shows", lambda uid: shows)
    monkeypatch.setattr(scorer.db, "get_scout_state", lambda uid: None)
    monkeypatch.setattr(scorer.db, "put_scout_state", lambda uid, u: None)
    monkeypatch.setattr(scorer.db, "get_profile", lambda uid: None)
    monkeypatch.setattr(scorer.taste, "client", lambda: None)
    monkeypatch.setattr(
        scorer.seasons, "check_franchises",
        lambda c, cands, t: ([{"franchise": "Slow Horses", "have_season": 4,
                               "next_season": 4, "released": True, "note": ""}],
                             {"input_tokens": 0, "output_tokens": 0,
                              "cache_creation_input_tokens": 0,
                              "cache_read_input_tokens": 0}, 0))
    created = []
    monkeypatch.setattr(scorer.db, "create_show", lambda uid, p: created.append(p))

    result = scorer.run_scout("uid")
    assert result["created"] == [] and not created
