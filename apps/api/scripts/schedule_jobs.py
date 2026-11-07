r"""Run CampusXI's background jobs on Vercel: Supabase Cron calls the API on each job's schedule.

On Vercel the API only runs while a request is in flight, so its job thread can't run. This sets up
Supabase Cron (pg_cron + pg_net, both free) in the database from apps/api/.env to call
    POST https://<api>/jobs/run/<job>    Authorization: Bearer <CRON_SECRET>
for every job in app/jobs.py, on that job's interval (refunds every minute, payouts every 5, ...).
The secret is kept in Supabase Vault; the same value goes in Vercel as CRON_SECRET.

PowerShell, from apps/api (or double-click schedule-jobs.cmd):
  .\.venv\Scripts\python.exe scripts\schedule_jobs.py https://campusxi-api.vercel.app   set up / update
  .\.venv\Scripts\python.exe scripts\schedule_jobs.py --status    the schedule and the last calls (read-only)
  .\.venv\Scripts\python.exe scripts\schedule_jobs.py --test      call one job now, as the scheduler would
  .\.venv\Scripts\python.exe scripts\schedule_jobs.py --show-secret   print the saved secret again
  .\.venv\Scripts\python.exe scripts\schedule_jobs.py --new-secret https://...   replace the secret
  .\.venv\Scripts\python.exe scripts\schedule_jobs.py --off       stop all scheduled calls
"""
import json
import pathlib
import re
import secrets
import sys
import urllib.error
import urllib.request

API_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(API_DIR / "scripts"))
from connect_supabase import mask_db, read  # noqa: E402

ENV = read(API_DIR / ".env")
PREFIX = "campusxi_"
SECRET_NAME = "campusxi_cron_secret"
URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?$")


def connect():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(ENV["DATABASE_URL"], row_factory=dict_row, connect_timeout=15)


def cron_expr(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "0 * * * *" if hours == 1 else f"0 */{hours} * * *"
    minutes = max(1, seconds // 60)
    return "* * * * *" if minutes == 1 else f"*/{minutes} * * * *"


def job_list():
    from app.jobs import JOBS
    return [(j.name, cron_expr(j.every_seconds)) for j in JOBS]


def saved_secret(conn) -> str | None:
    row = conn.execute("select decrypted_secret from vault.decrypted_secrets where name = %s",
                       (SECRET_NAME,)).fetchone()
    return row["decrypted_secret"] if row else None


def call_job(api_url: str, secret: str, name: str) -> tuple:
    req = urllib.request.Request(f"{api_url}/jobs/run/{name}", data=b"{}", method="POST",
                                 headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json",
                                          "User-Agent": "campusxi-setup"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.status, res.read().decode()[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except (urllib.error.URLError, TimeoutError) as e:
        return None, str(e)


def scheduled_url(conn) -> str | None:
    row = conn.execute("select command from cron.job where jobname = %s", (PREFIX + "refund_at_lock",)).fetchone()
    m = re.search(r"url := '(https://[^/']+)/jobs/run/", row["command"]) if row else None
    return m.group(1) if m else None


def status(conn) -> int:
    has_cron = conn.execute("select 1 from pg_extension where extname = 'pg_cron'").fetchone()
    if not has_cron:
        print("Supabase Cron isn't set up yet: run this script with the API's address.")
        return 1
    jobs = conn.execute("select jobname, schedule, active from cron.job where jobname like %s order by jobname",
                        (PREFIX + "%",)).fetchall()
    print("Scheduled:", "(nothing)" if not jobs else "")
    for j in jobs:
        print(f"  {j['jobname'][len(PREFIX):]:<22} {j['schedule']:<14} {'on' if j['active'] else 'OFF'}")
    print(f"Calls go to: {scheduled_url(conn) or '(not set)'}")
    has_net = conn.execute("select 1 from pg_extension where extname = 'pg_net'").fetchone()
    if has_net:
        rows = conn.execute("""select created, status_code, timed_out, error_msg, left(content, 140) as content
                               from net._http_response order by created desc limit 8""").fetchall()
        print("Last calls (newest first; 200 = ran):")
        for r in rows:
            result = r["status_code"] or ("timed out" if r["timed_out"] else r["error_msg"])
            print(f"  {r['created']:%d %b %H:%M:%S}  {result}  {(r['content'] or '').strip()}")
        if not rows:
            print("  (none yet)")
    return 0


def setup(conn, api_url: str, new_secret: bool) -> int:
    jobs = job_list()
    print(f"Database: {mask_db(ENV['DATABASE_URL'])}")
    print(f"API:      {api_url}")
    print("Supabase Cron will call these jobs:")
    for name, expr in jobs:
        print(f"  {name:<22} {expr}")
    if input("Type YES to set this up: ").strip() != "YES":
        print("Nothing changed.")
        return 1
    with conn.transaction():
        conn.execute("create extension if not exists pg_cron with schema pg_catalog")
        conn.execute("create extension if not exists pg_net with schema extensions")
        secret = saved_secret(conn)
        created = secret is None or new_secret
        if secret is None:
            secret = secrets.token_urlsafe(32)
            conn.execute("select vault.create_secret(%s, %s, %s)",
                         (secret, SECRET_NAME, "CampusXI: Supabase Cron -> API /jobs/run (CRON_SECRET in Vercel)"))
        elif new_secret:
            secret = secrets.token_urlsafe(32)
            sid = conn.execute("select id from vault.secrets where name = %s", (SECRET_NAME,)).fetchone()["id"]
            conn.execute("select vault.update_secret(%s, %s)", (sid, secret))
        old = conn.execute("select jobname from cron.job where jobname like %s", (PREFIX + "%",)).fetchall()
        for row in old:
            conn.execute("select cron.unschedule(%s)", (row["jobname"],))
        for name, expr in jobs:
            command = (f"select net.http_post(url := '{api_url}/jobs/run/{name}', body := '{{}}'::jsonb, "
                       f"headers := jsonb_build_object('Content-Type', 'application/json', 'Authorization', "
                       f"'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = '{SECRET_NAME}')), "
                       f"timeout_milliseconds := 60000)")
            conn.execute("select cron.schedule(%s, %s, %s)", (PREFIX + name, expr, command))
        # cron keeps a row per run; keep a week of them
        conn.execute("select cron.schedule(%s, %s, %s)", (PREFIX + "cleanup_cron_log", "30 3 * * *",
                     "delete from cron.job_run_details where end_time < now() - interval '7 days'"))
    print(f"\nDone: {len(jobs)} jobs scheduled.")
    if created:
        print("\nPut this in Vercel (API project -> Settings -> Environment Variables) as CRON_SECRET,")
        print("then redeploy the API. It is shown once; --show-secret prints it again.\n")
        print(f"  {secret}\n")
    else:
        print("Kept the existing secret (already in Vercel as CRON_SECRET). --new-secret replaces it.")
    print("Check in a few minutes with --status (200 = the job ran).")
    return 0


def main(argv) -> int:
    if not ENV.get("DATABASE_URL"):
        print("No DATABASE_URL in apps/api/.env: run connect-supabase.cmd first.")
        return 1
    flags = {a for a in argv if a.startswith("--")}
    urls = [a.rstrip("/") for a in argv if not a.startswith("--")]
    with connect() as conn:
        if "--status" in flags:
            return status(conn)
        if "--show-secret" in flags:
            print(saved_secret(conn) or "No secret saved yet: run with the API's address.")
            return 0
        if "--off" in flags:
            if input("Stop all scheduled CampusXI jobs? Type YES: ").strip() != "YES":
                return 1
            with conn.transaction():
                for row in conn.execute("select jobname from cron.job where jobname like %s",
                                        (PREFIX + "%",)).fetchall():
                    conn.execute("select cron.unschedule(%s)", (row["jobname"],))
            print("Stopped. Run with the API's address to start again.")
            return 0
        if "--test" in flags:
            api_url, secret = urls[0] if urls else scheduled_url(conn), saved_secret(conn)
            if not api_url or not secret:
                print("Not set up yet: run with the API's address first.")
                return 1
            code, body = call_job(api_url, secret, "refund_at_lock")
            hint = {401: "  -> CRON_SECRET in Vercel doesn't match: set it (--show-secret) and redeploy.",
                    404: "  -> the API has no /jobs/run route: is Vercel using apps/api/index.py?"}.get(code, "")
            print(f"{api_url}/jobs/run/refund_at_lock -> {code}: {body}\n{hint}".rstrip())
            return 0 if code == 200 else 1
        if len(urls) != 1 or not URL_RE.match(urls[0]):
            print(__doc__)
            print("Give the API's address, e.g. https://campusxi-api.vercel.app (https, no path).")
            return 1
        return setup(conn, urls[0], "--new-secret" in flags)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
