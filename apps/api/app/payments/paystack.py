"""Paystack (https://paystack.com/docs/api). Amounts are kobo; webhooks are signed with
HMAC-SHA512 of the raw body using the secret key (x-paystack-signature)."""
import hashlib
import hmac
import json

import httpx

from app.payments import Checkout, Payment, ProviderError, Transfer, WebhookEvent, http


class Paystack:
    name = "paystack"

    def __init__(self, secret: str):
        self.secret = secret
        self.client = http("https://api.paystack.co", secret)

    def _call(self, method: str, path: str, **kw) -> dict:
        try:
            res = self.client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ProviderError(f"paystack unreachable: {e}") from e
        body = res.json() if res.content else {}
        if res.status_code >= 400 or not body.get("status"):
            raise ProviderError(f"paystack {path}: {body.get('message', res.status_code)}")
        return body["data"]

    def init_deposit(self, reference: str, amount_kobo: int, email: str, callback_url: str,
                     bank_transfer_only: bool = False) -> Checkout:
        channels = ["bank_transfer"] if bank_transfer_only else ["card", "bank", "ussd", "bank_transfer"]
        data = self._call("POST", "/transaction/initialize", json={
            "reference": reference, "amount": amount_kobo, "email": email, "currency": "NGN",
            "callback_url": callback_url, "channels": channels})
        return Checkout(self.name, reference, data["authorization_url"])

    def verify(self, reference: str) -> Payment:
        data = self._call("GET", f"/transaction/verify/{reference}")
        status = {"success": "success", "failed": "failed", "abandoned": "failed", "reversed": "failed"}.get(
            data.get("status"), "pending")
        auth = data.get("authorization") or {}       # Pay with Transfer: sender_name / sender_bank / sender_bank_account_number
        return Payment(status, int(data.get("amount") or 0), data.get("channel"), int(data.get("fees") or 0),
                       auth.get("sender_name") or auth.get("account_name"), auth.get("sender_bank"),
                       auth.get("sender_bank_account_number"))

    def parse_webhook(self, raw: bytes, headers) -> WebhookEvent:
        expected = hmac.new(self.secret.encode(), raw, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(expected, headers.get("x-paystack-signature", "")):
            raise PermissionError("bad paystack signature")
        body = json.loads(raw)
        event, data = body.get("event", ""), body.get("data") or {}
        kind = "charge" if event.startswith("charge.") else "transfer" if event.startswith("transfer.") else "other"
        status = {"charge.success": "success", "transfer.success": "success", "transfer.failed": "failed",
                  "transfer.reversed": "reversed"}.get(event)
        return WebhookEvent(f"{event}:{data.get('id') or data.get('reference')}", kind, data.get("reference"), status)

    def banks(self) -> list:
        return [{"code": b["code"], "name": b["name"]} for b in self._call("GET", "/bank", params={"country": "nigeria"})]

    def resolve_account(self, bank_code: str, account_number: str) -> str:
        data = self._call("GET", "/bank/resolve", params={"account_number": account_number, "bank_code": bank_code})
        return data["account_name"]

    def transfer(self, reference: str, amount_kobo: int, account: dict) -> Transfer:
        code = (account.get("recipient_codes") or {}).get(self.name)
        if not code:
            code = self._call("POST", "/transferrecipient", json={
                "type": "nuban", "name": account["account_name"], "account_number": account["account_number"],
                "bank_code": account["bank_code"], "currency": "NGN"})["recipient_code"]
        data = self._call("POST", "/transfer", json={
            "source": "balance", "amount": amount_kobo, "recipient": code, "reference": reference,
            "reason": "CampusXI withdrawal"})
        return Transfer(_transfer_status(data.get("status")), code)

    def verify_transfer(self, reference: str) -> Transfer:
        return Transfer(_transfer_status(self._call("GET", f"/transfer/verify/{reference}").get("status")))


def _transfer_status(s: str | None) -> str:
    return {"success": "success", "failed": "failed", "reversed": "failed"}.get(s or "", "pending")
