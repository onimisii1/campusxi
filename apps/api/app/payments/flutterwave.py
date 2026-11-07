"""Flutterwave v3 (https://developer.flutterwave.com). Amounts are naira here (converted at the
boundary); webhooks carry the dashboard's secret hash in the verif-hash header."""
import hmac
import json

import httpx

from app.payments import Checkout, Payment, ProviderError, Transfer, WebhookEvent, http


def _kobo(naira) -> int:
    return int(round(float(naira or 0) * 100))


class Flutterwave:
    name = "flutterwave"

    def __init__(self, secret: str, webhook_hash: str):
        self.webhook_hash = webhook_hash
        self.client = http("https://api.flutterwave.com/v3", secret)

    def _call(self, method: str, path: str, **kw):
        try:
            res = self.client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ProviderError(f"flutterwave unreachable: {e}") from e
        body = res.json() if res.content else {}
        if res.status_code >= 400 or body.get("status") != "success":
            raise ProviderError(f"flutterwave {path}: {body.get('message', res.status_code)}")
        return body["data"]

    def init_deposit(self, reference: str, amount_kobo: int, email: str, callback_url: str,
                     bank_transfer_only: bool = False) -> Checkout:
        data = self._call("POST", "/payments", json={
            "tx_ref": reference, "amount": amount_kobo / 100, "currency": "NGN", "redirect_url": callback_url,
            "customer": {"email": email},
            "payment_options": "banktransfer" if bank_transfer_only else "card,banktransfer,ussd"})
        return Checkout(self.name, reference, data["link"])

    def verify(self, reference: str) -> Payment:
        data = self._call("GET", "/transactions/verify_by_reference", params={"tx_ref": reference})
        status = {"successful": "success", "failed": "failed", "cancelled": "failed"}.get(data.get("status"), "pending")
        if data.get("currency", "NGN") != "NGN":
            status = "failed"
        meta = data.get("meta") or {}                # bank transfers: originatorname / bankname / originatoraccountnumber
        return Payment(status, _kobo(data.get("amount")), data.get("payment_type"), _kobo(data.get("app_fee")),
                       meta.get("originatorname"), meta.get("bankname"), meta.get("originatoraccountnumber"))

    def parse_webhook(self, raw: bytes, headers) -> WebhookEvent:
        if not self.webhook_hash or not hmac.compare_digest(self.webhook_hash, headers.get("verif-hash", "")):
            raise PermissionError("bad flutterwave hash")
        body = json.loads(raw)
        event, data = body.get("event", ""), body.get("data") or {}
        if event == "charge.completed":
            return WebhookEvent(f"{event}:{data.get('id')}", "charge", data.get("tx_ref"),
                                "success" if data.get("status") == "successful" else "failed")
        if event == "transfer.completed":
            return WebhookEvent(f"{event}:{data.get('id')}", "transfer", data.get("reference"),
                                "success" if data.get("status") == "SUCCESSFUL" else "failed")
        return WebhookEvent(f"{event}:{data.get('id')}", "other", None, None)

    def banks(self) -> list:
        return [{"code": b["code"], "name": b["name"]} for b in self._call("GET", "/banks/NG")]

    def resolve_account(self, bank_code: str, account_number: str) -> str:
        return self._call("POST", "/accounts/resolve", json={"account_number": account_number,
                                                              "account_bank": bank_code})["account_name"]

    def transfer(self, reference: str, amount_kobo: int, account: dict) -> Transfer:
        data = self._call("POST", "/transfers", json={
            "account_bank": account["bank_code"], "account_number": account["account_number"],
            "amount": amount_kobo / 100, "currency": "NGN", "reference": reference,
            "narration": "CampusXI withdrawal"})
        return Transfer(_status(data.get("status")), str(data.get("id")))

    def verify_transfer(self, reference: str) -> Transfer:
        rows = self._call("GET", "/transfers", params={"reference": reference})
        return Transfer(_status(rows[0].get("status")) if rows else "pending")


def _status(s: str | None) -> str:
    return {"SUCCESSFUL": "success", "FAILED": "failed"}.get(s or "", "pending")
