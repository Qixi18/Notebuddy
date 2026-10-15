from fastapi.testclient import TestClient

from app.main import app


def test_local_browser_can_preflight_reading_position_put():
    response = TestClient(app).options(
        "/api/v1/courses/course/notebooks/book/reading-position",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "PUT" in response.headers["access-control-allow-methods"]
