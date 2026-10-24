import base64

pytest_plugins = ["tests.test_notebook_api"]


def test_cover_move_delete_and_restore_notebook(setup, monkeypatch, tmp_path):
    from app.core.config import settings

    client, _, course, *_ = setup
    other = client.post("/api/v1/courses", json={"name": "另一门课"}).json()
    created = client.post(f"/api/v1/courses/{course.id}/notebooks", json={"title": "随堂笔记"})
    assert created.status_code == 201, created.text
    book = created.json()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pXcAAAAASUVORK5CYII=")
    cover = client.put(f"/api/v1/notebooks/{book['id']}/cover", files={"file": ("cover.png", png, "image/png")})
    assert cover.status_code == 200, cover.text
    assert client.get(cover.json()["cover_url"]).status_code == 200
    moved = client.post(f"/api/v1/notebooks/{book['id']}/move", json={"course_id": other["id"]})
    assert moved.status_code == 200 and moved.json()["cover_url"]
    assert client.get(f"/api/v1/courses/{other['id']}/notebooks").json()[0]["id"] == book["id"]
    monkeypatch.setattr("app.services.deletion._checkpoint", lambda: None)
    assert client.delete(f"/api/v1/courses/{other['id']}/notebooks/{book['id']}").status_code == 204
    assert client.get(f"/api/v1/courses/{other['id']}/notebooks").json() == []
    deleted = client.get("/api/v1/notebooks/deleted")
    assert deleted.status_code == 200 and deleted.json()[0]["id"] == book["id"]
    restored = client.post(f"/api/v1/notebooks/{book['id']}/restore", json={"course_id": other["id"]})
    assert restored.status_code == 200 and restored.json()["cover_url"]
    assert client.get(f"/api/v1/courses/{other['id']}/notebooks").json()[0]["id"] == book["id"]
