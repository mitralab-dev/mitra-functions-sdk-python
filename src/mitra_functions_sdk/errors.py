from __future__ import annotations


class MitraSdkError(Exception):
    """Base exception for SDK configuration, transport, and response errors."""


class MitraConfigError(MitraSdkError, ValueError):
    """Raised when the SDK configuration is missing or invalid."""


class MitraNetworkError(MitraSdkError):
    """Raised when a request cannot reach the Mitra API."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = True


class MitraResponseError(MitraSdkError):
    """Raised when a successful API response is malformed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "INVALID_RESPONSE"
        self.retryable = False


class MitraApiError(MitraSdkError):
    """Error returned by a Mitra API service."""

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: str | None = None,
        details: object | None = None,
        request_id: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details
        self.request_id = request_id
        self.retryable = retryable
