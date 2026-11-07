r"""First-time setup of a CampusXI database: add schools and make the first admin.

PowerShell, from apps/api:
  .\.venv\Scripts\python.exe scripts\bootstrap.py list
  .\.venv\Scripts\python.exe scripts\bootstrap.py add-school "Nile University of Nigeria"
  .\.venv\Scripts\python.exe scripts\bootstrap.py make-admin you@example.com          (school admin)
  .\.venv\Scripts\python.exe scripts\bootstrap.py make-admin you@example.com --super  (all schools)

make-admin needs the person to have signed in to the app once and finished their profile.
Uses DATABASE_URL, SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from apps/api/.env.
"""
import json
import pathlib
import sys
import urllib.request

API_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR / "scripts"))
from connect_supabase import read  # noqa: E402

ENV = read(API_DIR / ".env")


def connect():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(ENV["DATABASE_URL"], row_factory=dict_row, connect_timeout=15)


def auth_user_id(email: str) -> str | None:
    key, url = ENV.get("SUPABASE_SERVICE_ROLE_KEY", ""), ENV.get("SUPABASE_URL", "")
    page = 1
    while True:
        req = urllib.request.Request(f"{url}/auth/v1/admin/users?page={page}&per_page=200",
                                     headers={"apikey": key, "Authorization": f"Bearer {key}",
                                              "User-Agent": "campusxi-setup"})
        with urllib.request.urlopen(req, timeout=20) as res:
            users = json.loads(res.read()).get("users", [])
        for u in users:
            if (u.get("email") or "").lower() == email.lower():
                return u["id"]
        if len(users) < 200:
            return None
        page += 1


def main(argv) -> int:
    if not argv or argv[0] not in ("list", "add-school", "make-admin"):
        print(__doc__)
        return 1
    with connect() as conn:
        if argv[0] == "list":
            schools = conn.execute("select id, name from schools order by name").fetchall()
            print("Schools:", ", ".join(s["name"] for s in schools) or "(none yet)")
            admins = conn.execute("""select team_name, roles from users where roles && array['admin', 'superadmin']
                                     and deleted_at is null order by team_name""").fetchall()
            print("Admins: ", ", ".join(f"{a['team_name']} ({'/'.join(r for r in a['roles'] if r != 'player')})"
                                       for a in admins) or "(none yet)")
            return 0
        if argv[0] == "add-school":
            name = " ".join(argv[1:]).strip()
            if len(name) < 3:
                print("Give the school's full name, e.g. add-school \"Nile University of Nigeria\"")
                return 1
            if conn.execute("select 1 from schools where lower(name) = lower(%s)", (name,)).fetchone():
                print(f"{name} is already there.")
                return 0
            conn.execute("insert into schools (name) values (%s)", (name,))
            conn.commit()
            print(f"Added {name}. Players can choose it when they create their profile.")
            return 0
        email = argv[1] if len(argv) > 1 else ""
        uid = auth_user_id(email) if "@" in email else None
        if uid is None:
            print(f"No sign-in found for {email!r}: sign in to the app once with that email first.")
            return 1
        user = conn.execute("select id, team_name, roles from users where id = %s and deleted_at is null",
                            (uid,)).fetchone()
        if user is None:
            print(f"{email} has signed in but hasn't finished their profile yet: do that in the app first.")
            return 1
        role = "superadmin" if "--super" in argv else "admin"
        roles = sorted(set(user["roles"]) | {"player", "admin", role})
        conn.execute("update users set roles = %s where id = %s", (roles, uid))
        conn.execute("insert into audit_log (actor_id, action, target_type, target_id, details) "
                     "values (null, 'user.bootstrap_admin', 'user', %s, %s)", (uid, json.dumps({"roles": roles})))
        conn.commit()
        print(f"{user['team_name']} ({email}) is now: {', '.join(r for r in roles if r != 'player')}.")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
