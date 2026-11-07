r"""Show the latest deposits and what the payment provider said about the payer (read-only).

PowerShell, from apps/api:
  .\.venv\Scripts\python.exe scripts\check_deposits.py          last 5 deposits
  .\.venv\Scripts\python.exe scripts\check_deposits.py 20       last 20

For each deposit: when, amount, status, channel, and the payer name / bank / last 4 digits the
withdrawal rule matches against. Also lists which fields the provider's webhook carried under
"authorization" (names only, never values), so we can see what a live bank transfer really sends.
Uses DATABASE_URL from apps/api/.env. Changes nothing.
"""
import pathlib
import sys

API_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR / "scripts"))
from connect_supabase import mask_db, read  # noqa: E402

ENV = read(API_DIR / ".env")


def main(argv) -> int:
    import psycopg
    from psycopg.rows import dict_row
    limit = int(argv[0]) if argv and argv[0].isdigit() else 5
    print(f"Database: {mask_db(ENV.get('DATABASE_URL', ''))}  (read-only)\n")
    with psycopg.connect(ENV["DATABASE_URL"], row_factory=dict_row, connect_timeout=15) as conn:
        conn.read_only = True
        rows = conn.execute("""select d.created_at, d.amount_kobo, d.status, coalesce(d.provider, d.psp) as psp, d.channel, d.payer_name,
                                      d.payer_bank, d.payer_account_tail, d.webhook_payload, u.team_name, u.legal_name
                               from deposits d join users u on u.id = d.user_id
                               order by d.created_at desc limit %s""", (limit,)).fetchall()
    if not rows:
        print("No deposits yet.")
        return 0
    for r in rows:
        payload = r["webhook_payload"] or {}
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        auth = data.get("authorization") if isinstance(data, dict) else None
        print(f"{r['created_at']:%d %b %H:%M}  N{r['amount_kobo'] // 100:,}  {r['status']}  {r['psp']}/{r['channel'] or '-'}"
              f"  player: {r['team_name']}")
        print(f"   payer name: {r['payer_name'] or '(none)'}   bank: {r['payer_bank'] or '(none)'}"
              f"   account ends: {r['payer_account_tail'] or '(none)'}")
        print(f"   player's saved legal name: {r['legal_name'] or '(none)'}")
        if isinstance(auth, dict):
            print(f"   webhook authorization fields: {', '.join(sorted(auth)) or '(empty)'}")
        else:
            print("   webhook: none stored (confirmed by verify/reconcile instead)")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
