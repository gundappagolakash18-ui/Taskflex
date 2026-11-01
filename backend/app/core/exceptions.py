from enum import Enum


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_NOT_CONFIRMABLE = "TASK_NOT_CONFIRMABLE"
    TASK_NOT_CANCELLABLE = "TASK_NOT_CANCELLABLE"
    OFFER_NOT_AVAILABLE = "OFFER_NOT_AVAILABLE"
    AI_PARSE_FAILED = "AI_PARSE_FAILED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_TYPE_NOT_ALLOWED = "FILE_TYPE_NOT_ALLOWED"
    USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"
    OTP_INVALID = "OTP_INVALID"
    OTP_LOCKED = "OTP_LOCKED"
    PROOF_REQUIRED = "PROOF_REQUIRED"
    PROOF_LOCATION_MISSING = "PROOF_LOCATION_MISSING"
    PROOF_OUT_OF_RANGE = "PROOF_OUT_OF_RANGE"
    EXPENSE_LIMIT_EXCEEDED = "EXPENSE_LIMIT_EXCEEDED"
    CHAT_CLOSED = "CHAT_CLOSED"
    SHARE_LINK_EXPIRED = "SHARE_LINK_EXPIRED"
    BUDGET_BELOW_MINIMUM_FLOOR = "BUDGET_BELOW_MINIMUM_FLOOR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppException(Exception):
    status_code = 400
    code = ErrorCode.CONFLICT
    message = "Request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict | None = None,
        code: ErrorCode | None = None,
        status_code: int | None = None,
    ):
        self.message = message or self.message
        self.details = details or {}
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        super().__init__(self.message)


class UnauthorizedException(AppException):
    status_code = 401
    code = ErrorCode.UNAUTHORIZED
    message = "Authentication required."


class ForbiddenException(AppException):
    status_code = 403
    code = ErrorCode.FORBIDDEN
    message = "You do not have permission to perform this action."


class NotFoundException(AppException):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    message = "Resource was not found."


class ConflictException(AppException):
    status_code = 409
    code = ErrorCode.CONFLICT
    message = "Resource already exists."


class InvalidTransitionException(AppException):
    status_code = 422
    code = ErrorCode.INVALID_TRANSITION
    message = "This action is not allowed in the current state."


class RateLimitException(AppException):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    message = "Too many requests. Please slow down."


class AIParseException(AppException):
    status_code = 502
    code = ErrorCode.AI_PARSE_FAILED
    message = "The AI service could not process this request."


class OtpInvalidException(AppException):
    status_code = 422
    code = ErrorCode.OTP_INVALID
    message = "The verification code is incorrect."


class OtpLockedException(AppException):
    status_code = 423
    code = ErrorCode.OTP_LOCKED
    message = "Too many wrong attempts — this verification code is locked for now."


class BudgetBelowFloorException(AppException):
    status_code = 422
    code = ErrorCode.BUDGET_BELOW_MINIMUM_FLOOR
    message = "Your budget is below the minimum fare for this task."


class ChatClosedException(AppException):
    status_code = 409
    code = ErrorCode.CHAT_CLOSED
    message = "This conversation is closed and can no longer be read or written."


class ShareLinkExpiredException(AppException):
    status_code = 410
    code = ErrorCode.SHARE_LINK_EXPIRED
    message = "This tracking link has expired."
