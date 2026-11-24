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


class UnauthorizedException(DomainException):
    """Raised for authentication or authorization failures (maps to 401)."""
    pass


class ForbiddenException(DomainException):
    """Raised when access is forbidden due to insufficient privileges (maps to 403)."""
    pass

