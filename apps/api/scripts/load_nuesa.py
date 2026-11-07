r"""Load the real NUESA tournament (football + basketball) from the repo's data/ folder into the database
in apps/api/.env (production), through the same admin import the app uses.

    Windows: double-click apps/api/load-nuesa.cmd
    PowerShell, from apps/api:  .\.venv\Scripts\python.exe scripts\load_nuesa.py
    Testing against another database:  ... scripts\load_nuesa.py --database-url postgresql://...

Before running it:
  1. connect-supabase.cmd --check --migrate      (tables up to date)
  2. bootstrap.py add-school "Nile University of Nigeria"
  3. sign in on the app once, then bootstrap.py make-admin <your email> --super

It loads nuesa_{football,basketball}_{squads,fixtures,results,result_stats}.csv (squads carry jersey
colours and captains) as two published tournaments at Nile University, acting as that admin. It asks
before writing, and refuses if the NUESA tournaments are already there.
"""
import os
import pathlib
import secrets
import sys
from datetime import datetime, timedelta, timezone

API_DIR = pathlib.Path(__file__).resolve().parents[1]
REPO = API_DIR.parents[1]
DATA = REPO / "data"
SCHOOL = "Nile University of Nigeria"
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(API_DIR / "scripts"))

from connect_supabase import mask_db, read  # noqa: E402


def fail(msg: str) -> int:
    print(f"\n{msg}")
    return 1


def main(argv) -> int:
    url = argv[argv.index("--database-url") + 1] if "--database-url" in argv else read(API_DIR / ".env").get("DATABASE_URL")
    if not url:
        return fail("No DATABASE_URL in apps/api/.env: run connect-supabase.cmd first.")
    if not (DATA / "nuesa_football_squads.csv").exists():
        return fail(f"No NUESA files in {DATA}: put the nuesa_*.csv files there first.")
    print(f"Database: {mask_db(url)}")

    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=15) as c:
        files = sorted(p.name.split("_")[0] for p in (REPO / "supabase" / "migrations").glob("*.sql"))
        try:
            done = {r["version"] for r in c.execute("select version from supabase_migrations.schema_migrations")}
        except psycopg.errors.UndefinedTable:
            done = set()
        missing = [v for v in files if v not in done]
        if missing:
            return fail(f"The database is missing {len(missing)} update(s) ({', '.join(missing)}): "
                        "run connect-supabase.cmd --check --migrate first.")
        school = c.execute("select id from schools where name = %s", (SCHOOL,)).fetchone()
        if school is None:
            return fail(f'No school called "{SCHOOL}": run bootstrap.py add-school "{SCHOOL}" first.')
        admin = c.execute(
            """select id, team_name from users where deleted_at is null
               and ('superadmin' = any(roles) or ('admin' = any(roles) and school_id = %s))
               order by 'superadmin' = any(roles) desc, created_at limit 1""", (school["id"],)).fetchone()
        if admin is None:
            return fail("No admin yet: sign in to the app once, then run bootstrap.py make-admin <email> --super.")
        loaded = c.execute("select name from tournaments where school_id = %s and name like 'NUESA %%'",
                           (school["id"],)).fetchall()
        if loaded:
            return fail("Already loaded: " + "; ".join(t["name"] for t in loaded) + ". Nothing was changed.")

    sports = [s for s in ("football", "basketball") if (DATA / f"nuesa_{s}_squads.csv").exists()]
    print(f"Will create {len(sports)} published tournament(s) at {SCHOOL} as {admin['team_name']}: "
          + ", ".join(f"NUESA Sports Tournament 2026/27 ({s.title()})" for s in sports))
    if input("Type YES to load them: ").strip() != "YES":
        print("Skipped.")
        return 0

    # Run the app's own admin import in this process. The token is signed with a throwaway secret that
    # only this process accepts; background jobs and rate limits stay off here.
    os.environ["CAMPUSXI_IGNORE_DOTENV"] = "1"
    import jwt
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app
    from dev_seed import load_nuesa
    settings.database_url = url
    settings.supabase_jwt_secret = secrets.token_urlsafe(32)
    settings.jobs_enabled = False
    settings.rate_limit_enabled = False
    token = jwt.encode({"sub": str(admin["id"]), "aud": settings.jwt_audience,
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
                       settings.supabase_jwt_secret, algorithm="HS256")
    errors = []

    def ok(res):
        if res.status_code >= 300:
            errors.append(res.text)
            raise SystemExit(f"\nImport stopped: {res.status_code} {res.text[:600]}\n"
                             "Fix the CSV row it names and run this again (finished steps are kept).")
        return res.json()

    import logging
    logging.getLogger("campusxi.http").setLevel(logging.WARNING)     # no per-request log lines here
    with TestClient(app) as client:
        load_nuesa(client, ok, {"Authorization": f"Bearer {token}"}, school["id"], DATA)
    print("\nDone: the NUESA tournaments are live in the app (Home, Live Score, Tournament pages).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
