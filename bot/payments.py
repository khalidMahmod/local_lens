"""Payment link generation. ToyyibPay-backed but provider-agnostic.

DuitNow / Stripe / etc. can swap in by implementing `PaymentProvider`.

ToyyibPay sandbox: https://dev.toyyibpay.com — production: https://toyyibpay.com.
The API takes a `userSecretKey` + `categoryCode` and returns a `BillCode`; the
payment URL is `{base_url}/{BillCode}`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from bot.models import Session

logger = logging.getLogger(__name__)

TOYYIBPAY_SANDBOX_BASE = "https://dev.toyyibpay.com"
TOYYIBPAY_PRODUCTION_BASE = "https://toyyibpay.com"

# Returned when no provider is configured (dev without ToyyibPay creds).
PLACEHOLDER_PAYMENT_URL = "https://toyyibpay.example.com/no-payment-configured"


class PaymentProvider(Protocol):
    def create_bill(self, *, amount_rm: int, description: str, reference: str) -> str:
        """Create a bill with the provider, return the user-facing payment URL."""


@dataclass(frozen=True)
class ToyyibPayProvider:
    api_key: str
    category_code: str
    base_url: str = TOYYIBPAY_SANDBOX_BASE
    return_url: str = ""
    callback_url: str = ""

    def create_bill(self, *, amount_rm: int, description: str, reference: str) -> str:
        # ToyyibPay wants the amount in cents and a strict set of form fields.
        payload = {
            "userSecretKey": self.api_key,
            "categoryCode": self.category_code,
            "billName": "LocalLens plan",
            "billDescription": description[:100],  # ToyyibPay caps at 100 chars
            "billPriceSetting": 1,
            "billPayorInfo": 0,
            "billAmount": str(int(amount_rm) * 100),
            "billReturnUrl": self.return_url,
            "billCallbackUrl": self.callback_url,
            "billExternalReferenceNo": reference,
            "billTo": "",
            "billEmail": "",
            "billPhone": "",
            "billSplitPayment": 0,
            "billPaymentChannel": 0,
            "billContentEmail": "Thanks for trying LocalLens.",
            "billChargeToCustomer": 1,
        }
        resp = requests.post(
            f"{self.base_url}/index.php/api/createBill", data=payload, timeout=15
        )
        resp.raise_for_status()
        body: Any = resp.json()
        # Successful response is a list with one dict containing BillCode.
        if not isinstance(body, list) or not body or "BillCode" not in body[0]:
            raise RuntimeError(f"Unexpected ToyyibPay response: {body!r}")
        return f"{self.base_url}/{body[0]['BillCode']}"


def build_payment_link(
    session: Session,
    *,
    provider: PaymentProvider | None = None,
) -> str:
    """Return a payment URL for `session`'s commitment.

    When `provider` is None (e.g., dev without TOYYIBPAY credentials), returns
    the placeholder URL so the rest of the flow stays exercisable.
    """
    if provider is None:
        logger.info(
            "No payment provider configured; returning placeholder URL for user %s",
            session.telegram_user_id,
        )
        return PLACEHOLDER_PAYMENT_URL

    amount = session.commitment_price or 0
    reference = f"{session.telegram_user_id}:{session.active_package_id or 'no-pkg'}"
    description = f"LocalLens plan — {session.active_package_id or 'plan'}"
    try:
        return provider.create_bill(
            amount_rm=amount, description=description, reference=reference
        )
    except (requests.RequestException, RuntimeError):
        logger.exception(
            "Payment provider failed for user %s; returning placeholder URL",
            session.telegram_user_id,
        )
        return PLACEHOLDER_PAYMENT_URL
