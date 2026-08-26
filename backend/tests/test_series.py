from mediamaster_api import series
from mediamaster_api.models import Medium, Show, ShowType, Status, now_iso

_counter = 0


def make_book(name, *, series_name=None, index=None, author=None,
              status=Status.done, rating=None):
    global _counter
    _counter += 1
    ts = f"2026-01-{min(_counter, 28):02d}T00:00:00+00:00"
    return Show(
        show_id=f"B{_counter:04d}", name=name, show_type=ShowType.book,
        medium=Medium.book, author=author, series=series_name, series_index=index,
        status=status, rating=rating,
        created_at=ts, updated_at=ts, status_changed_at=ts,
        rated_at=ts if rating else None,
    )


def test_group_series_tracks_frontier_and_author():
    books = [
        make_book("Red Rising", series_name="Red Rising Saga", index=1, author="Pierce Brown"),
        make_book("Golden Son", series_name="Red Rising Saga", index=2),
        make_book("Standalone Novel"),
    ]
    groups = series.group_series(books)
    assert set(groups) == {"red rising saga"}
    g = groups["red rising saga"]
    assert g.max_index == 2
    assert g.frontier.name == "Golden Son"
    assert g.author == "Pierce Brown"


def test_eligibility_matrix():
    def grp(status, rating=None):
        return series.group_series(
            [make_book("B1", series_name="S", index=1, status=status, rating=rating)]
        )["s"]

    assert series.eligible(grp(Status.done)) is True          # unrated done
    assert series.eligible(grp(Status.done, rating=3)) is True
    assert series.eligible(grp(Status.done, rating=1)) is False
    assert series.eligible(grp(Status.poubelle)) is False
    assert series.eligible(grp(Status.to_watch)) is False     # next already queued
    assert series.eligible(grp(Status.watching)) is False     # mid-read


def test_create_book_cards_dedupes_and_sets_fields(monkeypatch):
    from mediamaster_api import scorer

    books = [
        make_book("Red Rising", series_name="Red Rising Saga", index=1, author="Pierce Brown"),
        make_book("Golden Son", series_name="Red Rising Saga", index=2),
    ]
    groups = series.group_series(books)
    created_payloads = []
    monkeypatch.setattr(scorer.db, "get_profile", lambda uid, medium="show": None)
    monkeypatch.setattr(
        scorer.db, "create_show",
        lambda uid, p: created_payloads.append(p) or make_book(p.name, series_name=p.series,
                                                               index=p.series_index))

    results = [
        {"series": "Red Rising Saga", "next_title": "Morning Star", "next_index": 3,
         "author": "Pierce Brown", "released": True, "note": "published 2016"},
        # already owned -> index dedupe
        {"series": "Red Rising Saga", "next_title": "Golden Son", "next_index": 2,
         "released": True, "author": "Pierce Brown", "note": ""},
        # unreleased -> skipped
        {"series": "Red Rising Saga", "next_title": "Red God", "next_index": 7,
         "released": False, "author": "Pierce Brown", "note": "expected 2027"},
    ]
    created = scorer._create_book_cards("uid", groups, results)
    assert created == ["Morning Star"]
    p = created_payloads[0]
    assert p.medium == Medium.book and p.show_type == ShowType.book
    assert p.series == "Red Rising Saga" and p.series_index == 3
    assert p.author == "Pierce Brown"
    assert p.source == "Series Scout" and p.status == Status.to_watch


def test_title_dedupe_when_index_missing(monkeypatch):
    from mediamaster_api import scorer

    books = [make_book("Dawn of Everything", series_name="Loose Series")]
    groups = series.group_series(books)
    monkeypatch.setattr(scorer.db, "get_profile", lambda uid, medium="show": None)
    monkeypatch.setattr(scorer.db, "create_show", lambda uid, p: make_book(p.name))
    results = [{"series": "Loose Series", "next_title": "dawn of everything",
                "next_index": 0, "author": "", "released": True, "note": ""}]
    assert scorer._create_book_cards("uid", groups, results) == []
