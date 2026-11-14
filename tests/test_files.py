import json
import logging
import traceback
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from mitra_functions_sdk import (
    MitraApiError,
    MitraClient,
    MitraClientConfig,
    MitraFileTransferError,
    MitraNetworkError,
    MitraResponseError,
    create_client,
)

TOKEN = "app-access-token"
STORAGE_HOST = "bucket.s3.test"
UPLOAD_SIGNATURE = "upload-signature-secret"
READ_SIGNATURE = "read-signature-secret"
UPLOAD_URL = (
    f"https://{STORAGE_HOST}/files/tmp/tenant/tenant-1/app/app-1/file-1"
    f"?X-Amz-Credential=key&X-Amz-Signature={UPLOAD_SIGNATURE}"
)
READ_URL = (
    f"https://{STORAGE_HOST}/files/tmp/tenant/tenant-1/app/app-1/file-1"
    f"?versionId=v1&X-Amz-Signature={READ_SIGNATURE}"
)
CONTENT = b"id\n1\n"
FILES_PATH = "/data-manager/api/v1/files"
FILE_PATH = f"{FILES_PATH}/file-1"

Reply = httpx.Response | Exception
Handler = Callable[[httpx.Request], httpx.Response]


def file_metadata(**overrides: object) -> dict[str, object]:
    return {
        "id": "file-1",
        "name": "report.csv",
        "contentType": "text/csv",
        "sizeBytes": len(CONTENT),
        "kind": "TEMPORARY",
        "visibility": "RESTRICTED",
        "status": "READY",
        "ownerUserId": "user-1",
        "createdBy": "USER",
        "createdAt": "2026-11-13T10:00:00Z",
        "confirmedAt": "2026-11-13T10:00:01Z",
        "expiresAt": "2026-11-20T10:00:00Z",
        **overrides,
    }


def upload_response(**overrides: object) -> dict[str, object]:
    return {
        "fileId": "file-1",
        "uploadUrl": UPLOAD_URL,
        "uploadMethod": "PUT",
        "uploadHeaders": {"content-type": "text/csv", "if-none-match": "*"},
        "expiresAt": "2026-11-13T10:05:00Z",
        **overrides,
    }


def api_error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error_code": code, "message": message})


def platform(routes: dict[tuple[str, str], Reply], requests: list[httpx.Request]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        target = "storage" if request.url.host == STORAGE_HOST else request.url.path
        reply = routes.get((request.method, target))
        if reply is None:
            raise AssertionError(f"unexpected request {request.method} {target}")
        if isinstance(reply, Exception):
            raise reply
        return reply

    return handler


def upload_routes(**overrides: Reply) -> dict[tuple[str, str], Reply]:
    routes: dict[tuple[str, str], Reply] = {
        ("POST", FILES_PATH): httpx.Response(201, json=upload_response()),
        ("PUT", "storage"): httpx.Response(200),
        ("POST", f"{FILE_PATH}/confirm"): httpx.Response(200, json=file_metadata()),
        ("DELETE", FILE_PATH): httpx.Response(204),
        ("POST", f"{FILE_PATH}/read-url"): httpx.Response(
            200, json={"url": READ_URL, "expiresAt": "2026-11-13T10:05:00Z"}
        ),
        ("GET", "storage"): httpx.Response(200, content=CONTENT),
    }
    keys = {
        "request": ("POST", FILES_PATH),
        "send": ("PUT", "storage"),
        "confirm": ("POST", f"{FILE_PATH}/confirm"),
        "delete": ("DELETE", FILE_PATH),
        "receive": ("GET", "storage"),
    }
    for step, reply in overrides.items():
        routes[keys[step]] = reply
    return routes


def make_client(handler: Handler, **client_options: Any) -> tuple[MitraClient, httpx.Client]:
    http_client = httpx.Client(transport=httpx.MockTransport(handler), **client_options)
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token=TOKEN,
            app_id="app-1",
            timeout_seconds=4,
            http_client=http_client,
        )
    )
    return client, http_client


def upload_csv(client: MitraClient) -> object:
    return client.files.upload(
        CONTENT,
        name="report.csv",
        content_type="text/csv",
        kind="TEMPORARY",
        visibility="RESTRICTED",
    )


def storage_requests(requests: list[httpx.Request]) -> list[httpx.Request]:
    return [request for request in requests if request.url.host == STORAGE_HOST]


def api_calls(requests: list[httpx.Request]) -> list[tuple[str, str]]:
    return [
        (request.method, request.url.path)
        for request in requests
        if request.url.host != STORAGE_HOST
    ]


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


def sdk_frames(error: BaseException) -> list[traceback.FrameSummary]:
    frames: list[traceback.FrameSummary] = []
    captured: traceback.TracebackException | None = traceback.TracebackException.from_exception(
        error, capture_locals=True
    )
    while captured is not None:
        frames.extend(frame for frame in captured.stack if "mitra_functions_sdk" in frame.filename)
        captured = captured.__cause__ or captured.__context__
    return frames


def assert_no_signed_link(error: BaseException) -> None:
    serialized = serialize_exception(error)
    for secret in (UPLOAD_URL, READ_URL, UPLOAD_SIGNATURE, READ_SIGNATURE, STORAGE_HOST, TOKEN):
        assert secret not in serialized


def test_upload_requests_sends_and_confirms() -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(platform(upload_routes(), requests))

    uploaded = upload_csv(client)

    assert uploaded == file_metadata()
    assert api_calls(requests) == [("POST", FILES_PATH), ("POST", f"{FILE_PATH}/confirm")]
    assert json.loads(requests[0].content) == {
        "name": "report.csv",
        "contentType": "text/csv",
        "sizeBytes": len(CONTENT),
        "kind": "TEMPORARY",
        "visibility": "RESTRICTED",
        "appOwned": False,
    }
    [sent] = storage_requests(requests)
    assert requests.index(sent) == 1
    assert sent.method == "PUT"
    assert str(sent.url) == UPLOAD_URL
    assert sent.content == CONTENT
    http_client.close()


def test_storage_request_uses_the_method_the_api_returned() -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform(
            {
                **upload_routes(
                    request=httpx.Response(201, json=upload_response(uploadMethod="POST"))
                ),
                ("POST", "storage"): httpx.Response(204),
            },
            requests,
        )
    )

    upload_csv(client)

    [sent] = storage_requests(requests)
    assert sent.method == "POST"
    assert sent.content == CONTENT
    http_client.close()


def test_storage_request_carries_only_the_headers_the_api_returned() -> None:
    requests: list[httpx.Request] = []
    hooked_hosts: list[str] = []
    client, http_client = make_client(
        platform(upload_routes(), requests),
        headers={"Authorization": "Bearer client-default", "X-Client-Default": "1"},
        auth=("client-user", "client-password"),
        cookies={"session": "client-cookie"},
        event_hooks={"request": [lambda request: hooked_hosts.append(request.url.host)]},
    )

    upload_csv(client)

    [sent] = storage_requests(requests)
    assert dict(sent.headers) == {
        "host": STORAGE_HOST,
        "content-length": str(len(CONTENT)),
        "content-type": "text/csv",
        "if-none-match": "*",
    }
    assert TOKEN not in str(sent.headers.raw)
    assert TOKEN not in str(sent.url)
    assert sent.extensions["timeout"] == {"connect": 4, "read": 4, "write": 4, "pool": 4}
    assert "api.mitra.test" in hooked_hosts
    assert STORAGE_HOST not in hooked_hosts
    http_client.close()


def test_upload_can_ask_for_a_file_of_the_app_without_an_owner() -> None:
    app_file = file_metadata(
        name="export.bin",
        contentType="application/octet-stream",
        kind="PERMANENT",
        visibility="APP",
        ownerUserId=None,
        createdBy="FUNCTION",
        expiresAt=None,
    )
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform(
            upload_routes(
                request=httpx.Response(
                    201,
                    json=upload_response(
                        uploadHeaders={
                            "content-type": "application/octet-stream",
                            "if-none-match": "*",
                        }
                    ),
                ),
                confirm=httpx.Response(200, json=app_file),
            ),
            requests,
        )
    )

    uploaded = client.files.upload(
        CONTENT,
        name="export.bin",
        kind="PERMANENT",
        visibility="APP",
        app_owned=True,
    )

    assert uploaded == app_file
    assert uploaded["ownerUserId"] is None
    body = json.loads(requests[0].content)
    assert body["appOwned"] is True
    assert body["contentType"] == "application/octet-stream"
    http_client.close()


def test_send_refused_by_storage_deletes_the_pending_file() -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(platform(upload_routes(send=httpx.Response(412)), requests))

    with pytest.raises(MitraFileTransferError) as caught:
        upload_csv(client)

    error = caught.value
    assert error.file_id == "file-1"
    assert error.step == "send"
    assert error.status == 412
    assert error.cleaned_up is True
    assert str(error) == (
        "File file-1 was not sent: storage answered 412; the pending file was deleted"
    )
    assert api_calls(requests) == [("POST", FILES_PATH), ("DELETE", FILE_PATH)]
    assert_no_signed_link(error)
    http_client.close()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"send": httpx.ConnectError(f"cannot connect to {UPLOAD_URL}")},
            "the storage request failed (ConnectError)",
        ),
        (
            {"send": httpx.WriteTimeout(f"timed out writing to {UPLOAD_URL}")},
            "the storage request timed out",
        ),
        (
            {
                "request": httpx.Response(
                    201,
                    json=upload_response(
                        uploadUrl=f"https://{STORAGE_HOST}:port/file-1"
                        f"?X-Amz-Signature={UPLOAD_SIGNATURE}"
                    ),
                )
            },
            "the storage request failed (InvalidURL)",
        ),
    ],
    ids=["connect-error", "timeout", "unparsable-link"],
)
def test_send_that_does_not_reach_storage_hides_the_link_and_cleans_up(
    overrides: dict[str, Reply],
    reason: str,
) -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(platform(upload_routes(**overrides), requests))

    with pytest.raises(MitraFileTransferError) as caught:
        upload_csv(client)

    error = caught.value
    assert str(error) == f"File file-1 was not sent: {reason}; the pending file was deleted"
    assert error.status is None
    assert error.cleaned_up is True
    assert error.__cause__ is None
    assert error.__context__ is None
    assert_no_signed_link(error)
    assert ("DELETE", FILE_PATH) in api_calls(requests)
    http_client.close()


def test_failed_cleanup_is_reported_without_replacing_the_send_failure() -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform(
            upload_routes(
                send=httpx.Response(412),
                delete=api_error(503, "FILE_STORAGE_UNAVAILABLE", "File storage is unavailable"),
            ),
            requests,
        )
    )

    with pytest.raises(MitraFileTransferError) as caught:
        upload_csv(client)

    error = caught.value
    assert error.step == "send"
    assert error.status == 412
    assert error.cleaned_up is False
    assert str(error).endswith("the pending file could not be deleted")
    assert error.__cause__ is None
    assert error.__context__ is None
    http_client.close()


def test_redirect_from_storage_is_refused_and_not_followed() -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform(
            upload_routes(
                send=httpx.Response(307, headers={"Location": "https://elsewhere.test/take"})
            ),
            requests,
        ),
        follow_redirects=True,
    )

    with pytest.raises(MitraFileTransferError) as caught:
        upload_csv(client)

    assert caught.value.status == 307
    assert caught.value.cleaned_up is True
    assert len(storage_requests(requests)) == 1
    assert all(request.url.host != "elsewhere.test" for request in requests)
    http_client.close()


@pytest.mark.parametrize(
    ("confirm_reply", "cause_type", "cause_code"),
    [
        (
            api_error(409, "FILE_NOT_UPLOADED", "File was not uploaded"),
            MitraApiError,
            "FILE_NOT_UPLOADED",
        ),
        (httpx.ReadTimeout("confirmation timed out"), MitraNetworkError, "REQUEST_TIMEOUT"),
    ],
)
def test_failed_confirmation_keeps_the_file_and_names_it(
    confirm_reply: Reply,
    cause_type: type[Exception],
    cause_code: str,
) -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(platform(upload_routes(confirm=confirm_reply), requests))

    with pytest.raises(MitraFileTransferError) as caught:
        upload_csv(client)

    error = caught.value
    assert error.file_id == "file-1"
    assert error.step == "confirm"
    assert error.status is None
    assert error.cleaned_up is False
    assert str(error).startswith("File file-1 was sent but not confirmed: ")
    assert isinstance(error.__cause__, cause_type)
    assert getattr(error.__cause__, "code", None) == cause_code
    assert ("DELETE", FILE_PATH) not in api_calls(requests)
    assert_no_signed_link(error)
    http_client.close()


def test_upload_refused_by_the_api_raises_the_api_error_and_sends_nothing() -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform(
            upload_routes(request=api_error(413, "FILE_TOO_LARGE", "File is too large")),
            requests,
        )
    )

    with pytest.raises(MitraApiError) as caught:
        upload_csv(client)

    assert caught.value.status == 413
    assert caught.value.code == "FILE_TOO_LARGE"
    assert api_calls(requests) == [("POST", FILES_PATH)]
    assert storage_requests(requests) == []
    http_client.close()


@pytest.mark.parametrize(
    "response",
    [
        upload_response(uploadHeaders={"content-type": 1}),
        upload_response(uploadHeaders=None),
        upload_response(uploadUrl=None),
        upload_response(uploadMethod=1),
        {key: value for key, value in upload_response().items() if key != "fileId"},
    ],
)
def test_invalid_upload_response_is_rejected_before_sending(response: object) -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform(upload_routes(request=httpx.Response(201, json=response)), requests)
    )

    with pytest.raises(MitraResponseError):
        upload_csv(client)

    assert storage_requests(requests) == []
    http_client.close()


@pytest.mark.parametrize("content", ["id\n1\n", bytearray(CONTENT)])
def test_upload_requires_bytes_before_any_request(content: object) -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(platform(upload_routes(), requests))

    with pytest.raises(TypeError, match="content must be bytes"):
        client.files.upload(
            content,  # type: ignore[arg-type]
            name="report.csv",
            kind="TEMPORARY",
            visibility="PRIVATE",
        )

    assert requests == []
    http_client.close()


def test_get_returns_metadata_with_the_encoded_id() -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform(
            {("GET", f"{FILES_PATH}/file/1"): httpx.Response(200, json=file_metadata())},
            requests,
        )
    )

    assert client.files.get("file/1") == file_metadata()
    assert requests[0].url.raw_path == b"/data-manager/api/v1/files/file%2F1"
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"
    http_client.close()


def test_get_accepts_null_fields_and_values_added_later() -> None:
    response = file_metadata(
        status="ARCHIVED",
        ownerUserId=None,
        confirmedAt=None,
        expiresAt=None,
        futureField=True,
    )
    client, http_client = make_client(
        platform({("GET", FILE_PATH): httpx.Response(200, json=response)}, [])
    )

    assert client.files.get("file-1") == response
    http_client.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", None),
        ("name", 1),
        ("contentType", None),
        ("sizeBytes", "5"),
        ("sizeBytes", True),
        ("kind", None),
        ("visibility", 1),
        ("status", None),
        ("ownerUserId", 1),
        ("createdBy", None),
        ("createdAt", None),
        ("confirmedAt", 1),
        ("expiresAt", {}),
    ],
)
def test_get_rejects_invalid_metadata(field: str, value: object) -> None:
    client, http_client = make_client(
        platform(
            {("GET", FILE_PATH): httpx.Response(200, json=file_metadata(**{field: value}))},
            [],
        )
    )

    with pytest.raises(MitraResponseError, match=field):
        client.files.get("file-1")
    http_client.close()


def test_get_rejects_metadata_without_a_nullable_field() -> None:
    response = {key: value for key, value in file_metadata().items() if key != "ownerUserId"}
    client, http_client = make_client(
        platform({("GET", FILE_PATH): httpx.Response(200, json=response)}, [])
    )

    with pytest.raises(MitraResponseError, match="ownerUserId"):
        client.files.get("file-1")
    http_client.close()


def test_get_url_returns_the_short_lived_link() -> None:
    requests: list[httpx.Request] = []
    read_url = {"url": READ_URL, "expiresAt": "2026-11-13T10:05:00Z"}
    client, http_client = make_client(
        platform({("POST", f"{FILE_PATH}/read-url"): httpx.Response(200, json=read_url)}, requests)
    )

    assert client.files.get_url("file-1") == read_url
    assert requests[0].content == b""
    http_client.close()


def test_download_reads_the_signed_link_without_credentials() -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform(
            {
                ("POST", f"{FILE_PATH}/read-url"): httpx.Response(
                    200, json={"url": READ_URL, "expiresAt": "2026-11-13T10:05:00Z"}
                ),
                ("GET", "storage"): httpx.Response(200, content=CONTENT),
            },
            requests,
        ),
        headers={"Authorization": "Bearer client-default"},
    )

    assert client.files.download("file-1") == CONTENT
    [received] = storage_requests(requests)
    assert str(received.url) == READ_URL
    assert dict(received.headers) == {"host": STORAGE_HOST}
    http_client.close()


class BodyCutMidway(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield CONTENT[:2]
        raise httpx.ReadError(f"connection reset reading {READ_URL}")


@pytest.mark.parametrize(
    ("storage_reply", "status", "reason"),
    [
        (httpx.Response(403, text=f"<Error>{READ_URL}</Error>"), 403, "storage answered 403"),
        (
            httpx.Response(200, stream=BodyCutMidway()),
            None,
            "the storage request failed (ReadError)",
        ),
    ],
    ids=["refused", "cut-midway"],
)
def test_failed_download_names_the_file_closes_the_response_and_hides_the_link(
    storage_reply: httpx.Response,
    status: int | None,
    reason: str,
) -> None:
    client, http_client = make_client(
        platform(
            {
                ("POST", f"{FILE_PATH}/read-url"): httpx.Response(
                    200, json={"url": READ_URL, "expiresAt": "2026-11-13T10:05:00Z"}
                ),
                ("GET", "storage"): storage_reply,
            },
            [],
        )
    )

    with pytest.raises(MitraFileTransferError) as caught:
        client.files.download("file-1")

    error = caught.value
    assert str(error) == f"File file-1 was not downloaded: {reason}"
    assert error.step == "download"
    assert error.status == status
    assert error.cleaned_up is False
    assert error.__cause__ is None
    assert error.__context__ is None
    assert storage_reply.is_closed
    assert_no_signed_link(error)
    http_client.close()


@pytest.mark.parametrize(
    ("read_url_reply", "error_type", "code"),
    [
        (api_error(404, "NOT_FOUND", "Resource not found"), MitraApiError, "NOT_FOUND"),
        (
            httpx.Response(200, json={"expiresAt": "2026-11-13T10:05:00Z"}),
            MitraResponseError,
            "INVALID_RESPONSE",
        ),
        (httpx.Response(200, json={"url": READ_URL}), MitraResponseError, "INVALID_RESPONSE"),
    ],
    ids=["not-found", "answer-without-link", "answer-without-expiry"],
)
def test_download_without_a_link_raises_without_touching_storage(
    read_url_reply: httpx.Response,
    error_type: type[Exception],
    code: str,
) -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform({("POST", f"{FILE_PATH}/read-url"): read_url_reply}, requests)
    )

    with pytest.raises(error_type) as caught:
        client.files.download("file-1")

    assert getattr(caught.value, "code", None) == code
    assert storage_requests(requests) == []
    http_client.close()


def test_delete_expects_an_empty_answer() -> None:
    requests: list[httpx.Request] = []
    client, http_client = make_client(
        platform({("DELETE", FILE_PATH): httpx.Response(204)}, requests)
    )

    assert client.files.delete("file-1") is None
    assert api_calls(requests) == [("DELETE", FILE_PATH)]
    http_client.close()


def test_delete_rejects_a_body_where_none_is_expected() -> None:
    client, http_client = make_client(
        platform({("DELETE", FILE_PATH): httpx.Response(200, json={"deleted": True})}, [])
    )

    with pytest.raises(MitraResponseError, match="Delete file response must be empty"):
        client.files.delete("file-1")
    http_client.close()


def test_signed_links_never_reach_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client, http_client = make_client(platform(upload_routes(), []))

    upload_csv(client)
    client.files.download("file-1")

    # The API calls are logged by httpx, so the capture works and the links are absent on purpose.
    # The host is not asserted: with a real transport httpcore logs it at DEBUG, without the path.
    assert f"POST https://api.mitra.test{FILES_PATH}" in caplog.text
    for link in (httpx.URL(UPLOAD_URL), httpx.URL(READ_URL)):
        assert link.path not in caplog.text
        assert link.query.decode() not in caplog.text
    for signature in (UPLOAD_SIGNATURE, READ_SIGNATURE):
        assert signature not in caplog.text
    http_client.close()


@pytest.mark.parametrize(
    ("overrides", "operation", "raising_frame"),
    [
        (
            {"send": httpx.ConnectError(f"cannot connect to {UPLOAD_URL}")},
            upload_csv,
            "upload",
        ),
        (
            {"confirm": api_error(409, "FILE_NOT_UPLOADED", "File was not uploaded")},
            upload_csv,
            "upload",
        ),
        (
            {"receive": httpx.Response(403)},
            lambda client: client.files.download("file-1"),
            "download",
        ),
    ],
)
def test_signed_link_is_not_in_the_locals_of_any_sdk_frame(
    overrides: dict[str, Reply],
    operation: Callable[[MitraClient], object],
    raising_frame: str,
) -> None:
    client, http_client = make_client(platform(upload_routes(**overrides), []))

    with pytest.raises(MitraFileTransferError) as caught:
        operation(client)

    frames = sdk_frames(caught.value)
    assert raising_frame in {frame.name for frame in frames}
    captured_locals = json.dumps([frame.locals for frame in frames])
    assert "file_id" in captured_locals
    for secret in (UPLOAD_URL, READ_URL, UPLOAD_SIGNATURE, READ_SIGNATURE):
        assert secret not in captured_locals
    http_client.close()


def test_storage_request_goes_through_the_transport_mounted_for_the_storage_host() -> None:
    api_requests: list[httpx.Request] = []
    mounted_requests: list[httpx.Request] = []

    def api_only(request: httpx.Request) -> httpx.Response:
        if request.url.host == STORAGE_HOST:
            raise AssertionError("the storage request skipped the transport mounted for its host")
        return platform(upload_routes(), api_requests)(request)

    def storage(request: httpx.Request) -> httpx.Response:
        mounted_requests.append(request)
        return httpx.Response(200)

    http_client = httpx.Client(
        transport=httpx.MockTransport(api_only),
        mounts={f"https://{STORAGE_HOST}": httpx.MockTransport(storage)},
    )
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token=TOKEN,
            app_id="app-1",
            http_client=http_client,
        )
    )

    upload_csv(client)

    assert [str(request.url) for request in mounted_requests] == [UPLOAD_URL]
    assert api_calls(api_requests) == [("POST", FILES_PATH), ("POST", f"{FILE_PATH}/confirm")]
    http_client.close()
