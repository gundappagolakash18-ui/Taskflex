"""Simulated payment gateway for development, demos and tests.
Authorizes instantly with deterministic references and always captures successfully."""

import hashlib
from datetime import datetime, timezone

from app.payments.base import CaptureResult, PaymentIntent, PaymentProvider


class MockPaymentProvider(PaymentProvider):
    name = "mock"

    def create_payment(self, amount: float, currency: str, reference: str) -> PaymentIntent:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        digest = hashlib.sha256(f"{reference}:{stamp}".encode()).hexdigest()[:12]
        return PaymentIntent(
            provider_reference=f"mock_pay_{digest}",
            status="AUTHORIZED",
            amount=amount,
            currency=currency,
            client_secret=f"mock_secret_{digest}",
            provider=self.name,
        )

    def capture(
        self,
        provider_reference: str,
        amount: float,
        payment_id: str | None = None,
        currency: str = "INR",
    ) -> CaptureResult:
        return CaptureResult(success=True, provider_reference=provider_reference, captured_amount=amount)

    def refund(
        self,
        provider_reference: str,
        amount: float,
        payment_id: str | None = None,
    ) -> CaptureResult:
        return CaptureResult(success=True, provider_reference=provider_reference, captured_amount=amount)
