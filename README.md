# Mitra Functions SDK for Python

Synchronous Python SDK for code running inside Mitra Server Functions. It exposes the application-scoped capabilities granted to the function token without implementing browser login, token refresh, or privileged control-plane operations.

## Requirements

- Python 3.11 or later
- A short-lived Mitra access token with the resources required by the operations you call

## Installation

```bash
pip install mitra-functions-sdk
```

## Runtime integration status

The SDK is ready for the target runtime contract, but Functions and Sandbox do not inject it yet. The pending integration must deliver the platform access token separately from user-defined function secrets and install a pinned SDK version in the runtime template.

Until then, the variables below must be supplied explicitly in local or controlled execution environments. Once the runtime integration is available, create one client for the invocation and close it when the handler finishes:

```python
from mitra_functions_sdk import create_client


def handler(event: dict[str, object], context: dict[str, object]) -> dict[str, object]:
    with create_client() as mitra:
        orders = mitra.entities.table("Order")
        created = orders.create(
            {
                "customerId": event["customerId"],
                "status": "pending",
            }
        )

        execution = mitra.functions.execute(
            "send-confirmation-function-id",
            {"orderId": created["id"]},
        )
        return {"order": created, "notification": execution}
```

The Python function runner is synchronous, so this SDK deliberately provides a single synchronous API backed by `httpx.Client`.

## Contract parity

The test suite consumes the canonical SDK-PARITY-001 corpus maintained by
`@mitralab.io/sdk-core`. This repository vendors the exact fixture bytes with a
source repository, full Git commit, version, and SHA-256 digest so normal tests
stay deterministic and offline. Version 0.1.0 is pinned to sdk-core commit
`b513454d0d1f7344a4656cd9c0e1e32530c5ea90`.

Verify the vendored snapshot on its own:

```bash
python scripts/check_contract_fixture.py
```

When both worktrees are available, reproduce the cross-repository equivalence
gate by passing the canonical file:

```bash
python scripts/check_contract_fixture.py \
  --canonical ../mitra-core-sdk/contracts/v0.1.0/sdk-parity.json
```

The path is illustrative and may be absolute. No workspace path is stored in
the package. Continuous integration and release gates download the canonical
file from the public repository at that exact commit and compare the bytes.
They fail even when the vendored file and its local digest are changed together.

The corpus drives all 16 success cases, every response-validation case, and
every concrete HTTP-adapter case through the real synchronous SDK modules and
`HttpTransport` with an `httpx.MockTransport` boundary.

## Configuration

`create_client()` reads the target runtime contract:

| Variable | Required | Description |
|---|---|---|
| `MITRA_API_URL` | yes | Base URL of the Mitra API gateway. |
| `MITRA_PLATFORM_ACCESS_TOKEN` | yes | Short-lived bearer token for the current function invocation. |
| `MITRA_APP_ID` | yes | Application scope propagated as `X-App-Id`. |
| `MITRA_DATA_SOURCE_ID` | no | Data source used by custom queries. If absent, call `init()`. |

For local development or tests, pass explicit configuration:

```python
from mitra_functions_sdk import MitraClientConfig, create_client

mitra = create_client(
    MitraClientConfig(
        api_url="http://localhost:8000",
        access_token="short-lived-token",
        app_id="app-id",
        timeout_seconds=10,
    )
)
```

The access token and injected HTTP client are excluded from the configuration representation. The SDK does not log credentials, refresh tokens, read browser storage, or retry requests automatically.

## Initialization

Entity CRUD is scoped by the token and `X-App-Id`, so it is available immediately. Custom queries also require a data source ID. Supply `MITRA_DATA_SOURCE_ID` or resolve it once through Code Studio:

```python
with create_client() as mitra:
    mitra.init()
    result = mitra.queries.execute("5df41c69-2a74-4db6-9cca-4af2b473941f", {"limit": 20})
```

Calling `init()` is idempotent. It requests `GET /code-studio/api/v1/apps/{appId}/info` only when no data source was configured.

The current release targets the Data Manager `main` custom-query request and
sends both `dataSourceId` and `parameters`. The recorded `alpha` contract accepts
the same request body but resolves the data source from the authenticated app,
ignoring the body field. The SDK never retries the POST with another shape. A
future parameters-only migration still requires the coordinated server,
canonical-corpus, deprecation, and SDK gates recorded in SDK-PARITY-001.

## API

### Current user

Requires `PROFILE_READ`.

```python
current_user = mitra.auth.me()
```

### Entities

Requires `ENTITY_READ`, `ENTITY_WRITE`, or `ENTITY_DELETE`, depending on the operation.

```python
tasks = mitra.entities.table("Task")

page = tasks.list(sort="-created_at", limit=20, fields=["id", "status"])
pending = tasks.filter({"status": "pending"}, limit=10)
task = tasks.get("task-id")
created = tasks.create({"title": "Prepare release", "status": "pending"})
created_many = tasks.bulk_create([{"title": "A"}, {"title": "B"}])
updated = tasks.update("task-id", {"status": "done"})
tasks.delete("task-id")
deleted = tasks.delete_many({"status": "archived"})
```

`delete_many()` rejects an empty filter locally to preserve the Data Manager safety contract. Its result preserves the API envelope: `{"deleted": number}`.

### Custom queries

Requires `QUERY_EXECUTE` and a resolved data source ID.

```python
result = mitra.queries.execute(
    "5df41c69-2a74-4db6-9cca-4af2b473941f",
    {"status": "active"},
)
```

### Server Functions

Requires `FUNCTION_EXECUTE`. Reading an execution requires `FUNCTION_EXECUTION_READ`.

```python
# Blocks until the execution reaches a terminal state.
terminal = mitra.functions.execute("function-id", {"orderId": "123"})

# Returns the accepted execution without waiting for completion.
accepted = mitra.functions.execute_async("function-id", {"orderId": "123"})
current = mitra.functions.get_execution(accepted["id"])
mitra.functions.cancel_execution(accepted["id"])
```

`execute()` always sends `X-Invocation-Type: sync`. `execute_async()` always sends `X-Invocation-Type: async`, avoiding dependence on the service default.

### Integrations

Requires `INTEGRATION_EXECUTE`.

```python
resource_result = mitra.integration.execute_resource(
    "resource-id",
    {"customerId": "123"},
)

proxy_result = mitra.integration.execute(
    "template-config-id",
    {
        "method": "POST",
        "endpoint": "/orders",
        "body": {"customerId": "123"},
    },
)
```

Direct integration execution always sets `source` to `SDK`.

## Errors

- `MitraConfigError`: missing or invalid local configuration.
- `MitraNetworkError`: timeout or transport failure before a response.
- `MitraResponseError`: malformed successful response.
- `MitraApiError`: non-success HTTP response, with normalized `status`, `code`, `details`, `request_id`, and `retryable` metadata.

The local errors use the same normalized envelope as API errors.
`MitraNetworkError` exposes `status=0`, `details=None`, `request_id=None`, and
`retryable=True`. `MitraResponseError` exposes `status=200`,
`code="INVALID_RESPONSE"`, `details=None`, `request_id=None`, and
`retryable=False` for the successful-response validation path.

When an API error omits `retryable`, the HTTP adapter classifies 4xx responses
as `False` and 5xx responses as `True`. This is diagnostic classification only.
The SDK still makes one attempt and never retries a request automatically.

The JavaScript package represents local timeout, network, and invalid-response failures as `MitraApiError` with codes `REQUEST_TIMEOUT`, `NETWORK_ERROR`, or `INVALID_RESPONSE`. These map to Python `MitraNetworkError` and `MitraResponseError`. API responses use `MitraApiError` in both packages.

The SDK does not include the access token in its error messages or structured details.

## Development

```bash
python -m pip install -e '.[test]'
ruff format --check .
ruff check .
mypy
pytest
python -m build
python -m twine check dist/*
```

The continuous integration workflow runs linting, strict type checking, and tests with at least 80 percent coverage on Python 3.11 and 3.12. Distribution metadata checks and the isolated wheel import smoke run on Python 3.12.

## Scope

Version 0.1.0 intentionally excludes browser authentication, token refresh, API keys, messaging, workspace administration, project administration, raw SQL, schema management, and legacy SDK global configuration.
