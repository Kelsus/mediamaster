def add(client, name, **kwargs):
    payload = {"name": name, "show_type": "tv", **kwargs}
    resp = client.post("/api/shows", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_board(client):
    add(client, "Severance", service="Apple TV+", source="Alice")
    add(client, "Heat", show_type="movie")
    board = client.get("/api/board").json()
    names = [s["name"] for s in board["columns"]["to_watch"]]
    assert set(names) == {"Severance", "Heat"}
    assert all(c in board["columns"] for c in ("to_watch", "watching", "done", "poubelle"))


def test_move_and_rate_flow(client):
    show = add(client, "The Wire")
    resp = client.patch(f"/api/shows/{show['show_id']}", json={"status": "done", "rating": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done" and body["rating"] == 3 and body["rated_at"]

    # moving out of done clears the rating
    resp = client.patch(f"/api/shows/{show['show_id']}", json={"status": "to_watch"})
    assert resp.json()["rating"] is None


def test_rating_requires_done(client):
    show = add(client, "Fargo")
    resp = client.patch(f"/api/shows/{show['show_id']}", json={"rating": 2})
    assert resp.status_code == 422


def test_rating_with_move_to_done_in_one_patch(client):
    show = add(client, "Tampopo", show_type="movie")
    resp = client.patch(f"/api/shows/{show['show_id']}", json={"status": "done", "rating": 1})
    assert resp.status_code == 200
    assert resp.json()["rating"] == 1


def test_edit_in_place_and_clear_optional_field(client):
    show = add(client, "Dark", service="Netflix")
    resp = client.patch(f"/api/shows/{show['show_id']}", json={"name": "Dark (DE)", "service": None})
    body = resp.json()
    assert body["name"] == "Dark (DE)"
    assert body.get("service") is None


def test_delete(client):
    show = add(client, "Doomed")
    assert client.delete(f"/api/shows/{show['show_id']}").status_code == 204
    assert client.delete(f"/api/shows/{show['show_id']}").status_code == 404


def test_bulk_create_with_backdated_created_at(client):
    resp = client.post("/api/shows/bulk", json={"shows": [
        {"name": "Old Pick", "show_type": "movie", "created_at": "2023-05-01T00:00:00+00:00"},
        {"name": "Rated Import", "show_type": "tv", "status": "done", "rating": 2},
        {"name": "Trash Import", "show_type": "tv", "status": "poubelle"},
    ]})
    assert resp.status_code == 200
    assert resp.json()["created"] == 3
    board = client.get("/api/board").json()["columns"]
    assert board["to_watch"][0]["created_at"].startswith("2023-05-01")
    assert board["done"][0]["rating"] == 2
    assert len(board["poubelle"]) == 1


def test_board_sorted_by_preference(client):
    for i in range(4):
        show = add(client, f"alice hit {i}", source="Alice")
        client.patch(f"/api/shows/{show['show_id']}", json={"status": "done", "rating": 3})
    for i in range(4):
        show = add(client, f"bob miss {i}", source="Bob")
        client.patch(f"/api/shows/{show['show_id']}", json={"status": "poubelle"})
    add(client, "bob pick", source="Bob")
    add(client, "alice pick", source="Alice")
    board = client.get("/api/board").json()["columns"]["to_watch"]
    assert board[0]["name"] == "alice pick"
    assert board[-1]["name"] == "bob pick"
    assert board[0]["predicted_score"] > board[-1]["predicted_score"]


def test_token_lifecycle(client):
    resp = client.post("/api/tokens", json={"label": "mcp"})
    assert resp.status_code == 201
    token = resp.json()
    assert token["token"].startswith("mm_")

    listed = client.get("/api/tokens").json()
    assert listed[0]["prefix"] == token["prefix"]
    assert "token" not in listed[0]

    assert client.delete(f"/api/tokens/{token['prefix']}").status_code == 204
    assert client.get("/api/tokens").json() == []
