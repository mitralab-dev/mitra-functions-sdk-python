import json
import math
import traceback

import httpx
import pytest

import mitra_functions_sdk
from mitra_functions_sdk import (
    MitraClient,
    MitraClientConfig,
    MitraConfigError,
    create_client,
    create_client_from_environment,
)


def test_config_normalizes_values_and_hides_secrets() -> None:
    http_client = httpx.Client()
    config = MitraClientConfig(
        api_url=" https://api.mitra.test/ ",
        access_token=" secret-token ",
        app_id=" app-1 ",
        data_source_id=" data-source-1 ",
        http_client=http_client,
    )

    assert config.api_url == "https://api.mitra.test"
    assert config.access_token == "secret-token"
    assert config.app_id == "app-1"
    assert config.data_source_id == "data-source-1"
    assert "secret-token" not in repr(config)
    assert "access_token" not in repr(config)
    assert "http_client" not in repr(config)
    http_client.close()


@pytest.mark.parametrize(
    "api_url",
    [
        "",
        "api.mitra.test",
        "ftp://api.mitra.test",
        "https://user:password@api.mitra.test",
        "https://api.mitra.test?debug=true",
        "https://api.mitra.test?",
        "https://api.mitra.test#fragment",
        "https://api.mitra.test#",
        "https://api .mitra.test",
        "https://api.mitra.test/\npath",
        "https://api.mitra.test/\x00path",
        "https://api.mitra.test:not-a-port",
        "https://api.mitra.test:",
        "https://api.mitra.test:0",
        "https://api.mitra.test:-1",
        "https://api.mitra.test:+1",
        "https://api.mitra.test:65536",
        "https://api.mitra.test:99999",
        "https://[invalid-ipv6]",
        "https://[::1",
        "https://bad_host.test",
        "https://-bad.test",
        "https://bad-.test",
        "https://bad..test",
        "https://999.999.999.999",
    ],
)
def test_config_rejects_invalid_api_url(api_url: str) -> None:
    requests: list[httpx.Request] = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(204)
        )
    ) as http_client:
        with pytest.raises(MitraConfigError, match="api_url") as caught:
            MitraClientConfig(
                api_url=api_url,
                access_token="token",
                app_id="app-1",
                http_client=http_client,
            )

    error = caught.value
    serialized = json.dumps(
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
    assert type(error) is MitraConfigError
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "InvalidURL" not in serialized
    assert requests == []


@pytest.mark.parametrize(
    ("api_url", "expected"),
    [
        ("https://api.mitra.test/root/path/", "https://api.mitra.test/root/path"),
        (" https://api.mitra.test/root/path/ ", "https://api.mitra.test/root/path"),
        ("http://localhost:8000/root", "http://localhost:8000/root"),
        ("https://api.mitra.test:1/root", "https://api.mitra.test:1/root"),
        ("https://api.mitra.test:65535/root", "https://api.mitra.test:65535/root"),
        ("https://[::1]:8443/root", "https://[::1]:8443/root"),
        ("https://münchen.example/root", "https://xn--mnchen-3ya.example/root"),
    ],
)
def test_config_preserves_valid_base_paths(api_url: str, expected: str) -> None:
    config = MitraClientConfig(api_url=api_url, access_token="token", app_id="app-1")

    assert config.api_url == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_token", " "),
        ("app_id", ""),
        ("data_source_id", "\t"),
    ],
)
def test_config_rejects_blank_values(field: str, value: str) -> None:
    values: dict[str, object] = {
        "api_url": "https://api.mitra.test",
        "access_token": "token",
        "app_id": "app-1",
    }
    values[field] = value

    with pytest.raises(MitraConfigError, match=field):
        MitraClientConfig(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf, -math.inf])
def test_config_rejects_invalid_timeout(timeout: float) -> None:
    with pytest.raises(MitraConfigError, match="timeout_seconds"):
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token="token",
            app_id="app-1",
            timeout_seconds=timeout,
        )


def test_environment_accepts_the_names_the_functions_runtime_injects() -> None:
    config = MitraClientConfig.from_environment(
        {
            "MITRA_BASE_URL": "https://api.mitra.test/legacy",
            "MITRA_TOKEN": "runtime-token",
            "MITRA_PROJECT_ID": "app-1",
        }
    )

    assert config.api_url == "https://api.mitra.test"
    assert config.access_token == "runtime-token"
    assert config.app_id == "app-1"


def test_environment_prefers_canonical_names_over_runtime_names() -> None:
    client = create_client_from_environment(
        {
            "MITRA_API_URL": "https://api.mitra.test",
            "MITRA_PLATFORM_ACCESS_TOKEN": "token",
            "MITRA_APP_ID": "app-1",
            "MITRA_DATA_SOURCE_ID": "data-source-1",
            "MITRA_BASE_URL": "https://legacy.test/legacy",
            "MITRA_PROJECT_ID": "legacy-project",
            "MITRA_TOKEN": "legacy-token",
        }
    )

    assert client.config.api_url == "https://api.mitra.test"
    assert client.config.access_token == "token"
    assert client.config.app_id == "app-1"
    assert client.data_source_id == "data-source-1"
    client.close()


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.mitra.test/legacy/", "https://api.mitra.test"),
        ("https://api.mitra.test/root/legacy", "https://api.mitra.test/root"),
        ("https://api.mitra.test/root", "https://api.mitra.test/root"),
        ("https://api.mitra.test/notlegacy", "https://api.mitra.test/notlegacy"),
        ("https://legacy", "https://legacy"),
    ],
)
def test_environment_removes_only_a_trailing_legacy_segment(base_url: str, expected: str) -> None:
    config = MitraClientConfig.from_environment(
        {"MITRA_BASE_URL": base_url, "MITRA_TOKEN": "token", "MITRA_PROJECT_ID": "app-1"}
    )

    assert config.api_url == expected


def test_environment_rejects_invalid_runtime_base_url() -> None:
    with pytest.raises(MitraConfigError, match="api_url"):
        MitraClientConfig.from_environment(
            {
                "MITRA_BASE_URL": "https://user:password@api.mitra.test/legacy",
                "MITRA_TOKEN": "token",
                "MITRA_PROJECT_ID": "app-1",
            }
        )


def test_blank_canonical_name_does_not_fall_back_to_runtime_name() -> None:
    with pytest.raises(MitraConfigError) as caught:
        MitraClientConfig.from_environment(
            {
                "MITRA_API_URL": " ",
                "MITRA_BASE_URL": "https://api.mitra.test/legacy",
                "MITRA_PLATFORM_ACCESS_TOKEN": "",
                "MITRA_TOKEN": "runtime-token",
                "MITRA_APP_ID": "app-1",
            }
        )

    assert "MITRA_API_URL (or MITRA_BASE_URL)" in str(caught.value)
    assert "MITRA_PLATFORM_ACCESS_TOKEN (or MITRA_TOKEN)" in str(caught.value)
    assert "MITRA_APP_ID" not in str(caught.value)
    assert "runtime-token" not in str(caught.value)


def test_create_client_without_config_reads_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("MITRA_API_URL", "MITRA_PLATFORM_ACCESS_TOKEN", "MITRA_APP_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MITRA_BASE_URL", "https://api.mitra.test/legacy")
    monkeypatch.setenv("MITRA_TOKEN", "token")
    monkeypatch.setenv("MITRA_PROJECT_ID", "app-1")

    client = create_client()

    assert isinstance(client, MitraClient)
    assert client.config.api_url == "https://api.mitra.test"
    assert client.config.app_id == "app-1"
    client.close()


def test_environment_reports_all_missing_required_variables() -> None:
    with pytest.raises(MitraConfigError) as caught:
        create_client_from_environment({"MITRA_TOKEN": " ", "MITRA_BASE_URL": ""})

    assert str(caught.value) == (
        "Missing required environment variables: MITRA_API_URL (or MITRA_BASE_URL), "
        "MITRA_PLATFORM_ACCESS_TOKEN (or MITRA_TOKEN), MITRA_APP_ID (or MITRA_PROJECT_ID)"
    )


def test_public_exports_are_complete() -> None:
    expected = {
        "CurrentUser",
        "DeleteManyResult",
        "FunctionExecution",
        "MitraApiError",
        "MitraClient",
        "MitraClientConfig",
        "MitraConfigError",
        "MitraNetworkError",
        "MitraResponseError",
        "MitraSdkError",
        "Plan",
        "ProxyInput",
        "ProxyResult",
        "QueryResult",
        "Record",
        "Tenant",
        "create_client",
        "create_client_from_environment",
    }

    assert set(mitra_functions_sdk.__all__) == expected
    assert all(hasattr(mitra_functions_sdk, name) for name in mitra_functions_sdk.__all__)
