class DomainException(Exception):
    """Base exception for all domain logic."""
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ResourceNotFoundException(DomainException):
    """Raised when a requested resource is not found (maps to 404)."""
    pass


class BusinessRuleViolationException(DomainException):
    """Raised when a business rule is violated (maps to 409)."""
    pass


class InvalidInputException(DomainException):
    """Raised when input is well-formed but rejected by a domain/provider rule (maps to 422)."""
    pass


class ServiceUnavailableException(DomainException):
    """Raised when a required downstream provider fails unexpectedly (maps to 503)."""
    pass


class UnauthorizedException(DomainException):
    """Raised for authentication or authorization failures (maps to 401)."""
    pass


class ForbiddenException(DomainException):
    """Raised when access is forbidden due to insufficient privileges (maps to 403)."""
    pass

