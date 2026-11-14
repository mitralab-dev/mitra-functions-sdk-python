from __future__ import annotations


class MitraSdkError(Exception):
    """Base exception for SDK configuration, transport, and response errors."""


class MitraConfigError(MitraSdkError, ValueError):
    """Raised when the SDK configuration is missing or invalid."""


class MitraNetworkError(MitraSdkError):
    """Raised when a request cannot reach the Mitra API."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.status = 0
        self.code = code
        self.details = None
        self.request_id = None
        self.retryable = True


class MitraResponseError(MitraSdkError):
    """Raised when a successful API response is malformed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.status = 200
        self.code = "INVALID_RESPONSE"
        self.details = None
        self.request_id = None
        self.retryable = False


class MitraFileTransferError(MitraSdkError):
    """Raised when an upload or download fails after the API already knows the file."""

    def __init__(
        self,
        message: str,
        *,
        file_id: str,
        step: str,
        status: int | None = None,
        cleaned_up: bool = False,
    ) -> None:
        super().__init__(message)
        self.file_id = file_id
        self.step = step
        self.status = status
        self.cleaned_up = cleaned_up


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
