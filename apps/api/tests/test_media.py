"""Photo uploads: avatars, team crests, match photos."""
from tests.conftest import auth, make_school, make_user
from tests.test_api_scorer import sw  # noqa: F401  (fixture)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 300
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 300


def _put(client, url, user, body, ctype):
    return client.put(url, headers={**auth(user), "Content-Type": ctype}, content=body)


def test_avatar_upload_serve_and_validation(client, db):
    u = make_user(db, make_school(db), team_name="photo_fc")
    res = _put(client, "/me/avatar", u, PNG, "image/png")
    assert res.status_code == 200
    url = res.json()["avatar_url"]
    assert client.get("/me", headers=auth(u)).json()["avatar_url"] == url
    img = client.get(url)
    assert img.status_code == 200 and img.content == PNG and img.headers["content-type"] == "image/png"
    assert "immutable" in img.headers["cache-control"] and img.headers["x-content-type-options"] == "nosniff"

    assert _put(client, "/me/avatar", u, b"<svg onload=alert(1)>" + b" " * 200, "image/svg+xml").status_code == 415
    assert _put(client, "/me/avatar", u, b"<html>" + b" " * 200, "image/png").json()["error"]["code"] == "not_an_image"
    assert _put(client, "/me/avatar", u, JPEG, "image/png").json()["error"]["code"] == "not_an_image"
    assert _put(client, "/me/avatar", u, b"\xff\xd8\xff" + b"\x00" * 1_600_000, "image/jpeg").status_code == 413
    assert client.delete("/me/avatar", headers=auth(u)).json() == {"avatar_url": None}


def test_crest_and_match_photo(sw, client, db):
    mid, admin = sw["match"]["id"], sw["admin"]
    team_id = sw["match"]["home_team"]["id"]
    assert _put(client, f"/admin/teams/{team_id}/logo", sw["player"], PNG, "image/png").status_code == 403
    logo = _put(client, f"/admin/teams/{team_id}/logo", admin, PNG, "image/png").json()["logo"]
    photo = _put(client, f"/admin/matches/{mid}/photo", admin, JPEG, "image/jpeg").json()["photo_url"]
    card = client.get(f"/matches/{mid}").json()
    assert card["home_team"]["logo"] == logo and card["photo_url"] == photo
    assert client.get(photo).content == JPEG
    other = make_user(db, make_school(db, "Elsewhere"), roles=("player", "admin"))
    assert _put(client, f"/admin/matches/{mid}/photo", other, JPEG, "image/jpeg").status_code == 403
    assert client.delete(f"/admin/matches/{mid}/photo", headers=auth(admin)).json() == {"photo_url": None}

    # fans' photos appear in the people row
    _put(client, "/me/avatar", sw["player"], PNG, "image/png")
    from tests.conftest import valid_picks
    client.post(f"/matches/{mid}/teams", headers=auth(sw["player"]), json={"picks": valid_picks(sw["names"])})
    card = next(m for m in client.get("/matches").json() if m["id"] == mid)
    assert card["fans"] == 1 and card["fans_avatars"][0].startswith("/media/")
