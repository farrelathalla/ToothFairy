"""Framework-agnostic service errors. Routers map these to HTTP responses."""


class ServiceError(Exception):
    """Base class for domain errors raised by services."""


class EmailExists(ServiceError):
    """An account with this email already exists."""


class UserNotFound(ServiceError):
    """No user with the given id."""


class ValidationError(ServiceError):
    """Invalid input that pydantic didn't already reject."""


class CaseNotFound(ServiceError):
    """No case with the given id owned by this doctor."""


class InvalidImage(ServiceError):
    """Uploaded file is not an acceptable image (type/size/empty)."""
