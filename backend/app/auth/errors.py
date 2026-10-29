"""Framework-free service errors. Each carries the HTTP status the API layer should return."""


class ServiceError(Exception):
    status_code = 400
    headers: dict[str, str] | None = None

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class InvalidCredentials(ServiceError):
    status_code = 401


class InvalidToken(ServiceError):
    status_code = 401


class AccountLocked(ServiceError):
    status_code = 423


class AccountDisabled(ServiceError):
    status_code = 403


class Forbidden(ServiceError):
    status_code = 403


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409


class ValidationFailed(ServiceError):
    status_code = 422
