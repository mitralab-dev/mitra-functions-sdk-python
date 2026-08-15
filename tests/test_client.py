import json

import httpx
import pytest

from mitra_functions_sdk import (
    MitraClientConfig,
    MitraConfigError,
    MitraResponseError,
    create_client,
)


def config(http_client: httpx.Client, *, data_source_id: str | None = None) -> MitraClientConfig:
    return MitraClientConfig(
        api_url="https://api.mitra.test/root",
        access_token="test-token",
        app_id="app-1",
        data_source_id=data_source_id,
        timeout_seconds=3,
        http_client=http_client,
    )


def request_json(request: httpx.Request) -> object:
    return json.loads(request.content)


def current_user_response() -> dict[str, object]:
    return {
        "id": "user-1",
        "tenant": {
            "id": "tenant-1",
            "shortId": "AAAAAAAAAAAAAAAAAAAAEA",
            "legacyId": None,
            "slug": "acme",
            "plan": {"id": "plan-1", "name": "Free"},
            "name": "Acme",
            "description": None,
            "hexColor": None,
            "icon": None,
            "infraStatus": "ACTIVE",
            "active": True,
        },
        "name": "Ada",
        "email": "ada@example.com",
        "imageUrl": None,
        "onboardingCompleted": True,
    }


def omit_field(payload: dict[str, object], field: str) -> dict[str, object]:
    copy = dict(payload)
    copy.pop(field)
    return copy


def test_init_resolves_data_source_once_with_runtime_headers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"dataSourceId": "ds-1", "allowSignup": False})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = create_client(config(http_client))

        assert client.init() is None
        assert client.init() is None

    assert client.data_source_id == "ds-1"
    assert len(requests) == 1
    assert str(requests[0].url) == (
        "https://api.mitra.test/root/code-studio/api/v1/apps/app-1/info"
    )
    assert requests[0].headers["Authorization"] == "Bearer test-token"
    assert requests[0].headers["X-App-Id"] == "app-1"
    assert requests[0].headers["Accept"] == "application/json"
    assert requests[0].extensions["timeout"] == {
        "connect": 3,
        "read": 3,
        "write": 3,
        "pool": 3,
    }


def test_init_url_encodes_app_id() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"dataSourceId": "ds-1"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="token",
                app_id="app/1",
                http_client=http_client,
            )
        )

        client.init()

    assert requests[0].url.raw_path == b"/code-studio/api/v1/apps/app%2F1/info"


def test_init_is_noop_when_data_source_is_configured() -> None:
    def unexpected(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("init must not make a request")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as http_client:
        client = create_client(config(http_client, data_source_id="ds-1"))

        client.init()

    assert client.data_source_id == "ds-1"


@pytest.mark.parametrize("payload", [{}, {"dataSourceId": ""}, {"dataSourceId": 12}, []])
def test_init_rejects_app_info_without_valid_data_source(payload: object) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as http_client:
        client = create_client(config(http_client))

        with pytest.raises(MitraResponseError, match="dataSourceId|JSON object"):
            client.init()


def test_entities_do_not_require_data_source_but_queries_do() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/root/data-manager/api/v1/tables/Task/records"
        return httpx.Response(200, json={"data": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = create_client(config(http_client))

        assert client.entities.table("Task").list() == []
        with pytest.raises(MitraConfigError, match="client.init"):
            client.queries.execute("query-1")


def test_auth_me_returns_current_cloud_profile_without_dropping_extra_fields() -> None:
    profile = {**current_user_response(), "futureField": "preserved"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/root/iam/api/v1/auth/me"
        return httpx.Response(200, json=profile)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = create_client(config(http_client))

        assert client.auth.me() == profile


@pytest.mark.parametrize(
    "field",
    ["id", "tenant", "name", "email", "imageUrl", "onboardingCompleted"],
)
def test_auth_me_rejects_missing_user_fields(field: str) -> None:
    profile = omit_field(current_user_response(), field)

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=profile))
    ) as http_client:
        client = create_client(config(http_client))

        with pytest.raises(MitraResponseError, match=field):
            client.auth.me()


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "shortId",
        "legacyId",
        "slug",
        "plan",
        "name",
        "description",
        "hexColor",
        "icon",
        "infraStatus",
        "active",
    ],
)
def test_auth_me_rejects_missing_tenant_fields(field: str) -> None:
    profile = current_user_response()
    tenant = dict(profile["tenant"])  # type: ignore[arg-type]
    tenant.pop(field)
    profile["tenant"] = tenant

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=profile))
    ) as http_client:
        client = create_client(config(http_client))

        with pytest.raises(MitraResponseError, match=field):
            client.auth.me()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 1),
        ("name", None),
        ("email", False),
        ("imageUrl", 1),
        ("onboardingCompleted", 1),
    ],
)
def test_auth_me_rejects_invalid_user_field_types(field: str, value: object) -> None:
    profile = current_user_response()
    profile[field] = value

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=profile))
    ) as http_client:
        client = create_client(config(http_client))

        with pytest.raises(MitraResponseError, match=field):
            client.auth.me()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("shortId", 1),
        ("legacyId", True),
        ("legacyId", 1.5),
        ("description", 1),
        ("active", 1),
        ("plan", []),
    ],
)
def test_auth_me_rejects_invalid_tenant_field_types(field: str, value: object) -> None:
    profile = current_user_response()
    tenant = dict(profile["tenant"])  # type: ignore[arg-type]
    tenant[field] = value
    profile["tenant"] = tenant

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=profile))
    ) as http_client:
        client = create_client(config(http_client))

        with pytest.raises(MitraResponseError, match=field):
            client.auth.me()


@pytest.mark.parametrize(
    "plan",
    [
        {},
        {"name": "Free"},
        {"id": "plan-1"},
        {"id": 1, "name": "Free"},
        {"id": "plan-1", "name": 1},
    ],
)
def test_auth_me_rejects_invalid_nested_plan(plan: object) -> None:
    profile = current_user_response()
    tenant = dict(profile["tenant"])  # type: ignore[arg-type]
    tenant["plan"] = plan
    profile["tenant"] = tenant

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=profile))
    ) as http_client:
        client = create_client(config(http_client))

        with pytest.raises(MitraResponseError, match="tenant plan"):
            client.auth.me()


def test_auth_validation_error_does_not_include_invalid_response_values() -> None:
    sensitive_value = "Bearer response-secret"
    profile = current_user_response()
    profile["email"] = {"value": sensitive_value}

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=profile))
    ) as http_client:
        client = create_client(config(http_client))

        with pytest.raises(MitraResponseError, match="invalid email") as caught:
            client.auth.me()

    assert sensitive_value not in str(caught.value)
    assert sensitive_value not in repr(caught.value)


def test_injected_http_client_is_not_closed_by_sdk() -> None:
    http_client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(204)))
    client = create_client(config(http_client))

    client.close()

    assert http_client.is_closed is False
    http_client.close()


def test_context_manager_closes_owned_http_client() -> None:
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token="test-token",
            app_id="app-1",
        )
    )
    owned_client = client._transport._client

    with client as active_client:
        assert active_client is client
        assert owned_client.is_closed is False

    assert owned_client.is_closed is True


def test_dot_segments_are_rejected_before_any_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = create_client(config(http_client, data_source_id="ds-1"))

        for operation in (
            lambda: client.entities.table(" "),
            lambda: client.entities.table(".."),
            lambda: client.entities.table("Orders").get(" "),
            lambda: client.entities.table("Orders").get(".."),
            lambda: client.entities.table("Orders").delete(".."),
            lambda: client.functions.execute(".."),
            lambda: client.functions.get_execution("."),
            lambda: client.queries.execute(".."),
            lambda: client.integration.execute_resource(".."),
            lambda: client.integration.execute(".", {"method": "GET", "endpoint": "/users"}),
        ):
            with pytest.raises(ValueError, match="must not be (?:blank|a dot segment)"):
                operation()

        app_client = create_client(
            MitraClientConfig(
                api_url="https://api.mitra.test",
                access_token="test-token",
                app_id="..",
                http_client=http_client,
            )
        )
        with pytest.raises(ValueError, match="must not be a dot segment"):
            app_client.init()

    assert requests == []


def test_path_segments_preserve_boundary_spaces_and_numeric_zero() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "record"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = create_client(config(http_client))
        spaced = client.entities.table(" Orders ")

        assert spaced.get(" record/1 ") == {"id": "record"}
        assert spaced.get(0) == {"id": "record"}
        assert spaced.get(" .. ") == {"id": "record"}
        assert spaced is client.entities.table(" Orders ")
        assert spaced is not client.entities.table("Orders")

    assert requests[0].url.raw_path == (
        b"/root/data-manager/api/v1/tables/%20Orders%20/records/%20record%2F1%20"
    )
    assert requests[1].url.raw_path.endswith(b"/tables/%20Orders%20/records/0")
    assert requests[2].url.raw_path.endswith(b"/tables/%20Orders%20/records/%20..%20")
