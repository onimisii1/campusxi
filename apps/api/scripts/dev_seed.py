"""Local database with ONLY the real NUESA data from the gitignored data/ folder, plus test logins.

    python scripts/dev_seed.py               # starts a local Postgres in apps/api/.devdb (pgserver)
    python scripts/dev_seed.py --reset       # wipe the local .devdb database first, then reload data/
    python scripts/dev_seed.py --challenges  # the test fans post free challenges on the next match
    DATABASE_URL=... python scripts/dev_seed.py

Loads nuesa_{football,basketball}_{squads,fixtures,results,result_stats}.csv from data/ and creates
bare Nile test logins (admin, two scorers, two fans: no teams, money or challenges). Prints
DATABASE_URL, SUPABASE_JWT_SECRET and their sign-in tokens, plus a newcomer with no profile yet.
Start the API with those two variables set, then paste a token into the web app's development
sign-in (#/signin, or #/scorer for scorers). Never point this at a production database.
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

LOGINS = (("admin", ["player", "admin"]), ("scorer_a", ["player", "scorer"]), ("scorer_b", ["player", "scorer"]),
          ("fan_a", ["player"]), ("fan_b", ["player"]))


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
    data = REPO / "data"
    if not (data / "nuesa_football_squads.csv").exists():
        sys.exit("no data/nuesa_*.csv files: put the NUESA CSVs in the repo's data/ folder first")
    url = database_url(reset="--reset" in sys.argv)
    secret = os.environ.get("SUPABASE_JWT_SECRET") or secrets.token_urlsafe(32)
    os.environ.update(DATABASE_URL=url, SUPABASE_JWT_SECRET=secret)
    migrate(url)

    # Bare test logins at Nile (no teams, money or challenges of their own); reused on later runs.
    with psycopg.connect(url, autocommit=True) as c:
        row = c.execute("select id from schools where name = 'Nile University of Nigeria'").fetchone()
        school = row[0] if row else c.execute(
            "insert into schools (name) values ('Nile University of Nigeria') returning id").fetchone()[0]
        users = {}
        for name, roles in LOGINS:
            found = c.execute("select id from users where team_name = %s", (f"nile_{name}",)).fetchone()
            users[name] = found[0] if found else c.execute(
                "insert into users (id, school_id, team_name, roles, dob) values (%s, %s, %s, %s, '2000-01-01') "
                "returning id", (uuid.uuid4(), school, f"nile_{name}", roles)).fetchone()[0]
        loaded = c.execute("select count(*) from tournaments where name like 'NUESA %%'").fetchone()[0]

    from fastapi.testclient import TestClient

    from app.main import app

    def tok(uid):
        return jwt.encode({"sub": str(uid), "aud": "authenticated",
                           "exp": datetime.now(timezone.utc) + timedelta(days=7)}, secret, algorithm="HS256")

    client = TestClient(app)

    def ok(res):
        if res.status_code >= 300:
            sys.exit(f"seed failed: {res.status_code} {res.text}")
        return res.json()

    if loaded:
        print("NUESA tournaments already loaded (use --reset to reload them from data/)", file=sys.stderr)
    else:
        load_nuesa(client, ok, {"Authorization": f"Bearer {tok(users['admin'])}"}, school, data)
    if "--challenges" in sys.argv:
        post_test_challenges(client, ok, tok, users)

    print(f"DATABASE_URL={url}")
    print(f"SUPABASE_JWT_SECRET={secret}")
    for name, uid in users.items():
        print(f"TOKEN_{name.upper()}={tok(uid)}")
    print(f"TOKEN_NEWCOMER={tok(uuid.uuid4())}   # signed in, no profile yet")


def load_nuesa(client, ok, admin, school, data):
    """Import the real tournament from the gitignored data/ folder:
    nuesa_{football,basketball}_{squads,fixtures,results,result_stats}.csv (results are optional).
    Those files hold students' names, so they never go into git."""
    for sport, minutes in (("football", 30), ("basketball", 32)):
        if not (data / f"nuesa_{sport}_squads.csv").exists():
            continue
        t = ok(client.post("/admin/tournaments", headers=admin, json={
            "school_id": str(school), "sport": sport, "name": f"NUESA Sports Tournament 2026/27 ({sport.title()})",
            "match_minutes": minutes}))
        for kind, route in (("squads", "squads"), ("fixtures", "fixtures"), ("results", "results"),
                            ("result_stats", "result-stats")):
            path = data / f"nuesa_{sport}_{kind}.csv"
            if path.exists():
                ok(client.post(f"/admin/tournaments/{t['id']}/{route}", headers=admin,
                               content=path.read_text(encoding="utf-8")))
        ok(client.post(f"/admin/tournaments/{t['id']}/publish", headers=admin))
        print(f"NUESA {sport} tournament {t['id']} loaded", file=sys.stderr)


def post_test_challenges(client, ok, tok, users):
    """--challenges: so the swipe deck has cards locally, the two test fans each build a team for the
    next NUESA match that hasn't started and post two free challenges on the open board."""
    import random

    from app.engines.scoring.rules import CAPTAIN, KEY, NONE, VICE_CAPTAIN
    from app.engines.scoring.teams import Pick, SquadAthlete, validate_team

    upcoming = [m for m in ok(client.get("/matches")) if not m["locked"]]
    if not upcoming:
        print("no NUESA match still to come: no test challenges posted", file=sys.stderr)
        return
    m = upcoming[0]
    detail = ok(client.get(f"/matches/{m['id']}"))
    squad = [SquadAthlete(a["id"], side, a["position"]) for side in ("home", "away") for a in detail["squads"][side]]
    size = 11 if m["sport"] == "football" else 8
    rng = random.Random(7)
    for fan in ("fan_a", "fan_b"):
        auth = {"Authorization": f"Bearer {tok(users[fan])}"}
        for _ in range(20000):
            chosen = rng.sample(squad, size)
            roles = [CAPTAIN, VICE_CAPTAIN, KEY] + [NONE] * (size - 3)
            picks = [Pick(a.athlete_id, r) for a, r in zip(chosen, roles)]
            if not validate_team(m["sport"], picks, squad):
                break
        else:
            sys.exit(f"couldn't build a valid test team for {m['home_team']['name']} v {m['away_team']['name']}")
        team = ok(client.post(f"/matches/{m['id']}/teams", headers=auth,
                              json={"picks": [{"athlete_id": p.athlete_id, "role": p.role} for p in picks]}))
        for _ in range(2):
            ok(client.post("/bets", headers=auth, json={"match_id": m["id"], "fantasy_team_id": team["id"]}))
    print(f"test challenges: 4 free challenges on {m['home_team']['name']} v {m['away_team']['name']}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
