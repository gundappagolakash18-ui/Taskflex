"""Payment flow: Razorpay signature verification, checkout/verify/webhook,
capture + worker payout, refunds, and the mock-provider regression path."""

import hashlib
import hmac
import json

from app.core.config import settings as app_settings
from app.models import Payment, Task, TaskExecutionProof, Wallet
from app.payments.razorpay_provider import RazorpayProvider

from tests.conftest import auth_headers, make_user, task_payload

KEY_ID = "rzp_test_key_id"
KEY_SECRET = "rzp_test_key_secret"
WEBHOOK_SECRET = "whsec_test_secret"


# ---------------------------------------------------------------------------
# Fake Razorpay SDK client (mirrors razorpay.Client's resource nesting)
# ---------------------------------------------------------------------------


class _FakeOrders:
    def __init__(self, client: "FakeRazorpayClient") -> None:
        self._client = client

    def create(self, data: dict) -> dict:
        order = {
            "id": self._client.next_id("order"),
            "amount": data["amount"],
            "currency": data["currency"],
            "receipt": data.get("receipt"),
            "payment_capture": data.get("payment_capture"),
            "status": "created",
        }
        self._client.orders[order["id"]] = order
        return dict(order)

    def fetch(self, order_id: str) -> dict:
        order = self._client.orders.get(order_id)
        if order is None:
            raise RuntimeError(f"order {order_id} not found")
        return dict(order)

    def payments(self, order_id: str) -> dict:
        return {"items": [dict(p) for p in self._client.payments.values() if p["order_id"] == order_id]}


class _FakePayments:
    def __init__(self, client: "FakeRazorpayClient") -> None:
        self._client = client

    def fetch(self, payment_id: str) -> dict:
        record = self._client.payments.get(payment_id)
        if record is None:
            raise RuntimeError(f"payment {payment_id} not found")
        return dict(record)

    def capture(self, payment_id: str, amount: int, data: dict | None = None) -> dict:
        # Mirrors razorpay.resources.payment.Payment.capture(payment_id, amount, data).
        record = self._client.payments[payment_id]
        if record["status"] != "authorized":
            raise RuntimeError(f"payment is {record['status']} and cannot be captured")
        record["status"] = "captured"
        record["amount"] = amount
        self._client.capture_calls.append(
            {"payment_id": payment_id, "amount": amount, "data": dict(data or {})}
        )
        return dict(record)

    def refund(self, payment_id: str, data: dict) -> dict:
        self._client.refunds.append({"id": f"rfnd_{payment_id}", "payment_id": payment_id, "amount": data["amount"]})
        return {"id": f"rfnd_{payment_id}", "amount": data["amount"]}


class FakeRazorpayClient:
    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.refunds: list[dict] = []
        self.capture_calls: list[dict] = []
        self._seq = 0
        self.order = _FakeOrders(self)
        self.payment = _FakePayments(self)

    def next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_test{self._seq:04d}"


def install_razorpay(monkeypatch) -> FakeRazorpayClient:
    """Route PaymentService through a RazorpayProvider backed by a fake SDK client."""
    client = FakeRazorpayClient()
    provider = RazorpayProvider()
    provider._client = client
    monkeypatch.setattr("app.services.payment_service.get_payment_provider", lambda: provider)
    monkeypatch.setattr(app_settings, "razorpay_key_id", KEY_ID)
    monkeypatch.setattr(app_settings, "razorpay_key_secret", KEY_SECRET)
    monkeypatch.setattr(app_settings, "razorpay_webhook_secret", WEBHOOK_SECRET)
    return client


def checkout_signature(order_id: str, payment_id: str) -> str:
    return hmac.new(KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def webhook_signature(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def stage_gateway_payment(fake: FakeRazorpayClient, order_id: str, payment_id: str, status: str = "authorized") -> None:
    """Mirror the gateway-side record of a payment the customer just made."""
    fake.payments[payment_id] = {
        "id": payment_id,
        "order_id": order_id,
        "status": status,
        "amount": 35000,
        "currency": "INR",
    }


def test_razorpay_capture_sends_integer_amount_and_currency():
    """The SDK builds the request body itself: capture(id, amount, data)."""
    client = FakeRazorpayClient()
    stage_gateway_payment(client, "order_capture", "pay_capture")
    provider = RazorpayProvider()
    provider._client = client

    result = provider.capture("order_capture", 350.0, payment_id="pay_capture")

    assert result.success is True
    assert result.captured_amount == 350.0
    assert client.capture_calls == [
        {"payment_id": "pay_capture", "amount": 35000, "data": {"currency": "INR"}}
    ]


def confirm_task(client, customer, **overrides) -> dict:
    created = client.post("/api/v1/tasks", json=task_payload(**overrides), headers=auth_headers(customer))
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task"]["id"]
    confirmed = client.post(f"/api/v1/tasks/{task_id}/confirm", headers=auth_headers(customer))
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["data"]["task"]


def accept_and_finish(client, db, worker, customer, task_id: str) -> dict:
    """Worker accepts, walks the OTP handshake (start code → IN_PROGRESS,
    proof + completion code → COMPLETED) and returns the final task payload."""
    offers = client.get("/api/v1/workers/me/offers", headers=auth_headers(worker)).json()["data"]["items"]
    offer_id = next(o["offer"]["id"] for o in offers if o["task"]["id"] == task_id)
    accepted = client.post(f"/api/v1/workers/offers/{offer_id}/accept", headers=auth_headers(worker))
    assert accepted.status_code == 200, accepted.text
    for next_status in ("WORKER_ON_THE_WAY", "ARRIVED_AT_LOCATION"):
        step = client.post(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": next_status},
            headers=auth_headers(worker),
        )
        assert step.status_code == 200, step.text

    start_code = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)
    ).json()["data"]["task"]["start_otp_display"]
    started = client.post(
        f"/api/v1/tasks/{task_id}/verify-start-otp",
        json={"otp": start_code},
        headers=auth_headers(worker),
    )
    assert started.status_code == 200, started.text

    db.add(TaskExecutionProof(task_id=task_id, worker_id=worker.id, file_key=f"proofs/{task_id}.webp"))
    db.commit()
    requested = client.post(
        f"/api/v1/tasks/{task_id}/request-completion", headers=auth_headers(worker)
    )
    assert requested.status_code == 200, requested.text

    completion_code = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)
    ).json()["data"]["task"]["completion_otp_display"]
    done = client.post(
        f"/api/v1/tasks/{task_id}/complete",
        json={"otp": completion_code},
        headers=auth_headers(worker),
    )
    assert done.status_code == 200, done.text
    return done.json()["data"]["task"]


# ---------------------------------------------------------------------------
# Signature verification (unit)
# ---------------------------------------------------------------------------


def test_checkout_signature_verification(monkeypatch):
    monkeypatch.setattr(app_settings, "razorpay_key_secret", KEY_SECRET)
    provider = RazorpayProvider()
    order_id, payment_id = "order_unit000001", "pay_unit000001"
    assert provider.verify_checkout_signature(order_id, payment_id, checkout_signature(order_id, payment_id))
    assert not provider.verify_checkout_signature(order_id, payment_id, "0" * 64)
    assert not provider.verify_checkout_signature(order_id, payment_id, "")
    assert not provider.verify_checkout_signature("", payment_id, checkout_signature(order_id, payment_id))
    assert not provider.verify_checkout_signature(order_id, "", checkout_signature(order_id, payment_id))
    monkeypatch.setattr(app_settings, "razorpay_key_secret", "")
    assert not provider.verify_checkout_signature(order_id, payment_id, checkout_signature(order_id, payment_id))


def test_webhook_signature_verification(monkeypatch):
    monkeypatch.setattr(app_settings, "razorpay_webhook_secret", WEBHOOK_SECRET)
    provider = RazorpayProvider()
    body = b'{"event": "payment.authorized"}'
    assert provider.verify_webhook_signature(body, webhook_signature(body))
    assert not provider.verify_webhook_signature(body, webhook_signature(b"other body"))
    assert not provider.verify_webhook_signature(body, "")
    monkeypatch.setattr(app_settings, "razorpay_webhook_secret", "")
    assert not provider.verify_webhook_signature(body, webhook_signature(body))


# ---------------------------------------------------------------------------
# Mock-provider regression (dev / default test configuration)
# ---------------------------------------------------------------------------


def test_checkout_reports_nothing_due_for_mock_provider(client, db):
    customer = make_user(db, "CUSTOMER")
    task = confirm_task(client, customer)
    assert task["payment_status"] == "AUTHORIZED"

    checkout = client.get(f"/api/v1/payments/checkout/{task['id']}", headers=auth_headers(customer))
    assert checkout.status_code == 200
    assert checkout.json()["data"] == {"required": False, "provider": "mock", "status": "AUTHORIZED"}

    verify = client.post(
        "/api/v1/payments/verify",
        json={
            "razorpay_order_id": "order_mock0001",
            "razorpay_payment_id": "pay_mock0001",
            "razorpay_signature": "0" * 64,
        },
        headers=auth_headers(customer),
    )
    assert verify.status_code == 400


def test_checkout_requires_task_owner(client, db):
    customer = make_user(db, "CUSTOMER")
    stranger = make_user(db, "CUSTOMER")
    task = confirm_task(client, customer)

    forbidden = client.get(f"/api/v1/payments/checkout/{task['id']}", headers=auth_headers(stranger))
    assert forbidden.status_code == 403
    missing = client.get("/api/v1/payments/checkout/no-such-task", headers=auth_headers(customer))
    assert missing.status_code == 404


def test_cancel_refunds_mock_payment(client, db):
    customer = make_user(db, "CUSTOMER")
    task = confirm_task(client, customer)

    cancelled = client.post(
        f"/api/v1/tasks/{task['id']}/cancel",
        json={"reason": "Changed my mind"},
        headers=auth_headers(customer),
    )
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()["data"]["task"]
    assert body["status"] == "CANCELLED"
    assert body["payment_status"] == "REFUNDED"

    payment = db.query(Payment).filter(Payment.task_id == task["id"]).one()
    assert payment.status == "REFUNDED"


# ---------------------------------------------------------------------------
# Razorpay flow
# ---------------------------------------------------------------------------


def test_razorpay_checkout_verify_capture_flow(client, db, monkeypatch):
    fake = install_razorpay(monkeypatch)
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER", skills=("document_submission",))

    task = confirm_task(client, customer)
    task_id = task["id"]
    assert task["payment_status"] == "INITIATED"

    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    order_id = payment.provider_reference
    assert order_id and order_id.startswith("order_")
    assert payment.status == "INITIATED"

    # 1 — checkout details for the hosted widget.
    checkout = client.get(f"/api/v1/payments/checkout/{task_id}", headers=auth_headers(customer))
    assert checkout.status_code == 200
    data = checkout.json()["data"]
    assert data["required"] is True
    assert data["provider"] == "razorpay"
    assert data["key_id"] == KEY_ID
    assert data["order_id"] == order_id
    assert data["amount"] == 35000  # paise
    assert data["currency"] == "INR"
    assert data["prefill"]["email"] == customer.email

    # 2 — the customer pays in the widget; the signature is verified.
    payment_id = "pay_" + order_id[6:]
    stage_gateway_payment(fake, order_id, payment_id)
    verify = client.post(
        "/api/v1/payments/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": checkout_signature(order_id, payment_id),
        },
        headers=auth_headers(customer),
    )
    assert verify.status_code == 200, verify.text
    verified = verify.json()["data"]["payment"]
    assert verified["status"] == "AUTHORIZED"

    db.expire_all()
    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    assert payment.provider_payment_id == payment_id
    assert payment.status == "AUTHORIZED"
    assert db.get(Task, task_id).payment_status == "AUTHORIZED"

    # 3 — nothing left to collect; retrying checkout is a no-op.
    again = client.get(f"/api/v1/payments/checkout/{task_id}", headers=auth_headers(customer))
    assert again.json()["data"]["required"] is False

    # 4 — the job runs to completion; funds are captured and the worker is paid.
    finished = accept_and_finish(client, db, worker, customer, task_id)
    assert finished["payment_status"] == "CAPTURED"
    assert fake.payments[payment_id]["status"] == "captured"

    db.expire_all()
    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    assert payment.status == "CAPTURED"
    assert payment.captured_at is not None
    wallet = db.query(Wallet).filter(Wallet.user_id == worker.id).one()
    assert float(wallet.balance) == 315.0  # 350 minus 10% commission


def test_verify_rejects_bad_signature_and_foreign_payments(client, db, monkeypatch):
    install_razorpay(monkeypatch)
    customer = make_user(db, "CUSTOMER")
    other_customer = make_user(db, "CUSTOMER")
    task = confirm_task(client, customer)

    payment = db.query(Payment).filter(Payment.task_id == task["id"]).one()
    order_id = payment.provider_reference
    payment_id = "pay_badsig0001"
    payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": checkout_signature(order_id, payment_id),
    }

    tampered = client.post(
        "/api/v1/payments/verify",
        json={**payload, "razorpay_signature": "f" * 64},
        headers=auth_headers(customer),
    )
    assert tampered.status_code == 400

    stolen = client.post("/api/v1/payments/verify", json=payload, headers=auth_headers(other_customer))
    assert stolen.status_code == 403


def test_razorpay_upi_autocapture_is_detected_at_completion(client, db, monkeypatch):
    fake = install_razorpay(monkeypatch)
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER", skills=("document_submission",))
    task = confirm_task(client, customer)
    task_id = task["id"]

    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    order_id = payment.provider_reference
    payment_id = "pay_upi00000001"
    stage_gateway_payment(fake, order_id, payment_id)
    verified = client.post(
        "/api/v1/payments/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": checkout_signature(order_id, payment_id),
        },
        headers=auth_headers(customer),
    )
    assert verified.status_code == 200

    # UPI auto-captures at authorization; Razorpay then rejects the manual
    # capture call, but a re-fetch shows the money is already secured.
    def capture_raises(payment_id_: str, amount: int, data: dict | None = None) -> dict:
        fake.payments[payment_id_]["status"] = "captured"
        raise RuntimeError("This payment has already been captured")

    monkeypatch.setattr(fake.payment, "capture", capture_raises)

    accept_and_finish(client, db, worker, customer, task_id)
    db.expire_all()
    assert db.get(Task, task_id).payment_status == "CAPTURED"


def test_checkout_reconciles_paid_order_without_callback(client, db, monkeypatch):
    fake = install_razorpay(monkeypatch)
    customer = make_user(db, "CUSTOMER")
    task = confirm_task(client, customer)
    task_id = task["id"]

    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    order_id = payment.provider_reference
    payment_id = "pay_late0000001"
    # Paid at the gateway, but the browser callback never reached TaskFlex.
    fake.orders[order_id]["status"] = "paid"
    stage_gateway_payment(fake, order_id, payment_id)

    checkout = client.get(f"/api/v1/payments/checkout/{task_id}", headers=auth_headers(customer))
    assert checkout.status_code == 200
    data = checkout.json()["data"]
    assert data["required"] is False
    assert data["status"] == "AUTHORIZED"

    db.expire_all()
    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    assert payment.status == "AUTHORIZED"
    assert payment.provider_payment_id == payment_id


def test_cancel_closes_unpaid_gateway_order(client, db, monkeypatch):
    install_razorpay(monkeypatch)
    customer = make_user(db, "CUSTOMER")
    task = confirm_task(client, customer)

    # The customer never completed checkout: nothing to refund, order closed.
    cancelled = client.post(
        f"/api/v1/tasks/{task['id']}/cancel",
        json={"reason": "No longer needed"},
        headers=auth_headers(customer),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["task"]["payment_status"] == "CANCELLED"

    payment = db.query(Payment).filter(Payment.task_id == task["id"]).one()
    assert payment.status == "CANCELLED"

    checkout = client.get(f"/api/v1/payments/checkout/{task['id']}", headers=auth_headers(customer))
    assert checkout.status_code == 409


def test_cancel_refunds_razorpay_authorized_payment(client, db, monkeypatch):
    fake = install_razorpay(monkeypatch)
    customer = make_user(db, "CUSTOMER")
    task = confirm_task(client, customer)
    task_id = task["id"]

    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    order_id = payment.provider_reference
    payment_id = "pay_refund00001"
    stage_gateway_payment(fake, order_id, payment_id)
    verified = client.post(
        "/api/v1/payments/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": checkout_signature(order_id, payment_id),
        },
        headers=auth_headers(customer),
    )
    assert verified.status_code == 200

    cancelled = client.post(
        f"/api/v1/tasks/{task_id}/cancel",
        json={"reason": "Found someone locally"},
        headers=auth_headers(customer),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["task"]["payment_status"] == "REFUNDED"

    db.expire_all()
    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    assert payment.status == "REFUNDED"
    assert any(r["payment_id"] == payment_id for r in fake.refunds)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def test_webhook_requires_secret_configuration(client, monkeypatch):
    monkeypatch.setattr(app_settings, "razorpay_webhook_secret", "")
    response = client.post(
        "/api/v1/payments/webhook/razorpay",
        content=json.dumps({"event": "payment.authorized"}).encode(),
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": "0" * 64},
    )
    assert response.status_code == 503


def test_webhook_applies_gateway_events(client, db, monkeypatch):
    install_razorpay(monkeypatch)
    customer = make_user(db, "CUSTOMER")
    task = confirm_task(client, customer)
    task_id = task["id"]

    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    order_id = payment.provider_reference
    payment_id = "pay_hook0000001"

    def post_event(event: dict, signature: str | None = None):
        body = json.dumps(event).encode()
        return client.post(
            "/api/v1/payments/webhook/razorpay",
            content=body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": signature or webhook_signature(body)},
        )

    def event_for(event_type: str, entity: dict) -> dict:
        return {"event": event_type, "payload": {"payment": {"entity": entity}}}

    entity = {"id": payment_id, "order_id": order_id, "status": "authorized", "amount": 35000, "currency": "INR"}

    bad = post_event(event_for("payment.authorized", entity), signature="0" * 64)
    assert bad.status_code == 400

    authorized = post_event(event_for("payment.authorized", entity))
    assert authorized.status_code == 200
    assert authorized.json()["data"]["outcome"] == "updated"

    db.expire_all()
    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    assert payment.status == "AUTHORIZED"
    assert payment.provider_payment_id == payment_id
    assert db.get(Task, task_id).payment_status == "AUTHORIZED"

    unknown = post_event(event_for("payment.captured", {"id": "pay_x", "order_id": "order_unknown"}))
    assert unknown.json()["data"]["outcome"] == "unknown_order"

    ignored = post_event({"event": "payment.authorized", "payload": {}})
    assert ignored.json()["data"]["outcome"] == "ignored"


def test_webhook_marks_failed_payment_and_recovers(client, db, monkeypatch):
    install_razorpay(monkeypatch)
    customer = make_user(db, "CUSTOMER")
    task = confirm_task(client, customer)
    task_id = task["id"]

    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    order_id = payment.provider_reference
    payment_id = "pay_retry000001"

    def post_event(event: dict):
        body = json.dumps(event).encode()
        return client.post(
            "/api/v1/payments/webhook/razorpay",
            content=body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": webhook_signature(body)},
        )

    def event_for(event_type: str, entity: dict) -> dict:
        return {"event": event_type, "payload": {"payment": {"entity": entity}}}

    failed = post_event(
        event_for(
            "payment.failed",
            {
                "id": payment_id,
                "order_id": order_id,
                "status": "failed",
                "error_description": "Card declined by issuer.",
            },
        )
    )
    assert failed.status_code == 200
    assert failed.json()["data"]["outcome"] == "failed"

    db.expire_all()
    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    assert payment.status == "FAILED"
    assert db.get(Task, task_id).payment_status == "FAILED"

    # The customer retries in the widget and succeeds → webhook recovers it.
    retried = post_event(
        event_for("payment.authorized", {"id": payment_id, "order_id": order_id, "status": "authorized", "amount": 35000})
    )
    assert retried.json()["data"]["outcome"] == "updated"

    db.expire_all()
    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    assert payment.status == "AUTHORIZED"
