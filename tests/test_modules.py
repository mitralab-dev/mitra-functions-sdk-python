import json

import httpx
import pytest

from mitra_functions_sdk import MitraClientConfig, MitraResponseError, ProxyInput, create_client


def function_execution_response() -> dict[str, object]:
    return {
        "id": "execution-1",
        "functionId": "function-1",
        "functionVersionId": "version-1",
        "status": "SUCCESS",
        "input": {},
        "output": {"ok": True},
        "errorMessage": None,
        "logs": None,
        "durationMs": 10,
        "startedAt": "2026-08-14T20:00:00Z",
        "finishedAt": "2026-08-14T20:00:01Z",
        "createdAt": "2026-08-14T20:00:00Z",
    }


def proxy_result() -> dict[str, object]:
    return {
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {"ok": True},
        "durationMs": 20,
        "executionId": "integration-execution-1",
    }


def omit_field(payload: dict[str, object], field: str) -> dict[str, object]:
    copy = dict(payload)
    copy.pop(field)
    return copy


def test_query_execution_uses_resolved_data_source() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"rows": [{"total": 2}], "durationMs": 7},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                data_source_id="ds-1",
                http_client=http_client,
            )
        )

        result = client.queries.execute("query/1", {"status": "active"})

    assert result["rows"] == [{"total": 2}]
    assert "affectedRows" not in result
    assert captured[0].url.raw_path == b"/data-manager/api/v1/custom-queries/query%2F1/execute"
    assert json.loads(captured[0].content) == {
        "dataSourceId": "ds-1",
        "parameters": {"status": "active"},
    }


@pytest.mark.parametrize("affected_rows", [None, 0, 2])
def test_query_execution_accepts_optional_affected_rows(affected_rows: int | None) -> None:
    response = {"rows": [], "affectedRows": affected_rows, "durationMs": 1}

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    ) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                data_source_id="ds-1",
                http_client=http_client,
            )
        )

        assert client.queries.execute("query-1") == response


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"rows": []},
        {"durationMs": 1},
        {"rows": [None], "durationMs": 1},
        {"rows": [], "durationMs": True},
        {"rows": [], "durationMs": 1.5},
        {"rows": [], "affectedRows": True, "durationMs": 1},
        {"rows": [], "affectedRows": "0", "durationMs": 1},
    ],
)
def test_query_execution_rejects_invalid_response_structure(response: object) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    ) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                data_source_id="ds-1",
                http_client=http_client,
            )
        )

        with pytest.raises(MitraResponseError):
            client.queries.execute("query-1")


def test_function_sync_async_status_and_cancel_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/cancel"):
            return httpx.Response(204)
        response = function_execution_response()
        response["status"] = (
            "PENDING" if request.headers.get("X-Invocation-Type") == "async" else "SUCCESS"
        )
        return httpx.Response(
            202 if request.headers.get("X-Invocation-Type") == "async" else 200,
            json=response,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                http_client=http_client,
            )
        )

        assert client.functions.execute("function/1", {"orderId": "1"})["status"] == "SUCCESS"
        assert client.functions.execute_async("function/1")["id"] == "execution-1"
        assert client.functions.get_execution("execution/1")["functionId"] == "function-1"
        assert client.functions.cancel_execution("execution/1") is None

    assert requests[0].headers["X-Invocation-Type"] == "sync"
    assert requests[0].url.raw_path == b"/functions/api/v1/functions/function%2F1/execute"
    assert json.loads(requests[0].content) == {"input": {"orderId": "1"}}
    assert requests[1].headers["X-Invocation-Type"] == "async"
    assert json.loads(requests[1].content) == {"input": {}}
    assert requests[2].url.raw_path == b"/functions/api/v1/executions/execution%2F1"
    assert requests[3].url.raw_path.endswith(b"/executions/execution%2F1/cancel")


def test_function_execution_accepts_nullable_fields_and_extra_fields() -> None:
    response = {
        **function_execution_response(),
        "status": "FUTURE_STATUS",
        "input": None,
        "output": None,
        "durationMs": None,
        "startedAt": None,
        "finishedAt": None,
        "futureField": True,
    }

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    ) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                http_client=http_client,
            )
        )

        assert client.functions.get_execution("execution-1") == response


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "functionId",
        "functionVersionId",
        "status",
        "input",
        "output",
        "errorMessage",
        "logs",
        "durationMs",
        "startedAt",
        "finishedAt",
        "createdAt",
    ],
)
def test_function_execution_rejects_missing_fields(field: str) -> None:
    response = omit_field(function_execution_response(), field)

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    ) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                http_client=http_client,
            )
        )

        with pytest.raises(MitraResponseError, match=field):
            client.functions.get_execution("execution-1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 1),
        ("functionId", None),
        ("functionVersionId", False),
        ("status", 1),
        ("input", []),
        ("output", "invalid"),
        ("errorMessage", {}),
        ("logs", []),
        ("durationMs", True),
        ("durationMs", 1.5),
        ("startedAt", 1),
        ("finishedAt", {}),
        ("createdAt", None),
    ],
)
def test_function_execution_rejects_invalid_field_types(field: str, value: object) -> None:
    response = function_execution_response()
    response[field] = value

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    ) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                http_client=http_client,
            )
        )

        with pytest.raises(MitraResponseError, match=field):
            client.functions.get_execution("execution-1")


def test_integration_resource_and_direct_execution_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=proxy_result())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                http_client=http_client,
            )
        )
        proxy_input: ProxyInput = {
            "method": "POST",
            "endpoint": "/orders",
            "body": {"id": "1"},
            "queryParams": {"limit": 10, "active": True},
        }

        assert client.integration.execute_resource("resource/1", {"limit": 10})["status"] == 200
        assert client.integration.execute("config/1", proxy_input)["body"] == {"ok": True}

    assert requests[0].url.raw_path == (b"/integration/api/v1/proxy/resources/resource%2F1/execute")
    assert json.loads(requests[0].content) == {"params": {"limit": 10}}
    assert requests[1].url.raw_path == (
        b"/integration/api/v1/proxy/template-configs/config%2F1/execute"
    )
    assert json.loads(requests[1].content) == {
        "method": "POST",
        "endpoint": "/orders",
        "body": {"id": "1"},
        "queryParams": {"limit": 10, "active": True},
        "source": "SDK",
    }


@pytest.mark.parametrize("field", ["status", "headers", "body", "durationMs", "executionId"])
def test_integration_rejects_missing_result_fields(field: str) -> None:
    response = omit_field(proxy_result(), field)

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    ) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                http_client=http_client,
            )
        )

        with pytest.raises(MitraResponseError, match=field):
            client.integration.execute_resource("resource-1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", True),
        ("status", 200.0),
        ("headers", {"content-type": 1}),
        ("durationMs", False),
        ("durationMs", 1.5),
        ("executionId", 1),
    ],
)
def test_integration_rejects_invalid_result_types(field: str, value: object) -> None:
    response = proxy_result()
    response[field] = value

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    ) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                http_client=http_client,
            )
        )

        with pytest.raises(MitraResponseError, match=field):
            client.integration.execute_resource("resource-1")


@pytest.mark.parametrize("body", [None, ["future", None], "text", 0, False])
def test_integration_accepts_any_result_body(body: object) -> None:
    response = {**proxy_result(), "body": body, "futureField": True}

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    ) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app-1",
                http_client=http_client,
            )
        )

        assert client.integration.execute_resource("resource-1") == response
