from fastapi.testclient import TestClient

from app.main import app


def test_health():
    res = TestClient(app).get("/health")
    assert res.status_code == 200
    # no database in this bare test, so health honestly reports "degraded" (test_backend covers "ok")
    assert res.json()["status"] in ("ok", "degraded") and "database" in res.json()
    assert set(res.json()["scoring_rules"]) == {"football", "basketball", "volleyball"}
