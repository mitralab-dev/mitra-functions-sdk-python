from __future__ import annotations

import re
from collections.abc import Mapping
from typing import cast

import httpx

from .config import MitraClientConfig
from .errors import MitraApiError, MitraNetworkError, MitraResponseError

QueryParam = str | int | float | bool
_NO_BODY = object()
_BEARER_CREDENTIAL = re.compile(r"\bbearer\s+\S+", re.IGNORECASE)


class HttpTransport:
    def __init__(self, config: MitraClientConfig) -> None:
        self._access_token = config.access_token
        self._app_id = config.app_id
        self._timeout_seconds = config.timeout_seconds
        self._owns_client = config.http_client is None
        self._client = config.http_client or httpx.Client()
        self._base_urls = {
            service: f"{config.api_url}/{service}"
            for service in ("iam", "data-manager", "functions", "integration", "code-studio")
        }

    def request(
        self,
        method: str,
        service: str,
        path: str,
        *,
        params: Mapping[str, QueryParam] | None = None,
        json_body: object = _NO_BODY,
        headers: Mapping[str, str] | None = None,
    ) -> object | None:
        request_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "X-App-Id": self._app_id,
        }
        if headers:
            request_headers.update(headers)

        url = f"{self._base_urls[service]}{path}"
        response: httpx.Response | None = None
        network_error_code: str | None = None
        try:
            if json_body is _NO_BODY:
                response = self._client.request(
                    method,
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=self._timeout_seconds,
                    follow_redirects=False,
                )
            else:
                response = self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=request_headers,
                    timeout=self._timeout_seconds,
                    follow_redirects=False,
                )
        except httpx.TimeoutException:
            network_error_code = "REQUEST_TIMEOUT"
        except httpx.RequestError:
            network_error_code = "NETWORK_ERROR"

        if network_error_code == "REQUEST_TIMEOUT":
            raise MitraNetworkError("Mitra request timed out", code=network_error_code)
        if network_error_code is not None or response is None:
            raise MitraNetworkError(
                "Mitra request failed before receiving a response",
                code="NETWORK_ERROR",
            )

        if not response.is_success:
            raise self._api_error(response)
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        if not response.content:
            raise MitraResponseError(
                f"Mitra API returned an empty response with status {response.status_code}"
            )

        payload: object | None = None
        invalid_json = False
        try:
            payload = response.json()
        except ValueError:
            invalid_json = True

        if invalid_json:
            raise MitraResponseError(
                f"Mitra API returned invalid JSON with status {response.status_code}"
            )
        if payload is None:
            raise MitraResponseError(
                f"Mitra API returned a null JSON response with status {response.status_code}"
            )
        return payload

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _api_error(self, response: httpx.Response) -> MitraApiError:
        try:
            raw_payload: object = response.json()
        except ValueError:
            raw_payload = None

        payload = _as_string_object_mapping(raw_payload)
        message_value = payload.get("message")
        message = (
            message_value
            if isinstance(message_value, str) and message_value.strip()
            else f"Mitra API request failed with status {response.status_code}"
        )
        message = _redact_string(message, self._access_token)

        error_code_value = payload.get("error_code")
        code_value = error_code_value if isinstance(error_code_value, str) else payload.get("code")
        code = (
            _redact_string(code_value, self._access_token) if isinstance(code_value, str) else None
        )
        snake_request_id = payload.get("request_id")
        request_id_value = (
            snake_request_id if isinstance(snake_request_id, str) else payload.get("requestId")
        )
        request_id = (
            _redact_string(request_id_value, self._access_token)
            if isinstance(request_id_value, str)
            else None
        )
        if request_id is None:
            header_request_id = response.headers.get("X-Request-Id")
            request_id = (
                _redact_string(header_request_id, self._access_token)
                if header_request_id is not None
                else None
            )
        retryable_value = payload.get("retryable")
        retryable = (
            retryable_value
            if isinstance(retryable_value, bool)
            else response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR
        )

        return MitraApiError(
            message,
            status=response.status_code,
            code=code,
            details=_redact(payload.get("details"), self._access_token),
            request_id=request_id,
            retryable=retryable,
        )


def _as_string_object_mapping(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        return {}
    return cast(dict[str, object], payload)


def _redact(value: object, access_token: str, key: str | None = None) -> object:
    if key is not None and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return _redact_string(value, access_token)
    if isinstance(value, list):
        return [_redact(item, access_token) for item in value]
    if isinstance(value, dict):
        return {
            _redact_string(str(item_key), access_token): _redact(
                item_value,
                access_token,
                str(item_key),
            )
            for item_key, item_value in value.items()
        }
    return value


def _redact_string(value: str, access_token: str) -> str:
    without_bearer_credentials = _BEARER_CREDENTIAL.sub("Bearer [REDACTED]", value)
    return without_bearer_credentials.replace(access_token, "[REDACTED]")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(
        marker in normalized
        for marker in ("token", "authorization", "password", "secret", "api_key", "apikey")
    )
