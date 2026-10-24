"""Common API schemas and standard error envelopes."""

from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """Authoritative API error structure per TechSpec Section 11 & Appendix A."""
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Safe, user-facing error message (no secrets/paths)")
    retryable: bool = Field(default=False, description="Whether the client/worker may retry")
    request_id: str = Field(..., description="Correlation request ID for tracking")


class ErrorResponse(BaseModel):
    """Standard error response envelope."""
    error: ErrorDetail


class StatusResponse(BaseModel):
    """Generic operation status response."""
    status: str
    message: Optional[str] = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated collection response."""
    items: List[T]
    total: int
    limit: int
    offset: int
