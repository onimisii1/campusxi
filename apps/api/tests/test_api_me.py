"""Profiles and auth (PRD A1, A2, 11.2)."""
import uuid

from tests.conftest import auth, make_school, make_user, token


def test_profile_flow(client, db):
    school = make_school(db)
    uid = uuid.uuid4()
    res = client.get("/me", headers=auth(uid))
    assert res.status_code == 403 and res.json()["error"]["code"] == "profile_required"

    res = client.post("/me", headers=auth(uid), json={"school_id": str(school), "team_name": "Goal Machine",
                                                      "dob": "2005-03-01"})
    assert res.status_code == 201, res.json()
    assert res.json()["roles"] == ["player"] and res.json()["kyc_status"] == "none"
    assert client.get("/me", headers=auth(uid)).json()["team_name"] == "Goal Machine"

    again = client.post("/me", headers=auth(uid), json={"school_id": str(school), "team_name": "Other",
                                                        "dob": "2005-03-01"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "profile_exists"


def test_under_18_refused(client, db):
    school = make_school(db)
    # clock is 10 Nov 2026: born 11 Nov 2008 is one day short of 18
    res = client.post("/me", headers=auth(uuid.uuid4()),
                      json={"school_id": str(school), "team_name": "Youngster", "dob": "2008-11-11"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "under_18"
    ok = client.post("/me", headers=auth(uuid.uuid4()),
                     json={"school_id": str(school), "team_name": "JustEighteen", "dob": "2008-11-10"})
    assert ok.status_code == 201


def test_team_name_taken_ignores_case(client, db):
    school = make_school(db)
    make_user(db, school, team_name="Striker")
    res = client.post("/me", headers=auth(uuid.uuid4()),
                      json={"school_id": str(school), "team_name": "STRIKER", "dob": "2000-01-01"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "team_name_taken"


def test_unknown_school(client):
    res = client.post("/me", headers=auth(uuid.uuid4()),
                      json={"school_id": str(uuid.uuid4()), "team_name": "Nowhere", "dob": "2000-01-01"})
    assert res.json()["error"]["code"] == "unknown_school"


def test_bad_tokens(client):
    assert client.get("/me").json()["error"]["code"] == "unauthenticated"
    forged = {"Authorization": f"Bearer {token(uuid.uuid4(), secret='wrong-secret-wrong-secret-wrong!!')}"}
    assert client.get("/me", headers=forged).json()["error"]["code"] == "invalid_token"
    wrong_aud = {"Authorization": f"Bearer {token(uuid.uuid4(), aud='anon')}"}
    assert client.get("/me", headers=wrong_aud).status_code == 401


def test_validation_errors_use_error_shape(client, db):
    school = make_school(db)
    res = client.post("/me", headers=auth(uuid.uuid4()), json={"school_id": str(school), "team_name": "x"})
    body = res.json()
    assert res.status_code == 422 and body["error"]["code"] == "validation_error"
    assert {d["field"] for d in body["error"]["details"]} >= {"team_name", "dob"}
