"""Payment provider abstraction. Task/payment business logic depends only on
the PaymentProvider interface — never on Razorpay or any concrete gateway."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PaymentIntent:
    provider_reference: str
    status: str  # INITIATED | AUTHORIZED | FAILED
    amount: float
    currency: str
    client_secret: str | None = None
    provider: str = "mock"


@dataclass
class CaptureResult:
    success: bool
    provider_reference: str
    captured_amount: float
    failure_reason: str | None = None


class PaymentProvider(ABC):
    name: str = "base"

    @abstractmethod
    def create_payment(self, amount: float, currency: str, reference: str) -> PaymentIntent:
        """Authorize (hold) funds for a confirmed task."""

    @abstractmethod
    def capture(
        self,
        provider_reference: str,
        amount: float,
        payment_id: str | None = None,
        currency: str = "INR",
    ) -> CaptureResult:
        """Capture previously authorized funds after task completion.

        ``provider_reference`` is the order created at authorization time;
        ``payment_id`` is the gateway payment produced by the customer's checkout
        (required by gateways such as Razorpay for capture/refund)."""

    @abstractmethod
    def refund(
        self,
        provider_reference: str,
        amount: float,
        payment_id: str | None = None,
    ) -> CaptureResult:
        """Refund a captured/authorized payment (used on cancellations & disputes)."""

    def verify_checkout_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        """Verify the signature returned by a hosted checkout. Hosted-checkout
        providers override this; providers without a checkout return False."""
        return False

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        """Verify an inbound webhook signature. Overridden by real gateways."""
        return False
