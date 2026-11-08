"""Deposits and withdrawals on top of the providers and the wallet.

Money only moves on proof: a deposit is credited after a server-side verify agrees on the amount
(never on the webhook body alone), exactly once (deposits.credited_at). A withdrawal holds the cash
first, then transfers; a failed transfer returns the cash.
"""
import uuid

from app import wallet
from app.audit import audit
from app.config import settings
from app.errors import ApiError
from app.payments import ProviderError, configured, get
from app.referrals import maybe_reward


def new_reference(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def start_deposit(conn, user: dict, amount: int, email: str | None, now) -> dict:
    providers = configured()
    if not providers:
        raise ApiError(503, "payments_unavailable", "payments aren't set up yet")
    ref = new_reference("cxd")
    errors = []
    for p in providers:
        try:
            checkout = p.init_deposit(ref, amount, email or f"{user['id']}@players.campusxi.app",
                                      f"{settings.public_app_url}/#/wallet/deposit/{ref}",
                                      bank_transfer_only=not settings.kyc_required)
        except ProviderError as e:
            errors.append(str(e))
            continue
        row = conn.execute(
            """insert into deposits (user_id, amount_kobo, psp, psp_reference, provider, checkout_url, created_at,
                                   updated_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s) returning id, amount_kobo, psp_reference as reference, provider,
               checkout_url, status""", (user["id"], amount, p.name, ref, p.name, checkout.url, now, now)).fetchone()
        audit(conn, user["id"], "deposit.start", "deposit", row["id"], amount_kobo=amount, provider=p.name)
        return row
    raise ApiError(502, "payments_down", "we couldn't reach the payment providers; try again shortly", errors)


def settle_deposit(conn, reference: str, now) -> dict:
    """Verify with the provider and credit once. Safe to call from a webhook, a poll or the job."""
    d = conn.execute("select * from deposits where psp_reference = %s for update", (reference,)).fetchone()
    if d is None:
        raise ApiError(404, "deposit_not_found", "deposit not found")
    if d["status"] != "pending":
        return d
    try:
        payment = get(d["provider"]).verify(reference)
    except ProviderError:
        return d                                          # try again later (poll or reconciliation job)
    if payment.status == "success" and payment.amount_kobo == d["amount_kobo"]:
        wallet.credit_deposit(conn, d["user_id"], d["amount_kobo"], d["provider"], d["id"])
        d = conn.execute("""update deposits set status = 'success', credited_at = %s, channel = %s, fee_kobo = %s,
                            payer_name = %s, payer_bank = %s, payer_account_tail = %s,
                            updated_at = %s where id = %s returning *""",
                         (now, payment.channel, payment.fee_kobo, (payment.payer_name or "").strip() or None,
                          payment.payer_bank, account_tail(payment.payer_account), now, d["id"])).fetchone()
        audit(conn, None, "deposit.credit", "deposit", d["id"], amount_kobo=d["amount_kobo"])
        name_from_bank(conn, d["user_id"], d["payer_name"], d["id"])
        maybe_reward(conn, d["user_id"], now)
    elif payment.status in ("failed", "reversed") or (payment.status == "success"
                                                      and payment.amount_kobo != d["amount_kobo"]):
        d = conn.execute("update deposits set status = 'failed', updated_at = %s where id = %s returning *",
                         (now, d["id"])).fetchone()
        audit(conn, None, "deposit.fail", "deposit", d["id"], provider_amount=payment.amount_kobo)
    return d


def name_matches(account_name: str, kyc_name: str | None) -> bool:
    """Bank names are often "SURNAME FIRST MIDDLE": two shared words (or one, for one-word names) is enough."""
    if not kyc_name:
        return False
    a = {w for w in account_name.upper().replace(",", " ").split() if len(w) > 1}
    b = {w for w in kyc_name.upper().replace(",", " ").split() if len(w) > 1}
    return len(a & b) >= min(2, len(b))


def account_tail(account: str | None) -> str | None:
    """Last four digits of an account number, masked ("XXXXXX6789") or not."""
    digits = "".join(ch for ch in (account or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


def _words(s: str | None) -> set:
    return {w for w in (s or "").upper().replace(",", " ").replace(".", " ").split()
            if len(w) > 1 and w not in ("BANK", "PLC", "LIMITED", "LTD", "NIGERIA", "MFB", "OF", "THE")}


def funding_deposit(conn, user_id, account_number: str, account_name: str, bank_name: str | None = None) -> dict | None:
    """The newest successful deposit this bank account paid in: same last four digits and holder name.
    Some payers (OPay and other fintechs) arrive with no account number at all; those match on holder
    name + bank instead, marked weak_match so a person approves every withdrawal to that account."""
    rows = conn.execute("""select * from deposits where user_id = %s and status = 'success' and payer_name is not null
                           order by created_at desc""", (user_id,)).fetchall()
    tail = account_tail(account_number)
    exact = next((d for d in rows if d["payer_account_tail"] == tail and name_matches(account_name, d["payer_name"])), None)
    if exact:
        return exact
    weak = next((d for d in rows if d["payer_account_tail"] is None and name_matches(account_name, d["payer_name"])
                 and same_bank(d["payer_bank"], bank_name)), None)
    return {**weak, "weak_match": True} if weak else None


def same_bank(a: str | None, b: str | None) -> bool:
    """Loose: provider bank names differ ("GTBank" vs "Guaranty Trust Bank"); unknown counts as a mismatch."""
    wa, wb = _words(a), _words(b)
    return bool(wa & wb) or bool(a and b and (a.upper() in b.upper() or b.upper() in a.upper()))


def name_from_bank(conn, user_id, payer_name: str | None, deposit_id) -> None:
    """Ellie, Nov 2026: players don't type their bank name. The name the payment provider reports on
    their first bank-transfer deposit becomes it, locked; only an admin can correct it."""
    name = " ".join((payer_name or "").split())
    if not name:
        return
    row = conn.execute("update users set legal_name = %s where id = %s and legal_name is null returning id",
                       (name, user_id)).fetchone()
    if row:
        audit(conn, None, "user.legal_name_from_bank", "user", user_id, deposit_id=str(deposit_id))


def holder_name(conn, user: dict) -> tuple:
    """(name a bank account must be in, where it comes from). Verified ID wins; without KYC, the
    full name the player gave on their profile."""
    kyc = conn.execute("""select verified_name from kyc_records where user_id = %s and status = 'verified'
                          order by created_at desc limit 1""", (user["id"],)).fetchone()
    if user["kyc_status"] == "verified" and kyc:
        return kyc["verified_name"], "ID"
    if settings.kyc_required:
        raise ApiError(403, "kyc_required", "verify your ID before adding a bank account")
    if not user.get("legal_name"):
        raise ApiError(403, "legal_name_required", "your bank name comes from your first deposit by bank "
                                                   "transfer: add money first")
    return user["legal_name"], "bank name on CampusXI"


def add_bank_account(conn, user: dict, bank_code: str, account_number: str) -> dict:
    expected, source = holder_name(conn, user)
    name, bank_name, errors = None, bank_code, []
    for p in configured():
        try:
            name = p.resolve_account(bank_code, account_number)
            bank_name = next((b["name"] for b in p.banks() if b["code"] == bank_code), bank_code)
            break
        except ProviderError as e:
            errors.append(str(e))
    if name is None:
        raise ApiError(422, "account_not_found", "we couldn't find that account; check the number and bank", errors)
    if not name_matches(name, expected):
        raise ApiError(422, "name_mismatch", f"the account is in the name {name}, which doesn't match your {source}")
    if not settings.kyc_required and funding_deposit(conn, user["id"], account_number, name, bank_name) is None:
        raise ApiError(422, "not_funding_account", "withdrawals only go back to an account you've paid in from: "
                                                   "deposit from this account by bank transfer first")
    row = conn.execute(
        """insert into bank_accounts (user_id, bank_code, bank_name, account_number, account_name)
           values (%s, %s, %s, %s, %s) on conflict (user_id, bank_code, account_number)
           do update set account_name = excluded.account_name returning *""",
        (user["id"], bank_code, bank_name, account_number, name)).fetchone()
    audit(conn, user["id"], "bank_account.add", "bank_account", row["id"], bank_code=bank_code,
          last4=account_number[-4:])
    return row


def request_withdrawal(conn, user: dict, amount: int, bank_account_id, now) -> dict:
    from app.gate import require_not_frozen
    require_not_frozen(user)
    if settings.kyc_required and user["kyc_status"] != "verified":
        raise ApiError(403, "kyc_required", "verify your ID first")
    if amount < settings.min_withdrawal_kobo:
        raise ApiError(422, "below_minimum", f"the smallest withdrawal is ₦{settings.min_withdrawal_kobo / 100:,.0f}")
    account = conn.execute("select * from bank_accounts where id = %s and user_id = %s",
                           (bank_account_id, user["id"])).fetchone()
    if account is None:
        raise ApiError(404, "bank_account_not_found", "add the bank account first")
    first = not conn.execute("select 1 from withdrawals where user_id = %s and status = 'paid'",
                             (user["id"],)).fetchone()
    approval = first or amount > settings.withdrawal_approval_over_kobo
    if not settings.kyc_required:
        funded = funding_deposit(conn, user["id"], account["account_number"], account["account_name"], account["bank_name"])
        if funded is None:
            raise ApiError(422, "not_funding_account", "withdrawals only go back to an account you've paid in from")
        # An admin compares when the bank names don't line up, or the payer's account number was never reported.
        approval = approval or bool(funded.get("weak_match")) or not same_bank(funded["payer_bank"], account["bank_name"])
    w = conn.execute(
        """insert into withdrawals (user_id, amount_kobo, psp_reference, bank_account_id, status, needs_approval,
                                  created_at, updated_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (user["id"], amount, new_reference("cxw"), account["id"], "awaiting_approval" if approval else "pending",
         approval, now, now)).fetchone()
    wallet.hold_withdrawal(conn, user["id"], amount, w["id"], now)
    audit(conn, user["id"], "withdrawal.request", "withdrawal", w["id"], amount_kobo=amount, needs_approval=approval)
    if not approval:
        w = send_withdrawal(conn, w, now)
    return w


def send_withdrawal(conn, w: dict, now) -> dict:
    account = conn.execute("select * from bank_accounts where id = %s", (w["bank_account_id"],)).fetchone()
    errors = []
    for p in configured():
        try:
            t = p.transfer(w["psp_reference"], w["amount_kobo"], account)
        except ProviderError as e:
            errors.append(str(e))
            continue
        if p.name == "paystack" and t.provider_ref:
            conn.execute("""update bank_accounts set recipient_codes = recipient_codes || jsonb_build_object(%s::text, %s::text)
                            where id = %s""", (p.name, t.provider_ref, account["id"]))
        w = conn.execute("update withdrawals set status = 'pending', provider = %s, updated_at = %s where id = %s "
                         "returning *", (p.name, now, w["id"])).fetchone()
        if t.status == "success":
            return finish_withdrawal(conn, w, "success", now)
        if t.status == "failed":
            return finish_withdrawal(conn, w, "failed", now, "the bank transfer failed")
        return w
    return finish_withdrawal(conn, w, "failed", now, "; ".join(errors) or "no payment provider available")


def finish_withdrawal(conn, w: dict, outcome: str, now, reason: str | None = None) -> dict:
    """Transfer succeeded (money leaves for the provider) or failed (the cash comes back)."""
    if w["status"] in ("paid", "reversed", "failed", "rejected"):
        return w
    h = wallet.open_hold(conn, "withdrawal", w["id"])
    if outcome == "success":
        wallet.complete_withdrawal(conn, h, w["provider"], now)
        status = "paid"
    else:
        wallet.release(conn, h, now, "withdrawal_reversal")
        status = "reversed" if w["status"] == "pending" and w["provider"] else "failed"
    w = conn.execute("""update withdrawals set status = %s, failure_reason = %s, updated_at = %s where id = %s
                        returning *""", (status, reason, now, w["id"])).fetchone()
    audit(conn, None, f"withdrawal.{status}", "withdrawal", w["id"], reason=reason)
    return w


def _admins_for(conn, user_id) -> list:
    """Admins of the player's school, and every superadmin."""
    return [r["id"] for r in conn.execute(
        """select a.id from users a, users p where p.id = %s and a.deleted_at is null
           and ('superadmin' = any(a.roles) or ('admin' = any(a.roles) and a.school_id = p.school_id))""",
        (user_id,)).fetchall()]


def freeze(conn, user_id, reason: str, now) -> None:
    conn.execute("update users set money_frozen_at = coalesce(money_frozen_at, %s), money_frozen_reason = %s "
                 "where id = %s", (now, reason, user_id))
    audit(conn, None, "user.money_frozen", "user", user_id, reason=reason)


def reverse_deposit(conn, d: dict, reason: str, now) -> dict:
    """The provider took a credited deposit back (refund or lost chargeback). Take it back out of the
    player's cash; whatever they've already spent or withdrawn is booked to platform:reversal_loss,
    their cash play is frozen, and admins are told."""
    if d["status"] != "success":
        return d
    wallet.lock_user(conn, d["user_id"])
    have = wallet.balances(conn, d["user_id"])[wallet.CASH]
    take = min(max(have, 0), d["amount_kobo"])
    short = d["amount_kobo"] - take
    lines = [(wallet.psp(d["provider"]), d["amount_kobo"], "deposit_reversal")]
    if take:
        lines.append((wallet.acct(d["user_id"], wallet.CASH), -take, "deposit_reversal"))
    if short:
        lines.append((wallet.REVERSAL_LOSS, -short, "deposit_reversal"))
    wallet.post(conn, lines, "deposit", d["id"])
    d = conn.execute("""update deposits set status = 'reversed', reversed_at = %s, reversal_reason = %s,
                        shortfall_kobo = %s, updated_at = %s where id = %s returning *""",
                     (now, reason, short, now, d["id"])).fetchone()
    audit(conn, None, "deposit.reverse", "deposit", d["id"], amount_kobo=d["amount_kobo"], taken_back_kobo=take,
          shortfall_kobo=short, reason=reason)
    naira = f"₦{d['amount_kobo'] / 100:,.0f}"
    player = conn.execute("select team_name from users where id = %s", (d["user_id"],)).fetchone()["team_name"]
    if short:
        freeze(conn, d["user_id"], f"a {naira} deposit was reversed by the bank after it was used", now)
    from app.notify import notify
    notify(conn, [d["user_id"]], "deposit_reversed", d["id"], f"Your {naira} deposit was reversed",
           "Your bank took the payment back, so it's been removed from your wallet."
           + (" Cash play is paused until this is sorted: contact support." if short else ""), "#/wallet", now)
    notify(conn, _admins_for(conn, d["user_id"]), "admin_alert", f"reversal:{d['id']}",
           f"Deposit reversed: {player}, {naira}",
           f"{reason}. Taken back from wallet: ₦{take / 100:,.0f}."
           + (f" Already spent: ₦{short / 100:,.0f} (account frozen)." if short else ""), "#/admin/finance", now)
    return d


def check_reversal(conn, reference: str, now) -> dict | None:
    """A refund webhook: confirm with the provider (never the webhook body alone) before taking money back."""
    d = conn.execute("select * from deposits where psp_reference = %s for update", (reference,)).fetchone()
    if d is None or d["status"] != "success":
        return d
    try:
        payment = get(d["provider"]).verify(reference)
    except ProviderError:
        return d
    if payment.status == "reversed":
        return reverse_deposit(conn, d, "refunded by the payment provider", now)
    return d


def dispute_opened(conn, reference: str, now) -> None:
    """A chargeback was opened on a credited deposit: no money moves yet, but freeze cash play and
    tell admins (respond in the provider's dashboard; a lost dispute arrives as a refund)."""
    d = conn.execute("select * from deposits where psp_reference = %s", (reference,)).fetchone()
    if d is None or d["status"] != "success":
        return
    naira = f"₦{d['amount_kobo'] / 100:,.0f}"
    freeze(conn, d["user_id"], f"a chargeback was opened on a {naira} deposit", now)
    player = conn.execute("select team_name from users where id = %s", (d["user_id"],)).fetchone()["team_name"]
    from app.notify import notify
    notify(conn, _admins_for(conn, d["user_id"]), "admin_alert", f"dispute:{d['id']}",
           f"Chargeback opened: {player}, {naira}",
           "Respond in the Paystack dashboard. The player's cash play is frozen meanwhile.", "#/admin/finance", now)


def handle_webhook(conn, provider_name: str, raw: bytes, headers, now) -> dict:
    p = get(provider_name)
    event = p.parse_webhook(raw, headers)        # PermissionError on a bad signature
    import json
    fresh = conn.execute(
        """insert into payment_events (provider, event_id, event_type, payload) values (%s, %s, %s, %s)
           on conflict (provider, event_id) do nothing returning id""",
        (provider_name, event.event_id, event.kind, json.dumps(json.loads(raw)))).fetchone()
    if not fresh or not event.reference:
        return {"handled": False}
    if event.kind == "charge":
        if conn.execute("select 1 from deposits where psp_reference = %s", (event.reference,)).fetchone():
            settle_deposit(conn, event.reference, now)      # verifies with the provider before crediting
    elif event.kind == "refund":
        check_reversal(conn, event.reference, now)          # verifies with the provider before taking back
    elif event.kind == "dispute" and event.status == "create":
        dispute_opened(conn, event.reference, now)
    elif event.kind == "transfer":
        w = conn.execute("select * from withdrawals where psp_reference = %s for update", (event.reference,)).fetchone()
        if w and w["provider"] == provider_name:
            try:
                confirmed = p.verify_transfer(event.reference).status   # don't trust the body alone
            except ProviderError:
                confirmed = "pending"
            if confirmed in ("success", "failed"):
                finish_withdrawal(conn, w, confirmed, now, None if confirmed == "success" else "the bank transfer failed")
    return {"handled": True}


def reconcile(conn, now, older_than_minutes: int = 10) -> dict:
    """Catch payments whose webhook never arrived."""
    from datetime import timedelta
    cutoff = now - timedelta(minutes=older_than_minutes)
    done = {"deposits": 0, "withdrawals": 0}
    for d in conn.execute("select psp_reference from deposits where status = 'pending' and created_at < %s",
                          (cutoff,)).fetchall():
        if settle_deposit(conn, d["psp_reference"], now)["status"] != "pending":
            done["deposits"] += 1
    for w in conn.execute("""select * from withdrawals where status = 'pending' and provider is not null
                             and updated_at < %s for update""", (cutoff,)).fetchall():
        try:
            t = get(w["provider"]).verify_transfer(w["psp_reference"])
        except ProviderError:
            continue
        if t.status in ("success", "failed"):
            finish_withdrawal(conn, w, t.status, now, None if t.status == "success" else "the bank transfer failed")
            done["withdrawals"] += 1
    return done
