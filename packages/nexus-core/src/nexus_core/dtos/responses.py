from typing import Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Contrato canónico de respuesta para APIs de Nexus."""
    success: bool = True
    data: T | None = None
    message: str | None = None


class ErrorResponse(BaseModel):
    """Contrato estándar para respuestas de error."""
    success: bool = False
    detail: str
    error_code: str | None = None

