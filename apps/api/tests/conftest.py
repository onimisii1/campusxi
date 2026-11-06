"""Database fixtures for integration tests.

A real Postgres is used: TEST_DATABASE_URL if set (e.g. CI), otherwise a throwaway
server from the `pgserver` package. Migrations are applied once to a template
database; every test gets a fresh copy of it, so tests never share state and the
append-only tables never need truncating.
"""
import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

MIGRATIONS = pathlib.Path(__file__).resolve().parents[3] / "supabase" / "migrations"
JWT_SECRET = "test-only-jwt-secret-that-is-long-enough"
TEMPLATE = "campusxi_template"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def pg_admin_url(tmp_path_factory):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    import pgserver
    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"), cleanup_mode="stop")
    yield server.get_uri()


@pytest.fixture(scope="session")
def template_db(pg_admin_url):
    with psycopg.connect(pg_admin_url, autocommit=True) as c:
        c.execute(f"drop database if exists {TEMPLATE}")
        c.execute(f"create database {TEMPLATE}")
    with psycopg.connect(make_conninfo(pg_admin_url, dbname=TEMPLATE), autocommit=True) as c:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            c.execute(path.read_text(encoding="utf-8"))
    return TEMPLATE


@pytest.fixture
def db_url(pg_admin_url, template_db):
    name = "t_" + uuid.uuid4().hex[:16]
    with psycopg.connect(pg_admin_url, autocommit=True) as c:
        c.execute(f"create database {name} template {template_db}")
    yield make_conninfo(pg_admin_url, dbname=name)
    with psycopg.connect(pg_admin_url, autocommit=True) as c:
        c.execute(f"drop database {name} with (force)")


@pytest.fixture
def db(db_url):
    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as conn:
        yield conn


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def client(db_url, monkeypatch):
    from fastapi.testclient import TestClient

    from app.clock import utcnow
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "supabase_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)   # test_backend.py turns it back on
    clock = Clock(NOW)
    app.dependency_overrides[utcnow] = clock
    with TestClient(app) as c:
        c.clock = clock
        yield c
    app.dependency_overrides.clear()


# ---------- helpers ----------

def token(user_id, secret=JWT_SECRET, **claims) -> str:
    payload = {"sub": str(user_id), "aud": "authenticated", "email": f"{user_id}@example.test",
               "exp": datetime.now(timezone.utc) + timedelta(hours=1), **claims}
    return jwt.encode(payload, secret, algorithm="HS256")


def auth(user_id) -> dict:
    return {"Authorization": f"Bearer {token(user_id)}"}


def make_school(db, name="Demo University") -> uuid.UUID:
    return db.execute("insert into schools (name) values (%s) returning id", (name,)).fetchone()["id"]


def make_user(db, school_id, roles=("player",), team_name=None) -> uuid.UUID:
    uid = uuid.uuid4()
    db.execute("insert into users (id, school_id, team_name, roles, dob) values (%s, %s, %s, %s, '2000-01-01')",
               (uid, school_id, team_name or f"user_{uid.hex[:8]}", list(roles)))
    return uid


FOOTBALL_TEAMS = ("Engineering", "Law", "Medicine", "Sciences")
FOOTBALL_SHAPE = (("GK", 2), ("DEF", 6), ("MID", 6), ("FWD", 4))


def football_squads_csv(teams=FOOTBALL_TEAMS) -> str:
    lines = ["team,athlete,position"]
    for team in teams:
        for pos, n in FOOTBALL_SHAPE:
            lines += [f"{team},{team} {pos} {i},{pos}" for i in range(1, n + 1)]
    return "\n".join(lines) + "\n"


def fixtures_csv(rows) -> str:
    return "home_team,away_team,scheduled_start,venue\n" + "\n".join(",".join(r) for r in rows) + "\n"


@pytest.fixture
def world(client, db):
    """A published football tournament at Demo University with one match on 12 Nov 2026."""
    school = make_school(db)
    admin = make_user(db, school, roles=("player", "admin"), team_name="sports_admin")
    player = make_user(db, school, team_name="fan_one")
    t = client.post("/admin/tournaments", headers=auth(admin), json={
        "school_id": str(school), "sport": "football", "name": "Inter-Faculty Cup 2026", "match_minutes": 90,
    }).json()
    assert client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(admin),
                       content=football_squads_csv()).status_code == 200
    assert client.post(f"/admin/tournaments/{t['id']}/fixtures", headers=auth(admin), content=fixtures_csv([
        ("Engineering", "Law", "2026-11-12T16:00:00", "Main Bowl"),
        ("Medicine", "Sciences", "2026-11-13T16:00:00+01:00", "Main Bowl"),
    ])).status_code == 200
    assert client.post(f"/admin/tournaments/{t['id']}/publish", headers=auth(admin)).status_code == 200
    match = client.get("/matches", params={"tournament_id": t["id"]}).json()[0]
    return {"school": school, "admin": admin, "player": player, "tournament": t, "match": match}


def athletes_by_name(db, match_id) -> dict:
    rows = db.execute(
        """select a.id, a.display_name from athletes a join matches m on a.team_id in (m.home_team_id, m.away_team_id)
           where m.id = %s""", (match_id,)).fetchall()
    return {r["display_name"]: str(r["id"]) for r in rows}


def valid_picks(names: dict) -> list:
    """1 GK, 4 DEF, 4 MID, 2 FWD; 6 Engineering + 5 Law; C/VC/Key set."""
    chosen = (["Engineering GK 1", "Engineering DEF 1", "Engineering DEF 2", "Law DEF 1", "Law DEF 2",
               "Engineering MID 1", "Engineering MID 2", "Law MID 1", "Law MID 2", "Engineering FWD 1", "Law FWD 1"])
    roles = {"Engineering FWD 1": "captain", "Law FWD 1": "vice_captain", "Engineering MID 1": "key"}
    return [{"athlete_id": names[n], "role": roles.get(n, "none")} for n in chosen]
