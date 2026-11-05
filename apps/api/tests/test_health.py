from fastapi.testclient import TestClient

from app.main import app


def test_health():
    res = TestClient(app).get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert set(res.json()["scoring_rules"]) == {"football", "basketball", "volleyball"}
