"""Local demo: a database with one football match ready to score, plus sign-in tokens.

    python scripts/dev_seed.py              # starts a local Postgres in apps/api/.devdb (pgserver)
    DATABASE_URL=... python scripts/dev_seed.py
    KICKOFF_IN_MINUTES=5 python scripts/dev_seed.py
    python scripts/dev_seed.py --reset      # wipe the local .devdb database first

Prints DATABASE_URL, SUPABASE_JWT_SECRET and tokens for an admin, two scorers, two fans
and a newcomer with no profile yet.
Start the API with those two variables set, then paste a scorer token into the web
app's development sign-in (#/scorer). Never point this at a production database.
"""
import os
import pathlib
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import psycopg

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))


def database_url(reset: bool) -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    import pgserver
    server = pgserver.get_server(ROOT / ".devdb", cleanup_mode=None)
    with psycopg.connect(server.get_uri(), autocommit=True) as c:
        if reset:
            c.execute("drop database if exists campusxi with (force)")
        if not c.execute("select 1 from pg_database where datname = 'campusxi'").fetchone():
            c.execute("create database campusxi")
    return server.get_uri("campusxi")


def migrate(url: str):
    """Apply pending migrations, tracked like the Supabase CLI does."""
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("create schema if not exists supabase_migrations")
        c.execute("create table if not exists supabase_migrations.schema_migrations (version text primary key)")
        done = {r[0] for r in c.execute("select version from supabase_migrations.schema_migrations")}
        for path in sorted((REPO / "supabase" / "migrations").glob("*.sql")):
            version = path.name.split("_")[0]
            if version in done:
                continue
            with c.transaction():
                c.execute(path.read_text(encoding="utf-8"))
                c.execute("insert into supabase_migrations.schema_migrations (version) values (%s)", (version,))
            print(f"applied {path.name}", file=sys.stderr)


def main():
    url = database_url(reset="--reset" in sys.argv)
    secret = os.environ.get("SUPABASE_JWT_SECRET") or secrets.token_urlsafe(32)
    os.environ.update(DATABASE_URL=url, SUPABASE_JWT_SECRET=secret)
    migrate(url)

    with psycopg.connect(url, autocommit=True) as c:
        school = c.execute("insert into schools (name) values (%s) returning id",
                           (f"Demo University {secrets.token_hex(2)}",)).fetchone()[0]
        users = {}
        for name, roles in (("admin", ["player", "admin"]), ("scorer_a", ["player", "scorer"]),
                            ("scorer_b", ["player", "scorer"]), ("fan_a", ["player"]), ("fan_b", ["player"])):
            uid = uuid.uuid4()
            c.execute("insert into users (id, school_id, team_name, roles, dob) values (%s, %s, %s, %s, '2000-01-01')",
                      (uid, school, f"{name}_{uid.hex[:4]}", roles))
            users[name] = uid

    from fastapi.testclient import TestClient

    from app.main import app

    def tok(uid):
        return jwt.encode({"sub": str(uid), "aud": "authenticated",
                           "exp": datetime.now(timezone.utc) + timedelta(days=7)}, secret, algorithm="HS256")

    admin = {"Authorization": f"Bearer {tok(users['admin'])}"}
    client = TestClient(app)

    def ok(res):
        if res.status_code >= 300:
            sys.exit(f"seed failed: {res.status_code} {res.text}")
        return res.json()

    seed = REPO / "supabase" / "seed"
    t = ok(client.post("/admin/tournaments", headers=admin, json={
        "school_id": str(school), "sport": "football", "name": "Demo Cup", "match_minutes": 90}))
    ok(client.post(f"/admin/tournaments/{t['id']}/squads", headers=admin,
                   content=(seed / "example_football_squads.csv").read_text()))
    minutes = int(os.environ.get("KICKOFF_IN_MINUTES", "20"))
    kickoff = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).replace(microsecond=0)
    ok(client.post(f"/admin/tournaments/{t['id']}/fixtures", headers=admin,
                   content=f"home_team,away_team,scheduled_start,venue\nEngineering,Law,{kickoff.isoformat()},Main Bowl\n"))
    ok(client.post(f"/admin/tournaments/{t['id']}/publish", headers=admin))
    match = ok(client.get("/matches", params={"tournament_id": t["id"]}))[0]
    detail = ok(client.get(f"/matches/{match['id']}"))
    starters = [a["id"] for side in ("home", "away") for a in detail["squads"][side]
                if a["name"].split()[-2] in ("GK", "DEF", "MID", "FWD")
                and int(a["name"].split()[-1]) <= {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}[a["name"].split()[-2]]]
    bench = [a["id"] for a in detail["squads"]["home"] if a["name"] == "Engineering FWD 3"]
    ok(client.post(f"/admin/matches/{match['id']}/lineup", headers=admin, json={"starters": starters, "bench": bench}))
    ok(client.post(f"/admin/matches/{match['id']}/scorers", headers=admin,
                   json={"user_ids": [str(users["scorer_a"]), str(users["scorer_b"])]}))

    print(f"DATABASE_URL={url}")
    print(f"SUPABASE_JWT_SECRET={secret}")
    print(f"MATCH_ID={match['id']}  kick-off {kickoff.isoformat()}")
    for name, uid in users.items():
        print(f"TOKEN_{name.upper()}={tok(uid)}")
    print(f"TOKEN_NEWCOMER={tok(uuid.uuid4())}   # signed in, no profile yet")


if __name__ == "__main__":
    main()
