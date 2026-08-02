from mediamaster_api.models import Show, Status
from mediamaster_api.scoring import score_board, sort_to_watch

_counter = 0


def make_show(name, status=Status.to_watch, rating=None, source=None, service=None,
              show_type="tv", created_at=None):
    global _counter
    _counter += 1
    ts = created_at or f"2026-01-{_counter:02d}T00:00:00.000+00:00"
    return Show(
        show_id=f"id{_counter}", name=name, show_type=show_type, service=service,
        source=source, status=status, rating=rating, created_at=ts,
        updated_at=ts, status_changed_at=ts,
    )


def test_no_history_scores_zero():
    shows = [make_show("A"), make_show("B")]
    score_board(shows)
    assert all(s.predicted_score == 0.0 for s in shows)


def test_poubelle_only_history_keeps_neutral_base():
    # Nothing rated in Done yet: base stays 0, only tainted features go negative.
    history = [make_show(f"p{i}", status=Status.poubelle, source="Ads") for i in range(4)]
    tainted = make_show("tainted", source="Ads")
    neutral = make_show("neutral", source="Maria", show_type="movie")
    shows = history + [tainted, neutral]
    score_board(shows)
    assert neutral.predicted_score == 0.0  # no feature overlap with the trash
    assert tainted.predicted_score < -0.5


def test_trusted_source_ranks_first():
    history = [make_show(f"h{i}", status=Status.done, rating=3, source="Alice") for i in range(5)]
    history += [make_show(f"p{i}", status=Status.poubelle, source="Bob") for i in range(5)]
    alice_pick = make_show("Alice pick", source="Alice")
    bob_pick = make_show("Bob pick", source="Bob")
    nobody_pick = make_show("Nobody pick")
    shows = history + [alice_pick, bob_pick, nobody_pick]
    score_board(shows)
    ordered = sort_to_watch([alice_pick, bob_pick, nobody_pick])
    assert [s.name for s in ordered] == ["Alice pick", "Nobody pick", "Bob pick"]
    assert alice_pick.predicted_score > 0
    assert bob_pick.predicted_score < 0


def test_smoothing_pulls_small_samples_toward_mean():
    # One 3-star from a new source vs ten 3-stars from a proven source
    history = [make_show("one", status=Status.done, rating=3, source="NewGuy")]
    history += [make_show(f"h{i}", status=Status.done, rating=3, source="Vet") for i in range(10)]
    # ballast so the global mean isn't already +2
    history += [make_show(f"m{i}", status=Status.done, rating=1, source="Meh") for i in range(10)]
    new_pick = make_show("new pick", source="NewGuy")
    vet_pick = make_show("vet pick", source="Vet")
    shows = history + [new_pick, vet_pick]
    score_board(shows)
    assert vet_pick.predicted_score > new_pick.predicted_score


def test_poubelle_counts_as_strong_negative():
    history = [make_show(f"p{i}", status=Status.poubelle, service="Quibi") for i in range(4)]
    history += [make_show(f"h{i}", status=Status.done, rating=2, service="Max") for i in range(4)]
    quibi = make_show("q", service="Quibi")
    max_ = make_show("m", service="Max")
    shows = history + [quibi, max_]
    score_board(shows)
    assert quibi.predicted_score < max_.predicted_score


def test_source_outweighs_service_and_type():
    history = [
        make_show("a", status=Status.done, rating=3, source="Alice", service="BadFlix", show_type="movie"),
        make_show("b", status=Status.poubelle, source="Bob", service="GoodFlix", show_type="tv"),
    ]
    # same show except source; feature weights should make source dominate
    alice = make_show("x", source="Alice", service="GoodFlix", show_type="tv")
    bob = make_show("y", source="Bob", service="GoodFlix", show_type="tv")
    shows = history + [alice, bob]
    score_board(shows)
    assert alice.predicted_score > bob.predicted_score


def test_unrated_done_shows_are_not_history():
    shows = [make_show("d", status=Status.done, rating=None, source="Alice"),
             make_show("w", source="Alice")]
    score_board(shows)
    assert shows[1].predicted_score == 0.0
    assert "source" not in shows[1].score_breakdown


def test_case_insensitive_feature_matching():
    history = [make_show("h", status=Status.done, rating=3, source="alice")]
    pick = make_show("p", source="ALICE")
    shows = history + [pick]
    score_board(shows)
    assert pick.score_breakdown["source"]["rated_count"] == 1


def test_recency_tiebreak_newest_first():
    a = make_show("older", created_at="2026-01-01T00:00:00.000+00:00")
    b = make_show("newer", created_at="2026-02-01T00:00:00.000+00:00")
    score_board([a, b])
    assert [s.name for s in sort_to_watch([a, b])] == ["newer", "older"]


def test_breakdown_explains_score():
    history = [make_show(f"h{i}", status=Status.done, rating=3, source="Alice") for i in range(3)]
    pick = make_show("p", source="Alice")
    shows = history + [pick]
    score_board(shows)
    bd = pick.score_breakdown
    assert bd["source"]["value"] == "Alice"
    assert bd["source"]["rated_count"] == 3
    # score = base + sum of adjustments
    total = bd["base"] + bd["source"]["adjustment"]
    assert abs(total - pick.predicted_score) < 0.01
