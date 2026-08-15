import json
import traceback

import httpx
import pytest

from mitra_functions_sdk import (
    MitraApiError,
    MitraClient,
    MitraClientConfig,
    MitraNetworkError,
    MitraResponseError,
    create_client,
)


def client_with(handler: httpx.MockTransport) -> tuple[MitraClient, httpx.Client]:
    http_client = httpx.Client(transport=handler)
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token="sensitive-token",
            app_id="app-1",
            http_client=http_client,
        )
    )
    return client, http_client


def serialize_exception(error: BaseException) -> str:
    return json.dumps(
        {
            "message": str(error),
            "repr": repr(error),
            "args": error.args,
            "vars": vars(error),
            "traceback": "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            ),
        },
        default=repr,
        sort_keys=True,
    )


@pytest.mark.parametrize(
    ("status", "code_field", "code"),
    [(404, "error_code", "NOT_FOUND"), (503, "code", "DOWN")],
)
def test_api_error_preserves_structured_fields_and_redacts_token(
    status: int,
    code_field: str,
    code: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "message": "failure sensitive-token",
                code_field: code,
                "details": {
                    "service": "data-manager",
                    "nested": {
                        "accessToken": "different-secret",
                        "debug": ["prefix sensitive-token suffix"],
                    },
                },
                "requestId": "request-1",
                "retryable": True,
            },
        )

    client, http_client = client_with(httpx.MockTransport(handler))

    with pytest.raises(MitraApiError) as caught:
        client.auth.me()

    error = caught.value
    assert error.status == status
    assert error.code == code
    assert error.details == {
        "service": "data-manager",
        "nested": {
            "accessToken": "[REDACTED]",
            "debug": ["prefix [REDACTED] suffix"],
        },
    }
    assert error.request_id == "request-1"
    assert error.retryable is True
    assert "sensitive-token" not in str(error)
    assert "sensitive-token" not in repr(error)
    http_client.close()


def test_api_error_uses_valid_alias_when_primary_field_is_invalid() -> None:
    client, http_client = client_with(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                404,
                json={
                    "message": "not found",
                    "error_code": None,
                    "code": "NOT_FOUND",
                    "request_id": 42,
                    "requestId": "request-1",
                },
            )
        )
    )

    with pytest.raises(MitraApiError) as caught:
        client.auth.me()

    assert caught.value.code == "NOT_FOUND"
    assert caught.value.request_id == "request-1"
    http_client.close()


def test_api_error_uses_request_id_header_and_safe_fallback_for_non_json() -> None:
    client, http_client = client_with(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                502,
                text="not-json sensitive-token",
                headers={"X-Request-Id": "header-request"},
            )
        )
    )

    with pytest.raises(MitraApiError) as caught:
        client.auth.me()

    error = caught.value
    assert str(error) == "Mitra API request failed with status 502"
    assert error.request_id == "header-request"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "sensitive-token" not in serialize_exception(error)
    http_client.close()


def test_api_error_redacts_token_from_request_id_header() -> None:
    client, http_client = client_with(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                json={"message": "failed"},
                headers={"X-Request-Id": "request-sensitive-token"},
            )
        )
    )

    with pytest.raises(MitraApiError) as caught:
        client.auth.me()

    assert caught.value.request_id == "request-[REDACTED]"
    assert "sensitive-token" not in repr(caught.value)
    http_client.close()


def test_api_error_redacts_exact_token_and_any_bearer_credential_everywhere() -> None:
    token = "runtime-access-credential"
    exposed_credentials = {
        "message": "upstream-message-credential",
        "code": "upstream-code-credential",
        "request": "upstream-request-credential",
        "key": "upstream-key-credential",
        "detail": "upstream-detail-credential",
        "authorization": "upstream-authorization-credential",
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={
                "message": f"upstream echoed Bearer {exposed_credentials['message']} and {token}",
                "code": f"Bearer {exposed_credentials['code']}",
                "requestId": f"Bearer {exposed_credentials['request']}",
                "details": {
                    "nested": {
                        f"Bearer {exposed_credentials['key']}": [
                            f"Bearer {exposed_credentials['detail']}",
                            token,
                        ],
                        "Authorization": f"Bearer {exposed_credentials['authorization']}",
                    }
                },
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token=token,
            app_id="app-1",
            http_client=http_client,
        )
    )

    with pytest.raises(MitraApiError) as caught:
        client.auth.me()

    error = caught.value
    serialized_details = json.dumps(error.details, sort_keys=True)
    serialized_exception = serialize_exception(error)
    assert str(error) == "upstream echoed Bearer [REDACTED] and [REDACTED]"
    assert error.code == "Bearer [REDACTED]"
    assert error.request_id == "Bearer [REDACTED]"
    assert error.details == {
        "nested": {
            "Bearer [REDACTED]": ["Bearer [REDACTED]", "[REDACTED]"],
            "Authorization": "[REDACTED]",
        }
    }
    for credential in (token, *exposed_credentials.values()):
        assert credential not in serialized_details
        assert credential not in serialized_exception
        assert credential not in str(error)
        assert credential not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    http_client.close()


def test_exact_token_redaction_cannot_disable_generic_bearer_redaction() -> None:
    upstream_credential = "upstream-bearer-credential"
    http_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                json={"message": f"Bearer {upstream_credential}"},
            )
        )
    )
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token="Bearer",
            app_id="app-1",
            http_client=http_client,
        )
    )

    with pytest.raises(MitraApiError) as caught:
        client.auth.me()

    serialized = serialize_exception(caught.value)
    assert upstream_credential not in serialized
    assert "Bearer" not in serialized
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    http_client.close()


def test_redirect_is_not_followed_even_when_injected_client_would_follow() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://other.test/replayed"})

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token="sensitive-token",
            app_id="app-1",
            http_client=http_client,
        )
    )

    with pytest.raises(MitraApiError) as caught:
        client.auth.me()

    assert caught.value.status == 307
    assert len(requests) == 1
    http_client.close()


def test_success_with_invalid_json_raises_response_error() -> None:
    body_secret = "upstream-json-credential"
    client, http_client = client_with(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                text=f"Bearer {body_secret} sensitive-token",
            )
        )
    )

    with pytest.raises(MitraResponseError, match="invalid JSON") as caught:
        client.auth.me()
    error = caught.value
    serialized = serialize_exception(error)
    assert error.code == "INVALID_RESPONSE"
    assert error.retryable is False
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "sensitive-token" not in serialized
    assert body_secret not in serialized
    http_client.close()


@pytest.mark.parametrize(("status", "operation"), [(200, "delete"), (202, "cancel")])
def test_non_204_empty_success_is_rejected_safely(status: int, operation: str) -> None:
    client, http_client = client_with(
        httpx.MockTransport(lambda _request: httpx.Response(status, content=b""))
    )

    with pytest.raises(MitraResponseError, match=f"empty response with status {status}") as caught:
        if operation == "delete":
            client.entities.table("Task").delete("record-1")
        else:
            client.functions.cancel_execution("execution-1")

    error = caught.value
    serialized = serialize_exception(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "sensitive-token" not in serialized
    http_client.close()


def test_non_204_json_null_is_not_treated_as_an_empty_success() -> None:
    client, http_client = client_with(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                content=b"null",
                headers={"Content-Type": "application/json"},
            )
        )
    )

    with pytest.raises(MitraResponseError, match="null JSON response") as caught:
        client.entities.table("Task").delete("record-1")

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    http_client.close()


@pytest.mark.parametrize(
    ("transport_error", "expected_code", "upstream_secret"),
    [
        (
            httpx.ReadTimeout("Bearer upstream-timeout-credential sensitive-token"),
            "REQUEST_TIMEOUT",
            "upstream-timeout-credential",
        ),
        (
            httpx.ConnectError("Bearer upstream-network-credential sensitive-token"),
            "NETWORK_ERROR",
            "upstream-network-credential",
        ),
    ],
)
def test_transport_errors_are_wrapped_without_secrets(
    transport_error: Exception,
    expected_code: str,
    upstream_secret: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise transport_error

    client, http_client = client_with(httpx.MockTransport(handler))

    with pytest.raises(MitraNetworkError) as caught:
        client.auth.me()

    error = caught.value
    serialized = serialize_exception(error)
    assert "sensitive-token" not in serialized
    assert upstream_secret not in serialized
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.code == expected_code
    assert error.retryable is True
    http_client.close()
