

def test_board_medium_filter_and_unverified_roundtrip(client):
    book = {"name": "Golden Son", "show_type": "book", "medium": "book",
            "author": "Pierce Brown", "series": "Red Rising Saga",
            "series_index": 2, "unverified": True, "status": "done"}
    bid = client.post("/api/shows", json=book).json()["show_id"]
    client.post("/api/shows", json={"name": "Severance", "show_type": "tv"})

    shows_board = client.get("/api/board").json()["columns"]
    books_board = client.get("/api/board", params={"medium": "book"}).json()["columns"]
    assert all(s["medium"] == "show"
               for col in shows_board.values() for s in col)
    assert [s["name"] for s in books_board["done"]] == ["Golden Son"]
    b = books_board["done"][0]
    assert b["author"] == "Pierce Brown" and b["series_index"] == 2.0
    assert b["unverified"] is True

    # claiming the book clears the triage flag; series fields survive the patch
    resp = client.patch(f"/api/shows/{bid}", json={"unverified": False})
    assert resp.json()["unverified"] is False
    again = client.get("/api/board", params={"medium": "book"}).json()["columns"]["done"][0]
    assert again["series"] == "Red Rising Saga" and again["unverified"] is False
