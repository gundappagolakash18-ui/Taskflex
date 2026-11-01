"""Auth: register + email OTP verification, login gate, refresh, forgot/reset."""

from tests.conftest import auth_headers


REGISTER_PAYLOAD = {
    "role": "CUSTOMER",
    "full_name": "Ananya Desai",
    "email": "ananya@test.dev",
    "phone": "+919812345678",
    "password": "StrongPass123!",
    "city": "Belagavi",
}


def register_and_verify(client, payload=None) -> dict:
    payload = payload or REGISTER_PAYLOAD
    reg = client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201
    verified = client.post(
        "/api/v1/auth/verify-email", json={"identifier": payload["email"], "code": "123456"}
    )
    assert verified.status_code == 200
    return verified.json()["data"]


def test_register_returns_user_needing_verification(client):
    resp = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    user = data["user"]
    assert user["email"] == "ananya@test.dev"
    assert user["role"] == "CUSTOMER"
    assert user["id"]
    assert data["needs_verification"] is True
    assert "dev_code" not in data
    assert "tokens" not in data


def test_register_worker_role(client):
    payload = dict(REGISTER_PAYLOAD, email="vikram@test.dev", phone="+919812345679", role="WORKER")
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201
    assert resp.json()["data"]["user"]["role"] == "WORKER"


def test_register_requires_real_email_delivery(client, monkeypatch):
    monkeypatch.setattr("app.services.auth_service.settings.email_provider", "log")
    resp = client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"


def test_register_duplicate_email_conflict(client):
    assert client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD).status_code == 201
    dup = dict(REGISTER_PAYLOAD, phone="+919800000000")
    resp = client.post("/api/v1/auth/register", json=dup)
    assert resp.status_code == 409
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "CONFLICT"


def test_register_weak_password_422(client):
    resp = client.post("/api/v1/auth/register", json=dict(REGISTER_PAYLOAD, password="short"))
    assert resp.status_code == 422


def test_login_blocked_until_email_verified(client):
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = client.post(
        "/api/v1/auth/login",
        json={"identifier": "ananya@test.dev", "password": "StrongPass123!"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "EMAIL_NOT_VERIFIED"


def test_login_with_phone_identifier(client):
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    # Unverified: the same gate applies when the phone identifies the account.
    blocked = client.post(
        "/api/v1/auth/login",
        json={"identifier": "+919812345678", "password": "StrongPass123!"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"

    # Verification also works when the phone identifies the account.
    verified = client.post(
        "/api/v1/auth/verify-email", json={"identifier": "+919812345678", "code": "123456"}
    )
    assert verified.status_code == 200

    with_cc = client.post(
        "/api/v1/auth/login",
        json={"identifier": "+919812345678", "password": "StrongPass123!"},
    )
    assert with_cc.status_code == 200

    without_cc = client.post(
        "/api/v1/auth/login",
        json={"identifier": "9812345678", "password": "StrongPass123!"},
    )
    assert without_cc.status_code == 200
    assert without_cc.json()["data"]["user"]["email"] == "ananya@test.dev"


def test_login_with_phone_stored_without_country_code(client):
    payload = dict(REGISTER_PAYLOAD, email="local@test.dev", phone="9876500011")
    client.post("/api/v1/auth/register", json=payload)
    client.post("/api/v1/auth/verify-email", json={"identifier": "9876500011", "code": "123456"})
    resp = client.post(
        "/api/v1/auth/login", json={"identifier": "+919876500011", "password": "StrongPass123!"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["email"] == "local@test.dev"


def test_login_rejects_bad_identifier_and_unknown_phone(client):
    too_short = client.post(
        "/api/v1/auth/login", json={"identifier": "12345", "password": "StrongPass123!"}
    )
    assert too_short.status_code == 422

    unknown = client.post(
        "/api/v1/auth/login", json={"identifier": "+919800000000", "password": "StrongPass123!"}
    )
    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_resend_otp_with_phone_identifier(client):
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    # The registration code was just issued, so the cooldown applies.
    resp = client.post("/api/v1/auth/resend-otp", json={"identifier": "+919812345678"})
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"


def test_verify_with_wrong_code_and_remaining_attempts(client):
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    resp = client.post("/api/v1/auth/verify-email", json={"identifier": "ananya@test.dev", "code": "000000"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"

    # Attempts are tracked: a later correct code still works within the limit.
    client.post("/api/v1/auth/register", json=dict(
        REGISTER_PAYLOAD, email="retry@test.dev", phone="+919811111111"
    ))
    for _ in range(5):
        client.post("/api/v1/auth/verify-email", json={"identifier": "retry@test.dev", "code": "000000"})
    locked = client.post("/api/v1/auth/verify-email", json={"identifier": "retry@test.dev", "code": "123456"})
    assert locked.status_code == 400  # 5 wrong attempts exhaust the code


def test_verify_email_returns_tokens_and_logs_in(client):
    data = register_and_verify(client)
    assert data["tokens"]["token_type"] == "bearer"
    assert data["tokens"]["access_token"]
    assert data["user"]["email"] == "ananya@test.dev"

    # The account is now active: password login works.
    login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "ananya@test.dev", "password": "StrongPass123!"},
    )
    assert login.status_code == 200

    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['tokens']['access_token']}"}
    )
    assert me.status_code == 200


def test_verify_rejects_unknown_email_and_bad_format(client):
    resp = client.post("/api/v1/auth/verify-email", json={"identifier": "ghost@test.dev", "code": "123456"})
    assert resp.status_code == 400

    bad = client.post("/api/v1/auth/verify-email", json={"identifier": "ananya@test.dev", "code": "12ab"})
    assert bad.status_code == 422


def test_verify_twice_rejects_reused_code(client):
    register_and_verify(client)

    # An already-verified account can't be "verified" again via the OTP endpoint.
    again = client.post(
        "/api/v1/auth/verify-email", json={"identifier": "ananya@test.dev", "code": "123456"}
    )
    assert again.status_code == 400


def test_resend_otp_cooldown_429(client):
    client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = client.post("/api/v1/auth/resend-otp", json={"identifier": "ananya@test.dev"})
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"


def test_resend_otp_never_probes_unknown_emails(client):
    resp = client.post("/api/v1/auth/resend-otp", json={"identifier": "ghost@test.dev"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "dev_code" not in body["data"]


def test_me_requires_token(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_refresh_returns_new_tokens(client):
    tokens = register_and_verify(client)["tokens"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new_tokens = resp.json()["data"]["tokens"]
    assert new_tokens["access_token"]
    assert new_tokens["refresh_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_tokens['access_token']}"})
    assert me.status_code == 200


def test_refresh_rejects_access_token(client):
    tokens = register_and_verify(client)["tokens"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


def test_forgot_and_reset_password(client):
    register_and_verify(client)

    forgot = client.post("/api/v1/auth/forgot-password", json={"email": "ananya@test.dev"})
    assert forgot.status_code == 200
    reset_token = forgot.json()["data"].get("reset_token")
    assert reset_token  # dev/demo mode returns the raw token

    reset = client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "new_password": "NewStrong123!"},
    )
    assert reset.status_code == 200

    old_login = client.post(
        "/api/v1/auth/login", json={"identifier": "ananya@test.dev", "password": "StrongPass123!"}
    )
    assert old_login.status_code == 401
    new_login = client.post(
        "/api/v1/auth/login", json={"identifier": "ananya@test.dev", "password": "NewStrong123!"}
    )
    assert new_login.status_code == 200


def test_auth_headers_helper_reaches_me(client, db):
    from tests.conftest import make_user

    user = make_user(db, "CUSTOMER")
    resp = client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["id"] == user.id


# ---------- google sign-in ----------

GOOGLE_CLAIMS = {
    "iss": "https://accounts.google.com",
    "aud": "test-client-id",
    "sub": "google-sub-123",
    "email": "gwen@test.dev",
    "email_verified": True,
    "name": "Gwen Cooper",
    "picture": "https://lh3.googleusercontent.com/a/gwen.jpg",
}


def _fake_service_verifier(monkeypatch, claims=None, error=None):
    """Replace token verification at the service boundary (auth_service's import)."""
    import app.services.auth_service as auth_module

    def fake_verify(credential):
        if error is not None:
            raise error
        return dict(claims or GOOGLE_CLAIMS)

    monkeypatch.setattr(auth_module, "verify_google_id_token", fake_verify)


def _google_post(client, role="CUSTOMER"):
    return client.post("/api/v1/auth/google", json={"credential": "x" * 40, "role": role})


def test_google_login_creates_account_first_time(client, monkeypatch):
    _fake_service_verifier(monkeypatch)
    resp = _google_post(client)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["created"] is True
    user = data["user"]
    assert user["email"] == "gwen@test.dev"
    assert user["full_name"] == "Gwen Cooper"
    assert user["role"] == "CUSTOMER"
    assert user["is_email_verified"] is True
    assert user["phone"] is None
    assert user["avatar_url"] == GOOGLE_CLAIMS["picture"]
    assert data["tokens"]["access_token"]

    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['tokens']['access_token']}"}
    )
    assert me.status_code == 200


def test_google_login_second_visit_same_account(client, monkeypatch):
    _fake_service_verifier(monkeypatch)
    first = _google_post(client).json()["data"]
    second = _google_post(client).json()["data"]
    assert second["created"] is False
    assert second["user"]["id"] == first["user"]["id"]


def test_google_login_worker_role(client, monkeypatch):
    _fake_service_verifier(monkeypatch, claims=dict(GOOGLE_CLAIMS, email="gworker@test.dev"))
    resp = _google_post(client, role="WORKER")
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["role"] == "WORKER"


def test_google_login_links_existing_unverified_account(client, monkeypatch):
    client.post(
        "/api/v1/auth/register",
        json=dict(REGISTER_PAYLOAD, email="gwen@test.dev", phone="+919833333333"),
    )
    _fake_service_verifier(monkeypatch)
    resp = _google_post(client)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["created"] is False
    assert data["user"]["is_email_verified"] is True

    # Linking marks the email verified, so the existing password now logs in.
    login = client.post(
        "/api/v1/auth/login", json={"identifier": "gwen@test.dev", "password": "StrongPass123!"}
    )
    assert login.status_code == 200


def test_google_login_blocked_for_suspended_account(client, monkeypatch, db):
    from tests.conftest import make_user

    make_user(db, "CUSTOMER", email="gwen@test.dev", is_active=False)
    _fake_service_verifier(monkeypatch)
    resp = _google_post(client)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_google_login_password_login_rejected_for_google_account(client, monkeypatch):
    _fake_service_verifier(monkeypatch)
    _google_post(client)
    resp = client.post(
        "/api/v1/auth/login", json={"identifier": "gwen@test.dev", "password": "whatever123"}
    )
    assert resp.status_code == 400
    assert "Google" in resp.json()["error"]["message"]


def test_google_login_invalid_token_401(client, monkeypatch):
    from app.core.exceptions import UnauthorizedException

    # The real verifier converts ValueError -> UnauthorizedException before
    # the service sees it; the fake must match that contract.
    _fake_service_verifier(
        monkeypatch, error=UnauthorizedException("Google sign-in could not be verified. Please try again.")
    )
    resp = _google_post(client)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_google_rejects_unverified_email_claim(client, monkeypatch):
    # Exercises the real verifier (email_verified gate) with a stubbed Google lib.
    from google.oauth2 import id_token as google_id_token

    monkeypatch.setattr(
        "app.core.google_oauth.settings.google_client_id", "test-client-id"
    )
    monkeypatch.setattr(
        google_id_token,
        "verify_oauth2_token",
        lambda token, request, audience=None: dict(GOOGLE_CLAIMS, email_verified=False),
    )
    resp = _google_post(client)
    assert resp.status_code == 401


def test_google_verifier_rejects_bad_signature(client, monkeypatch):
    from google.oauth2 import id_token as google_id_token

    monkeypatch.setattr(
        "app.core.google_oauth.settings.google_client_id", "test-client-id"
    )

    def _raise(token, request, audience=None):
        raise ValueError("Signature verification failed")

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", _raise)
    resp = _google_post(client)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_google_config_reports_disabled_by_default(client):
    resp = client.get("/api/v1/auth/google/config")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["enabled"] is False
    assert body["client_id"] is None


def test_google_config_reflects_client_id(client, monkeypatch):
    monkeypatch.setattr("app.core.google_oauth.settings.google_client_id", "abc.apps.googleusercontent.com")
    resp = client.get("/api/v1/auth/google/config")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["enabled"] is True
    assert body["client_id"] == "abc.apps.googleusercontent.com"
