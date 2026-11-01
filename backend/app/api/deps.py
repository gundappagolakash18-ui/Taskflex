from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import jwt as pyjwt

from app.db.session import get_db
from app.core.exceptions import UnauthorizedException
from app.core.security import decode_token
from app.models import User
from app.repositories import UserRepository
from app.services.auth_service import UserRole_CUSTOMER, UserRole_WORKER

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedException("Authentication required. Please sign in.")
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except pyjwt.ExpiredSignatureError as exc:
        raise UnauthorizedException("Your session has expired. Please sign in again.") from exc
    except pyjwt.InvalidTokenError as exc:
        raise UnauthorizedException("Invalid authentication token.") from exc

    users = UserRepository(db)
    user = users.get_by_id(payload["sub"])
    if user is None:
        raise UnauthorizedException("Account no longer exists.")
    if not user.is_active:
        raise UnauthorizedException("This account has been disabled.")
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    try:
        return get_current_user(credentials=credentials, db=db)
    except UnauthorizedException:
        return None


def require_roles(*allowed_roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            from app.core.exceptions import ForbiddenException

            raise ForbiddenException("You do not have permission to perform this action.")
        return user

    return dependency


require_admin = require_roles("ADMIN")
require_customer = require_roles(UserRole_CUSTOMER)
require_worker = require_roles(UserRole_WORKER)
require_any_user = require_roles(UserRole_CUSTOMER, UserRole_WORKER, "ADMIN")
