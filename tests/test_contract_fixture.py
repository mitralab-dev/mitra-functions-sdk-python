from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import cast

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
from mitra_functions_sdk.models import ProxyInput

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST_PATH = FIXTURES / "sdk-parity-v0.1.0.manifest.json"
VERIFY_SCRIPT = Path(__file__).parents[1] / "scripts" / "check_contract_fixture.py"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
SNAPSHOT = FIXTURES / cast(str, MANIFEST["file"])
CONTRACT = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

OPERATIONS = [
    "auth.me",
    "entities.list",
    "entities.filter",
    "entities.get",
    "entities.create",
    "entities.bulkCreate",
    "entities.update",
    "entities.delete",
    "entities.deleteMany",
    "queries.execute",
    "functions.execute",
    "functions.executeAsync",
    "functions.getExecution",
    "functions.cancelExecution",
    "integration.execute",
    "integration.executeResource",
]

Case = dict[str, object]
ContractError = MitraApiError | MitraNetworkError | MitraResponseError


def as_object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return cast(dict[str, object], value)


def as_object_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return cast(list[dict[str, object]], value)


def as_string(value: object) -> str:
    assert isinstance(value, str)
    return value


def service_path(request: dict[str, object]) -> str:
    service = {
        "auth": "iam",
        "dataManager": "data-manager",
        "functions": "functions",
        "integration": "integration",
    }[as_string(request["service"])]
    return f"/{service}{as_string(request['path'])}"


def client_for(test_case: Case) -> tuple[MitraClient, httpx.Client, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        failure = test_case.get("failure")
        if isinstance(failure, dict) and failure.get("type") == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)

        response = as_object(test_case["response"])
        status = cast(int, response["status"])
        if response.get("empty") is True:
            return httpx.Response(status, content=b"")
        return httpx.Response(status, json=response["body"])

    input_data = as_object(test_case["input"])
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token="fixture-token",
            app_id="app-1",
            data_source_id=cast(str | None, input_data.get("dataSourceId")),
            timeout_seconds=0.01,
            http_client=http_client,
        )
    )
    return client, http_client, requests


def table_options(input_data: Case) -> Case:
    options = input_data.get("options")
    return as_object(options) if options is not None else input_data


def execute_case(test_case: Case, client: MitraClient) -> object:
    operation = as_string(test_case["operation"])
    input_data = as_object(test_case["input"])

    if operation == "auth.me":
        return client.auth.me()

    if operation.startswith("entities."):
        table = client.entities.table(as_string(input_data["table"]))
        options = table_options(input_data)
        if operation == "entities.list":
            return table.list(
                sort=cast(str | None, options.get("sort")),
                limit=cast(int | None, options.get("limit")),
                skip=cast(int | None, options.get("skip")),
                fields=cast(list[str] | None, options.get("fields")),
            )
        if operation == "entities.filter":
            return table.filter(
                as_object(input_data["query"]),
                sort=cast(str | None, options.get("sort")),
                limit=cast(int | None, options.get("limit")),
                skip=cast(int | None, options.get("skip")),
                fields=cast(list[str] | None, options.get("fields")),
            )
        if operation == "entities.get":
            return table.get(as_string(input_data["id"]))
        if operation == "entities.create":
            return table.create(as_object(input_data["data"]))
        if operation == "entities.bulkCreate":
            return table.bulk_create(as_object_list(input_data["data"]))
        if operation == "entities.update":
            return table.update(as_string(input_data["id"]), as_object(input_data["data"]))
        if operation == "entities.delete":
            return table.delete(as_string(input_data["id"]))
        if operation == "entities.deleteMany":
            return table.delete_many(as_object(input_data["query"]))

    if operation == "queries.execute":
        return client.queries.execute(
            as_string(input_data["id"]),
            as_object(input_data["parameters"]),
        )
    if operation == "functions.execute":
        return client.functions.execute(
            as_string(input_data["id"]),
            as_object(input_data["body"]),
        )
    if operation == "functions.executeAsync":
        return client.functions.execute_async(
            as_string(input_data["id"]),
            as_object(input_data["body"]),
        )
    if operation == "functions.getExecution":
        return client.functions.get_execution(as_string(input_data["id"]))
    if operation == "functions.cancelExecution":
        return client.functions.cancel_execution(as_string(input_data["id"]))
    if operation == "integration.execute":
        return client.integration.execute(
            as_string(input_data["id"]),
            cast(ProxyInput, as_object(input_data["proxyRequest"])),
        )
    if operation == "integration.executeResource":
        return client.integration.execute_resource(
            as_string(input_data["id"]),
            as_object(input_data["parameters"]),
        )
    raise AssertionError(f"Unsupported executable fixture operation {operation}")


def assert_request(test_case: Case, requests: list[httpx.Request]) -> None:
    assert len(requests) == 1
    actual = requests[0]
    expected = as_object(test_case["request"])

    assert actual.method == expected["method"]
    assert actual.url.raw_path.split(b"?", 1)[0].decode() == service_path(expected)
    assert actual.headers["Authorization"] == "Bearer fixture-token"
    assert actual.headers["X-App-Id"] == "app-1"

    expected_params = {
        key: str(value) for key, value in as_object(expected.get("params", {})).items()
    }
    assert dict(actual.url.params) == expected_params
    if "body" in expected:
        assert json.loads(actual.content) == expected["body"]
    else:
        assert actual.content == b""
    for key, value in as_object(expected.get("headers", {})).items():
        assert actual.headers[key] == value


def assert_contract_error(error: ContractError, expected: Case) -> None:
    assert error.status == expected["status"]
    assert error.code == expected["code"]
    assert str(error) == expected["message"]
    assert error.details == expected["details"]
    assert error.request_id == expected["requestId"]
    assert error.retryable == expected["retryable"]


def test_snapshot_identity_source_and_digest_are_pinned() -> None:
    digest = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    source = as_object(MANIFEST["source"])

    assert MANIFEST["contract"] == "SDK-PARITY-001"
    assert MANIFEST["version"] == CONTRACT["version"] == "0.1.0"
    assert source == {
        "repository": "https://github.com/mitralab-dev/mitra-core-sdk",
        "commit": "b513454d0d1f7344a4656cd9c0e1e32530c5ea90",
        "path": "contracts/v0.1.0/sdk-parity.json",
    }
    assert (
        digest
        == MANIFEST["sha256"]
        == ("600be3688cea7cfef16a8cf347516e87949b8e4151efb2c4136a2345557dde70")
    )


def test_canonical_comparison_rejects_vendor_and_digest_mutated_together(tmp_path: Path) -> None:
    mutated_snapshot = tmp_path / "sdk-parity-v0.1.0.json"
    mutated = dict(CONTRACT)
    mutated["description"] = "mutated together with the manifest digest"
    mutated_snapshot.write_text(json.dumps(mutated), encoding="utf-8")

    mutated_manifest = dict(MANIFEST)
    mutated_manifest["sha256"] = hashlib.sha256(mutated_snapshot.read_bytes()).hexdigest()
    mutated_manifest_path = tmp_path / "sdk-parity-v0.1.0.manifest.json"
    mutated_manifest_path.write_text(json.dumps(mutated_manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_SCRIPT),
            "--manifest",
            str(mutated_manifest_path),
            "--canonical",
            str(SNAPSHOT),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "differs from the supplied sdk-core canonical fixture" in result.stderr


def test_consumer_requirements_match_the_exact_python_gate() -> None:
    requirements = as_object(CONTRACT["consumerRequirements"])

    assert as_object(requirements["mitra-functions-sdk"]) == {
        "successCases": "all",
        "responseValidationCases": "all",
        "httpAdapterCases": "all",
    }
    assert len(as_object_list(CONTRACT["cases"])) == 16
    assert len(as_object_list(CONTRACT["responseValidationCases"])) == 1
    assert len(as_object_list(CONTRACT["httpAdapterCases"])) == 3


def test_matrix_covers_the_complete_mcp_javascript_python_mapping() -> None:
    matrix = as_object_list(CONTRACT["matrix"])

    assert [row["operation"] for row in matrix] == OPERATIONS
    for row in matrix:
        assert as_string(row["javascript"])
        assert as_string(row["python"])
        assert as_string(row["endpoint"])
        if row["mcpTransportParity"] == "sdk-only":
            assert row["mcpTool"] is None
        else:
            assert as_string(row["mcpTool"])


@pytest.mark.parametrize(
    "test_case", as_object_list(CONTRACT["cases"]), ids=lambda case: case["id"]
)
def test_all_canonical_success_cases(test_case: Case) -> None:
    client, http_client, requests = client_for(test_case)
    try:
        assert execute_case(test_case, client) == test_case.get("expectedResult")
        assert_request(test_case, requests)
    finally:
        http_client.close()


@pytest.mark.parametrize(
    "test_case",
    as_object_list(CONTRACT["responseValidationCases"]),
    ids=lambda case: case["id"],
)
def test_all_canonical_response_validation_cases(test_case: Case) -> None:
    expected = as_object(test_case["expectedError"])
    client, http_client, requests = client_for(test_case)
    try:
        with pytest.raises(MitraResponseError) as caught:
            execute_case(test_case, client)

        assert_contract_error(cast(ContractError, caught.value), expected)
        assert_request(test_case, requests)
    finally:
        http_client.close()


@pytest.mark.parametrize(
    "test_case",
    as_object_list(CONTRACT["httpAdapterCases"]),
    ids=lambda case: case["id"],
)
def test_all_canonical_http_adapter_cases(test_case: Case) -> None:
    expected = as_object(test_case["expectedError"])
    error_type = MitraNetworkError if expected["type"] == "network" else MitraApiError
    client, http_client, requests = client_for(test_case)
    try:
        with pytest.raises(error_type) as caught:
            execute_case(test_case, client)

        assert_contract_error(cast(ContractError, caught.value), expected)
        assert_request(test_case, requests)
    finally:
        http_client.close()


def test_custom_query_transition_keeps_the_first_release_block_open() -> None:
    transition = as_object(CONTRACT["customQueryTransition"])
    main = as_object(transition["main"])
    alpha = as_object(transition["alpha"])
    query_case = next(
        case
        for case in as_object_list(CONTRACT["cases"])
        if case["id"] == "queries.execute.success"
    )

    assert transition["currentSdkTarget"] == "main"
    assert transition["sharedRequestBody"] == as_object(query_case["request"])["body"]
    assert main["acceptsSharedRequestBody"] is True
    assert main["dataSourceIdTransportBehavior"] == "consumed"
    assert alpha["acceptsSharedRequestBody"] is True
    assert alpha["dataSourceIdTransportBehavior"] == "ignored"
    assert alpha["dataSourceResolution"] == "authenticated-app"
    assert as_string(alpha["semanticCompatibility"])
    assert transition["singlePayloadTransportCompatibility"] is True
    assert transition["automaticFallbackAllowed"] is False
    assert as_string(transition["automaticFallbackReason"])
    assert cast(list[str], transition["removeDataSourceIdGate"])
