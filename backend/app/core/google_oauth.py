"""Google Identity Services id_token verification (Sign in with Google)."""

from app.core.config import settings
from app.core.exceptions import AppException, ErrorCode, UnauthorizedException
from app.core.logging import get_logger

logger = get_logger("auth")

_TRUSTED_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


def verify_google_id_token(credential: str) -> dict:
    """Validate a GIS id_token and return its claims (sub, email, name, picture).

    Verifies the JWS signature against Google's public keys, the audience
    (GOOGLE_CLIENT_ID), expiry, issuer, and that Google marked the email
    as verified.
    """
    if not settings.google_oauth_enabled:
        raise AppException(
            "Google sign-in is not configured on this server.",
            code=ErrorCode.VALIDATION_ERROR,
            status_code=503,
        )

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        claims = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), settings.google_client_id
        )
    except ValueError as exc:
        logger.info("google_token_rejected reason=%s", exc)
        raise UnauthorizedException("Google sign-in could not be verified. Please try again.") from exc

    if claims.get("iss") not in _TRUSTED_ISSUERS:
        raise UnauthorizedException("Google sign-in could not be verified. Please try again.")
    if not claims.get("email_verified", False):
        logger.info("google_token_unverified_email")
        raise UnauthorizedException(
            "Your Google account does not have a verified email address."
        )
    if not claims.get("email"):
        raise UnauthorizedException("Google sign-in did not return an email address.")
    return claims
