r"""Connect CampusXI to your Supabase project: save the settings, check them, set up the database.

    Windows: double-click apps/api/connect-supabase.cmd
    PowerShell, from apps/api:  .\.venv\Scripts\python.exe scripts\connect_supabase.py [--check] [--migrate]

It asks for (Supabase dashboard -> Project Settings):
  - Project URL                      (Data API / API: https://<ref>.supabase.co)            public
  - anon / publishable key           (API Keys)                                              public
  - service_role / secret key        (API Keys; used only by the API to delete accounts)      SECRET
  - Database connection string       (Database -> Connection string -> URI, "Session pooler"
                                      for IPv4 networks; put your database password in it)   SECRET
Secrets are typed hidden (or visibly, if you choose) and confirmed as e.g. postgresql://…@….com.

Saved to apps/api/.env (API) and apps/web/.env.local (web app); both are gitignored.
--migrate creates/updates the CampusXI tables in the Supabase database (asks first).
"""
import getpass
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

API_DIR = pathlib.Path(__file__).resolve().parents[1]
API_ENV = API_DIR / ".env"
WEB_ENV = API_DIR.parent / "web" / ".env.local"
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(API_DIR / "scripts"))

from set_payment_keys import mask  # noqa: E402  (same masking as the payment script)

SHOW = False


def secret(prompt: str) -> str:
    return input(prompt) if SHOW else getpass.getpass(prompt)


def read(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def write(path: pathlib.Path, updates: dict, header: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else [header]
    done = set()
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                lines[i] = f"{k}={updates[k]}"
                done.add(k)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask_db(url: str) -> str:
    if not url:
        return "(not set)"
    m = re.match(r"^(postgres(?:ql)?://)([^:@]+)(?::[^@]*)?@([^/]+)", url)
    return f"{m.group(1)}{m.group(2)}:****@{m.group(3)}" if m else mask(url)


def get(url: str, headers: dict) -> tuple:
    req = urllib.request.Request(url, headers={"User-Agent": "campusxi-setup", **headers})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except json.JSONDecodeError:
            return e.code, {}
    except (urllib.error.URLError, TimeoutError) as e:
        return None, {"message": str(e)}


def check(api: dict, web: dict) -> bool:
    ok = True
    url = api.get("SUPABASE_URL", "")
    print("\nChecking (read-only):")
    if not url:
        print("  Project URL            not set")
        return False
    status, body = get(f"{url}/auth/v1/.well-known/jwks.json", {})
    keys = len(body.get("keys", [])) if status == 200 else 0
    print(f"  Project URL            {url}: {'OK' if status == 200 else f'FAILED ({status})'}"
          + (f", {keys} signing key(s)" if status == 200 else ""))
    ok &= status == 200
    if status == 200 and keys == 0:
        print("    No asymmetric signing keys: this project still signs with the legacy JWT secret.\n"
              "    Either switch to JWT Signing Keys (Settings -> JWT Keys) or set SUPABASE_JWT_SECRET in apps/api/.env.")
    anon = web.get("VITE_SUPABASE_ANON_KEY", "")
    if anon:
        status, body = get(f"{url}/auth/v1/settings", {"apikey": anon})
        email_on = body.get("external", {}).get("email") if status == 200 else None
        result = "OK" if status == 200 else f"FAILED ({body.get('message', status)})"
        email = "" if status != 200 else f", email sign-in {'on' if email_on else 'OFF (turn on in Authentication -> Providers)'}"
        print(f"  anon key               {mask(anon)}: {result}{email}")
        ok &= status == 200
    else:
        print("  anon key               not set")
        ok = False
    service = api.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if service:
        status, _ = get(f"{url}/auth/v1/admin/users?per_page=1", {"apikey": service, "Authorization": f"Bearer {service}"})
        print(f"  service key            {mask(service)}: {'OK' if status == 200 else f'FAILED ({status})'}")
        ok &= status == 200
    else:
        print("  service key            not set (needed only for deleting accounts)")
    db = api.get("DATABASE_URL", "")
    if db:
        try:
            import psycopg
            with psycopg.connect(db, connect_timeout=10) as conn:
                version = conn.execute("show server_version").fetchone()[0]
                tables = conn.execute("""select count(*) from information_schema.tables
                                         where table_schema = 'public' and table_name in ('users', 'matches', 'wallet_ledger')""").fetchone()[0]
            print(f"  Database               {mask_db(db)}: OK (Postgres {version}), "
                  + ("CampusXI tables present" if tables == 3 else "no CampusXI tables yet: run with --migrate"))
        except Exception as e:  # noqa: BLE001
            print(f"  Database               {mask_db(db)}: FAILED ({type(e).__name__}: {str(e).splitlines()[0][:120]})")
            ok = False
    else:
        print("  Database               not set")
        ok = False
    return ok


def migrate(db: str) -> None:
    from dev_seed import migrate as run
    if input("\nCreate/update the CampusXI tables in the Supabase database now? Type YES: ").strip() != "YES":
        print("Skipped.")
        return
    run(db)
    print("Database is up to date.")


def main() -> int:
    global SHOW
    api, web = read(API_ENV), read(WEB_ENV)
    if "--check" in sys.argv:
        ok = check(api, web)
        if "--migrate" in sys.argv and api.get("DATABASE_URL"):
            migrate(api["DATABASE_URL"])
        return 0 if ok else 1

    print(f"Saving to {API_ENV} and {WEB_ENV} (both gitignored).")
    SHOW = input("Show secrets while you type? Only if nobody can see your screen (y/N): ").strip().lower() in ("y", "yes")
    print("Paste with Ctrl+V or right-click." + ("" if SHOW else " Hidden fields show nothing as you paste: that's normal.")
          + " Press Enter to keep what's saved.\n")
    api_up, web_up = {}, {}

    url = input(f"Project URL [{api.get('SUPABASE_URL') or '(not set)'}]: ").strip().rstrip("/")
    if url:
        if not re.match(r"^https://[a-z0-9-]+\.supabase\.(co|in)$", url):
            print("  That doesn't look like https://<ref>.supabase.co; saved anyway, check it below.")
        api_up["SUPABASE_URL"] = url
        web_up["VITE_SUPABASE_URL"] = url

    anon = input(f"anon / publishable key (public) [{mask(web.get('VITE_SUPABASE_ANON_KEY', ''))}]: ").strip()
    if anon:
        if anon.startswith("sb_secret_") or '"role":"service_role"' in anon:
            print("  That's the SECRET key: it must never go in the web app. Not saved; paste the anon/publishable key.")
        else:
            web_up["VITE_SUPABASE_ANON_KEY"] = anon
            print(f"  Got {mask(anon)} ({len(anon)} characters).")

    service = secret(f"service_role / secret key (SECRET) [{mask(api.get('SUPABASE_SERVICE_ROLE_KEY', ''))}]: ").strip()
    if service:
        api_up["SUPABASE_SERVICE_ROLE_KEY"] = service
        print(f"  Got {mask(service)} ({len(service)} characters).")

    db = secret(f"Database connection string (SECRET) [{mask_db(api.get('DATABASE_URL', ''))}]: ").strip()
    if db:
        if "[YOUR-PASSWORD]" in db:
            print("  Replace [YOUR-PASSWORD] with your database password first. Not saved.")
        elif not db.startswith(("postgresql://", "postgres://")):
            print("  That doesn't look like a postgresql:// connection string. Not saved.")
        else:
            api_up["DATABASE_URL"] = db
            print(f"  Got {mask_db(db)}.")
    web_up.setdefault("VITE_API_URL", web.get("VITE_API_URL", "http://localhost:8000"))

    if api_up:
        write(API_ENV, api_up, "# Local settings for the CampusXI API (gitignored).")
    if web_up:
        write(WEB_ENV, web_up, "# Local settings for the CampusXI web app (gitignored). These values ship to browsers.")
    print(f"\nSaved: {', '.join(sorted(api_up)) or 'nothing'} (API); {', '.join(sorted(web_up)) or 'nothing'} (web).")
    api, web = read(API_ENV), read(WEB_ENV)
    ok = check(api, web)
    if api.get("DATABASE_URL"):
        migrate(api["DATABASE_URL"])
    print("\nRestart the API and the web app to use the new settings.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
