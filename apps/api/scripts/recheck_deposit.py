r"""Re-check a deposit with Paystack and credit the wallet if the money really arrived.

For a deposit the app marked failed (or left pending) although Paystack has the money, e.g. the
7 Nov live deposits where the customer paid the fee and the old amount check rejected them.

PowerShell, from apps/api:
  .\.venv\Scripts\python.exe scripts\recheck_deposit.py cxd_...      (the reference check_deposits.py shows)

It asks for the Paystack secret key (hidden; the live key for live deposits; it is used for this one
check and never saved), asks Paystack about that reference, and shows what Paystack says. Only if
Paystack reports it successful for exactly the deposit's amount does it offer to credit, and only
after you type YES. The credit is the same one the app makes (wallet ledger, payer details, bank
name, referral reward), plus an audit entry saying it came from this script. A deposit already
credited is never credited twice. Uses DATABASE_URL from apps/api/.env.
"""
import getpass
import pathlib
import sys
from datetime import datetime, timezone

API_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(API_DIR / "scripts"))
from connect_supabase import mask_db, read  # noqa: E402

ENV = read(API_DIR / ".env")


def main(argv) -> int:
    if len(argv) != 1 or not argv[0].startswith("cxd_"):
        print(__doc__)
        return 1
    reference = argv[0]
    import psycopg
    from psycopg.rows import dict_row

    from app import wallet
    from app.audit import audit
    from app.payments import ProviderError
    from app.payments.paystack import Paystack
    from app.payments.service import account_tail, name_from_bank
    from app.referrals import maybe_reward

    print(f"Database: {mask_db(ENV.get('DATABASE_URL', ''))}")
    with psycopg.connect(ENV["DATABASE_URL"], row_factory=dict_row, connect_timeout=15) as conn:
        d = conn.execute("""select d.*, u.team_name from deposits d join users u on u.id = d.user_id
                            where d.psp_reference = %s""", (reference,)).fetchone()
        if d is None:
            print(f"No deposit with reference {reference}.")
            return 1
        print(f"Deposit {reference}: N{d['amount_kobo'] // 100:,} for {d['team_name']}, status {d['status']}, "
              f"made {d['created_at']:%d %b %H:%M}")
        if d["status"] not in ("failed", "pending"):
            print("Only a failed or pending deposit can be re-checked. Nothing to do.")
            return 0
        if (d["provider"] or d["psp"]) != "paystack":
            print("This script checks Paystack deposits only.")
            return 1
        key = getpass.getpass("Paystack secret key (hidden, not saved): ").strip()
        if not key.startswith(("sk_live_", "sk_test_")):
            print("That doesn't look like a Paystack secret key (sk_live_... or sk_test_...).")
            return 1
        try:
            payment = Paystack(key).verify(reference)
        except ProviderError as e:
            print(f"Paystack didn't answer: {e}")
            return 1
        print(f"Paystack says: {payment.status}, for N{payment.amount_kobo // 100:,} (fee N{payment.fee_kobo // 100:,}), "
              f"channel {payment.channel or '-'}")
        print(f"   payer: {payment.payer_name or '(no name)'}, {payment.payer_bank or '(no bank)'}, "
              f"account ends {account_tail(payment.payer_account) or '(none)'}")
        if payment.status != "success" or payment.amount_kobo != d["amount_kobo"]:
            print("Not a successful payment for this deposit's amount, so nothing is credited.")
            return 0
        if input(f"Credit N{d['amount_kobo'] // 100:,} to {d['team_name']}'s wallet? Type YES: ").strip() != "YES":
            print("Nothing changed.")
            return 1
        now = datetime.now(timezone.utc)
        with conn.transaction():
            locked = conn.execute("select status from deposits where id = %s for update", (d["id"],)).fetchone()
            if locked["status"] not in ("failed", "pending"):
                print(f"Status changed to {locked['status']} meanwhile; nothing done.")
                return 1
            wallet.credit_deposit(conn, d["user_id"], d["amount_kobo"], "paystack", d["id"])
            conn.execute("""update deposits set status = 'success', credited_at = %s, channel = %s, fee_kobo = %s,
                            payer_name = %s, payer_bank = %s, payer_account_tail = %s, updated_at = %s
                            where id = %s""",
                         (now, payment.channel, payment.fee_kobo, (payment.payer_name or "").strip() or None,
                          payment.payer_bank, account_tail(payment.payer_account), now, d["id"]))
            audit(conn, None, "deposit.credit", "deposit", d["id"], amount_kobo=d["amount_kobo"],
                  via="scripts/recheck_deposit.py", previous_status=locked["status"])
            name_from_bank(conn, d["user_id"], (payment.payer_name or "").strip() or None, d["id"])
            maybe_reward(conn, d["user_id"], now)
        print(f"Done: N{d['amount_kobo'] // 100:,} credited. Check with check_deposits.py and the Wallet page.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
