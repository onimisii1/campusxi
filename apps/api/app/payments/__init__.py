"""Payment providers behind one interface: Paystack first, Flutterwave as the fallback.

Each provider: start a checkout (deposit), verify a payment server-side, check a webhook's
signature, resolve a bank account name, and send a transfer (withdrawal). Amounts are always
kobo at this boundary; Flutterwave's naira amounts are converted inside its class.

Keys come only from the environment (settings). Tests swap the HTTP transport (TRANSPORT) for a
fake, so they never touch the network.
"""
from dataclasses import dataclass

import httpx

from app.config import settings

TRANSPORT: httpx.BaseTransport | None = None     # tests set an httpx.MockTransport here


class ProviderError(Exception):
    """The provider refused or is unreachable: try the next one."""


@dataclass(frozen=True)
class Checkout:
    provider: str
    reference: str
    url: str


@dataclass(frozen=True)
class Payment:
    status: str            # success | failed | pending
    amount_kobo: int
    channel: str | None = None
    fee_kobo: int = 0


@dataclass(frozen=True)
class WebhookEvent:
    event_id: str
    kind: str              # charge | transfer | other
    reference: str | None
    status: str | None     # success | failed | reversed | None


@dataclass(frozen=True)
class Transfer:
    status: str            # pending | success | failed
    provider_ref: str | None = None


def http(base_url: str, secret: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, transport=TRANSPORT, timeout=20,
                        headers={"Authorization": f"Bearer {secret}"})


def get(name: str):
    from app.payments.flutterwave import Flutterwave
    from app.payments.paystack import Paystack
    if name == "paystack":
        return Paystack(settings.paystack_secret_key)
    if name == "flutterwave":
        return Flutterwave(settings.flutterwave_secret_key, settings.flutterwave_webhook_hash)
    raise KeyError(name)


def configured() -> list:
    """Providers with a key, in preference order."""
    keys = {"paystack": settings.paystack_secret_key, "flutterwave": settings.flutterwave_secret_key}
    return [get(n) for n in settings.payment_providers if keys.get(n)]
