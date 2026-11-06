"""Add or change the payment keys in apps/api/.env, then check they work.

    Windows: double-click apps/api/set-payment-keys.cmd (or run it with --check)
    PowerShell, from apps/api:  .\.venv\Scripts\python.exe scripts\set_payment_keys.py [--check]
    Bash, from apps/api:        .venv/Scripts/python scripts/set_payment_keys.py [--check]

Keys are typed with hidden input and saved only to apps/api/.env (gitignored); they are never
printed in full. Press Enter at any question to keep what's already saved.

Test keys first: Paystack sk_test_..., Flutterwave FLWSECK_TEST-... . Live keys (sk_live_...,
FLWSECK-...) take real money, so the script asks you to type LIVE to confirm them.

Where to find them:
  Paystack:    Dashboard -> Settings -> API Keys & Webhooks -> Secret Key
  Flutterwave: Dashboard -> Settings -> API Keys -> Secret Key;
               Settings -> Webhooks -> Secret hash (any long random text; this script can make one)
Restart the API after changing keys.
"""
import getpass
import json
import os
import pathlib
import re
import secrets
import sys
import urllib.error
import urllib.request

ENV = pathlib.Path(__file__).resolve().parents[1] / ".env"
TEMPLATE = """# Local settings for the CampusXI API. This file is gitignored: it never leaves this computer.
PAYSTACK_SECRET_KEY=
FLUTTERWAVE_SECRET_KEY=
FLUTTERWAVE_WEBHOOK_HASH=
PUBLIC_APP_URL=http://localhost:5180
PAID_PLAY_ENABLED=false
RESULT_BETS_ENABLED=false
JOBS_ENABLED=false
KYC_PROVIDER=stub
KYC_PEPPER=
"""

PATTERNS = {
    "PAYSTACK_SECRET_KEY": (r"^sk_(test|live)_[A-Za-z0-9]{20,}$", "sk_live_"),
    "FLUTTERWAVE_SECRET_KEY": (r"^FLWSECK(_TEST)?-[A-Za-z0-9]{20,}-X$", "FLWSECK-"),
}


# ---------- .env read/write (keeps comments and order) ----------

def read_env() -> dict:
    if not ENV.exists():
        ENV.write_text(TEMPLATE, encoding="utf-8")
    values = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def write_env(updates: dict) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines()
    done = set()
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                lines[i] = f"{k}={updates[k]}"
                done.add(k)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)        # owner-only where the OS supports it
    except OSError:
        pass


def mask(value: str) -> str:
    if not value:
        return "(not set)"
    return f"{value[:8]}...{value[-4:]}" if len(value) > 14 else "****"


# ---------- checks against the providers (read-only calls) ----------

def call(url: str, key: str) -> tuple:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "campusxi-setup"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except json.JSONDecodeError:
            return e.code, {}
    except (urllib.error.URLError, TimeoutError) as e:
        return None, {"message": f"couldn't reach the provider ({e})"}


def check_paystack(key: str) -> str:
    status, body = call("https://api.paystack.co/balance", key)          # needs a valid secret key
    if status == 200 and body.get("status"):
        return "OK"
    return f"FAILED: {body.get('message', status)}"


def check_flutterwave(key: str) -> str:
    status, body = call("https://api.flutterwave.com/v3/balances/NGN", key)
    if status == 200 and body.get("status") == "success":
        return "OK"
    return f"FAILED: {body.get('message', status)}"


def check(values: dict) -> bool:
    ok = True
    print("\nChecking saved keys (read-only calls):")
    for name, fn in (("PAYSTACK_SECRET_KEY", check_paystack), ("FLUTTERWAVE_SECRET_KEY", check_flutterwave)):
        key = values.get(name, "")
        if not key:
            print(f"  {name:26} not set")
            continue
        result = fn(key)
        mode = "LIVE" if PATTERNS[name][1] in key else "test"
        print(f"  {name:26} {mask(key)} ({mode}): {result}")
        ok = ok and result == "OK"
    if values.get("FLUTTERWAVE_SECRET_KEY") and not values.get("FLUTTERWAVE_WEBHOOK_HASH"):
        print("  FLUTTERWAVE_WEBHOOK_HASH   not set: Flutterwave webhooks will be rejected")
    if not (values.get("PAYSTACK_SECRET_KEY") or values.get("FLUTTERWAVE_SECRET_KEY")):
        print("  No payment provider set: deposits will say payments aren't set up yet.")
    return ok


# ---------- questions ----------

def ask_key(name: str, current: str, label: str) -> str | None:
    pattern, live_prefix = PATTERNS[name]
    while True:
        value = getpass.getpass(f"{label} [{mask(current)}] (Enter to keep, '-' to clear): ").strip()
        if value == "":
            return None
        if value == "-":
            return ""
        if not re.match(pattern, value):
            print("  That doesn't look like a secret key (check you copied the SECRET key, not the public one).")
            continue
        if live_prefix in value and input("  This is a LIVE key: real money. Type LIVE to use it: ").strip() != "LIVE":
            print("  Not saved.")
            continue
        return value


def ask_yes(question: str, current: str) -> str | None:
    now = current.lower() == "true"
    answer = input(f"{question} [{'yes' if now else 'no'}] (y/n, Enter to keep): ").strip().lower()
    if answer in ("y", "yes"):
        return "true"
    if answer in ("n", "no"):
        return "false"
    return None


def main() -> int:
    values = read_env()
    if "--check" in sys.argv:
        return 0 if check(values) else 1

    print(f"Saving to {ENV} (gitignored; never committed). Input is hidden.\n")
    updates = {}
    for name, label in (("PAYSTACK_SECRET_KEY", "Paystack secret key"),
                        ("FLUTTERWAVE_SECRET_KEY", "Flutterwave secret key (fallback)")):
        v = ask_key(name, values.get(name, ""), label)
        if v is not None:
            updates[name] = v

    if updates.get("FLUTTERWAVE_SECRET_KEY", values.get("FLUTTERWAVE_SECRET_KEY")):
        current = values.get("FLUTTERWAVE_WEBHOOK_HASH", "")
        v = getpass.getpass(f"Flutterwave webhook secret hash [{mask(current)}] "
                            "(Enter to keep, 'new' to generate one): ").strip()
        if v.lower() == "new" or (not v and not current):
            v = secrets.token_urlsafe(32)
            print(f"  Generated. Paste this into Flutterwave -> Settings -> Webhooks -> Secret hash:\n  {v}")
        if v:
            updates["FLUTTERWAVE_WEBHOOK_HASH"] = v

    url = input(f"Web app address players return to [{values.get('PUBLIC_APP_URL', 'http://localhost:5180')}]: ").strip()
    if url:
        updates["PUBLIC_APP_URL"] = url.rstrip("/")
    for name, question in (("PAID_PLAY_ENABLED", "Turn paid play on?"),
                           ("RESULT_BETS_ENABLED", "Turn Home/Away result bets on? (needs the sports-betting licence)")):
        v = ask_yes(question, values.get(name, "false"))
        if v is not None:
            updates[name] = v
    if not values.get("KYC_PEPPER"):
        updates["KYC_PEPPER"] = secrets.token_urlsafe(48)       # stable secret for hashing NIN/BVN

    if updates:
        write_env(updates)
        print(f"\nSaved {len(updates)} setting(s): {', '.join(sorted(updates))}.")
    else:
        print("\nNothing changed.")
    values = read_env()
    ok = check(values)
    print("\nRestart the API to use the new settings."
          + ("" if ok else "\nSome checks failed: fix the key and run this again."))
    if values.get("PAYSTACK_SECRET_KEY") or values.get("FLUTTERWAVE_SECRET_KEY"):
        print("Webhook URLs to set in the dashboards (once the API has a public address):\n"
              "  Paystack:    https://<your-api>/payments/paystack/webhook\n"
              "  Flutterwave: https://<your-api>/payments/flutterwave/webhook\n"
              "Locally, checkout still works without webhooks: the app confirms each payment with the provider.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
