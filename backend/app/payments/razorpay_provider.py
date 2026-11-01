"""Razorpay provider: hosted checkout with manual capture.

Flow: task confirmation creates a Razorpay order (``payment_capture: 0`` → funds
are authorized/held, not auto-captured). The customer pays in the Razorpay
checkout; the returned signature is verified in POST /payments/verify and the
payment is recorded. On completion confirmation the funds are captured and the
worker is paid; cancellations refund the hold. Webhooks keep the record in sync
when the browser callback never arrives.
"""

import hashlib
import hmac

from app.core.config import settings
from app.core.logging import get_logger
from app.payments.base import CaptureResult, PaymentIntent, PaymentProvider
from app.payments.mock_provider import MockPaymentProvider

logger = get_logger("payments.razorpay")


class RazorpayProvider(PaymentProvider):
    name = "razorpay"

    def __init__(self) -> None:
        self._client = None

    # ---------- plumbing ----------

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import razorpay
        except ImportError as exc:
            raise RuntimeError("razorpay package is not installed") from exc
        if not (settings.razorpay_key_id and settings.razorpay_key_secret):
            raise RuntimeError("Razorpay credentials are not configured")
        self._client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
        return self._client

    @staticmethod
    def _paise(amount: float) -> int:
        return int(round(amount * 100))

    # ---------- orders & payments ----------

    def create_payment(self, amount: float, currency: str, reference: str) -> PaymentIntent:
        client = self._get_client()
        order = client.order.create(
            {
                "amount": self._paise(amount),
                "currency": currency,
                "receipt": reference[:40],
                "payment_capture": 0,
                "notes": {"reference": reference},
            }
        )
        return PaymentIntent(
            provider_reference=order["id"],
            status="INITIATED",
            amount=amount,
            currency=currency,
            client_secret=order["id"],
            provider=self.name,
        )

    def fetch_order(self, order_id: str) -> dict | None:
        try:
            return self._get_client().order.fetch(order_id)
        except Exception as exc:
            logger.warning("razorpay order fetch failed order=%s: %s", order_id, exc)
            return None

    def fetch_payment(self, payment_id: str) -> dict | None:
        try:
            return self._get_client().payment.fetch(payment_id)
        except Exception as exc:
            logger.warning("razorpay payment fetch failed payment=%s: %s", payment_id, exc)
            return None

    def payments_for_order(self, order_id: str) -> list[dict]:
        try:
            data = self._get_client().order.payments(order_id) or {}
            return list(data.get("items", []))
        except Exception as exc:
            logger.warning("razorpay order payments failed order=%s: %s", order_id, exc)
            return []

    # ---------- signature verification ----------

    def verify_checkout_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        """HMAC-SHA256 of ``"<order_id>|<payment_id>"`` keyed with the API key secret."""
        secret = settings.razorpay_key_secret
        if not (secret and order_id and payment_id and signature):
            return False
        expected = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        """HMAC-SHA256 of the raw webhook body keyed with the webhook secret."""
        secret = settings.razorpay_webhook_secret
        if not (secret and signature):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ---------- lifecycle ----------

    def capture(
        self,
        provider_reference: str,
        amount: float,
        payment_id: str | None = None,
        currency: str = "INR",
    ) -> CaptureResult:
        if not payment_id:
            return CaptureResult(
                success=False,
                provider_reference=provider_reference,
                captured_amount=0.0,
                failure_reason="Checkout was not completed — there is no payment to capture.",
            )
        data = self.fetch_payment(payment_id)
        if data is None:
            return CaptureResult(False, payment_id, 0.0, "Could not reach the payment gateway.")
        status = data.get("status")
        if status == "captured":
            captured = (data.get("amount") or self._paise(amount)) / 100.0
            return CaptureResult(True, payment_id, captured)
        if status != "authorized":
            return CaptureResult(False, payment_id, 0.0, f"Payment is '{status}' and cannot be captured.")
        try:
            # SDK signature: capture(payment_id, amount, data) — it places the
            # amount in the request body itself, so it must be an integer.
            result = self._get_client().payment.capture(
                payment_id, self._paise(amount), {"currency": currency}
            )
            captured = (result.get("amount") or self._paise(amount)) / 100.0
            return CaptureResult(True, payment_id, captured)
        except Exception as exc:
            # UPI payments auto-capture at authorization and Razorpay then rejects
            # the manual capture call — re-fetch to confirm the money is secured.
            after = self.fetch_payment(payment_id)
            if after and after.get("status") == "captured":
                captured = (after.get("amount") or self._paise(amount)) / 100.0
                return CaptureResult(True, payment_id, captured)
            logger.exception("razorpay capture failed payment=%s", payment_id)
            return CaptureResult(False, payment_id, 0.0, f"Gateway capture failed: {exc}")

    def refund(
        self,
        provider_reference: str,
        amount: float,
        payment_id: str | None = None,
    ) -> CaptureResult:
        reference = payment_id or provider_reference
        if not reference:
            return CaptureResult(False, provider_reference, 0.0, "No payment reference to refund.")
        try:
            result = self._get_client().payment.refund(
                reference, {"amount": self._paise(amount), "speed": "normal"}
            )
            return CaptureResult(True, result.get("id", reference), amount)
        except Exception as exc:
            logger.exception("razorpay refund failed payment=%s", reference)
            return CaptureResult(False, reference, 0.0, f"Gateway refund failed: {exc}")


def get_payment_provider() -> PaymentProvider:
    if settings.payment_provider.lower() == "razorpay":
        try:
            provider = RazorpayProvider()
            provider._get_client()  # fail fast when credentials are missing
            return provider
        except Exception as exc:
            if settings.is_production:
                # Never silently simulate payments in production.
                raise RuntimeError(f"Razorpay is configured but unavailable: {exc}") from exc
            logger.warning("Razorpay unavailable (%s); falling back to mock provider", exc)
    return MockPaymentProvider()
