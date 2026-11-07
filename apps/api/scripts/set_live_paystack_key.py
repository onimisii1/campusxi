r"""Put the LIVE Paystack secret key on the live API (Vercel), without it ever touching chat or git.

    Windows: double-click apps/api/set-live-paystack-key.cmd
    PowerShell, from apps/api:  .\.venv\Scripts\python.exe scripts\set_live_paystack_key.py

What it does:
  1. Makes sure this folder is linked to the API's Vercel project (runs `vercel link` if not; you
     pick the project once). You need to be logged in to Vercel (`npx vercel@latest login`).
  2. Asks for the key with hidden typing (paste with Ctrl+V or right-click: nothing shows, that's
     normal), checks it starts with sk_live_ and that Paystack accepts it (read-only balance check).
  3. Saves it as PAYSTACK_SECRET_KEY for Production, marked Sensitive (replacing any old value).
     The key goes to Vercel through standard input, never on the command line.
  4. Tells you to redeploy so the API picks it up.

It does not write the key to apps/api/.env: this computer keeps the test key. Paid play stays
switched off until PAID_PLAY_ENABLED=true is set on purpose.
"""
import getpass
import pathlib
import shutil
import subprocess
import sys

API_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR / "scripts"))
from set_payment_keys import check_paystack, mask  # noqa: E402

NAME = "PAYSTACK_SECRET_KEY"
NPX = shutil.which("npx.cmd") or shutil.which("npx") or "npx"


def vercel(*args, input_text: str | None = None, interactive: bool = False) -> subprocess.CompletedProcess:
    cmd = [NPX, "--yes", "vercel@latest", *args]
    if interactive:
        return subprocess.run(cmd, cwd=API_DIR)
    return subprocess.run(cmd, cwd=API_DIR, input=input_text, capture_output=True, text=True)


def main() -> int:
    if not (API_DIR / ".vercel" / "project.json").exists():
        print("This folder isn't linked to the API's Vercel project yet. Linking now:")
        print("pick your team, say yes to linking an EXISTING project, and choose the API project.\n")
        if vercel("link", interactive=True).returncode != 0 or not (API_DIR / ".vercel" / "project.json").exists():
            print("\nNot linked. Log in first with:  npx vercel@latest login   then run this again.")
            return 1
    else:
        print("Linked to the API's Vercel project (apps/api/.vercel).")

    print("\nPaste the LIVE Paystack secret key (sk_live_...). Typing is hidden: nothing shows, that's normal.")
    key = getpass.getpass("Live secret key: ").strip()
    if not key:
        print("Nothing entered. Nothing was changed.")
        return 1
    if key.startswith("sk_test_"):
        print("That's a TEST key (sk_test_). This script is only for the live key. Nothing was changed.")
        return 1
    if key.startswith("pk_"):
        print("That's the PUBLIC key (pk_). Use the SECRET key (sk_live_). Nothing was changed.")
        return 1
    if not key.startswith("sk_live_"):
        print("A live secret key starts with sk_live_. Nothing was changed.")
        return 1
    print(f"Got {mask(key)} ({len(key)} characters). Checking with Paystack...")
    result = check_paystack(key)
    if result != "OK":
        print(f"Paystack didn't accept it: {result}. Nothing was changed.")
        return 1
    print("Paystack accepted the key.")

    if input(f"\nSave it on Vercel as {NAME} (Production, Sensitive), replacing any old value? Type LIVE: ").strip() != "LIVE":
        print("Skipped. Nothing was changed.")
        return 0
    vercel("env", "rm", NAME, "production", "--yes")          # fine if there was none
    res = vercel("env", "add", NAME, "production", "--sensitive", input_text=key + "\n")
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip().splitlines()
        detail = [line for line in detail if key not in line]   # never echo the key
        print("Vercel refused:", " ".join(detail[-3:]) or res.returncode)
        return 1
    print(f"\nSaved {NAME} on the live API (Production, Sensitive).")
    print("Next: redeploy the API so it uses the key (Vercel dashboard -> API project -> Deployments ->")
    print("the latest one -> Redeploy, or ask the integrations session). Paid play stays off until")
    print("PAID_PLAY_ENABLED=true is set on purpose.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
