from unittest.mock import patch

from mediamaster_api import db

from conftest import TEST_UID

OTHER_UID = "other-user"


def _register_both():
    db.put_user(TEST_UID, "jon@example.com", "Jon Test")
    db.put_user(OTHER_UID, "kelly@example.com", "Kelly Test")


def _add_book(client, name="The Nightingale", unverified=True):
    resp = client.post("/api/shows", json={
        "name": name, "show_type": "book", "medium": "book",
        "author": "Kristin Hannah", "status": "done", "unverified": unverified,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_users_endpoint_excludes_caller(client):
    _register_both()
    users = client.get("/api/users").json()
    assert [u["uid"] for u in users] == [OTHER_UID]


def test_transfer_moves_card_and_resets_llm_fields(client):
    _register_both()
    book = _add_book(client)
    db.write_show_score(TEST_UID, book["show_id"], 88, "great fit",
                        "2026-08-29T00:00:00+00:00", "abc123")

    with patch("mediamaster_api.main._invoke_scorer") as invoke:
        resp = client.post(f"/api/shows/{book['show_id']}/transfer",
                           json={"to_uid": OTHER_UID})
    assert resp.status_code == 200
    moved = resp.json()

    # source gone
    assert db.get_show(TEST_UID, book["show_id"]) is None
    # target has it with fields intact but llm scores cleared
    theirs = db.get_show(OTHER_UID, moved["show_id"])
    assert theirs is not None
    assert theirs.name == "The Nightingale"
    assert theirs.author == "Kristin Hannah"
    assert theirs.unverified is True
    assert theirs.llm_score is None and theirs.llm_reason is None
    # recipient's scorer invoked for their own re-score
    invoke.assert_called_once()
    assert invoke.call_args[0][0]["uid"] == OTHER_UID


def test_transfer_rejects_unknown_target_and_self(client):
    _register_both()
    book = _add_book(client)
    assert client.post(f"/api/shows/{book['show_id']}/transfer",
                       json={"to_uid": "nobody"}).status_code == 403
    assert client.post(f"/api/shows/{book['show_id']}/transfer",
                       json={"to_uid": TEST_UID}).status_code == 403
    assert client.post("/api/shows/01XXXXXXXXXXXXXXXXXXXXXXXX/transfer",
                       json={"to_uid": OTHER_UID}).status_code == 404


def test_scheduled_sweep_loops_all_users(table, monkeypatch):
    from mediamaster_api import scorer

    _register_both()
    swept = []
    monkeypatch.setattr(scorer, "run_scout", lambda uid, franchise=None: swept.append(("show", uid)) or {})
    monkeypatch.setattr(scorer, "run_series_scout", lambda uid, series_name=None: swept.append(("book", uid)) or {})

    result = scorer.handler({"mode": "scout", "medium": "all"}, None)
    assert ("show", TEST_UID) in swept and ("show", OTHER_UID) in swept
    assert ("book", TEST_UID) in swept and ("book", OTHER_UID) in swept
    assert set(result) == {"jon@example.com", "kelly@example.com"}


def test_scheduled_sweep_survives_one_user_failing(table, monkeypatch):
    from mediamaster_api import scorer

    _register_both()

    def boom(uid, franchise=None):
        if uid == TEST_UID:
            raise RuntimeError("kaput")
        return {"ok": True}

    monkeypatch.setattr(scorer, "run_scout", boom)
    monkeypatch.setattr(scorer, "run_series_scout", lambda uid, series_name=None: {})
    result = scorer.handler({"mode": "scout", "medium": "all"}, None)
    assert result["jon@example.com"] == {"error": True}
    assert "book" in result["kelly@example.com"]
